"""Validate deployment settings before opening a database or serving requests.

Production is a transport/configuration guard, not permission to import REAL data.
Errors deliberately name settings without repeating their potentially secret values.
"""
import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


LOCAL_ORIGINS = ('http://localhost:3000', 'http://127.0.0.1:3000')
_HOST_LABEL = re.compile(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z')
_PLACEHOLDER_PASSWORDS = frozenset({
    'password', 'postgres', 'asboljam', 'changeme', 'change_me', 'change-me',
    'replace_me', 'replace-me', 'url_encoded_password', 'your_password',
})


class ConfigurationError(ValueError):
    """Unsafe or malformed environment configuration, without secret values."""


@dataclass(frozen=True)
class Settings:
    environment: str
    allowed_origins: tuple[str, ...]
    cookie_secure: bool
    database_url: str | None = field(repr=False)


def _origin(value: str, production: bool) -> str:
    message = 'ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths, credentials or wildcards'
    if not value or any(c.isspace() for c in value) or any(c in value for c in ('*', '\\', '%')):
        raise ConfigurationError(message)
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ConfigurationError(message) from None
    if (parts.scheme not in {'http', 'https'} or not host
            or value != f'{parts.scheme}://{parts.netloc}'
            or parts.username is not None or parts.password is not None
            or parts.netloc.endswith(':') or port == 0):
        raise ConfigurationError(message)
    expected_host = f'[{host}]' if ':' in host else host
    expected_netloc = expected_host + (f':{port}' if port is not None else '')
    if parts.netloc.lower() != expected_netloc:
        # urlsplit accepts malformed suffixes after bracketed IPv6, e.g. [::1]junk.
        raise ConfigurationError(message)
    try:
        address = ipaddress.ip_address(host)
        host = address.compressed
    except ValueError:
        if len(host) > 253 or not all(_HOST_LABEL.fullmatch(label) for label in host.split('.')):
            raise ConfigurationError(message) from None
    if production and parts.scheme != 'https':
        raise ConfigurationError('Production ALLOWED_ORIGINS must use HTTPS')
    # Match the Origin header serialization sent by browsers (case/default port/IPv6).
    canonical_host = f'[{host}]' if ':' in host else host
    default_port = 443 if parts.scheme == 'https' else 80
    suffix = f':{port}' if port is not None and port != default_port else ''
    return f'{parts.scheme}://{canonical_host}{suffix}'


def load_settings(database_url: str | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    """Pure validation: no file reads, connection, migration or implicit .env loading."""
    env = os.environ if environ is None else environ
    mode = env.get('ASBOLJAM_ENV', 'local').strip().lower()
    if mode not in {'local', 'production'}:
        raise ConfigurationError('ASBOLJAM_ENV must be local or production')
    production = mode == 'production'

    raw_origins = env.get('ALLOWED_ORIGINS')
    if raw_origins is None:
        if production:
            raise ConfigurationError('Production requires explicit ALLOWED_ORIGINS')
        origins = LOCAL_ORIGINS
    else:
        # Empty entries are errors too: a typo must not silently weaken configuration.
        origins = tuple(dict.fromkeys(_origin(item.strip(), production) for item in raw_origins.split(',')))

    raw_secure = env.get('COOKIE_SECURE', 'false').strip().lower()
    if raw_secure not in {'true', 'false'}:
        raise ConfigurationError('COOKIE_SECURE must be true or false')
    secure = raw_secure == 'true'
    if production and not secure:
        raise ConfigurationError('Production requires COOKIE_SECURE=true')
    if production and env.get('DEMO_PASSWORD', '').strip():
        raise ConfigurationError('DEMO_PASSWORD must be unset in production')

    selected_url = database_url if database_url is not None else env.get('DATABASE_URL')
    if selected_url is None:
        if production:
            raise ConfigurationError('Production requires an explicit PostgreSQL DATABASE_URL')
    else:
        try:
            if not selected_url.strip():
                raise ValueError()
            parsed = make_url(selected_url)
            backend = parsed.get_backend_name()
            # Match the drivers implemented by make_engine; do not silently use another backend.
            if parsed.drivername not in {'sqlite', 'sqlite+pysqlite', 'postgresql', 'postgresql+psycopg'}:
                raise ValueError()
            if backend == 'postgresql' and not parsed.database:
                raise ValueError()
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
        except (ValueError, TypeError, AttributeError, ArgumentError):
            # SQLAlchemy parsing errors may include the original URL; never propagate it.
            raise ConfigurationError('DATABASE_URL must be a valid supported database URL') from None
        if production:
            if backend != 'postgresql':
                raise ConfigurationError('Production DATABASE_URL must select PostgreSQL')
            query_password = parsed.query.get('password')
            passwords = (parsed.password,) + (query_password if isinstance(query_password, tuple) else (query_password,))
            for password in passwords:
                if password is not None and (not password.strip() or password.strip().lower() in _PLACEHOLDER_PASSWORDS):
                    raise ConfigurationError('Production DATABASE_URL contains a placeholder password')
            # An absent password is allowed for deliberate socket/certificate/IAM authentication.
            # Authentication and network TLS are verified against the target deployment separately.

    return Settings(mode, origins, secure, selected_url)


if __name__ == '__main__':
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    print(f'Configuration valid: {settings.environment}; no database connection attempted.')
