// Exercises apps/web/public/_worker.js with a fake ASSETS binding and a fake upstream fetch.
// Run: node tests/pages_worker_check.mjs  (tests/test_cloud_config.py runs it too).
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const worker = (await import(pathToFileURL(resolve('apps/web/public/_worker.js')).href)).default;
const calls = [];
globalThis.fetch = async (target, init) => {
  const body = init.body ? await new Response(init.body).text() : null;
  calls.push({ target, method: init.method, headers: init.headers, body, redirect: init.redirect });
  const headers = new Headers({ 'Content-Type': 'application/json' });
  headers.append('Set-Cookie', 'asboljam_session=abc; HttpOnly; Secure; SameSite=Lax; Path=/api');
  return new Response('{"ok":true}', { status: 201, headers });
};
const assets = { fetch: async request => new Response('index:' + new URL(request.url).pathname, { headers: { 'Content-Type': 'text/html' } }) };
const env = { ASSETS: assets, API_ORIGIN: 'https://predas-api.onrender.com' };

// Static routes go to Pages assets and never reach the API.
let response = await worker.fetch(new Request('https://predas.pages.dev/day-close'), env);
assert.equal(await response.text(), 'index:/day-close');
assert.equal(response.headers.get('X-Frame-Options'), 'DENY');
response = await worker.fetch(new Request('https://predas.pages.dev/apiary'), env);
assert.equal(await response.text(), 'index:/apiary');
assert.equal(calls.length, 0);

// API calls keep method, path, query, body, Origin and CSRF headers; cookies come back unchanged.
response = await worker.fetch(new Request('https://predas.pages.dev/api/v1/auth/login?next=1', {
  method: 'POST', body: '{"email":"a@example.invalid"}',
  headers: { Origin: 'https://predas.pages.dev', 'X-CSRF-Token': 't1', 'Content-Type': 'application/json', Host: 'predas.pages.dev' },
}), env);
assert.equal(response.status, 201);
assert.match(response.headers.get('Set-Cookie'), /asboljam_session=abc; HttpOnly; Secure; SameSite=Lax; Path=\/api/);
const call = calls.at(-1);
assert.equal(call.target, 'https://predas-api.onrender.com/api/v1/auth/login?next=1');
assert.equal(call.method, 'POST');
assert.equal(call.body, '{"email":"a@example.invalid"}');
assert.equal(call.redirect, 'manual');
assert.equal(call.headers.get('origin'), 'https://predas.pages.dev');
assert.equal(call.headers.get('x-csrf-token'), 't1');
assert.equal(call.headers.get('host'), null);
assert.equal(call.headers.get('x-forwarded-host'), 'predas.pages.dev');
assert.equal(call.headers.get('x-forwarded-proto'), 'https');

// GET has no body.
await worker.fetch(new Request('https://predas.pages.dev/api/v1/health'), env);
assert.equal(calls.at(-1).body, null);

// Missing or unsafe API_ORIGIN is refused without contacting anything.
const before = calls.length;
for (const value of [undefined, '', 'http://predas-api.onrender.com', 'https://x.onrender.com/api', 'https://u:p@x.onrender.com', 'not a url']) {
  response = await worker.fetch(new Request('https://predas.pages.dev/api/v1/health'), { ASSETS: assets, API_ORIGIN: value });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).detail.code, 'API_NOT_CONFIGURED');
}
assert.equal(calls.length, before);

// Local proxy testing may use plain HTTP only on localhost.
await worker.fetch(new Request('http://localhost:8788/api/v1/health'), { ASSETS: assets, API_ORIGIN: 'http://127.0.0.1:8000' });
assert.equal(calls.at(-1).target, 'http://127.0.0.1:8000/api/v1/health');

console.log('pages worker checks passed');
