"""A private-chat trial/status assistant. Purchases do not run through this bot."""
import logging
import threading
import time
import requests
from .service import CheckoutError
from .store import digest

log=logging.getLogger(__name__)


class TelegramError(RuntimeError):
    def __init__(self,code=0):
        super().__init__('Telegram request failed')
        self.code=code


class TelegramBot:
    def __init__(self,service,api=None):
        self.service=service;self.store=service.store
        self.http=requests.Session();self.api=api or self.call
        from .support import SupportRelay
        self.support=SupportRelay(self)

    def call(self,method,payload):
        # Do not log URLs: Telegram's bot token is part of the URL.
        try:
            response=self.http.post('https://api.telegram.org/bot'+self.service.config['bot_token']+'/'+method,json=payload,timeout=35)
            result=response.json()
            if not response.ok or not result.get('ok'): raise TelegramError(result.get('error_code',response.status_code))
            return result['result']
        except (requests.RequestException,ValueError): raise TelegramError() from None

    def send(self,chat_id,text):
        return self.api('sendMessage',{'chat_id':chat_id,'text':text,'link_preview_options':{'is_disabled':True}})

    def trial_text(self,order):
        if order['status']=='fulfilled':
            credentials=order['credentials']
            text='Your 24-hour trial is ready.\nUsername: '+credentials['username']+'\nPassword: '+credentials['password']
            if credentials.get('server_url'): text+='\nServer: '+credentials['server_url']
            if credentials.get('expires_at'): text+='\nExpires: '+str(credentials['expires_at'])
            return text+'\nKeep these details private.'
        if order['status']=='review': return 'Your trial needs a manual account check. '+self.service.config['support']
        return 'Your trial is being prepared. I will send the details here when it is ready. You can also use /trial to check.'

    def handle(self,update):
        message=update.get('message') or {}
        chat=message.get('chat') or {};sender=message.get('from') or {}
        if chat.get('type')!='private' or chat.get('id')!=sender.get('id'): return
        uid=sender.get('id')
        if not isinstance(uid,int) or uid<=0: return
        incoming_id=message.get('message_id',update.get('update_id'))
        accepted_key='telegram_accepted:'+digest(f'{uid}:{incoming_id}') if type(incoming_id) is int else None
        if not accepted_key or not self.store.metadata(accepted_key):
            if not self.store.limit('telegram:'+str(uid),20,60):
                self.send(uid,'Please wait a minute before trying again.');return
            if accepted_key:self.store.metadata(accepted_key,'1')
        text=message.get('text','').strip()
        parts=text.split(maxsplit=1);command=(parts[0].split('@')[0].lower() if parts else '')
        try:
            if self.support.handle(message,command,parts[1] if len(parts)>1 else ''):return
            if command=='/trial':
                order=self.service.create_trial(uid)
                self.send(uid,self.trial_text(order))
                if order['status']=='fulfilled': self.store.metadata('trial_sent:'+order['id'],'1')
            elif command=='/link':
                if len(parts)!=2: self.send(uid,'Use /link CODE with the one-time code from your account page.');return
                result=self.service.link_account(parts[1].strip(),uid)
                self.send(uid,'Account linked. '+result['plan']['name']+' — '+result['status']+'. Use /status to check it.')
            elif command=='/status':
                accounts=self.service.linked_accounts(uid)
                trial=self.service.trial_status(uid)
                lines=[a['plan']['name']+' — '+a['status']+' (order '+a['id']+')' for a in accounts]
                if trial: lines.append('24-hour trial — '+trial['status'])
                self.send(uid,'\n'.join(lines) if lines else 'No account linked. You can request a free trial with /trial, or use /link CODE to link an existing account.')
            elif command=='/privacy':
                self.send(uid,'This assistant stores your numeric Telegram ID, trial history and accounts you choose to link. Login details are encrypted on the server. /contact shares messages and your Telegram identity with support. Reply routing is encrypted; message contents are copied through Telegram. Your ID is retained to enforce one trial per user. Contact support to request access or deletion. '+self.service.config['support'])
            else:
                prefix='DEMO — generated accounts are examples only.\n\n' if self.service.config['mode']=='demo' else ''
                self.send(uid,prefix+self.service.config['brand']+' account assistant\n\n/trial — request one free 24-hour trial\n/status — view linked account status\n/link CODE — link an existing account\n/contact — message support\n/support — message support\n/cancel — leave support chat\n/myid — show your Telegram user ID\n/privacy — data information\n/help — show this menu')
        except CheckoutError as exc: self.send(uid,str(exc))

    def notify_trials(self):
        with self.store.connection() as db:
            ids=[row[0] for row in db.execute("SELECT id FROM orders WHERE kind='trial' AND status='fulfilled' AND NOT EXISTS(SELECT 1 FROM metadata WHERE key='trial_sent:'||orders.id) AND NOT EXISTS(SELECT 1 FROM metadata WHERE key='trial_retry:'||orders.id AND CAST(value AS INTEGER)>?) LIMIT 5",(int(time.time()),))]
        for order_id in ids:
            order=self.store.get(order_id)
            try:
                self.send(order['telegram_id'],self.trial_text(self.service.public(order)))
                self.store.metadata('trial_sent:'+order_id,'1')
            except Exception as exc:
                if isinstance(exc,TelegramError) and exc.code==403:
                    self.store.metadata('trial_sent:'+order_id,'blocked')
                else:
                    self.store.metadata('trial_retry:'+order_id,int(time.time())+300)
                    log.warning('Trial notification deferred for order %s (%s).',order_id,type(exc).__name__)
                    break

    def run(self,stop):
        registered=False
        offset=int(self.store.metadata('telegram_offset') or '0')
        while not stop.is_set():
            try:
                if not registered:
                    self.api('getMe',{})
                    self.api('setMyCommands',{'commands':[{'command':c,'description':d} for c,d in [('start','Account assistant'),('trial','One free 24-hour trial'),('status','Linked account status'),('link','Link an existing account'),('contact','Message support'),('support','Message support'),('cancel','Leave support chat'),('myid','Show my Telegram ID'),('privacy','Data information')]]})
                    registered=True
                updates=self.api('getUpdates',{'offset':offset,'timeout':25,'allowed_updates':['message']})
                for update in updates:
                    if stop.is_set(): break
                    try: self.handle(update)
                    except TelegramError as exc:
                        if exc.code!=403: raise
                    offset=update['update_id']+1
                    self.store.metadata('telegram_offset',offset)
                self.notify_trials()
            except Exception as exc:
                log.warning('Telegram assistant paused (%s); retrying.',type(exc).__name__)
                stop.wait(5)
