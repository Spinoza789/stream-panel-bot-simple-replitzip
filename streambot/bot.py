"""Private membership, support, and custom blockchain-payment assistant."""
import logging
import re
import threading
import time
import requests
from .service import CheckoutError
from .store import digest
from .trial_message import trial_ready_text

log=logging.getLogger(__name__)


class TelegramError(RuntimeError):
    def __init__(self,code=0,method='',retry_after=300):
        super().__init__('Telegram request failed')
        self.code=code if type(code) is int else 0
        self.method=method
        self.retry_after=retry_after if type(retry_after) is int and 1<=retry_after<=3600 else 300


class TelegramBot:
    def __init__(self,service,api=None):
        self.service=service;self.store=service.store
        self.http=requests.Session();self.api=api or self.call
        from .support import SupportRelay
        self.support=SupportRelay(self)
        from .telegram_payments import TelegramCheckout
        self.checkout=TelegramCheckout(self)
        from .reseller_bot import ResellerBot
        self.reseller=ResellerBot(self)
        from .notification_bot import NotificationBot
        self.notifications=NotificationBot(self)
        from .trial_recovery import TrialRecovery
        self.trial_recovery=TrialRecovery(self)

    def call(self,method,payload):
        # Do not log URLs: Telegram's bot token is part of the URL.
        try:
            response=self.http.post('https://api.telegram.org/bot'+self.service.config['bot_token']+'/'+method,json=payload,timeout=35)
            result=response.json()
            if not response.ok or not result.get('ok'):
                raise TelegramError(result.get('error_code',response.status_code),method,(result.get('parameters') or {}).get('retry_after',300))
            return result['result']
        except (requests.RequestException,ValueError): raise TelegramError(method=method) from None

    def send(self,chat_id,text,reply_markup=None,*,parse_mode=None):
        payload={'chat_id':chat_id,'text':text,'link_preview_options':{'is_disabled':True}}
        if reply_markup: payload['reply_markup']=reply_markup
        if parse_mode: payload['parse_mode']=parse_mode
        return self.api('sendMessage',payload)

    def answer_callback(self,payload):
        try:
            self.api('answerCallbackQuery',payload)
        except TelegramError as exc:
            # Telegram expires callback acknowledgements quickly. An old click
            # must not block this update and every newer message in the queue.
            if exc.code!=400: raise

    def menu_keyboard(self):
        return {'inline_keyboard':[
            [{'text':'🌐 Membership plans','callback_data':'menu:plans'}],
            [{'text':'🎁 Start 24-hour trial','callback_data':'menu:trial'}],
            [{'text':'💳 My orders','callback_data':'pay:orders'}],
            [{'text':'Reseller area','callback_data':'rs:home'}],
            [{'text':'Notifications & deals','callback_data':'nt:settings'}],
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

    def find_plan(self,months,adult,connections=None):
        for plan in self.service.config.get('plans',[]):
            if (plan.get('months')==months
                    and bool(plan.get('adult_content',False))==adult
                    and (connections is None or plan.get('connections')==connections)):
                return plan
        return None

    def duration_keyboard(self):
        durations=sorted({p['months'] for p in self.service.config.get('plans',[])})
        buttons=[[{'text':f'📅 {months} month'+('s' if months!=1 else ''),
                   'callback_data':f'plan:duration:{months}'} for months in durations[i:i+2]]
                 for i in range(0,len(durations),2)]
        buttons.append([{'text':'⬅️ Back','callback_data':'menu'}])
        return {'inline_keyboard':buttons}

    def content_keyboard(self,months):
        return {'inline_keyboard':[
            [{'text':'🚫 No adult content','callback_data':f'plan:content:{months}:0'},
             {'text':'🔞 Adult content','callback_data':f'plan:content:{months}:1'}],
            [{'text':'⬅️ Back','callback_data':'plan:back:duration'}],
        ]}

    def connection_keyboard(self,months,adult):
        buttons=[]
        for connections in sorted({p['connections'] for p in self.service.config.get('plans',[])
                                   if p.get('months')==months and bool(p.get('adult_content',False))==adult}):
            plan=self.find_plan(months,adult,connections)
            if plan:
                price='£'+format(float(plan['gbp_price']),'.2f').rstrip('0').rstrip('.')
                buttons.append({'text':f'{connections} connection'+('s' if connections!=1 else '')+f' · {price}',
                                'callback_data':f'plan:connections:{months}:{int(adult)}:{connections}'})
        return {'inline_keyboard':[
            buttons,
            [{'text':'⬅️ Back','callback_data':f'plan:back:content:{months}:{int(adult)}'}],
        ]}

    def selection_keyboard(self,months,adult,connections):
        plan=self.find_plan(months,adult,connections)
        return {'inline_keyboard':[
            [{'text':'Choose payment crypto','callback_data':'pay:choose:'+plan['id']}],
            [{'text':'⬅️ Back','callback_data':f'plan:back:connections:{months}:{int(adult)}'}],
            [{'text':'🏠 Main menu','callback_data':'menu'}],
        ]}

    def membership_step(self,action):
        parts=action.split(':')
        if parts==['plan','back','duration']:
            return '🌐 MEMBERSHIP PLANS\n\nChoose a subscription length:',self.duration_keyboard()
        if len(parts)==3 and parts[:2]==['plan','duration']:
            months=int(parts[2])
            if months not in {p.get('months') for p in self.service.config.get('plans',[])}:
                raise CheckoutError('That membership length is unavailable.')
            return f'📅 {months} month'+('s' if months!=1 else '')+'\n\nInclude adult content?',self.content_keyboard(months)
        if parts[:2]==['plan','content'] and len(parts)==4:
            months=int(parts[2]);adult=parts[3]
            if adult not in ('0','1') or not any(p.get('months')==months and bool(p.get('adult_content',False))==(adult=='1') for p in self.service.config.get('plans',[])):
                raise CheckoutError('That content option is unavailable.')
            label='With adult content' if adult=='1' else 'No adult content'
            return f'{label}\n\nChoose the number of connections:',self.connection_keyboard(months,adult=='1')
        if parts[:3]==['plan','back','content'] and len(parts)==5:
            months=int(parts[3]);adult=parts[4]
            if adult not in ('0','1') or not self.find_plan(months,adult=='1'):
                raise CheckoutError('That membership option is unavailable.')
            return f'📅 {months} month'+('s' if months!=1 else '')+'\n\nInclude adult content?',self.content_keyboard(months)
        if parts[:2]==['plan','connections'] and len(parts)==5:
            months=int(parts[2]);adult=parts[3];connections=int(parts[4])
            if adult not in ('0','1'):
                raise CheckoutError('That content option is unavailable.')
            plan=self.find_plan(months,adult=='1',connections)
            if not plan: raise CheckoutError('That membership option is unavailable.')
            content='With adult content' if adult=='1' else 'No adult content'
            price='£'+format(float(plan['gbp_price']),'.2f').rstrip('0').rstrip('.')
            text=('✅ MEMBERSHIP SELECTED\n\n'+plan['name']+' · '+content+' · '
                  +str(connections)+' connection'+('s' if connections!=1 else '')
                  +' · '+price+'\n\nSelection only — no order or payment has been created.')
            return text,self.selection_keyboard(months,adult=='1',connections)
        if parts[:3]==['plan','back','connections'] and len(parts)==5:
            months=int(parts[3]);adult=parts[4]
            if adult not in ('0','1') or not self.find_plan(months,adult=='1'):
                raise CheckoutError('That membership option is unavailable.')
            content='With adult content' if adult=='1' else 'No adult content'
            return f'{content}\n\nChoose the number of connections:',self.connection_keyboard(months,adult=='1')
        raise CheckoutError('That membership option is unavailable. Start again from Membership plans.')

    def status_text(self,uid):
        accounts=self.service.linked_accounts(uid)
        trial=self.service.trial_status(uid)
        lines=[a['plan']['name']+' — '+a['status']+' (order '+a['id']+')' for a in accounts]
        if trial: lines.append('24-hour trial — '+trial['status'])
        return ('\n'.join(lines) if lines else
                'No account linked yet. Start a trial or use /link CODE to link an existing account.')

    def trial_text(self,order):
        if order['status']=='fulfilled':
            return trial_ready_text(order['credentials'])
        if order['status']=='review':
            if order.get('account_identity_unknown'):
                return ('Your panel-generated trial could not be confirmed. Support must identify the account '
                        'before another creation is attempted. '+self.service.config['support'])
            return ('Your trial could not be confirmed. Tap Check / retry trial to check for an existing account '
                    'before retrying this same request, or use /retrytrial. '+self.service.config['support'])
        return 'Your trial is being prepared. I will send the details here when it is ready. You can also use /trial to check.'

    def trial_keyboard(self,order):
        if order['status']=='review':
            if order.get('account_identity_unknown'):
                return {'inline_keyboard':[[{'text':'Contact support','callback_data':'menu:contact'}],
                                           [{'text':'Back to main menu','callback_data':'menu'}]]}
            return {'inline_keyboard':[[{'text':'Check / retry trial','callback_data':'menu:retrytrial'}],
                                       [{'text':'Back to main menu','callback_data':'menu'}]]}
        return self.menu_keyboard()

    def handle_callback(self,query):
        callback_id=query.get('id')
        sender=query.get('from') or {}
        message=query.get('message') or {}
        chat=message.get('chat') or {}
        uid=sender.get('id')
        if (not isinstance(callback_id,str) or not isinstance(uid,int) or uid<=0
                or chat.get('type')!='private' or chat.get('id')!=uid):
            if isinstance(callback_id,str):
                self.answer_callback({'callback_query_id':callback_id,
                                                'text':'Open this menu in a private chat.'})
            return
        if not self.store.limit('telegram:'+str(uid),20,60):
            self.answer_callback({'callback_query_id':callback_id,
                                            'text':'Please wait a minute before trying again.'})
            return
        action=query.get('data','')
        allowed={'menu','menu:plans','menu:trial','menu:retrytrial','menu:status','menu:contact','menu:about','menu:privacy'}
        if not isinstance(action,str) or (action not in allowed and not action.startswith(('plan:','pay:','rs:','nt:','tr:'))):
            self.answer_callback({'callback_query_id':callback_id,
                                            'text':'This menu option is unavailable.'})
            return
        self.answer_callback({'callback_query_id':callback_id})
        try:
            self.notifications.contact(uid,incoming=True)
            if self.trial_recovery.callback(uid,action):return
            if self.notifications.callback(uid,action):return
            if self.reseller.callback(uid,action,sender):return
            member=self.service.resellers.member(uid)
            if action=='menu' and member:
                self.reseller.home(uid);return
            if member and member['status']!='active' and action.startswith(('pay:','plan:','menu:trial','menu:retrytrial')):
                raise CheckoutError('Your reseller account must be approved and active for this action.')
            if action.startswith('pay:'):
                self.checkout.handle_callback(uid,action,callback_id)
                return
            self.checkout.clear_session(uid)
            markup=self.menu_keyboard()
            if action.startswith('plan:'):
                text,markup=self.membership_step(action)
            elif action=='menu':
                text=self.menu_text()
            elif action=='menu:plans':
                text,markup=('🌐 MEMBERSHIP PLANS\n\nChoose a subscription length:',
                             self.duration_keyboard())
            elif action in ('menu:trial','menu:retrytrial'):
                order=self.service.retry_trial(uid) if action=='menu:retrytrial' else self.service.create_trial(uid)
                text,markup=self.trial_text(order),self.trial_keyboard(order)
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
                      'with support. Notification preferences and delivery history are stored; deals require opt-in. '
                      'Use /notifications to manage reminders or /contact for data requests.')
            self.send(uid,text,markup)
        except CheckoutError as exc:
            self.send(uid,str(exc),self.menu_keyboard())
        except ValueError:
            self.send(uid,'That membership option is invalid. Please choose Membership plans to start again.',
                      self.menu_keyboard())

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
            self.notifications.contact(uid,incoming=True)
            if self.trial_recovery.message(uid,command,parts[1] if len(parts)>1 else ''):return
            if self.notifications.message(uid,command,parts[1] if len(parts)>1 else ''):return
            if self.reseller.message(message,command,parts[1] if len(parts)>1 else ''):return
            if command=='/retrytrial':
                self.checkout.clear_session(uid)
                order=self.service.retry_trial(uid)
                self.send(uid,self.trial_text(order),self.trial_keyboard(order))
                if order['status']=='fulfilled': self.store.metadata('trial_sent:'+order['id'],'1')
                return
            if self.checkout.handle_message(message,command):return
            if self.support.handle(message,command,parts[1] if len(parts)>1 else ''):return
            if command in ('/start','/help') or not command:
                self.send(uid,self.menu_text(),self.menu_keyboard())
            elif command=='/trial':
                order=self.service.create_trial(uid)
                self.send(uid,self.trial_text(order),self.trial_keyboard(order))
                if order['status']=='fulfilled': self.store.metadata('trial_sent:'+order['id'],'1')
            elif command=='/link':
                if len(parts)!=2: self.send(uid,'Use /link CODE with the one-time code from your account page.');return
                result=self.service.link_account(parts[1].strip(),uid)
                self.send(uid,'Account linked. '+result['plan']['name']+' — '+result['status']+'. Use /status to check it.',self.menu_keyboard())
            elif command=='/status':
                self.send(uid,self.status_text(uid),self.menu_keyboard())
            elif command=='/privacy':
                self.send(uid,'This assistant stores your numeric Telegram ID, trial history and accounts you choose to link. Login details are encrypted on the server. Notification preferences and delivery history are stored; deals require opt-in. Use /notifications to manage reminders. /contact shares messages and your Telegram identity with support. Reply routing is encrypted; message contents are copied through Telegram. Your ID is retained to enforce one trial per user. Contact support to request access or deletion. '+self.service.config['support'],self.menu_keyboard())
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
        offset=None
        while not stop.is_set():
            stage='offset_load'
            try:
                if offset is None:
                    offset=int(self.store.metadata('telegram_offset') or '0')
                if not registered:
                    stage='registration'
                    self.notifications.recover()
                    self.api('getMe',{})
                    self.api('setMyCommands',{'commands':[{'command':c,'description':d} for c,d in [('start','Account assistant'),('trial','One free 24-hour trial'),('status','Linked account status'),('link','Link an existing account'),('notifications','Reminders and optional deals'),('contact','Message support'),('support','Message support'),('cancel','Leave support chat'),('myid','Show my Telegram ID'),('privacy','Data information')]]})
                    registered=True
                stage='poll'
                updates=self.api('getUpdates',{'offset':offset,'timeout':0 if self.notifications.backlog else 25,'allowed_updates':['message','callback_query']})
                for update in updates:
                    if stop.is_set(): break
                    stage='handle_update'
                    try: self.handle(update)
                    except TelegramError as exc:
                        if exc.code!=403: raise
                    stage='save_offset'
                    next_offset=update['update_id']+1
                    self.store.metadata('telegram_offset',next_offset)
                    offset=next_offset
                stage='trial_notifications'
                self.notify_trials()
                stage='payment_notifications'
                self.checkout.notify()
                stage='reseller_notifications'
                self.reseller.notify()
                stage='expiry_and_deal_notifications'
                self.notifications.tick()
                if self.notifications.backlog:stop.wait(1)
            except Exception as exc:
                if isinstance(exc,TelegramError):
                    log.warning('Telegram assistant paused (%s, Telegram API code %s); retrying.',exc.method or 'request',exc.code)
                    stop.wait(5)
                    continue
                db_stage=getattr(exc,'db_stage','unknown')
                if db_stage not in ('connect','query','commit'): db_stage='unknown'
                state=getattr(exc,'sqlstate','unavailable')
                if not isinstance(state,str) or not re.fullmatch(r'[A-Z0-9]{5}',state): state='unavailable'
                log.warning('Telegram assistant paused (stage=%s, error=%s, db_stage=%s, SQLSTATE=%s); retrying.',
                            stage,type(exc).__name__,db_stage,state)
                stop.wait(5)
