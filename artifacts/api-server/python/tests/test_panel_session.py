"""Panel session renewal: the panel signs sessions out after about an hour."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from streambot.panel import PanelClient, PanelError, PanelSessionExpired, ProvisioningUncertain

BASE = 'https://panel.example.invalid'
LOGIN_PAGE = ('<form action="/"><input name="_token" value="csrf"><input name="username">'
              '<input name="password"></form>')


def page(path, text='<html><body>ok</body></html>', status=200, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {}, url=BASE + path, text=text, json=lambda: {})


class FakePanel:
    """Scripted HTTP: the session is signed out after `valid_for` authenticated reads."""
    def __init__(self, valid_for):
        self.valid_for = valid_for
        self.reads = 0
        self.logins = 0
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        if path in ('/', BASE + '/'):
            if method == 'GET':
                return page('/', LOGIN_PAGE)
            self.logins += 1
            self.reads = 0
            return page('/', status=302, headers={'Location': '/dashboard'})
        if path.endswith('/dashboard'):
            return page('/dashboard')
        self.reads += 1
        if self.logins == 0 or self.reads > self.valid_for:
            return page('/', LOGIN_PAGE)  # signed out: the panel shows its login form
        return page(path, '<html><body>' + path + '</body></html>')


class PanelSessionTests(unittest.TestCase):
    def client(self, valid_for=1000, **kwargs):
        fake = FakePanel(valid_for)
        panel = PanelClient(BASE, 'login', 'secret', allow_create=True, **kwargs)
        panel._request = fake.request
        return panel, fake

    def test_first_read_signs_in_once_and_later_reads_reuse_the_session(self):
        panel, fake = self.client()
        self.assertIn('/lines', panel._read('/lines').text)
        panel._read('/lines'); panel._read('/lines')
        self.assertEqual(fake.logins, 1)

    def test_signed_out_session_is_renewed_and_the_read_repeated(self):
        panel, fake = self.client(valid_for=2)
        panel._read('/lines'); panel._read('/lines')
        response = panel._read('/lines/create/0/line')  # third read: the panel has signed us out
        self.assertIn('/lines/create/0/line', response.text)
        self.assertEqual(fake.logins, 2)
        self.assertTrue(panel._authenticated)

    def test_session_older_than_the_limit_is_renewed_before_reading(self):
        panel, fake = self.client(session_max_age=60)
        panel._read('/lines')
        panel._authenticated_at = time.time() - 61
        panel._read('/lines')
        self.assertEqual(fake.logins, 2)
        self.assertEqual([c for c in fake.calls if c == ('GET', '/lines')], [('GET', '/lines')] * 2)

    def test_default_renewal_limit_is_under_the_panel_hour(self):
        self.assertLess(PanelClient.SESSION_MAX_AGE, 3600)
        self.assertGreaterEqual(PanelClient.SESSION_MAX_AGE, 30 * 60)

    def test_persistent_sign_out_is_reported_after_one_renewal(self):
        panel, fake = self.client(valid_for=0)
        with self.assertRaisesRegex(PanelError, 'session expired'):
            panel._read('/lines')
        self.assertEqual(fake.logins, 2)
        self.assertFalse(panel._authenticated)

    def test_listing_post_sign_out_renews_and_lists_again(self):
        panel, _ = self.client()
        panel._login = Mock()
        panel._list_accounts = Mock(side_effect=[PanelSessionExpired('x'), [{'username': 'a'}]])
        self.assertEqual(panel._account_rows('a'), [{'username': 'a'}])
        panel._login.assert_called_once()
        self.assertEqual(panel._list_accounts.call_count, 2)

    def test_listing_post_sign_out_marks_the_session_invalid(self):
        panel, _ = self.client()
        panel._authenticated = True; panel._authenticated_at = time.time()
        panel._list_accounts = Mock(side_effect=PanelSessionExpired('x'))
        panel._login = Mock()
        with self.assertRaises(PanelSessionExpired):
            panel._account_rows('a')
        self.assertEqual(panel._login.call_count, 1)

    def test_creation_post_is_never_repeated_after_a_sign_out(self):
        panel, fake = self.client()
        panel._authenticated = True; panel._authenticated_at = time.time()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<form method="POST" action="/lines/create/0"><input name="_token" value="t">'
                             '<input name="credits_left" value="10"><input name="line_type" value="line">'
                             '<input name="current_bouquets" value=""><input name="username"><input name="password">'
                             '<textarea name="description"></textarea>'
                             '<select name="package"><option value="275" data-credits="0">Trial</option></select></form>', 'html.parser')
        panel._create_form = Mock(return_value=(soup, soup.form, BASE + '/lines/create/0'))
        panel._package_details = Mock(return_value={'result': True, 'data': {'max_connections': 1, 'exp_date': '2030-01-01'}, 'bouquets': [{'id': 1}]})
        posts = []
        def request(method, path, **kwargs):
            if method == 'POST':
                posts.append(path)
                return page('/', LOGIN_PAGE)  # signed out exactly at the creation request
            return page(path)
        panel._request = request
        generation = dict(generation_mode='panel', package_id='275', before_ids=['8'], prepared_at=int(time.time()))
        with self.assertRaises(ProvisioningUncertain):
            panel.create_account('275', '', '', '', generation=generation)
        self.assertEqual(len(posts), 1)


if __name__ == '__main__':
    unittest.main()
