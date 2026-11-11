import argparse
import fcntl
import json
import logging
import os
import signal
import secrets
import time
import threading
from contextlib import ExitStack,contextmanager,nullcontext
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from waitress import serve
from .config import load_config
from .store import Store, digest
from .service import CheckoutService
from .panel import PanelClient
from .chains import BlockchainVerifier, PaymentPending
from .web import create_app
from .bot import TelegramBot
from .runtime import ExclusiveRuntime

log=logging.getLogger('streambot')


class DemoPanel:
    """Simulated panel for demo mode. Accounts it creates are registered as demo lines so the
    demo reseller provider can extend them (renewals and trial upgrades) exactly like live lines."""
    def __init__(self,store=None,trial_package_id=None):
        self.store=store;self.trial_package_id=str(trial_package_id) if trial_package_id is not None else None

    def find_account(self,username):
        return None

    def prepare_generation(self,package_id):
        return dict(generation_mode='panel',package_id=str(package_id),before_ids=[],prepared_at=int(time.time()),post_attempted=True)

    def create_account(self,package_id,username='',password='',description='',*,generation=None):
        if username or password or description: raise ValueError('Demo generation fields must be empty')
        account=dict(username='demo_'+secrets.token_urlsafe(6),password=secrets.token_urlsafe(12),
                     package_id=package_id,server_url='DEMO — no live streaming server')
        if self.store is not None:
            now=int(time.time())
            pid=str(secrets.randbelow(10**15)+1)
            expires=now+(86400 if str(package_id)==self.trial_package_id else 30*86400)
            self.store.metadata('rs_demo:'+pid,self.store.seal(dict(provider_id=pid,expires_at=expires,status='active',starts_at=now,connections=1,
                                                                   credentials=dict(username=account['username'],password=account['password'],server_url=account['server_url']))))
            account.update(panel_id=pid,expires_at=expires)
        return account


class DemoVerifier:
    def verify(self,*args,**kwargs): raise PaymentPending('Demo does not access blockchains.')


def build(config):
    key=config['encryption_key']
    if not key:
        if config.get('database_url'): raise ValueError('Set a stable CREDENTIAL_KEY before using PostgreSQL, including in demo mode.')
        key_path=Path('data/demo.key');key_path.parent.mkdir(mode=0o700,exist_ok=True)
        if not key_path.exists():
            with key_path.open('xb') as handle: handle.write(Fernet.generate_key())
            key_path.chmod(0o600)
        key=key_path.read_bytes()
    if config.get('database_url'):
        from .postgres_store import PostgresStore
        store=PostgresStore(config['database_url'],key,schema=config['database_schema'])
    else:store=Store(config['db_path'],key)
    if store.metadata('mode') not in (None,config['mode']): raise ValueError('Database mode mismatch. Use separate demo/live databases.')
    key_id=digest(key)
    if store.metadata('key_id') not in (None,key_id): raise ValueError('Credential encryption key does not match this database. Restore the original key.')
    store.metadata('mode',config['mode']);store.metadata('key_id',key_id)
    panel=DemoPanel(store,config.get('trial_package_id')) if config['mode']=='demo' else PanelClient(config['panel_base_url'],config['panel_username'],config['panel_password'],allow_create=config['panel_writes'])
    verifier=DemoVerifier() if config['mode']=='demo' else BlockchainVerifier()
    return CheckoutService(config,store,verifier,panel)


@contextmanager
def file_instance_lock(path):
    lock_path=Path(path+'.lock');lock_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with lock_path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another instance owns this database. Run only one service process.') from None
        yield


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    load_dotenv(override=False)
    parser=argparse.ArgumentParser(description='Standalone subscription checkout and Telegram trial assistant')
    parser.add_argument('--config',default='config.json')
    parser.add_argument('command',choices=['serve','check','inspect-panel','orders','reconcile','retry'],nargs='?',default='serve')
    parser.add_argument('order_id',nargs='?')
    parser.add_argument('--confirm-absent',action='store_true')
    args=parser.parse_args()
    try: config=load_config(args.config)
    except (ValueError,FileNotFoundError) as exc: parser.exit(1,'Configuration error: '+str(exc)+'\n')
    if args.command=='check':
        print(json.dumps({'mode':config['mode'],'plans':len(config['plans']),'assets':list(config['assets']),
                          'telegram_configured':bool(config['bot_token']),'panel_writes':config['panel_writes'],
                          'database':('PostgreSQL / '+config['database_schema']) if config.get('database_url') else config['db_path'],
                          'base_path':config.get('base_path','')},indent=2));return
    if args.command=='inspect-panel':
        if not config['panel_username'] or not config['panel_password']: parser.exit(1,'Set PANEL_USERNAME and PANEL_PASSWORD in .env first.\n')
        client=PanelClient(config['panel_base_url'],config['panel_username'],config['panel_password'],allow_create=False)
        try: packages=client.inspect_packages()
        except Exception as exc: parser.exit(1,'Read-only panel inspection failed ('+type(exc).__name__+'). Check credentials and the panel page format.\n')
        print(json.dumps(packages,indent=2));return
    try:service=build(config)
    except (ValueError,RuntimeError) as exc:parser.exit(1,'State setup error: '+str(exc)+'\n')
    if args.command=='orders':
        with service.store.connection() as db:
            for row in db.execute('SELECT id,kind,status,created_at FROM orders ORDER BY created_at DESC LIMIT 100'): print(dict(row))
        return
    if args.command in ('reconcile','retry'):
        order=service.store.get(args.order_id)
        if not order or order['status']!='review' or not order['credentials']: parser.exit(1,'Choose an order in review with stored credentials.\n')
        if order['credentials'].get('generation_mode')=='panel':
            parser.exit(1,'Panel-generated account identity is uncertain. Identify its panel account manually; do not submit another creation.\n')
        try: found=service.panel.find_account(order['credentials']['username'])
        except Exception as exc: parser.exit(1,'Lookup failed ('+type(exc).__name__+'). No order state changed.\n')
        if found:
            if found.get('password')!=order['credentials']['password']: parser.exit(1,'Existing credentials do not match. No changes made.\n')
            credentials={**order['credentials'],**found}
            service.store.update(order['id'],status='fulfilled',credentials=credentials,message='Your account is ready.')
            print('Existing panel account confirmed. Order fulfilled without another creation request.')
        elif args.command=='retry' and args.confirm_absent:
            service.store.update(order['id'],status='paid',message='Account creation queued after operator reconciliation.')
            print('No matching panel account found. Queued one new creation attempt.')
        else: print('No matching account found. Verify absence in the panel; retry with --confirm-absent only after checking.')
        return
    with ExitStack() as resources:
        if not config.get('database_url'):
            try:resources.enter_context(file_instance_lock(config['db_path']))
            except RuntimeError as exc:parser.exit(1,str(exc)+'\n')
        run_server(service,config,resources)


def run_server(service,config,resources):
    stop=threading.Event()
    resources.callback(stop.set)
    if config['mode']=='live':
        try:
            available={p['id'] for p in service.panel.inspect_packages()}
            required={str(p['package_id']) for p in config['plans']}|{str(config['trial_package_id'])}
            if not required<=available:raise RuntimeError('Configured panel packages are unavailable. Run inspect-panel and update config.json.')
        except Exception as exc:raise SystemExit('Panel startup inspection failed ('+type(exc).__name__+'). No checkout started.') from None
    def worker(operation):
        while not stop.is_set():
            try: operation()
            except Exception as exc: log.error('Order worker paused (%s); retrying.',type(exc).__name__)
            stop.wait(2)
    def activate():
        # Recovery and every business worker stay behind the same exclusive
        # lease. A standby version must never reconcile the old version's work.
        service.recover_interrupted()
        threading.Thread(target=worker,args=(service.check_payments,),daemon=True,name='payment-worker').start()
        threading.Thread(target=worker,args=(service.provision_pending,),daemon=True,name='account-worker').start()
        if config['telegram_enabled'] and config['bot_token']:
            threading.Thread(target=TelegramBot(service).run,args=(stop,),daemon=True,name='telegram').start()
        else: log.info('Telegram polling is disabled in this instance.')
    runtime=ExclusiveRuntime(
        service.store.acquire_instance_lock if config.get('database_url') else nullcontext,
        service.store.instance_lock_healthy if config.get('database_url') else lambda:True,
        activate,lambda:os._exit(1),stop=stop)
    resources.callback(runtime.close)
    def shutdown(*_): stop.set();raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    runtime.start()
    host=os.getenv('HOST','127.0.0.1');port=int(os.getenv('PORT','8090'))
    log.info('Checkout listening at http://%s:%s — %s mode',host,port,config['mode'])
    try: serve(create_app(service,ready=runtime.ready),host=host,port=port,threads=8)
    finally: runtime.close()


if __name__=='__main__': main()
