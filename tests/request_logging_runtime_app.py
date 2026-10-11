"""Runtime-only fixture for scripts/verify_request_logging.py; never a deployment entry point.

It is the real API (configured by the verifier's isolated environment) plus one route
that fails with a private value in the exception, SQL parameters and path.
"""
from sqlalchemy.exc import IntegrityError

from apps.api.main import app

SENTINEL = 'runtime-private-logging-sentinel'


@app.get('/verify/fail/{item_id}')
def fail(item_id: str):
    raise IntegrityError('INSERT INTO private VALUES (?) ' + SENTINEL, {'password': SENTINEL}, Exception(SENTINEL))
