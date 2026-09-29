"""Opt-in PostgreSQL schemas for security tests; SQLite remains the default.

The caller must create a fresh database named asboljam_security_<32 hex digits>.
Each test gets its own schema, retained inside that database for diagnosis.
No pre-existing tables/schemas/databases are truncated, dropped or overwritten.
"""
import os
import re
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def isolated_database_url(fallback_url: str) -> str:
    configured = os.environ.get('ASBOLJAM_SECURITY_TEST_DATABASE_URL')
    if configured is None:
        return fallback_url
    try:
        url = make_url(configured)
        if (url.drivername not in {'postgresql', 'postgresql+psycopg'}
                or re.fullmatch(r'asboljam_security_[0-9a-f]{32}', url.database or '') is None
                or url.query):
            raise ValueError()
        url = url.set(drivername='postgresql+psycopg')
    except Exception:
        raise ValueError('ASBOLJAM_SECURITY_TEST_DATABASE_URL must target a fresh security-test PostgreSQL database without query parameters') from None
    schema = 'test_' + uuid.uuid4().hex
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        engine.dispose()
    return url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
