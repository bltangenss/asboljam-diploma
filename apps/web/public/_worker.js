// Cloudflare Pages (advanced mode): serve the built web client and forward /api/* to the
// Render API. The browser sees one origin, so the HttpOnly session cookie (SameSite=Lax,
// Path=/api), the Origin check and the CSRF header work exactly as behind nginx.
// API_ORIGIN is a plain Pages variable, e.g. https://predas-api.onrender.com.
const SECURITY_HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'same-origin',
};

function apiOrigin(value) {
  try {
    const url = new URL(value || '');
    const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
    if ((url.protocol === 'https:' || (local && url.protocol === 'http:')) && url.pathname === '/' && !url.search && !url.username) return url.origin;
  } catch {}
  return null;
}

function withSecurityHeaders(response) {
  const result = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) result.headers.set(name, value);
  return result;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== '/api' && !url.pathname.startsWith('/api/')) {
      return withSecurityHeaders(await env.ASSETS.fetch(request));
    }
    const origin = apiOrigin(env.API_ORIGIN);
    if (!origin) {
      return withSecurityHeaders(Response.json(
        { detail: { code: 'API_NOT_CONFIGURED', message: 'API_ORIGIN is not configured for this site.' } },
        { status: 503, headers: { 'Cache-Control': 'no-store' } },
      ));
    }
    const headers = new Headers(request.headers);
    headers.delete('host');
    headers.set('X-Forwarded-Host', url.host);
    headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''));
    // Buffer the body (uploads are capped at 22 MB by the API) so the upstream request carries
    // an exact Content-Length, which the API checks before reading.
    const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
    const upstream = await fetch(origin + url.pathname + url.search, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: 'manual',
    });
    return withSecurityHeaders(upstream);
  },
};
