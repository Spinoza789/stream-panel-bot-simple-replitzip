import logging
import secrets
import time
from decimal import Decimal, ROUND_UP, ROUND_HALF_UP
from .config import display_units, units
from .store import digest
from .rates import Rates, RateUnavailable

log = logging.getLogger(__name__)


class CheckoutError(Exception): pass


class CheckoutService:
    def __init__(self, config, store, verifier, panel, rates=None):
        self.config = config; self.store = store; self.verifier = verifier; self.panel = panel
        self.rates = rates or Rates(demo=config['mode']=='demo')

    def public(self, order, credentials=True):
        allowed = ('id','kind','plan','asset','amount_units','created_at','expires_at','status','txid','message')
        result = {key: order[key] for key in allowed}
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
            if proof['amount_units'] != int(order['amount_units']): raise PaymentRejected('The received amount does not match this order. Send the exact quoted amount.')
            if proof['network'] != asset['network']: raise PaymentRejected('Wrong payment network.')
            if not order['created_at'] <= proof['block_time'] <= order['expires_at']: raise PaymentRejected('The payment was made outside this quote’s time window. Contact support.')
            self.store.claim_payment(order['id'],proof)
        except PaymentPending:
            self.store.update(order['id'],message='Waiting for blockchain confirmation. No need to pay again.')
        except PaymentRejected as exc:
            self.store.update(order['id'],message=str(exc),txid=None)
        except ChainUnavailable:
            self.store.update(order['id'],message='The blockchain provider is temporarily unavailable. We will retry automatically.')
        finally: self.store.update(order['id'],last_check=int(time.time()))

    def demo_pay(self, token):
        if self.config['mode']!='demo': raise CheckoutError('Demo payments are disabled.')
        order = self.store.by_token(token)
        if not order: raise CheckoutError('Order not found.')
        self._demo_pay(order)

    def demo_pay_telegram(self,telegram_id,order_id):
        if self.config['mode']!='demo': raise CheckoutError('Demo payments are disabled.')
        order=self.store.owned_order(telegram_id,order_id)
        if not order: raise CheckoutError('Order not found.')
        self._demo_pay(order)

    def _demo_pay(self,order):
        self.store.claim_payment(order['id'],dict(network=order['asset']['network'],txid='demo-'+order['id'],amount_units=int(order['amount_units']),block_time=int(time.time()),confirmations=0))

    def provision_pending(self):
        for order in self.store.select('paid',10):
            if not self.store.claim_provision(order['id']): continue
            try:
                credentials = order['credentials'] or {
                    'username':'st_'+order['id'][:18], 'password':secrets.token_urlsafe(18),
                    'package_id':str(order['plan']['package_id'])}
                # Stable credentials are durable before any remote POST. A crash becomes review.
                self.store.update(order['id'],credentials=credentials)
                account = self.panel.create_account(str(order['plan']['package_id']),credentials['username'],credentials['password'],'Streamline order '+order['id'])
                if account.get('username')!=credentials['username'] or account.get('password')!=credentials['password']:
                    raise ValueError('Panel account confirmation mismatch')
                self.store.update(order['id'],status='fulfilled',credentials=account,message='Your account is ready.')
            except Exception as exc:
                from .panel import ProvisioningUncertain
                reason = exc.reason if isinstance(exc,ProvisioningUncertain) else 'unclassified_error'
                log.error('Panel provisioning requires review for order %s (%s, %s)',order['id'],type(exc).__name__,reason)
                self.store.update(order['id'],status='review',message='Your order needs a manual account check. Do not pay again. Contact support with your order ID.')
                if order['kind']=='trial':
                    self.store.metadata('trial_recheck_after:'+order['id'],int(time.time())+120)

    def recover_interrupted(self):
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
        if not isinstance(telegram_id,int) or telegram_id<=0: raise CheckoutError('Invalid Telegram user.')
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
        order = self.store.trial(telegram_id)
        if not order: raise CheckoutError('Start your trial first with /trial.')
        if order['status']!='review': return self.public(order)
        credentials = order['credentials']
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
