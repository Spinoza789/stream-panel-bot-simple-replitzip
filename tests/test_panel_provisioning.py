"""Panel creation protocol tests with no external requests."""
import unittest
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
            <select name="package"><option value="275" data-credits="0">Trial</option></select>
            </form>''', 'html.parser')
        self.panel._create_form = Mock(return_value=(soup, soup.form, 'https://panel.example.invalid/lines/create/0'))
        self.panel._package_details = Mock(return_value={
            'result': True, 'data': {'max_connections': 1, 'exp_date': '2030-01-01'},
            'bouquets': [{'id': 12}, {'id': 34}],
        })
        self.account = dict(username='test-user', password='test-secret', package_id='275')
        self.panel.find_account = Mock(side_effect=[None, self.account])
        self.panel._request = Mock(return_value=SimpleNamespace(
            status_code=302, headers={'Location': '/lines'}, text='', url='https://panel.example.invalid/lines'))

    def create(self):
        return self.panel.create_account('275', 'test-user', 'test-secret', 'test order')

    def test_bouquets_follow_browser_comma_separated_protocol(self):
        self.assertEqual(self.create()['username'], 'test-user')
        self.panel._request.assert_called_once()
        data = self.panel._request.call_args.kwargs['data']
        self.assertEqual(data['current_bouquets'], '12,34')
        self.assertEqual(data['bouquets[]'], ['12', '34'])
        self.assertEqual(data['bouquets_main[]'], ['12', '34'])
        self.assertEqual(data['price'], '0')
        self.assertEqual(data['credits_left'], '10')
        self.assertEqual(data['connections'], '1')

    def test_existing_matching_account_never_posts_again(self):
        self.panel.find_account = Mock(return_value=self.account)
        self.assertEqual(self.create(), self.account)
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
        self.panel._request.assert_called_once()

    def test_unverified_result_never_automatically_reposts(self):
        self.panel.find_account = Mock(side_effect=[None, None])
        with self.assertRaises(ProvisioningUncertain) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, 'confirmation_failed')
        self.panel._request.assert_called_once()
