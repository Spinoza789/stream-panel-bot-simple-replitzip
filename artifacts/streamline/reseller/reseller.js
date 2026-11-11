'use strict';
const $=id=>document.getElementById(id);
const BASE=document.querySelector('meta[name="streambot-base-path"]').content;
const API=BASE+'/api/reseller';
let me=null,packages=null,apps=null,sub={filter:'active',page:0,search:'',items:[],sort:{key:'expires_at',dir:'asc'},selected:new Set()},hist={page:0},
    create={kind:'create',months:1,connections:1},tk={filter:'active',page:0,topics:null},nonce=null,pollTimer=null,credits={pack:null,asset:null};
const names={ethereum:'Ethereum',solana:'Solana',bitcoin:'Bitcoin'};
const when=ts=>new Date(ts*1000).toLocaleString('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Europe/London'});
const whenDay=ts=>new Date(ts*1000).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/London'});
const money=p=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',maximumFractionDigits:2,minimumFractionDigits:0}).format(p/100);
const plural=(n,word)=>n+' '+word+(n===1?'':'s');
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}
class SignedOut extends Error{}

// ---------- feedback: toasts, inline errors, one page-level banner for load failures ----------
let toastTimer=null;
function toast(message){const t=$('toast');t.textContent=message;t.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{t.hidden=true;},2200);}
function error(message){const box=me?$('error'):$('signin-error');box.textContent=message||'';box.hidden=!message;}
function inlineError(anchor,message){
  // Show the message right under the control that failed; fall back to the page banner.
  let node=anchor&&anchor.closest&&anchor.closest('form, .actions, .extend, .drawer-body, .card');
  let slot=node&&node.querySelector('.inline-error');
  if(!slot&&node){slot=el('p','inline-error');(anchor.parentElement===node?node:anchor.parentElement).insertAdjacentElement('afterend',slot);}
  if(slot){slot.textContent=message||'';slot.hidden=!message;}else error(message);
}
async function busy(button,work){
  const text=button.textContent;button.disabled=true;inlineError(button,'');
  try{await work();}catch(e){if(e instanceof SignedOut)return signedOut();inlineError(button,e.message);}finally{button.disabled=false;button.textContent=text;}
}
async function api(path,{method='GET',data}={}){
  const headers={};if(method==='POST')headers['Content-Type']='application/json';
  const response=await fetch(API+path,{method,headers,credentials:'same-origin',cache:'no-store',body:method==='POST'?JSON.stringify(data||{}):undefined});
  const body=await response.json().catch(()=>({}));
  if(response.status===401)throw new SignedOut(body.error||'Sign in required.');
  if(!response.ok)throw new Error(body.error||'This request could not be completed. Please try again.');
  return body;
}
function fail(e){if(e instanceof SignedOut)return signedOut();error(e.message);}
async function copyText(button,text,label){try{await navigator.clipboard.writeText(text);toast('Copied');}catch{inlineError(button,'Clipboard unavailable. Select and copy the text.');}}
function skeleton(tbody,rows,cols){tbody.replaceChildren();for(let i=0;i<rows;i++){const tr=el('tr','skeleton');for(let c=0;c<cols;c++){const td=el('td');td.append(el('span'));tr.append(td);}tbody.append(tr);}}

// ---------- theme ----------
function applyTheme(theme){if(theme)document.documentElement.setAttribute('data-theme',theme);else document.documentElement.removeAttribute('data-theme');}
(function(){let saved=null;try{saved=localStorage.getItem('rs-theme');}catch(e){}if(saved)applyTheme(saved);})();
$('theme-toggle').onclick=()=>{const dark=document.documentElement.getAttribute('data-theme')==='dark';const next=dark?'light':'dark';applyTheme(next);try{localStorage.setItem('rs-theme',next);}catch(e){}};

// ---------- shell ----------
function signedOut(){me=null;$('shell').hidden=true;$('view-signin').hidden=false;$('loading').hidden=true;closeDrawer(false);}
function applyMe(data){
  me=data;if(!apps)api('/apps').then(a=>{apps=a;}).catch(()=>{});
  document.querySelectorAll('[data-brand]').forEach(n=>n.textContent=me.brand);$('demo-banner').hidden=!me.demo;
  $('who').textContent=(me.username?'@'+me.username:'ID '+me.telegram_id);$('who').hidden=false;$('signout').hidden=false;$('avatar').textContent=(me.username||'R')[0].toUpperCase();
  $('view-signin').hidden=true;$('shell').hidden=false;$('loading').hidden=true;
  const hour=new Date().getHours();$('greeting').textContent=(hour<12?'Good morning':hour<18?'Good afternoon':'Good evening')+(me.username?', @'+me.username:'');
  $('t-available').textContent=me.credits.available;$('t-reserved').textContent=me.credits.reserved?me.credits.reserved+' reserved for pending requests':'';
  $('t-active').textContent=me.counts.active;$('t-expiring').textContent=me.counts.expiring;$('t-trials').textContent=me.counts.trials;
  $('c-available').textContent=me.credits.available;$('c-reserved').textContent=me.credits.reserved?me.credits.reserved+' reserved for pending requests':'';
  const fresh=!me.counts.total;$('home-empty').hidden=!fresh;$('home-full').hidden=fresh;
  const note=$('status-note');
  if(me.status==='pending'){note.textContent='Buy your first credit pack to activate your reseller account. Credits are added, and the account goes live, as soon as the payment is verified.';note.hidden=false;}
  else if(me.status==='suspended'){note.textContent='Your reseller account is suspended. You can view records but not buy, create or extend. '+me.support;note.hidden=false;}
  else note.hidden=true;
  $('acc-id').textContent=me.telegram_id;$('acc-username').textContent=me.username?'@'+me.username:'—';$('acc-status').textContent=me.status[0].toUpperCase()+me.status.slice(1);
  $('acc-email').textContent=me.login.email||'Not set';$('acc-form-title').textContent=me.login.has_password?'Change recovery email or password':'Add a recovery email and password';
  $('current-wrap').hidden=!me.login.has_password;$('acc-current').required=me.login.has_password;
  if(me.login.email)$('acc-new-email').value=me.login.email;
  $('export-customers').href=API+'/subscriptions.csv';$('export-history').href=API+'/history.csv';$('install-link').href=BASE+'/install';
}
async function refreshMe(){applyMe(await api('/me'));}
function route(){
  if(!me)return;
  const hash=location.hash.replace(/^#\/?/,'')||'dashboard';const [tab,query]=hash.split('?');const params=new URLSearchParams(query||'');
  const known=['dashboard','subscriptions','create','credits','apps','history','support','account'];const view=known.includes(tab)?tab:'dashboard';
  known.forEach(v=>$('view-'+v).hidden=v!==view);
  document.querySelectorAll('#tabs a, .tabbar a').forEach(a=>a.getAttribute('data-tab')===view?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current'));
  error('');$('more-sheet').hidden=true;
  if(view==='subscriptions'){if(params.get('filter'))sub.filter=params.get('filter');loadSubs().catch(fail);if(params.get('open'))openDetail(params.get('open')).catch(fail);else closeDrawer(false);}
  else if(!(view==='support'&&params.get('open')))closeDrawer(false);
  if(view==='history')loadHistory().catch(fail);
  if(view==='support'){loadTickets().catch(fail);if(params.get('open'))openTicket(params.get('open')).catch(fail);if(params.get('new'))showTicketForm(true);}
  if(view==='credits'){loadPackages().then(()=>{if(!inv.token)showStep(credits.pack?2:1);}).catch(fail);resumeInvoice();}
  if(view==='create')renderCreate();
  if(view==='apps')loadApps().catch(fail);
  if(view==='dashboard'){refreshMe().then(loadHome).catch(fail);}
  window.scrollTo({top:0});
}

// ---------- customers: table, sorting, selection, bulk extend ----------
function expiryInfo(r){
  const now=Date.now()/1000;const days=Math.ceil((r.expires_at-now)/86400);
  if(r.expires_at<=now){const ago=Math.max(1,Math.floor((now-r.expires_at)/86400));return {pill:['Expired','bad'],days:[ago===1?'Expired yesterday':'Expired '+ago+' days ago','bad']};}
  const left=days<=1?'Expires today':days===2?'Expires tomorrow':'in '+days+' days';
  if(r.expires_at<now+7*86400)return {pill:['Expiring soon','warn'],days:[left,'warn']};
  return {pill:[r.status[0].toUpperCase()+r.status.slice(1),r.status==='active'?'ok':''],days:[left,'ok']};
}
function deletable(r){return r.expires_at<=Date.now()/1000||['expired','disabled'].includes(r.status);}
async function deleteOne(id){await api('/subscriptions/'+encodeURIComponent(id)+'/delete',{method:'POST',data:{}});}
function sorted(items){
  const {key,dir}=sub.sort;const sign=dir==='asc'?1:-1;
  return [...items].sort((a,b)=>{const x=key==='customer_ref'?(a.customer_ref||a.username).toLowerCase():a[key];const y=key==='customer_ref'?(b.customer_ref||b.username).toLowerCase():b[key];return (x>y?1:x<y?-1:0)*sign;});
}
function subRow(r,{selectable=true}={}){
  const tr=el('tr');tr.dataset.id=r.id;if(sub.selected.has(r.id))tr.classList.add('selected');
  if(selectable){const td=el('td','check');const cb=el('input');cb.type='checkbox';cb.checked=sub.selected.has(r.id);cb.setAttribute('aria-label','Select '+(r.customer_ref||r.username));
    cb.onclick=e=>{e.stopPropagation();if(cb.checked)sub.selected.add(r.id);else sub.selected.delete(r.id);tr.classList.toggle('selected',cb.checked);renderBulk();};td.append(cb);tr.append(td);}
  const name=el('td');name.append(el('strong',null,r.customer_ref||r.username));name.append(el('small',null,(r.contact?r.contact+' · ':'')+r.username));
  const kind=el('td');kind.append(document.createTextNode(r.kind==='trial'?'24-hour test':'Subscription'));kind.append(el('small',null,plural(r.connections,'device')));
  const started=el('td','hide-sm',whenDay(r.starts_at));
  const info=expiryInfo(r);const exp=el('td');exp.append(document.createTextNode(whenDay(r.expires_at)));const d=el('small','days '+info.days[1],info.days[0]);exp.append(d);
  const st=el('td');st.append(el('span','pill '+info.pill[1],info.pill[0]));
  tr.append(name,kind,started,exp,st);
  tr.onclick=()=>{if(location.hash.startsWith('#/subscriptions'))openDetail(r.id).catch(fail);else location.hash='#/subscriptions?open='+encodeURIComponent(r.id);};
  return tr;
}
function renderTable(){
  const body=$('sub-list');body.replaceChildren();
  if(!sub.items.length){const tr=el('tr');const td=el('td','empty',sub.search?'No customers match "'+sub.search+'".':'No customers here yet.');td.colSpan=6;tr.append(td);body.append(tr);}
  for(const r of sorted(sub.items))body.append(subRow(r));
  document.querySelectorAll('#sub-table th button').forEach(b=>{if(b.dataset.sort===sub.sort.key)b.dataset.dir=sub.sort.dir;else delete b.dataset.dir;});
  $('select-all').checked=sub.items.length>0&&sub.items.every(r=>sub.selected.has(r.id));
  renderBulk();
}
function renderBulk(){const n=sub.selected.size;$('bulk-bar').hidden=!n;$('bulk-count').textContent=plural(n,'customer')+' selected';}
async function loadSubs(){
  document.querySelectorAll('#filters .chip').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===sub.filter)));
  $('search').value=sub.search;skeleton($('sub-list'),5,6);
  const data=await api('/subscriptions?filter='+encodeURIComponent(sub.filter)+'&page='+sub.page+'&search='+encodeURIComponent(sub.search));
  sub.items=data.items;renderTable();renderExpiredBar();
  $('sub-prev').disabled=!sub.page;$('sub-next').disabled=!data.more;$('sub-page').textContent='Page '+(sub.page+1);
}
function renderMiniList(container,items,empty){
  container.replaceChildren();
  if(!items.length){container.append(el('div','empty',empty));return;}
  const table=el('table','index-table');const body=el('tbody');for(const r of items)body.append(subRow(r,{selectable:false}));table.append(body);container.append(table);
}
async function loadHome(){
  if(!me||!me.counts.total)return;
  for(const id of ['home-expiring','home-recent']){const c=$(id);c.replaceChildren();for(let i=0;i<3;i++)c.append(el('div','skeleton-row'));}
  const [expiring,recent,stats]=await Promise.all([api('/subscriptions?filter=expiring&page=0'),api('/subscriptions?filter=all&page=0'),api('/stats')]);
  renderMiniList($('home-expiring'),expiring.items.slice(0,5),'Nothing expires in the next 7 days.');
  renderMiniList($('home-recent'),recent.items.slice(0,5),'No customer accounts yet.');
  const m=stats.this_month,a=stats.all_time;
  $('stats-month').textContent=new Date().toLocaleDateString('en-GB',{month:'long',year:'numeric'});
  $('s-used').textContent=m.credits_used;$('s-bought').textContent=m.credits_bought;$('s-tests').textContent=m.tests_created;
  $('s-converted').textContent=m.tests_converted+(m.tests_created?' ('+m.conversion_rate+'%)':'');
  $('s-alltime').textContent='All time: '+plural(a.credits_used,'credit')+' used, '+plural(a.tests_created,'test')+' created, '+a.tests_converted+' converted'+(a.tests_created?' ('+a.conversion_rate+'%)':'')+'.';
}
async function bulkExtend(){
  const ids=[...sub.selected];const months=parseInt($('bulk-months').value,10);const status=$('bulk-status');
  if(me.status!=='active')throw new Error('Your reseller account is not active.');
  let done=0,failed=[];
  for(const id of ids){
    const r=sub.items.find(x=>x.id===id);status.textContent='Extending '+(done+1)+' of '+ids.length+'…';
    try{
      const p=await api('/operations/preview',{method:'POST',data:{kind:'extend',months,connections:r?r.connections:1,adult:!!(r&&r.adult),target:id}});
      if(p.preview.remaining<0)throw new Error('not enough credits');
      const c=await api('/operations/confirm',{method:'POST',data:{nonce:p.nonce}});
      await waitFor(c.operation.id);done++;
    }catch(e){if(e instanceof SignedOut)throw e;failed.push((r?(r.customer_ref||r.username):id)+': '+e.message);}
  }
  sub.selected.clear();await refreshMe();await loadSubs();
  status.textContent='';toast(plural(done,'customer')+' extended'+(failed.length?', '+failed.length+' failed':''));
  if(failed.length)error('Could not extend: '+failed.join('; '));
}
async function waitFor(oid){
  for(let i=0;i<40;i++){const {operation}=await api('/operations/'+oid);
    if(operation.status==='succeeded')return operation;
    if(operation.status==='failed')throw new Error(operation.message||'provider rejected the request');
    if(operation.status==='uncertain')throw new Error('provider did not confirm; support is checking');
    await new Promise(r=>setTimeout(r,1500));}
  throw new Error('still processing');
}

// ---------- customer drawer ----------
function openDrawer(){$('drawer').hidden=false;$('drawer-backdrop').hidden=false;document.body.style.overflow='hidden';}
function closeDrawer(updateHash=true){
  $('drawer').hidden=true;$('drawer-backdrop').hidden=true;document.body.style.overflow='';
  if(updateHash&&location.hash.includes('open=')){const [tab,query]=location.hash.replace(/^#\/?/,'').split('?');const p=new URLSearchParams(query||'');p.delete('open');history.replaceState(null,'','#/'+tab+(p.toString()?'?'+p:''));}
}
$('drawer-close').onclick=()=>closeDrawer();$('drawer-backdrop').onclick=()=>closeDrawer();
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('drawer').hidden)closeDrawer();});
async function openDetail(id){
  const box=$('sub-detail');box.replaceChildren();for(let i=0;i<4;i++)box.append(el('div','skeleton-row'));$('drawer-title').textContent='Customer';openDrawer();
  const data=await api('/subscriptions/'+encodeURIComponent(id));const r=data.record;box.replaceChildren();
  const info=expiryInfo(r);
  $('drawer-title').textContent=(r.customer_ref||r.credentials.username);
  const head=el('div','actions');head.append(el('span','pill '+info.pill[1],info.pill[0]));head.append(el('span','muted',(r.kind==='trial'?'24-hour test':'Subscription')+' · '+plural(r.connections,'device')+' · '+info.days[0]));box.append(head);
  if(data.warning)box.append(el('div','notice error',data.warning));
  box.append(el('h3','sub','Login details to give the customer'));
  const grid=el('div','credential-grid');
  for(const [label,value] of [['Username',r.credentials.username],['Password',r.credentials.password]].concat(r.credentials.server_url?[['Server',r.credentials.server_url]]:[])){
    const wrap=el('div');wrap.append(el('label',null,label));wrap.append(el('code',null,value));
    const copy=el('button','text-button','Copy');copy.type='button';copy.onclick=()=>copyText(copy,value);wrap.append(copy);grid.append(wrap);
  }
  box.append(grid);
  const actions=el('div','actions');const all=el('button','primary','Copy login + setup guide');all.type='button';
  all.onclick=async()=>{if(!apps)await loadApps().catch(fail);copyText(all,guideText(r.credentials));};
  const guideLink=el('a','secondary','Open the setup guide');guideLink.href='#/apps';guideLink.onclick=()=>closeDrawer(false);actions.append(all,guideLink);box.append(actions);
  // notes
  box.append(el('h3','sub','Your notes'));
  const form=el('form','notes-form');
  const n1=el('div');n1.append(el('label','select-label','Customer name'));const nameIn=el('input');nameIn.maxLength=100;nameIn.value=r.customer_ref||'';n1.append(nameIn);
  const n2=el('div');n2.append(el('label','select-label','Contact'));const contactIn=el('input');contactIn.maxLength=100;contactIn.placeholder='Phone, Telegram or email';contactIn.value=r.contact||'';n2.append(contactIn);
  const save=el('button','secondary','Save');save.type='submit';form.append(n1,n2,save);
  form.onsubmit=e=>{e.preventDefault();busy(save,async()=>{await api('/subscriptions/'+encodeURIComponent(id)+'/notes',{method:'POST',data:{customer_ref:nameIn.value,contact:contactIn.value}});toast('Saved');$('drawer-title').textContent=nameIn.value||r.credentials.username;loadSubs().catch(()=>{});});};
  box.append(form);box.append(el('p','fineprint','Only you see these. They are never sent to the customer or the provider.'));
  const dl=el('dl','plain');
  for(const [k,v] of [['Subscription ID',r.provider_id],['Devices',plural(r.connections,'device')]].concat([['Status',r.status[0].toUpperCase()+r.status.slice(1)],['Started',when(r.starts_at)],['Expires',when(r.expires_at)],['Last confirmed',when(r.confirmed_at)]])){const d=el('div');d.append(el('dt',null,k),el('dd',null,String(v)));dl.append(d);}
  box.append(el('h3','sub','Details'));box.append(dl);
  if(data.extensions.length){box.append(el('h3','sub','Extensions'));const l=el('div','muted');for(const e of data.extensions)l.append(el('div',null,when(e.created_at)+' · extended by '+plural(e.months,'month')+' · '+plural(e.credits,'credit')+' · now expires '+when(e.confirmed_expiry)));box.append(l);}
  if(me.status==='active'&&!data.warning&&['active','expired'].includes(r.status)){
    const ext=el('div','extend');ext.append(el('h3','sub',r.kind==='trial'?'Upgrade this test to a paid subscription':'Extend this subscription'));
    const opts=el('div','connection-options');let months=1;
    const render=()=>{opts.replaceChildren();for(const m of [1,3,6,9,12]){const b=el('button','choice',plural(m,'month'));b.type='button';b.setAttribute('aria-pressed',String(months===m));b.onclick=()=>{months=m;render();};opts.append(b);}};render();
    const go=el('button','primary','Check cost');go.type='button';const status=el('div','notice');status.hidden=true;
    go.onclick=()=>busy(go,async()=>{
      const p=await api('/operations/preview',{method:'POST',data:{kind:'extend',months,connections:r.connections,adult:!!r.adult,target:r.id}});
      status.hidden=false;status.replaceChildren(document.createTextNode('Cost: '+plural(p.preview.cost,'credit')+'. Available: '+p.preview.available+'. Left after: '+p.preview.remaining+'. '));
      if(p.preview.remaining<0){status.append(document.createTextNode('Not enough credits. Order more under Credits.'));return;}
      const ok=el('button','primary','Confirm '+(r.kind==='trial'?'upgrade':'extension'));ok.type='button';ok.style.marginLeft='8px';
      ok.onclick=()=>busy(ok,async()=>{const c=await api('/operations/confirm',{method:'POST',data:{nonce:p.nonce}});await watch(c.operation.id,status,()=>{toast('Extended');loadSubs().catch(()=>{});return openDetail(id);});});status.append(ok);
    });
    ext.append(opts,go,status);box.append(ext);
  }
  if(deletable(r)){
    const zone=el('div','drawer-danger');zone.append(el('h3','sub','Finished with this '+(r.kind==='trial'?'test':'subscription')+'?'));
    zone.append(el('p',null,'It has expired. Deleting removes it from your customer list only; your credit history and reports keep it.'));
    const del=el('button','secondary danger','Delete from my list');del.type='button';
    del.onclick=()=>{if(!confirm('Delete '+(r.customer_ref||r.credentials.username)+' from your list?'))return;busy(del,async()=>{await deleteOne(id);toast('Deleted');closeDrawer(false);await refreshMe();await loadSubs();});};
    zone.append(del);box.append(zone);
  }
}
async function watch(oid,node,done){
  clearInterval(pollTimer);node.hidden=false;node.textContent='Creating the account…';
  await new Promise(resolve=>{pollTimer=setInterval(async()=>{try{const {operation}=await api('/operations/'+oid);
    if(operation.status==='succeeded'){clearInterval(pollTimer);node.textContent='Done. '+plural(operation.credit_cost,'credit')+' used.';await refreshMe();if(done)await done(operation);resolve();}
    else if(operation.status==='failed'){clearInterval(pollTimer);node.textContent='The provider rejected this request. Reserved credits were released. '+(operation.message||'');await refreshMe();resolve();}
    else if(operation.status==='uncertain'){clearInterval(pollTimer);node.textContent='The provider did not confirm the result. Credits stay reserved while support checks it; do not create this customer again. '+me.support;resolve();}
    else node.textContent='Working…';}catch(e){clearInterval(pollTimer);fail(e);resolve();}},1500);});
}

// ---------- apps & setup guide ----------
function guideText(credentials){
  if(!apps)return '';const g=apps.guide,brand=apps.brand;const out=[];
  if(credentials){out.push('Your '+brand+' login','Username: '+credentials.username,'Password: '+credentials.password);if(credentials.server_url)out.push('Server: '+credentials.server_url);out.push('');}
  out.push('HOW TO INSTALL','Full guide with pictures: '+location.origin+BASE+'/install','');
  out.push(g.firestick.title.toUpperCase());g.firestick.steps.forEach((st,i)=>out.push((i+1)+'. '+st.text));out.push('Downloader codes:');for(const a of g.firestick.apps)out.push('  '+a.name+': '+a.codes.join(' or '));out.push('');
  out.push(g.apple.title.toUpperCase());g.apple.steps.forEach((st,i)=>out.push((i+1)+'. '+st.text));out.push('Site: '+g.apple.site,'URL code: '+g.apple.url_code,'');
  out.push(g.android.title.toUpperCase());g.android.steps.forEach((st,i)=>out.push((i+1)+'. '+st.text));out.push('App links:');for(const a of g.android.apps)out.push('  '+a.name+': '+a.url);
  return out.join('\n');
}
function codeChip(value){const chip=el('span','code-chip');chip.append(document.createTextNode(value));const b=el('button',null,'Copy');b.type='button';b.onclick=()=>copyText(b,value);chip.append(b);return chip;}
function appCard(section,build){const card=el('article','card app-card');const head=el('div','app-head');if(section.icon){const ic=el('img','app-icon');ic.src=BASE+'/reseller/static/'+section.icon;ic.alt='';ic.width=40;ic.height=40;head.append(ic);}head.append(el('h2',null,section.title));card.append(head);
  const grid=el('ol','step-grid');
  section.steps.forEach((st,i)=>{const li=el('li','step');if(st.picture){const img=el('img');img.src=BASE+'/reseller/static/'+st.picture;img.alt='';img.loading='lazy';li.append(img);}const cap=el('div','step-text');cap.append(el('span','step-n',String(i+1)));cap.append(document.createTextNode(st.text));li.append(cap);grid.append(li);});
  card.append(grid);build(card);return card;}
async function loadApps(){
  if(!apps)apps=await api('/apps');const g=apps.guide,root=$('apps-content');root.replaceChildren();
  root.append(appCard(g.firestick,card=>{
    const t=el('div','app-table');for(const a of g.firestick.apps){t.append(el('div','name',a.name));const codes=el('div','codes');for(const c of a.codes)codes.append(codeChip(c));t.append(codes);}card.append(t);
    if(g.firestick.note)card.append(el('p','fineprint app-note',g.firestick.note));
  }));
  root.append(appCard(g.apple,card=>{
    const t=el('div','app-table');t.append(el('div','name','Download'));const site=el('a','app-link',g.apple.site);site.href='https://'+g.apple.site;site.target='_blank';site.rel='noopener';t.append(site);
    t.append(el('div','name','URL code'));const codes=el('div','codes');codes.append(codeChip(g.apple.url_code));t.append(codes);card.append(t);
  }));
  root.append(appCard(g.android,card=>{
    const t=el('div','app-table');for(const a of g.android.apps){const nm=el('div','name');if(a.icon){const ic=el('img','app-icon small');ic.src=BASE+'/reseller/static/'+a.icon;ic.alt='';ic.width=24;ic.height=24;nm.append(ic);}nm.append(document.createTextNode(a.name));t.append(nm);const codes=el('div','codes');const link=el('a','app-link',a.url);link.href=a.url;link.target='_blank';link.rel='noopener';codes.append(link);const b=el('button','text-button','Copy link');b.type='button';b.onclick=()=>copyText(b,a.url);codes.append(b);t.append(codes);}card.append(t);
  }));
  if(g.credits)root.append(el('p','fineprint',g.credits));
}
$('copy-guide').onclick=async()=>{if(!apps)await loadApps().catch(fail);copyText($('copy-guide'),guideText());};

// ---------- create ----------
function creditsFor(months,connections){if(!packages)return undefined;const c=packages.costs.find(x=>x.months===months&&x.connections===connections);return c?c.credits:undefined;}
function priceChip(label,cost){const b=el('button','choice',label);b.type='button';if(cost!==undefined)b.append(el('span','choice-price',plural(cost,'credit')));return b;}
function renderCreate(){
  const trial=create.kind==='trial';
  document.querySelectorAll('[data-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.kind===create.kind)));
  $('plan-card').hidden=trial;$('details-no').textContent=trial?'2':'3';
  const mo=$('months-options');mo.replaceChildren();for(const m of [1,3,6,9,12]){const b=priceChip(plural(m,'month'),creditsFor(m,create.connections));b.setAttribute('aria-pressed',String(create.months===m));b.onclick=()=>{create.months=m;renderCreate();};mo.append(b);}
  const co=$('connections-options');co.replaceChildren();for(const c of [1,2,3]){const b=priceChip(plural(c,'device'),creditsFor(create.months,c));b.setAttribute('aria-pressed',String(create.connections===c));b.onclick=()=>{create.connections=c;renderCreate();};co.append(b);}
  $('cs-title').textContent=trial?'24-hour test':plural(create.months,'month')+' subscription';
  $('cs-detail').textContent=trial?'1 device · ends after 24 hours':plural(create.connections,'device')+' · same household';
  const cost=trial?0:creditsFor(create.months,create.connections);
  showCost(cost,me?me.credits.available:'–','–');
  $('confirm-create').hidden=true;$('review-create').hidden=false;nonce=null;$('op-status').hidden=true;inlineError($('review-create'),'');
  $('cs-note').textContent=trial?'Tests are free and never use credits.':'Nothing is charged until you confirm.';
  if(!packages)loadPackages().then(renderCreate).catch(()=>{});
}
function showCost(cost,available,remaining){
  if(cost===0){$('cs-cost').textContent='Free';$('cs-unit').textContent='';}
  else{$('cs-cost').textContent=cost===undefined?'–':cost;$('cs-unit').textContent=cost===1?'credit':'credits';}
  $('cs-available').textContent=available;$('cs-remaining').textContent=remaining;
}
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{create.kind=b.dataset.kind;renderCreate();});
$('create-form').onsubmit=e=>{e.preventDefault();busy($('review-create'),async()=>{
  const trial=create.kind==='trial';
  const data={kind:create.kind,months:trial?0:create.months,connections:trial?1:create.connections,adult:false,customer_ref:$('customer-ref').value.trim()};
  const p=await api('/operations/preview',{method:'POST',data});nonce=p.nonce;
  showCost(p.preview.cost,p.preview.available,p.preview.remaining);
  const short=p.preview.remaining<0;
  $('confirm-create').hidden=short;$('review-create').hidden=!short;
  $('cs-note').textContent=short?'Not enough credits. Order more under Credits first.':trial?'Confirm to create the test. No credits are used.':'Confirm to reserve '+plural(p.preview.cost,'credit')+'. They are only taken once the account is live.';
  if(window.innerWidth<=900)$('create-summary').scrollIntoView({behavior:'smooth',block:'start'});
});};
$('confirm-create').onclick=()=>busy($('confirm-create'),async()=>{if(!nonce)return;const c=await api('/operations/confirm',{method:'POST',data:{nonce}});nonce=null;$('confirm-create').hidden=true;
  await watch(c.operation.id,$('op-status'),async op=>{if(op.result_id){
    const customer_ref=$('customer-ref').value.trim(),contact=$('customer-contact').value.trim();
    if(contact||customer_ref){try{await api('/subscriptions/'+encodeURIComponent(op.result_id)+'/notes',{method:'POST',data:{customer_ref,contact}});}catch(e){}}
    $('customer-ref').value='';$('customer-contact').value='';toast('Account created');
    location.hash='#/subscriptions?open='+encodeURIComponent(op.result_id);}});});

// ---------- credits: pack → coin → pay ----------
function showStep(n){
  document.querySelectorAll('#wizard li').forEach(li=>{const s=parseInt(li.dataset.step,10);li.classList.toggle('active',s===n);li.classList.toggle('done',s<n);});
  $('step-pack').hidden=n!==1;$('step-coin').hidden=n!==2;$('invoice-card').hidden=n!==3;
}
async function loadPackages(){
  if(!packages)packages=await api('/packages');
  const packs=$('packs');if(!packs.dataset.ready){packs.dataset.ready='1';
    for(const p of packages.packages){const b=el('button','choice');b.type='button';b.append(el('b',null,money(p.price_pence)));b.append(el('span','choice-price',p.credits+' credits · '+money(Math.round(p.price_pence/p.credits))+' each'));
      b.onclick=()=>{packs.querySelectorAll('.choice').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');credits.pack=p;$('coin-summary').textContent=money(p.price_pence)+' for '+p.credits+' credits. Choose the coin and network you will pay with.';showStep(2);};packs.append(b);}
    const list=$('coin-list');for(const a of packages.assets){const b=el('button','choice');b.type='button';b.append(document.createTextNode(a.symbol));b.append(el('small',null,names[a.network]||a.network));
      b.onclick=()=>{list.querySelectorAll('.choice').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');credits.asset=a.id;};list.append(b);}
    const t=$('costs');const months=[...new Set(packages.costs.map(c=>c.months))];const head=el('tr');head.append(el('th',null,'Duration'));for(const c of [1,2,3])head.append(el('th',null,plural(c,'device')));t.append(head);
    for(const m of months){const tr=el('tr');tr.append(el('td',null,plural(m,'month')));for(const c of [1,2,3]){const f=packages.costs.find(x=>x.months===m&&x.connections===c);tr.append(el('td',null,f?plural(f.credits,'credit'):'–'));}t.append(tr);}
  }
}
$('coin-back').onclick=()=>showStep(1);
$('buy').onclick=()=>busy($('buy'),async()=>{if(!credits.pack)throw new Error('Choose a credit pack first.');if(!credits.asset)throw new Error('Choose the coin you will pay with.');const q=await api('/purchase',{method:'POST',data:{package_id:credits.pack.id,asset_id:credits.asset}});openInvoice(q.token,q.order);});

// ---------- credit payment inside the panel (existing order engine, token-authenticated) ----------
let inv={token:null,order:null,poll:null,clock:null,qr:null};
async function orderApi(path,{method='GET',data}={}){
  const headers={'X-Order-Token':inv.token};if(method==='POST')headers['Content-Type']='application/json';
  const response=await fetch(BASE+path,{method,headers,cache:'no-store',body:method==='POST'?JSON.stringify(data||{}):undefined});
  const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||'This request could not be completed. Please try again.');return body;
}
function openInvoice(token,order){inv.token=token;try{localStorage.setItem('rs-invoice',token);}catch(e){}showInvoice(order);}
async function resumeInvoice(){
  if(inv.token)return;let saved=null;try{saved=localStorage.getItem('rs-invoice');}catch(e){}
  if(!saved)return;inv.token=saved;
  try{showInvoice(await orderApi('/api/order'));}catch(e){closeInvoice();}
}
function closeInvoice(){
  clearTimeout(inv.poll);clearInterval(inv.clock);if(inv.qr)URL.revokeObjectURL(inv.qr);
  inv={token:null,order:null,poll:null,clock:null,qr:null};try{localStorage.removeItem('rs-invoice');}catch(e){}
  credits.pack=null;document.querySelectorAll('#packs .choice').forEach(x=>x.setAttribute('aria-pressed','false'));showStep(1);
}
async function showInvoice(order){
  inv.order=order;clearTimeout(inv.poll);clearInterval(inv.clock);showStep(3);
  const asset=order.asset||{};const chip=$('inv-status');
  $('inv-plan').textContent=(order.plan&&order.plan.name)||'';$('inv-network').textContent=(asset.symbol||'')+' · '+(names[asset.network]||asset.network||'');
  $('inv-amount').textContent=(order.amount||'')+' '+(asset.symbol||'');$('inv-wallet').textContent=asset.wallet||'';
  $('inv-quote').textContent=order.plan&&order.plan.gbp_price?'£'+order.plan.gbp_price+' at the exchange rate locked for this order.':'';
  $('inv-demo').hidden=!(me&&me.demo&&order.status==='pending');
  $('inv-message').textContent=order.message||'';
  const labels={pending:order.txid?'Checking payment':'Awaiting payment',paid:'Paid · adding credits',provisioning:'Paid · adding credits',fulfilled:'Credits added',review:'Needs a manual check',expired:'Quote expired'};
  chip.textContent=labels[order.status]||order.status;
  $('inv-verify-form').hidden=order.status!=='pending';
  if(order.status==='fulfilled'){$('inv-heading').textContent='Credits added';$('inv-message').textContent='Your balance is updated. Thank you.';toast('Credits added');await refreshMe();}
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
$('inv-copy-amount').onclick=()=>copyText($('inv-copy-amount'),String(inv.order.amount));
$('inv-copy-wallet').onclick=()=>copyText($('inv-copy-wallet'),inv.order.asset.wallet);

// ---------- history ----------
async function loadHistory(){
  skeleton($('history-list'),5,4);
  const data=await api('/history?page='+hist.page);const list=$('history-list');list.replaceChildren();
  if(!data.items.length){const tr=el('tr');const td=el('td','empty','No credit movements yet.');td.colSpan=4;tr.append(td);list.append(tr);}
  for(const r of data.items){const tr=el('tr');tr.style.cursor='default';tr.append(el('td',null,when(r.created_at)));const c=el('td');c.append(el('strong',null,(r.movement>0?'+':'')+r.movement));tr.append(c);tr.append(el('td',null,r.reason));const ref=el('td','hide-sm');ref.append(el('small',null,r.reference));tr.append(ref);list.append(tr);}
  $('hist-prev').disabled=!hist.page;$('hist-next').disabled=!data.more;$('hist-page').textContent='Page '+(hist.page+1);
}

// ---------- wiring ----------
document.querySelectorAll('#filters .chip').forEach(b=>b.onclick=()=>{sub.filter=b.dataset.filter;sub.page=0;sub.selected.clear();loadSubs().catch(fail);});
document.querySelectorAll('#sub-table th button').forEach(b=>b.onclick=()=>{const key=b.dataset.sort;sub.sort=sub.sort.key===key?{key,dir:sub.sort.dir==='asc'?'desc':'asc'}:{key,dir:'asc'};renderTable();});
$('select-all').onclick=()=>{const on=$('select-all').checked;for(const r of sub.items){if(on)sub.selected.add(r.id);else sub.selected.delete(r.id);}renderTable();};
$('bulk-clear').onclick=()=>{sub.selected.clear();renderTable();};
function renderExpiredBar(){
  const n=me?me.counts.expired||0:0;const show=sub.filter==='expired'&&n>0;
  $('expired-bar').hidden=!show;if(show)$('expired-note').textContent=plural(n,'expired record')+'. Deleting only tidies your list; reports and credit history are kept.';
}
$('delete-expired').onclick=()=>busy($('delete-expired'),async()=>{
  const n=me.counts.expired||0;if(!confirm('Delete all '+n+' expired subscriptions and tests from your list?'))return;
  const r=await api('/subscriptions/delete-expired',{method:'POST',data:{}});sub.selected.clear();await refreshMe();await loadSubs();toast(plural(r.deleted,'record')+' deleted');
});
$('bulk-delete').onclick=()=>busy($('bulk-delete'),async()=>{
  const ids=[...sub.selected].filter(id=>{const r=sub.items.find(x=>x.id===id);return r&&deletable(r);});
  if(!ids.length)throw new Error('None of the selected customers has expired. Only expired subscriptions and tests can be deleted.');
  const skipped=sub.selected.size-ids.length;
  if(!confirm('Delete '+plural(ids.length,'expired record')+' from your list?'+(skipped?' '+plural(skipped,'active customer')+' will be kept.':'')))return;
  let done=0;for(const id of ids){try{await deleteOne(id);done++;}catch(e){if(e instanceof SignedOut)throw e;}}
  sub.selected.clear();await refreshMe();await loadSubs();toast(plural(done,'record')+' deleted');
});
$('bulk-extend').onclick=()=>busy($('bulk-extend'),bulkExtend);
$('search-form').onsubmit=e=>{e.preventDefault();sub.search=$('search').value.trim();sub.page=0;loadSubs().catch(fail);};
$('global-search').onsubmit=e=>{e.preventDefault();sub.search=$('global-search-input').value.trim();sub.page=0;sub.filter='all';if(location.hash.startsWith('#/subscriptions'))loadSubs().catch(fail);else location.hash='#/subscriptions';};
$('sub-prev').onclick=()=>{sub.page--;loadSubs().catch(fail);};$('sub-next').onclick=()=>{sub.page++;loadSubs().catch(fail);};
$('hist-prev').onclick=()=>{hist.page--;loadHistory().catch(fail);};$('hist-next').onclick=()=>{hist.page++;loadHistory().catch(fail);};
// ---------- Log in with Telegram (deep link + poll) ----------
let tgPoll=null,tgTimer=null,tgDeadline=0,tgBlob=null;
function tgReset(){clearTimeout(tgTimer);tgTimer=null;tgPoll=null;if(tgBlob){URL.revokeObjectURL(tgBlob);tgBlob=null;}$('tg-wait').hidden=true;$('tg-start').hidden=false;}
async function tgTick(){
  if(!tgPoll)return;
  if(Date.now()>tgDeadline){$('tg-status').textContent='That request expired. Tap Log in with Telegram to try again.';$('tg-status').classList.remove('waiting');return;}
  try{
    const r=await api('/session/poll?poll='+encodeURIComponent(tgPoll));
    if(r.status==='approved'){const data=r;tgReset();applyMe(data);location.hash='#/dashboard';route();toast('Logged in with Telegram');return;}
  }catch(e){if(!(e instanceof SignedOut)){$('tg-status').textContent=e.message;$('tg-status').classList.remove('waiting');tgPoll=null;return;}}
  tgTimer=setTimeout(tgTick,2000);
}
$('tg-login').onclick=()=>busy($('tg-login'),async()=>{
  const r=await api('/session/start',{method:'POST',data:{}});
  tgPoll=r.poll;tgDeadline=Date.now()+(r.expires_in||600)*1000;
  $('tg-open').href=r.url;if(r.bot)$('tg-open').textContent='Open @'+r.bot;
  const bytes=Uint8Array.from(atob(r.qr),c=>c.charCodeAt(0));tgBlob=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));$('tg-qr').src=tgBlob;
  $('tg-status').textContent='Waiting for you to confirm in Telegram…';$('tg-status').classList.add('waiting');
  $('tg-start').hidden=true;$('tg-wait').hidden=false;
  tgTimer=setTimeout(tgTick,2000);
});
$('tg-cancel').onclick=tgReset;
$('password-form').onsubmit=e=>{e.preventDefault();busy(e.submitter||$('password-form').querySelector('.primary'),async()=>{applyMe(await api('/session/password',{method:'POST',data:{email:$('login-email').value,password:$('login-password').value}}));$('login-password').value='';location.hash='#/dashboard';route();});};
$('account-form').onsubmit=e=>{e.preventDefault();busy(e.submitter||$('account-form').querySelector('.primary'),async()=>{
  const r=await api('/account',{method:'POST',data:{email:$('acc-new-email').value,password:$('acc-new-password').value,current_password:$('acc-current').value}});
  me.login=r.login;$('acc-new-password').value='';$('acc-current').value='';toast('Saved. You can now log in with this email and password.');applyMe(me);});};
$('signout').onclick=()=>busy($('signout'),async()=>{await api('/signout',{method:'POST'});signedOut();});
$('signout-all').onclick=()=>busy($('signout-all'),async()=>{await api('/signout-everywhere',{method:'POST'});signedOut();});
// ---------- support tickets ----------
function ticketPill(t){return t.status==='answered'?['Answered','ok']:t.status==='closed'?['Closed','']:['Open','warn'];}
function showTicketForm(on){$('ticket-form').hidden=!on;$('ticket-help').hidden=on;if(on){$('ticket-body').focus();}}
async function loadTickets(){
  document.querySelectorAll('#ticket-filters .chip').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tfilter===tk.filter)));
  const list=$('ticket-list');list.replaceChildren();for(let i=0;i<3;i++)list.append(el('div','skeleton-row'));
  const data=await api('/tickets?page='+tk.page);list.replaceChildren();
  if(!tk.topics){tk.topics=data.topics;const sel=$('ticket-topic');sel.replaceChildren();for(const [k,v] of Object.entries(data.topics)){const o=el('option',null,v);o.value=k;sel.append(o);}}
  if(me&&me.support_url)$('support-direct').textContent='Prefer Telegram? '+(me.support||'Message support directly.')+' '+me.support_url;
  const items=data.items.filter(t=>tk.filter==='all'||(tk.filter==='closed'?t.status==='closed':t.status!=='closed'));
  if(!items.length){list.append(el('div','ticket-empty',tk.filter==='closed'?'No closed tickets.':'No open tickets. Need help? Open a new ticket and we will answer in the panel and in Telegram.'));}
  for(const t of items){
    const row=el('button','ticket-row');row.type='button';
    row.append(el('span','dot '+t.status));
    const mid=el('div');const title=el('div','title');title.append(document.createTextNode(t.topic_label));title.append(el('small',null,t.id));const pill=ticketPill(t);title.append(el('span','pill '+pill[1],pill[0]));mid.append(title);
    mid.append(el('div','preview',(t.last_sender==='support'?'Support: ':'You: ')+(t.preview||'')));row.append(mid);
    const meta=el('div','meta');meta.append(el('div',null,when(t.updated_at)));meta.append(el('div',null,plural(t.messages,'message')));row.append(meta);
    row.onclick=()=>{location.hash='#/support?open='+encodeURIComponent(t.id);};list.append(row);
  }
  $('tk-prev').disabled=!tk.page;$('tk-next').disabled=!data.more;$('tk-page').textContent='Page '+(tk.page+1);
}
function renderThread(box,data){
  box.replaceChildren();const t=data.ticket;const pill=ticketPill(t);
  const head=el('div','ticket-head');head.append(el('span','pill '+pill[1],pill[0]));head.append(el('span',null,t.topic_label+' · opened '+when(t.created_at)));box.append(head);
  const thread=el('div','thread');
  for(const m of data.messages){const b=el('div','bubble '+(m.sender==='customer'?'me':'support'));b.append(el('small',null,(m.sender==='customer'?'You':'Support')+' · '+when(m.created_at)));b.append(document.createTextNode(m.body));thread.append(b);}
  box.append(thread);
  const form=el('form','reply-form');const ta=el('textarea');ta.maxLength=2000;ta.placeholder=t.status==='closed'?'Write a reply to reopen this ticket':'Write a reply';ta.rows=3;
  const actions=el('div','actions');const send=el('button','primary',t.status==='closed'?'Reopen with reply':'Send reply');send.type='submit';actions.append(send);
  if(t.status!=='closed'){const close=el('button','secondary','Close ticket');close.type='button';close.onclick=()=>busy(close,async()=>{const d=await api('/tickets/'+encodeURIComponent(t.id)+'/close',{method:'POST',data:{}});toast('Ticket closed');renderThread(box,d);loadTickets().catch(()=>{});});actions.append(close);}
  form.append(ta,actions);form.append(el('p','fineprint','Replies also arrive in Telegram.'));
  form.onsubmit=e=>{e.preventDefault();busy(send,async()=>{const d=await api('/tickets/'+encodeURIComponent(t.id)+'/reply',{method:'POST',data:{body:ta.value}});toast('Sent');renderThread(box,d);loadTickets().catch(()=>{});});};
  box.append(form);
}
async function openTicket(id){
  const box=$('sub-detail');box.replaceChildren();for(let i=0;i<3;i++)box.append(el('div','skeleton-row'));$('drawer-title').textContent='Ticket '+id;openDrawer();
  const data=await api('/tickets/'+encodeURIComponent(id));renderThread(box,data);
}
$('new-ticket').onclick=()=>showTicketForm(true);$('ticket-cancel').onclick=()=>showTicketForm(false);
document.querySelectorAll('#ticket-filters .chip').forEach(b=>b.onclick=()=>{tk.filter=b.dataset.tfilter;tk.page=0;loadTickets().catch(fail);});
$('tk-prev').onclick=()=>{tk.page=Math.max(0,tk.page-1);loadTickets().catch(fail);};$('tk-next').onclick=()=>{tk.page++;loadTickets().catch(fail);};
$('ticket-form').onsubmit=e=>{e.preventDefault();busy(e.submitter||$('ticket-form').querySelector('.primary'),async()=>{
  const d=await api('/tickets',{method:'POST',data:{topic:$('ticket-topic').value,body:$('ticket-body').value}});
  $('ticket-body').value='';showTicketForm(false);toast('Ticket '+d.ticket.id+' opened');location.hash='#/support?open='+encodeURIComponent(d.ticket.id);
});};
$('more-tab').onclick=()=>{$('more-sheet').hidden=false;};$('sheet-close').onclick=()=>{$('more-sheet').hidden=true;};$('more-sheet').onclick=e=>{if(e.target===$('more-sheet'))$('more-sheet').hidden=true;};
window.addEventListener('hashchange',route);

(async()=>{
  const m=location.hash.match(/^#code=([A-Za-z0-9_-]{20,100})$/);
  try{
    if(m){history.replaceState(null,'',location.pathname);applyMe(await api('/session/code',{method:'POST',data:{code:m[1]}}));location.hash='#/dashboard';}
    else applyMe(await api('/me'));
    route();
  }catch(e){if(e instanceof SignedOut)signedOut();else{signedOut();error(e.message);}}
})();
