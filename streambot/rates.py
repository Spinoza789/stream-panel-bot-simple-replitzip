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

    def rate(self, symbol):
        if self.demo:
            return {'USDC':Decimal('1.25'),'USDT':Decimal('1.25'),'ETH':Decimal('0.0004'),'BTC':Decimal('0.000015')}[symbol]
        with self.lock:
            if time.time() - self.fetched_at > 60:
                try:
                    response = self.http.get('https://api.coinbase.com/v2/exchange-rates', params={'currency':'GBP'}, timeout=12)
                    response.raise_for_status(); data = response.json()['data']
                    if data['currency'] != 'GBP': raise ValueError('Wrong base currency')
                    rates = {key: Decimal(data['rates'][key]) for key in ('USDC','USDT','ETH','BTC')}
                    if any(not r.is_finite() or r <= 0 for r in rates.values()): raise ValueError('Invalid exchange rate')
                    self.cached = rates; self.fetched_at = time.time()
                except (requests.RequestException, KeyError, ValueError, InvalidOperation):
                    raise RateUnavailable('Exchange rates are temporarily unavailable. Please try again later.') from None
            return self.cached[symbol]
