"""Exact trial-delivery content, using fake credentials only."""
import unittest

from streambot.trial_message import trial_ready_text, membership_ready_text, APP_DOWNLOAD_GUIDE


class TrialMessageTests(unittest.TestCase):
    def test_exact_layout_codes_links_and_dynamic_credentials(self):
        expected="""24 Hour Trial

Username: generated-test-user
Password: generated-test-password

APP DOWNLOAD CODES

Enter a code in the Downloader app (Firestick):
Sky Live
2976199 • 565410 • 6261787
962396 • 969828

Magic
9801832

Safe Media
589666 • 7400092

iPhone/Apple TV App - viziplayer.com/app
URL Code BA896705

Android APPS
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
        self.assertIn('Username: another-test-user\nPassword: another-test-password',text)
        self.assertNotIn('generated-test-user',text)

    def test_membership_uses_purchased_plan_and_the_identical_guide(self):
        text=membership_ready_text({'name':'3 months','detail':'2 connections · No adult content'},
                                   {'username':'test-member','password':'test-member-password'})
        self.assertEqual(text,'Membership — 3 months\n2 connections · No adult content\n\n'
                         'Username: test-member\nPassword: test-member-password\n\n'+APP_DOWNLOAD_GUIDE)
