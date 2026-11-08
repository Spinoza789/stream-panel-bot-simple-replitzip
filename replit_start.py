"""Run this add-on without consuming an existing Replit app's generic Secrets."""
import os
import sys
from pathlib import Path


def prepare_environment(source):
    env=dict(source)
    defaults={
        'APP_MODE':('STREAMBOT_MODE','demo'),
        'HOST':('STREAMBOT_HOST','0.0.0.0'),
        'PORT':('STREAMBOT_PORT','5000'),
        'TELEGRAM_BOT_TOKEN':('STREAMBOT_TELEGRAM_BOT_TOKEN',''),
        'TELEGRAM_ENABLED':('STREAMBOT_TELEGRAM_ENABLED','false'),
        'SUPPORT_ADMIN_ID':('STREAMBOT_SUPPORT_ADMIN_ID',''),
        'PANEL_USERNAME':('STREAMBOT_PANEL_USERNAME',''),
        'PANEL_PASSWORD':('STREAMBOT_PANEL_PASSWORD',''),
        'PANEL_WRITE_ENABLED':('STREAMBOT_PANEL_WRITE_ENABLED','false'),
        'LIVE_PAYMENTS_ENABLED':('STREAMBOT_LIVE_PAYMENTS_ENABLED','false'),
        'CREDENTIAL_KEY':('STREAMBOT_CREDENTIAL_KEY',''),
        'ETHEREUM_RPC_URL':('STREAMBOT_ETHEREUM_RPC_URL',''),
        'SOLANA_RPC_URL':('STREAMBOT_SOLANA_RPC_URL',''),
        'BITCOIN_ESPLORA_URL':('STREAMBOT_BITCOIN_ESPLORA_URL','https://blockstream.info/api'),
        'DATABASE_PATH':('STREAMBOT_SQLITE_PATH','data/demo.sqlite3'),
        'TRUST_PROXY':('STREAMBOT_TRUST_PROXY','false'),
    }
    for key,(namespaced,default) in defaults.items(): env[key]=source.get(namespaced,default)
    try: port=int(env['PORT'])
    except (TypeError,ValueError): raise ValueError('STREAMBOT_PORT must be a port number.') from None
    if not 1<=port<=65535: raise ValueError('STREAMBOT_PORT must be between 1 and 65535.')
    if env['APP_MODE'] not in ('demo','live'): raise ValueError('STREAMBOT_MODE must be demo or live.')
    if env['APP_MODE']=='demo':
        # Saving production Secrets must not move demo state to another database
        # or make existing demo credentials unreadable with a different key.
        env['STREAMBOT_DATABASE_URL']=''
        env['CREDENTIAL_KEY']=''
    else:
        database_source=source.get('STREAMBOT_DATABASE_SOURCE','external')
        if database_source not in ('managed','external'):
            raise ValueError('STREAMBOT_DATABASE_SOURCE must be managed or external.')
        if database_source=='managed':
            # Replit supplies a different DATABASE_URL in production. Never pin
            # a published bot to a copied development connection string.
            if not source.get('DATABASE_URL'):
                raise ValueError('The managed PostgreSQL connection is unavailable.')
            env['STREAMBOT_DATABASE_URL']=source['DATABASE_URL']
    origin=source.get('STREAMBOT_PUBLIC_URL','').rstrip('/')
    if not origin:
        if env['APP_MODE']=='live': raise ValueError('Set STREAMBOT_PUBLIC_URL to the exact HTTPS checkout origin before live startup.')
        preview=source.get('REPLIT_DEV_DOMAIN','')
        origin='https://'+preview if preview else 'http://localhost:'+str(port)
    env['PUBLIC_URL']=origin
    env['STREAMBOT_REPLIT']='true'
    return env


def main():
    project=Path(__file__).resolve().parent
    # All relative paths, configuration and optional .env belong to this subfolder.
    os.chdir(project)
    try: env=prepare_environment(os.environ)
    except ValueError as exc: raise SystemExit('Replit configuration error: '+str(exc)) from None
    os.environ.clear();os.environ.update(env)
    from streambot.__main__ import main as run
    run()


if __name__=='__main__': main()
