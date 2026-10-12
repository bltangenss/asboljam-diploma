"""Fixes from the 12.10.2026 security review: CSV export, import bounds, proxy trust, login timing, audit privacy.

Importing apps.api.main creates the default application; run with an isolated DATABASE_URL.
"""
import asyncio
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from apps.api import main as api_main
from apps.api.db import Organization, User
from apps.api.importing import parse_csv, safe_csv
from apps.api.security import password_hash

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'Hardening-fixture-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class ExportAndImportBoundsTests(unittest.TestCase):
    def test_negative_numbers_stay_numeric_while_formulas_are_neutralized(self):
        text = safe_csv([{'temperature_forecast_c': '-6.6', 'delta': '-12', 'tiny': '-1E-7',
                          'formula': '-1+2', 'command': '=HYPERLINK("x")', 'spaced': ' -5'}])
        row = text.splitlines()[1]
        self.assertTrue(row.startswith('-6.6,-12,-1E-7,'), row)
        self.assertIn("'-1+2", row)
        self.assertIn("'=HYPERLINK", row)
        self.assertIn("' -5", row)

    def test_decimal_values_are_limited_to_nine_decimal_places(self):
        header = 'meal_id,ingredient_id,net_qty_per_portion,recipe_version,data_origin\n'
        for value, valid in (('0.000000001', True), ('0.12', True), ('2300.0', True),
                             ('0.0000000001', False), ('1E-999999999', False)):
            with self.subTest(value=value):
                _, errors = parse_csv('recipes', header + f'1,1,{value},V1,SYNTHETIC\n')
                self.assertEqual(not errors, valid, errors)


class ProxyTrustTests(unittest.TestCase):
    def client_seen(self, peer, forwarded_for):
        compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        trusted = re.search(r'FORWARDED_ALLOW_IPS: "([^"]+)"', compose).group(1)
        seen = {}

        async def app(scope, receive, send):
            seen['client'] = scope['client'][0]
        scope = {'type': 'http', 'scheme': 'http', 'client': (peer, 40000),
                 'headers': [(b'x-forwarded-for', forwarded_for.encode())]}
        asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
        return seen['client']

    def test_login_limit_sees_the_real_client_behind_the_compose_proxies(self):
        # Caddy sets the client address, nginx appends Caddy's; uvicorn skips the trusted hops.
        self.assertEqual(self.client_seen('172.18.0.4', '203.0.113.7, 172.18.0.5'), '203.0.113.7')

    def test_untrusted_peers_cannot_choose_their_address(self):
        self.assertEqual(self.client_seen('198.51.100.9', '203.0.113.7'), '198.51.100.9')


class AccountPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = api_main.create_app('sqlite:///' + (Path(cls.temp.name) / 'hardening.sqlite').as_posix())
        with cls.app.state.sessions() as db:
            db.add(Organization(id='org', name='Hardening fixture', timezone='Asia/Qyzylorda',
                                data_policy='synthetic_only', provenance='test_fixture'))
            for role in ('admin', 'manager', 'analyst'):
                db.add(User(id=role, organization_id='org', email=role + '@hardening.invalid',
                            password_hash=password_hash(PASSWORD), role=role, branch_ids=['1']))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.app.state.engine.dispose()
        cls.temp.cleanup()

    def login(self, email):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        response = client.post('/api/v1/session/login', json={'email': email, 'password': PASSWORD}, headers=ORIGIN)
        return client, response

    def test_unknown_email_pays_the_same_password_check(self):
        with patch.object(api_main, 'verify_password', wraps=api_main.verify_password) as check:
            _, response = self.login('nobody@hardening.invalid')
        self.assertEqual((response.status_code, response.json()['detail']['code']), (401, 'INVALID_CREDENTIALS'))
        check.assert_called_once()

    def test_only_administrators_see_sign_ins_and_access_changes(self):
        def actions(role):
            client, response = self.login(role + '@hardening.invalid')
            self.assertEqual(response.status_code, 200, response.text)
            return {item['action'] for item in client.get('/api/v1/audit').json()['items']}
        self.assertIn('session.login', actions('admin'))
        for role in ('manager', 'analyst'):
            with self.subTest(role=role):
                self.assertEqual({action for action in actions(role)
                                  if action.startswith(api_main.IDENTITY_AUDIT_PREFIXES)}, set())


if __name__ == '__main__':
    unittest.main()
