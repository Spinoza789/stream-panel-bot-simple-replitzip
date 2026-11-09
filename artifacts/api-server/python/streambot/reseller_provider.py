"""Native panel adapter. Read-only preparation, one submission, read-back verification."""
import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .panel import PanelError, ProvisioningUncertain
from .reseller_ledger import now


def provider_time(value, timezone='Europe/London'):
    if isinstance(value,(int,float)) or isinstance(value,str) and value.isdecimal():
        return int(value)
    text=BeautifulSoup(str(value),'html.parser').get_text(' ',strip=True)
    for pattern,fmt in ((r'\d{4}-\d\d-\d\d \d\d:\d\d(?::\d\d)?','%Y-%m-%d %H:%M'),
                        (r'\d\d-\d\d-\d{4} \d\d:\d\d(?::\d\d)?','%d-%m-%Y %H:%M')):
        match=re.search(pattern,text)
        if match:
            candidate=match.group()
            return int(datetime.strptime(candidate,fmt+(':%S' if len(candidate)==19 else '')).replace(tzinfo=ZoneInfo(timezone)).timestamp())
    raise PanelError('Provider expiry is unavailable')


class PanelProvider:
    def __init__(self, service):
        self.service=service
        self.panel=service.panel

    def package(self, months, connections, adult):
        if months==0:return str(self.service.config['trial_package_id'])
        if months==9:return str((122 if adult else 119)+connections-1)
        for plan in self.service.config['plans']:
            if plan.get('months')==months and plan.get('connections')==connections and plan['id'].startswith('adult-')==adult:
                return str(plan['package_id'])
        raise PanelError('Provider package is not configured')

    def summary(self):
        results={}
        for account in self.panel._account_rows():
            try:expiry=provider_time(account.get('expires_at'),self.service.config.get('provider_timezone','Europe/London'))
            except PanelError:continue
            status='expired' if expiry<=now() else 'active'
            if account.get('enabled') in ('0',0,'false'):status='disabled'
            results[account['panel_id']]=dict(expires_at=expiry,status=status)
        return results

    def _metadata(self,soup,pid,extra=None):
        if not extra:return self.panel._package_details(soup,pid)
        endpoint,method,_=self.panel._ajax(soup,'/lines/packages')
        if method!='POST' or urlsplit(self.panel._url(endpoint)).path!='/lines/packages':
            raise PanelError('Unknown renewal metadata contract')
        response=self.panel._request('POST',endpoint,data=dict(extra,package_id=pid,trial='0'),
                                     headers={'X-Requested-With':'XMLHttpRequest','X-CSRF-TOKEN':self.panel._token(soup)},
                                     allow_redirects=False)
        if response.status_code>=300 or self.panel._is_login(response):raise PanelError('Renewal preview is unavailable')
        payload=response.json()
        if payload.get('result') is not True:raise PanelError('Provider rejected the package preview')
        return payload

    @staticmethod
    def _bouquets(metadata):
        values=metadata.get('bouquets')
        if not isinstance(values,list) or not values:raise PanelError('Provider bouquet profile is unavailable')
        ids=[str(v['id']) for v in values]
        if any(not x.isdecimal() for x in ids):raise PanelError('Invalid provider bouquet profile')
        return ids

    def read(self,panel_id):
        if not isinstance(panel_id,str) or not re.fullmatch(r'[1-9][0-9]*',panel_id):
            raise PanelError('Invalid provider account ID')
        listed=next((a for a in self.panel._account_rows() if a.get('panel_id')==panel_id),None)
        if not listed:raise PanelError('Provider account was not found')
        account=self.panel.verify_account(listed)
        expiry=provider_time(account.get('expires_at'),self.service.config.get('provider_timezone','Europe/London'))
        soup=self.panel._soup(self.panel._read('/lines/edit/'+panel_id))
        field=soup.select_one('[name="username"]')
        form=field.find_parent('form') if field else None
        if not form:raise PanelError('Provider account form is unavailable')
        data=self.panel._form_data(form)
        # This panel's right-hand selector contains the selected profile even
        # though its options have no HTML "selected" attribute. Native save()
        # serializes EVERY #searchmain_to option into current_bouquets.
        right=form.select('#searchmain_to option[value]')
        bouquets=[option['value'] for option in right] if right else data.get('bouquets[]')
        if isinstance(bouquets,str):bouquets=[bouquets]
        if not bouquets:
            current=data.get('current_bouquets','')
            if isinstance(current,str) and re.fullmatch(r'\d+(?:,\d+)*',current):bouquets=current.split(',')
        connections=listed.get('connections')
        text=BeautifulSoup(str(connections or ''),'html.parser').get_text(' ',strip=True)
        match=re.fullmatch(r'\s*\d+\s*/\s*(\d+)\s*',text)
        if match:connections=int(match.group(1))
        elif text.isdecimal():connections=int(text)
        field=form.select_one('[name="max_connections"],[name="connections"]')
        if field and str(field.get('value','')).isdigit():connections=int(field['value'])
        enabled=listed.get('enabled')
        status='expired' if expiry<=now() else 'active'
        if enabled in ('0',0,'false'):status='disabled'
        return dict(provider_id=panel_id,credentials=account,expires_at=expiry,status=status,
                    connections=int(connections) if str(connections).isdigit() else None,
                    bouquets=list(map(str,bouquets)) if bouquets else None,native_expiry=listed.get('native_expiry'))

    def _renewal(self, record, pid):
        panel_id=record['provider_id']
        soup=self.panel._soup(self.panel._read('/lines/extend/'+panel_id))
        field=soup.select_one('select[name="package"]')
        form=field.find_parent('form') if field else None
        action=self.panel._url(form.get('action','')) if form else ''
        if not form or form.get('method','').upper()!='POST' or urlsplit(action).path!='/lines/extend/'+panel_id:
            raise PanelError('Unknown panel renewal form')
        if pid not in {p['id'] for p in self.panel._packages(form)}:raise PanelError('Renewal package is unavailable')
        _,_,script=self.panel._ajax(soup,'/lines/packages')
        blocks=re.findall(r'["\']?data["\']?\s*:\s*\{(.{0,1500}?)\}',script,re.S)
        block=next((b for b in blocks if 'package_id' in b),None)
        if not block:raise PanelError('Unknown renewal preview parameters')
        extra={}
        for key in ('id','uid'):
            match=re.search(r'["\']'+key+r'["\']\s*:\s*["\']([0-9]+)["\']',block)
            if not match:raise PanelError('Unknown renewal preview identity')
            extra[key]=match.group(1)
        if panel_id not in extra.values():raise PanelError('Renewal preview identity does not match')
        return soup,form,action,self._metadata(soup,pid,extra)

    def preview_extension(self, record, months):
        current=self.read(record['provider_id'])
        if current['status']=='disabled':raise PanelError('Provider account is disabled; contact support')
        if current['connections'] is not None and current['connections']!=record['connections']:
            raise PanelError('Provider connections changed; contact support')
        pid=self.package(months,record['connections'],bool(record['adult']))
        _,_,_,metadata=self._renewal(record,pid)
        if int(metadata['data']['max_connections'])!=record['connections']:
            raise PanelError('Renewal would change the connection count')
        expiry=provider_time(metadata['data']['exp_date'])
        if expiry<=max(now(),current['expires_at']):raise PanelError('Provider did not quote an extended expiry')
        return dict(previous_expiry=current['expires_at'],expected_expiry=expiry,package_id=pid)

    def prepare(self,operation,record=None):
        if not self.panel.allow_create:raise PanelError('Panel writes are disabled')
        pid=operation['package_id']
        if operation['operation_type']=='extend':
            current=self.read(record['provider_id'])
            if current['status']=='disabled':raise PanelError('Provider account is disabled; contact support')
            soup,form,action,metadata=self._renewal(record,pid)
            if current['expires_at']!=record['expires_at']:raise PanelError('Provider expiry changed; review this subscription again')
            data=self.panel._form_data(form)
            price=Decimal(str(metadata['data']['cost_credits']))
            balance=data.get('credits_left')
            if not balance:
                scripts='\n'.join(s.get_text() for s in soup.select('script'))
                balances=re.findall(r'\b(?:var|let|const)\s+currentCredits\s*=\s*(\d+(?:\.\d+)?)\s*-\s*credits',scripts)
                if len(balances)!=1:raise PanelError('Provider credit balance is unavailable')
                balance=balances[0]
            remaining=Decimal(str(balance))-price
            if remaining<0 or not remaining.is_finite():raise PanelError('Provider has insufficient credits')
            if int(metadata['data']['max_connections'])!=operation['connections']:
                raise PanelError('Renewal would change connections')
            bouquets=self._bouquets(metadata)
            expiry=provider_time(metadata['data']['exp_date'])
            if expiry<=max(now(),current['expires_at']):raise PanelError('Invalid provider renewal expiry')
            data.update({'_token':self.panel._token(soup),'package':pid,'description':'',
                         'expire_date':metadata['data']['exp_date'],'connections':str(operation['connections']),
                         'price':str(price),'credits_left':str(remaining),'current_bouquets':','.join(bouquets),
                         'bouquets[]':bouquets,'bouquets_main[]':bouquets})
            return dict(mode='extend',provider_id=record['provider_id'],previous_expiry=current['expires_at'],
                        expected_expiry=expiry,expected_native_expiry=metadata['data']['exp_date'],action=action,data=data,bouquets=bouquets)
        generation=self.panel.prepare_generation(pid)
        soup,_,_=self.panel._create_form()
        metadata=self._metadata(soup,pid)
        if int(metadata['data']['max_connections'])!=operation['connections']:
            raise PanelError('Provider package has different connections')
        bouquets=self._bouquets(metadata)
        if operation['operation_type']=='trial' and not operation['adult']:
            adult=self._bouquets(self._metadata(soup,self.package(1,1,True)))
            plain=self._bouquets(self._metadata(soup,self.package(1,1,False)))
            excluded=set(adult)-set(plain)
            if not excluded or not excluded.issubset(set(bouquets)):
                raise PanelError('Trial content profiles cannot be verified')
            bouquets=[x for x in bouquets if x not in excluded]
        if not bouquets:raise PanelError('Empty trial profile')
        return dict(mode='create',generation=generation,bouquets=bouquets,
                    expected_expiry=provider_time(metadata['data']['exp_date']),expected_native_expiry=metadata['data']['exp_date'])

    def execute(self,operation,context):
        if context['mode']=='create':
            kwargs={'generation':context['generation']}
            if operation['operation_type']=='trial':kwargs['bouquet_ids']=context['bouquets']
            try:account=self.panel.create_account(operation['package_id'],'','','',**kwargs)
            except PanelError:raise
            except Exception:raise ProvisioningUncertain('Provider result is uncertain') from None
            context=dict(context,provider_id=str(account['panel_id']))
        try:
            if context['mode']=='extend':
                response=self.panel._request('POST',context['action'],data=context['data'],allow_redirects=False,
                                             headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'})
                acknowledgement=response.json()
                redirect=acknowledgement.get('redirect')
                if (response.status_code>=300 or self.panel._is_login(response) or not isinstance(redirect,str)
                        or urlsplit(self.panel._url(redirect)).path!='/lines'
                        or acknowledgement.get('errors') or acknowledgement.get('type') not in (None,'success')):
                    raise PanelError('Renewal was not acknowledged')
            return self.reconcile(operation,context)
        except Exception:
            raise ProvisioningUncertain('Provider result is uncertain; reconcile without resubmitting') from None

    def reconcile(self,operation,context,provider_id=None):
        if context['mode']=='create':
            if provider_id:
                if provider_id in context['generation']['before_ids']:raise PanelError('Account existed before this operation')
                panel_id=provider_id
            elif context.get('provider_id'):panel_id=context['provider_id']
            else:panel_id=str(self.panel.generated_account(context['generation'])['panel_id'])
        else:
            panel_id=context['provider_id']
            if provider_id and provider_id!=panel_id:raise PanelError('Cannot change the account being extended')
        account=self.read(panel_id)
        if account['status']!='active':raise PanelError('Provider account is not active')
        # Compare the provider's own formatted preview/read-back in its native
        # clock. Use its separate Unix expiry for storage and London display;
        # guessing its timezone from a winter sample breaks summer renewals.
        native=account.get('native_expiry')
        expected=context.get('expected_native_expiry')
        if isinstance(native,str) and not native.isdecimal() and isinstance(expected,str):
            difference=abs(provider_time(native,'UTC')-provider_time(expected,'UTC'))
        else:difference=abs(account['expires_at']-context['expected_expiry'])
        if difference>120:
            raise PanelError('Provider expiry does not match this operation')
        if account['connections'] is not None and account['connections']!=operation['connections']:
            raise PanelError('Provider connections do not match')
        if account['bouquets'] is None or set(account['bouquets'])!=set(context['bouquets']):
            raise PanelError('Provider content profile does not match')
        return account
