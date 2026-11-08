import unittest

from replit_start import prepare_environment


class ReplitEnvironmentTests(unittest.TestCase):
    def test_demo_does_not_consume_live_database_or_encryption_key(self):
        source = {
            'STREAMBOT_MODE': 'demo',
            'STREAMBOT_DATABASE_URL': 'postgresql://example.invalid/live',
            'STREAMBOT_CREDENTIAL_KEY': 'fake-live-key',
            'REPLIT_DEV_DOMAIN': 'example.replit.dev',
        }
        env = prepare_environment(source)
        self.assertEqual(env['STREAMBOT_DATABASE_URL'], '')
        self.assertEqual(env['CREDENTIAL_KEY'], '')
        self.assertEqual(env['DATABASE_PATH'], 'data/demo.sqlite3')
        self.assertEqual(source['STREAMBOT_CREDENTIAL_KEY'], 'fake-live-key')

    def test_live_keeps_explicit_database_key_and_verified_origin(self):
        source = {
            'STREAMBOT_MODE': 'live',
            'STREAMBOT_DATABASE_URL': 'postgresql://example.invalid/live',
            'STREAMBOT_CREDENTIAL_KEY': 'fake-live-key',
            'STREAMBOT_PUBLIC_URL': 'https://checkout.example.com',
        }
        env = prepare_environment(source)
        self.assertEqual(env['STREAMBOT_DATABASE_URL'], source['STREAMBOT_DATABASE_URL'])
        self.assertEqual(env['CREDENTIAL_KEY'], source['STREAMBOT_CREDENTIAL_KEY'])
        self.assertEqual(env['PUBLIC_URL'], source['STREAMBOT_PUBLIC_URL'])

    def test_live_requires_explicit_origin(self):
        with self.assertRaises(ValueError):
            prepare_environment({'STREAMBOT_MODE': 'live'})

    def test_managed_live_uses_runtime_database_not_copied_development_url(self):
        source = {
            'STREAMBOT_MODE': 'live',
            'STREAMBOT_PUBLIC_URL': 'https://checkout.example.com',
            'STREAMBOT_DATABASE_SOURCE': 'managed',
            'STREAMBOT_DATABASE_URL': 'postgresql://example.invalid/copied-development',
            'DATABASE_URL': 'postgresql://example.invalid/production',
        }
        env = prepare_environment(source)
        self.assertEqual(env['STREAMBOT_DATABASE_URL'], source['DATABASE_URL'])
        self.assertEqual(source['STREAMBOT_DATABASE_URL'], 'postgresql://example.invalid/copied-development')

    def test_managed_live_fails_when_runtime_database_is_missing(self):
        with self.assertRaises(ValueError):
            prepare_environment({
                'STREAMBOT_MODE': 'live',
                'STREAMBOT_PUBLIC_URL': 'https://checkout.example.com',
                'STREAMBOT_DATABASE_SOURCE': 'managed',
            })
