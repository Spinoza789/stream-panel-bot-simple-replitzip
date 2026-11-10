"""Private, owner-scoped Telegram reseller and administrator screens."""
import json
import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from .reseller_ledger import now
from .service import CheckoutError
from html import escape
from .trial_message import APP_DOWNLOAD_GUIDE

log=logging.getLogger(__name__)


def date(value):
    return datetime.fromtimestamp(int(value),ZoneInfo('Europe/London')).strftime('%d %b %Y %H:%M %Z')


def button(text,action):
    return {'text':text,'callback_data':'rs:'+action}


def keyboard(rows,back=True):
    return {'inline_keyboard':rows+([[button('Back to reseller menu','home')]] if back else [])}


class ResellerBot:
    def __init__(self,bot):
        self.bot=bot;self.r=bot.service.resellers;self.store=bot.store

    def state(self,uid,value=None,clear=False):
        key='rs_ui:'+str(uid)
        if clear:self.store.metadata(key,'');return None
        if value is not None:
            value=dict(value,expires=now()+900)
            self.store.metadata(key,self.store.seal(value));return value
        value=self.store.unseal(self.store.metadata(key))
        return value if value and value.get('expires',0)>now() else None

    def send(self,uid,text,rows=None,keep=False,parse_mode=None):
        if self.bot.service.config['mode']=='demo' and self.bot.service.config.get('demo_banner',True):text='DEMO — simulated accounts and payments only.\n\n'+text
        self.bot.send(uid,text,keyboard(rows or []),parse_mode=parse_mode,keep=keep)

    def home(self,uid):
        self.r.require_ready()
        member=self.r.member(uid)
        if not member:
            packages=[p for p in self.r.finance.packages() if p['active']]
            text=('🏪 BECOME A RESELLER\n\n'
                  'Sell Streamline subscriptions to your own customers and keep the margin.\n\n'
                  '• Buy credits in bulk'+(' — from £'+str(min(p['price_pence'] for p in packages)//100)+' for '
                  +str(min(packages,key=lambda p:p['price_pence'])['credits'])+' credits' if packages else '')+'\n'
                  '• Create trials and subscriptions in seconds, right here\n'
                  '• See every customer, expiry and credit in one place\n\n'
                  'Tap Apply and we will approve you shortly.')
            rows=[[button('✅ Apply now','apply')],
                  [{'text':'💬 Questions? Contact support','callback_data':'menu:contact'}],
                  [{'text':'⬅️ Main menu','callback_data':'menu'}]]
        elif member['status']=='pending':
            text=('⏳ APPLICATION RECEIVED\n\n'
                  'Thanks! We are reviewing your reseller application. You will get a message here as soon as it is approved.')
            rows=[[button('🔄 Check status','home')],
                  [{'text':'💬 Contact support','callback_data':'menu:contact'}],
                  [{'text':'⬅️ Main menu','callback_data':'menu'}]]
        else:
            counts=self.r.ops.counts(uid)
            text=('🏪 RESELLER DASHBOARD\n\n'
                  '💳 Credits: '+str(member['available'])+' available'
                  +(' · '+str(member['reserved'])+' reserved' if member['reserved'] else '')+'\n'
                  '📺 Subscriptions: '+str(counts['active'])+' active · '+str(counts['expiring'])+' expiring in 7 days · '
                  +str(counts['trials'])+' trial'+('' if counts['trials']==1 else 's')+' running')
            if member['status']=='suspended':
                text+='\n\n⛔ Your account is suspended. You can view records, but not buy, create or extend. '+self.bot.service.config['support']
            rows=[[button('➕ Create subscription','create'),button('🎁 Create trial','trial')],
                  [button('💳 Buy credits','packages'),button('📊 My balance','balance')],
                  [button('📺 My subscriptions','list:active:0'),button('🧾 History','history:0')],
                  [button('🌐 Open web dashboard','web')],
                  [button('❓ Help','help'),{'text':'🔔 Notifications','callback_data':'nt:settings'}]]
            if uid==self.bot.service.config.get('support_admin_id'):rows.append([button('🛠 Administration','admin')])
            rows.append([{'text':'⬅️ Main menu','callback_data':'menu'}])
        self.bot.send(uid,text,keyboard(rows,False))

    def _applied(self,uid,sender):
        """One-tap application: register, tell the applicant, and ping the administrator with an Approve button."""
        existing=self.r.member(uid)
        self.r.finance.register(uid,sender.get('username',''))
        admin=self.bot.service.config.get('support_admin_id')
        if not existing and admin and admin!=uid:
            who=('@'+sender['username']+' ' if sender.get('username') else '')+'(ID '+str(uid)+')'
            try:
                self.bot.send(admin,'🆕 New reseller application from '+who+'.',
                              keyboard([[button('✅ Approve','approve:'+str(uid))],[button('Reseller accounts','adminlist:accounts:0')]],False),keep=True)
            except Exception as exc:  # a blocked administrator must not break the applicant's flow
                if getattr(exc,'code',None)!=403:raise
        self.home(uid)

    def announce_status(self,target,status):
        """Tell a reseller their account was approved or suspended. Delivery problems never block the admin action."""
        if status=='active':
            text=('🎉 You are approved as a Streamline reseller!\n\n'
                  'Buy credits, then create trials and subscriptions for your customers from your dashboard.')
        else:
            text='⛔ Your reseller account has been suspended. '+self.bot.service.config['support']
        try:self.bot.send(target,text,keyboard([[button('Open reseller dashboard','home')]],False),keep=True)
        except Exception as exc:
            if getattr(exc,'code',None)!=403:raise

    def _confirmation(self,uid,state):
        preview=self.r.ops.preview(uid,state['kind'],state.get('months',0),state.get('connections',1),
                                   state.get('adult',False),state.get('customer_ref',''),state.get('target'))
        state=self.state(uid,dict(state,preview=preview))
        text=('Confirm '+('24-hour trial' if preview['kind']=='trial' else preview['kind']+' subscription')+
              '\nDuration: '+('24 hours' if preview['kind']=='trial' else str(preview['months'])+' month(s)')+
              '\nConnections: '+str(preview['connections'])+'\nContent: '+('With adult' if preview['adult'] else 'No adult')+
              '\nCustomer: '+(preview['customer_ref'] or 'Not provided')+
              '\nCredit cost: '+str(preview['cost'])+'\nAvailable: '+str(preview['available'])+
              '\nRemaining after purchase: '+str(preview['remaining']))
        if preview['provider_preview']:
            text+='\nCurrent provider-confirmed expiry: '+date(preview['provider_preview']['previous_expiry'])+'\nThe provider-confirmed new expiry is returned after completion.'
        text+='\n\nConfirmation reserves credits. A permanent deduction happens only after the provider confirms success.'
        rows=[[button('Confirm','confirm:'+state['nonce'])]] if preview['remaining']>=0 else [[button('Insufficient credits — Buy Credits','packages')]]
        self.send(uid,text,rows)

    def _durations(self,uid):
        self.send(uid,'Choose a duration:',[[button(str(months)+' month(s)','duration:'+str(months))] for months in (1,3,6,9,12)])

    def _content(self,uid):
        self.send(uid,'Choose the content option:',[[button('With adult','adult:1'),button('No adult','adult:0')]])

    def _details(self,uid,sid):
        record,warning,extensions=self.r.ops.refresh(uid,sid)
        member=self.r.finance.member(uid)
        e=escape
        text=('<u>24 Hour Trial</u>' if record['kind']=='trial' else '<u>Membership</u>')+'\n\n'+e(
              'Customer: '+(record['customer_ref'] or 'Not provided')+'\nSubscription ID: '+record['provider_id']+
              '\nConnections: '+str(record['connections'])+'\nContent: '+('With adult' if record['adult'] else 'No adult')+
              '\nStatus: '+record['status']+'\nRecorded start: '+date(record['starts_at'])+
              '\nProvider-confirmed expiry: '+date(record['expires_at'])+
              '\nLast confirmed: '+date(record['confirmed_at'])+
              '\nAvailable credits: '+str(member['available']))+(
              '\n\n<b>Username: '+e(record['credentials']['username'])+'</b>\n<b>Password: '+e(record['credentials']['password'])+'</b>')
        if record['credentials'].get('server_url'):text+='\nServer: '+e(record['credentials']['server_url'])
        if warning:text+='\n\n'+e(warning)
        text+='\n\n'+APP_DOWNLOAD_GUIDE
        if extensions:
            text+=e('\n\nRecent extensions:\n'+'\n'.join(date(x['created_at'])+' · '+str(x['months'])+' months · '+str(x['credits'])+' credits' for x in extensions[:5]))
            text+='\nAll extension dates, durations and charges are in Transaction History.'
        rows=[]
        if not warning and member['status']=='active' and record['status'] in ('active','expired'):
            rows.append([button('Convert trial / Extend Subscription' if record['kind']=='trial' else 'Extend Subscription','extend:'+sid)])
        rows.append([button('Refresh details','detail:'+sid),button('My Subscriptions','filters')])
        self.send(uid,text,rows,keep=True,parse_mode='HTML')  # customer login details stay in the chat

    def _operation(self,uid,oid):
        op=self.r.ops.operation(uid,oid)
        if op['status']=='succeeded':return self._details(uid,op['result_id'])
        member=self.r.finance.member(uid)
        self.send(uid,'Request: '+oid+'\nStatus: '+op['status']+'\nCredit cost: '+str(op['credit_cost'])+
                  '\nReserved credits: '+str(member['reserved'])+'\nAvailable: '+str(member['available'])+
                  ('\n'+op['error'] if op['error'] else '\nYour request is queued. Details will be sent here after confirmation.'),
                  [[button('Check request','op:'+oid)]])

    def _history(self,uid,page,viewer=None):
        viewer=uid if viewer is None else viewer
        if viewer!=uid:self.r.finance.admin(viewer)
        rows=self.r.finance.history(uid,page)
        text='Transaction History\n\n'+('\n\n'.join(date(r['created_at'])+' · '+f"{r['movement']:+d}"+' credits\n'+r['reason'][:120]+'\nReference: '+r['reference'] for r in rows[:10]) or 'No credit transactions yet.')
        navigation=[]
        prefix='history:' if viewer==uid else 'adminhistory:'+str(uid)+':'
        if page:navigation.append(button('Previous',prefix+str(page-1)))
        if len(rows)>10:navigation.append(button('Next',prefix+str(page+1)))
        self.send(viewer,text,[navigation] if navigation else [])

    def _records(self,uid,filter_name,page):
        warning=self.r.ops.refresh_listing(uid)
        search=self.store.unseal(self.store.metadata('rs_search:'+str(uid))) or ''
        rows=self.r.ops.records(uid,filter_name,page,search)
        text='My Subscriptions — '+filter_name+('\nSearch: '+search if search else '')+'\n\n'
        if warning:text+=warning+'\n\n'
        text+='\n'.join(('TRIAL' if r['kind']=='trial' else 'PAID')+' · '+(r['customer_ref'] or r['username'])+' · '+r['status']+' · '+date(r['expires_at']) for r in rows[:10]) or 'No matching records.'
        actions=[[button((r['customer_ref'] or r['username'])[:35]+' · '+r['provider_id'],'detail:'+r['id'])] for r in rows[:10]]
        nav=[]
        if page:nav.append(button('Previous','list:'+filter_name+':'+str(page-1)))
        if len(rows)>10:nav.append(button('Next','list:'+filter_name+':'+str(page+1)))
        if nav:actions.append(nav)
        actions.append([button('Search','search'),button('Clear search','clearsearch')])
        actions.append([button('Change filter','filters')])
        self.send(uid,text,actions)

    def callback(self,uid,action,sender):
        if not action.startswith('rs:'):return False
        try:
            self.r.require_ready()
            parts=action.split(':');name=parts[1]
            if name=='home':
                self.state(uid,clear=True);self.home(uid)
            elif name=='apply':
                self.state(uid,clear=True);self._applied(uid,sender)
            elif name=='web':
                if not self.store.limit('rs_web_link:'+str(uid),5,600):raise CheckoutError('Please wait a few minutes before requesting another sign-in link.')
                url=self.r.web.login_url(self.r.web.issue_code(uid))
                self.bot.send(uid,'🌐 Your web dashboard sign-in link (valid for 10 minutes, one use):\n'+url+
                              '\n\nOnce signed in, open Account to add a recovery email and password so you can also sign in without Telegram.',
                              keyboard([],False),keep=True)
            elif name=='balance':
                member=self.r.finance.member(uid)
                if not member:raise CheckoutError('Request reseller approval first.')
                self.send(uid,'My Balance\n\nTotal credits: '+str(member['balance'])+'\nReserved: '+str(member['reserved'])+'\nAvailable: '+str(member['available']),[[button('Requests / reserved credits','requests:0')]])
            elif name=='packages':
                self.r.finance.member(uid,active=True);self.state(uid,clear=True)
                packages=self.r.finance.packages()
                self.send(uid,'Buy Credits\n\nCredits are added only after blockchain verification or an authorised manual payment confirmation.',
                          [[button(f"£{p['price_pence']//100}.{p['price_pence']%100:02d} = {p['credits']} credits",'package:'+p['id'])] for p in packages if p['active']])
            elif name=='package':
                self.r.finance.member(uid,active=True)
                self.send(uid,'Choose the crypto and network:',[[button(a['symbol']+' · '+a['network'],'buy:'+parts[2]+':'+aid)] for aid,a in self.bot.service.config['assets'].items() if a.get('enabled',True)])
            elif name=='buy':
                self.state(uid,clear=True)
                order=self.r.finance.quote_purchase(uid,parts[2],parts[3],secrets.token_hex(12))
                self.bot.checkout.show_order(uid,order)
            elif name in ('create','trial','extend'):
                self.r.finance.member(uid,active=True)
                self.bot.checkout.clear_session(uid)
                state={'kind':name,'nonce':secrets.token_hex(12)}
                if name=='extend':
                    record,warning,_=self.r.ops.refresh(uid,parts[2])
                    if warning:raise CheckoutError(warning)
                    state.update(target=record['id'],connections=record['connections'],adult=bool(record['adult']))
                self.state(uid,state)
                if name=='trial':self._content(uid)
                else:self._durations(uid)
            elif name in ('duration','connections','adult','skip'):
                state=self.state(uid)
                if not state:raise CheckoutError('This form expired. Start again from the reseller menu.')
                if name=='duration':
                    state['months']=int(parts[2]);self.state(uid,state)
                    if state['kind']=='extend':self._confirmation(uid,state)
                    else:self.send(uid,'Choose connections:',[[button(str(n),'connections:'+str(n)) for n in (1,2,3)]])
                elif name=='connections':
                    state['connections']=int(parts[2]);self.state(uid,state);self._content(uid)
                elif name=='adult':
                    if parts[2] not in ('0','1'):raise CheckoutError('Invalid content option.')
                    state['adult']=parts[2]=='1';state['input']='reference';self.state(uid,state)
                    self.send(uid,'Send an optional customer name or reference (up to 100 characters), or skip it.',[[button('Skip customer reference','skip')]])
                else:
                    state['customer_ref']='';state.pop('input',None);self._confirmation(uid,state)
            elif name=='confirm':
                nonce=parts[2]
                receipt=self.store.metadata('rs_confirm:'+str(uid)+':'+nonce)
                if receipt:self._operation(uid,receipt);return True
                state=self.state(uid)
                if not state or state.get('nonce')!=nonce or not state.get('preview'):
                    raise CheckoutError('This confirmation expired. Review a new request.')
                op=self.r.ops.reserve(uid,nonce,state['preview'])
                self.store.metadata('rs_confirm:'+str(uid)+':'+nonce,op['id'])
                self.state(uid,clear=True);self._operation(uid,op['id'])
            elif name=='op':self._operation(uid,parts[2])
            elif name=='requests':
                page=int(parts[2]);rows=self.r.ops.requests(uid,page)
                text='Your requests\n\n'+('\n\n'.join(r['id']+'\n'+r['operation_type']+' · '+r['status']+' · '+str(r['credit_cost'])+' credits · '+r['reservation'] for r in rows[:10]) or 'No requests yet.')
                actions=[[button(r['operation_type']+' · '+r['status']+' · '+r['id'][:8],'op:'+r['id'])] for r in rows[:10]]
                nav=[]
                if page:nav.append(button('Previous','requests:'+str(page-1)))
                if len(rows)>10:nav.append(button('Next','requests:'+str(page+1)))
                if nav:actions.append(nav)
                self.send(uid,text,actions)
            elif name=='detail':self._details(uid,parts[2])
            elif name=='history':self._history(uid,int(parts[2]))
            elif name=='adminhistory':
                self.r.finance.admin(uid);self._history(int(parts[2]),int(parts[3]),uid)
            elif name=='filters':
                self.send(uid,'Choose a filter:',[[button(label,'list:'+value+':0')] for label,value in
                          (('Active subscriptions','active'),('Expiring within 7 days','expiring'),('Expired subscriptions','expired'),('Trials','trials'),('All records','all'))]+[[button('Search','search')]])
            elif name=='list':self._records(uid,parts[2],int(parts[3]))
            elif name=='search':
                self.r.finance.member(uid)
                self.state(uid,{'input':'search'})
                self.send(uid,'Send a customer reference, username or subscription ID to search your own records.')
            elif name=='clearsearch':
                self.store.metadata('rs_search:'+str(uid),'');self._records(uid,'all',0)
            elif name=='help':
                self.send(uid,'Reseller help\n\nApproval is required. Buy credits using the existing crypto checkout and submit the TXID. “I’ve paid” never adds credits by itself.\n\nConfirmed subscription requests reserve credits. Uncertain provider results remain reserved for support review; do not create another request for the same customer.\n\nTrial limits are separate from retail trials. Expiry times are shown in Europe/London.\n\nContact: '+self.bot.service.config['support'])
            elif name=='admin':
                self.r.finance.admin(uid)
                self.send(uid,self.admin_help(),[[button('Reseller accounts','adminlist:accounts:0')],[button('Credit purchases','adminlist:purchases:0')],[button('Pending / failed operations','adminlist:operations:0')],[button('Configuration','config')],[button('Audit log','adminlist:audit:0')]])
            elif name=='adminlist':
                rows=self.r.finance.admin_list(uid,parts[2],int(parts[3]))
                text=parts[2].title()+'\n\n'+'\n\n'.join(' · '.join(str(v)[:120] for v in r.values()) for r in rows[:10])
                buttons=[]
                if parts[2]=='accounts':
                    buttons=[[button('Approve '+str(r['telegram_id']),'approve:'+str(r['telegram_id']))] for r in rows[:10] if r['status']=='pending']
                if parts[2]=='operations':
                    buttons=[[button('Reconcile '+r['id'][:10],'reconcile:'+r['id'])] for r in rows[:10] if r['status']=='uncertain']
                page=int(parts[3]);nav=[]
                if page:nav.append(button('Previous','adminlist:'+parts[2]+':'+str(page-1)))
                if len(rows)>10:nav.append(button('Next','adminlist:'+parts[2]+':'+str(page+1)))
                if nav:buttons.append(nav)
                buttons.append([button('Administration','admin')]);self.send(uid,text,buttons)
            elif name=='approve':
                self.r.finance.account_status(uid,int(parts[2]),'active','Approved from reseller administration')
                self.send(uid,'Reseller approved.')
                self.announce_status(int(parts[2]),'active')
            elif name=='reconcile':
                self.r.ops.reconcile(uid,parts[2]);self.send(uid,'Provider result reconciled. Credits charged once; details are available to the reseller.')
            elif name=='config':
                config=self.r.finance.configuration(uid)
                text='Credit packages (ID / pence / credits / active)\n'+'\n'.join(f"{p['id']} / {p['price_pence']} / {p['credits']} / {p['active']}" for p in config['packages'])
                text+='\n\nCosts (months / connections / credits)\n'+'\n'.join(f"{p['months']} / {p['connections']} / {p['credits']}" for p in config['costs'])
                text+='\n\nTrial settings: '+json.dumps(config['settings'])+'\n\n'+self.admin_help()
                self.send(uid,text)
            else:raise CheckoutError('Unknown reseller option.')
        except CheckoutError as exc:self.send(uid,str(exc))
        except (ValueError,KeyError,IndexError,TypeError):self.send(uid,'This reseller option is invalid or expired. Start again.')
        return True

    @staticmethod
    def admin_help():
        return ('Administration\n\nAll changes are audited. Credit adjustments and payment confirmations require a reason.\n'
                '/rsapprove TELEGRAM_ID reason\n/rssuspend TELEGRAM_ID reason\n'
                '/rsbalance TELEGRAM_ID\n/rshistory TELEGRAM_ID [page]\n'
                '/rscredits TELEGRAM_ID signed_credits reason\n'
                '/rspayment ORDER_ID network:TXID_or_bank:reference reason\n'
                '/rspackage PACKAGE_ID PRICE_PENCE CREDITS ACTIVE_0_OR_1 reason\n'
                '/rscost MONTHS CONNECTIONS CREDITS reason\n/rstrials DAILY_LIMIT ACTIVE_LIMIT reason\n'
                '/rsreconcile OPERATION_ID [PROVIDER_ID]\n\n'
                'Suspension blocks new spending and trial requests. Already-submitted operations remain subject to safe reconciliation.')

    def message(self,message,command,argument):
        uid=message['from']['id']
        member=self.r.member(uid)
        try:
            if command=='/reseller' or command in ('/start','/help') and member:
                self.home(uid);return True
            if command.startswith('/rs'):
                self.r.require_ready();self.r.finance.admin(uid)
                if command in ('/rsapprove','/rssuspend'):
                    target,reason=argument.split(maxsplit=1)
                    status='active' if command=='/rsapprove' else 'suspended'
                    self.r.finance.account_status(uid,int(target),status,reason)
                    self.announce_status(int(target),status)
                elif command=='/rscredits':
                    target,amount,reason=argument.split(maxsplit=2)
                    self.r.finance.adjust(uid,int(target),int(amount),reason,str(message['message_id']))
                elif command=='/rspayment':
                    oid,reference,reason=argument.split(maxsplit=2)
                    self.r.finance.grant(oid,actor=uid,reference=reference,reason=reason)
                elif command=='/rspackage':
                    pid,pence,credits,active,reason=argument.split(maxsplit=4)
                    self.r.finance.configure(uid,'package',(pid,int(pence),int(credits),int(active)),reason)
                elif command=='/rscost':
                    months,connections,cost,reason=argument.split(maxsplit=3)
                    self.r.finance.configure(uid,'cost',(int(months),int(connections),int(cost)),reason)
                elif command=='/rstrials':
                    daily,active,reason=argument.split(maxsplit=2)
                    self.r.finance.configure(uid,'trials',(int(daily),int(active)),reason)
                elif command=='/rsreconcile':
                    values=argument.split()
                    self.r.ops.reconcile(uid,values[0],values[1] if len(values)>1 else None)
                elif command=='/rsbalance':
                    target=self.r.finance.member(int(argument))
                    if not target:raise CheckoutError('Reseller not found.')
                    self.send(uid,'Balance: '+str(target['balance'])+'\nReserved: '+str(target['reserved'])+'\nAvailable: '+str(target['available']));return True
                elif command=='/rshistory':
                    values=argument.split();self._history(int(values[0]),int(values[1]) if len(values)>1 else 0,uid)
                    return True
                else:raise CheckoutError(self.admin_help())
                self.send(uid,'Administrator action completed and audited.');return True
            if member and member['status']!='active' and command in ('/trial','/retrytrial','/txid'):
                raise CheckoutError('Your reseller account must be approved and active for this action.')
            state=self.state(uid)
            if command.startswith('/') or not state or not state.get('input'):return False
            text=message.get('text','').strip()
            if len(text)>100:raise CheckoutError('Use at most 100 characters.')
            if state['input']=='search':
                self.store.metadata('rs_search:'+str(uid),self.store.seal(text));self.state(uid,clear=True)
                self._records(uid,'all',0)
            else:
                state['customer_ref']=text;state.pop('input',None);self._confirmation(uid,state)
            return True
        except CheckoutError as exc:self.send(uid,str(exc));return True
        except (ValueError,KeyError,IndexError,TypeError):self.send(uid,'Invalid input. Use /reseller and open Administration for command formats.');return True

    def notify(self):
        if not self.r.ready:return
        with self.store.connection() as db:
            rows=db.execute("SELECT o.id,o.status,r.telegram_id FROM rs_operations o JOIN rs_resellers r ON r.id=o.reseller_id "
                            "WHERE o.status IN ('succeeded','failed','uncertain') "
                            "AND NOT EXISTS(SELECT 1 FROM metadata WHERE key='rs_notice:'||o.id||':'||o.status) "
                            "AND NOT EXISTS(SELECT 1 FROM metadata WHERE key='rs_notice:'||o.id||':'||o.status||':retry' AND CAST(value AS INTEGER)>?) "
                            "ORDER BY o.updated_at,o.id LIMIT 5",(now(),)).fetchall()
        sent=0
        for row in rows:
            key='rs_notice:'+row['id']+':'+row['status']
            if self.store.metadata(key) or int(self.store.metadata(key+':retry') or 0)>now():continue
            try:
                self._operation(row['telegram_id'],row['id'])
                self.store.metadata(key,'1')
            except Exception as exc:
                if getattr(exc,'code',None)==403:self.store.metadata(key,'blocked')
                else:
                    self.store.metadata(key+':retry',now()+300)
                    log.warning('Reseller delivery deferred (%s).',type(exc).__name__)
            sent+=1
            if sent>=5:break
