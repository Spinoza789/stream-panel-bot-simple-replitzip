"""Private notification preferences and administrator-confirmed deal announcements."""
import secrets
from .notifications import Notifications,now
from .service import CheckoutError

def button(text,action):return {'text':text,'callback_data':'nt:'+action}


class NotificationBot(Notifications):
    def admin(self,uid):return uid==self.service.config.get('support_admin_id')

    def settings(self,uid):
        if not self.ready:
            self.bot.send(uid,'Notification setup is not available yet. Please contact support.');return
        p=self.preferences(uid)
        rows=[[button('Expiry reminders: '+('ON' if p['alerts'] else 'OFF'),'alerts:'+str(1-p['alerts']))],
              [button('Deals: '+('ON' if p['deals'] else 'OFF'),'deals:'+str(1-p['deals']))]]
        if self.admin(uid):rows.append([button('Manage announcements','campaigns')])
        rows.append([{'text':'Back to menu','callback_data':'menu'}])
        self.bot.send(uid,'NOTIFICATION SETTINGS\n\nSubscription reminders: 7, 3 and 1 day before expiry. Trial and subscription expiry alerts are also included.\n\nDeals are optional and off until you opt in. /stopdeals turns deals off; /stop turns both options off.',{'inline_keyboard':rows})

    def draft(self,uid):
        value=self.store.metadata('nt_draft:'+str(uid))
        return self.store.unseal(value) if value else None

    def callback(self,uid,action):
        if not action.startswith('nt:'):return False
        if not self.ready:
            self.settings(uid);return True
        parts=action.split(':');name=parts[1]
        try:
            if name=='settings':self.settings(uid)
            elif name in ('alerts','deals'):
                self.preference(uid,name,int(parts[2]));self.settings(uid)
            elif name=='campaigns':
                self.service.resellers.finance.admin(uid)
                campaigns=self.campaigns(uid)
                text='ANNOUNCEMENTS\n\nCreate a draft with:\n/announce Your offer text here\n\nOnly customers who opt in to deals can receive an announcement. Each send needs an audience preview and confirmation.'
                rows=[]
                for c in campaigns:
                    text+='\n\n'+c['id']+' · '+c['status']+'\n'+', '.join(k+': '+str(v) for k,v in c['counts'].items())
                    if c['status']=='queued':rows.append([button('Cancel '+c['id'][:6],'cancel:'+c['id'])])
                text+='\n\nUnknown delivery outcomes are not retried automatically, to avoid duplicate messages.'
                rows.append([button('Back','settings')])
                self.bot.send(uid,text,{'inline_keyboard':rows})
            elif name in ('audience','send','cancel','discard'):
                self.service.resellers.finance.admin(uid)
                if name=='cancel':
                    self.cancel(uid,parts[2]);self.bot.send(uid,'Pending announcement deliveries cancelled. Already sent messages cannot be recalled.');return True
                draft=self.draft(uid)
                if not draft or draft['expires']<=now() or draft['id']!=parts[2]:
                    raise CheckoutError('This announcement preview expired or was already confirmed. Open notification settings to check delivery status.')
                if name=='discard':
                    with self.store.connection() as db:db.execute('DELETE FROM metadata WHERE key=?',('nt_draft:'+str(uid),))
                    self.bot.send(uid,'Announcement draft discarded. Nothing was sent.');return True
                if name=='audience':
                    audience=parts[3];recipients=self.eligible(audience)
                    if len(recipients)>5000:raise CheckoutError('This audience is too large for one announcement. Contact support to arrange a segmented send.')
                    draft.update(audience=audience,recipients=recipients,preview_id=secrets.token_hex(8))
                    self.store.metadata('nt_draft:'+str(uid),self.store.seal(draft))
                    self.bot.send(uid,'PREVIEW — NOT SENT\nAudience: '+audience+'\nOpted-in recipients: '+str(len(recipients))+'\n\n'+draft['body'],
                                  {'inline_keyboard':[[button('Confirm send','send:'+draft['id']+':'+draft['preview_id'])],[button('Discard draft','discard:'+draft['id'])]]})
                else:
                    if 'recipients' not in draft or len(parts)!=4 or parts[3]!=draft.get('preview_id'):
                        raise CheckoutError('This preview changed. Confirm only the latest audience preview.')
                    cid=self.queue_campaign(uid,draft)
                    self.bot.send(uid,'Announcement queued: '+cid+'. Delivery is rate-limited; check Manage announcements for results.')
            else:raise CheckoutError('This notification option is unavailable.')
        except (CheckoutError,ValueError,IndexError,KeyError) as exc:
            self.bot.send(uid,str(exc) if isinstance(exc,CheckoutError) else 'Invalid or expired notification option.')
        return True

    def message(self,uid,command,argument):
        if command not in ('/notifications','/stopdeals','/stop','/announce','/announcements'):return False
        if not self.ready:self.settings(uid);return True
        try:
            if command=='/notifications':self.settings(uid)
            elif command in ('/stop','/stopdeals'):
                self.preference(uid,'deals',0)
                if command=='/stop':self.preference(uid,'alerts',0)
                self.bot.send(uid,'Deals are off.' if command=='/stopdeals' else 'Deals and expiry reminders are off. Use /notifications to change this.')
            elif command=='/announcements':self.callback(uid,'nt:campaigns')
            else:
                self.service.resellers.finance.admin(uid)
                text=argument.strip()
                if not text or len(text.encode('utf-16-le'))//2>2500:
                    raise CheckoutError('Use /announce followed by your offer text, up to 2,500 characters.')
                draft=dict(id=secrets.token_hex(8),body=text,expires=now()+900)
                self.store.metadata('nt_draft:'+str(uid),self.store.seal(draft))
                self.bot.send(uid,'DRAFT — NOT SENT\n\n'+text+'\n\nChoose who should receive this offer:',
                              {'inline_keyboard':[[button(label,'audience:'+draft['id']+':'+audience)]
                                                   for label,audience in (('All opted-in users','all'),('Retail users','retail'),('Approved resellers','resellers'))]})
        except CheckoutError as exc:self.bot.send(uid,str(exc))
        return True
