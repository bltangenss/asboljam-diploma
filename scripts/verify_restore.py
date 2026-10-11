"""Restore drill: compare a restored database with its running source over HTTP.

SQLite (default): the script creates a verified backup and a separate restored copy of
--source-database with scripts/backup_db.py. PostgreSQL or another operator-made copy:
restore the dump into a NEW database first (pg_restore), then pass its URL only through
the RESTORED_DATABASE_URL environment variable and use --restored-from-environment.

The source API must be quiet (no imports, decisions or worker jobs) from the backup
until the end of the drill. The script logs in as an administrator, reads plans,
approved/rejected CSV exports, runs, audit, users, import history and operational CSV
exports, re-reads the source to prove it did not change, then starts a temporary API
(no worker) on the restored database and compares the same reads.

Expected difference: each login appends one session.login audit row. The source
login happens before the backup, so the restored copy must contain exactly one
extra audit row: its own login. Nothing else may differ. Passwords come from the
environment or --env-file and are never printed or written to the report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.backup_db import copy_database  # noqa: E402

EXPORT_KINDS = ('branches', 'meals', 'ingredients', 'recipes', 'suppliers', 'supplier_offers',
                'calendar', 'sales', 'inventory')


class DrillFailure(Exception):
    """Author-written, sanitized message only."""


def read_password(env_file: Path | None) -> str:
    if os.environ.get('DEMO_PASSWORD'):
        return os.environ['DEMO_PASSWORD']
    if env_file is not None and env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            name, separator, value = line.strip().partition('=')
            if separator and name.strip() == 'DEMO_PASSWORD' and value.strip().strip('"').strip("'"):
                return value.strip().strip('"').strip("'")
    raise DrillFailure('DEMO_PASSWORD unavailable in environment or env file')


class Client:
    def __init__(self, base: str, origin: str):
        self.base, self.origin = base.rstrip('/'), origin
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, payload=None, *, raw=False):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {'Origin': self.origin, **({'Content-Type': 'application/json'} if data else {})}
        try:
            with self.opener.open(Request(self.base + path, data=data, method=method, headers=headers), timeout=60) as response:
                body = response.read()
                return body if raw else json.loads(body)
        except HTTPError as error:
            raise DrillFailure(f'{method} {path.split("?")[0]} returned HTTP {error.code}') from None
        except URLError:
            raise DrillFailure(f'{method} {path.split("?")[0]} is unreachable') from None

    def login(self, email: str, password: str):
        self.call('POST', '/session/login', {'email': email, 'password': password})

    def pages(self, path: str, limit: int, drop=()):
        items, cursor = [], '0'
        separator = '&' if '?' in path else '?'
        while cursor is not None:
            page = self.call('GET', f'{path}{separator}limit={limit}&cursor={cursor}')
            items.extend({k: v for k, v in item.items() if k not in drop} for item in page['items'])
            cursor = page.get('next_cursor')
        return items


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(client: Client) -> dict:
    branches = client.call('GET', '/branches')['items']
    ids = sorted(row['branch_id'] for row in branches)
    plans = {b: client.pages(f'/plans?branch_id={b}', 200) for b in ids}
    return {
        'branches': branches,
        'users': sorted(client.call('GET', '/users')['items'], key=lambda row: row['id']),
        'plans': plans,
        'plan_exports': {plan['id']: digest(client.call('GET', f'/plans/{plan["id"]}/export', raw=True))
                         for rows in plans.values() for plan in rows if plan['status'] in {'approved', 'rejected'}},
        'runs': {f'{b}:{kind}': client.pages(f'/runs?branch_id={b}&kind={kind}', 50, drop=('observed_at',))
                 for b in ids for kind in ('forecast', 'procurement')},
        'audit': {row['id']: row for row in client.pages('/audit', 200)},
        'imports': client.pages('/imports', 200),
        'exports': {kind: digest(client.call('GET', f'/exports/{kind}', raw=True)) for kind in EXPORT_KINDS},
    }


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def compare(source: dict, restored: dict, *, source_login_after_backup: bool = False) -> dict:
    """Every read must match; audit may differ only by the drill's own logins.

    The restored API's login adds one session.login row. When the backup was made
    before the drill (operator-restored database), the drill's source login is also
    absent from the copy: exactly one source-only session.login row is then allowed.
    """
    checks = {}
    for key in ('branches', 'users', 'plans', 'plan_exports', 'runs', 'imports', 'exports'):
        checks[key + '_identical'] = source[key] == restored[key]
    extra = [restored['audit'][key] for key in restored['audit'].keys() - source['audit'].keys()]
    missing = [source['audit'][key] for key in source['audit'].keys() - restored['audit'].keys()]
    checks['audit_common_rows_identical'] = all(
        restored['audit'][key] == row for key, row in source['audit'].items() if key in restored['audit'])
    if source_login_after_backup:
        checks['audit_only_drill_source_login_missing'] = len(missing) == 1 and missing[0]['action'] == 'session.login'
    else:
        checks['audit_no_source_rows_missing'] = not missing
    checks['audit_only_restored_login_added'] = len(extra) == 1 and extra[0]['action'] == 'session.login'
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source-api', default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--source-database', type=Path, default=ROOT / 'data' / 'asboljam.sqlite')
    parser.add_argument('--web-origin', default='http://localhost:3000')
    parser.add_argument('--admin-email', default='admin@asboljam.local')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--restored-from-environment', action='store_true',
                        help='Use RESTORED_DATABASE_URL (an operator-restored NEW database) instead of a SQLite backup')
    parser.add_argument('--work-dir', type=Path, help='New directory for backup/restored files (default: new .cache/restore-drill-*)')
    parser.add_argument('--report', type=Path, help='New JSON report path; existing files are never overwritten')
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error('Report path already exists; choose a new file')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    work = args.work_dir or ROOT / '.cache' / f'restore-drill-{stamp}'
    work.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'source_api': args.source_api, 'work_dir': str(work), 'checks': {}}
    process, log = None, None
    try:
        password = read_password(args.env_file)
        source = Client(args.source_api, args.web_origin)
        source.login(args.admin_email, password)
        before = snapshot(source)
        if args.restored_from_environment:
            restored_url = os.environ.get('RESTORED_DATABASE_URL', '')
            if not restored_url:
                raise DrillFailure('RESTORED_DATABASE_URL is not set')
            report['mode'] = 'operator_restored_database'
        else:
            backup = copy_database(args.source_database, work / 'backup.sqlite', 'backup')
            restored_file = copy_database(work / 'backup.sqlite', work / 'restored.sqlite', 'restore')
            restored_url = 'sqlite:///' + (work / 'restored.sqlite').resolve().as_posix()
            report['mode'] = 'sqlite_backup_and_restore'
            report['backup'] = {key: backup[key] for key in ('sha256', 'integrity_check', 'foreign_key_check', 'table_rows')}
            report['restore'] = {key: restored_file[key] for key in ('sha256', 'integrity_check', 'foreign_key_check', 'table_rows')}
            report['checks']['restored_table_rows_equal_backup'] = restored_file['table_rows'] == backup['table_rows']
        after = snapshot(source)
        report['checks']['source_unchanged_during_drill'] = before == after
        if before != after:
            raise DrillFailure('Source changed during the drill; stop imports, decisions and workers and repeat')
        port = free_port()
        env = {key: value for key, value in os.environ.items()
               if key not in {'DATABASE_URL', 'POSTGRES_PASSWORD', 'RESTORED_DATABASE_URL'}}
        # A temporary local verification API: no worker, loopback only, not a deployment.
        env.update({'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false', 'ALLOWED_ORIGINS': args.web_origin,
                    'DATABASE_URL': restored_url})
        log = open(work / 'restored-api.log', 'wb')
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'uvicorn', 'apps.api.main:app', '--host', '127.0.0.1',
                                    '--port', str(port), '--no-access-log'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        restored = Client(f'http://127.0.0.1:{port}/api/v1', args.web_origin)
        deadline = time.monotonic() + 90
        while True:
            try:
                if restored.call('GET', '/ready') == {'status': 'ready'}:
                    break
            except DrillFailure:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                raise DrillFailure('Restored API did not become ready')
            time.sleep(0.5)
        report['checks']['restored_api_ready_with_expected_schema'] = True
        restored.login(args.admin_email, password)
        report['checks']['restored_admin_login'] = True
        report['checks'].update(compare(before, snapshot(restored), source_login_after_backup=args.restored_from_environment))
        report['counts'] = {'branches': len(before['branches']), 'plans': sum(map(len, before['plans'].values())),
                            'decided_plan_exports': len(before['plan_exports']), 'audit_rows': len(before['audit']),
                            'runs': sum(map(len, before['runs'].values())), 'import_batches': len(before['imports']),
                            'csv_exports': len(before['exports'])}
        report['status'] = 'passed' if all(report['checks'].values()) else 'failed'
    except DrillFailure as error:
        report.update(status='failed', failure=str(error))
    except Exception as error:  # Never print response bodies, SQL or credentials.
        report.update(status='failed', failure='Unexpected ' + type(error).__name__)
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        if log is not None:
            log.close()
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with open(args.report, 'x', encoding='utf-8', newline='\n') as handle:
                handle.write(text + '\n')
        print(text)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
