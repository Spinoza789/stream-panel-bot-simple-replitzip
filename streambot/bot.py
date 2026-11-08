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

    def send(self,chat_id,text,reply_markup=None):
        payload={'chat_id':chat_id,'text':text,'link_preview_options':{'is_disabled':True}}
        if reply_markup: payload['reply_markup']=reply_markup
        return self.api('sendMessage',payload)

    def menu_keyboard(self):
        return {'inline_keyboard':[
            [{'text':'🌐 Membership plans','callback_data':'menu:plans'}],
            [{'text':'🎁 Start 24-hour trial','callback_data':'menu:trial'}],
            [{'text':'📋 My account','callback_data':'menu:status'},
             {'text':'💬 Contact support','callback_data':'menu:contact'}],
            [{'text':'ℹ️ About','callback_data':'menu:about'},
             {'text':'🔒 Privacy','callback_data':'menu:privacy'}],
        ]}

    def menu_text(self):
        prices=[]
        for plan in self.service.config.get('plans',[]):
            try: prices.append(float(plan['gbp_price']))
            except (KeyError,TypeError,ValueError): pass
        starting_price=('Plans from £'+format(min(prices),'.2f').rstrip('0').rstrip('.')
                        if prices else 'Flexible membership plans')
        demo=('🧪 DEMO MODE — orders and accounts are simulations. No real payments are accepted.\n\n'
              if self.service.config['mode']=='demo' else '')
        return (demo+'✨ '+self.service.config['brand']+' · MEMBER ACCESS\n\n'
                'Your subscription, trial and account in one place.\n'
                +starting_price+' · Choose an option below.')

    def plans_text(self):
        lines=['🌐 MEMBERSHIP PLANS','']
        for plan in self.service.config.get('plans',[]):
            price=plan.get('gbp_price')
            amount=' — £'+str(price).rstrip('0').rstrip('.') if price else ''
            detail=plan.get('detail','')
            lines.append('• '+plan['name']+amount+(' · '+detail if detail else ''))
        if self.service.config['mode']=='demo':
            lines.extend(['','Demo mode only — no real payment or account is created.'])
        else:
            lines.extend(['','Open the membership checkout to continue.'])
        return '\n'.join(lines)

    def status_text(self,uid):
        accounts=self.service.linked_accounts(uid)
        trial=self.service.trial_status(uid)
        lines=[a['plan']['name']+' — '+a['status']+' (order '+a['id']+')' for a in accounts]
        if trial: lines.append('24-hour trial — '+trial['status'])
        return ('\n'.join(lines) if lines else
                'No account linked yet. Start a trial or use /link CODE to link an existing account.')

    def trial_text(self,order):
        if order['status']=='fulfilled':
            credentials=order['credentials']
            text='Your 24-hour trial is ready.\nUsername: '+credentials['username']+'\nPassword: '+credentials['password']
            if credentials.get('server_url'): text+='\nServer: '+credentials['server_url']
            if credentials.get('expires_at'): text+='\nExpires: '+str(credentials['expires_at'])
            return text+'\nKeep these details private.'
        if order['status']=='review': return 'Your trial needs a manual account check. '+self.service.config['support']
        return 'Your trial is being prepared. I will send the details here when it is ready. You can also use /trial to check.'

    def handle_callback(self,query):
        callback_id=query.get('id')
        sender=query.get('from') or {}
        message=query.get('message') or {}
        chat=message.get('chat') or {}
        uid=sender.get('id')
        if (not isinstance(callback_id,str) or not isinstance(uid,int) or uid<=0
                or chat.get('type')!='private' or chat.get('id')!=uid):
            if isinstance(callback_id,str):
                self.api('answerCallbackQuery',{'callback_query_id':callback_id,
                                                'text':'Open this menu in a private chat.'})
            return
        if not self.store.limit('telegram:'+str(uid),20,60):
            self.api('answerCallbackQuery',{'callback_query_id':callback_id,
                                            'text':'Please wait a minute before trying again.'})
            return
        action=query.get('data','')
        allowed={'menu','menu:plans','menu:trial','menu:status','menu:contact','menu:about','menu:privacy'}
        if not isinstance(action,str) or action not in allowed:
            self.api('answerCallbackQuery',{'callback_query_id':callback_id,
                                            'text':'This menu option is unavailable.'})
            return
        self.api('answerCallbackQuery',{'callback_query_id':callback_id})
        try:
            if action=='menu':
                text=self.menu_text()
            elif action=='menu:plans':
                text=self.plans_text()
            elif action=='menu:trial':
                text=self.trial_text(self.service.create_trial(uid))
            elif action=='menu:status':
                text=self.status_text(uid)
            elif action=='menu:contact':
                if uid==self.support.admin:
                    text='You are the support administrator. Reply to a customer support message received by this bot.'
                elif not self.support.admin:
                    text='Bot support is not connected yet. Contact us directly:\n'+self.support.contact_text()
                else:
                    self.store.metadata(self.support.session_key(uid),int(time.time())+86400)
                    text=('Support chat is open. Send a message here and it will be shared with support. '
                          'Use /cancel to close the chat.\n\n'+self.support.contact_text())
            elif action=='menu:about':
                text=(self.service.config['brand']+' provides subscription access and account support.\n'
                      'Choose Membership plans to review available options, or contact support for help.')
            else:
                text=('This assistant stores your Telegram ID, trial history and accounts you choose to link. '
                      'Login details are encrypted. Using contact support shares your identity and messages '
                      'with support. Use /contact for data requests.')
            self.send(uid,text,self.menu_keyboard())
        except CheckoutError as exc:
            self.send(uid,str(exc),self.menu_keyboard())

    def handle(self,update):
        if update.get('callback_query'):
            self.handle_callback(update['callback_query'])
            return
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
            if command in ('/start','/help') or not command:
                self.send(uid,self.menu_text(),self.menu_keyboard())
            elif command=='/trial':
                order=self.service.create_trial(uid)
                self.send(uid,self.trial_text(order),self.menu_keyboard())
                if order['status']=='fulfilled': self.store.metadata('trial_sent:'+order['id'],'1')
            elif command=='/link':
                if len(parts)!=2: self.send(uid,'Use /link CODE with the one-time code from your account page.');return
                result=self.service.link_account(parts[1].strip(),uid)
                self.send(uid,'Account linked. '+result['plan']['name']+' — '+result['status']+'. Use /status to check it.',self.menu_keyboard())
            elif command=='/status':
                self.send(uid,self.status_text(uid),self.menu_keyboard())
            elif command=='/privacy':
                self.send(uid,'This assistant stores your numeric Telegram ID, trial history and accounts you choose to link. Login details are encrypted on the server. /contact shares messages and your Telegram identity with support. Reply routing is encrypted; message contents are copied through Telegram. Your ID is retained to enforce one trial per user. Contact support to request access or deletion. '+self.service.config['support'],self.menu_keyboard())
            else:
                self.send(uid,self.menu_text(),self.menu_keyboard())
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
                updates=self.api('getUpdates',{'offset':offset,'timeout':25,'allowed_updates':['message','callback_query']})
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
