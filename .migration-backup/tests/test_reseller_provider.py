"""Native widget and renewal contract fixtures. No real HTTP requests."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup

from streambot.config import load_config
from streambot.panel import PanelClient,PanelError,ProvisioningUncertain
from streambot.reseller_provider import PanelProvider,provider_time


class Response:
    status_code=200
    url='https://panel.example/lines'
    headers={}
    def __init__(self,text='',payload=None):self.text=text;self.payload=payload
    def json(self):return self.payload


class NativeProviderTests(unittest.TestCase):
    def setUp(self):
        self.panel=PanelClient('https://panel.example','test-admin','test-password',allow_create=True)
        self.config=load_config(env={'APP_MODE':'demo'})
        self.provider=PanelProvider(SimpleNamespace(panel=self.panel,config=self.config))
        self.account=dict(panel_id='7',username='test-user',password='test-secret',
                          expires_at='2027-01-08 12:00',connections='<span>0/2</span>',enabled='1')
        self.edit="""<form class="pro-ajax" action="/lines/edit/7" method="POST">
        <input name="username" value="test-user"><input name="password" value="test-secret">
        <input name="current_bouquets" value=""><textarea name="description">-</textarea>
        <select id="searchmain_to" name="bouquets_main[]" multiple>
        <option value="1">Group one</option><option value="2">Group two</option></select>
        <select name="bouquets[]" multiple></select></form>"""

    def test_read_uses_native_right_hand_options_and_max_connection_denominator(self):
        self.panel._account_rows=Mock(return_value=[self.account])
        response=Response(self.edit);response.url='https://panel.example/lines/edit/7'
        self.panel._read=Mock(return_value=response)
        result=self.provider.read('7')
        self.assertEqual(result['bouquets'],['1','2'])
        self.assertEqual(result['connections'],2)
        self.assertEqual(result['credentials']['username'],'test-user')
        self.assertEqual(result['status'],'active')

    def test_renewal_preparation_uses_native_identity_and_preserves_empty_notes(self):
        html="""<form action="/lines/extend/7" method="POST">
        <input name="_token" value="test-csrf"><input name="username" value="test-user">
        <select name="package"><option value="141">1 Month With Adult 2 Connections</option></select>
        <input name="credits_left" value="100"><input name="expire_date">
        <input name="connections"><input name="price"><input name="current_bouquets">
        <textarea name="description">-</textarea></form>"""
        self.panel._read=Mock(return_value=Response(html))
        self.panel._ajax=Mock(return_value=('/lines/packages','POST',
                             """data: {'package_id': package.val(), 'trial':0,'id':'0','uid':'7'}"""))
        metadata=dict(result=True,data=dict(cost_credits=2,max_connections=2,exp_date='2027-02-08 12:00'),
                      bouquets=[{'id':1},{'id':2}])
        self.panel._request=Mock(return_value=Response(payload=metadata))
        self.provider.read=Mock(return_value=dict(provider_id='7',expires_at=1799409600,connections=2,status='active'))
        record=dict(provider_id='7',expires_at=1799409600,connections=2,adult=1)
        op=dict(operation_type='extend',package_id='141',connections=2)
        context=self.provider.prepare(op,record)
        method,path=self.panel._request.call_args.args
        self.assertEqual((method,path),('POST','/lines/packages'))
        self.assertEqual(self.panel._request.call_args.kwargs['data']['uid'],'7')
        self.assertEqual(context['data']['username'],'test-user')
        self.assertEqual(context['data']['description'],'')
        self.assertEqual(context['data']['credits_left'],'98')
        self.assertEqual(context['data']['current_bouquets'],'1,2')
        self.assertEqual(context['data']['connections'],'2')

    def test_extension_submits_once_and_requires_safe_acknowledgement(self):
        self.panel._request=Mock(return_value=Response(payload={'redirect':'https://panel.example/lines'}))
        self.provider.reconcile=Mock(return_value={'confirmed':True})
        context=dict(mode='extend',action='https://panel.example/lines/extend/7',data={'description':''})
        self.assertEqual(self.provider.execute({},context),{'confirmed':True})
        self.panel._request.assert_called_once()
        self.panel._request.reset_mock()
        self.panel._request.return_value=Response(payload={'redirect':'https://other.example/lines'})
        with self.assertRaises(ProvisioningUncertain):self.provider.execute({},context)
        self.panel._request.assert_called_once()

    def test_create_preflight_failure_is_definite_but_readback_failure_is_uncertain(self):
        op=dict(operation_type='create',package_id='137')
        context=dict(mode='create',generation={'test':'snapshot'},bouquets=['1'])
        self.panel.create_account=Mock(side_effect=PanelError('No submission'))
        with self.assertRaises(PanelError) as error:self.provider.execute(op,context)
        self.assertNotIsInstance(error.exception,ProvisioningUncertain)
        self.panel.create_account=Mock(return_value={'panel_id':'7'})
        self.provider.reconcile=Mock(side_effect=PanelError('Readback mismatch'))
        with self.assertRaises(ProvisioningUncertain):self.provider.execute(op,context)

    def test_no_adult_trial_uses_only_provider_verified_nonadult_bouquets(self):
        self.panel.prepare_generation=Mock(return_value={'before_ids':[]})
        self.panel._create_form=Mock(return_value=(BeautifulSoup('','html.parser'),None,None))
        def metadata(soup,pid):
            groups=[1,2] if pid=='137' else [1,2,3,4]
            return dict(result=True,data=dict(max_connections=1,exp_date='2026-11-10 12:00'),bouquets=[{'id':i} for i in groups])
        self.panel._package_details=Mock(side_effect=metadata)
        context=self.provider.prepare(dict(operation_type='trial',package_id='275',connections=1,adult=0))
        self.assertEqual(context['bouquets'],['1','2'])
        self.panel.create_account=Mock(return_value={'panel_id':'7'})
        self.provider.reconcile=Mock(return_value={'confirmed':True})
        self.provider.execute(dict(operation_type='trial',package_id='275'),context)
        self.assertEqual(self.panel.create_account.call_args.kwargs['bouquet_ids'],['1','2'])

    def test_native_clock_comparison_keeps_authoritative_unix_expiry_across_bst(self):
        actual=provider_time('2027-07-08 12:00','UTC')
        self.provider.read=Mock(return_value=dict(provider_id='7',expires_at=actual,status='active',
                                               connections=1,bouquets=['1'],native_expiry='08-07-2027 12:00'))
        context=dict(mode='extend',provider_id='7',expected_expiry=provider_time('2027-07-08 12:00'),
                     expected_native_expiry='2027-07-08 12:00',bouquets=['1'])
        result=self.provider.reconcile({'connections':1},context)
        self.assertEqual(result['expires_at'],actual)
