"""Every API refusal a web user can see has Kazakh and Russian text in the web copy.

API messages are written in Kazakh; without a copy entry the Russian interface would
show Kazakh text (general pages) or only a generic message with the code (stock pages).
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GENERAL_SOURCES = ('main.py', 'data_policy.py', 'import_service.py', 'importing.py', 'accounts.py', 'lineage.py', 'production.py',
                   'places_api.py', 'factor_builder.py', 'weather.py')
STOCK_SOURCES = ('stock.py', 'stock_service.py', 'stock_api.py', 'stock_recipes.py', 'stock_dependencies.py')
CODE = re.compile(r"""['"]([A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+)['"]""")
# Codes that never reach the web interface as a refusal: operator CLIs, setting names,
# readiness probes, native bearer-token flows, job codes and dashboard counters with own copy.
NOT_WEB = {
    'ACCOUNT_NOT_FOUND', 'OPERATOR_INVALID', 'REASON_REQUIRED', 'RECOVERY_METADATA_INVALID',
    'ALLOWED_ORIGINS', 'ASBOLJAM_ENV', 'COOKIE_SECURE', 'DATABASE_URL', 'DEMO_PASSWORD',
    'IMPORT_MAX_BYTES', 'IMPORT_MAX_ROWS', 'DATABASE_UNAVAILABLE', 'MIGRATION_REQUIRED',
    'NATIVE_REAL_UNSUPPORTED', 'NATIVE_STOCK_UNSUPPORTED', 'REFRESH_INVALID', 'REFRESH_REUSED',
    'EXPIRED_LOTS', 'EXPIRING_LOTS', 'DEMO_ORIGIN', 'DEMO_TARGET',
    'ASBOLJAM_SELF_REGISTRATION', 'WEATHER_PROVIDER', 'WEATHER_API_KEY', 'WEATHER_FORECAST_URL', 'WEATHER_ARCHIVE_URL',
}
KAZAKH_ONLY = re.compile('[әғқңөұүһіӘҒҚҢӨҰҮҺІ]')


def codes(files, prefix=None):
    found = set()
    for name in files:
        path = ROOT / 'apps' / 'api' / name
        if path.exists():
            found |= set(CODE.findall(path.read_text(encoding='utf-8')))
    found -= NOT_WEB
    found = {code for code in found if not code.startswith('JOB_')}
    return {code for code in found if prefix is None or code.startswith(prefix)}


def entries(path, key_prefix):
    text = (ROOT / path).read_text(encoding='utf-8')
    pairs = re.findall(r"""(?m)^\s*""" + key_prefix + r"""([A-Z][A-Z0-9_]+):\['([^']*)','([^']*)'\]""", text)
    return {code: (kk, ru) for code, kk, ru in pairs}


class UiCopyTests(unittest.TestCase):
    def assert_translated(self, required, translations):
        missing = sorted(required - translations.keys())
        self.assertEqual(missing, [], 'Add KK/RU copy for these API codes')
        for code in sorted(required):
            kk, ru = translations[code]
            with self.subTest(code=code):
                self.assertTrue(kk.strip() and ru.strip())
                self.assertNotEqual(kk, ru)
                self.assertIsNone(KAZAKH_ONLY.search(ru), 'Russian text contains Kazakh-only letters')

    def test_general_api_refusals_have_kazakh_and_russian_copy(self):
        general = codes(GENERAL_SOURCES) - {code for code in codes(GENERAL_SOURCES) if code.startswith('STOCK_')}
        self.assertGreater(len(general), 60)
        self.assert_translated(general, entries('apps/web/src/shared.tsx', 'error_'))

    def test_stock_refusals_have_kazakh_and_russian_copy(self):
        stock = codes(STOCK_SOURCES + GENERAL_SOURCES, 'STOCK_')
        self.assertGreater(len(stock), 50)
        # Stock pages use stockCopy; stock refusals raised during procurement reach ErrorBox (error_ keys).
        self.assert_translated(stock, {**entries('apps/web/src/shared.tsx', 'error_'), **entries('apps/web/src/stockCopy.ts', '')})


if __name__ == '__main__':
    unittest.main()
