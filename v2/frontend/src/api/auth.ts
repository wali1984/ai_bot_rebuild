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

async function parseJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) throw new Error('Authentication service unavailable');
  return response.json() as Promise<T>;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetch('/api/auth/me', { credentials: 'include', signal: controller.signal });
    if (response.status === 401 || response.status === 403 || response.status === 404) return null;
    if (!response.ok) throw new Error('Authentication check failed');
    const payload = await parseJson<{ user: AuthUser }>(response);
    return payload.user;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function loginWithPassword(request: LoginRequest): Promise<LoginResponse> {
  let response: Response;
  try {
    response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
  } catch {
    throw new Error('Sign-in service unavailable');
  }
  if (!response.ok) {
    throw new Error(response.status === 401 ? 'Invalid email or password' : 'Sign-in service unavailable');
  }
  try {
    return await parseJson<LoginResponse>(response);
  } catch {
    throw new Error('Sign-in service unavailable');
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
