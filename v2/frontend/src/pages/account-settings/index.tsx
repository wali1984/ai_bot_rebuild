import { useState, type FormEvent } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useRoles } from '../../auth/rbac';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { updateMyWatchlist } from '../../api/auth';
import { Panel, Metric } from '../cockpitComponents';
import { CanonicalMetricCard, CanonicalMetricValue } from '../../components/data/CanonicalMetric';
import { selectAccountMetric } from '../../selectors/accountSelectors';
import { normalizeWatchlistInput } from '../../lib/traderPageHelpers';
import type { ExchangeAccount } from '../../api/auth';
import meta from './meta';
import rbac from './rbac';
import route from './route';

const SUPPORTED_EXCHANGES = ['binance', 'kucoin', 'bybit'] as const;
type Exchange = (typeof SUPPORTED_EXCHANGES)[number];

export { normalizeWatchlistInput };

function friendlyAccountError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error ?? '');
  if (/invalid_watchlist_symbol/i.test(raw)) return 'One or more symbols could not be saved. Use market symbols such as BTCUSDT.';
  if (/watchlist_limit_exceeded/i.test(raw)) return 'Watchlist limit reached. Save up to 100 symbols.';
  if (/trader_account_scope_required/i.test(raw)) return 'Trader account scope is required before linking an exchange account.';
  if (/trader_role_required/i.test(raw)) return 'Trader approval is required before linking an exchange account.';
  if (/unsupported_exchange/i.test(raw)) return 'That exchange is not available for account linking yet.';
  if (/exchange_account_exists/i.test(raw)) return 'That exchange account is already linked.';
  if (/exchange_account_metadata_only/i.test(raw)) return 'Account labels cannot contain private exchange values.';
  if (/401|unauth/i.test(raw)) return 'Sign in required to update account settings.';
  if (/403|forbidden/i.test(raw)) return 'This account does not have permission to change that setting.';
  if (/failed|error/i.test(raw)) return 'Account settings update unavailable. Try again after the service reconnects.';
  return 'Account settings update unavailable.';
}

function containsPrivateExchangeValue(value: string): boolean {
  return /(api[_ -]?key|api[_ -]?secret|private[_ -]?key|secret|credential[_ -]?ref|access[_ -]?token)/i.test(value);
}

function accountRoleLabel(role: string | null | undefined): string {
  switch ((role ?? '').toLowerCase()) {
    case 'viewer':
      return 'Viewer';
    case 'trader':
      return 'Trader';
    case 'admin':
    case 'superadmin':
      return 'Privileged access';
    case 'guest':
      return 'Guest';
    default:
      return 'Access pending';
  }
}

function accountTypeLabel(value: string | null | undefined): string {
  if (!value) return 'Account type unavailable';
  return value
    .replace(/_/g, ' ')
    .replace(/\busd m\b/i, 'USD-M')
    .replace(/\bcoin m\b/i, 'COIN-M')
    .replace(/^./u, (char) => char.toUpperCase());
}

function accountModeLabel(value: string | null | undefined): string {
  if (!value) return 'Live account';
  if (/paper/i.test(value)) return 'Live account';
  if (/read/i.test(value)) return 'Live account';
  return 'Live account';
}

function AccountRow({ account, onRemove }: { account: ExchangeAccount; onRemove: (id: string) => void }): JSX.Element {
  const [removing, setRemoving] = useState(false);

  async function handleRemove(): Promise<void> {
    if (!window.confirm(`Unlink ${account.label}?`)) return;
    setRemoving(true);
    try {
      const res = await fetch(`/api/accounts/me/exchange-accounts/${encodeURIComponent(account.id)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      onRemove(account.id);
    } catch (e) {
      window.alert(friendlyAccountError(e));
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="account-exchange-row">
      <div className="account-exchange-info">
        <div className="account-exchange-header">
          <span className={`account-exchange-badge account-exchange-badge--${account.exchange}`}>
            {account.exchange.toUpperCase()}
          </span>
          <strong>{account.label}</strong>
        </div>
        <div className="account-exchange-chips">
          <span className="chip">{accountTypeLabel(account.account_type)}</span>
          <span className="chip solid-paper">{accountModeLabel(account.mode)}</span>
          {account.read_only && <span className="chip solid-ok">Account access</span>}
          <span className="chip solid-ok">Real-time platform</span>
          <span className="chip" title="Trading workspace this exchange metadata is bound to">
            {account.paper_account_id ? 'Workspace linked' : 'Workspace unavailable'}
          </span>
          <span className="chip" style={{ opacity: 0.7, fontSize: '0.7rem' }}>
            {account.credential_status?.configured ? 'Account access configured' : 'Account access pending'}
          </span>
        </div>
      </div>
      <button className="account-btn-danger" onClick={handleRemove} disabled={removing}>
        {removing ? 'Removing…' : 'Unlink'}
      </button>
    </div>
  );
}

function LinkExchangeForm({ onLinked }: { onLinked: () => void }): JSX.Element {
  const [exchange, setExchange] = useState<Exchange>('binance');
  const [label, setLabel] = useState('');
  const [accountType, setAccountType] = useState('usd_m_futures');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    if (containsPrivateExchangeValue(label) || containsPrivateExchangeValue(accountType)) {
      setError('Account labels cannot contain private exchange values.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch('/api/accounts/me/exchange-accounts', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exchange, label: label.trim(), account_type: accountType }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail ?? `Error ${res.status}`);
      setSuccess(true);
      setLabel('');
      setTimeout(() => { setSuccess(false); onLinked(); }, 1200);
    } catch (e) {
      setError(friendlyAccountError(e));
    } finally {
      setSubmitting(false);
    }
  }

  const accountTypeOptions: Record<Exchange, { value: string; label: string }[]> = {
    binance: [
      { value: 'usd_m_futures', label: 'USD-M Futures' },
      { value: 'spot', label: 'Spot' },
      { value: 'coin_m_futures', label: 'COIN-M Futures' },
    ],
    kucoin: [
      { value: 'spot', label: 'Spot' },
      { value: 'futures', label: 'Futures' },
    ],
    bybit: [
      { value: 'unified', label: 'Unified' },
      { value: 'spot', label: 'Spot' },
    ],
  };
  const metadataLooksPrivate = containsPrivateExchangeValue(label) || containsPrivateExchangeValue(accountType);

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 16, maxWidth: 520 }}>
      <div className="form-field">
        <span className="form-label">Exchange</span>
        <div className="exchange-picker">
          {SUPPORTED_EXCHANGES.map((ex) => (
            <button
              key={ex}
              type="button"
              className={`exchange-picker__btn${exchange === ex ? ' exchange-picker__btn--active' : ''}`}
              onClick={() => { setExchange(ex); setAccountType(accountTypeOptions[ex][0].value); }}
            >
              {ex.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="exchange-label">Account label</label>
        <input
          id="exchange-label"
          className="form-input"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={`e.g. My ${exchange.charAt(0).toUpperCase() + exchange.slice(1)} Futures`}
          required
        />
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="account-type">Account type</label>
        <select
          id="account-type"
          className="form-select"
          value={accountType}
          onChange={(e) => setAccountType(e.target.value)}
        >
          {(accountTypeOptions[exchange] ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <p className="form-hint">
        Account access is managed through the secure account-link workflow. This form links account metadata only.
        It never accepts private exchange values directly.
      </p>

      {metadataLooksPrivate && <p className="form-error">Account labels cannot contain private exchange values.</p>}
      {error && <p className="form-error">{error}</p>}
      {success && <p className="form-success">Account linked successfully.</p>}

      <button type="submit" className="form-btn-primary" disabled={submitting || !label.trim() || metadataLooksPrivate}>
        {submitting ? 'Linking…' : `Link ${exchange.charAt(0).toUpperCase() + exchange.slice(1)} account`}
      </button>
    </form>
  );
}

function ChangePasswordForm(): JSX.Element {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch('/api/accounts/me/change-password', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail ?? `Error ${res.status}`);
      setSuccess(true);
      setCurrent('');
      setNext('');
    } catch (e) {
      setError(friendlyAccountError(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 14, maxWidth: 400 }}>
      <div className="form-field">
        <label className="form-label" htmlFor="pwd-current">Current password</label>
        <input
          id="pwd-current"
          type="password"
          className="form-input"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          required
        />
      </div>
      <div className="form-field">
        <label className="form-label" htmlFor="pwd-new">New password (min 8 chars)</label>
        <input
          id="pwd-new"
          type="password"
          className="form-input"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          required
          minLength={8}
        />
      </div>
      {error && <p className="form-error">{error}</p>}
      {success && <p className="form-success">Password changed successfully.</p>}
      <button
        type="submit"
        className="form-btn-primary"
        disabled={submitting || !current || next.length < 8}
      >
        {submitting ? 'Changing…' : 'Change password'}
      </button>
    </form>
  );
}

function WatchlistForm({
  symbols,
  onSaved,
}: {
  symbols: string[];
  onSaved: () => Promise<void>;
}): JSX.Element {
  const [value, setValue] = useState(symbols.join(', '));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const normalized = normalizeWatchlistInput(value);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(false);
    try {
      await updateMyWatchlist(normalized);
      setValue(normalized.join(', '));
      setSuccess(true);
      await onSaved();
    } catch (err) {
      setError(friendlyAccountError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 12, maxWidth: 620 }}>
      <label className="form-field" htmlFor="account-watchlist-input">
        <span className="form-label">Market symbols</span>
        <textarea
          id="account-watchlist-input"
          className="form-input"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          rows={3}
          placeholder="BTCUSDT, ETHUSDT, BNBUSDT"
        />
      </label>
      <p className="form-hint">
        Symbols are saved to your signed-in trader profile and used by Markets, Trade, and ProChart.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {normalized.length ? normalized.map((symbol) => <span key={symbol} className="chip">{symbol}</span>) : (
          <span className="chip solid-warn">No valid symbols</span>
        )}
      </div>
      {error && <p className="form-error">{error}</p>}
      {success && <p className="form-success">Watchlist saved.</p>}
      <button type="submit" className="form-btn-primary" disabled={submitting}>
        {submitting ? 'Saving…' : 'Save watchlist'}
      </button>
    </form>
  );
}

export default function AccountSettingsPage(): JSX.Element {
  const { user, refresh } = useAuth();
  const sessionRole = useRoles();
  const traderSnapshot = useTraderSnapshot();
  const [showLinkForm, setShowLinkForm] = useState(false);

  const accounts: ExchangeAccount[] = user?.exchange_accounts ?? [];
  const localTraderPreview = !user && sessionRole === 'trader';
  const hasAccountScope = Boolean(user?.trader_id && user?.paper_account_id) || localTraderPreview;
  const hasTraderApproval = user?.role === 'trader' || localTraderPreview;
  const canLinkExchange = Boolean(hasAccountScope && hasTraderApproval);
  const exchangeLinkUnavailableCopy = !hasAccountScope
    ? 'Exchange linking requires an assigned trader profile and execution workspace.'
    : !hasTraderApproval
      ? 'Trader approval is required before linking an exchange account.'
      : 'No exchange accounts linked yet. Click "+ Link account" to connect Binance, KuCoin, or Bybit.';
  const accountMetric = (fieldId: string) => selectAccountMetric(traderSnapshot, fieldId);

  async function handleRemove(_id: string): Promise<void> {
    await refresh();
  }

  async function handleLinked(): Promise<void> {
    setShowLinkForm(false);
    await refresh();
  }

  return (
    <article
      className="enterprise-cockpit-page"
      data-testid="page-account-settings"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Account</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="enterprise-cockpit-hero-chips">
          <span className="chip solid-paper">Real-time platform</span>
          <span className={`chip ${hasAccountScope ? 'solid-ok' : 'solid-warn'}`}>
            {hasAccountScope ? 'Account scope complete' : 'Account scope incomplete'}
          </span>
          <span className="chip solid-warn">Execution restricted</span>
        </div>
      </header>

      <Panel id="account-canonical-status" title="Trader Account Source">
        <div className="trader-metric-grid">
          <CanonicalMetricCard label="Trader ID" metric={accountMetric('account.trader_id')} />
          <CanonicalMetricCard label="Account ID" metric={accountMetric('account.account_id')} />
          <CanonicalMetricCard label="Account Mode" metric={accountMetric('account.mode')} />
          <CanonicalMetricCard label="Account Connection" metric={accountMetric('account.connection_status')} />
          <CanonicalMetricCard label="Equity" metric={accountMetric('account.equity')} />
          <CanonicalMetricCard
            label="Available Balance"
            metric={accountMetric('account.available_balance')}
            emptyText="Paper balance unavailable; live signed account not read"
          />
        </div>
        <div className="cockpit-analytics-grid" style={{ marginTop: 14 }}>
          <Metric label="Backend session" value={user?.is_active ? 'Active' : 'Access unavailable'} />
          <Metric label="Session role" value={accountRoleLabel(user?.role ?? sessionRole)} />
          <Metric label="Exchange accounts" value={String(accounts.length)} />
          <div className="cockpit-metric">
            <span>Last account refresh</span>
            <strong>
              <CanonicalMetricValue metric={accountMetric('account.connection_status')} emptyText="Source offline" />
            </strong>
          </div>
        </div>
      </Panel>

      <Panel id="account-profile" title="Profile">
        <div className="cockpit-analytics-grid">
          <Metric label="Username" value={user?.username ?? 'Unavailable'} />
          <Metric label="Email" value={user?.email ?? 'Unavailable'} />
          <Metric label="Access level" value={accountRoleLabel(user?.role)} />
          <Metric label="Trading profile" value={user?.trader_id || localTraderPreview ? 'Connected' : 'Unavailable'} />
          <Metric label="Trading workspace" value={user?.paper_account_id || localTraderPreview ? 'Connected' : 'Unavailable'} />
          <Metric label="Status" value={user?.is_active ? 'Active' : 'Inactive'} />
        </div>
      </Panel>

      <Panel
        id="account-exchanges"
        title="Linked Exchange Accounts"
        right={
          <button
            className={`form-btn-secondary${showLinkForm ? ' active' : ''}`}
            onClick={() => setShowLinkForm((v) => !v)}
            disabled={!canLinkExchange}
            title={canLinkExchange ? 'Link exchange account metadata' : exchangeLinkUnavailableCopy}
          >
            {showLinkForm ? '✕ Cancel' : '+ Link account'}
          </button>
        }
      >
        {accounts.length === 0 && !showLinkForm && (
          <p className="cockpit-evidence-gap">
            {exchangeLinkUnavailableCopy}
          </p>
        )}
        {accounts.map((account) => (
          <AccountRow key={account.id} account={account} onRemove={handleRemove} />
        ))}

        {showLinkForm && canLinkExchange && (
          <div className="account-link-form-wrap">
            <p className="eyebrow" style={{ marginTop: 0, marginBottom: 14 }}>Link new exchange account</p>
            <div className="account-link-notice">
              <p className="account-link-notice-title">Safety notice</p>
              <p className="account-link-notice-body">
                Use the secure account-link workflow for exchange access references. This page stores account metadata only.
              </p>
            </div>
            <LinkExchangeForm onLinked={handleLinked} />
          </div>
        )}
        <p className="cockpit-evidence-note" style={{ marginTop: 12 }}>
          Exchange account metadata is scoped to the active trading workspace.
        </p>
      </Panel>

      <Panel id="account-password" title="Change Password">
        <ChangePasswordForm />
      </Panel>

      <Panel id="account-watchlist" title="Watchlist">
        <WatchlistForm key={(user?.watchlist ?? []).join('|')} symbols={user?.watchlist ?? []} onSaved={refresh} />
      </Panel>
    </article>
  );
}
