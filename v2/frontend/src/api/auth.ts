export type AuthRole = 'guest' | 'viewer' | 'trader' | 'admin' | 'superadmin';

export interface CredentialStatus {
  credential_scope?: string;
  source_type: string;
  configured: boolean;
  status: string;
  read_only_required: boolean;
  live_trading_enabled: boolean;
  binding_blocked_reason?: string | null;
  raw_credential_value_exposed: boolean;
  checked_at?: string;
}

export interface ExchangeAccount {
  id: string;
  trader_id?: string | null;
  paper_account_id?: string | null;
  exchange: string;
  label: string;
  account_type: string;
  mode: string;
  read_only: boolean;
  live_trading_enabled: boolean;
  status: string;
  credential_status?: CredentialStatus;
  created_at?: string;
  updated_at?: string;
}

export interface AuthUser {
  id: string;
  trader_id: string | null;
  username: string;
  email: string;
  role: AuthRole;
  paper_account_id: string | null;
  exchange_accounts: ExchangeAccount[];
  watchlist: string[];
  alert_preferences: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_login: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}

export interface AuthHealthSessionSecurity {
  cookie_name?: string;
  token_type?: string;
  http_only_cookie?: boolean;
  secure_cookie?: boolean;
  same_site?: string;
}

export interface AuthHealth {
  schema_version: string;
  generated_at_utc?: string;
  generated_at_et?: string;
  source?: string;
  status: string;
  staleness_seconds?: number;
  freshness_status?: string;
  canonical_owner?: string;
  data_quality_status?: string;
  login_endpoint_available: boolean;
  auth_store_backend?: string;
  durable_user_store_configured?: boolean;
  production_ready?: boolean;
  contains_secret_values: boolean;
  raw_credential_value_exposed: boolean;
  live_gate: string;
  places_real_order: boolean;
  routes_to_live: boolean;
  exchange_mutation_enabled?: boolean;
  session_security?: AuthHealthSessionSecurity;
  warnings?: string[];
}

export class AuthApiError extends Error {
  status: number | null;
  detail: string | null;

  constructor(message: string, status: number | null = null, detail: string | null = null) {
    super(message);
    this.name = 'AuthApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function responseDetail(response: Response): Promise<string | null> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) return null;
  try {
    const payload = await response.clone().json() as { detail?: unknown; error?: unknown; message?: unknown };
    const detail = payload.detail ?? payload.error ?? payload.message;
    return typeof detail === 'string' && detail.trim() ? detail.trim() : null;
  } catch {
    return null;
  }
}

function signInErrorMessage(status: number | null, detail: string | null): string {
  if (status === 401 || detail === 'invalid_credentials') return 'Invalid email or password';
  if (status === 403) return 'This account is not allowed to sign in';
  if (status === 404) return 'Sign-in endpoint is not deployed on this server';
  if (status === 408 || status === 429) return 'Sign-in is temporarily throttled. Try again shortly';
  if (status === 503 || status === 504 || detail === 'auth_service_unavailable') {
    return 'Sign-in service is temporarily unavailable. Try again shortly';
  }
  if (status !== null && status >= 500) return 'Sign-in service returned an error. Try again shortly';
  if (status !== null && status >= 400) return 'Sign-in request was rejected';
  return 'Sign-in service unavailable';
}

async function parseJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    throw new AuthApiError('Authentication service returned an unexpected response', response.status, null);
  }
  return response.json() as Promise<T>;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  let timeoutId: number | null = null;
  const timeoutPromise = new Promise<null>((resolve) => {
    timeoutId = window.setTimeout(() => resolve(null), 3000);
  });
  try {
    const response = await Promise.race([
      fetch('/api/auth/me', { credentials: 'include' }),
      timeoutPromise,
    ]);
    if (!response) return null;
    if (response.status === 401 || response.status === 403 || response.status === 404) return null;
    if (!response.ok) throw new Error('Authentication check failed');
    const payload = await parseJson<{ user: AuthUser }>(response);
    return payload.user;
  } catch {
    return null;
  } finally {
    if (timeoutId !== null) window.clearTimeout(timeoutId);
  }
}

export async function fetchAuthHealth(): Promise<AuthHealth> {
  let response: Response;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 4000);
  try {
    response = await fetch('/api/auth/health', {
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new AuthApiError('Auth health check timed out', null, 'request_timeout');
    }
    throw new AuthApiError('Cannot reach auth health endpoint', null, 'network_error');
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (!response.ok) {
    const detail = await responseDetail(response);
    throw new AuthApiError('Auth health endpoint returned an error', response.status, detail);
  }
  try {
    return await parseJson<AuthHealth>(response);
  } catch (error) {
    if (error instanceof AuthApiError) throw error;
    throw new AuthApiError('Auth health endpoint returned an invalid response', response.status, 'invalid_json');
  }
}

export async function loginWithPassword(request: LoginRequest): Promise<LoginResponse> {
  let response: Response;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 8000);
  try {
    response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new AuthApiError('Sign-in request timed out. Try again shortly', null, 'request_timeout');
    }
    throw new AuthApiError('Cannot reach sign-in service. Check the connection and try again', null, 'network_error');
  } finally {
    window.clearTimeout(timeoutId);
  }
  if (!response.ok) {
    const detail = await responseDetail(response);
    throw new AuthApiError(signInErrorMessage(response.status, detail), response.status, detail);
  }
  try {
    return await parseJson<LoginResponse>(response);
  } catch (error) {
    if (error instanceof AuthApiError) throw error;
    throw new AuthApiError('Sign-in service returned an invalid response', response.status, 'invalid_json');
  }
}

export async function logoutSession(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => undefined);
}

export async function updateMyWatchlist(symbols: string[]): Promise<AuthUser> {
  const response = await fetch('/api/accounts/me/watchlist', {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols }),
  });
  if (!response.ok) {
    throw new Error(response.status === 400 ? 'Enter valid market symbols only' : 'Watchlist update unavailable');
  }
  const payload = await parseJson<{ user: AuthUser; watchlist: string[] }>(response);
  return payload.user;
}
