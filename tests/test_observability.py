"""Diagnostic schemas reject secrets, invalid values and mixed concurrent lines."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from apps.api.observability import emit_event


class ObservabilityTests(unittest.TestCase):
    def test_allowlist_never_serializes_unknown_values(self):
        class PrivateValue:
            def __str__(self):
                raise AssertionError('private value inspected')
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(emit_event('job.claimed', job_id='job', kind='forecast',
                claim_time=1.25, password=PrivateValue(), snapshot='CSV-SENTINEL',
                database_url='DATABASE-SENTINEL', token='TOKEN-SENTINEL'))
        event = json.loads(output.getvalue())
        self.assertEqual(set(event), {'schema_version', 'timestamp', 'event', 'job_id', 'kind', 'claim_time'})
        self.assertNotIn('SENTINEL', output.getvalue())

    def test_invalid_ids_codes_methods_routes_and_nonfinite_values_are_not_logged(self):
        request = dict(request_id='a' * 32, method='GET', route='/api/v1/runs/{run_id}',
            status=200, duration_ms=3.5)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(emit_event('http.request', **request))
            for key, value in [('request_id', 'spoof\r\nsecret'), ('request_id', 'A' * 32),
                    ('method', 'CUSTOM-SENTINEL'), ('route', '/query?token=SENTINEL'),
                    ('route', '/literal\nsecret'), ('status', True), ('status', 600),
                    ('duration_ms', float('nan')), ('duration_ms', float('inf')),
                    ('duration_ms', -1), ('duration_ms', '2')]:
                with self.subTest(key=key, value=value):
                    self.assertFalse(emit_event('http.request', **{**request, key: value}))
            self.assertFalse(emit_event('PRIVATE-SENTINEL', **request))
            self.assertFalse(emit_event('job.claimed', job_id='bad\nsecret', kind='forecast', claim_time=1))
            self.assertFalse(emit_event('job.claimed', job_id='job', kind='forecast'))
            self.assertFalse(emit_event('job.discarded', job_id='job', claim_time=1, code='PRIVATE-SENTINEL'))
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_terminal_codes_cannot_claim_contradictory_success(self):
        base = dict(job_id='job', kind='forecast', claim_time=1)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertTrue(emit_event('job.finished', **base, status='succeeded'))
            self.assertTrue(emit_event('job.finished', **base, status='failed', code='JOB_TIMEOUT'))
            self.assertFalse(emit_event('job.finished', **base, status='failed'))
            self.assertFalse(emit_event('job.finished', **base, status='succeeded', code='JOB_TIMEOUT'))
        self.assertEqual(len(output.getvalue().splitlines()), 2)

    def test_parallel_events_remain_independent_json_lines(self):
        output = io.StringIO()
        with redirect_stdout(output), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: emit_event('job.claimed', job_id=f'job-{n}',
                kind='forecast', claim_time=1 + n), range(100)))
        self.assertTrue(all(results))
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(events), 100)
        self.assertEqual({e['job_id'] for e in events}, {f'job-{n}' for n in range(100)})

    def test_closed_or_failing_sink_does_not_raise(self):
        closed = io.StringIO()
        closed.close()
        with redirect_stdout(closed):
            self.assertFalse(emit_event('job.claimed', job_id='job', kind='forecast', claim_time=1))
        with patch('apps.api.observability.sys.stdout') as stream:
            stream.write.side_effect = OSError('PRIVATE-SENTINEL')
            self.assertFalse(emit_event('job.claimed', job_id='job', kind='forecast', claim_time=1))
            stream.flush.assert_not_called()


if __name__ == '__main__':
    unittest.main()
