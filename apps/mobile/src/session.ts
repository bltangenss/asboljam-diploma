import { ApiClient, ApiError, type User } from '../../../packages/api-client';

export interface TokenStore {
  read(): Promise<string | null>;
  write(value: string): Promise<void>;
  clear(): Promise<void>;
}
type Tokens = { access_token: string; refresh_token: string; expires_in: number; user: User };

/** Access stays in memory. Store mutations and refresh rotation are serialized. */
export class NativeSession {
  private access = '';
  private refreshToken = '';
  private expiresAt = 0;
  private epoch = 0;
  private refreshFlight: { epoch: number; promise: Promise<void> } | null = null;
  private storageFlight: Promise<void> = Promise.resolve();
  private raw: ApiClient;
  private authenticated: ApiClient;
  user: User | null = null;
  onUser: (user: User | null) => void = () => {};

  constructor(readonly base: string, private store: TokenStore) {
    this.raw = new ApiClient(base, async () => null);
    this.authenticated = new ApiClient(base, async () => this.access || null);
  }
  private check(epoch: number) {
    if (epoch !== this.epoch) throw new ApiError(401, 'SESSION_CHANGED', 'Сессия өзгерді. Қайта кіріңіз.');
  }
  private mutateStorage(operation: () => Promise<void>) {
    const next = this.storageFlight.catch(() => {}).then(operation);
    this.storageFlight = next;
    return next;
  }
  private resetMemory() {
    this.access = ''; this.refreshToken = ''; this.expiresAt = 0; this.user = null;
    this.onUser(null);
  }
  private async timed<T>(client: ApiClient, path: string, options: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try { return await client.request<T>(path, { ...options, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  }
  private async accept(tokens: Tokens, epoch: number) {
    this.check(epoch);
    await this.mutateStorage(async () => {
      this.check(epoch);
      await this.store.write(JSON.stringify({ base: this.base, refresh_token: tokens.refresh_token }));
    });
    // A later clear/login already queued its storage operation. Never clear its token here.
    this.check(epoch);
    this.access = tokens.access_token;
    this.refreshToken = tokens.refresh_token;
    this.expiresAt = Date.now() + tokens.expires_in * 1000;
    this.user = tokens.user;
    this.onUser(this.user);
  }
  async login(email: string, password: string) {
    const epoch = ++this.epoch;
    this.resetMemory();
    await this.mutateStorage(() => this.store.clear());
    this.check(epoch);
    const tokens = await this.timed<Tokens>(this.raw, '/auth/token', {
      method: 'POST', body: JSON.stringify({ email: email.trim(), password }),
    });
    await this.accept(tokens, epoch);
  }
  async restore() {
    const epoch = this.epoch;
    await this.storageFlight.catch(() => {});
    const stored = await this.store.read();
    this.check(epoch);
    if (!stored) return;
    let parsed: { base?: string; refresh_token?: string };
    try { parsed = JSON.parse(stored); } catch { await this.clear(); return; }
    if (!parsed || typeof parsed !== 'object' || parsed.base !== this.base || typeof parsed.refresh_token !== 'string' || !parsed.refresh_token.trim()) { await this.clear(); return; }
    this.refreshToken = parsed.refresh_token;
    await this.refresh();
  }
  private refresh(): Promise<void> {
    if (this.refreshFlight?.epoch === this.epoch) return this.refreshFlight.promise;
    if (!this.refreshToken) return Promise.reject(new ApiError(401, 'AUTH_REQUIRED', 'Қайта кіріңіз.'));
    const epoch = this.epoch;
    const refreshToken = this.refreshToken;
    const flight = { epoch, promise: Promise.resolve() };
    flight.promise = (async () => {
      try {
        const tokens = await this.timed<Tokens>(this.raw, '/auth/refresh', {
          method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }),
        });
        await this.accept(tokens, epoch);
      } catch (error) {
        if (epoch === this.epoch && error instanceof ApiError && error.status === 401) await this.clear();
        throw error;
      } finally { if (this.refreshFlight === flight) this.refreshFlight = null; }
    })();
    this.refreshFlight = flight;
    return flight.promise;
  }
  async request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const epoch = this.epoch;
    if (this.refreshFlight?.epoch === epoch || Date.now() >= this.expiresAt - 30000) await this.refresh();
    this.check(epoch);
    const usedToken = this.access;
    try {
      const result = await this.timed<T>(this.authenticated, path, options);
      this.check(epoch);
      return result;
    } catch (error) {
      this.check(epoch);
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      if (this.access === usedToken) await this.refresh();
      this.check(epoch);
      // The server rejects 401 before any business action. No network/409 retries.
      const result = await this.timed<T>(this.authenticated, path, options);
      this.check(epoch);
      return result;
    }
  }
  async logout(): Promise<void> {
    const epoch = this.epoch;
    try { if (this.refreshToken) await this.request('/session/logout', { method: 'POST' }); }
    finally { if (epoch === this.epoch) await this.clear(); }
  }
  async clear() {
    ++this.epoch;
    this.resetMemory();
    await this.mutateStorage(() => this.store.clear());
  }
}
