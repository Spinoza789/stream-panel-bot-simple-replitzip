"""Owned reseller accounts, immutable financial movements and administrator controls."""
import contextlib
import json
import re
import secrets
import time

from .service import CheckoutError

WEB_ACTOR=r'(?:replit|local):[A-Za-z0-9_-]{1,128}:[a-f0-9]{64}'


def now():
    return int(time.time())


def identifier():
    return secrets.token_hex(12)


def integer(value, minimum=0, maximum=10**9):
    if type(value) is not int or not minimum<=value<=maximum:
        raise CheckoutError('Enter a valid whole number.')
    return value


# Reseller free-trial allowances. Each cap is a whole number; -1 means unlimited and 0 means none.
# daily/weekly/monthly are rolling windows (24 hours, 7 days, 30 days); active is trials running at once.
UNLIMITED=-1
TRIAL_MAX=100000
TRIAL_WINDOWS=('daily','weekly','monthly','active')
TRIAL_KEYS={name:'trial_'+name for name in TRIAL_WINDOWS}
TRIAL_SECONDS={'daily':86400,'weekly':7*86400,'monthly':30*86400}
TRIAL_DEFAULTS={'daily':1,'weekly':UNLIMITED,'monthly':UNLIMITED,'active':1}


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
            for pounds,credits in ((10,3),(100,34),(200,75),(300,129),(400,192)):  # £10 is the small live-test pack; switch it off in Settings → Rate card when not needed
                db.execute('INSERT INTO rs_packages VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                           (str(pounds),pounds*100,credits,1,now()))
            for months,costs in ((1,(1,2,3)),(3,(3,4,5)),(6,(6,7,8)),(9,(9,10,11)),(12,(12,15,20))):
                for connections,cost in enumerate(costs,1):
                    db.execute('INSERT INTO rs_costs VALUES(?,?,?,?) ON CONFLICT(months,connections) DO NOTHING',
                               (months,connections,cost,now()))
            # Weekly and monthly caps start unlimited (-1) so existing installs keep their daily/active behaviour.
            for key,value in (('trial_daily','1'),('trial_active','1'),('trial_weekly','-1'),('trial_monthly','-1')):
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
            if not result:raise CheckoutError('Open Become a reseller and buy a credit pack first.')
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
        # Telegram administrator (numeric) or the website owner, whose actor string only
        # ever arrives through the HMAC-authenticated bridge in admin_web.py.
        if isinstance(uid,str) and re.fullmatch(WEB_ACTOR,uid):return
        expected=self.service.config.get('support_admin_id')
        if type(uid) is not int or not expected or uid!=expected:
            raise CheckoutError('Administrator access required.')

    def audit(self, db, actor, action, subject, reason, details=None):
        if not isinstance(reason,str) or not 3<=len(reason.strip())<=500:
            raise CheckoutError('A reason of 3–500 characters is required.')
        details=dict(details or {})
        if isinstance(actor,str):details['web_actor']=actor;actor=0  # administrator column is numeric; 0 = website owner
        db.execute('INSERT INTO rs_audit VALUES(?,?,?,?,?,?,?)',
                   (identifier(),actor,action,str(subject),reason.strip(),json.dumps(details),now()))

    def admin_create(self, actor, uid, username, credits, reason, request_key):
        """Owner sets someone up as an active reseller, optionally with starting credits, without a pack purchase."""
        self.admin(actor)
        if type(uid) is not int or not 0<uid<2**63:raise CheckoutError('Enter the reseller’s numeric Telegram ID.')
        if type(credits) is not int or not 0<=credits<=100000:raise CheckoutError('Starting credits must be a whole number from 0 to 100000.')
        if not isinstance(reason,str) or not 3<=len(reason.strip())<=500:raise CheckoutError('A reason of 3–500 characters is required.')
        username=(username or '').strip().lstrip('@') if isinstance(username,str) else ''
        if username and not re.fullmatch(r'[A-Za-z0-9_]{1,64}',username):raise CheckoutError('That Telegram username is not valid. Leave it empty if unsure.')
        existing=self.member(uid)
        if existing and existing['status']=='active':raise CheckoutError('This Telegram user is already an active reseller.')
        if existing and existing['status']=='suspended':raise CheckoutError('This reseller is suspended. Open them and reactivate instead.')
        self.register(uid,username or (existing or {}).get('username',''))
        self.account_status(actor,uid,'active',reason)
        if credits:self.adjust(actor,uid,credits,reason,request_key)
        member=self.member(uid)
        self.store.metadata('rs_onboard:'+member['id'],'due')  # the bot walks them through it the next time they open it
        return member

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
                       (identifier(),member['id'],movement,reason,reference,actor if isinstance(actor,int) else 0,now()))
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
                        settings={r['key']:r['value'] for r in db.execute('SELECT * FROM rs_settings').fetchall() if r['key'] in TRIAL_KEYS.values()})

    def configure(self, actor, category, values, reason):
        self.admin(actor);self.seed()
        with self.transaction() as db:
            if category=='package':
                pid,price,credits,active=values
                integer(price,1);integer(credits,1);integer(active,0,1)
                if not db.execute('SELECT id FROM rs_packages WHERE id=?',(pid,)).fetchone():
                    raise CheckoutError('Package not found.')
                db.execute('UPDATE rs_packages SET price_pence=?,credits=?,active=?,updated_at=? WHERE id=?',(price,credits,active,now(),pid))
            elif category=='package_add':
                price,credits=values
                integer(price,1);integer(credits,1)
                pid=str(price//100) if price%100==0 and not db.execute('SELECT 1 FROM rs_packages WHERE id=?',(str(price//100),)).fetchone() else 'pk'+secrets.token_hex(3)
                db.execute('INSERT INTO rs_packages VALUES(?,?,?,?,?)',(pid,price,credits,1,now()))
            elif category=='package_delete':
                pid,=values
                if not db.execute('SELECT id FROM rs_packages WHERE id=?',(pid,)).fetchone():raise CheckoutError('Package not found.')
                if db.execute('SELECT COUNT(*) FROM rs_packages WHERE id!=? AND active=1',(pid,)).fetchone()[0]==0 and db.execute('SELECT active FROM rs_packages WHERE id=?',(pid,)).fetchone()[0]:
                    raise CheckoutError('Keep at least one credit pack on sale.')
                db.execute('DELETE FROM rs_packages WHERE id=?',(pid,))  # past purchases keep their own snapshot of the pack
            elif category=='cost':
                months,connections,cost=values
                if months not in (1,3,6,9,12):raise CheckoutError('Invalid duration.')
                integer(connections,1,3);integer(cost,1)
                db.execute('UPDATE rs_costs SET credits=?,updated_at=? WHERE months=? AND connections=?',(cost,now(),months,connections))
            elif category=='trials':
                # (daily, active) from the Telegram command, or (daily, weekly, monthly, active) from the website. -1 = unlimited.
                if len(values)==2:limits=dict(daily=values[0],active=values[1])
                elif len(values)==4:limits=dict(zip(TRIAL_WINDOWS,values))
                else:raise CheckoutError('Invalid trial limits.')
                for name,value in limits.items():
                    integer(value,UNLIMITED,TRIAL_MAX)
                    db.execute('INSERT INTO rs_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(TRIAL_KEYS[name],str(value)))
            else:raise CheckoutError('Unknown configuration option.')
            self.audit(db,actor,'configuration',category,reason,{'values':values})

    # ---- reseller trial limits: one default for everyone, optional override per reseller ----
    @staticmethod
    def _override_key(reseller_id):
        return 'trial_limits:'+reseller_id

    def trial_limits(self, db, reseller_id=None):
        """(effective, override, default). `override` holds only the windows set for this reseller."""
        default=dict(TRIAL_DEFAULTS)
        for name,key in TRIAL_KEYS.items():
            row=db.execute('SELECT value FROM rs_settings WHERE key=?',(key,)).fetchone()
            if row and re.fullmatch(r'-?[0-9]{1,6}',str(row[0])):default[name]=int(row[0])
        override={}
        if reseller_id:
            row=db.execute('SELECT value FROM rs_settings WHERE key=?',(self._override_key(reseller_id),)).fetchone()
            try:saved=json.loads(row[0]) if row else {}
            except ValueError:saved={}
            if isinstance(saved,dict):
                override={k:v for k,v in saved.items() if k in TRIAL_WINDOWS and type(v) is int and UNLIMITED<=v<=TRIAL_MAX}
        return dict(default,**override),override,default

    def trial_usage(self, db, reseller_id):
        """Trials this reseller has used in each rolling window, and how many are running or pending now."""
        clock=now()
        usage={name:int(db.execute("SELECT count(*) FROM rs_operations WHERE reseller_id=? AND operation_type='trial' AND created_at>=? AND status!='failed'",
                                   (reseller_id,clock-seconds)).fetchone()[0]) for name,seconds in TRIAL_SECONDS.items()}
        running=db.execute("SELECT count(*) FROM rs_subscriptions WHERE reseller_id=? AND kind='trial' AND expires_at>? AND status!='disabled'",(reseller_id,clock)).fetchone()[0]
        pending=db.execute("SELECT count(*) FROM rs_operations WHERE reseller_id=? AND operation_type='trial' AND reservation='held'",(reseller_id,)).fetchone()[0]
        usage['active']=int(running)+int(pending)
        return usage

    def trial_blocked(self, db, reseller_id):
        """Name of the first limit this reseller has reached, or None when another trial is allowed."""
        limits,_,_=self.trial_limits(db,reseller_id)
        usage=self.trial_usage(db,reseller_id)
        return next((name for name in TRIAL_WINDOWS if limits[name]!=UNLIMITED and usage[name]>=limits[name]),None)

    def trial_summary(self, uid):
        member=self.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        self.seed()
        with self.store.connection() as db:
            effective,override,default=self.trial_limits(db,member['id'])
            return dict(limits={name:override.get(name) for name in TRIAL_WINDOWS},effective=effective,default=default,usage=self.trial_usage(db,member['id']))

    def set_trial_limits(self, actor, uid, limits, reason):
        """Per-reseller override. A window left as None follows the default for all resellers."""
        self.admin(actor);self.seed()
        if not isinstance(limits,dict) or set(limits)!=set(TRIAL_WINDOWS):raise CheckoutError('Invalid trial limits.')
        override={}
        for name,value in limits.items():
            if value is None:continue
            override[name]=integer(value,UNLIMITED,TRIAL_MAX)
        with self.transaction() as db:
            member=self.member(uid,db)
            if not member:raise CheckoutError('Reseller account not found.')
            self.audit(db,actor,'trial_limits',uid,reason,{'limits':override})
            key=self._override_key(member['id'])
            db.execute('DELETE FROM rs_settings WHERE key=?',(key,))
            if override:db.execute('INSERT INTO rs_settings VALUES(?,?)',(key,json.dumps(override)))
        return self.trial_summary(uid)

    def quote_purchase(self, uid, package_id, asset, request_key, with_token=False):
        self.seed()
        member=self.member(uid)
        if not member:raise CheckoutError('Open Become a reseller first.')
        if member['status']=='suspended':raise CheckoutError('Your reseller account is suspended and cannot buy credits.')
        package=next((p for p in self.packages() if p['id']==package_id and p['active']),None)
        if not package:raise CheckoutError('Credit package is unavailable.')
        from .store import digest
        gbp=f"{package['price_pence']//100}.{package['price_pence']%100:02d}"
        plan=dict(id='credits-'+package['id']+'-'+digest(json.dumps(package,sort_keys=True))[:10],
                  name=str(package['credits'])+' reseller credits',detail='£'+gbp,gbp_price=gbp,
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
            activated=db.execute("UPDATE rs_resellers SET status='active',updated_at=? WHERE id=? AND status='pending'",(now(),purchase['reseller_id'])).rowcount
            if activated:
                # First pack: the bot sends a short getting-started walkthrough with the receipt.
                db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('rs_onboard:'+purchase['reseller_id'],'due'))

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

    # ---- reporting -------------------------------------------------------------------
    @staticmethod
    def month_start(clock=None):
        from datetime import datetime, timezone
        d=datetime.fromtimestamp(clock or now(),timezone.utc)
        return int(datetime(d.year,d.month,1,tzinfo=timezone.utc).timestamp())

    def stats(self, uid):
        """Numbers for one reseller's dashboard: this month and all time."""
        member=self.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        since=self.month_start()
        def window(db,start):
            bought=db.execute('SELECT COALESCE(SUM(movement),0) FROM rs_ledger WHERE reseller_id=? AND movement>0 AND created_at>=?',(member['id'],start)).fetchone()[0]
            used=db.execute('SELECT COALESCE(-SUM(movement),0) FROM rs_ledger WHERE reseller_id=? AND movement<0 AND created_at>=?',(member['id'],start)).fetchone()[0]
            # Each column needs its own name: PostgreSQL calls every unnamed SUM "sum" and the row adapter keeps one value per name.
            row=db.execute("SELECT SUM(CASE WHEN kind='trial' OR converted_at IS NOT NULL THEN 1 ELSE 0 END) AS tests,"
                           "SUM(CASE WHEN kind='paid' AND converted_at IS NULL THEN 1 ELSE 0 END) AS subscriptions,"
                           "SUM(CASE WHEN converted_at IS NOT NULL AND converted_at>=? THEN 1 ELSE 0 END) AS converted "
                           "FROM rs_subscriptions WHERE reseller_id=? AND created_at>=?",(start,member['id'],start)).fetchone()
            tests=int(row[0] or 0);converted=int(row[2] or 0)
            return dict(credits_bought=int(bought),credits_used=int(used),tests_created=tests,subscriptions_created=int(row[1] or 0),
                        tests_converted=converted,conversion_rate=round(100*converted/tests) if tests else 0)
        with self.store.connection() as db:
            return dict(this_month=window(db,since),all_time=window(db,0))

    def summary(self, actor, search='', page=0, *, telegram_id=None):
        """Administrator list of resellers with balances, customer counts and last activity."""
        self.admin(actor);self.seed();integer(page,0,100000)
        if not isinstance(search,str) or len(search)>80:raise CheckoutError('Invalid search.')
        # Select the requested page before aggregating its subscriptions/ledger.
        # Escape LIKE metacharacters: search is a literal substring, not a pattern.
        needle=search.lower().lstrip('@')
        clauses=[];params=[]
        if needle:
            clauses.append("LOWER(CAST(r.telegram_id AS TEXT)||' '||r.username||' '||r.status) LIKE ? ESCAPE '!'")
            params.append('%'+needle.replace('!','!!').replace('%','!%').replace('_','!_')+'%')
        if telegram_id is not None:
            integer(telegram_id,1,2**63-1)
            clauses.append('r.telegram_id=?');params.append(telegram_id)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        params.extend((26,page*25,now()))
        with self.store.connection() as db:
            rows=db.execute(
                "WITH selected AS ("
                "SELECT r.id,r.telegram_id,r.username,r.status,r.created_at,a.balance,a.reserved "
                "FROM rs_resellers r JOIN rs_accounts a ON a.reseller_id=r.id"+where+
                " ORDER BY r.created_at DESC,r.id LIMIT ? OFFSET ?),"
                "customers AS (SELECT s.reseller_id,COUNT(*) AS customers,"
                "SUM(CASE WHEN s.kind='paid' AND s.expires_at>? THEN 1 ELSE 0 END) AS active_customers,"
                "MAX(s.created_at) AS last_customer FROM rs_subscriptions s "
                "JOIN selected p ON p.id=s.reseller_id GROUP BY s.reseller_id),"
                "movements AS (SELECT l.reseller_id,"
                "SUM(CASE WHEN l.movement>0 THEN l.movement ELSE 0 END) AS credits_bought,"
                "MAX(l.created_at) AS last_ledger FROM rs_ledger l "
                "JOIN selected p ON p.id=l.reseller_id GROUP BY l.reseller_id) "
                "SELECT p.*,COALESCE(c.customers,0) AS customers,"
                "COALESCE(c.active_customers,0) AS active_customers,"
                "COALESCE(m.credits_bought,0) AS credits_bought,m.last_ledger,c.last_customer "
                "FROM selected p LEFT JOIN customers c ON c.reseller_id=p.id "
                "LEFT JOIN movements m ON m.reseller_id=p.id ORDER BY p.created_at DESC,p.id",tuple(params)).fetchall()
        items=[]
        for row in rows:
            row=dict(row)
            row['credits_bought']=int(row['credits_bought'] or 0)  # PostgreSQL returns SUM() as Decimal, which the admin API would ship as a string
            row['last_activity']=max(row.pop('last_ledger') or 0,row.pop('last_customer') or 0,row['created_at'])
            row['available']=row['balance']-row['reserved']
            items.append(row)
        return items

    def report(self, actor, months=12):
        """Revenue and credit movements per month, plus per-reseller totals. Counts come from verified payments only."""
        self.admin(actor);self.seed();integer(months,1,36)
        from datetime import datetime, timezone
        with self.store.connection() as db:
            retail=db.execute("SELECT o.created_at,o.plan_json FROM orders o JOIN payments p ON p.order_id=o.id "
                              "WHERE o.kind='paid' AND o.status IN ('paid','provisioning','fulfilled')").fetchall()
            purchases=db.execute("SELECT p.created_at,p.amount_pence,p.credits,r.telegram_id FROM rs_purchases p JOIN rs_resellers r ON r.id=p.reseller_id WHERE p.status='granted'").fetchall()
            used=db.execute("SELECT created_at,-movement AS credits FROM rs_ledger WHERE movement<0").fetchall()
            converted=db.execute("SELECT converted_at FROM rs_subscriptions WHERE converted_at IS NOT NULL").fetchall()
            tests=db.execute("SELECT created_at FROM rs_subscriptions WHERE kind='trial' OR converted_at IS NOT NULL").fetchall()
        def key(ts):
            d=datetime.fromtimestamp(ts,timezone.utc);return f'{d.year:04d}-{d.month:02d}'
        buckets={}
        def bucket(ts):
            return buckets.setdefault(key(ts),dict(month=key(ts),retail_orders=0,retail_gbp=0.0,credit_packs=0,credit_gbp=0.0,credits_sold=0,credits_used=0,tests=0,tests_converted=0))
        for row in retail:
            plan=json.loads(row['plan_json'])
            if plan.get('reseller_purchase'):continue
            b=bucket(row['created_at']);b['retail_orders']+=1;b['retail_gbp']+=float(plan.get('gbp_price') or 0)
        for row in purchases:
            b=bucket(row['created_at']);b['credit_packs']+=1;b['credit_gbp']+=row['amount_pence']/100;b['credits_sold']+=row['credits']
        for row in used:bucket(row['created_at'])['credits_used']+=row['credits']
        for row in tests:bucket(row['created_at'])['tests']+=1
        for row in converted:bucket(row['converted_at'])['tests_converted']+=1
        rows=sorted(buckets.values(),key=lambda b:b['month'],reverse=True)[:months]
        for b in rows:
            b['retail_gbp']=round(b['retail_gbp'],2);b['credit_gbp']=round(b['credit_gbp'],2);b['total_gbp']=round(b['retail_gbp']+b['credit_gbp'],2)
        return dict(months=rows,resellers=self.summary(actor))
