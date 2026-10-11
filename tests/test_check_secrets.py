"""The staged secret scan compares local .env values, never their documentation comments."""
from pathlib import Path
import tempfile
import unittest

from scripts import check_secrets


class LocalSecretTests(unittest.TestCase):
    def test_only_credential_assignments_become_known_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # A .env copied from .env.example keeps comments such as "Blank => generated".
            (root / '.env').write_text(
                '# Local-only seed password (12+ characters). Blank => generated/displayed once.\n'
                'DEMO_PASSWORD=fixture-value-not-real-1234\n'
                '  # API_KEY=commented-out-value-1234\n'
                'DEMO_DATASET=kz\nPOSTGRES_PASSWORD=\n', encoding='utf-8')
            (root / '.env.example').write_text('DEMO_PASSWORD=example-value-not-read\n', encoding='utf-8')
            self.assertEqual(check_secrets.local_secrets(root), [('DEMO_PASSWORD', b'fixture-value-not-real-1234')])


if __name__ == '__main__':
    unittest.main()
