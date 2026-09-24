export type Role = 'admin' | 'manager' | 'analyst' | 'warehouse';
export interface User { id: string; email: string; role: Role; organization_id: string; branch_ids: string[] }
export interface Page<T> { items: T[]; total: number; next_cursor: string | null; data_origin: string; scenario_date: string }
export interface Prediction { meal_id: string; point_forecast: number; p10: number | null; p50: number | null; p90: number | null }
export interface Run { id: string; run_id: string; kind: string; status: 'queued'|'running'|'succeeded'|'failed'; result_id: string | null; error: string | null }
export class ApiError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }
export class ApiClient {
  csrf = '';
  onUnauthorized?: (error: ApiError) => void;
  constructor(public base = '/api/v1', public token?: () => Promise<string | null>) {}
  async request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const csrfAtStart = this.csrf;
    const headers = new Headers(options.headers);
    if (options.body) headers.set('Content-Type', 'application/json');
    if (this.csrf) headers.set('X-CSRF-Token', this.csrf);
    const token = await this.token?.();
    if (token) headers.set('Authorization', `Bearer ${token}`);
    let response: Response;
    try { response = await fetch(`${this.base}${path}`, { ...options, headers, credentials: this.token ? 'omit' : 'include' }); }
    catch { throw new ApiError(0, 'offline', 'Сервермен байланыс жоқ. Подключение к серверу отсутствует.'); }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = body.detail ?? body;
      const error = new ApiError(response.status, detail.code || String(response.status), typeof detail === 'string' ? detail : detail.message || JSON.stringify(detail));
      // A delayed response from a previous browser session must not sign out a new login.
      if (!this.token && csrfAtStart && this.csrf === csrfAtStart && response.status === 401 && error.code === 'AUTH_REQUIRED') {
        this.csrf = '';
        this.onUnauthorized?.(error);
      }
      throw error;
    }
    return response.status === 204 ? undefined as T : response.json();
  }
  async session() { const data = await this.request<{user:User;csrf_token:string}>('/session/me'); this.csrf=data.csrf_token; return data.user; }
  async login(email:string,password:string) { const data=await this.request<{user:User;csrf_token:string}>('/session/login',{method:'POST',body:JSON.stringify({email,password})});this.csrf=data.csrf_token;return data.user; }
  post<T=any>(path:string,body:unknown,headers?:Record<string,string>) { return this.request<T>(path,{method:'POST',body:JSON.stringify(body),headers}); }
}
