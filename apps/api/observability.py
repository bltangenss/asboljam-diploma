"""Small, best-effort JSON events with an explicit schema and no payload logging.

Callers must supply server-owned IDs and registered route templates, never request
paths or customer text. Events are operational diagnostics, not durable audit rows.
"""
from datetime import datetime, timezone
import json
import math
import re
import sys
import threading


_LOCK = threading.Lock()
_ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_REQUEST_ID = re.compile(r'[a-f0-9]{32}\Z')
_ROUTE = re.compile(r'/[A-Za-z0-9_{}:/.-]{0,199}\Z')
_JOB_CODES = frozenset({'JOB_ACCESS_REVOKED', 'JOB_SCOPE_INVALID',
    'JOB_INPUT_INVALID', 'JOB_CALCULATION_FAILED', 'JOB_TIMEOUT'})
# Fixed codes per event; anything else (including exception names) is refused.
_CODES = {
    'http.request': frozenset({'HTTP_REQUEST_FAILED', 'HTTP_REQUEST_CANCELLED'}),
    'job.finished': _JOB_CODES,
    'job.discarded': frozenset({'CLAIM_LOST', 'JOB_MISSING'}),
    'job.publication_error': frozenset({'DATABASE_ERROR', 'PUBLICATION_ERROR'}),
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


_VALIDATORS = {
    'request_id': lambda value: _matches(_REQUEST_ID, value),
    'job_id': lambda value: _matches(_ID, value),
    'kind': lambda value: type(value) is str and value in {'forecast', 'procurement'},
    'claim_time': _number,
    'duration_ms': _number,
    'method': lambda value: type(value) is str and value in {
        'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT', 'OTHER'},
    'route': lambda value: type(value) is str and (value == 'unmatched' or _matches(_ROUTE, value)),
    'status': lambda value: type(value) is int and 100 <= value <= 599,
}
# Required and optional keys are event-specific; unknown keys are never serialized.
# http.request status is the status actually started; a request cancelled before
# any response has no status and must carry a code instead.
_SCHEMAS = {
    'http.request': ({'request_id', 'method', 'route', 'duration_ms'}, {'status', 'code'}),
    'job.queued': ({'request_id', 'job_id', 'kind'}, set()),
    'job.claimed': ({'job_id', 'kind', 'claim_time'}, set()),
    'job.finished': ({'job_id', 'kind', 'claim_time', 'status'}, {'code'}),
    'job.discarded': ({'job_id', 'claim_time', 'code'}, {'kind'}),
    'job.released': ({'job_id', 'claim_time'}, {'kind'}),
    'job.lease_expired': ({'job_id'}, set()),
    'job.publication_error': ({'job_id', 'claim_time', 'code'}, set()),
}


def emit_event(event, **fields):
    """Write one allowlisted JSON line; logging failure never changes a transaction.

    Return False for invalid schemas or an unavailable output stream. Do not fall
    back to printing arguments or exceptions: they may contain private material.
    """
    try:
        if type(event) is not str or event not in _SCHEMAS:
            return False
        required, optional = _SCHEMAS[event]
        if not required <= fields.keys():
            return False
        safe = {key: fields[key] for key in sorted(required | optional) if key in fields}
        for key, value in safe.items():
            if key == 'status' and event == 'job.finished':
                valid = type(value) is str and value in {'succeeded', 'failed'}
            elif key == 'code':
                valid = type(value) is str and value in _CODES[event]
            else:
                valid = _VALIDATORS[key](value)
            if not valid:
                return False
        if event == 'job.finished':
            if (safe['status'] == 'failed') != ('code' in safe):
                return False
        if event == 'http.request' and not {'status', 'code'} & safe.keys():
            return False
        record = {'schema_version': 1,
            'timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'event': event, **safe}
        line = json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n'
        with _LOCK:
            sys.stdout.write(line)
            sys.stdout.flush()
        return True
    except Exception:
        # Best effort only. A broken log sink cannot roll back or relabel a commit.
        return False
