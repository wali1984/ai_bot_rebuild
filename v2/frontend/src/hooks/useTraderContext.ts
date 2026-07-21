import { useMemo } from 'react';
import { useAuth } from './useAuth';
import { useRoles } from '../auth/rbac';
import type { AuthUser, ExchangeAccount } from '../api/auth';

const LOCAL_TRADER_PREVIEW_ID = 'trader-wajidali1984';
const LOCAL_PAPER_PREVIEW_ID = 'paper-wajidali1984';

function prettyExchange(account: ExchangeAccount | null): string {
  if (!account) return 'Exchange account connecting';
  const exchangeKey = account.exchange?.toLowerCase();
  const exchange = exchangeKey === 'binance'
    ? 'Binance'
    : account.exchange
      ? account.exchange.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
      : 'Exchange';
  const typeKey = account.account_type?.toLowerCase();
  const type = typeKey === 'usd_m_futures' || typeKey === 'usdm_futures'
    ? 'USD M Futures'
    : account.account_type
      ? account.account_type.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
      : 'Account';
  return `${exchange} ${type}`.toUpperCase();
}

function prettyCredentialStatus(account: ExchangeAccount | null, signedIn: boolean): string {
  if (!signedIn) return 'Sign in for trader-specific account';
  const status = account?.credential_status;
  if (!account) return 'Exchange account connecting';
  if (status?.status === 'credential_binding_blocked') return 'Account link pending';
  if (status?.configured && status.read_only_required) return 'Account access configured';
  if (status?.configured) return 'Account access configured';
  if (status?.status === 'credential_binding_required' || account.status === 'credential_binding_required') {
    return 'Account link setup required';
  }
  // These states are hard-unavailable, not transient — "connecting" would imply an
  // in-progress connection that will resolve on its own, which is dishonest here.
  if (status?.status === 'credential_reference_missing') return 'Account access unavailable — no credential on file';
  if (status?.status === 'credential_source_pending' || account.status === 'credential_source_pending') {
    return 'Account access unavailable — credential source not configured';
  }
  return 'Account access pending';
}

function accountMatchesUserScope(account: ExchangeAccount, user: AuthUser | null | undefined): boolean {
  return Boolean(
    user?.trader_id
    && user.paper_account_id
    && account.trader_id === user.trader_id
    && account.paper_account_id === user.paper_account_id
    && account.read_only === true
    && account.live_trading_enabled === false,
  );
}

export function selectPrimaryExchangeAccount(accounts: ExchangeAccount[], user: AuthUser | null | undefined): ExchangeAccount | null {
  if (!user?.trader_id || !user.paper_account_id) return null;
  const binanceAccounts = accounts.filter((account) => account.exchange?.toLowerCase() === 'binance');
  return (
    binanceAccounts.find((account) => accountMatchesUserScope(account, user))
    ?? accounts.find((account) => accountMatchesUserScope(account, user))
    ?? null
  );
}

export function useTraderContext() {
  const { user, loading } = useAuth();
  const sessionRole = useRoles();

  return useMemo(() => {
    const accounts = user?.exchange_accounts ?? [];
    const primaryExchangeAccount = selectPrimaryExchangeAccount(accounts, user);
    const localTraderPreview = !user && sessionRole === 'trader';
    const displayName = user?.username || user?.email || (localTraderPreview ? 'wajidali1984' : 'Public preview');
    const hasTraderScope = Boolean(user && user.trader_id && user.paper_account_id) || localTraderPreview;
    const accountLabel = primaryExchangeAccount?.label ?? (user
      ? hasTraderScope
        ? 'Trading workspace connected'
        : 'Account scope incomplete'
      : localTraderPreview
        ? 'Trading workspace connected'
        : 'Public market preview');
    const accountScopeLabel = !user && !localTraderPreview
      ? 'Public market preview'
      : hasTraderScope
        ? 'Authenticated trader account'
        : 'Account scope incomplete';
    const accountBindingVerified = Boolean(
      primaryExchangeAccount && accountMatchesUserScope(primaryExchangeAccount, user),
    );
    const accountBindingStatus = !user
      ? 'Sign in for trader account scope'
      : !hasTraderScope
        ? 'Account scope incomplete'
      : accountBindingVerified
        ? 'Trading workspace connected'
        : 'Exchange account connecting';
    const credentialStatus = prettyCredentialStatus(primaryExchangeAccount, Boolean(user));
    const credentialStatusDetail = primaryExchangeAccount?.credential_status
      ? 'Account access checked; no private values are exposed'
      : credentialStatus;

    return {
      loading,
      user,
      displayName,
      traderId: user?.trader_id ?? (localTraderPreview ? LOCAL_TRADER_PREVIEW_ID : null),
      paperAccountId: user?.paper_account_id ?? (localTraderPreview ? LOCAL_PAPER_PREVIEW_ID : null),
      exchangeAccounts: accounts,
      primaryExchangeAccount,
      accountLabel,
      exchangeLabel: prettyExchange(primaryExchangeAccount),
      accountScopeLabel,
      accountBindingVerified,
      accountBindingStatus,
      credentialStatus,
      credentialStatusDetail,
      readOnly: primaryExchangeAccount?.read_only ?? true,
      liveTradingEnabled: false,
    };
  }, [loading, sessionRole, user]);
}
