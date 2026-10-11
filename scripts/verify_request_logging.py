"""Run a real Uvicorn API process on an isolated SQLite store and inspect its logs.

The verifier checks the launch flags used by start/cloud/Docker (`--no-access-log`):
server-generated request IDs, allowlisted JSON events, a sanitized middleware 500 and
no raw path/query/body/header values in stdout/stderr. A control run without the flag
shows what Uvicorn's own access log would otherwise record. Nothing outside a new
ignored .cache directory is written, and no existing database is opened.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = 'runtime-private-logging-sentinel'
ORIGIN = 'http://localhost:3000'


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def request(base, path, *, method='GET', body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        **({'Content-Type': 'application/json'} if data is not None else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def run_server(directory, *, access_log, calls):
    port = free_port()
    env = {key: value for key, value in os.environ.items()
           if key not in {'DATABASE_URL', 'DEMO_PASSWORD', 'POSTGRES_PASSWORD'}}
    env.update({'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false', 'ALLOWED_ORIGINS': ORIGIN,
                'DATABASE_URL': 'sqlite:///' + (directory / 'runtime.sqlite').as_posix(),
                'PYTHONUNBUFFERED': '1'})
    command = [sys.executable, '-X', 'utf8', '-m', 'uvicorn', 'tests.request_logging_runtime_app:app',
               '--host', '127.0.0.1', '--port', str(port)] + ([] if access_log else ['--no-access-log'])
    stdout_path, stderr_path = directory / f'stdout-{port}.log', directory / f'stderr-{port}.log'
    with open(stdout_path, 'wb') as stdout, open(stderr_path, 'wb') as stderr:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        base = f'http://127.0.0.1:{port}'
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    if request(base, '/api/v1/health')[0] == 200:
                        break
                except OSError:
                    pass
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Runtime API did not become healthy')
                time.sleep(0.25)
            results = [request(base, *call[0], **call[1]) for call in calls]
            time.sleep(0.5)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
    return command, results, stdout_path.read_text(encoding='utf-8', errors='replace'), \
        stderr_path.read_text(encoding='utf-8', errors='replace')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', help='New JSON report path; an existing file is never overwritten')
    args = parser.parse_args()
    if args.report and Path(args.report).exists():
        raise SystemExit('Report path already exists; choose a new file.')
    (ROOT / '.cache').mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='request-logging-runtime-', dir=ROOT / '.cache'))
    calls = [
        (('/api/v1/health?token=' + SENTINEL,), {'headers': {'X-Request-ID': 'spoof-' + SENTINEL}}),
        (('/api/v1/runs/' + SENTINEL + '?q=' + SENTINEL,), {}),
        (('/api/v1/session/login',), {'method': 'POST', 'body': {'email': 'a@b.c', 'password': SENTINEL}}),
        (('/api/v1/' + SENTINEL + '/missing',), {}),
        (('/verify/fail/' + SENTINEL + '?csv=' + SENTINEL,), {'headers': {'Origin': ORIGIN}}),
    ]
    command, results, stdout, stderr = run_server(directory, access_log=False, calls=calls)
    events = [json.loads(line) for line in stdout.splitlines() if line.startswith('{')]
    request_events = [event for event in events if event['event'] == 'http.request']
    statuses = [result[0] for result in results]
    ids = [result[1].get('x-request-id') or result[1].get('X-Request-ID') for result in results]
    failure_headers = {key.lower(): value for key, value in results[-1][1].items()}
    other_stdout = [line for line in stdout.splitlines() if line and not line.startswith('{')]
    checks = {
        'statuses_200_401_403_404_500': statuses == [200, 401, 403, 404, 500],
        'one_server_id_per_response': all(isinstance(i, str) and len(i) == 32 and 'spoof' not in i for i in ids)
            and len(set(ids)) == len(ids),
        'events_match_response_ids_in_order': [e['request_id'] for e in request_events[-len(calls):]] == ids,
        'route_templates_only': [e['route'] for e in request_events[-len(calls):]] == [
            '/api/v1/health', '/api/v1/runs/{run_id}', '/api/v1/session/login', 'unmatched', '/verify/fail/{item_id}'],
        'failure_event_code': request_events[-1].get('code') == 'HTTP_REQUEST_FAILED' and request_events[-1]['status'] == 500,
        'failure_cors_and_exposed_id': failure_headers.get('access-control-allow-origin') == ORIGIN
            and 'x-request-id' in failure_headers.get('access-control-expose-headers', '').lower(),
        'no_sentinel_in_stdout_stderr': SENTINEL not in stdout + stderr,
        'no_access_log_lines': 'HTTP/1.1"' not in stdout + stderr,
        'only_json_events_on_stdout': other_stdout == [],
        'sanitized_asgi_error_signal': 'Exception in ASGI application' in stderr
            and 'RuntimeError: HTTP_REQUEST_FAILED' in stderr and 'IntegrityError' not in stderr
            and 'INSERT' not in stderr,
    }
    control_command, _, control_stdout, control_stderr = run_server(
        directory, access_log=True, calls=[(('/api/v1/health?token=' + SENTINEL,), {})])
    control = {'uvicorn_access_log_records_raw_query_without_flag':
               SENTINEL in control_stdout + control_stderr}
    report = {
        'status': 'passed' if all(checks.values()) and all(control.values()) else 'failed',
        'verified_at_utc': datetime.now(timezone.utc).isoformat(),
        'command': ' '.join(Path(part).name if part == sys.executable else part for part in command),
        'control_command': ' '.join(Path(part).name if part == sys.executable else part for part in control_command),
        'python': sys.version.split()[0],
        'checks': checks,
        'control': control,
        'events_seen': len(events),
        'runtime_directory': directory.relative_to(ROOT).as_posix(),
        'not_tested': ['Nginx/Docker runtime log format', 'PostgreSQL backend', 'log shipping, rotation and retention'],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        with open(args.report, 'x', encoding='utf-8', newline='\n') as handle:
            handle.write(text + '\n')
    print(text)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
