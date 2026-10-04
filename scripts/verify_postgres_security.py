"""Run commercial security suites on isolated real PostgreSQL using existing Docker images.

Start the existing local verification PostgreSQL container first. This command creates
one fresh database and one schema per test, retaining them for diagnosis. It never seeds
the existing application database, removes a volume, pulls an image or deploys a service.
"""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote
import uuid


ROOT = Path(__file__).resolve().parents[1]
SUITES = ('test_tenant_isolation.py', 'test_worker_security.py', 'test_password_security.py',
          'test_tenant_migration.py', 'test_tenant_lifecycle.py', 'test_import_migration.py',
          'test_import_transactions.py', 'test_import_lineage.py', 'test_real_source_migration.py',
          'test_real_source.py', 'test_real_execution.py', 'test_real_api.py',
          'test_worker_heartbeat.py', 'test_worker_migration.py', 'test_readiness.py', 'test_worker_shutdown.py')


def source_hashes():
    paths = [*ROOT.glob('apps/api/*.py'), *ROOT.glob('apps/worker/*.py'),
             *ROOT.glob('tests/test_*security.py'), *[ROOT/'tests'/name for name in SUITES],
             ROOT/'tests/database_fixture.py', ROOT/'scripts/pilot_fixture.py', ROOT/'scripts/seed_demo.py', Path(__file__)]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths))}


def inside(suites):
    """Container-only runner: real PostgreSQL fixtures, writable temp cwd, readonly sources."""
    import unittest
    sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    configured = os.environ['ASBOLJAM_SECURITY_TEST_DATABASE_URL']
    url = make_url(configured)
    if url.drivername != 'postgresql+psycopg' or not re.fullmatch(r'asboljam_security_[0-9a-f]{32}', url.database or ''):
        raise SystemExit('Refusing a database outside the isolated security-test namespace.')
    report = {'status': 'running', 'suites': [], 'source_sha256': source_hashes()}
    def test_ids(suite):
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                yield from test_ids(test)
            else:
                yield test.id()
    pure_engine_ids = []
    sqlite_backup_ids = []
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            report['postgres_version'] = connection.execute(text('SELECT version()')).scalar_one()
            report['database_dialect'] = engine.dialect.name
        for pattern in suites:
            started = time.monotonic()
            output = io.StringIO()
            suite = unittest.TestLoader().discover(str(ROOT/'tests'), pattern=pattern)
            identifiers = list(test_ids(suite))
            pure_engine_ids.extend(identifier for identifier in identifiers if identifier.startswith('test_real_execution.RealEngineTests.'))
            sqlite_backup_ids.extend(identifier for identifier in identifiers if 'sqlite' in identifier and 'backup' in identifier)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
            report['suites'].append({
                'pattern': pattern, 'tests_run': result.testsRun, 'failures': len(result.failures),
                'errors': len(result.errors), 'skipped': len(result.skipped),
                'status': 'passed' if result.wasSuccessful() and result.testsRun and not result.skipped else 'failed',
                'elapsed_seconds': round(time.monotonic() - started, 3), 'output': output.getvalue(),
            })
        with engine.connect() as connection:
            report['test_schema_count'] = connection.execute(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name ~ '^test_[0-9a-f]{32}$'")).scalar_one()
        report['source_changed_during_run'] = report['source_sha256'] != source_hashes()
        report['tests_run'] = sum(suite['tests_run'] for suite in report['suites'])
        report['pure_engine_test_ids'] = pure_engine_ids
        report['sqlite_backup_test_ids'] = sqlite_backup_ids
        report['expected_postgres_fixture_setups'] = report['tests_run'] - len(pure_engine_ids)
        report['postgres_test_bodies'] = report['expected_postgres_fixture_setups'] - len(sqlite_backup_ids)
        report['status'] = 'passed' if (all(suite['status'] == 'passed' for suite in report['suites'])
                                        and not report['source_changed_during_run']
                                        and report['test_schema_count'] >= report['expected_postgres_fixture_setups']) else 'failed'
    finally:
        engine.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--suite', action='append', choices=SUITES)
    parser.add_argument('--env-file', type=Path, default=ROOT/'.env.docker.local')
    parser.add_argument('--postgres-container', default='asboljam-verification-postgres-1')
    parser.add_argument('--network', default='asboljam-verification_default')
    parser.add_argument('--image', default='asboljam-verification-api:latest')
    parser.add_argument('--report-name', choices=('postgres-security.json', 'postgres-password-security.json', 'postgres-tenant-platform.json', 'postgres-import-platform.json', 'postgres-real-platform.json', 'postgres-real-worker.json', 'postgres-worker-heartbeat.json', 'postgres-readiness.json', 'postgres-worker-shutdown.json'),
                        default='postgres-security.json')
    args = parser.parse_args()
    suites = args.suite or list(SUITES[:2])
    if args.inside:
        return inside(suites)

    from verify_postgres import load_env
    config = load_env(args.env_file)
    password = config.get('POSTGRES_PASSWORD')
    if not password:
        raise SystemExit('POSTGRES_PASSWORD must be configured privately.')
    started = time.monotonic()
    environment = dict(os.environ)
    database = 'asboljam_security_' + uuid.uuid4().hex
    report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'running',
              'database': database, 'suites_requested': suites,
              'limits': ['Local PostgreSQL in Docker; no production deployment or TLS/load verification.',
                         'Security fixtures use synthetic organizations; forecast calculations are stubbed where the suite specifies.',
                         'Existing operational databases and volumes are preserved; fresh test database/schemas retained.']}

    def safe(value):
        value = value.replace(password, '[REDACTED]').replace(quote(password, safe=''), '[REDACTED]')
        return re.sub(r'(postgresql(?:\+psycopg)?://[^:]+:)[^@]+@', r'\1[REDACTED]@', value)

    def run(command, timeout=45):
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=timeout)
        if result.returncode:
            raise RuntimeError(safe(result.stderr + result.stdout)[-12000:])
        return result.stdout.strip()

    try:
        report['source_commit'] = run(['git', 'rev-parse', 'HEAD'])
        report['working_tree_changes'] = run(['git', 'status', '--porcelain']).splitlines()
        # Inspect pins a local immutable image ID; --pull=never prevents network image pulls.
        image = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image])
        report['image_id'] = image
        report['docker_server_version'] = run(['docker', 'version', '--format', '{{.Server.Version}}'])
        run(['docker', 'exec', args.postgres_container, 'createdb', '-U', 'asboljam', database])
        report['database_created'] = True
        environment['ASBOLJAM_SECURITY_TEST_DATABASE_URL'] = ('postgresql+psycopg://asboljam:'
            + quote(password, safe='') + '@postgres:5432/' + database)
        environment['DATABASE_URL'] = environment['ASBOLJAM_SECURITY_TEST_DATABASE_URL']
        command = ['docker', 'run', '--rm', '--pull=never', '--network', args.network,
                   '--env', 'ASBOLJAM_SECURITY_TEST_DATABASE_URL', '--env', 'DATABASE_URL',
                   '--env', 'ASBOLJAM_ENV=local', '--env', 'COOKIE_SECURE=false',
                   '--env', 'ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000',
                   '--env', 'PYTHONPATH=/workspace:/workspace/tests',
                   '--volume', str(ROOT) + ':/workspace:ro', '--workdir', '/tmp',
                   image, 'python', '/workspace/scripts/verify_postgres_security.py', '--inside']
        for suite in suites:
            command += ['--suite', suite]
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=300)
        # The runner emits only JSON. Preserve structured assertion failures on non-zero exits.
        try:
            inner = json.loads(safe(result.stdout))
        except json.JSONDecodeError:
            raise RuntimeError(safe(result.stderr + result.stdout)[-12000:]) from None
        report.update(inner)
        if result.returncode:
            report['status'] = 'failed'
        if result.stderr:
            report['runner_stderr'] = safe(result.stderr)
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = safe(str(exc))
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    target = ROOT/'artifacts/verification'/args.report_name
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"PostgreSQL security verification: {report['status']}; tests={report.get('tests_run', 0)}")
    print('Report: artifacts/verification/' + args.report_name)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
