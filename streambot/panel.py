"""Conservative, form-driven reseller panel connector.

No HTTP retries are installed. Unknown panel shapes are errors, never evidence
that an account does not exist. No response bodies or credentials are logged.
"""
from __future__ import annotations

import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


class PanelError(RuntimeError):
    """The panel could not be read safely, or a precondition failed."""


class ProvisioningUncertain(PanelError):
    """A create may have reached the panel; reconcile instead of retrying."""

    def __init__(self, message, reason='confirmation_failed'):
        super().__init__(message)
        self.reason = reason if re.fullmatch(r'[a-z0-9_]{1,40}',reason) else 'confirmation_failed'


class CreationDisabled(PanelError):
    """Account creation was not explicitly enabled."""


class PanelClient:
    def __init__(self, base_url, username, password, allow_create=False, session=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password:
            raise PanelError('Invalid panel base URL')
        self.base_url = base_url.rstrip('/') + '/'
        self._username, self._password = username, password
        self.allow_create = allow_create
        self.session = session if session is not None else requests.Session()
        self._authenticated = False

    def _url(self, path):
        url = urljoin(self.base_url, path)
        if urlsplit(url)[:2] != urlsplit(self.base_url)[:2]:
            raise PanelError('Panel endpoint is outside the configured origin')
        return url

    def _request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, self._url(path), timeout=(10, 30), **kwargs)
        except requests.RequestException:
            raise PanelError('Panel request failed') from None
        if response.status_code >= 400:
            error = PanelError('Panel returned an unsuccessful response')
            error.http_status = response.status_code
            raise error
        if getattr(response, 'url', ''):
            self._url(response.url)
        return response

    @staticmethod
    def _soup(response):
        return BeautifulSoup(response.text, 'html.parser')

    @staticmethod
    def _token(soup):
        token = soup.select_one('input[name="_token"]')
        if token and token.get('value'):
            return token['value']
        token = soup.select_one('meta[name="csrf-token"]')
        if token and token.get('content'):
            return token['content']
        raise PanelError('Panel CSRF token not found')

    @staticmethod
    def _is_login(response):
        soup = BeautifulSoup(response.text, 'html.parser')
        for form in soup.find_all('form'):
            if form.select_one('input[name="password"]') and form.select_one('input[name="username"]'):
                action = urlsplit(form.get('action','')).path.rstrip('/')
                page = urlsplit(getattr(response,'url','')).path.rstrip('/')
                if action in ('','/login') and page not in ('/lines/create/0/line',):
                    return True
        return False

    def _login(self):
        if self._authenticated:
            return
        response = self._request('GET', '/')
        token = self._token(self._soup(response))
        response = self._request('POST', '/', data={
            '_token': token, 'username': self._username, 'password': self._password}, allow_redirects=False)
        if response.status_code in (301, 302, 303):
            location = response.headers.get('Location')
            if not location:
                raise PanelError('Panel login redirect has no destination')
            response = self._request('GET', self._url(location), allow_redirects=False)
        if response.status_code >= 300:
            raise PanelError('Panel login redirect could not be confirmed')
        if self._is_login(response) or urlsplit(response.url).path.rstrip('/') != '/dashboard':
            raise PanelError('Panel login was not confirmed')
        self._authenticated = True

    def _read(self, path, **kwargs):
        self._login()
        response = self._request('GET', path, **kwargs)
        if self._is_login(response):
            self._authenticated = False
            raise PanelError('Panel session expired')
        return response

    def _create_form(self):
        response = self._read('/lines/create/0/line')
        soup = self._soup(response)
        package = soup.select_one('select[name="package"]')
        form = package.find_parent('form') if package else None
        if not form or form.get('method', '').upper() != 'POST':
            raise PanelError('Unrecognized panel creation form')
        action = self._url(form.get('action', ''))
        if urlsplit(action).path.rstrip('/') != '/lines/create/0':
            raise PanelError('Unrecognized panel creation action')
        required = {'username', 'password', 'line_type', 'package', 'current_bouquets',
                    'connections', 'expire_date', 'price', 'credits_left',
                    'bouquets_main[]', 'bouquets[]', 'description'}
        if not required.issubset({x.get('name') for x in form.select('[name]')}):
            raise PanelError('Panel creation form is missing expected fields')
        self._token(soup)
        return soup, form, action

    @staticmethod
    def _packages(form):
        return [{'id': str(option['value']), 'label': option.get_text(' ', strip=True)}
                for option in form.select('select[name="package"] option[value]')
                if option['value'] and not option.has_attr('disabled')]

    def inspect_packages(self):
        _, form, _ = self._create_form()
        packages = self._packages(form)
        if not packages:
            raise PanelError('No panel packages found')
        return packages

    @staticmethod
    def _ajax(soup, endpoint=None):
        """Read literal AJAX routes without evaluating panel JavaScript."""
        scripts = '\n'.join(s.get_text() for s in soup.find_all('script'))
        starts = r"(?:[\"']?ajax[\"']?\s*:\s*|\$\s*\.\s*ajax\s*\(\s*)\{"
        if endpoint is None:
            # The DataTable ajax declaration, rather than unrelated $.ajax calls.
            starts = r"[\"']?ajax[\"']?\s*:\s*\{"
        candidates = []
        for declaration in re.finditer(starts, scripts):
            depth, quote, escaped, end = 1, None, False, declaration.end()
            while end < len(scripts) and depth:
                char = scripts[end]
                if quote:
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == quote:
                        quote = None
                elif char in "\"'`":
                    quote = char
                elif char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                end += 1
            if depth:
                raise PanelError('Unterminated panel AJAX declaration')
            block = scripts[declaration.end():end - 1]
            routes = list(re.finditer(r"[\"']?url[\"']?\s*:\s*(?:base\s*\+\s*)?(['\"])([^'\"]+)\1", block))
            if len(routes) != 1:
                continue
            route = routes[0].group(2)
            if endpoint and urlsplit(route).path != endpoint:
                continue
            methods = re.findall(r"[\"']?(?:type|method)[\"']?\s*:\s*['\"](GET|POST)['\"]", block, re.I)
            if len(methods) > 1 or (endpoint and not methods):
                raise PanelError('Panel AJAX HTTP method is unknown')
            candidates.append((route, methods[0].upper() if methods else 'GET'))
        if len(candidates) != 1:
            raise PanelError('Cannot identify a unique panel AJAX endpoint')
        return candidates[0][0], candidates[0][1], scripts

    @staticmethod
    def _normalize(row):
        if not isinstance(row, dict):
            raise PanelError('Unrecognized panel account record')
        username = row.get('username')
        if not isinstance(username, str) or '<' in username:
            raise PanelError('Account username is not an explicit text field')
        result = {'username': username}
        for target, aliases in {
            'panel_id': ('id',),
            'password': ('password',), 'package_id': ('package_id', 'package'),
            'server_url': ('server_url',), 'expires_at': ('expires_at', 'expire_date', 'exp_date'),
        }.items():
            for key in aliases:
                if key in row and isinstance(row[key], (str, int)):
                    result[target] = str(row[key])
                    break
        return result

    def find_account(self, username):
        matches = [account for account in self._account_rows(username) if account['username']==username]
        if len(matches)>1:
            raise PanelError('Multiple panel accounts have the same username')
        return matches[0] if matches else None

    def _account_rows(self, username=''):
        response = self._read('/lines')
        soup = self._soup(response)
        endpoint, method, script = self._ajax(soup)
        if method == 'POST' and urlsplit(self._url(endpoint)).path != '/lines/data':
            raise PanelError('Unrecognized read-only panel listing endpoint')
        self._url(endpoint)
        column_match = re.search(r'[\"\']?columns[\"\']?\s*:\s*\[(.*?)\]', script, re.S)
        column_blocks = re.findall(r'\{([^{}]+)\}', column_match.group(1)) if column_match else []
        column_specs = []
        for block in column_blocks:
            field = re.search(r"[\"']?data[\"']?\s*:\s*['\"]([\w]+)['\"]", block)
            name = re.search(r"[\"']?name[\"']?\s*:\s*['\"]([\w.]+)['\"]", block)
            if not field:
                raise PanelError('Unrecognized panel DataTable column')
            column_specs.append((field.group(1), name.group(1) if name else '',
                                 not bool(re.search(r'[\"\']?searchable[\"\']?\s*:\s*false', block))))
        columns = [spec[0] for spec in column_specs]
        params = {'draw': 1, 'start': 0, 'length': 100,
                  'search[value]': username, 'search[regex]': 'false'}
        for index, (column, name, searchable) in enumerate(column_specs):
            params[f'columns[{index}][data]'] = column
            params[f'columns[{index}][name]'] = name
            params[f'columns[{index}][searchable]'] = str(searchable).lower()
            params[f'columns[{index}][orderable]'] = 'false'
            params[f'columns[{index}][search][value]'] = ''
            params[f'columns[{index}][search][regex]'] = 'false'
        total, seen, accounts = None, 0, []
        fingerprints = set()
        for _ in range(100):
            if method == 'GET':
                response = self._read(endpoint, params=dict(params))
            else:
                query = dict(params, id='users', filter='', reseller='')
                headers = {'X-Requested-With': 'XMLHttpRequest'}
                try:
                    headers['X-CSRF-TOKEN'] = self._token(soup)
                except PanelError:
                    pass
                response = self._request('POST', endpoint, data=query, headers=headers, allow_redirects=False)
                if response.status_code >= 300 or self._is_login(response):
                    raise PanelError('Panel listing session expired')
            try:
                payload = response.json()
                rows = payload['data']
                count = payload['recordsFiltered']
                if isinstance(count, bool) or int(count) != float(count) or int(count) < 0 or not isinstance(rows, list):
                    raise ValueError()
                count = int(count)
            except (ValueError, KeyError, TypeError, OverflowError):
                raise PanelError('Panel listing lacks reliable filtered counts') from None
            if total is not None and count != total:
                raise PanelError('Panel listing changed during lookup')
            total = count
            for row in rows:
                if isinstance(row, list):
                    if not columns or len(row) != len(columns):
                        raise PanelError('Unrecognized panel listing columns')
                    row = dict(zip(columns, row))
                account = self._normalize(row)
                fingerprint = json.dumps(row, sort_keys=True)
                if fingerprint in fingerprints:
                    raise PanelError('Panel listing repeated a record')
                fingerprints.add(fingerprint)
                accounts.append(account)
            seen += len(rows)
            if seen == total:
                return accounts
            if not rows or seen > total:
                raise PanelError('Panel listing is incomplete')
            params['start'] = seen
            params['draw'] += 1
        raise PanelError('Panel listing exceeded safe pagination limit')

    def account_snapshot(self):
        result = {}
        for account in self._account_rows():
            panel_id = account.get('panel_id','')
            if not re.fullmatch(r'[1-9][0-9]*',panel_id) or panel_id in result:
                raise PanelError('Panel account IDs are missing or ambiguous')
            result[panel_id] = account
        return result

    def prepare_generation(self, package_id):
        return dict(generation_mode='panel',package_id=str(package_id),
                    before_ids=sorted(self.account_snapshot()),prepared_at=int(time.time()),
                    post_attempted=True)

    def generated_account(self, generation):
        before = set(generation['before_ids'])
        after = self.account_snapshot()
        new = set(after)-before
        if not before.issubset(after) or len(new)!=1:
            raise PanelError('Generated account cannot be identified unambiguously')
        panel_id = new.pop()
        return self.verify_account(after[panel_id],generation['package_id'])

    def verify_account(self, listed, package_id=None):
        panel_id = listed.get('panel_id','')
        if not isinstance(panel_id,str) or not re.fullmatch(r'[1-9][0-9]*',panel_id):
            raise PanelError('Panel account ID is invalid')
        response = self._read('/lines/edit/'+panel_id)
        if urlsplit(response.url).path.rstrip('/')!='/lines/edit/'+panel_id:
            raise PanelError('Generated account details redirected unexpectedly')
        form = self._soup(response).select_one('form.pro-ajax')
        if form is None:
            raise PanelError('Generated account details form is missing')
        result = {'panel_id':panel_id}
        if package_id is not None: result['package_id']=str(package_id)
        for key in ('username','password'):
            field = form.select_one('input[name="'+key+'"]')
            value = field.get('value') if field else None
            if not isinstance(value,str) or not value or value!=listed.get(key):
                raise PanelError('Generated credentials could not be verified')
            result[key] = value
        description = form.select_one('textarea[name="description"]')
        # The panel renders its own "-" placeholder for an empty description.
        if description is None or description.get_text().strip() not in ('','-'):
            raise PanelError('Generated account has unexpected notes')
        for key in ('expires_at','server_url'):
            if listed.get(key): result[key]=listed[key]
        return result

    @staticmethod
    def _form_data(form):
        data = {}
        for field in form.select('input[name],select[name],textarea[name]'):
            if field.has_attr('disabled'):
                continue
            name = field['name']
            kind = field.get('type', 'text').lower()
            if kind in ('submit', 'button', 'reset', 'file'):
                continue
            if kind in ('checkbox', 'radio') and not field.has_attr('checked'):
                continue
            if field.name == 'select':
                selected = field.select('option[selected]')
                if field.has_attr('multiple'):
                    data[name] = [o.get('value', o.get_text()) for o in selected]
                    continue
                selected = selected or field.select('option')[:1]
                data[name] = selected[0].get('value', selected[0].get_text()) if selected else ''
            elif field.name == 'textarea':
                data[name] = field.get_text()
            else:
                data[name] = field.get('value', 'on' if kind in ('checkbox', 'radio') else '')
        return data

    def _package_details(self, soup, package_id):
        endpoint, method, script = self._ajax(soup, '/lines/packages')
        if not re.search(r"[\"']?trial[\"']?\s*:\s*['\"]?0", script) or 'package_id' not in script:
            raise PanelError('Unrecognized package details parameters')
        params = {'package_id': str(package_id), 'trial': '0'}
        if method == 'GET':
            response = self._read(endpoint, params=params)
        else:
            # This is the observed metadata-only POST endpoint, never creation.
            if urlsplit(self._url(endpoint)).path != '/lines/packages':
                raise PanelError('Unrecognized package metadata route')
            params['_token'] = self._token(soup)
            response = self._request('POST', endpoint, data=params, headers={
                'X-Requested-With': 'XMLHttpRequest', 'X-CSRF-TOKEN': self._token(soup),
                'Referer': self._url('/lines/create/0/line')}, allow_redirects=False)
            if response.status_code >= 300 or self._is_login(response):
                raise PanelError('Package metadata request was not confirmed')
        try:
            payload = response.json()
        except ValueError:
            raise PanelError('Package details must be explicit JSON') from None
        if not isinstance(payload, dict):
            raise PanelError('Unrecognized package details response')
        return payload

    @staticmethod
    def _matches(account, package_id, username, password):
        return (account is not None and account.get('username') == username and
                account.get('password') == password and
                ('package_id' not in account or account['package_id'] == str(package_id)))

    def create_account(self, package_id, username='', password='', description='', *, generation=None):
        if not self.allow_create:
            raise CreationDisabled('Panel account creation is disabled')
        if username!='' or password!='' or description!='':
            raise PanelError('New panel accounts require empty credentials and description')
        generation = generation if generation is not None else self.prepare_generation(package_id)
        if (generation.get('generation_mode')!='panel' or generation.get('package_id')!=str(package_id)
                or not isinstance(generation.get('before_ids'),list)
                or any(not isinstance(x,str) or not re.fullmatch(r'[1-9][0-9]*',x) for x in generation['before_ids'])
                or len(set(generation['before_ids']))!=len(generation['before_ids'])
                or type(generation.get('prepared_at')) is not int
                or not -5<=time.time()-generation['prepared_at']<=120):
            raise PanelError('Panel generation snapshot is invalid or expired')
        soup, form, action = self._create_form()
        if str(package_id) not in {p['id'] for p in self._packages(form)}:
            raise PanelError('Requested package is not available on the panel')
        data = self._form_data(form)
        if not data.get('credits_left'):
            scripts = '\n'.join(s.get_text() for s in soup.find_all('script'))
            balances = re.findall(r'\b(?:var|let|const)\s+currentCredits\s*=\s*(\d+(?:\.\d+)?)\s*-\s*credits\b', scripts)
            if len(balances) != 1:
                raise PanelError('Current panel credit balance is unknown')
            data['credits_left'] = balances[0]
        details = self._package_details(soup, package_id)
        if details.get('result') is True and isinstance(details.get('data'), dict):
            option = form.find('select', attrs={'name': 'package'}).find('option', attrs={'value': str(package_id)})
            try:
                price = Decimal(option['data-credits'])
                remaining = Decimal(str(data['credits_left'])) - price
                details = {'bouquets': [str(item['id']) for item in details['bouquets']],
                           'connections': details['data']['max_connections'],
                           'expire_date': details['data']['exp_date'],
                           'price': str(price), 'credits_left': str(remaining)}
            except (KeyError, TypeError, InvalidOperation):
                raise PanelError('Package metadata or credit balance is incomplete') from None
        required = {'bouquets', 'connections', 'expire_date', 'price', 'credits_left'}
        if not required.issubset(details):
            raise PanelError('Package metadata is missing required provisioning fields')
        bouquets = details['bouquets']
        if not isinstance(bouquets, list) or not bouquets or any(not isinstance(x, (str, int)) for x in bouquets):
            raise PanelError('Package bouquet selection is unknown')
        bouquets = list(map(str, bouquets))
        if any(not re.fullmatch(r'[0-9]+',item) for item in bouquets):
            raise PanelError('Package bouquet selection is unknown')
        try:
            remaining = Decimal(str(details['credits_left']))
            price = Decimal(str(details['price']))
            current = Decimal(str(data['credits_left']))
            if not all(x.is_finite() for x in (remaining, price, current)) or min(remaining, price, current) < 0 or price > current:
                raise ValueError()
            connections = int(details['connections'])
            if connections <= 0:
                raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise PanelError('Panel credits or package limits do not permit creation') from None
        data.update({key: str(details[key]) for key in required - {'bouquets'}})
        data.update({'_token': self._token(soup), 'package': str(package_id), 'username': username,
                     'password': password, 'description': description, 'line_type': 'line',
                     'bouquets[]': list(map(str, bouquets)), 'bouquets_main[]': list(map(str, bouquets)),
                     'current_bouquets': ','.join(bouquets)})
        # Once this call begins, every failure is uncertain. Never submit it again.
        try:
            response = self._request('POST', action, data=data, allow_redirects=False,headers={
                'X-Requested-With':'XMLHttpRequest','Accept':'application/json',
                'Referer':self._url('/lines/create/0/line')})
            if self._is_login(response):
                raise PanelError('Session expired during creation')
            location = getattr(response, 'headers', {}).get('Location', '')
            if location:
                self._url(location)
                if urlsplit(self._url(location)).path.rstrip('/') in ('', '/login'):
                    raise PanelError('Creation redirected to login')
            if response.status_code >= 400:
                raise PanelError('Creation rejected')
            try: acknowledgement=response.json()
            except ValueError: raise PanelError('Panel creation acknowledgement is missing') from None
            redirect=acknowledgement.get('redirect') if isinstance(acknowledgement,dict) else None
            if (not isinstance(redirect,str) or urlsplit(self._url(redirect)).path.rstrip('/')!='/lines'
                    or acknowledgement.get('type') not in (None,'success') or acknowledgement.get('errors')):
                raise PanelError('Panel creation was not acknowledged')
            return self.generated_account(generation)
        except PanelError as exc:
            status = getattr(exc,'http_status',None)
            reason = 'http_'+str(status) if type(status) is int and 400<=status<=599 else 'confirmation_failed'
            raise ProvisioningUncertain('Account creation may have reached the panel; operator reconciliation is required',reason) from None
