"""Opt-in private support relay; only a configured numeric owner may reply."""
import re
import time
from .store import digest


class SupportRelay:
    def __init__(self,bot):
        self.bot=bot;self.store=bot.store;self.config=bot.service.config

    @property
    def admin(self):return self.config.get('support_admin_id')

    def contact_text(self):
        return self.config.get('support','Contact support.')+'\n'+self.config['support_url']

    def session_key(self,uid):return 'support_session:'+digest(uid)

    def save(self,key,value):self.store.metadata(key,self.store.seal(value))

    def read(self,key):
        value=self.store.metadata(key)
        return self.store.unseal(value) if value else None

    @staticmethod
    def message_id(result):
        value=result.get('message_id') if isinstance(result,dict) else None
        if type(value) is not int or value<=0:raise RuntimeError('Telegram did not confirm a support message ID.')
        return value

    def route_key(self,message_id):return f'support_route:{self.admin}:{message_id}'

    def route(self,message_id,customer_id):
        self.save(self.route_key(message_id),{'customer_id':customer_id,'expires_at':int(time.time())+30*86400})

    def active(self,uid):
        return int(self.store.metadata(self.session_key(uid)) or '0')>=int(time.time())

    @staticmethod
    def supported(message):
        return any(message.get(key) for key in ('text','photo','document','voice','audio','video','video_note','animation','sticker')) and not message.get('has_protected_content')

    def relay_customer(self,message):
        from .bot import TelegramError
        uid=message['from']['id'];mid=message.get('message_id')
        if not self.admin:
            self.bot.send(uid,'Bot support is not connected yet. Contact us directly:\n'+self.contact_text());return
        if type(mid) is not int or mid<=0 or not self.supported(message):
            self.bot.send(uid,'Please send a text message, photo, document or voice/video message. Protected and service messages cannot be relayed.');return
        key='support_in:'+digest(f'{self.admin}:{uid}:{mid}')
        receipt=self.read(key) or {}
        if receipt.get('delivered'):return
        try:
            if not receipt.get('header_id'):
                username=message['from'].get('username','')
                label='@'+username if re.fullmatch(r'[a-zA-Z0-9_]{1,64}',username) else 'Customer'
                header=self.bot.send(self.admin,f'Support message from {label}\nCustomer ID: {uid}\nReply to this message or the copied content to answer privately through the bot.')
                receipt['header_id']=self.message_id(header)
                self.route(receipt['header_id'],uid);self.save(key,receipt)
            if not receipt.get('copy_id'):
                result=self.bot.api('copyMessage',{'chat_id':self.admin,'from_chat_id':uid,'message_id':mid})
                receipt['copy_id']=self.message_id(result)
                self.route(receipt['copy_id'],uid)
            receipt['delivered']=True;self.save(key,receipt)
            self.bot.send(uid,'Your message was sent to @'+self.config['support_username']+'. Their reply will appear here. Send /cancel to leave support chat.')
        except TelegramError as exc:
            if exc.code not in (400,403):raise
            self.bot.send(uid,'We were unable to deliver this message. You can contact us directly:\n'+self.contact_text())

    def relay_admin(self,message):
        from .bot import TelegramError
        mid=message.get('message_id');reply=(message.get('reply_to_message') or {}).get('message_id')
        if type(mid) is not int or mid<=0 or type(reply) is not int:
            self.bot.send(self.admin,'Reply to a support message received by this bot to answer its customer.');return
        route=self.read(self.route_key(reply))
        if not route or route.get('expires_at',0)<int(time.time()):
            self.bot.send(self.admin,'Reply to a recent support message from this bot. This reply has no valid customer route.');return
        if not self.supported(message):
            self.bot.send(self.admin,'Unable to relay that message type. Please send text or supported media.');return
        key='support_out:'+digest(f'{self.admin}:{mid}')
        if self.read(key):return
        try:
            result=self.bot.api('copyMessage',{'chat_id':route['customer_id'],'from_chat_id':self.admin,'message_id':mid})
            self.save(key,{'delivered_id':self.message_id(result),'at':int(time.time())})
            self.bot.send(self.admin,'Reply sent to the customer.')
        except TelegramError as exc:
            if exc.code not in (400,403):raise
            self.bot.send(self.admin,'Unable to deliver this reply. The customer may have blocked the bot, or this content cannot be copied. Try a text reply if appropriate.')

    def handle(self,message,command,argument=''):
        uid=message['from']['id']
        if command=='/myid':
            self.bot.send(uid,'Your Telegram user ID is: '+str(uid));return True
        if uid==self.admin and message.get('reply_to_message'):
            self.relay_admin(message);return True
        if command in ('/contact','/support','/paysupport'):
            if uid==self.admin:
                self.bot.send(uid,'You are the support administrator. Reply to a received customer support message to answer privately.');return True
            if not self.admin:
                self.bot.send(uid,'Bot support is not connected yet. You can message us directly:\n'+self.contact_text());return True
            self.store.metadata(self.session_key(uid),int(time.time())+86400)
            if argument:self.relay_customer(message)
            else:self.bot.send(uid,'Support chat with @'+self.config['support_username']+' is open. Messages you send now will be shared with them so they can reply here. Send text, a photo or a voice message. Use /cancel to leave support chat.\n\nDirect contact: '+self.config['support_url'])
            return True
        if command=='/cancel':
            self.store.metadata(self.session_key(uid),'0')
            self.bot.send(uid,'Support chat closed. New messages will not be shared unless you use /contact again.');return True
        if not command.startswith('/'):
            if uid==self.admin:
                self.bot.send(uid,'Reply to a customer support message to choose who receives your answer.');return True
            if self.active(uid):self.relay_customer(message);return True
        return False
