import logging
import secrets
import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
from .config import display_units, units
from .store import digest
from .rates import Rates, RateUnavailable
from .panel import PanelError, ProvisioningUncertain

log = logging.getLogger(__name__)


class CheckoutError(Exception): pass


class CheckoutService:
    def __init__(self, config, store, verifier, panel, rates=None):
        self.config = config; self.store = store; self.verifier = verifier; self.panel = panel
        self.rates = rates or Rates(demo=config['mode']=='demo')
        from .resellers import Resellers
        self.resellers=Resellers(self)

    def public(self, order, credentials=True):
        allowed = ('id','kind','plan','asset','amount_units','created_at','expires_at','status','txid','message')
        result = {key: order[key] for key in allowed}
        stored_credentials=order.get('credentials') or {}
        if (order['status']=='review' and stored_credentials.get('generation_mode')=='panel'
                and stored_credentials.get('post_attempted',True)):
            result['account_identity_unknown']=True
        result['amount'] = display_units(order['amount_units'], order['asset'].get('decimals',0))
        if 'crypto_base_units' in order['plan']:
            result['matching_adjustment']=display_units(int(order['amount_units'])-int(order['plan']['crypto_base_units']),order['asset']['decimals'])
        if order['status'] == 'pending' and int(time.time()) > order['expires_at']:
            result['quote_expired'] = True
        if credentials and order['status'] == 'fulfilled': result['credentials'] = order['credentials']
        return result

    def create_order(self, plan_id, asset_id, *, owner_telegram_id=None, request_key=None):
        if not isinstance(plan_id,str) or not isinstance(asset_id,str): raise CheckoutError('Choose a plan and a payment network.')
        plan = next((p for p in self.config['plans'] if p['id']==plan_id),None)
        asset = self.config['assets'].get(asset_id)
        if not plan or not asset or not asset.get('enabled',True): raise CheckoutError('Unknown plan or payment network.')
        return self.quote_plan(plan,asset_id,owner_telegram_id=owner_telegram_id,request_key=request_key)

    def quote_plan(self,plan,asset_id,*,owner_telegram_id=None,request_key=None):
        self.resellers.guard(owner_telegram_id)
        asset=self.config['assets'].get(asset_id)
        if not asset or not asset.get('enabled',True):raise CheckoutError('Unknown payment network.')
        plan = dict(plan)
        if 'gbp_price' in plan:
            try: quote = self.rates.snapshot(asset['symbol'])
            except RateUnavailable as exc: raise CheckoutError(str(exc)) from None
            rate=quote['crypto_per_gbp']
            plan['fx_rate'] = str(rate)
            plan['gbp_usd_rate']=str(quote['usd_per_gbp'])
            plan['crypto_per_usd']=str(quote['crypto_per_usd'])
            plan['usd_price']=str((Decimal(plan['gbp_price'])*quote['usd_per_gbp']).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
            plan['rate_fetched_at'] = quote['fetched_at']
            base_units = int((Decimal(plan['gbp_price']) * rate * 10**asset['decimals']).to_integral_value(rounding=ROUND_UP))
            # Payments a little under or over the quote are still accepted (see amount_check). Fixed at quote time.
            tolerance=self.config.get('payment_tolerance_usd',{})
            scale=quote['crypto_per_usd']*10**asset['decimals']
            plan['tolerance_under_units']=str(int((Decimal(tolerance.get('under','0'))*scale).to_integral_value(rounding=ROUND_DOWN)))
            plan['tolerance_over_units']=str(int((Decimal(tolerance.get('over','0'))*scale).to_integral_value(rounding=ROUND_UP)))
        else: base_units = units(plan['prices'][asset_id],asset['decimals'])
        quantum = 10**max(0,asset['decimals']-8)
        max_nonce=999
        if 'gbp_price' in plan:
            # Cap the identifying suffix at one penny, even for BTC.
            max_nonce=min(999,int(Decimal('0.01')*rate*10**asset['decimals']//quantum))
            if max_nonce<1: raise CheckoutError('The selected asset cannot currently support an exact payment quote.')
        plan['crypto_base_units']=str(base_units)
        asset_snapshot = {k:v for k,v in asset.items() if k not in ('rpc_url','rpc_env')}
        try:
            token, order = self.store.create(plan, asset_snapshot, base_units, quantum, lifetime=self.config['quote_minutes']*60,
                                            max_nonce=max_nonce,owner_telegram_id=owner_telegram_id,request_key=request_key)
        except ValueError as exc: raise CheckoutError(str(exc)) from None
        return {'token':token,'order':self.public(order)}

    def renew_order(self,telegram_id,order_id,asset_id,request_key):
        """Quote a renewal of a fulfilled retail membership: same plan, same panel account, extended on payment."""
        self.resellers.guard(telegram_id)
        original=self.store.owned_order(telegram_id,order_id)
        if not original or original['kind']!='paid' or original['status']!='fulfilled':raise CheckoutError('Only a delivered membership can be renewed.')
        credentials=original.get('credentials') or {}
        panel_id=str(credentials.get('panel_id') or '')
        if not panel_id.isdigit():raise CheckoutError('This account cannot be renewed automatically. Contact support.')
        base=original['plan']
        if base.get('reseller_purchase') or base.get('renew_of'):
            raise CheckoutError('Renew from your original membership order in My orders.')
        plan=next((p for p in self.config['plans'] if p['id']==base.get('id')),None) or base
        renewal=dict(plan,name=plan['name']+' renewal',detail='Extends your current login by '+str(plan['months'])+(' month' if plan['months']==1 else ' months'),
                     renew_of=order_id,renew_panel_id=panel_id)
        renewal.pop('reseller_purchase',None)
        return self.quote_plan(renewal,asset_id,owner_telegram_id=telegram_id,request_key=request_key)

    def _provision_renewal(self,order):
        """Extend the original panel account instead of creating a new one. Uses the reseller provider's verified renewal path."""
        plan=order['plan'];provider=self.resellers.ops.provider
        original=self.store.get(plan['renew_of'])
        credentials=dict((original or {}).get('credentials') or {})
        panel_id=str(credentials.get('panel_id') or '')
        if not original or panel_id!=str(plan.get('renew_panel_id')):raise PanelError('Renewal target does not match the original order')
        current=provider.read(panel_id)
        record=dict(provider_id=panel_id,connections=int(plan['connections']),adult=False,expires_at=current['expires_at'])
        operation=dict(operation_type='extend',package_id=provider.package(int(plan['months']),int(plan['connections']),False),connections=int(plan['connections']))
        context=provider.prepare(operation,record)
        account=provider.execute(operation,context)
        credentials.update(expires_at=account['expires_at'],renewed_at=int(time.time()),renewed_from=plan['renew_of'])
        self.store.update(order['id'],status='fulfilled',credentials=credentials,message='Your membership has been extended. Same login, new expiry.')

    def get_order(self, token):
        order = self.store.by_token(token)
        if not order: raise CheckoutError('Order not found. Use the private recovery link from checkout.')
        return self.public(order)

    def submit_tx(self, token, txid):
        order = self.store.by_token(token)
        if not order: raise CheckoutError('Order not found.')
        return self._submit_tx(order,txid)

    def telegram_order(self,telegram_id,order_id):
        order=self.store.owned_order(telegram_id,order_id)
        if not order: raise CheckoutError('Order not found.')
        return self.public(order)

    def submit_telegram_tx(self,telegram_id,order_id,txid):
        self.resellers.guard(telegram_id)
        order=self.store.owned_order(telegram_id,order_id)
        if not order: raise CheckoutError('Order not found.')
        return self._submit_tx(order,txid)

    def _submit_tx(self,order,txid):
        if not isinstance(txid,str) or not 32<=len(txid.strip())<=100: raise CheckoutError('Enter a transaction ID, not an explorer link.')
        if '://' in txid or any(c.isspace() for c in txid.strip()):
            raise CheckoutError('Paste only the transaction hash, not an explorer link.')
        if order['status'] != 'pending': return self.public(order)
        # Do not reserve a TXID until the blockchain proves the invoice belongs to it.
        self.store.submit_tx(order['id'],txid.strip())
        return self.public(self.store.get(order['id']))

    def verify_order(self, token=None, *, order_id=None):
        from .chains import PaymentPending, PaymentRejected, ChainUnavailable
        order = self.store.get(order_id) if order_id else self.store.by_token(token)
        if not order or order['status']!='pending' or not order['txid']: return
        asset = dict(order['asset'])
        asset['rpc_url'] = self.config['assets'][asset['id']].get('rpc_url','')
        try:
            proof = self.verifier.verify(asset,order['txid'],order['created_at'],order['expires_at'])
            if proof['network'] != asset['network']: raise PaymentRejected('Wrong payment network.')
            if not order['created_at'] <= proof['block_time'] <= order['expires_at']: raise PaymentRejected('The payment was made outside this quote’s time window. Contact support.')
            self.amount_check(order,proof)
            self.store.claim_payment(order['id'],proof)
        except PaymentPending:
            self.store.update_pending_verification(order['id'],order['txid'],message='Waiting for blockchain confirmation. No need to pay again.')
        except PaymentRejected as exc:
            self.store.update_pending_verification(order['id'],order['txid'],message=str(exc),txid=None)
        except ChainUnavailable:
            self.store.update_pending_verification(order['id'],order['txid'],message='The blockchain provider is temporarily unavailable. We will retry automatically.')
        finally: self.store.update_pending_verification(order['id'],order['txid'],last_check=int(time.time()))

    @staticmethod
    def tolerance_range(order):
        quoted=int(order['amount_units']); plan=order['plan']
        return quoted-int(plan.get('tolerance_under_units',0)), quoted+int(plan.get('tolerance_over_units',0))

    def amount_check(self,order,proof):
        """Accept the exact quote, or an amount within the tolerance, unless it plainly belongs to another open order.

        The exact figure (with its identifying suffix) always wins: a payment that equals
        another open quote is that quote's, and an inexact amount that several open quotes
        could claim is left for support rather than handed to whoever submits the TXID first.
        """
        from .chains import PaymentRejected
        received=proof['amount_units']; quoted=int(order['amount_units'])
        if received==quoted: return
        low,high=self.tolerance_range(order)
        if not low<=received<=high:
            raise PaymentRejected('The received amount does not match this order. Do not pay again; contact support with your TXID.')
        for other in self.store.competing_orders(order['asset']['id'],order['id'],proof['block_time']):
            if received==int(other['amount_units']):
                raise PaymentRejected('The received amount matches a different order exactly. Do not pay again; contact support with your TXID.')
        for other in self.store.competing_orders(order['asset']['id'],order['id'],proof['block_time']):
            other_low,other_high=self.tolerance_range(other)
            if other_low<=received<=other_high:
                raise PaymentRejected('The received amount is close to more than one open order, so it must be matched by hand. Do not pay again; contact support with your TXID.')

    def demo_pay(self, token):
        if self.config['mode']!='demo': raise CheckoutError('Demo payments are disabled.')
        order = self.store.by_token(token)
        if not order: raise CheckoutError('Order not found.')
        self._demo_pay(order)

    def demo_pay_telegram(self,telegram_id,order_id):
        self.resellers.guard(telegram_id)
        if self.config['mode']!='demo': raise CheckoutError('Demo payments are disabled.')
        order=self.store.owned_order(telegram_id,order_id)
        if not order: raise CheckoutError('Order not found.')
        self._demo_pay(order)

    def _demo_pay(self,order):
        self.store.claim_payment(order['id'],dict(network=order['asset']['network'],txid='demo-'+order['id'],amount_units=int(order['amount_units']),block_time=int(time.time()),confirmations=0))

    def provision_pending(self):
        for order in self.store.select('paid',10):
            if order['plan'].get('reseller_purchase'):
                self.resellers.finance.grant(order['id'])
                continue
            if not self.store.claim_provision(order['id']): continue
            generation = None
            try:
                if order['plan'].get('renew_of'):
                    self._provision_renewal(order)
                    continue
                credentials = order['credentials']
                if credentials and credentials.get('generation_mode')=='panel':
                    raise ProvisioningUncertain('Previous generation requires manual reconciliation')
                if credentials and credentials.get('username'):
                    existing = self.panel.find_account(credentials['username'])
                    if existing is not None:
                        if (existing.get('username')!=credentials['username'] or existing.get('password')!=credentials['password']
                                or existing.get('package_id',str(order['plan']['package_id']))!=str(order['plan']['package_id'])):
                            raise PanelError('Existing account credentials do not match')
                        self.store.update(order['id'],status='fulfilled',credentials=existing,message='Your account is ready.')
                        continue
                generation = self.panel.prepare_generation(str(order['plan']['package_id']))
                # Persist correlation before POST; never repeat an uncertain blank-field submission.
                self.store.update(order['id'],credentials=generation)
                account = self.panel.create_account(str(order['plan']['package_id']),'','','',generation=generation)
                if not all(isinstance(account.get(key),str) and account[key] for key in ('username','password')):
                    raise ValueError('Panel account confirmation mismatch')
                self.store.update(order['id'],status='fulfilled',credentials=account,message='Your account is ready.')
            except Exception as exc:
                if generation is None and not credentials and isinstance(exc,PanelError):
                    # prepare_generation failed before any business POST. Preserve
                    # this proof so retry can requeue this order, not a new trial.
                    self.store.update(order['id'],credentials=dict(
                        generation_mode='panel',package_id=str(order['plan']['package_id']),
                        post_attempted=False,failure_stage='generation_preflight'))
                if generation and isinstance(exc,PanelError) and not isinstance(exc,ProvisioningUncertain):
                    generation['post_attempted']=False
                    self.store.update(order['id'],credentials=generation)
                reason = exc.reason if isinstance(exc,ProvisioningUncertain) else (
                    'generation_preflight' if generation is None and not credentials else 'unclassified_error')
                log.error('Panel provisioning requires review for order %s (%s, %s)',order['id'],type(exc).__name__,reason)
                self.store.update(order['id'],status='review',message='Your order needs a manual account check. Do not pay again. Contact support with your order ID.')
                if order['kind']=='trial':
                    self.store.metadata('trial_recheck_after:'+order['id'],int(time.time())+120)
        self.resellers.process()

    def recover_interrupted(self):
        self.resellers.recover()
        for order in self.store.select('provisioning',10000):
            self.store.update(order['id'],status='review',message='An interrupted account request needs a manual check. Do not pay again.')

    def check_payments(self):
        started=time.monotonic()
        for order in self.store.select('pending',3):
            if order['txid'] and time.time()-order['last_check']>=20:
                self.verify_order(order_id=order['id'])
            if time.monotonic()-started>20: break

    def tick(self):
        # Synchronous helper for tests. The server uses independent workers.
        self.provision_pending()
        self.check_payments()
        self.provision_pending()

    def create_trial(self, telegram_id):
        if type(telegram_id) is not int or telegram_id<=0: raise CheckoutError('Invalid Telegram user.')
        self.resellers.guard(telegram_id)
        if (self.resellers.member(telegram_id) or {}).get('status')=='active':
            raise CheckoutError('Use Reseller area → Create Trial for customer trials. Your reseller limits apply there.')
        plan = dict(id='trial',name='24-hour trial',package_id=str(self.config['trial_package_id']))
        try:
            _, order = self.store.create(plan,dict(id='trial',network='none',decimals=0),0,telegram_id=telegram_id,daily_limit=self.config['trial_daily_limit'])
        except ValueError as exc: raise CheckoutError(str(exc)) from None
        return self.public(order)

    def trial_status(self, telegram_id):
        order = self.store.trial(telegram_id)
        return self.public(order) if order else None

    def retry_trial(self, telegram_id):
        if type(telegram_id) is not int or telegram_id<=0: raise CheckoutError('Invalid Telegram user.')
        self.resellers.guard(telegram_id)
        order = self.store.trial(telegram_id)
        if not order: raise CheckoutError('Start your trial first with /trial.')
        if order['status']!='review': return self.public(order)
        if (self.resellers.member(telegram_id) or {}).get('status')=='active':
            raise CheckoutError('Contact support to recover your existing retail trial. Create customer trials from the reseller menu.')
        credentials = order['credentials']
        if credentials and credentials.get('generation_mode')=='panel':
            if credentials.get('post_attempted',True):
                raise CheckoutError('This panel-generated trial needs support to identify its account. No second account will be created.')
            if self.config['mode']=='live' and not self.config['panel_writes']:
                raise CheckoutError('Panel account creation is disabled. No retry was queued.')
            retry_after=int(self.store.metadata('trial_recheck_after:'+order['id']) or '0')
            if time.time()<retry_after or not self.store.limit('trial-recheck:'+str(telegram_id),2,3600):
                raise CheckoutError('Please wait before checking this trial again.')
            self.store.resolve_trial_review(order['id'],telegram_id,clear_credentials=True)
            return self.public(self.store.get(order['id']))
        if not credentials or not credentials.get('username') or not credentials.get('password'):
            raise CheckoutError('This trial needs support to check its stored account details.')
        retry_after = int(self.store.metadata('trial_recheck_after:'+order['id']) or order['created_at']+120)
        if time.time()<retry_after or not self.store.limit('trial-recheck:'+str(telegram_id),2,3600):
            raise CheckoutError('Please wait before checking this trial again. Contact support if it remains unavailable.')
        try: account = self.panel.find_account(credentials['username'])
        except Exception:
            raise CheckoutError('The panel could not be checked safely. No retry was queued; please contact support.') from None
        if account is not None:
            if (account.get('username')!=credentials['username'] or
                    account.get('password')!=credentials['password'] or
                    account.get('package_id',str(order['plan']['package_id']))!=str(order['plan']['package_id'])):
                raise CheckoutError('The existing panel account needs support to verify it. No retry was queued.')
        elif self.config['mode']=='live' and not self.config['panel_writes']:
            raise CheckoutError('Panel account creation is disabled. No retry was queued.')
        self.store.resolve_trial_review(order['id'],telegram_id,account)
        return self.public(self.store.get(order['id']))

    def create_link_code(self, token):
        order = self.store.by_token(token)
        if not order or order['status']!='fulfilled': raise CheckoutError('An active account is required.')
        code = secrets.token_hex(8).upper()
        with self.store.connection() as db:
            db.execute('DELETE FROM links WHERE expires_at<? OR order_id=?',(int(time.time()),order['id']))
            db.execute('INSERT INTO links VALUES(?,?,?)',(digest(code),order['id'],int(time.time())+600))
        return code

    def link_account(self, code, telegram_id):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM links WHERE code_hash=? AND expires_at>=?',(digest(code.upper()),int(time.time()))).fetchone()
            if not row: raise CheckoutError('Linking code is invalid or expired.')
            existing=db.execute('SELECT telegram_id FROM account_links WHERE order_id=?',(row['order_id'],)).fetchone()
            if existing and existing[0]!=telegram_id: raise CheckoutError('This account is already linked. Contact support to change it.')
            db.execute('INSERT OR IGNORE INTO account_links VALUES(?,?)',(telegram_id,row['order_id']))
            db.execute('DELETE FROM links WHERE code_hash=?',(digest(code.upper()),))
            order_id=row['order_id']
        return self.public(self.store.get(order_id),credentials=False)

    def linked_accounts(self, telegram_id):
        with self.store.connection() as db:
            ids=[row[0] for row in db.execute('SELECT order_id FROM account_links WHERE telegram_id=?',(telegram_id,))]
        return [self.public(self.store.get(order_id),credentials=False) for order_id in ids]
