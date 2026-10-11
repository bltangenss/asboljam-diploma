"""HTTP correlation logs fixed route templates and outcomes, never request contents."""
import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from apps.api import main as api
from apps.api.db import Audit, Job, User
from apps.api.request_logging import RequestLoggingMiddleware
from apps.api.security import password_hash
from apps.worker import main as worker
from database_fixture import isolated_database_url
from scripts.seed_demo import seed


SECRET = 'private-request-logging-csv-password-token-sentinel'
PASSWORD = 'Request-logging-fixture-2026!'
ALLOWED = 'http://localhost:3000'
FOREIGN = 'https://foreign.example'
EVENT_KEYS = {'schema_version', 'timestamp', 'event', 'request_id', 'method', 'route', 'status',
              'duration_ms', 'code', 'job_id', 'kind', 'claim_time'}


def events(output, name=None):
    rows = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]
    return [row for row in rows if name is None or row['event'] == name]


def is_server_id(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


class Recorder:
    """Outside the whole stack: records every response start the server receives."""

    def __init__(self, app):
        self.app, self.starts = app, []

    async def __call__(self, scope, receive, send):
        async def record(message):
            if message['type'] == 'http.response.start':
                self.starts.append(message['status'])
            await send(message)
        await self.app(scope, receive, record)


class RequestLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
                                          'ALLOWED_ORIGINS': ALLOWED})
        cls.env.start()
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = api.create_app(isolated_database_url(
            'sqlite:///' + (Path(cls.temp.name) / 'request-logging.sqlite').as_posix()))
        cls.factory = cls.app.state.sessions
        seed(cls.factory, PASSWORD)
        with cls.factory() as db:
            db.add(User(id='logging-manager', organization_id='demo', email='manager@logging.invalid',
                        password_hash=password_hash(PASSWORD), role='manager', branch_ids=['1']))
            db.commit()

        # Test-only routes join the same registered route list that labels events.
        @cls.app.get('/test/fail/{item_id}')
        def fail(item_id: str):
            raise IntegrityError('INSERT INTO private VALUES (?) ' + SECRET, {'password': SECRET},
                                 sqlite3.IntegrityError(SECRET))

        @cls.app.get('/test/stream-fail')
        def stream_fail():
            def body():
                yield b'partial'
                raise RuntimeError(SECRET)
            return StreamingResponse(body(), media_type='text/plain')

        @cls.app.get('/test/state')
        def state(request: Request):
            time.sleep(0.02)
            return {'request_id': request.state.request_id}

        @cls.app.get('/test/inner-header')
        def inner_header():
            return Response('ok', headers={'X-Request-ID': 'inner-' + SECRET})

    @classmethod
    def tearDownClass(cls):
        cls.app.state.engine.dispose()
        cls.temp.cleanup()
        cls.env.stop()

    def client(self, *, raise_server_exceptions=True, app=None):
        client = TestClient(app or self.app, raise_server_exceptions=raise_server_exceptions)
        self.addCleanup(client.close)
        return client

    def login(self, email='manager@logging.invalid'):
        client = self.client()
        response = client.post('/api/v1/session/login', json={'email': email, 'password': PASSWORD},
                               headers={'Origin': ALLOWED})
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({'Origin': ALLOWED, 'X-CSRF-Token': response.json()['csrf_token']})
        return client

    def assert_safe(self, text, *extra, rendered_traceback=False):
        for value in (SECRET, PASSWORD, 'INSERT', *(() if rendered_traceback else ('Traceback',)), *extra):
            self.assertNotIn(value, text)
        for row in [json.loads(line) for line in text.splitlines() if line.startswith('{')]:
            self.assertLessEqual(set(row), EVENT_KEYS)

    def test_server_generated_ids_ignore_incoming_and_inner_values(self):
        output = io.StringIO()
        client = self.client()
        with contextlib.redirect_stdout(output):
            spoofed = client.get('/api/v1/health', headers={'X-Request-ID': 'spoof-' + SECRET})
            inner = client.get('/test/inner-header')
            again = client.get('/api/v1/health')
        ids = []
        for response in (spoofed, inner, again):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.headers.get_list('x-request-id')), 1)
            self.assertTrue(is_server_id(response.headers['x-request-id']))
            ids.append(response.headers['x-request-id'])
        self.assertEqual(len(set(ids)), 3)
        logged = events(output, 'http.request')
        self.assertEqual([row['request_id'] for row in logged], ids)
        self.assertEqual([row['route'] for row in logged], ['/api/v1/health', '/test/inner-header', '/api/v1/health'])
        self.assert_safe(output.getvalue(), 'spoof')

    def test_parallel_requests_keep_independent_ids_in_endpoint_header_and_event(self):
        def call(_):
            with TestClient(self.app) as client:
                response = client.get('/test/state')
                return response.headers['x-request-id'], response.json()['request_id']

        output = io.StringIO()
        with contextlib.redirect_stdout(output), ThreadPoolExecutor(max_workers=8) as pool:
            pairs = list(pool.map(call, range(24)))
        self.assertTrue(all(header == seen for header, seen in pairs))
        self.assertEqual(len({header for header, _ in pairs}), 24)
        logged = events(output, 'http.request')
        self.assertEqual({row['request_id'] for row in logged}, {header for header, _ in pairs})
        self.assertTrue(all(row['route'] == '/test/state' and row['status'] == 200 for row in logged))

    def test_route_templates_hide_raw_paths_queries_and_bodies_for_early_and_routed_errors(self):
        client = self.client()
        cases = [
            ('400', lambda: client.post('/api/v1/session/login?token=' + SECRET, content='{}',
                                        headers={'Content-Length': 'not-a-size'}), 400, 'unmatched'),
            ('413', lambda: client.post('/api/v1/session/login', content='{}',
                                        headers={'Content-Length': str(23 * 1024 * 1024)}), 413, 'unmatched'),
            ('401', lambda: client.get('/api/v1/runs/' + SECRET + '?q=' + SECRET), 401, '/api/v1/runs/{run_id}'),
            ('403', lambda: client.post('/api/v1/session/login', json={'email': 'a@b.c', 'password': SECRET}),
             403, '/api/v1/session/login'),
            ('422', lambda: client.post('/api/v1/session/login', json={'email': 'x', 'password': SECRET},
                                        headers={'Origin': ALLOWED}), 422, '/api/v1/session/login'),
            ('404', lambda: client.get('/api/v1/' + SECRET + '/missing?token=' + SECRET), 404, 'unmatched'),
            ('405', lambda: client.delete('/api/v1/branches'), 405, '/api/v1/branches'),
        ]
        for name, request, status, route in cases:
            with self.subTest(name), contextlib.redirect_stdout(io.StringIO()) as output:
                response = request()
                self.assertEqual(response.status_code, status, response.text)
                self.assertTrue(is_server_id(response.headers['x-request-id']))
                self.assertEqual(response.headers['x-frame-options'], 'DENY')
                self.assertEqual(response.headers['cache-control'], 'no-store')
                logged = events(output)
                self.assertEqual(len(logged), 1)
                self.assertEqual({key: logged[0][key] for key in ('event', 'request_id', 'route', 'status')},
                                 {'event': 'http.request', 'request_id': response.headers['x-request-id'],
                                  'route': route, 'status': status})
                self.assertNotIn('code', logged[0])
                self.assertIsInstance(logged[0]['duration_ms'], (int, float))
                self.assert_safe(output.getvalue())

    def test_unhandled_error_before_headers_gets_one_safe_500_and_sanitized_server_signal(self):
        output, errors = io.StringIO(), io.StringIO()
        recorder = Recorder(self.app)
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(RuntimeError) as raised:
                self.client(app=recorder).get('/test/fail/' + SECRET)
            response = self.client(raise_server_exceptions=False).get('/test/fail/' + SECRET + '?csv=' + SECRET)
        exc = raised.exception
        self.assertEqual(str(exc), 'HTTP_REQUEST_FAILED')
        self.assertIsNone(exc.__cause__)
        self.assertTrue(exc.__suppress_context__)
        rendered = ''.join(traceback.format_exception(exc))
        self.assertNotIn('IntegrityError', rendered)
        self.assert_safe(rendered, rendered_traceback=True)
        self.assertEqual(recorder.starts, [500])
        self.assertEqual((response.status_code, response.text), (500, 'Internal Server Error'))
        for header, value in [('x-content-type-options', 'nosniff'), ('x-frame-options', 'DENY'),
                              ('referrer-policy', 'same-origin'), ('cache-control', 'no-store')]:
            self.assertEqual(response.headers[header], value)
        self.assertNotIn('strict-transport-security', response.headers)
        logged = events(output, 'http.request')
        self.assertEqual(len(logged), 2)
        for row in logged:
            self.assertEqual((row['route'], row['status'], row['code']), ('/test/fail/{item_id}', 500, 'HTTP_REQUEST_FAILED'))
        self.assertEqual(logged[1]['request_id'], response.headers['x-request-id'])
        self.assert_safe(output.getvalue() + errors.getvalue() + response.text)

    def test_failure_after_headers_keeps_sent_status_and_never_sends_second_start(self):
        output = io.StringIO()
        recorder = Recorder(self.app)
        with contextlib.redirect_stdout(output), self.assertRaises(RuntimeError) as raised:
            self.client(app=recorder).get('/test/stream-fail')
        self.assertEqual(str(raised.exception), 'HTTP_REQUEST_FAILED')
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertEqual(recorder.starts, [200])
        with contextlib.redirect_stdout(output):
            response = self.client(raise_server_exceptions=False).get('/test/stream-fail')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(is_server_id(response.headers['x-request-id']))
        logged = events(output, 'http.request')
        self.assertEqual([(row['status'], row['code']) for row in logged], [(200, 'HTTP_REQUEST_FAILED')] * 2)
        self.assert_safe(output.getvalue())
        self.assert_safe(''.join(traceback.format_exception(raised.exception)), rendered_traceback=True)

    def test_allowed_origin_reads_request_id_on_success_early_refusal_and_generated_500(self):
        client = self.client(raise_server_exceptions=False)
        with contextlib.redirect_stdout(io.StringIO()):
            responses = {
                'success': client.get('/api/v1/health', headers={'Origin': ALLOWED}),
                'early': client.post('/api/v1/session/login', content='{}', headers={
                    'Origin': ALLOWED, 'Content-Length': str(23 * 1024 * 1024)}),
                'failure': client.get('/test/fail/x', headers={'Origin': ALLOWED}),
                'foreign_failure': client.get('/test/fail/x', headers={'Origin': FOREIGN}),
                'foreign_success': client.get('/api/v1/health', headers={'Origin': FOREIGN}),
                'preflight': client.options('/api/v1/forecasts', headers={
                    'Origin': ALLOWED, 'Access-Control-Request-Method': 'POST'}),
            }
        for name in ('success', 'early', 'failure'):
            with self.subTest(name):
                response = responses[name]
                self.assertEqual(response.headers['access-control-allow-origin'], ALLOWED)
                self.assertEqual(response.headers['access-control-allow-credentials'], 'true')
                self.assertIn('x-request-id', response.headers['access-control-expose-headers'].lower())
                self.assertIn('Origin', response.headers['vary'])
                self.assertTrue(is_server_id(response.headers['x-request-id']))
        self.assertEqual(responses['early'].status_code, 413)
        self.assertEqual(responses['failure'].status_code, 500)
        for name in ('foreign_failure', 'foreign_success'):
            with self.subTest(name):
                self.assertNotIn('access-control-allow-origin', responses[name].headers)
                self.assertTrue(is_server_id(responses[name].headers['x-request-id']))
        self.assertEqual(responses['preflight'].status_code, 200)
        self.assertEqual(responses['preflight'].headers['access-control-allow-origin'], ALLOWED)
        self.assertTrue(is_server_id(responses['preflight'].headers['x-request-id']))

    def test_production_generated_500_keeps_hsts_and_cancellation_has_no_invented_status(self):
        async def failing(scope, receive, send):
            raise ValueError(SECRET)

        async def cancelled(scope, receive, send):
            raise asyncio.CancelledError()

        output = io.StringIO()
        production = RequestLoggingMiddleware(failing, routes=[], production=True)
        with contextlib.redirect_stdout(output):
            response = self.client(raise_server_exceptions=False, app=production).get('/x?token=' + SECRET)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['strict-transport-security'], 'max-age=31536000')
        scope = {'type': 'http', 'method': 'BREW', 'headers': [], 'path': '/' + SECRET}

        async def receive():
            return {'type': 'http.disconnect'}

        sent = []

        async def send(message):
            sent.append(message)

        with contextlib.redirect_stdout(output), self.assertRaises(asyncio.CancelledError):
            asyncio.run(RequestLoggingMiddleware(cancelled, routes=[])(scope, receive, send))
        self.assertEqual(sent, [])
        logged = events(output, 'http.request')
        self.assertEqual((logged[0]['route'], logged[0]['status'], logged[0]['code']), ('unmatched', 500, 'HTTP_REQUEST_FAILED'))
        self.assertEqual((logged[1]['method'], logged[1]['code']), ('OTHER', 'HTTP_REQUEST_CANCELLED'))
        self.assertNotIn('status', logged[1])
        self.assert_safe(output.getvalue())

    def test_job_queued_is_emitted_only_after_commit_with_the_request_id(self):
        client = self.login()
        observed = []
        original = api.emit_event

        def inspect_commit(name, **fields):
            with self.factory() as db:
                job = db.get(Job, fields['job_id'])
                audit = db.scalar(select(func.count()).select_from(Audit).where(
                    Audit.entity_id == fields['job_id'], Audit.action == 'forecast.queued'))
                observed.append((name, job.status if job else None, audit))
            original(name, **fields)

        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(api, 'emit_event', side_effect=inspect_commit):
            response = client.post('/api/v1/forecasts', json={'branch_id': '1'})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(observed, [('job.queued', 'queued', 1)])
        queued = events(output, 'job.queued')
        self.assertEqual(len(queued), 1)
        self.assertEqual(set(queued[0]), {'schema_version', 'timestamp', 'event', 'request_id', 'job_id', 'kind'})
        self.assertEqual((queued[0]['request_id'], queued[0]['job_id'], queued[0]['kind']),
                         (response.headers['x-request-id'], response.json()['run_id'], 'forecast'))
        self.assert_safe(output.getvalue(), client.cookies.get('asboljam_session'), client.headers['X-CSRF-Token'])

    def test_failed_enqueue_commit_logs_no_job_and_a_sanitized_request_failure(self):
        client = self.login()
        client = TestClient(self.app, raise_server_exceptions=False, cookies=client.cookies, headers=client.headers)
        self.addCleanup(client.close)

        def fail_job_commit(session):
            if any(isinstance(item, Job) for item in session.new):
                raise OperationalError('INSERT INTO jobs ' + SECRET, {'password': SECRET}, sqlite3.OperationalError(SECRET))

        with self.factory() as db:
            before = db.scalar(select(func.count()).select_from(Job))
        event.listen(self.factory, 'before_commit', fail_job_commit)
        self.addCleanup(event.remove, self.factory, 'before_commit', fail_job_commit)
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            response = client.post('/api/v1/forecasts', json={'branch_id': '1'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(events(output, 'job.queued'), [])
        logged = events(output, 'http.request')
        self.assertEqual((logged[-1]['route'], logged[-1]['status'], logged[-1]['code'], logged[-1]['request_id']),
                         ('/api/v1/forecasts', 500, 'HTTP_REQUEST_FAILED', response.headers['x-request-id']))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)), before)
        self.assert_safe(output.getvalue() + errors.getvalue() + response.text)

    def test_request_to_worker_chain_correlates_forecast_and_procurement_jobs(self):
        # Earlier tests may leave queued fixture jobs; the worker must claim this chain's job.
        with self.factory() as db:
            db.execute(api.update(Job).where(Job.status == 'queued').values(status='failed', error='TEST_FIXTURE_RETIRED'))
            db.commit()
        client = self.login()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            forecast = client.post('/api/v1/forecasts', json={'branch_id': '1'})
            self.assertEqual(forecast.status_code, 202, forecast.text)
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
            forecast_id = forecast.json()['run_id']
            procurement = client.post('/api/v1/procurement', json={
                'branch_id': '1', 'forecast_id': forecast_id, 'budget': '250000', 'strategy': 'point'})
            self.assertEqual(procurement.status_code, 202, procurement.text)
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        plan_id = procurement.json()['run_id']
        lifecycle = [(row['event'], row.get('job_id'), row.get('kind'), row.get('request_id'), row.get('status'))
                     for row in events(output) if row['event'] != 'http.request']
        self.assertEqual(lifecycle, [
            ('job.queued', forecast_id, 'forecast', forecast.headers['x-request-id'], None),
            ('job.claimed', forecast_id, 'forecast', None, None),
            ('job.finished', forecast_id, 'forecast', None, 'succeeded'),
            ('job.queued', plan_id, 'procurement', procurement.headers['x-request-id'], None),
            ('job.claimed', plan_id, 'procurement', None, None),
            ('job.finished', plan_id, 'procurement', None, 'succeeded'),
        ])
        requests = {row['request_id']: row for row in events(output, 'http.request')}
        self.assertEqual(requests[forecast.headers['x-request-id']]['route'], '/api/v1/forecasts')
        self.assertEqual(requests[procurement.headers['x-request-id']]['route'], '/api/v1/procurement')
        with self.factory() as db:
            meal = db.scalar(select(api.Record).where(api.Record.kind == 'meals').limit(1)).data['meal_name']
        self.assert_safe(output.getvalue(), meal, client.cookies.get('asboljam_session'))


if __name__ == '__main__':
    unittest.main()
