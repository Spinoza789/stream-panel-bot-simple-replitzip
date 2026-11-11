"""The main menu, built around what this user needs next.

A new visitor is offered the trial; someone mid-trial sees the time left and an upgrade;
a subscriber sees their expiry and a renew button; a lapsed customer sees how to switch
back on. Everything is derived from stored orders, never from a panel call, so the menu
is instant.
"""
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .reseller_provider import provider_time

LONDON = ZoneInfo('Europe/London')
DAY = 86400


def b(text, data): return {'text': text, 'callback_data': data}


def plural(n, word): return '%d %s%s' % (n, word, '' if n == 1 else 's')


def left(seconds):
    """'14 hours', '3 days' — the largest sensible unit, never zero."""
    if seconds >= 2 * DAY: return plural(int(seconds // DAY), 'day')
    if seconds >= 3600: return plural(int(seconds // 3600), 'hour')
    return plural(max(1, int(seconds // 60)), 'minute')


def day(ts): return datetime.fromtimestamp(ts, LONDON).strftime('%-d %b %Y')


def clock(ts):
    when, today = datetime.fromtimestamp(ts, LONDON), datetime.now(LONDON).date()
    label = 'today' if when.date() == today else 'tomorrow' if (when.date() - today).days == 1 else when.strftime('on %-d %b')
    return label + ' at ' + when.strftime('%H:%M')


class Menus:
    TRIAL_ENDING = 3 * 3600   # "ends soon" nudge
    EXPIRING = 7 * DAY

    def __init__(self, bot):
        self.bot = bot; self.service = bot.service; self.store = bot.store

    # ---------- state ----------
    def expiry(self, order, fallback):
        value = (order.get('credentials') or {}).get('expires_at')
        if value:
            try: return provider_time(value, self.service.config.get('provider_timezone', 'Europe/London'))
            except Exception: pass
        return fallback

    def subscription(self, uid, orders=None):
        """The customer's own membership with the latest expiry, or None. Renewals and upgrades share one login."""
        orders = self.store.telegram_orders(uid) if orders is None else orders
        groups = {}
        for order in orders:
            plan, creds = order['plan'], order.get('credentials') or {}
            if order['status'] != 'fulfilled' or plan.get('reseller_purchase') or not creds.get('username'): continue
            months = int(plan.get('months') or 1)
            expires = self.expiry(order, order['created_at'] + months * 30 * DAY)
            groups.setdefault(str(creds.get('panel_id') or order['id']), []).append((expires, order))
        if not groups: return None
        members = max(groups.values(), key=lambda g: max(e for e, _ in g))
        expires = max(e for e, _ in members)
        latest = max((o for _, o in members), key=lambda o: o['created_at'])
        root = next((o for _, o in members if str((o.get('credentials') or {}).get('panel_id') or '').isdigit()
                     and (not o['plan'].get('renew_of') or o['plan'].get('trial_upgrade'))), None)
        return dict(expires_at=expires, order=latest, renew_id=root['id'] if root else None,
                    months=int(latest['plan'].get('months') or 1), connections=int(latest['plan'].get('connections') or 1),
                    price=latest['plan'].get('gbp_price'))

    def state(self, uid):
        now = int(time.time())
        result = dict(kind='new', now=now, reseller=None, faq=bool(self.service.faq.items()) if hasattr(self.service, 'faq') else False)
        if not uid: return result
        member = self.service.resellers.member(uid)
        if member and member['status'] == 'active':
            try: counts = self.service.resellers.ops.counts(uid)
            except Exception: counts = None
            result['reseller'] = dict(credits=member['available'], counts=counts)
        result['member'] = member
        orders = self.store.telegram_orders(uid) if hasattr(self.store, 'telegram_orders') else []
        trial = self.service.trial_status(uid) if hasattr(self.service, 'trial_status') else None
        result['trial'] = trial
        paying = [o for o in orders if o['status'] == 'pending' and o.get('txid')]
        queued = [o for o in orders if o['status'] in ('paid', 'provisioning') and not o['plan'].get('reseller_purchase')]
        sub = self.subscription(uid, orders)
        result['sub'] = sub
        if paying or queued:
            result.update(kind='paying', order=max(paying or queued, key=lambda o: o['created_at']))
        elif sub:
            remaining = sub['expires_at'] - now
            result.update(kind='expired' if remaining <= 0 else 'expiring' if remaining <= self.EXPIRING else 'active', remaining=remaining)
        elif trial and trial['status'] == 'fulfilled':
            expires = self.expiry(trial, trial['created_at'] + DAY)
            remaining = expires - now
            result.update(kind='trial_ended' if remaining <= 0 else 'trial_ending' if remaining <= self.TRIAL_ENDING else 'trial_active',
                          remaining=remaining, trial_expires=expires,
                          upgradable=self.service.trial_upgrade_target(uid) is not None if hasattr(self.service, 'trial_upgrade_target') else False)
        elif trial and trial['status'] == 'review':
            result.update(kind='trial_review')
        elif trial:
            result.update(kind='trial_pending')
        elif result['reseller']:
            result.update(kind='reseller')
        return result

    # ---------- shared pieces ----------
    def prices(self):
        values = []
        for plan in self.service.config.get('plans', []):
            if not plan.get('active', True): continue
            try: values.append(float(plan['gbp_price']))
            except (KeyError, TypeError, ValueError): pass
        return values

    def from_price(self):
        values = self.prices()
        return self.bot.gbp(min(values)) if values else None

    def coins(self):
        seen = []
        for asset in self.service.config.get('assets', {}).values():
            if asset.get('enabled', True) and asset.get('symbol') not in seen: seen.append(asset['symbol'])
        return ', '.join(seen)

    def header(self):
        demo = ('🧪 DEMO MODE — orders and accounts are simulations. No real payments are accepted.\n\n'
                if self.service.config['mode'] == 'demo' and self.service.config.get('demo_banner', True) else '')
        return demo + '📺 ' + self.service.config['brand']

    def help_row(self, s):
        return [b('📲 How to watch', 'menu:watch'), b('💡 FAQ', 'menu:faq')] if s['faq'] else [b('📲 How to watch', 'menu:watch'), b('🛟 Support', 'menu:contact')]

    def tail(self, s, account=True):
        """Bottom rows every state shares: help, account/support, and the reseller entry."""
        rows = [self.help_row(s)]
        second = ([b('👤 My account', 'menu:account')] if account else []) + ([b('🛟 Support', 'menu:contact')] if s['faq'] else [])
        if second: rows.append(second)
        member = s.get('member')
        rows.append([b('💼 Reseller dashboard' if member and member['status'] != 'pending' else '💼 Become a reseller', 'rs:home')])
        return rows

    def reseller_line(self, s):
        r = s.get('reseller')
        if not r: return ''
        line = '\n\n💼 Reseller · 🪙 ' + plural(r['credits'], 'credit')
        if r['counts']: line += ' · 🟢 ' + str(r['counts']['active']) + ' active'
        return line

    def plan_line(self, sub):
        return plural(sub['months'], 'month') + ' plan · ' + plural(sub['connections'], 'device')

    def renew_button(self, sub, label='🔄 Renew'):
        if sub.get('renew_id'):
            price = (' · ' + plural(sub['months'], 'month') + ' ' + self.bot.gbp(sub['price'])) if sub.get('price') else ''
            return b(label + price, 'pay:renew:' + sub['renew_id'])
        return b(label, 'menu:plans')

    # ---------- the menu ----------
    def build(self, uid):
        s = self.state(uid); kind = s['kind']; head = self.header(); price = self.from_price()
        from_price = ('from ' + price) if price else 'on a plan that suits you'
        if kind == 'paying':
            order = s['order']
            if order['status'] == 'pending':
                text = head + '\n⏳ Payment being confirmed\n' + (order.get('message') or 'We are checking the blockchain. No need to pay again.')
            else:
                text = head + '\n🟢 Payment received\nYour account is being prepared. Your login arrives in this chat in a moment.'
            rows = [[b('🔄 Check payment status', 'pay:status:' + order['id'])], [b('🧾 My orders', 'pay:orders'), b('🛟 Support', 'menu:contact')]]
            if s.get('sub'): rows.insert(1, [b('🔑 Show my login', 'menu:login')])
            return text + self.reseller_line(s), {'inline_keyboard': rows}
        if kind == 'active':
            sub = s['sub']
            text = (head + '\n🟢 Active until ' + day(sub['expires_at']) + '\n' + self.plan_line(sub) + ' · ' + left(s['remaining']) + ' left')
            rows = [[b('🔑 Show my login', 'menu:login')], [self.renew_button(sub, '🔄 Renew early'), b('💎 Plans', 'menu:plans')]] + self.tail(s)
        elif kind == 'expiring':
            sub = s['sub']
            text = (head + '\n🟠 Your subscription ends in ' + left(s['remaining']) + '\nExpires ' + day(sub['expires_at']) +
                    ' · renew now and the time is added on top.')
            rows = [[self.renew_button(sub)], [b('💎 Switch to a longer plan', 'menu:plans')], [b('🔑 Show my login', 'menu:login')]] + self.tail(s)
        elif kind == 'expired':
            sub = s['sub']
            text = (head + '\n🔴 Your subscription expired on ' + day(sub['expires_at']) +
                    '\nRenew to switch it back on. Same login, no setup needed.')
            rows = [[self.renew_button(sub)], [b('💎 See all plans', 'menu:plans')]] + self.tail(s)
        elif kind == 'trial_active':
            text = (head + '\n🟢 Free trial active · ' + left(s['remaining']) + ' left\nEnds ' + clock(s['trial_expires']) +
                    '\n\nEnjoying it? Keep the same login ' + from_price + ' a month.')
            rows = [[b('🔑 Show my login', 'menu:login')],
                    [b('🚀 Keep watching · upgrade', 'pay:upgrade') if s['upgradable'] else b('💎 Plans and prices', 'menu:plans')]] + self.tail(s)
        elif kind == 'trial_ending':
            text = (head + '\n🟠 Your trial ends in ' + left(s['remaining']) +
                    '\nUpgrade now and nothing changes: same username, same password.')
            rows = [[b('🚀 Upgrade ' + from_price, 'pay:upgrade') if s['upgradable'] else b('💎 Plans and prices', 'menu:plans')],
                    [b('🔑 Show my login', 'menu:login')]] + self.tail(s)
        elif kind == 'trial_ended':
            if s['upgradable']:
                text = head + '\n🔴 Your free trial has ended\nPick up where you left off. Your login is saved for you.'
                rows = [[b('🚀 Reactivate my login · ' + from_price, 'pay:upgrade')], [b('💎 Plans for 2 or 3 devices', 'menu:plans')]]
            else:
                text = head + '\n🔴 Your free trial has ended\nChoose a plan to keep watching.'
                rows = [[b('💎 Plans and prices', 'menu:plans')]]
            if s.get('reseller'): rows.insert(0, [b('🎁 Create a customer trial', 'rs:trial')])
            rows += self.tail(s)
        elif kind == 'trial_pending':
            text = (head + '\n⏳ Your free trial is being set up. This usually takes under a minute.\n'
                    'I will send your login here as soon as it is ready.')
            rows = [[b('🔄 Check my trial', 'menu:trial')]] + self.tail(s, account=False)
        elif kind == 'trial_review':
            text = head + '\n🟠 Your trial needs a quick check before it can be delivered.'
            rows = [[b('🔄 Check / retry trial', 'menu:retrytrial')]] + self.tail(s)
        elif kind == 'reseller':
            r = s['reseller']; c = r['counts'] or {}
            text = (head + ' · Reseller\n🪙 ' + plural(r['credits'], 'credit') + ' available\n🟢 ' + str(c.get('active', 0)) + ' active · 🟠 ' +
                    str(c.get('expiring', 0)) + ' expiring this week · 🎁 ' + plural(c.get('trials', 0), 'trial') + ' running')
            rows = [[b('➕ New subscription', 'rs:create'), b('🎁 New trial', 'rs:trial')], [b('💼 Reseller dashboard', 'rs:home')],
                    [b('🪙 Buy credits', 'rs:packages'), b('🛟 Support', 'menu:contact')],
                    [b('🎁 My own free trial', 'menu:trial'), b('👤 My account', 'menu:account')]]
            return text, {'inline_keyboard': rows}
        else:
            coins = self.coins()
            text = (head + '\nLive TV, sport, movies and box sets on any device.\n\n'
                    '🎁 Free for 24 hours · no payment needed\n'
                    '💎 Then ' + from_price + (' a month' if price else '') + (' · ' + coins if coins else ''))
            rows = [[b('🎁 Start my free 24-hour trial', 'menu:trial')], [b('💎 Plans and prices', 'menu:plans')]] + self.tail(s)
        return text + (self.reseller_line(s) if kind != 'reseller' else ''), {'inline_keyboard': rows}

    # ---------- plans ----------
    def plans(self):
        """One screen with every price: a grid, a button per length for one device, and a way to more devices."""
        active = [p for p in self.service.config.get('plans', []) if p.get('active', True) and 'gbp_price' in p and not p.get('adult_content')]
        months = sorted({int(p['months']) for p in active}); devices = sorted({int(p['connections']) for p in active})
        price = {(int(p['months']), int(p['connections'])): p['gbp_price'] for p in active}
        if not active: return '💎 PLANS AND PRICES\n\nNo plans are on sale right now. Contact support.', {'inline_keyboard': [[b('🛟 Support', 'menu:contact')], [b('⬅️ Back', 'menu')]]}
        gbp = self.bot.gbp
        lines = ['%-10s' % '' + ''.join('%8s' % (str(d) + ' dev') for d in devices)]
        for m in months:
            lines.append('%-10s' % plural(m, 'month') + ''.join('%8s' % (gbp(price[(m, d)]) if (m, d) in price else '—') for d in devices))
        single = [m for m in months if (m, 1) in price]
        best = min(single, key=lambda m: float(price[(m, 1)]) / m) if len(single) > 1 else None
        coins = self.coins()
        text = ('<b>💎 PLANS AND PRICES</b>\nEvery plan includes all channels.' + (' Pay in ' + coins + '.' if coins else '') +
                '\n\n<pre>' + '\n'.join(lines) + '</pre>')
        if best and best != single[0]:
            text += '\n⭐ Best value: ' + plural(best, 'month') + ' works out at ' + gbp(round(float(price[(best, 1)]) / best, 2)) + ' a month'
        text += '\n\n🏠 All devices must be in the same household. Nothing is ordered until you choose a coin.'
        buttons = [b(('⭐ ' if m == best and best != single[0] else '') + plural(m, 'month') + ' · ' + gbp(price[(m, 1)]), 'plan:pick:%d:0:1' % m) for m in single]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        if any(d > 1 for d in devices): rows.append([b('📱 I need 2 or 3 devices', 'plan:duration')])
        rows.append([b('⬅️ Back', 'menu')])
        return text, {'inline_keyboard': rows}

    # ---------- account ----------
    def account(self, uid):
        s = self.state(uid); sub, trial = s.get('sub'), s.get('trial')
        lines = ['👤 MY ACCOUNT', '']
        if sub:
            remaining = sub['expires_at'] - s['now']
            dot = '🔴 Expired on ' if remaining <= 0 else '🟠 Active until ' if remaining <= self.EXPIRING else '🟢 Active until '
            lines.append(dot + day(sub['expires_at']) + ' · ' + plural(sub['connections'], 'device'))
        if trial: lines.append('🎁 24-hour trial — ' + trial['status'])
        for account in self.service.linked_accounts(uid):
            lines.append('🔗 ' + account['plan']['name'] + ' — ' + account['status'] + ' (order ' + account['id'] + ')')
        if not sub and not trial: lines.append('Nothing here yet. Start a free trial or choose a plan.')
        lines.extend(['', 'Telegram ID ' + str(uid)])
        rows = []
        if trial and trial['status'] == 'review': rows.append([b('🔄 Check / retry trial', 'menu:retrytrial')])
        first = ([b('🔑 My login', 'menu:login')] if sub or (trial and trial['status'] == 'fulfilled') else []) + [b('🧾 My orders', 'pay:orders')]
        rows.append(first)
        rows.append(([self.renew_button(sub, '🔄 Renew')] if sub else [b('💎 Plans', 'menu:plans')]) + [b('⚙️ Notifications', 'nt:settings')])
        rows.append([b('🛟 Support', 'menu:contact'), b('⬅️ Back', 'menu')])
        return '\n'.join(lines), {'inline_keyboard': rows}
