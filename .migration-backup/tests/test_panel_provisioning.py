"""Panel creation protocol tests with no external requests."""
import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock

from bs4 import BeautifulSoup

from streambot.panel import PanelClient, PanelError, ProvisioningUncertain


class PanelProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.panel = PanelClient('https://panel.example.invalid', 'test-login', 'test-password',
                                 allow_create=True)
        soup = BeautifulSoup('''<form method="POST" action="/lines/create/0">
            <input name="_token" value="fake-csrf">
            <input name="credits_left" value="10">
            <input name="line_type" value="line">
            <input name="current_bouquets" value="">
            <input name="username" value="remembered-user">
            <input name="password" value="remembered-password">
            <textarea name="description">remembered note</textarea>
            <select name="package"><option value="275" data-credits="0">Trial</option></select>
            </form>''', 'html.parser')
        self.panel._create_form = Mock(return_value=(soup, soup.form, 'https://panel.example.invalid/lines/create/0'))
        self.panel._package_details = Mock(return_value={
            'result': True, 'data': {'max_connections': 1, 'exp_date': '2030-01-01'},
            'bouquets': [{'id': 12}, {'id': 34}],
        })
        self.account = dict(panel_id='9',username='test-user', password='test-secret')
        self.generation = dict(generation_mode='panel',package_id='275',before_ids=['8'],prepared_at=int(time.time()))
        self.panel.account_snapshot = Mock(return_value={'8':{'panel_id':'8'},'9':self.account})
        self.panel._authenticated = True
        self.post = SimpleNamespace(status_code=200,headers={},text='',url='https://panel.example.invalid/lines/create/0',
                                    json=lambda:{'redirect':'/lines'})
        self.edit = SimpleNamespace(status_code=200,headers={},url='https://panel.example.invalid/lines/edit/9',
            text='''<form class="pro-ajax" action="/lines/edit/9">
            <input name="username" value="test-user"><input name="password" value="test-secret">
            <textarea name="description">-</textarea></form>''')
        self.panel._request = Mock(side_effect=lambda method,*args,**kwargs:self.post if method=='POST' else self.edit)

    def create(self):
        return self.panel.create_account('275', '', '', '', generation=self.generation)

    def posts(self):
        return [call for call in self.panel._request.call_args_list if call.args[0]=='POST']

    def test_bouquets_follow_browser_comma_separated_protocol(self):
        self.assertEqual(self.create()['username'], 'test-user')
        self.assertEqual(len(self.posts()),1)
        data = self.posts()[0].kwargs['data']
        self.assertEqual([data[k] for k in ('username','password','description')],['','',''])
        self.assertEqual(data['current_bouquets'], '12,34')
        self.assertEqual(data['bouquets[]'], ['12', '34'])
        self.assertEqual(data['bouquets_main[]'], ['12', '34'])
        self.assertEqual(data['price'], '0')
        self.assertEqual(data['credits_left'], '10')
        self.assertEqual(data['connections'], '1')

    def test_explicit_credentials_or_notes_are_never_submitted(self):
        with self.assertRaisesRegex(PanelError,'empty credentials'):
            self.panel.create_account('275','test-user','test-secret','test order')
        self.panel._request.assert_not_called()
        self.panel._create_form.assert_not_called()

    def test_invalid_bouquet_identifier_stops_before_post(self):
        self.panel._package_details.return_value['bouquets'] = [{'id': '12,34'}]
        with self.assertRaisesRegex(PanelError, 'bouquet selection'):
            self.create()
        self.panel._request.assert_not_called()

    def test_http_rejection_remains_uncertain_and_reports_only_status(self):
        error = PanelError('Panel returned an unsuccessful response')
        error.http_status = 422
        self.panel._request.side_effect = error
        with self.assertRaises(ProvisioningUncertain) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, 'http_422')
        self.assertNotIn('test-secret', str(caught.exception))
        self.assertEqual(len(self.posts()),1)

    def test_unverified_result_never_automatically_reposts(self):
        self.panel.account_snapshot.return_value = {'8':{'panel_id':'8'}}
        with self.assertRaises(ProvisioningUncertain) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, 'confirmation_failed')
        self.assertEqual(len(self.posts()),1)

    def test_concurrent_creation_or_deleted_records_are_ambiguous(self):
        for snapshot in ({'8':{},'9':self.account,'10':{}},{'9':self.account}):
            with self.subTest(snapshot_ids=sorted(snapshot)):
                self.panel.account_snapshot.return_value=snapshot
                with self.assertRaises(ProvisioningUncertain):
                    self.create()

    def test_account_details_must_match_and_have_no_added_notes(self):
        for content in ('<form class="pro-ajax" action="/lines/edit/9"><input name="username" value="other">'
                        '<input name="password" value="test-secret"><textarea name="description"></textarea></form>',
                        self.edit.text.replace('>-</textarea>','>unexpected note</textarea>')):
            with self.subTest():
                self.edit.text=content
                with self.assertRaises(ProvisioningUncertain):
                    self.create()

    def test_native_edit_form_is_not_mistaken_for_login(self):
        self.assertFalse(self.panel._is_login(self.edit))
        login=SimpleNamespace(url='https://panel.example.invalid/',text='<form action="/">'
                              '<input name="username"><input name="password"></form>')
        self.assertTrue(self.panel._is_login(login))

    def test_external_redirect_is_never_followed(self):
        self.post.json=lambda:{'redirect':'https://other.example.invalid/lines'}
        with self.assertRaises(ProvisioningUncertain):
            self.create()
        self.assertEqual(len(self.posts()),1)
        self.panel.account_snapshot.assert_not_called()
