"""Deployment configuration boundaries, using no network or operational database."""
import os
import unittest
from unittest.mock import patch

from apps.api.config import ConfigurationError, LOCAL_ORIGINS, load_settings


class ConfigurationTests(unittest.TestCase):
    def production(self, **overrides):
        return {
            'ASBOLJAM_ENV': 'production',
            'ALLOWED_ORIGINS': 'https://app.example.org',
            'COOKIE_SECURE': 'true',
            'DATABASE_URL': 'postgresql+psycopg://operator@database/asboljam',
            **overrides,
        }

    def test_local_defaults_preserve_demo(self):
        settings = load_settings(environ={})
        self.assertEqual(settings.environment, 'local')
        self.assertEqual(settings.allowed_origins, LOCAL_ORIGINS)
        self.assertFalse(settings.cookie_secure)
        self.assertIsNone(settings.database_url)

    def test_unknown_and_empty_environment_fail_closed(self):
        for mode in ('', 'prod', 'development', 'productionn'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ConfigurationError, 'ASBOLJAM_ENV'):
                load_settings(environ={'ASBOLJAM_ENV': mode})

    def test_explicit_local_origin_and_boolean_parsing(self):
        settings = load_settings(environ={
            'COOKIE_SECURE': 'TRUE',
            'ALLOWED_ORIGINS': ' http://localhost:3010 ,http://[::1]:3000,http://localhost:3010',
        })
        self.assertTrue(settings.cookie_secure)
        self.assertEqual(settings.allowed_origins, ('http://localhost:3010', 'http://[::1]:3000'))
        for value in ('', '1', 'yes', 'falsee', 'false,true'):
            with self.subTest(value=value), self.assertRaisesRegex(ConfigurationError, 'COOKIE_SECURE'):
                load_settings(environ={'COOKIE_SECURE': value})

    def test_origin_serialization_matches_browser_default_ports_and_host_case(self):
        settings = load_settings(environ=self.production(ALLOWED_ORIGINS='https://APP.example.org:443,https://app.example.org,https://[0:0::1]:443'))
        self.assertEqual(settings.allowed_origins, ('https://app.example.org', 'https://[::1]'))

    def test_malformed_origins_fail_in_both_modes(self):
        invalid = (
            '', '*', 'null', 'https://*.example.org', 'https://example.org/',
            'https://example.org/path', 'https://example.org?next=x', 'https://example.org?',
            'https://example.org#fragment', 'https://example.org#',
            'https://person:private@example.org', 'https://person@example.org',
            'https://example.org:wrong', 'https://example.org:65536', 'https://example.org:0',
            'https://example.org:', 'https://[invalid]', 'https://[::1]junk', 'https://bad host.example',
            'https://example.org\\evil', 'https://example.org%2f.evil', 'https://-bad.example',
            'ftp://example.org', 'example.org', 'https://example.org,', ',https://example.org',
        )
        for mode in ('local', 'production'):
            for origin in invalid:
                with self.subTest(mode=mode, origin=origin), self.assertRaisesRegex(ConfigurationError, 'ALLOWED_ORIGINS'):
                    load_settings(environ=self.production(ASBOLJAM_ENV=mode, ALLOWED_ORIGINS=origin))

    def test_production_needs_explicit_origins(self):
        env = self.production()
        del env['ALLOWED_ORIGINS']
        with self.assertRaisesRegex(ConfigurationError, 'explicit ALLOWED_ORIGINS'):
            load_settings(environ=env)

    def test_production_rejects_http_even_in_mixed_origins(self):
        for origins in ('http://localhost:3000', 'https://app.example.org,http://other.example.org'):
            with self.subTest(origins=origins), self.assertRaisesRegex(ConfigurationError, 'HTTPS'):
                load_settings(environ=self.production(ALLOWED_ORIGINS=origins))

    def test_production_needs_secure_cookies(self):
        for value in (None, 'false'):
            env = self.production()
            if value is None:
                del env['COOKIE_SECURE']
            else:
                env['COOKIE_SECURE'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ConfigurationError, 'COOKIE_SECURE'):
                load_settings(environ=env)

    def test_production_rejects_demo_credentials(self):
        with self.assertRaisesRegex(ConfigurationError, 'DEMO_PASSWORD'):
            load_settings(environ=self.production(DEMO_PASSWORD='only-a-test-fixture'))
        self.assertEqual(load_settings(environ=self.production(DEMO_PASSWORD='')).environment, 'production')

    def test_production_requires_explicit_postgresql(self):
        env = self.production()
        del env['DATABASE_URL']
        with self.assertRaisesRegex(ConfigurationError, 'DATABASE_URL'):
            load_settings(environ=env)
        for url in ('sqlite://', 'sqlite:///:memory:', 'sqlite:///data/explicit.sqlite'):
            with self.subTest(url=url), self.assertRaisesRegex(ConfigurationError, 'PostgreSQL'):
                load_settings(environ=self.production(DATABASE_URL=url))

    def test_invalid_database_settings_do_not_fallback(self):
        for url in ('', ' ', 'not-a-url', 'mysql://host/db', 'postgresql://host', 'postgresql://host:notaport/db', 'postgresql://host:0/db', 'postgresql://host:65536/db'):
            with self.subTest(url=url), self.assertRaisesRegex(ConfigurationError, 'DATABASE_URL'):
                load_settings(environ={'DATABASE_URL': url})

    def test_explicit_database_override_is_validated(self):
        settings = load_settings(database_url='sqlite:///:memory:', environ={'DATABASE_URL': 'invalid'})
        self.assertEqual(settings.database_url, 'sqlite:///:memory:')
        with self.assertRaisesRegex(ConfigurationError, 'PostgreSQL'):
            load_settings(database_url='sqlite:///:memory:', environ=self.production())

    def test_placeholder_password_is_rejected_after_url_decoding(self):
        for password in ('', 'password', 'POSTGRES', '%63hangeme', 'URL_ENCODED_PASSWORD'):
            with self.subTest(password=password), self.assertRaisesRegex(ConfigurationError, 'placeholder password'):
                load_settings(environ=self.production(DATABASE_URL=f'postgresql://operator:{password}@database/asboljam'))
        for query in ('password=changeme', 'password=%63hangeme', 'password=private-fixture&password=changeme'):
            with self.subTest(query=query), self.assertRaisesRegex(ConfigurationError, 'placeholder password'):
                load_settings(environ=self.production(DATABASE_URL=f'postgresql://operator@database/asboljam?{query}'))

    def test_postgresql_without_inline_password_is_allowed(self):
        for url in ('postgresql://operator@database/asboljam', 'postgresql+psycopg:///asboljam?host=/var/run/postgresql'):
            with self.subTest(url=url):
                self.assertEqual(load_settings(environ=self.production(DATABASE_URL=url)).database_url, url)

    def test_environment_mapping_is_optional_and_not_mutated(self):
        env = self.production()
        before = dict(env)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(load_settings().environment, 'production')
        self.assertEqual(env, before)

    def test_error_and_settings_repr_do_not_expose_values(self):
        marker = 'private-fixture-value'
        settings = load_settings(environ=self.production(DATABASE_URL=f'postgresql://operator:{marker}@database/asboljam'))
        self.assertNotIn(marker, repr(settings))
        for env in (
            self.production(DATABASE_URL=f'invalid://operator:{marker}@database/asboljam'),
            self.production(ALLOWED_ORIGINS=f'https://operator:{marker}@app.example.org'),
            self.production(DEMO_PASSWORD=marker),
        ):
            with self.subTest(keys=tuple(env)):
                try:
                    load_settings(environ=env)
                except ConfigurationError as exc:
                    self.assertNotIn(marker, str(exc))
                    self.assertNotIn(marker, repr(exc))
                else:
                    self.fail('Expected unsafe configuration to fail')


if __name__ == '__main__':
    unittest.main()
