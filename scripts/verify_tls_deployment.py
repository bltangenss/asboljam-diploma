"""HTTP-level checks of the TLS Compose deployment (infra/compose.prod.yml).

Run against a deployed site, or locally against ASBOLJAM_SITE_ADDRESS=localhost with
Caddy's internal root certificate (--ca-file). The administrator password is read only
from the environment variable named by --password-env. Nothing is written to the
server; one login session is created and closed. The report contains no secrets.
"""
import argparse
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
import os
import socket
import ssl
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, help='https://<domain>[:port] exactly as users open it')
    parser.add_argument('--ca-file', help='Trust this root certificate (local internal CA); default: system trust store')
    parser.add_argument('--http-port', type=int, default=80, help='Plain HTTP port that must redirect to HTTPS')
    parser.add_argument('--admin-email')
    parser.add_argument('--password-env', default='ASBOLJAM_CHECK_PASSWORD')
    parser.add_argument('--closed-port', action='append', type=int, default=[],
                        help='Host loopback port that must NOT accept connections (e.g. 8000, 3000)')
    parser.add_argument('--report')
    args = parser.parse_args()
    site = args.site.rstrip('/')
    parts = urlsplit(site)
    if parts.scheme != 'https' or not parts.hostname or parts.path or parts.query:
        parser.error('--site must be an https origin without path or query')
    context = ssl.create_default_context(cafile=args.ca_file) if args.ca_file else ssl.create_default_context()
    opener = build_opener(HTTPSHandler(context=context), HTTPCookieProcessor(CookieJar()))
    checks = {}

    def call(method, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(site + path, data=data, method=method,
                          headers={**({'Content-Type': 'application/json'} if data else {}), **(headers or {})})
        try:
            with opener.open(request, timeout=30) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    status, headers, body = call('GET', '/')
    checks['https_index_200_with_verified_certificate'] = status == 200 and b'<div id="root"' in body
    checks['hsts_header'] = headers.get('Strict-Transport-Security', '').startswith('max-age=')
    checks['no_server_header'] = headers.get('Server') is None
    checks['nosniff_and_frame_deny'] = headers.get('X-Content-Type-Options') == 'nosniff' and headers.get('X-Frame-Options') == 'DENY'

    # Plain HTTP must only redirect to HTTPS.
    host_port = parts.hostname
    plain = socket.create_connection((parts.hostname, args.http_port), timeout=10)
    try:
        plain.sendall(f'GET /api/v1/ready HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n\r\n'.encode())
        raw = b''
        while chunk := plain.recv(4096):
            raw += chunk
    finally:
        plain.close()
    head = raw.split(b'\r\n\r\n', 1)[0].decode('latin-1')
    checks['http_redirects_to_https'] = head.split(' ')[1] in {'301', '302', '307', '308'} and f'Location: https://{parts.hostname}' in head

    status, headers, body = call('GET', '/api/v1/ready')
    checks['api_ready_through_tls'] = status == 200 and json.loads(body) == {'status': 'ready'}
    request_id = headers.get('X-Request-ID') or ''
    checks['server_request_id'] = len(request_id) == 32 and all(c in '0123456789abcdef' for c in request_id)

    for port in args.closed_port:
        try:
            socket.create_connection(('127.0.0.1', port), timeout=3).close()
            checks[f'loopback_port_{port}_closed'] = False
        except OSError:
            checks[f'loopback_port_{port}_closed'] = True

    if args.admin_email:
        password = os.environ.get(args.password_env)
        if not password:
            raise SystemExit(f'{args.password_env} is not set')
        status, headers, body = call('POST', '/api/v1/session/login', {'email': args.admin_email, 'password': password},
                                     {'Origin': 'https://evil.example'})
        checks['foreign_origin_login_refused'] = status == 403
        status, headers, body = call('POST', '/api/v1/session/login', {'email': args.admin_email, 'password': password},
                                     {'Origin': site})
        cookie = headers.get('Set-Cookie', '')
        checks['login_200'] = status == 200
        checks['session_cookie_secure_httponly_lax'] = all(flag in cookie for flag in ('Secure', 'HttpOnly', 'SameSite=lax'))
        csrf = json.loads(body).get('csrf_token', '') if status == 200 else ''
        status, _, _ = call('GET', '/api/v1/session/me')
        checks['session_me_200'] = status == 200
        status, _, _ = call('POST', '/api/v1/session/logout', headers={'Origin': site, 'X-CSRF-Token': csrf})
        checks['logout_200'] = status == 200
        status, _, _ = call('GET', '/api/v1/session/me')
        checks['session_revoked_after_logout'] = status == 401

    report = {'status': 'passed' if all(checks.values()) else 'failed', 'site': site,
              'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'trust': 'custom CA file' if args.ca_file else 'system store',
              'checks': checks,
              'limits': ['HTTP-level checks only; certificate issuance by a public CA, DNS, firewall, load and failover are separate']}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        with open(args.report, 'x', encoding='utf-8', newline='\n') as handle:
            handle.write(text + '\n')
    print(text)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
