'use strict';
const $=id=>document.getElementById(id);
const BASE=document.querySelector('meta[name="streambot-base-path"]').content;
const API=BASE+'/api/reseller';
let me=null,packages=null,sub={filter:'active',page:0,search:''},hist={page:0},create={kind:'create',months:1,connections:1,adult:false},nonce=null,pollTimer=null;
const names={ethereum:'Ethereum',solana:'Solana',bitcoin:'Bitcoin'};
const when=ts=>new Date(ts*1000).toLocaleString('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Europe/London'});
const whenDay=ts=>new Date(ts*1000).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/London'});
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',maximumFractionDigits:2,minimumFractionDigits:0}).format(p/100);
function error(message){$('error').textContent=message||'';$('error').hidden=!message;if(message)window.scrollTo({top:0,behavior:'smooth'});}
class SignedOut extends Error{}
async function api(path,{method='GET',data}={}){
  const headers={};if(method==='POST')headers['Content-Type']='application/json';
  const response=await fetch(API+path,{method,headers,credentials:'same-origin',cache:'no-store',body:method==='POST'?JSON.stringify(data||{}):undefined});
  const body=await response.json().catch(()=>({}));
  if(response.status===401)throw new SignedOut(body.error||'Sign in required.');
  if(!response.ok)throw new Error(body.error||'This request could not be completed. Please try again.');
  return body;
}
async function busy(button,work){const text=button.textContent;button.disabled=true;error('');try{await work();}catch(e){if(e instanceof SignedOut)return signedOut();error(e.message);}finally{button.disabled=false;button.textContent=text;}}
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}

// ---------- shell ----------
function signedOut(){me=null;$('shell').hidden=true;$('view-signin').hidden=false;$('signout').hidden=true;$('who').hidden=true;$('loading').hidden=true;}
function applyMe(data){
  if(!apps)api('/apps').then(a=>{apps=a;}).catch(()=>{});
  me=data;document.querySelectorAll('[data-brand]').forEach(n=>n.textContent=me.brand);$('demo-banner').hidden=!me.demo;
  $('who').textContent=(me.username?'@'+me.username:'ID '+me.telegram_id);$('who').hidden=false;$('signout').hidden=false;$('avatar').textContent=(me.username||'R')[0].toUpperCase();
  $('view-signin').hidden=true;$('shell').hidden=false;$('loading').hidden=true;
  $('t-available').textContent=me.credits.available;$('t-reserved').textContent=me.credits.reserved?me.credits.reserved+' reserved for pending requests':'';
  $('t-active').textContent=me.counts.active;$('t-expiring').textContent=me.counts.expiring;$('t-trials').textContent=me.counts.trials;
  $('c-available').textContent=me.credits.available;$('c-reserved').textContent=me.credits.reserved?me.credits.reserved+' reserved for pending requests':'';
  const note=$('status-note');
  if(me.status==='pending'){note.textContent='Buy your first credit pack to activate your reseller account. Credits are added, and the account goes live, as soon as the payment is verified.';note.hidden=false;}
  else if(me.status==='suspended'){note.textContent='Your reseller account is suspended. You can view records but not buy, create or extend. '+me.support;note.hidden=false;}
  else note.hidden=true;
  $('acc-id').textContent=me.telegram_id;$('acc-username').textContent=me.username?'@'+me.username:'—';$('acc-status').textContent=me.status;
  $('acc-email').textContent=me.login.email||'Not set';$('acc-form-title').textContent=me.login.has_password?'Change recovery email or password':'Add a recovery email and password';
  $('current-wrap').hidden=!me.login.has_password;$('acc-current').required=me.login.has_password;
  if(me.login.email)$('acc-new-email').value=me.login.email;
}
async function refreshMe(){applyMe(await api('/me'));}
function route(){
  if(!me)return;
  const hash=location.hash.replace(/^#\/?/,'')||'dashboard';const [tab,query]=hash.split('?');const params=new URLSearchParams(query||'');
  const known=['dashboard','subscriptions','create','credits','apps','history','account'];const view=known.includes(tab)?tab:'dashboard';
  known.forEach(v=>$('view-'+v).hidden=v!==view);
  document.querySelectorAll('#tabs a').forEach(a=>a.getAttribute('data-tab')===view?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current'));
  error('');
  if(view==='subscriptions'){if(params.get('filter'))sub.filter=params.get('filter');loadSubs().catch(fail);if(params.get('open'))openDetail(params.get('open')).catch(fail);else $('sub-detail').hidden=true;}
  if(view==='history')loadHistory().catch(fail);
  if(view==='credits'){loadPackages().catch(fail);resumeInvoice();}
  if(view==='create')renderCreate();
  if(view==='apps')loadApps().catch(fail);
  if(view==='dashboard'){refreshMe().catch(fail);loadHome().catch(fail);}
}
function fail(e){if(e instanceof SignedOut)return signedOut();error(e.message);}

// ---------- subscriptions ----------
function pill(r){const now=Date.now()/1000;if(r.expires_at<=now)return ['EXPIRED','bad'];if(r.expires_at<now+7*86400)return ['EXPIRING','warn'];return [r.status.toUpperCase(),r.status==='active'?'ok:':''];}
async function loadSubs(){
  document.querySelectorAll('#filters .chip').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===sub.filter)));
  const data=await api('/subscriptions?filter='+encodeURIComponent(sub.filter)+'&page='+sub.page+'&search='+encodeURIComponent(sub.search));
  renderRows($('sub-list'),data.items,'No records here yet.');
  $('sub-prev').disabled=!sub.page;$('sub-next').disabled=!data.more;$('sub-page').textContent='Page '+(sub.page+1);
}
function subRow(r){
  const row=el('button','row');row.type='button';
  const name=el('div');name.append(el('strong',null,r.customer_ref||r.username));name.append(el('small',null,r.username+' · '+r.provider_id));
  const kind=el('div',null,(r.kind==='trial'?'Test':'Paid')+' · '+r.connections+' device'+(r.connections>1?'s':'')+(r.adult?' · adult':''));
  const start=el('div','hide-sm');start.append(el('small',null,'Started'));start.append(document.createTextNode(' '+whenDay(r.starts_at)));
  const exp=el('div');exp.append(el('small',null,'Expires'));exp.append(document.createTextNode(' '+whenDay(r.expires_at)));
  const [label,cls]=pill(r);const p=el('span','pill '+cls.replace(':',''),label);
  row.append(name,kind,start,exp,p);row.onclick=()=>{if(location.hash.startsWith('#/subscriptions'))openDetail(r.id).catch(fail);else location.hash='#/subscriptions?open='+encodeURIComponent(r.id);};return row;
}
function renderRows(list,items,empty){list.replaceChildren();if(!items.length)list.append(el('div','empty',empty));for(const r of items)list.append(subRow(r));}
async function loadHome(){
  const [expiring,recent]=await Promise.all([api('/subscriptions?filter=expiring&page=0'),api('/subscriptions?filter=all&page=0')]);
  renderRows($('home-expiring'),expiring.items.slice(0,5),'Nothing expires in the next 7 days.');
  renderRows($('home-recent'),recent.items.slice(0,5),'No customer accounts yet. Create a test or subscription to get started.');
}
async function openDetail(id){
  const data=await api('/subscriptions/'+encodeURIComponent(id));const r=data.record,box=$('sub-detail');box.replaceChildren();box.hidden=false;
  box.append(el('h2',null,(r.customer_ref||r.credentials.username)+' · '+(r.kind==='trial'?'24-hour test':'Subscription')));
  if(data.warning)box.append(Object.assign(el('div','notice error',data.warning),{}));
  box.append(el('h3','sub','Login details to give the customer'));
  const grid=el('div','credential-grid');
  for(const [label,value] of [['USERNAME',r.credentials.username],['PASSWORD',r.credentials.password]].concat(r.credentials.server_url?[['SERVER',r.credentials.server_url]]:[])){
    const wrap=el('div');wrap.append(el('label',null,label));const code=el('code',null,value);wrap.append(code);
    const copy=el('button','text-button','Copy');copy.type='button';copy.onclick=async()=>{try{await navigator.clipboard.writeText(value);copy.textContent='Copied ✓';setTimeout(()=>copy.textContent='Copy',1600);}catch{error('Clipboard unavailable. Select and copy the text.');}};wrap.append(copy);grid.append(wrap);
  }
  box.append(grid);
  const actions=el('div','actions');const all=el('button','primary','Copy login + setup guide');all.type='button';
  all.onclick=async()=>{if(!apps)await loadApps().catch(fail);copyText(all,guideText(r.credentials),'Copy login + setup guide');};
  const guideLink=el('a','secondary','Open the setup guide');guideLink.href='#/apps';actions.append(all,guideLink);box.append(actions);
  const dl=el('dl','plain');
  for(const [k,v] of [['Subscription ID',r.provider_id],['Connections',r.connections]].concat(r.kind==='trial'?[]:[['Content',r.adult?'With adult':'No adult']]).concat([['Status',r.status],['Started',when(r.starts_at)],['Expires',when(r.expires_at)],['Last confirmed',when(r.confirmed_at)]])){const d=el('div');d.append(el('dt',null,k),el('dd',null,String(v)));dl.append(d);}
  box.append(el('h3','sub','Details'));box.append(dl);
  if(data.extensions.length){const h=el('h3','sub','Extensions');box.append(h);const l=el('div','muted');l.innerHTML='';for(const e of data.extensions)l.append(el('div',null,when(e.created_at)+' · +'+e.months+' months · '+e.credits+' credits · new expiry '+when(e.confirmed_expiry)));box.append(l);}
  if(me.status==='active'&&!data.warning&&['active','expired'].includes(r.status)){
    const ext=el('div','extend');ext.append(el('h3','sub',r.kind==='trial'?'Convert this test into a paid subscription':'Extend this subscription'));
    const opts=el('div','connection-options');let months=1;
    const render=()=>{opts.replaceChildren();for(const m of [1,3,6,9,12]){const b=el('button','choice',m+' month'+(m>1?'s':''));b.type='button';b.setAttribute('aria-pressed',String(months===m));b.onclick=()=>{months=m;render();};opts.append(b);}};render();
    const go=el('button','primary');go.textContent='Preview extension';go.type='button';const status=el('div','notice');status.hidden=true;
    go.onclick=()=>busy(go,async()=>{
      const p=await api('/operations/preview',{method:'POST',data:{kind:'extend',months,connections:r.connections,adult:!!r.adult,target:r.id}});
      status.hidden=false;status.textContent='Cost '+p.preview.cost+' credits · available '+p.preview.available+' · remaining '+p.preview.remaining+'. ';
      if(p.preview.remaining<0){status.append(document.createTextNode('Not enough credits. '));return;}
      const ok=el('button','text-button','Confirm extension');ok.type='button';ok.onclick=()=>busy(ok,async()=>{const c=await api('/operations/confirm',{method:'POST',data:{nonce:p.nonce}});await watch(c.operation.id,status,()=>openDetail(id));});status.append(ok);
    });
    ext.append(opts,go,status);box.append(ext);
  }
  box.scrollIntoView({behavior:'smooth',block:'start'});
}
async function watch(oid,node,done){
  clearInterval(pollTimer);node.hidden=false;node.textContent='Request queued. Creating the account with the provider…';
  await new Promise(resolve=>{pollTimer=setInterval(async()=>{try{const {operation}=await api('/operations/'+oid);
    if(operation.status==='succeeded'){clearInterval(pollTimer);node.textContent='Done. Credits deducted: '+operation.credit_cost+'.';await refreshMe();if(done)await done(operation);resolve();}
    else if(operation.status==='failed'){clearInterval(pollTimer);node.textContent='The provider rejected this request. Reserved credits were released. '+(operation.message||'');await refreshMe();resolve();}
    else if(operation.status==='uncertain'){clearInterval(pollTimer);node.textContent='The provider did not confirm the result. Credits stay reserved while support checks it; do not create this customer again. '+me.support;resolve();}
    else node.textContent='Working… ('+operation.status+')';}catch(e){clearInterval(pollTimer);fail(e);resolve();}},1500);});
}

// ---------- apps & setup guide ----------
let apps=null;
async function copyText(button,text,label){try{await navigator.clipboard.writeText(text);const was=button.textContent;button.textContent='Copied ✓';setTimeout(()=>button.textContent=label||was,1600);}catch{error('Clipboard unavailable. Select and copy the text.');}}
function guideText(credentials){
  if(!apps)return '';const g=apps.guide,brand=apps.brand;const out=[];
  if(credentials){out.push('Your '+brand+' login','Username: '+credentials.username,'Password: '+credentials.password);if(credentials.server_url)out.push('Server: '+credentials.server_url);out.push('');}
  out.push('HOW TO INSTALL','');
  out.push(g.firestick.title.toUpperCase());g.firestick.steps.forEach((st,i)=>out.push((i+1)+'. '+st));out.push('Downloader codes:');for(const a of g.firestick.apps)out.push('  '+a.name+': '+a.codes.join(' or '));out.push('');
  out.push(g.apple.title.toUpperCase());g.apple.steps.forEach((st,i)=>out.push((i+1)+'. '+st));out.push('Site: '+g.apple.site,'URL code: '+g.apple.url_code,'');
  out.push(g.android.title.toUpperCase());g.android.steps.forEach((st,i)=>out.push((i+1)+'. '+st));out.push('App links:');for(const a of g.android.apps)out.push('  '+a.name+': '+a.url);
  return out.join('\n');
}
function codeChip(value){const chip=el('span','code-chip');chip.append(document.createTextNode(value));const b=el('button',null,'Copy');b.type='button';b.onclick=()=>copyText(b,value,'Copy');chip.append(b);return chip;}
function appCard(title,steps,build){const card=el('article','card app-card');card.append(el('h2',null,title));const ol=el('ol');for(const st of steps)ol.append(el('li',null,st));card.append(ol);build(card);return card;}
async function loadApps(){
  if(!apps)apps=await api('/apps');const g=apps.guide,root=$('apps-content');root.replaceChildren();
  root.append(appCard(g.firestick.title,g.firestick.steps,card=>{
    const t=el('div','app-table');for(const a of g.firestick.apps){t.append(el('div','name',a.name));const codes=el('div','codes');for(const c of a.codes)codes.append(codeChip(c));t.append(codes);}card.append(t);
    if(g.firestick.note)card.append(el('p','fineprint app-note',g.firestick.note));
  }));
  root.append(appCard(g.apple.title,g.apple.steps,card=>{
    const t=el('div','app-table');t.append(el('div','name','Download'));const site=el('a','app-link',g.apple.site);site.href='https://'+g.apple.site;site.target='_blank';site.rel='noopener';t.append(site);
    t.append(el('div','name','URL code'));const codes=el('div','codes');codes.append(codeChip(g.apple.url_code));t.append(codes);card.append(t);
  }));
  root.append(appCard(g.android.title,g.android.steps,card=>{
    const t=el('div','app-table');for(const a of g.android.apps){t.append(el('div','name',a.name));const codes=el('div','codes');const link=el('a','app-link',a.url);link.href=a.url;link.target='_blank';link.rel='noopener';codes.append(link);const b=el('button','text-button','Copy link');b.type='button';b.onclick=()=>copyText(b,a.url,'Copy link');codes.append(b);t.append(codes);}card.append(t);
  }));
}
$('copy-guide').onclick=async()=>{if(!apps)await loadApps().catch(fail);copyText($('copy-guide'),guideText(),'Copy setup guide');};

// ---------- create ----------
function renderCreate(){
  document.querySelectorAll('[data-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.kind===create.kind)));
  document.querySelectorAll('[data-adult]').forEach(b=>b.setAttribute('aria-pressed',String((b.dataset.adult==='1')===create.adult)));
  $('months-field').hidden=create.kind==='trial';$('connections-field').hidden=create.kind==='trial';$('content-field').hidden=create.kind==='trial';
  const mo=$('months-options');mo.replaceChildren();for(const m of [1,3,6,9,12]){const b=el('button','choice',m+' mo');b.type='button';b.setAttribute('aria-pressed',String(create.months===m));b.onclick=()=>{create.months=m;renderCreate();};mo.append(b);}
  const co=$('connections-options');co.replaceChildren();for(const c of [1,2,3]){const b=el('button','choice',String(c));b.type='button';b.setAttribute('aria-pressed',String(create.connections===c));b.onclick=()=>{create.connections=c;renderCreate();};co.append(b);}
  $('cs-title').textContent=create.kind==='trial'?'24-hour test':create.months+' month'+(create.months>1?'s':'');
  $('cs-detail').textContent=create.kind==='trial'?'1 device · standard content':create.connections+' device'+(create.connections>1?'s':'')+' · '+(create.adult?'With adult':'No adult');
  const cost=create.kind==='trial'?0:(packages&&packages.costs.find(c=>c.months===create.months&&c.connections===create.connections)||{}).credits;
  $('cs-cost').textContent=cost===undefined?'–':cost;$('cs-available').textContent=me?me.credits.available:'–';$('cs-remaining').textContent='–';
  $('confirm-create').hidden=true;nonce=null;$('op-status').hidden=true;
  if(!packages)loadPackages().then(renderCreate).catch(()=>{});
}
async function loadPackages(){
  if(!packages)packages=await api('/packages');
  const packs=$('packs');if(!packs.dataset.ready){packs.dataset.ready='1';
    for(const p of packages.packages){const b=el('button','choice');b.type='button';b.append(el('b',null,money(p.price_pence)));b.append(el('span','choice-price',p.credits+' credits'));b.onclick=()=>{packs.querySelectorAll('.choice').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');packs.dataset.pick=p.id;};packs.append(b);}
    const sel=$('pay-asset');for(const a of packages.assets){const o=el('option',null,a.symbol+' · '+(names[a.network]||a.network));o.value=a.id;sel.append(o);}
    const t=$('costs');const months=[...new Set(packages.costs.map(c=>c.months))];const head=el('tr');head.append(el('th',null,'Months'));for(const c of [1,2,3])head.append(el('th',null,c+' connection'+(c>1?'s':'')));t.append(head);
    for(const m of months){const tr=el('tr');tr.append(el('td',null,String(m)));for(const c of [1,2,3]){const f=packages.costs.find(x=>x.months===m&&x.connections===c);tr.append(el('td',null,f?f.credits+' cr':'–'));}t.append(tr);}
  }
}
async function loadHistory(){
  const data=await api('/history?page='+hist.page);const list=$('history-list');list.replaceChildren();
  if(!data.items.length)list.append(el('div','empty','No credit movements yet.'));
  for(const r of data.items){const row=el('div','row');const a=el('div');a.append(el('strong',null,(r.movement>0?'+':'')+r.movement+' credits'));a.append(el('small',null,when(r.created_at)));const b=el('div',null,r.reason);b.style.gridColumn='span 3';const c=el('small',null,r.reference);row.append(a,b,c);list.append(row);}
  $('hist-prev').disabled=!hist.page;$('hist-next').disabled=!data.more;$('hist-page').textContent='Page '+(hist.page+1);
}

// ---------- wiring ----------
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{create.kind=b.dataset.kind;renderCreate();});
document.querySelectorAll('[data-adult]').forEach(b=>b.onclick=()=>{create.adult=b.dataset.adult==='1';renderCreate();});
$('create-form').onsubmit=e=>{e.preventDefault();busy(e.submitter||$('create-form').querySelector('.primary'),async()=>{
  const data={kind:create.kind,months:create.kind==='trial'?0:create.months,connections:create.kind==='trial'?1:create.connections,adult:create.kind==='trial'?false:create.adult,customer_ref:$('customer-ref').value.trim()};
  const p=await api('/operations/preview',{method:'POST',data});nonce=p.nonce;
  $('cs-cost').textContent=p.preview.cost;$('cs-available').textContent=p.preview.available;$('cs-remaining').textContent=p.preview.remaining;
  $('confirm-create').hidden=p.preview.remaining<0;$('cs-note').textContent=p.preview.remaining<0?'Not enough credits. Buy credits first.':'Confirming reserves '+p.preview.cost+' credits; they are deducted once the provider confirms the account.';
});};
$('confirm-create').onclick=()=>busy($('confirm-create'),async()=>{if(!nonce)return;const c=await api('/operations/confirm',{method:'POST',data:{nonce}});nonce=null;$('confirm-create').hidden=true;
  await watch(c.operation.id,$('op-status'),async op=>{if(op.result_id){$('op-status').textContent='Done. Opening the new account so you can copy the login…';location.hash='#/subscriptions?open='+encodeURIComponent(op.result_id);}});});
$('buy').onclick=()=>busy($('buy'),async()=>{const pick=$('packs').dataset.pick;if(!pick)throw new Error('Choose a credit pack first.');const q=await api('/purchase',{method:'POST',data:{package_id:pick,asset_id:$('pay-asset').value}});openInvoice(q.token,q.order);});

// ---------- credit payment inside the panel (existing order engine, token-authenticated) ----------
let inv={token:null,order:null,poll:null,clock:null,qr:null};
async function orderApi(path,{method='GET',data}={}){
  const headers={'X-Order-Token':inv.token};if(method==='POST')headers['Content-Type']='application/json';
  const response=await fetch(BASE+path,{method,headers,cache:'no-store',body:method==='POST'?JSON.stringify(data||{}):undefined});
  const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||'This request could not be completed. Please try again.');return body;
}
function openInvoice(token,order){
  inv.token=token;try{localStorage.setItem('rs-invoice',token);}catch(e){}
  showInvoice(order);$('invoice-card').scrollIntoView({behavior:'smooth',block:'start'});
}
async function resumeInvoice(){
  if(inv.token)return;let saved=null;try{saved=localStorage.getItem('rs-invoice');}catch(e){}
  if(!saved)return;inv.token=saved;
  try{showInvoice(await orderApi('/api/order'));}catch(e){closeInvoice();}
}
function closeInvoice(){
  clearTimeout(inv.poll);clearInterval(inv.clock);if(inv.qr)URL.revokeObjectURL(inv.qr);
  inv={token:null,order:null,poll:null,clock:null,qr:null};try{localStorage.removeItem('rs-invoice');}catch(e){}
  $('invoice-card').hidden=true;$('order-form').hidden=false;
}
async function showInvoice(order){
  inv.order=order;clearTimeout(inv.poll);clearInterval(inv.clock);
  const card=$('invoice-card');card.hidden=false;$('order-form').hidden=order.status==='pending';
  const asset=order.asset||{};const chip=$('inv-status');
  $('inv-plan').textContent=(order.plan&&order.plan.name)||'';$('inv-network').textContent=(asset.symbol||'')+' · '+(names[asset.network]||asset.network||'');
  $('inv-amount').textContent=(order.amount||'')+' '+(asset.symbol||'');$('inv-wallet').textContent=asset.wallet||'';
  $('inv-quote').textContent=order.plan&&order.plan.gbp_price?'£'+order.plan.gbp_price+' at the rate locked for this quote.':'';
  $('inv-demo').hidden=!(me&&me.demo&&order.status==='pending');
  $('inv-message').textContent=order.message||'';
  const labels={pending:order.txid?'CHECKING PAYMENT':'AWAITING PAYMENT',paid:'PAID · ADDING CREDITS',provisioning:'PAID · ADDING CREDITS',fulfilled:'CREDITS ADDED',review:'NEEDS A MANUAL CHECK',expired:'QUOTE EXPIRED'};
  chip.textContent=labels[order.status]||order.status.toUpperCase();
  $('inv-verify-form').hidden=order.status!=='pending';
  if(order.status==='fulfilled'){$('inv-heading').textContent='Credits added';$('inv-message').textContent='Your balance is updated. Thank you.';await refreshMe();}
  else $('inv-heading').textContent=order.status==='pending'?'Pay to add credits':'Payment received';
  if(order.status==='pending'&&!inv.qr){try{const r=await fetch(BASE+'/api/order/qr',{headers:{'X-Order-Token':inv.token},cache:'no-store'});if(r.ok){inv.qr=URL.createObjectURL(await r.blob());$('inv-qr').src=inv.qr;}}catch(e){}}
  const tick=()=>{const left=Math.max(0,(order.expires_at||0)-Math.floor(Date.now()/1000));$('inv-countdown').textContent=left?String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0'):'Expired';
    if(!left&&order.status==='pending'){$('inv-warning').textContent='This quote has expired. Do not send a new payment to it. If you already paid, submit your TXID; otherwise start a new order.';}};
  tick();inv.clock=setInterval(tick,1000);
  if(['pending','paid','provisioning'].includes(order.status))inv.poll=setTimeout(async()=>{try{showInvoice(await orderApi('/api/order'));}catch(e){inv.poll=setTimeout(()=>resumeInvoice(),15000);}},order.status==='pending'?20000:4000);
}
$('inv-verify-form').onsubmit=e=>{e.preventDefault();busy($('inv-verify'),async()=>showInvoice(await orderApi('/api/order/verify',{method:'POST',data:{txid:$('inv-txid').value.trim()}})));};
$('inv-demo').onclick=()=>busy($('inv-demo'),async()=>showInvoice(await orderApi('/api/order/demo-pay',{method:'POST'})));
$('inv-dismiss').onclick=closeInvoice;
$('inv-copy-amount').onclick=async()=>{try{await navigator.clipboard.writeText(String(inv.order.amount));$('inv-copy-amount').textContent='Copied ✓';setTimeout(()=>$('inv-copy-amount').textContent='Copy amount',1600);}catch{error('Clipboard unavailable. Select and copy the text.');}};
$('inv-copy-wallet').onclick=async()=>{try{await navigator.clipboard.writeText(inv.order.asset.wallet);$('inv-copy-wallet').textContent='Copied ✓';setTimeout(()=>$('inv-copy-wallet').textContent='Copy address',1600);}catch{error('Clipboard unavailable. Select and copy the text.');}};
document.querySelectorAll('#filters .chip').forEach(b=>b.onclick=()=>{sub.filter=b.dataset.filter;sub.page=0;loadSubs().catch(fail);});
$('search-form').onsubmit=e=>{e.preventDefault();sub.search=$('search').value.trim();sub.page=0;loadSubs().catch(fail);};
$('global-search').onsubmit=e=>{e.preventDefault();sub.search=$('global-search-input').value.trim();$('search').value=sub.search;sub.page=0;sub.filter='all';if(location.hash.startsWith('#/subscriptions'))loadSubs().catch(fail);else location.hash='#/subscriptions';};
$('sub-prev').onclick=()=>{sub.page--;loadSubs().catch(fail);};$('sub-next').onclick=()=>{sub.page++;loadSubs().catch(fail);};
$('hist-prev').onclick=()=>{hist.page--;loadHistory().catch(fail);};$('hist-next').onclick=()=>{hist.page++;loadHistory().catch(fail);};
$('password-form').onsubmit=e=>{e.preventDefault();busy(e.submitter||$('password-form').querySelector('.primary'),async()=>{applyMe(await api('/session/password',{method:'POST',data:{email:$('login-email').value,password:$('login-password').value}}));$('login-password').value='';location.hash='#/dashboard';route();});};
$('account-form').onsubmit=e=>{e.preventDefault();busy(e.submitter||$('account-form').querySelector('.primary'),async()=>{
  const r=await api('/account',{method:'POST',data:{email:$('acc-new-email').value,password:$('acc-new-password').value,current_password:$('acc-current').value}});
  me.login=r.login;$('acc-new-password').value='';$('acc-current').value='';$('acc-saved').hidden=false;applyMe(me);});};
$('signout').onclick=()=>busy($('signout'),async()=>{await api('/signout',{method:'POST'});signedOut();});
$('signout-all').onclick=()=>busy($('signout-all'),async()=>{await api('/signout-everywhere',{method:'POST'});signedOut();});
$('support-button').onclick=()=>{if(me&&me.support_url)window.open(me.support_url,'_blank','noopener');else error(me?me.support:'Sign in to see support details.');};
window.addEventListener('hashchange',route);

(async()=>{
  const m=location.hash.match(/^#code=([A-Za-z0-9_-]{20,100})$/);
  try{
    if(m){history.replaceState(null,'',location.pathname);applyMe(await api('/session/code',{method:'POST',data:{code:m[1]}}));location.hash='#/dashboard';}
    else applyMe(await api('/me'));
    route();
  }catch(e){if(e instanceof SignedOut)signedOut();else{signedOut();error(e.message);}}
})();
