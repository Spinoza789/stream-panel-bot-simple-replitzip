"""Durable credit reservations and provider operations. Never replay an uncertain POST."""
import json

from .panel import PanelError, ProvisioningUncertain, panel_lock
from .reseller_ledger import identifier, integer, now
from .service import CheckoutError


class Operations:
    def __init__(self,ledger,provider):
        self.ledger=ledger;self.provider=provider;self.store=ledger.store

    def owned(self,uid,sid,db=None):
        if db is None:
            with self.store.connection() as connection:return self.owned(uid,sid,connection)
        member=self.ledger.member(uid,db)
        row=db.execute('SELECT * FROM rs_subscriptions WHERE id=? AND reseller_id=? AND deleted_at IS NULL',(sid,member['id'])).fetchone() if member else None
        if not row:raise CheckoutError('Subscription not found.')
        return dict(row)

    def operation(self,uid,oid):
        member=self.ledger.member(uid)
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM rs_operations WHERE id=? AND reseller_id=?',(oid,member['id'])).fetchone() if member else None
        if not row:raise CheckoutError('Operation not found.')
        return {k:v for k,v in dict(row).items() if k!='provider_context'}

    def requests(self,uid,page=0):
        integer(page,0,100000)
        member=self.ledger.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        with self.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT id,operation_type,customer_ref,credit_cost,status,reservation,created_at FROM rs_operations WHERE reseller_id=? ORDER BY created_at DESC,id DESC LIMIT 11 OFFSET ?',
                                               (member['id'],page*10)).fetchall()]

    def preview(self,uid,kind,months,connections,adult,customer_ref='',target=None):
        self.ledger.seed()
        member=self.ledger.member(uid,active=True)
        if kind not in ('create','trial','extend'):raise CheckoutError('Invalid operation.')
        if kind=='trial':months,connections,adult=0,1,False  # 24-hour tests are always the standard (no-adult) profile
        if type(adult) is not bool:raise CheckoutError('Choose adult or no-adult content.')
        if kind=='extend':
            record=self.owned(uid,target)
            connections,adult=record['connections'],bool(record['adult'])
            customer_ref=record['customer_ref']
            try:
                with panel_lock(getattr(self.provider,'panel',None)):provider_preview=self.provider.preview_extension(record,months)
            except Exception:raise CheckoutError('Provider renewal preview is unavailable. No credits were reserved. Contact support.') from None
        else:provider_preview=None
        integer(connections,1,3)
        if months not in ((0,) if kind=='trial' else (1,3,6,9,12)):raise CheckoutError('Invalid duration.')
        if not isinstance(customer_ref,str) or len(customer_ref)>100:raise CheckoutError('Customer reference must be at most 100 characters.')
        with self.store.connection() as db:
            row=db.execute('SELECT credits FROM rs_costs WHERE months=? AND connections=?',(months,connections)).fetchone()
        cost=0 if kind=='trial' else row[0]
        try:pid=self.provider.package(months,connections,adult)
        except Exception:raise CheckoutError('Provider package is not available.') from None
        return dict(kind=kind,months=months,connections=connections,adult=adult,customer_ref=customer_ref.strip(),
                    target=target,cost=cost,available=member['available'],remaining=member['available']-cost,
                    package_id=pid,provider_preview=provider_preview)

    def reserve(self,uid,request_key,preview):
        if not isinstance(request_key,str) or not 8<=len(request_key)<=100:raise CheckoutError('Invalid confirmation.')
        from .store import digest
        key=digest(str(uid)+':'+request_key)
        member=self.ledger.member(uid)
        if member:
            with self.store.connection() as db:
                existing=db.execute('SELECT * FROM rs_operations WHERE request_key=? AND reseller_id=?',(key,member['id'])).fetchone()
            if existing:return dict(existing)
        fresh=self.preview(uid,preview['kind'],preview['months'],preview['connections'],preview['adult'],preview['customer_ref'],preview.get('target'))
        if fresh['cost']!=preview['cost'] or fresh['package_id']!=preview['package_id']:
            raise CheckoutError('Pricing changed. Review the confirmation again.')
        if fresh['kind']=='extend' and fresh['provider_preview']['previous_expiry']!=preview['provider_preview']['previous_expiry']:
            raise CheckoutError('Provider expiry changed. Review this extension again.')
        with self.ledger.transaction() as db:
            member=self.ledger.member(uid,db,active=True)
            existing=db.execute('SELECT * FROM rs_operations WHERE request_key=? AND reseller_id=?',(key,member['id'])).fetchone()
            if existing:return dict(existing)
            # Recheck configurable cost under the same lock as reservation.
            if fresh['kind']!='trial':
                actual=db.execute('SELECT credits FROM rs_costs WHERE months=? AND connections=?',(fresh['months'],fresh['connections'])).fetchone()[0]
                if actual!=fresh['cost']:raise CheckoutError('Pricing changed. Review the confirmation again.')
            if fresh['kind']=='extend':
                target=self.owned(uid,fresh['target'],db)
                if db.execute("SELECT id FROM rs_operations WHERE target_id=? AND reservation='held'",(target['id'],)).fetchone():
                    raise CheckoutError('This subscription already has a pending operation.')
                if target['expires_at']!=fresh['provider_preview']['previous_expiry']:
                    raise CheckoutError('Expiry changed. Open the subscription to refresh it first.')
            else:
                pending=db.execute("SELECT id FROM rs_operations WHERE reseller_id=? AND operation_type=? AND LOWER(customer_ref)=LOWER(?) AND reservation='held'",
                                   (member['id'],fresh['kind'],fresh['customer_ref'])).fetchone()
                if pending:
                    raise CheckoutError('This customer reference already has a pending request: '+pending[0]+'. Use My Balance → Requests. Do not submit a replacement while its result is uncertain.')
            if fresh['kind']=='trial':
                reached=self.ledger.trial_blocked(db,member['id'])
                if reached:
                    raise CheckoutError('Your reseller trial limit has been reached'+
                                        ('. Expired trials remain in history.' if reached=='active' else ' ('+reached+' allowance). It frees up as earlier trials age out.'))
            cost=fresh['cost']
            changed=db.execute('UPDATE rs_accounts SET reserved=reserved+? WHERE reseller_id=? AND balance-reserved>=?',(cost,member['id'],cost)).rowcount
            if changed!=1:raise CheckoutError('Insufficient available credits.')
            oid=identifier()
            db.execute('INSERT INTO rs_operations(id,request_key,reseller_id,operation_type,target_id,months,connections,adult,customer_ref,credit_cost,reservation,status,package_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (oid,key,member['id'],fresh['kind'],fresh.get('target'),fresh['months'],fresh['connections'],int(fresh['adult']),fresh['customer_ref'],cost,'held','queued',fresh['package_id'],now(),now()))
            return dict(db.execute('SELECT * FROM rs_operations WHERE id=?',(oid,)).fetchone())

    def complete(self,oid,account):
        """Account row, extension history, balance and ledger commit together."""
        if not isinstance(account,dict) or not all(account.get(k) for k in ('provider_id','expires_at','credentials')):
            raise PanelError('Incomplete provider confirmation')
        credentials=account['credentials']
        if not all(isinstance(credentials.get(k),str) and credentials[k] for k in ('username','password')):
            raise PanelError('Provider access details are missing')
        with self.ledger.transaction() as db:
            op=dict(db.execute('SELECT * FROM rs_operations WHERE id=?',(oid,)).fetchone())
            if op['status']=='succeeded':return
            if op['status'] not in ('processing','uncertain') or op['reservation']!='held':
                raise PanelError('Operation is not awaiting provider confirmation')
            cost=op['credit_cost']
            if op['operation_type']=='extend':
                record=db.execute('SELECT * FROM rs_subscriptions WHERE id=? AND reseller_id=?',(op['target_id'],op['reseller_id'])).fetchone()
                context=self.store.unseal(op['provider_context']) or {}
                previous=context.get('previous_expiry',(context.get('record') or {}).get('expires_at'))
                # A concurrent detail refresh may already have observed the new
                # provider expiry. Compare against the durable pre-submit value,
                # not against a mutable last-confirmed subscription cache.
                if (not record or record['provider_id']!=account['provider_id']
                        or type(previous) is not int or account['expires_at']<=previous):
                    raise PanelError('Provider extension confirmation mismatch')
                sid=record['id']
                db.execute('INSERT INTO rs_extensions VALUES(?,?,?,?,?,?,?,?,?)',
                           (identifier(),sid,op['reseller_id'],oid,op['months'],cost,previous,account['expires_at'],now()))
                db.execute("UPDATE rs_subscriptions SET kind='paid',expires_at=?,status=?,credentials=?,confirmed_at=?,"
                           "converted_at=CASE WHEN kind='trial' THEN ? ELSE converted_at END WHERE id=?",
                           (account['expires_at'],account['status'],self.store.seal(credentials),now(),now(),sid))
            else:
                existing=db.execute('SELECT id FROM rs_subscriptions WHERE provider_id=?',(account['provider_id'],)).fetchone()
                if existing:raise PanelError('Provider account already belongs to another completed operation')
                sid=identifier()
                db.execute('INSERT INTO rs_subscriptions(id,reseller_id,provider_id,customer_ref,kind,connections,adult,starts_at,expires_at,status,credentials,confirmed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (sid,op['reseller_id'],account['provider_id'],op['customer_ref'],'trial' if op['operation_type']=='trial' else 'paid',
                            op['connections'],op['adult'],account.get('starts_at') or now(),account['expires_at'],account['status'],
                            self.store.seal(credentials),now(),now()))
            db.execute('UPDATE rs_accounts SET balance=balance-?,reserved=reserved-? WHERE reseller_id=?',(cost,cost,op['reseller_id']))
            db.execute('INSERT INTO rs_ledger VALUES(?,?,?,?,?,?,?)',
                       (identifier(),op['reseller_id'],-cost,op['operation_type']+' '+str(op['months'])+' month(s)','operation:'+oid,None,now()))
            db.execute("UPDATE rs_operations SET status='succeeded',reservation='charged',result_id=?,error='',updated_at=? WHERE id=?",(sid,now(),oid))

    def fail(self,oid,reason,uncertain=False):
        with self.ledger.transaction() as db:
            row=db.execute('SELECT * FROM rs_operations WHERE id=?',(oid,)).fetchone()
            if not row or row['reservation']!='held':return
            if uncertain:
                db.execute("UPDATE rs_operations SET status='uncertain',error=?,updated_at=? WHERE id=?",
                           ('Provider outcome is uncertain. Credits remain reserved; contact support.',now(),oid))
            else:
                # Only a pre-submit/definite failure reaches this path.
                db.execute('UPDATE rs_accounts SET reserved=reserved-? WHERE reseller_id=?',(row['credit_cost'],row['reseller_id']))
                db.execute("UPDATE rs_operations SET status='failed',reservation='released',error=?,updated_at=? WHERE id=?",
                           (reason,now(),oid))

    def recover(self):
        with self.ledger.transaction() as db:
            db.execute("UPDATE rs_operations SET status='queued',updated_at=? WHERE status='preparing'",(now(),))
            db.execute("UPDATE rs_operations SET status='uncertain',error='Interrupted provider submission; reconcile before retrying.',updated_at=? WHERE status='processing'",(now(),))

    def process(self):
        with self.store.connection() as db:
            ids=[r[0] for r in db.execute("SELECT id FROM rs_operations WHERE status='queued' ORDER BY created_at,id LIMIT 2").fetchall()]
        for oid in ids:
            with panel_lock(getattr(self.provider,'panel',None)):self._process_one(oid)

    def _process_one(self,oid):
        with self.ledger.transaction() as db:
            row=db.execute("SELECT o.* FROM rs_operations o JOIN rs_resellers r ON r.id=o.reseller_id WHERE o.id=? AND o.status='queued' AND r.status='active'",(oid,)).fetchone()
            if not row:return
            op=dict(row)
            db.execute("UPDATE rs_operations SET status='preparing',updated_at=? WHERE id=?",(now(),oid))
            record=dict(db.execute('SELECT * FROM rs_subscriptions WHERE id=?',(op['target_id'],)).fetchone()) if op['target_id'] else None
        try:context=self.provider.prepare(op,record)
        except Exception:
            self.fail(oid,'Provider preparation failed before submission. Credits released; contact support.')
            return
        with self.ledger.transaction() as db:
            # Durable submission intent BEFORE the external mutation.
            db.execute("UPDATE rs_operations SET status='processing',provider_context=?,updated_at=? WHERE id=?",
                       (self.store.seal(context),now(),oid))
        try:account=self.provider.execute(op,context)
        except ProvisioningUncertain:self.fail(oid,'',uncertain=True)
        except PanelError:self.fail(oid,'Provider rejected this request before submission. Credits released.')
        except Exception:self.fail(oid,'',uncertain=True)
        else:
            try:self.complete(oid,account)
            except Exception:self.fail(oid,'',uncertain=True)

    def reconcile(self,actor,oid,provider_id=None):
        self.ledger.admin(actor)
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM rs_operations WHERE id=?',(oid,)).fetchone()
        if not row or row['status']!='uncertain' or not row['provider_context']:
            raise CheckoutError('Only uncertain submitted operations can be reconciled.')
        context=self.store.unseal(row['provider_context'])
        try:
            with panel_lock(getattr(self.provider,'panel',None)):account=self.provider.reconcile(dict(row),context,provider_id)
        except Exception:raise CheckoutError('Provider result still cannot be confirmed. Credits remain reserved. No request was resubmitted.') from None
        self.complete(oid,account)
        with self.ledger.transaction() as db:
            self.ledger.audit(db,actor,'reconcile',oid,'Provider result verified',{'provider_id':account['provider_id']})

    def refresh(self,uid,sid):
        record=self.owned(uid,sid)
        warning=None
        try:
            with panel_lock(getattr(self.provider,'panel',None)):account=self.provider.read(record['provider_id'])
            if account['provider_id']!=record['provider_id']:raise PanelError('Provider identity mismatch')
            with self.ledger.transaction() as db:
                db.execute('UPDATE rs_subscriptions SET expires_at=?,status=?,credentials=?,confirmed_at=? WHERE id=? AND reseller_id=?',
                           (account['expires_at'],account['status'],self.store.seal(account['credentials']),now(),sid,record['reseller_id']))
            record=self.owned(uid,sid)
        except Exception:warning='Provider cannot be reached or verified. Showing last-confirmed information; extensions need a fresh provider check.'
        record['credentials']=self.store.unseal(record['credentials'])
        with self.store.connection() as db:
            extensions=[dict(r) for r in db.execute('SELECT months,credits,previous_expiry,confirmed_expiry,created_at FROM rs_extensions WHERE subscription_id=? AND reseller_id=? ORDER BY created_at DESC',(sid,record['reseller_id'])).fetchall()]
        return record,warning,extensions

    def records(self,uid,filter_name='all',page=0,search=''):
        integer(page,0,100000)
        member=self.ledger.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        filters={'all':('',()),'active':(" AND kind='paid' AND expires_at>? AND status='active'",(now(),)),
                 'expiring':(" AND kind='paid' AND expires_at>? AND expires_at<=?",(now(),now()+7*86400)),
                 'expired':(" AND kind='paid' AND expires_at<=?",(now(),)),
                 'trials':(" AND kind='trial'",())}
        if filter_name not in filters or not isinstance(search,str) or len(search)>100:raise CheckoutError('Invalid filter or search.')
        suffix,params=filters[filter_name]
        matches=[];skip=page*10
        with self.store.connection() as db:
            cursor=db.execute('SELECT * FROM rs_subscriptions WHERE reseller_id=? AND deleted_at IS NULL'+suffix+' ORDER BY created_at DESC,id DESC',(member['id'],*params))
            while True:
                rows=cursor.fetchmany(100)
                if not rows:break
                for raw in rows:
                    row=dict(raw)
                    credentials=self.store.unseal(row['credentials'])
                    if search.casefold() not in (' '.join((row['customer_ref'],row.get('contact') or '',row['provider_id'],row['id'],credentials['username']))).casefold():continue
                    if skip:skip-=1;continue
                    row.pop('credentials')
                    row['username']=credentials['username']
                    matches.append(row)
                    if len(matches)==11:return matches
        return matches

    def update_notes(self,uid,sid,customer_ref,contact):
        """Reseller-only labels: a customer name and a contact (phone, Telegram handle, email). Never sent to the provider."""
        record=self.owned(uid,sid)
        for value in (customer_ref,contact):
            if not isinstance(value,str) or len(value)>100:raise CheckoutError('Notes must be at most 100 characters.')
        with self.ledger.transaction() as db:
            db.execute('UPDATE rs_subscriptions SET customer_ref=?,contact=? WHERE id=? AND reseller_id=?',
                       (customer_ref.strip(),contact.strip(),record['id'],record['reseller_id']))
        return self.owned(uid,sid)

    def counts(self,uid):
        """Dashboard numbers for one reseller: active paid, expiring within 7 days, running trials."""
        member=self.ledger.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        with self.store.connection() as db:
            row=db.execute(
                # Named columns: PostgreSQL calls every unnamed SUM "sum" and the row adapter keeps one value per name.
                "SELECT SUM(CASE WHEN kind='paid' AND status='active' AND expires_at>? THEN 1 ELSE 0 END) AS active,"
                "SUM(CASE WHEN kind='paid' AND expires_at>? AND expires_at<=? THEN 1 ELSE 0 END) AS expiring,"
                "SUM(CASE WHEN kind='trial' AND expires_at>? THEN 1 ELSE 0 END) AS trials,COUNT(*) AS total,"
                "SUM(CASE WHEN expires_at<=? OR status IN ('expired','disabled') THEN 1 ELSE 0 END) AS expired "
                "FROM rs_subscriptions WHERE reseller_id=? AND deleted_at IS NULL",(now(),now(),now()+7*86400,now(),now(),member['id'])).fetchone()
        return {'active':int(row[0] or 0),'expiring':int(row[1] or 0),'trials':int(row[2] or 0),'total':int(row[3] or 0),'expired':int(row[4] or 0)}

    @staticmethod
    def deletable(record):
        """Only finished accounts can be removed from a reseller's list: past their expiry, or expired/disabled on the provider."""
        return int(record['expires_at'])<=now() or record['status'] in ('expired','disabled')

    def delete(self,uid,sid):
        """Hide an expired subscription or test from the reseller's list. The row stays for reports and history; nothing is sent to the provider."""
        record=self.owned(uid,sid)
        if not self.deletable(record):raise CheckoutError('Only expired subscriptions and tests can be deleted. Extend it instead if the customer is staying.')
        with self.ledger.transaction() as db:
            db.execute('UPDATE rs_subscriptions SET deleted_at=? WHERE id=? AND reseller_id=? AND deleted_at IS NULL',(now(),record['id'],record['reseller_id']))
        return record

    def delete_expired(self,uid):
        """Remove every expired subscription and test from the list in one go. Returns how many were removed."""
        member=self.ledger.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        with self.ledger.transaction() as db:
            cursor=db.execute("UPDATE rs_subscriptions SET deleted_at=? WHERE reseller_id=? AND deleted_at IS NULL AND (expires_at<=? OR status IN ('expired','disabled'))",
                              (now(),member['id'],now()))
            return int(cursor.rowcount or 0)

    def refresh_listing(self,uid):
        member=self.ledger.member(uid)
        if not member:raise CheckoutError('Reseller account not found.')
        with self.store.connection() as db:
            rows=[dict(r) for r in db.execute('SELECT id,provider_id FROM rs_subscriptions WHERE reseller_id=? AND deleted_at IS NULL',(member['id'],)).fetchall()]
        if not rows:return None
        try:
            with panel_lock(getattr(self.provider,'panel',None)):
                summary=self.provider.summary() if hasattr(self.provider,'summary') else {r['provider_id']:self.provider.read(r['provider_id']) for r in rows}
            with self.ledger.transaction() as db:
                for row in rows:
                    item=summary.get(row['provider_id'])
                    if not item:continue
                    db.execute('UPDATE rs_subscriptions SET expires_at=?,status=?,confirmed_at=? WHERE id=? AND reseller_id=?',
                               (item['expires_at'],item['status'],now(),row['id'],member['id']))
            if any(row['provider_id'] not in summary for row in rows):
                return 'Some provider accounts were not found. Showing their last-confirmed information; contact support.'
        except Exception:return 'Provider unavailable. Showing last-confirmed information.'
        return None
