import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ApiError } from '../../../packages/api-client';
import { NativeSession, type TokenStore } from './session';

const user = { id: 'manager', email: 'manager@example.test', role: 'manager' as const, organization_id: 'org', branch_ids: ['1'] };
function tokens(suffix = '1', expires = 900) { return { access_token: `access-${suffix}`, refresh_token: `refresh-${suffix}`, expires_in: expires, user }; }
function storage() {
  let value: string | null = null;
  const store: TokenStore = { read: async () => value, write: async v => { value = v; }, clear: async () => { value = null; } };
  return store;
}
function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }
const base = 'https://api.example.test/api/v1';

test('native login persists only refresh token and binds it to the API base', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const store = storage();
  globalThis.fetch = async (url, options) => {
    assert.equal(url, `${base}/auth/token`); assert.equal(options?.credentials, 'omit');
    assert.equal(new Headers(options?.headers).get('Authorization'), null);
    return response(tokens());
  };
  const session = new NativeSession(base, store);
  await session.login(' manager@example.test ', 'secret');
  assert.deepEqual(JSON.parse((await store.read())!), { base, refresh_token: 'refresh-1' });
  assert.equal(session.user?.id, 'manager');
});

test('simultaneous expiry uses one rotating refresh and all requests use the new access token', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  let refreshes = 0;
  globalThis.fetch = async (url, options) => {
    if (String(url).endsWith('/auth/token')) return response(tokens('1', 1));
    if (String(url).endsWith('/auth/refresh')) {
      refreshes++; assert.equal(JSON.parse(String(options?.body)).refresh_token, 'refresh-1');
      await new Promise(resolve => setTimeout(resolve, 10)); return response(tokens('2'));
    }
    assert.equal(new Headers(options?.headers).get('Authorization'), 'Bearer access-2');
    return response({ items: [] });
  };
  const store = storage(); const session = new NativeSession(base, store);
  await session.login('manager@example.test', 'secret');
  await Promise.all([session.request('/plans'), session.request('/inventory')]);
  assert.equal(refreshes, 1); assert.equal(JSON.parse((await store.read())!).refresh_token, 'refresh-2');
});

test('restore rotates a saved refresh and rejects credentials for a different API', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const store = storage(); await store.write(JSON.stringify({ base, refresh_token: 'refresh-1' }));
  let calls = 0;
  globalThis.fetch = async url => { calls++; assert.equal(url, `${base}/auth/refresh`); return response(tokens('2')); };
  const session = new NativeSession(base, store); await session.restore();
  assert.equal(session.user?.id, 'manager'); assert.equal(calls, 1);
  const other = new NativeSession('https://different.example/api/v1', store); await other.restore();
  assert.equal(other.user, null); assert.equal(await store.read(), null); assert.equal(calls, 1);
});

test('401 authentication retry preserves approval version, payload and idempotency key', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  let calls = 0; let refreshes = 0;
  const payload = { expected_version: 3, reason: 'reviewed', acknowledge_shortage: true };
  globalThis.fetch = async (url, options) => {
    if (String(url).endsWith('/auth/token')) return response(tokens());
    if (String(url).endsWith('/auth/refresh')) { refreshes++; return response(tokens('2')); }
    calls++;
    assert.equal(url, `${base}/plans/p1/approve`); assert.deepEqual(JSON.parse(String(options?.body)), payload);
    assert.equal(new Headers(options?.headers).get('Idempotency-Key'), 'decision-1');
    return calls === 1 ? response({ detail: { code: 'AUTH_REQUIRED' } }, 401) : response({ version: 4 });
  };
  const session = new NativeSession(base, storage()); await session.login('manager@example.test', 'secret');
  const result = await session.request<{version:number}>('/plans/p1/approve', { method: 'POST', body: JSON.stringify(payload), headers: { 'Idempotency-Key': 'decision-1' } });
  assert.equal(result.version, 4); assert.equal(calls, 2); assert.equal(refreshes, 1);
});

test('403 branch isolation and 409 stale plan are surfaced without refresh or silent retry', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  let calls = 0;
  globalThis.fetch = async url => {
    if (String(url).endsWith('/auth/token')) return response(tokens());
    calls++;
    return String(url).includes('branch_id=other') ? response({ detail: { code: 'BRANCH_FORBIDDEN' } }, 403) : response({ detail: { code: 'STALE_VERSION' } }, 409);
  };
  const session = new NativeSession(base, storage()); await session.login('manager@example.test', 'secret');
  await assert.rejects(session.request('/plans?branch_id=other'), (error: unknown) => error instanceof ApiError && error.status === 403);
  await assert.rejects(session.request('/plans/p1/approve', { method: 'POST' }), (error: unknown) => error instanceof ApiError && error.status === 409);
  assert.equal(calls, 2);
});

test('logout clears secure storage and user even when the server is unreachable', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  globalThis.fetch = async url => {
    if (String(url).endsWith('/auth/token')) return response(tokens());
    throw new TypeError('network unavailable');
  };
  const store = storage(); const session = new NativeSession(base, store); await session.login('manager@example.test', 'secret');
  await assert.rejects(session.logout(), (error: unknown) => error instanceof ApiError && error.status === 0);
  assert.equal(await store.read(), null); assert.equal(session.user, null);
  await assert.rejects(session.request('/plans'), (error: unknown) => error instanceof ApiError && error.status === 401);
});

test('invalid or reused refresh clears the session rather than retrying', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const store = storage(); await store.write(JSON.stringify({ base, refresh_token: 'refresh-used' }));
  globalThis.fetch = async () => response({ detail: { code: 'REFRESH_REUSED', message: 'session revoked' } }, 401);
  const session = new NativeSession(base, store);
  await assert.rejects(session.restore(), (error: unknown) => error instanceof ApiError && error.code === 'REFRESH_REUSED');
  assert.equal(await store.read(), null); assert.equal(session.user, null);
});

test('clearing while a refresh is in flight prevents late response from restoring credentials', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const store = storage(); await store.write(JSON.stringify({ base, refresh_token: 'refresh-1' }));
  let release!: () => void;
  globalThis.fetch = async () => { await new Promise<void>(resolve => { release = resolve; }); return response(tokens('2')); };
  const session = new NativeSession(base, store); const restoring = session.restore();
  await new Promise(resolve => setTimeout(resolve, 5));
  await session.clear(); release();
  await assert.rejects(restoring);
  assert.equal(await store.read(), null); assert.equal(session.user, null);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

test('an old refresh cannot clear a newer successful login', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const store = storage(); await store.write(JSON.stringify({ base, refresh_token: 'refresh-old' }));
  const oldResponse = deferred<Response>(); const started = deferred<void>();
  globalThis.fetch = async url => {
    if (String(url).endsWith('/auth/refresh')) { started.resolve(); return oldResponse.promise; }
    return response(tokens('new'));
  };
  const session = new NativeSession(base, store);
  const restoring = session.restore(); await started.promise;
  await session.login('new@example.test', 'secret');
  oldResponse.resolve(response(tokens('old')));
  await assert.rejects(restoring);
  assert.equal(JSON.parse((await store.read())!).refresh_token, 'refresh-new');
  assert.equal(session.user?.id, 'manager');
});

test('a delayed secure-store read cannot restore tokens after clear', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const reading = deferred<string | null>(); const started = deferred<void>();
  let calls = 0;
  globalThis.fetch = async () => { calls++; return response(tokens()); };
  const session = new NativeSession(base, { read: () => { started.resolve(); return reading.promise; }, write: async () => {}, clear: async () => {} });
  const restoring = session.restore(); await started.promise; await session.clear();
  reading.resolve(JSON.stringify({ base, refresh_token: 'refresh-old' }));
  await assert.rejects(restoring); assert.equal(calls, 0); assert.equal(session.user, null);
});

test('serialized secure-store writes preserve newer credentials after an old pending write', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  let value: string | null = JSON.stringify({ base, refresh_token: 'refresh-old' });
  const writing = deferred<void>(); const release = deferred<void>(); let writes = 0;
  const store: TokenStore = {
    read: async () => value,
    write: async next => { writes++; if (writes === 1) { writing.resolve(); await release.promise; } value = next; },
    clear: async () => { value = null; },
  };
  globalThis.fetch = async url => response(tokens(String(url).endsWith('/auth/token') ? 'new' : 'old-rotated'));
  const session = new NativeSession(base, store);
  const restoring = session.restore(); const rejected = assert.rejects(restoring); await writing.promise;
  const clearing = session.clear(); const login = session.login('new@example.test', 'secret');
  release.resolve(); await Promise.all([rejected, clearing, login]);
  assert.equal(JSON.parse((await store.read())!).refresh_token, 'refresh-new');
  assert.equal(session.user?.id, 'manager');
});

test('a delayed 401 never retries an old business action under a new login', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  const delayed = deferred<Response>(); const started = deferred<void>(); let businessCalls = 0; let logins = 0;
  globalThis.fetch = async url => {
    if (String(url).endsWith('/auth/token')) return response(tokens(String(++logins)));
    businessCalls++; started.resolve(); return delayed.promise;
  };
  const session = new NativeSession(base, storage()); await session.login('one@example.test', 'secret');
  const approving = session.request('/plans/p1/approve', { method: 'POST' });
  await started.promise; await session.login('two@example.test', 'secret');
  delayed.resolve(response({ detail: { code: 'AUTH_REQUIRED' } }, 401));
  await assert.rejects(approving, (error: unknown) => error instanceof ApiError && error.code === 'SESSION_CHANGED');
  assert.equal(businessCalls, 1); assert.equal(session.user?.id, 'manager');
});


test('corrupted secure-store values are cleared before any request', async t => {
  const previous = globalThis.fetch; t.after(() => { globalThis.fetch = previous; });
  let calls = 0;
  globalThis.fetch = async () => { calls++; return response(tokens()); };
  for (const value of ['null', '42', '[]', '{invalid', JSON.stringify({base, refresh_token: 17})]) {
    const store = storage(); await store.write(value);
    const session = new NativeSession(base, store); await session.restore();
    assert.equal(await store.read(), null); assert.equal(session.user, null);
  }
  assert.equal(calls, 0);
});
