"""Exact trial-delivery content, using fake credentials only."""
import unittest

from streambot.trial_message import trial_ready_text, membership_ready_text, APP_DOWNLOAD_GUIDE


class TrialMessageTests(unittest.TestCase):
    def test_exact_layout_codes_links_and_dynamic_credentials(self):
        expected="""<blockquote><u>24 Hour Trial</u>

<b>Username: generated-test-user</b>
<b>Password: generated-test-password</b></blockquote>

<b>APP DOWNLOAD CODES</b>

Enter a code in the Downloader app (Firestick):
<b>Sky Live</b>
<code>2976199</code> • <code>565410</code> • <code>6261787</code>
<code>962396</code> • <code>969828</code>

<b>Magic</b>
<code>9801832</code>

<b>Safe Media</b>
<code>589666</code> • <code>7400092</code>

<b>iPhone/Apple TV App</b> - viziplayer.com/app
URL Code <code>BA896705</code>

<b>Android APPS</b>
Sky Live: https://tinyurl.com/256zmkh3
Sky Glass: https://bit.ly/uhdglass
Smarters: https://apk.st/HVJU
Magic: https://apk.st/VPYJV
Safe Media: https://tinyurl.com/4fevkw2a
Safe Media V2: https://tinyurl.com/mrxhvej8"""
        actual=trial_ready_text({'username':'generated-test-user','password':'generated-test-password',
                                'server_url':'not-part-of-requested-message','expires_at':'not-part-of-requested-message'})
        self.assertEqual(actual,expected)
        self.assertLess(len(actual),4096)

    def test_another_customers_details_are_not_reused(self):
        text=trial_ready_text({'username':'another-test-user','password':'another-test-password'})
        self.assertIn('<b>Username: another-test-user</b>\n<b>Password: another-test-password</b></blockquote>',text)
        self.assertNotIn('generated-test-user',text)

    def test_membership_uses_purchased_plan_and_the_identical_guide(self):
        text=membership_ready_text({'name':'3 months','detail':'2 connections · No adult content'},
                                   {'username':'test-member','password':'test-member-password'})
        self.assertEqual(text,'<blockquote><u>Membership — 3 months</u>\n2 connections · No adult content\n\n'
                         '<b>Username: test-member</b>\n<b>Password: test-member-password</b></blockquote>\n\n'+APP_DOWNLOAD_GUIDE)

    def test_credentials_and_plan_names_are_html_escaped(self):
        text=trial_ready_text({'username':'a<b>&c','password':'p"q'})
        self.assertIn('<b>Username: a&lt;b&gt;&amp;c</b>',text)
        self.assertNotIn('a<b>&c',text)
        text=membership_ready_text({'name':'1 <month>','detail':'x & y'},{'username':'u','password':'p'})
        self.assertTrue(text.startswith('<blockquote><u>Membership — 1 &lt;month&gt;</u>\nx &amp; y'))
