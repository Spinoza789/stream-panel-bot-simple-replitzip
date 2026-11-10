"""Reseller subsystem facade; ordinary retail trial eligibility stays separate."""
import calendar
import logging
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from .panel import PanelError
from .reseller_ledger import Ledger, now
from .reseller_operations import Operations
from .reseller_provider import PanelProvider
from .service import CheckoutError


class DemoProvider:
    """Explicit local simulation only. Never selected by a live configuration."""
    def __init__(self,service):self.store=service.store
    def package(self,months,connections,adult):return 'demo-'+str(months)+'-'+str(connections)+'-'+str(adult)
    def read(self,pid):
        data=self.store.metadata('rs_demo:'+pid)
        if not data:raise PanelError('Demo account not found')
        result=self.store.unseal(data)
        result['status']='active' if result['expires_at']>now() else 'expired'
        return result
    def preview_extension(self,record,months):
        current=self.read(record['provider_id'])
        return dict(previous_expiry=current['expires_at'],expected_expiry=self.expiry(max(current['expires_at'],now()),months),
                    package_id=self.package(months,record['connections'],bool(record['adult'])))
    @staticmethod
    def expiry(start,months):
        if months==0:return start+86400
        value=datetime.fromtimestamp(start,ZoneInfo('Europe/London'))
        month=value.month-1+months;year=value.year+month//12;month=month%12+1
        return int(value.replace(year=year,month=month,day=min(value.day,calendar.monthrange(year,month)[1])).timestamp())
    def prepare(self,operation,record=None):
        return dict(record=record,expected_expiry=self.expiry(max(now(),record['expires_at']) if record else now(),operation['months']))
    def execute(self,operation,context):
        record=context['record']
        pid=record['provider_id'] if record else str(secrets.randbelow(10**15)+1)
        credentials=self.read(pid)['credentials'] if record else dict(username='demo_'+secrets.token_hex(4),password=secrets.token_urlsafe(12),server_url='DEMO — simulated account')
        result=dict(provider_id=pid,expires_at=context['expected_expiry'],credentials=credentials,status='active',starts_at=now())
        self.store.metadata('rs_demo:'+pid,self.store.seal(result))
        return result
    def reconcile(self,operation,context,provider_id=None):
        pid=provider_id or (context.get('record') or {}).get('provider_id')
        if not pid:raise PanelError('Identify the demo account first')
        return self.read(pid)


class Resellers:
    def __init__(self,service):
        self.service=service
        self.finance=Ledger(service)
        try:
            with service.store.connection() as db:db.execute('SELECT id FROM rs_resellers WHERE 1=0')
            self.ready=True
        except Exception as exc:
            self.ready=False
            logging.getLogger(__name__).warning('Reseller tables unavailable (%s); reseller actions are disabled until setup is complete.',type(exc).__name__)
        provider=DemoProvider(service) if service.config['mode']=='demo' else PanelProvider(service)
        self.ops=Operations(self.finance,provider)
        from .reseller_web import ResellerWeb
        self.web=ResellerWeb(self)

    def require_ready(self):
        if not self.ready:raise CheckoutError('Reseller database setup is not available. Publish the development schema before enabling reseller actions.')

    def member(self,uid):
        return self.finance.member(uid) if self.ready else None

    def guard(self,uid):
        if uid is None:return
        member=self.member(uid)
        if member and member['status']=='suspended':
            raise CheckoutError('Your reseller account is suspended. Contact support before purchasing or creating accounts.')

    def process(self):
        if self.ready:self.ops.process()

    def recover(self):
        if self.ready:self.ops.recover()
