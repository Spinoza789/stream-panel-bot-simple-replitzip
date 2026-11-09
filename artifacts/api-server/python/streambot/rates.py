"""GBP quotes using decimal strings; provider failures never fall back to demo rates."""
import threading
import time
from decimal import Decimal, InvalidOperation
import requests


class RateUnavailable(Exception): pass


class Rates:
    def __init__(self, demo=False, http=None):
        self.demo = demo; self.http = http or requests.Session()
        self.lock = threading.Lock(); self.cached = {}; self.fetched_at = 0

    def snapshot(self, symbol):
        if self.demo:
            rates={'USD':Decimal('1.25'),'USDC':Decimal('1.25'),'USDT':Decimal('1.25'),
                   'ETH':Decimal('0.0004'),'BTC':Decimal('0.000015')}
            return {'usd_per_gbp':rates['USD'],'crypto_per_gbp':rates[symbol],
                    'crypto_per_usd':rates[symbol]/rates['USD'],'fetched_at':int(time.time())}
        with self.lock:
            if time.time() - self.fetched_at > 60:
                try:
                    response = self.http.get('https://api.coinbase.com/v2/exchange-rates', params={'currency':'GBP'}, timeout=12)
                    response.raise_for_status(); data = response.json()['data']
                    if data['currency'] != 'GBP': raise ValueError('Wrong base currency')
                    rates = {key: Decimal(data['rates'][key]) for key in ('USD','USDC','USDT','ETH','BTC')}
                    if any(not r.is_finite() or r <= 0 for r in rates.values()): raise ValueError('Invalid exchange rate')
                    self.cached = rates; self.fetched_at = time.time()
                except (requests.RequestException, KeyError, ValueError, InvalidOperation):
                    raise RateUnavailable('Exchange rates are temporarily unavailable. Please try again later.') from None
            return {'usd_per_gbp':self.cached['USD'],'crypto_per_gbp':self.cached[symbol],
                    'crypto_per_usd':self.cached[symbol]/self.cached['USD'],
                    'fetched_at':int(self.fetched_at)}

    def rate(self, symbol):
        return self.snapshot(symbol)['crypto_per_gbp']
