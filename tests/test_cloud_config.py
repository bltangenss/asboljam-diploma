"""Render + Cloudflare Pages + Supabase configuration stays secret-free and valid.

These checks read files and validate settings only; they do not contact Render,
Cloudflare or Supabase and do not prove a deployment.
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from apps.api.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
RENDER = (ROOT / 'render.yaml').read_text(encoding='utf-8')


def render_env():
    pairs, key = {}, None
    for line in RENDER.splitlines():
        found = re.match(r'\s*- key: (\S+)\s*$', line)
        if found:
            key = found.group(1)
            pairs[key] = None
            continue
        found = re.match(r'\s*(value|sync): (.+?)\s*$', line)
        if found and key:
            pairs[key] = (found.group(1), found.group(2).strip('"'))
    return pairs


class CloudConfigTests(unittest.TestCase):
    def test_secrets_and_origin_are_entered_in_the_dashboard(self):
        env = render_env()
        self.assertEqual(env['DATABASE_URL'], ('sync', 'false'))
        self.assertEqual(env['ALLOWED_ORIGINS'], ('sync', 'false'))
        self.assertEqual(env['ASBOLJAM_ENV'], ('value', 'production'))
        self.assertEqual(env['COOKIE_SECURE'], ('value', 'true'))
        self.assertNotIn('DEMO_PASSWORD', env)
        settings = '\n'.join(line for line in RENDER.splitlines() if not line.lstrip().startswith('#'))
        self.assertNotRegex(settings, r'postgres(ql)?://|onrender\.com|pages\.dev|supabase\.co')

    def test_render_settings_validate_with_a_pooler_url_and_pages_origin(self):
        env = {k: v[1] for k, v in render_env().items() if v and v[0] == 'value'}
        env['ALLOWED_ORIGINS'] = 'https://predas.pages.dev'
        env['DATABASE_URL'] = ('postgresql://postgres.abcdefghijklmnop:example-only-not-a-secret@'
                               'aws-0-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require')
        settings = load_settings(environ=env)
        self.assertEqual(settings.environment, 'production')
        self.assertEqual(settings.allowed_origins, ('https://predas.pages.dev',))
        self.assertTrue(settings.cookie_secure)

    def test_native_python_service_uses_the_locked_dependencies_and_start_script(self):
        self.assertIn('runtime: python', RENDER)
        self.assertIn('buildCommand: pip install -r requirements.lock', RENDER)
        self.assertIn('startCommand: sh infra/render_start.sh', RENDER)
        self.assertEqual(render_env()['PYTHON_VERSION'][1].rsplit('.', 1)[0], '3.13')
        self.assertIn('Python 3.13', (ROOT / 'requirements.lock').read_text(encoding='utf-8').splitlines()[0])

    def test_start_script_is_shipped_and_uses_render_port(self):
        dockerfile = (ROOT / 'infra/Dockerfile.api').read_text(encoding='utf-8')
        self.assertIn('infra/render_start.sh ./infra/render_start.sh', dockerfile)
        script = (ROOT / 'infra/render_start.sh').read_bytes()
        self.assertNotIn(b'\r\n', script)
        self.assertIn(b'python -m apps.worker.main', script)
        self.assertIn(b'--port "${PORT:-8000}"', script)

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_pages_worker_proxies_only_api_paths(self):
        result = subprocess.run(['node', 'tests/pages_worker_check.mjs'], cwd=ROOT, capture_output=True,
                                text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn('pages worker checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
