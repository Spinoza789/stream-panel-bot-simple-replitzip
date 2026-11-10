"""Owned reseller accounts, immutable financial movements and administrator controls."""
import contextlib
import json
import secrets
import time

from .service import CheckoutError


def now():
    return int(time.time())


def identifier():
    return secrets.token_hex(12)


def integer(value, minimum=0, maximum=10**9):
    if type(value) is not int or not minimum<=value<=maximum:
        raise CheckoutError('Enter a valid whole number.')
    return value


class Ledger:
    def __init__(self, service):
        self.service=service
        self.store=service.store
        self._seeded=False

    @contextlib.contextmanager
    def transaction(self):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def seed(self):
        if self._seeded:return
        with self.transaction() as db:
            for pounds,credits in ((100,34),(200,75),(300,129),(400,192)):
                db.execute('INSERT INTO rs_packages VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                           (str(pounds),pounds*100,credits,1,now()))
            for months,costs in ((1,(1,2,3)),(3,(3,4,5)),(6,(6,7,8)),(9,(9,10,11)),(12,(12,15,20))):
                for connections,cost in enumerate(costs,1):
                    db.execute('INSERT INTO rs_costs VALUES(?,?,?,?) ON CONFLICT(months,connections) DO NOTHING',
                               (months,connections,cost,now()))
            for key,value in (('trial_daily','1'),('trial_active','1')):
                db.execute('INSERT INTO rs_settings VALUES(?,?) ON CONFLICT(key) DO NOTHING',(key,value))
        self._seeded=True

    def member(self, uid, db=None, active=False):
        integer(uid,1,2**63-1)
        if db is None:
            with self.store.connection() as connection:
                return self.member(uid,connection,active)
        row=db.execute('SELECT r.*,a.balance,a.reserved FROM rs_resellers r JOIN rs_accounts a ON a.reseller_id=r.id WHERE r.telegram_id=?',(uid,)).fetchone()
        result=dict(row) if row else None
        if active and (not result or result['status']!='active'):
            if not result:raise CheckoutError('Open Become A Reseller and buy a credit pack first.')
            raise CheckoutError('Buy a credit pack to activate your reseller account first.' if result['status']=='pending' else 'Your reseller account is suspended. Contact support for help.')
        if result:result['available']=result['balance']-result['reserved']
        return result

    def register(self, uid, username=''):
        integer(uid,1,2**63-1)
        self.seed()
        username=username[:64] if isinstance(username,str) else ''
        with self.transaction() as db:
            existing=self.member(uid,db)
            if existing:
                db.execute('UPDATE rs_resellers SET username=?,updated_at=? WHERE telegram_id=?',(username,now(),uid))
            else:
                rid=identifier()
                db.execute('INSERT INTO rs_resellers VALUES(?,?,?,?,?,?)',(rid,uid,username,'pending',now(),now()))
                db.execute('INSERT INTO rs_accounts VALUES(?,0,0)',(rid,))
            return self.member(uid,db)

    def admin(self, uid):
        expected=self.service.config.get('support_admin_id')
        if type(uid) is not int or not expected or uid!=expected:
            raise CheckoutError('Administrator access required.')

    def audit(self, db, actor, action, subject, reason, details=None):
        if not isinstance(reason,str) or not 3<=len(reason.strip())<=500:
            raise CheckoutError('A reason of 3–500 characters is required.')
        db.execute('INSERT INTO rs_audit VALUES(?,?,?,?,?,?,?)',
                   (identifier(),actor,action,str(subject),reason.strip(),json.dumps(details or {}),now()))

    def account_status(self, actor, uid, status, reason):
        self.admin(actor)
        if status not in ('active','suspended'):raise CheckoutError('Invalid account status.')
        if not self.member(uid):self.register(uid)
        with self.transaction() as db:
            self.audit(db,actor,status,uid,reason)
            db.execute('UPDATE rs_resellers SET status=?,updated_at=? WHERE telegram_id=?',(status,now(),uid))
        return self.member(uid)

    def adjust(self, actor, uid, movement, reason, request_key):
        self.admin(actor)
        if type(movement) is not int:raise CheckoutError('Credits must be whole numbers.')
        integer(abs(movement),1)
        self.seed()
        reference='adjust:'+str(actor)+':'+str(request_key)
        with self.transaction() as db:
            member=self.member(uid,db)
            if not member:raise CheckoutError('Reseller account not found.')
            if db.execute('SELECT id FROM rs_ledger WHERE reference=?',(reference,)).fetchone():
                return member
            self.audit(db,actor,'credit_adjustment',uid,reason,{'movement':movement})
            if member['available']+movement<0:
                raise CheckoutError('Not enough unreserved credits. Reserved credits cannot be removed.')
            db.execute('UPDATE rs_accounts SET balance=balance+? WHERE reseller_id=?',(movement,member['id']))
            db.execute('INSERT INTO rs_ledger VALUES(?,?,?,?,?,?,?)',
                       (identifier(),member['id'],movement,reason,reference,actor,now()))
            return self.member(uid,db)

    def packages(self):
        self.seed()
        with self.store.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM rs_packages ORDER BY price_pence').fetchall()]

    def configuration(self, actor):
        self.admin(actor); self.seed()
        with self.store.connection() as db:
            return dict(packages=[dict(r) for r in db.execute('SELECT * FROM rs_packages ORDER BY price_pence').fetchall()],
                        costs=[dict(r) for r in db.execute('SELECT * FROM rs_costs ORDER BY months,connections').fetchall()],
                        settings={r['key']:r['value'] for r in db.execute('SELECT * FROM rs_settings').fetchall()})

    def configure(self, actor, category, values, reason):
        self.admin(actor);self.seed()
        with self.transaction() as db:
            if category=='package':
                pid,price,credits,active=values
                integer(price,1);integer(credits,1);integer(active,0,1)
                if not db.execute('SELECT id FROM rs_packages WHERE id=?',(pid,)).fetchone():
                    raise CheckoutError('Package not found.')
                db.execute('UPDATE rs_packages SET price_pence=?,credits=?,active=?,updated_at=? WHERE id=?',(price,credits,active,now(),pid))
            elif category=='cost':
                months,connections,cost=values
                if months not in (1,3,6,9,12):raise CheckoutError('Invalid duration.')
                integer(connections,1,3);integer(cost,1)
                db.execute('UPDATE rs_costs SET credits=?,updated_at=? WHERE months=? AND connections=?',(cost,now(),months,connections))
            elif category=='trials':
                daily,active=values
                integer(daily,0,1000);integer(active,0,1000)
                db.execute("UPDATE rs_settings SET value=? WHERE key='trial_daily'",(str(daily),))
                db.execute("UPDATE rs_settings SET value=? WHERE key='trial_active'",(str(active),))
            else:raise CheckoutError('Unknown configuration option.')
            self.audit(db,actor,'configuration',category,reason,{'values':values})

    def quote_purchase(self, uid, package_id, asset, request_key, with_token=False):
        self.seed()
        member=self.member(uid)
        if not member:raise CheckoutError('Open Become A Reseller first.')
        if member['status']=='suspended':raise CheckoutError('Your reseller account is suspended and cannot buy credits.')
        package=next((p for p in self.packages() if p['id']==package_id and p['active']),None)
        if not package:raise CheckoutError('Credit package is unavailable.')
        from .store import digest
        plan=dict(id='credits-'+package['id']+'-'+digest(json.dumps(package,sort_keys=True))[:10],
                  name=str(package['credits'])+' reseller credits',detail='Verified payment required',
                  gbp_price=f"{package['price_pence']//100}.{package['price_pence']%100:02d}",
                  reseller_purchase=dict(reseller_id=member['id'],package=package))
        quote=self.service.quote_plan(plan,asset,owner_telegram_id=uid,request_key='rsquote:'+str(uid)+':'+request_key)
        return quote if with_token else quote['order']

    def grant(self, order_id, *, actor=None, reference=None, reason=None):
        """One purchase -> one ledger movement; no button can verify payment."""
        if actor is not None:self.admin(actor)
        with self.transaction() as db:
            purchase=db.execute('SELECT * FROM rs_purchases WHERE id=?',(order_id,)).fetchone()
            if not purchase:raise CheckoutError('Credit purchase not found.')
            if purchase['status']=='granted':return
            order=db.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
            if actor is None:
                proof=db.execute('SELECT network,txid FROM payments WHERE order_id=?',(order_id,)).fetchone()
                if not proof or order['status'] not in ('paid','provisioning'):
                    raise CheckoutError('Payment has not been verified.')
                reference=proof['network']+':'+proof['txid']
                reason='Verified blockchain payment'
            else:
                if not isinstance(reference,str) or not 3<=len(reference)<=150:
                    raise CheckoutError('A unique payment reference is required, such as network:TXID or bank:reference.')
                self.audit(db,actor,'manual_payment',order_id,reason,{'reference':reference})
            reference=reference.strip().casefold()
            if db.execute('SELECT id FROM rs_purchases WHERE payment_reference=?',(reference,)).fetchone():
                raise CheckoutError('This payment reference has already been credited.')
            db.execute("UPDATE rs_purchases SET status='granted',payment_reference=?,updated_at=? WHERE id=?",(reference,now(),order_id))
            db.execute('UPDATE rs_accounts SET balance=balance+? WHERE reseller_id=?',(purchase['credits'],purchase['reseller_id']))
            db.execute('INSERT INTO rs_ledger VALUES(?,?,?,?,?,?,?)',
                       (identifier(),purchase['reseller_id'],purchase['credits'],reason,'purchase:'+order_id,actor,now()))
            db.execute("UPDATE orders SET status='fulfilled',message='Credits added to your reseller balance.' WHERE id=?",(order_id,))
            # Buying credits is how someone becomes a reseller: the first verified pack activates the account.
            db.execute("UPDATE rs_resellers SET status='active',updated_at=? WHERE id=? AND status='pending'",(now(),purchase['reseller_id']))

    def history(self, uid, page=0):
        integer(page,0,100000)
        member=self.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        with self.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM rs_ledger WHERE reseller_id=? ORDER BY created_at DESC,id DESC LIMIT 11 OFFSET ?',(member['id'],page*10)).fetchall()]

    def admin_list(self, actor, category, page=0):
        self.admin(actor);self.seed();integer(page,0,100000)
        queries={'accounts':'SELECT telegram_id,username,status FROM rs_resellers ORDER BY created_at DESC,id',
                 'purchases':"SELECT p.id,r.telegram_id,p.amount_pence,p.credits,p.status FROM rs_purchases p JOIN rs_resellers r ON r.id=p.reseller_id ORDER BY p.created_at DESC,p.id",
                 'operations':"SELECT o.id,r.telegram_id,o.status,o.credit_cost,o.error FROM rs_operations o JOIN rs_resellers r ON r.id=o.reseller_id WHERE o.status IN ('queued','preparing','processing','uncertain','failed') ORDER BY o.created_at DESC,o.id",
                 'audit':'SELECT administrator,action,subject,reason,created_at FROM rs_audit ORDER BY created_at DESC,id'}
        if category not in queries:raise CheckoutError('Invalid list.')
        with self.store.connection() as db:
            return [dict(r) for r in db.execute(queries[category]+' LIMIT 11 OFFSET ?',(page*10,)).fetchall()]
