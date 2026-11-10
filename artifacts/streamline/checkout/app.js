'use strict';
const $=id=>document.getElementById(id);
const BASE=document.querySelector('meta[name="streambot-base-path"]').content;
let catalog,months=1,connections=1,currentOrder=null,token=null,pollTimer,countTimer,qrUrl;
const names={ethereum:'Ethereum',solana:'Solana',bitcoin:'Bitcoin'};
const money=value=>new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',maximumFractionDigits:2,minimumFractionDigits:0}).format(Number(value));
function error(message){$('error').textContent=message;$('error').hidden=!message;}
async function api(path,{method='GET',data}={}){
  const headers={};if(token)headers['X-Order-Token']=token;
  if(method==='POST')headers['Content-Type']='application/json';
  const response=await fetch(BASE+path,{method,headers,body:method==='POST'?JSON.stringify(data||{}):undefined,cache:'no-store'});
  const body=await response.json();if(!response.ok)throw new Error(body.error||'This request could not be completed. Please try again.');return body;
}
function selectedPlan(){return catalog.plans.find(p=>p.months===months&&p.connections===connections);}
function renderChoices(){
  $('duration-options').replaceChildren();
  for(const duration of [...new Set(catalog.plans.map(p=>p.months))]){
    const plan=catalog.plans.find(p=>p.months===duration&&p.connections===connections);
    const button=document.createElement('button');button.className='choice';button.type='button';button.setAttribute('aria-pressed',String(months===duration));
    const label=document.createElement('span');label.textContent=duration+' month'+(duration>1?'s':'');
    const price=document.createElement('span');price.className='choice-price';price.textContent=money(plan.gbp_price);button.append(label,price);
    button.onclick=()=>{months=duration;renderChoices();};$('duration-options').append(button);
  }
  $('connection-options').replaceChildren();
  for(const count of [1,2,3]){
    const button=document.createElement('button');button.type='button';button.className='choice';button.textContent=String(count);button.setAttribute('aria-label',count+' connection'+(count>1?'s':''));button.setAttribute('aria-pressed',String(connections===count));
    button.onclick=()=>{connections=count;renderChoices();};$('connection-options').append(button);
  }
  const plan=selectedPlan(),asset=catalog.assets.find(a=>a.id===$('asset').value);
  $('summary-heading').textContent=plan.name;$('summary-detail').textContent=plan.detail;$('price').textContent=money(plan.gbp_price);
  if(asset)$('summary-asset').textContent=asset.symbol+' · '+names[asset.network];
}
async function busy(button,work){const text=button.textContent;button.disabled=true;error('');try{await work();}catch(e){error(e.message);}finally{button.disabled=false;button.textContent=text;}}
async function copy(text,button){try{await navigator.clipboard.writeText(text);const old=button.textContent;button.textContent='Copied ✓';setTimeout(()=>button.textContent=old,1800);}catch{error('Clipboard access is unavailable. Select and copy the text manually.');}}
function recoveryLink(){return location.origin+BASE+'/#order='+encodeURIComponent(token);}
function updateClock(){
  if(!currentOrder)return;const left=Math.max(0,currentOrder.expires_at-Math.floor(Date.now()/1000));
  $('countdown').textContent=left?String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0'):'Expired';
  if(!left&&currentOrder.status==='pending')$('payment-warning').textContent='This quote has expired. Do not send a new payment. If you paid before expiry, submit your TXID; otherwise create a new quote.';
}
async function showOrder(order){
  const previousStatus=currentOrder?.status;currentOrder=order;
  $('workspace').hidden=true;$('invoice').hidden=false;$('loading').hidden=true;
  $('order-label').textContent='ORDER / '+order.id.toUpperCase();$('invoice-plan').textContent=order.plan.name+' · '+(order.plan.detail||'');
  $('invoice-network').textContent=order.asset.symbol+' ON '+names[order.asset.network];
  $('invoice-amount').textContent=order.amount+' '+order.asset.symbol;$('wallet').textContent=order.asset.wallet;
  $('invoice-quote-details').textContent=order.matching_adjustment?'Includes an order-matching adjustment of '+order.matching_adjustment+' '+order.asset.symbol+' (at most £0.01 at the quoted rate).':'';
  $('order-message').textContent=order.message||(catalog.demo?'Demo order: use the simulation button below. No real funds are accepted.':'Transfer the exact amount, then paste your TXID below.');
  const statusLabels={pending:'AWAITING PAYMENT',paid:'PAYMENT CONFIRMED',provisioning:'PREPARING ACCOUNT',fulfilled:'ACCOUNT READY',review:'MANUAL CHECK'};
  $('status-chip').textContent=statusLabels[order.status]||order.status;
  $('verify-form').hidden=order.status!=='pending';$('demo-pay').hidden=!catalog.demo||order.status!=='pending';
  $('account').hidden=order.status!=='fulfilled';document.querySelector('.invoice-grid').hidden=order.status==='fulfilled';
  if(order.credentials){
    $('invoice-heading').textContent='Your account is ready.';$('account-username').value=order.credentials.username;$('account-password').value=order.credentials.password;
    $('account-server').textContent=order.credentials.server_url?'Server: '+order.credentials.server_url:'Use the server address supplied by your provider.';
    $('account-expiry').textContent=order.credentials.expires_at?'Expires: '+order.credentials.expires_at:'';
  }else{$('invoice-heading').textContent=order.status==='review'?'We’re checking your account.':'One last step.';}
  updateClock();clearInterval(countTimer);countTimer=setInterval(updateClock,1000);
  if(previousStatus===undefined){
    try{const response=await fetch(BASE+'/api/order/qr',{headers:{'X-Order-Token':token}});if(response.ok){if(qrUrl)URL.revokeObjectURL(qrUrl);qrUrl=URL.createObjectURL(await response.blob());$('qr').src=qrUrl;}}catch{}
  }
  clearTimeout(pollTimer);if(!['fulfilled','review'].includes(order.status))pollTimer=setTimeout(refreshOrder,6000);
}
async function refreshOrder(){try{await showOrder(await api('/api/order'));}catch(e){error(e.message);pollTimer=setTimeout(refreshOrder,15000);}}
$('asset').onchange=renderChoices;
$('create-order').onclick=()=>busy($('create-order'),async()=>{
  const result=await api('/api/orders',{method:'POST',data:{plan_id:selectedPlan().id,asset_id:$('asset').value}});
  token=result.token;currentOrder=null;history.replaceState(null,'','#order='+encodeURIComponent(token));await showOrder(result.order);$('invoice').scrollIntoView({block:'start',behavior:'smooth'});
});
$('verify-form').onsubmit=event=>{event.preventDefault();busy($('verify-button'),async()=>showOrder(await api('/api/order/verify',{method:'POST',data:{txid:$('txid').value.trim()}})));};
$('demo-pay').onclick=()=>busy($('demo-pay'),async()=>showOrder(await api('/api/order/demo-pay',{method:'POST'})));
$('copy-wallet').onclick=()=>copy(currentOrder.asset.wallet,$('copy-wallet'));
$('copy-amount').onclick=()=>copy(currentOrder.amount,$('copy-amount'));
$('save-link').onclick=()=>copy(recoveryLink(),$('save-link'));
$('save-account-link').onclick=()=>copy(recoveryLink(),$('save-account-link'));
$('copy-credentials').onclick=()=>copy('Username: '+currentOrder.credentials.username+'\nPassword: '+currentOrder.credentials.password+(currentOrder.credentials.server_url?'\nServer: '+currentOrder.credentials.server_url:''),$('copy-credentials'));
$('reveal-password').onclick=()=>{const show=$('account-password').type==='password';$('account-password').type=show?'text':'password';$('reveal-password').textContent=show?'Hide':'Show';};
$('link-account').onclick=()=>busy($('link-account'),async()=>{const data=await api('/api/order/link',{method:'POST'});$('link-code').textContent='/link '+data.code+' — valid for 10 minutes';});
$('new-order').onclick=()=>{clearTimeout(pollTimer);clearInterval(countTimer);currentOrder=null;token=null;history.replaceState(null,'',location.pathname);$('invoice').hidden=true;$('workspace').hidden=false;error('');};
for(const id of ['support-button','privacy-button'])$(id).onclick=()=>$('support-dialog').showModal();$('close-dialog').onclick=()=>$('support-dialog').close();
async function init(){
  try{
    catalog=await api('/api/catalog');document.title=catalog.brand+' · Member access';document.querySelectorAll('[data-brand]').forEach(node=>node.textContent=catalog.brand);
    $('demo-banner').hidden=!catalog.demo;$('support-text').textContent=catalog.support;
    $('support-telegram').href=catalog.support_url;
    $('support-telegram').textContent='Message @'+catalog.support_url.split('/').pop()+' on Telegram ↗';
    for(const asset of catalog.assets){const option=document.createElement('option');option.value=asset.id;option.textContent=asset.symbol+' · '+names[asset.network]+(asset.network==='ethereum'&&asset.symbol!=='ETH'?' (ERC-20)':'');$('asset').append(option);}
    renderChoices();$('loading').hidden=true;
    const params=new URLSearchParams(location.hash.slice(1));token=params.get('order');
    if(token){await showOrder(await api('/api/order'));}else{document.querySelector('.intro').hidden=true;$('loading').hidden=false;$('loading').textContent='Memberships are ordered through our Telegram bot. This page only shows an existing order opened from its private link.';}
  }catch(e){$('loading').hidden=true;error(e.message);}
}
init();
