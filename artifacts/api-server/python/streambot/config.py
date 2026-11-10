"""Configuration is explicit; demo and live state never share a default database."""
import copy
import json
import os
import re
from decimal import Decimal
from urllib.parse import urlparse
from cryptography.fernet import Fernet


def units(value, decimals):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)?', value):
        raise ValueError('Amounts must be positive decimal strings, never floats.')
    amount = Decimal(value) * 10 ** decimals
    if amount != amount.to_integral_value() or amount <= 0:
        raise ValueError('Amount is zero, negative or has too many decimal places.')
    return int(amount)


def display_units(value, decimals):
    value = int(value)
    whole, fraction = divmod(value, 10 ** decimals)
    return f'{whole}.{fraction:0{decimals}d}'.rstrip('0').rstrip('.') if decimals else str(whole)


def load_config(path='config.json', env=None):
    env = os.environ if env is None else env
    with open(path) as handle: config = json.load(handle)
    config = copy.deepcopy(config)
    mode = env.get('APP_MODE', 'demo')
    if mode not in ('demo', 'live'): raise ValueError('APP_MODE must be demo or live.')
    config.update(mode=mode, public_url=env.get('PUBLIC_URL', 'http://localhost:8090').rstrip('/'),
                  panel_username=env.get('PANEL_USERNAME', ''), panel_password=env.get('PANEL_PASSWORD', ''),
                  panel_writes=env.get('PANEL_WRITE_ENABLED') == 'true',
                  encryption_key=env.get('CREDENTIAL_KEY', ''), bot_token=env.get('TELEGRAM_BOT_TOKEN', ''),
                  db_path=env.get('DATABASE_PATH', f'data/{mode}.sqlite3'),
                  trust_proxy=env.get('TRUST_PROXY', 'false') == 'true',
                  telegram_enabled=env.get('TELEGRAM_ENABLED', 'true') == 'true')
    config['database_url']=env.get('STREAMBOT_DATABASE_URL','')
    admin=env.get('SUPPORT_ADMIN_ID','').strip()
    if admin and (not re.fullmatch(r'[1-9][0-9]{0,18}',admin)):
        raise ValueError('SUPPORT_ADMIN_ID must be your positive numeric Telegram user ID, obtained with /myid.')
    config['support_admin_id']=int(admin) if admin else None
    config.setdefault('support_username','InterRamit')
    if not re.fullmatch(r'[a-zA-Z0-9_]{1,64}',config['support_username']):raise ValueError('Invalid support Telegram username.')
    config['support_url']='https://t.me/'+config['support_username']
    config['database_schema']='stream_panel_bot_'+mode
    config['base_path']=env.get('STREAMBOT_BASE_PATH','').rstrip('/')
    if config['base_path'] and not re.fullmatch(r'/[a-zA-Z0-9_-]+',config['base_path']):
        raise ValueError('STREAMBOT_BASE_PATH must be empty or a single path such as /stream.')
    if config['database_url'] and not config['database_url'].startswith(('postgresql://','postgres://')):
        raise ValueError('STREAMBOT_DATABASE_URL must be a PostgreSQL connection URL.')
    if mode=='live' and (env.get('STREAMBOT_REPLIT')=='true' or env.get('REPLIT_DEPLOYMENT')) and not config['database_url']:
        raise ValueError('Live Replit operation requires PostgreSQL via STREAMBOT_DATABASE_URL; local SQLite is for demo/persistent-volume hosting.')
    for asset_id, asset in config['assets'].items():
        asset['id'] = asset_id
        asset['rpc_url'] = env.get(asset['rpc_env'], '')
        if mode == 'demo':
            # Deliberately non-payable destinations. Real addresses are never shown in a demo invoice.
            asset['wallet'] = 'DEMO-' + asset['network'].upper() + '-DO-NOT-SEND-FUNDS'
    ids = set()
    for plan in config['plans']:
        if plan['id'] in ids: raise ValueError('Duplicate plan id.')
        ids.add(plan['id'])
        if 'gbp_price' in plan: units(plan['gbp_price'], 2)
        else:
            for key, value in plan.get('prices', {}).items(): units(value, config['assets'][key]['decimals'])
    if not 1 <= int(config.get('quote_minutes', 60)) <= 120: raise ValueError('Invalid quote lifetime.')
    tolerance = config.setdefault('payment_tolerance_usd', {})
    for key in ('under', 'over'):
        value = Decimal(str(tolerance.get(key, '0')))
        if not value.is_finite() or value < 0 or value > 50: raise ValueError('payment_tolerance_usd.' + key + ' must be between 0 and 50 USD.')
        tolerance[key] = str(value)
    if mode == 'live':
        from .chains import BlockchainVerifier, PaymentRejected
        url = urlparse(config['public_url'])
        if url.scheme != 'https' or not url.netloc or url.path:
            raise ValueError('Live PUBLIC_URL must be an HTTPS origin without a path.')
        missing = [k for k in ('panel_username', 'panel_password', 'encryption_key') if not config[k]]
        if missing: raise ValueError('Missing live configuration: ' + ', '.join(missing))
        try: Fernet(config['encryption_key'].encode())
        except (ValueError,TypeError): raise ValueError('CREDENTIAL_KEY must be a valid Fernet key.') from None
        if env.get('LIVE_PAYMENTS_ENABLED') != 'true' or not config['panel_writes']:
            raise ValueError('Live payments require LIVE_PAYMENTS_ENABLED=true and PANEL_WRITE_ENABLED=true.')
        for asset in config['assets'].values():
            if not asset.get('enabled', True): continue
            if not asset['wallet'] or not asset['rpc_url']:
                raise ValueError('Missing receiving wallet or read-only API for ' + asset['id'])
            try: BlockchainVerifier._validate_config(asset)
            except PaymentRejected as exc: raise ValueError('Invalid live asset '+asset['id']+': '+str(exc)) from None
            if asset['network'] == 'ethereum' and not re.fullmatch(r'0x[0-9a-fA-F]{40}', asset['wallet']):
                raise ValueError('Invalid Ethereum wallet.')
            if asset['network'] == 'solana' and not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}', asset['wallet']):
                raise ValueError('Invalid Solana wallet.')
            if asset['network'] == 'bitcoin' and not re.fullmatch(r'(bc1[ac-hj-np-z02-9]{25,90}|[13][1-9A-HJ-NP-Za-km-z]{24,34})', asset['wallet']):
                raise ValueError('Invalid Bitcoin mainnet wallet.')
    return config
