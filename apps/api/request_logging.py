"""Server-owned request correlation without request contents or raw URLs."""
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse

from .observability import emit_event


METHODS = frozenset({'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'CONNECT', 'TRACE'})
REQUEST_FAILED = 'HTTP_REQUEST_FAILED'


class RequestLoggingMiddleware:
    """Outermost user middleware, so early protection refusals are correlated too.

    Route labels come only from registered route objects after dispatch. Incoming
    correlation headers, URLs, headers and body values are never log fields.
    Request state is shared with sync endpoints without ContextVar propagation.
    """

    def __init__(self, app, *, routes, production=False, cors=None):
        self.app = app
        self.routes = routes
        self.production = production
        # The same options as the inner CORS layer: the generated 500 is outside it.
        self.cors = cors

    async def send_failure(self, scope, receive, send):
        headers = {'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
                   'Referrer-Policy': 'same-origin', 'Cache-Control': 'no-store'}
        if self.production:
            headers['Strict-Transport-Security'] = 'max-age=31536000'
        response = PlainTextResponse('Internal Server Error', status_code=500, headers=headers)
        request_headers = Headers(scope=scope)
        if self.cors is None or 'origin' not in request_headers:
            await response(scope, receive, send)
            return
        # Starlette's own simple-response rules: only an allowed origin is mirrored.
        # This path never answers a preflight; the inner CORS layer owns those.
        await CORSMiddleware(response, **self.cors).simple_response(
            scope, receive, send, request_headers=request_headers)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        method = scope.get('method')
        method = method if method in METHODS else 'OTHER'
        started = perf_counter()
        # Only a response start accepted by the server sets the logged status.
        status, code = None, None

        async def correlated_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                # The server owns this header even if inner code supplied a value.
                headers = [(key, value) for key, value in message.get('headers', [])
                           if key.lower() != b'x-request-id']
                headers.append((b'x-request-id', request_id.encode('ascii')))
                message = {**message, 'headers': headers}
                await send(message)
                status = message['status']
                return
            await send(message)

        try:
            await self.app(scope, receive, correlated_send)
        except Exception:
            code = REQUEST_FAILED
            if status is None:
                try:
                    await self.send_failure(scope, receive, correlated_send)
                except Exception:
                    # The client may already be gone; the sanitized signal below remains.
                    pass
            # Exception values can include SQL parameters or CSV. Hide the original
            # and its chain from the ASGI server traceback; never send a second start.
            raise RuntimeError(REQUEST_FAILED) from None
        except BaseException:
            code = 'HTTP_REQUEST_CANCELLED'
            raise
        finally:
            route = scope.get('route')
            template = getattr(route, 'path', None) if any(route is item for item in self.routes) else None
            emit_event('http.request', request_id=request_id, method=method,
                       route=template if isinstance(template, str) else 'unmatched',
                       duration_ms=max(0, round((perf_counter() - started) * 1000, 3)),
                       **({} if status is None else {'status': status}),
                       **({} if code is None else {'code': code}))
