"""Durable, consent-aware Telegram delivery. No provider writes or financial changes."""
import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from .store import digest

log=logging.getLogger(__name__)
def now():return int(time.time())
def london(value):return datetime.fromtimestamp(value,ZoneInfo('Europe/London')).strftime('%d %b %Y, %H:%M %Z')


class Notifications:
    def __init__(self,bot):
        self.bot=bot;self.store=bot.store;self.service=bot.service
        self.next_scan=0;self.backlog=False
        try:
            with self.store.connection() as db:db.execute('SELECT telegram_id FROM nt_contacts WHERE 1=0')
            self.ready=True
        except Exception:self.ready=False

    def contact(self,uid,incoming=False):
        if not self.ready:return
        with self.store.connection() as db:
            db.execute('INSERT INTO nt_contacts(telegram_id,updated_at) VALUES(?,?) ON CONFLICT(telegram_id) DO NOTHING',(uid,now()))
            if incoming:db.execute('UPDATE nt_contacts SET blocked=0,updated_at=? WHERE telegram_id=?',(now(),uid))

    def preferences(self,uid):
        self.contact(uid)
        with self.store.connection() as db:return dict(db.execute('SELECT * FROM nt_contacts WHERE telegram_id=?',(uid,)).fetchone())

    def preference(self,uid,field,value):
        if field not in ('alerts','deals') or value not in (0,1):raise ValueError('Invalid preference')
        self.contact(uid)
        with self.store.connection() as db:
            db.execute('UPDATE nt_contacts SET '+field+'=?,updated_at=? WHERE telegram_id=?',(value,now(),uid))

    def recover(self):
        if self.ready:
            with self.store.connection() as db:
                # Telegram has no sendMessage idempotency key. A crash after
                # acceptance cannot safely be replayed without risking duplicates.
                db.execute("UPDATE nt_deliveries SET status='uncertain',updated_at=? WHERE status='sending'",(now(),))

    def sources(self):
        with self.store.connection() as db:
            rows=db.execute("SELECT o.id,o.kind,o.credentials,COALESCE(o.telegram_id,a.telegram_id) AS uid "
                            "FROM orders o LEFT JOIN account_links a ON a.order_id=o.id "
                            "WHERE o.status='fulfilled' AND o.credentials IS NOT NULL "
                            "AND (o.telegram_id IS NOT NULL OR a.telegram_id IS NOT NULL)").fetchall()
            rs=[]
            if self.service.resellers.ready:
                rs=db.execute("SELECT s.*,r.telegram_id AS uid FROM rs_subscriptions s JOIN rs_resellers r ON r.id=s.reseller_id WHERE s.deleted_at IS NULL").fetchall()
        records=[]
        for row in rows:
            try:credentials=self.store.unseal(row['credentials'])
            except Exception:continue
            pid=credentials.get('panel_id') if isinstance(credentials,dict) else None
            if pid:records.append(dict(uid=row['uid'],provider_id=str(pid),kind=row['kind'],source='retail',reference='',order_id=row['id']))
        for row in rs:
            records.append(dict(uid=row['uid'],provider_id=row['provider_id'],kind=row['kind'],source='reseller',reference=row['customer_ref'],subscription_id=row['id']))
        return records

    def provider_status(self,records):
        provider=self.service.resellers.ops.provider
        if self.service.config['mode']=='live':return provider.summary()
        results={}
        for record in records:
            try:results[record['provider_id']]=provider.read(record['provider_id'])
            except Exception:continue
        return results

    @staticmethod
    def bucket(kind,expiry,clock):
        remaining=expiry-clock
        if -86400<remaining<=0:return 'expired'
        if kind=='trial' or remaining<=0:return None
        for days in (1,3,7):
            if remaining<=days*86400:return str(days)+'day'
        return None

    def enqueue_expiries(self,records,statuses):
        for record in records:
            actual=statuses.get(record['provider_id'])
            if not actual or actual['status']=='disabled':continue
            expiry=actual['expires_at'];bucket=self.bucket(record['kind'],expiry,now())
            if not bucket:continue
            uid=record['uid'];self.contact(uid)
            preference=self.preferences(uid)
            if not preference['alerts'] or preference['blocked']:continue
            subject=dict(record,expiry=expiry,bucket=bucket)
            key=digest('expiry:'+str(uid)+':'+record['provider_id']+':'+str(expiry)+':'+bucket)
            with self.store.connection() as db:
                db.execute("INSERT INTO nt_deliveries(id,telegram_id,kind,subject,status,due_at,created_at,updated_at) "
                           "VALUES(?,?,'expiry',?,'pending',?,?,?) ON CONFLICT(id) DO NOTHING",
                           (key,uid,json.dumps(subject),now(),now(),now()))

    def eligible(self,audience):
        if audience not in ('all','retail','resellers'):raise ValueError('Invalid audience')
        with self.store.connection() as db:
            rows=db.execute('SELECT c.telegram_id,r.status FROM nt_contacts c LEFT JOIN rs_resellers r ON r.telegram_id=c.telegram_id '
                            "WHERE c.deals=1 AND c.blocked=0 AND (r.status IS NULL OR r.status='active') ORDER BY c.telegram_id").fetchall()
        return [r['telegram_id'] for r in rows if audience=='all' or (audience=='retail')==(r['status'] is None)]

    def queue_campaign(self,actor,draft):
        self.service.resellers.finance.admin(actor)
        if draft['expires']<=now():raise ValueError('Preview expired')
        eligible=set(self.eligible(draft['audience']))
        recipients=[uid for uid in draft['recipients'] if uid in eligible]
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT id FROM nt_campaigns WHERE id=?',(draft['id'],)).fetchone()
            if existing:return draft['id']
            db.execute("INSERT INTO nt_campaigns VALUES(?,?,?,?,'queued',?)",(draft['id'],actor,draft['body'],draft['audience'],now()))
            for uid in recipients:
                db.execute("INSERT INTO nt_deliveries(id,telegram_id,kind,subject,campaign_id,status,due_at,created_at,updated_at) "
                           "VALUES(?,?,'deal','{}',?,'pending',?,?,?)",
                           (digest('deal:'+draft['id']+':'+str(uid)),uid,draft['id'],now(),now(),now()))
            db.execute('DELETE FROM metadata WHERE key=?',('nt_draft:'+str(actor),))
        return draft['id']

    def campaigns(self,actor):
        self.service.resellers.finance.admin(actor)
        with self.store.connection() as db:
            rows=db.execute('SELECT * FROM nt_campaigns ORDER BY created_at DESC,id DESC LIMIT 5').fetchall()
            result=[]
            for row in rows:
                counts={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM nt_deliveries WHERE campaign_id=? GROUP BY status',(row['id'],)).fetchall()}
                result.append(dict(row,counts=counts))
        return result

    def cancel(self,actor,cid):
        self.service.resellers.finance.admin(actor)
        with self.store.connection() as db:
            db.execute("UPDATE nt_campaigns SET status='cancelled' WHERE id=?",(cid,))
            db.execute("UPDATE nt_deliveries SET status='cancelled',updated_at=? WHERE campaign_id=? AND status IN ('pending','retry')",(now(),cid))

    def _message(self,row,statuses):
        uid=row['telegram_id'];prefs=self.preferences(uid)
        if prefs['blocked']:return None
        settings={'text':'Notification settings','callback_data':'nt:settings'}
        if row['kind']=='deal':
            if not prefs['deals']:return None
            with self.store.connection() as db:campaign=db.execute('SELECT * FROM nt_campaigns WHERE id=?',(row['campaign_id'],)).fetchone()
            if not campaign or campaign['status']=='cancelled' or uid not in self.eligible(campaign['audience']):return None
            return campaign['body']+'\n\nYou opted in to deals. Use /stopdeals to unsubscribe.',{'inline_keyboard':[[settings]]}
        if not prefs['alerts']:return None
        subject=json.loads(row['subject']);actual=statuses.get(subject['provider_id'])
        owner=next((r for r in self.sources() if r['uid']==uid and r['provider_id']==subject['provider_id'] and r['kind']==subject['kind']),None)
        if not owner:return None
        subject.update(source=owner['source'],reference=owner['reference'])
        if (not actual or actual['status']=='disabled' or actual['expires_at']!=subject['expiry']
                or self.bucket(subject['kind'],actual['expires_at'],now())!=subject['bucket']):return None
        label='24-hour trial' if subject['kind']=='trial' else 'subscription'
        prefix='Your '+label+(' has expired.' if subject['bucket']=='expired' else ' expires soon.')
        if subject['source']=='reseller':
            prefix='Customer '+label+(' has expired.' if subject['bucket']=='expired' else ' expires soon.')
        text=prefix+'\nExpiry: '+london(subject['expiry'])
        if subject['reference']:text+='\nCustomer reference: '+subject['reference']
        text+='\nAccount ID: '+subject['provider_id']
        text+='\n\nNothing has been renewed or charged yet.'
        if subject['source']=='reseller':
            sid=owner.get('subscription_id')
            rows=[[{'text':'➕ Extend 1 month','callback_data':'rs:extendnow:'+sid+':1'},{'text':'Other lengths','callback_data':'rs:extend:'+sid}],
                  [{'text':'Open this customer','callback_data':'rs:detail:'+sid}]] if sid else [[{'text':'Reseller area','callback_data':'rs:home'}]]
        elif subject['kind']=='trial':
            rows=[[{'text':'Membership plans','callback_data':'menu:plans'}]]
        else:
            oid=owner.get('order_id')
            rows=[[{'text':'🔁 Renew this subscription','callback_data':'pay:renew:'+oid}],[{'text':'Membership plans','callback_data':'menu:plans'}]] if oid else [[{'text':'Membership plans','callback_data':'menu:plans'}]]
        return text,{'inline_keyboard':rows+[[settings]]}

    def tick(self):
        if not self.ready:return
        statuses=None
        if now()>=self.next_scan:
            try:
                records=self.sources()
                statuses=self.provider_status(records) if records else {}
                self.enqueue_expiries(records,statuses)
                self.next_scan=now()+300
            except Exception:
                self.next_scan=now()+300
                log.warning('Expiry reminder scan deferred; provider status could not be verified.')
        pause=self.store.metadata('nt_pause_until')
        if pause and int(pause)>now():
            self.backlog=False;return
        with self.store.connection() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM nt_deliveries WHERE status IN ('pending','retry') AND due_at<=? ORDER BY due_at,id LIMIT 5",(now(),)).fetchall()]
        if any(r['kind']=='expiry' for r in rows) and statuses is None:
            try:statuses=self.provider_status([json.loads(r['subject']) for r in rows if r['kind']=='expiry'])
            except Exception:statuses=None
        for row in rows:
            last=int(self.store.metadata('nt_last_send:'+str(row['telegram_id'])) or 0)
            if last and now()-last<2:
                with self.store.connection() as db:db.execute('UPDATE nt_deliveries SET due_at=? WHERE id=?',(last+2,row['id']))
                continue
            if row['kind']=='expiry' and statuses is None:
                with self.store.connection() as db:db.execute('UPDATE nt_deliveries SET due_at=? WHERE id=?',(now()+300,row['id']))
                continue
            with self.store.connection() as db:
                changed=db.execute("UPDATE nt_deliveries SET status='sending',attempts=attempts+1,updated_at=? WHERE id=? AND status IN ('pending','retry')",(now(),row['id'])).rowcount
            if not changed:continue
            status='sent';due=now()
            try:
                message=self._message(row,statuses or {})
                if message:
                    self.bot.send(row['telegram_id'],*message)
                    self.store.metadata('nt_last_send:'+str(row['telegram_id']),now())
                else:status='cancelled'
            except Exception as exc:
                code=getattr(exc,'code',0)
                if code==403:
                    status='blocked'
                    with self.store.connection() as db:db.execute('UPDATE nt_contacts SET blocked=1 WHERE telegram_id=?',(row['telegram_id'],))
                elif code==429:
                    status='retry';due=now()+max(30,getattr(exc,'retry_after',300))
                    self.store.metadata('nt_pause_until',due)
                elif 400<=code<500:status='failed'
                else:status='uncertain'
            with self.store.connection() as db:
                db.execute('UPDATE nt_deliveries SET status=?,due_at=?,updated_at=? WHERE id=?',(status,due,now(),row['id']))
            if status=='retry':break
        with self.store.connection() as db:
            db.execute("UPDATE nt_campaigns SET status='completed' WHERE status='queued' "
                       "AND NOT EXISTS(SELECT 1 FROM nt_deliveries d WHERE d.campaign_id=nt_campaigns.id AND d.status IN ('pending','retry','sending'))")
            self.backlog=bool(db.execute("SELECT id FROM nt_deliveries WHERE status IN ('pending','retry') AND due_at<=? LIMIT 1",(now(),)).fetchone())
