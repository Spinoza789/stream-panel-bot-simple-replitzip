"""Retail plan prices editable from the admin dashboard.

config.json stays the source of plan structure (ids, months, devices, panel package ids);
the owner's price and on-sale changes are stored in the metadata table and applied over
the config at start-up and immediately after each change. Changes affect new quotes only.
"""
import json
from decimal import Decimal, InvalidOperation

from .service import CheckoutError

KEY = 'plan_overrides'


class Pricing:
    def __init__(self, service):
        self.service = service; self.store = service.store; self.config = service.config
        self.apply()

    def overrides(self):
        raw = self.store.metadata(KEY)
        try: data = json.loads(raw) if raw else {}
        except ValueError: data = {}
        return data if isinstance(data, dict) else {}

    def apply(self):
        data = self.overrides()
        for plan in self.config.get('plans', []):
            o = data.get(plan['id'])
            if not isinstance(o, dict): continue
            if 'gbp_price' in o and 'gbp_price' in plan: plan['gbp_price'] = str(o['gbp_price'])
            if 'active' in o: plan['active'] = bool(o['active'])

    def plans(self, include_hidden=False):
        return [p for p in self.config.get('plans', []) if include_hidden or p.get('active', True)]

    def plan(self, plan_id, include_hidden=False):
        return next((p for p in self.plans(include_hidden) if p['id'] == plan_id), None)

    @staticmethod
    def price(value):
        try: amount = Decimal(str(value).strip().lstrip('£'))
        except (InvalidOperation, ValueError): raise CheckoutError('Enter a price in pounds, like 12.50.') from None
        if not amount.is_finite() or amount < 1 or amount > 10000 or amount != amount.quantize(Decimal('0.01')):
            raise CheckoutError('Prices must be between £1 and £10,000 with at most two decimals.')
        return f'{amount:.2f}'

    def set_plan(self, actor, plan_id, gbp_price, active, reason):
        finance = self.service.resellers.finance
        finance.admin(actor)
        plan = self.plan(plan_id, include_hidden=True)
        if not plan or 'gbp_price' not in plan: raise CheckoutError('Plan not found.')
        price = self.price(gbp_price); active = bool(active)
        if active is False and not [p for p in self.plans() if p['id'] != plan_id]:
            raise CheckoutError('At least one plan must stay on sale.')
        data = self.overrides(); data[plan_id] = dict(gbp_price=price, active=active)
        if self.service.resellers.ready:
            with finance.transaction() as db:
                finance.audit(db, actor, 'plan_price', plan_id, reason, dict(gbp_price=price, active=active, previous=plan.get('gbp_price')))
        elif not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
            raise CheckoutError('A reason of 3–500 characters is required.')
        self.store.metadata(KEY, json.dumps(data))
        plan['gbp_price'] = price; plan['active'] = active
        return plan

    def public(self):
        return [dict(id=p['id'], name=p['name'], months=int(p.get('months', 0)), connections=int(p.get('connections', 1)), detail=p.get('detail', ''),
                     gbpPrice=str(p.get('gbp_price', '')), active=bool(p.get('active', True))) for p in self.config.get('plans', []) if 'gbp_price' in p]
