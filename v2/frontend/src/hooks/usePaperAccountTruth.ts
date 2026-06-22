import { useEffect, useMemo, useState } from 'react';
import { getV2Portfolio } from '../api/v2Portfolio';
import type { ApiV2Envelope, PortfolioData } from '../types/apiV2';
import { usePayloadFile } from './usePayloadFile';
import { useAuth } from './useAuth';
import { finite } from '../lib/tradeFormatters';

export const PAPER_ACCOUNT_TRUTH_PATH = '/operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json';
export const RUNTIME_PAGES_PATH = '/operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json';
export const PORTFOLIO_STATE_PATH = '/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json';

interface PaperAccountTruthPayload {
  generated_at?: string;
  generated_utc?: string;
  paper_equity?: number | null;
  paper_pnl?: number | null;
  paper_realized_pnl_usd?: number | null;
  paper_unrealized_pnl_usd?: number | null;
  paper_open_positions_count?: number | null;
  paper_closed_positions_count?: number | null;
  paper_equity_source?: string | null;
}

interface RuntimePagesPayload {
  generated_utc?: string;
  generated_est?: string;
  paper_current_session_equity?: number | null;
  paper_current_session_pnl?: number | null;
  paper_current_session_open_positions?: number | null;
}

interface PortfolioStatePayload {
  generated_utc?: string;
  account_mode?: string;
  equity?: number | null;
  cash_balance?: number | null;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  net_unrealized_pnl?: number | null;
  total_pnl_usd?: number | null;
  total_notional?: number | null;
  open_position_notional?: number | null;
  open_positions_count?: number | null;
  closed_positions_count?: number | null;
  paper_equity_source?: string | null;
  paper_equity_reason?: string | null;
}

export interface PaperAccountTruth {
  equity: number | null;
  totalPnl: number | null;
  realizedPnl: number | null;
  unrealizedPnl: number | null;
  cashBalance: number | null;
  totalNotional: number | null;
  openPositions: number | null;
  closedPositions: number | null;
  currency: 'USDT';
  accountMode: string;
  source: string;
  reason: string | null;
  generatedAt: string | null;
}

interface UsePaperAccountTruthOptions {
  requireTraderScope?: boolean;
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const n = finite(value);
    if (n !== null) return n;
  }
  return null;
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return null;
}

function scopeToken(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function traderFacingText(value: string): string {
  return value
    .trim()
    .replace(/\bPaper\/static\b/gi, 'Account data')
    .replace(/\bpaper account\b/gi, 'account')
    .replace(/\bpaper\b/gi, 'runtime')
    .replace(/\bstatic[_ -]?payload\b/gi, 'data snapshot')
    .replace(/\bpayloads?\b/gi, 'data feed')
    .replace(/\/api\/v2\/portfolio/gi, 'account service')
    .replace(/\bAPI\b/g, 'service');
}

function traderFacingSource(value: string | null | undefined): string {
  const source = value?.trim();
  if (!source) return 'Account service';
  if (source.startsWith('/api/') || source.includes('.json')) return 'Account service';
  return traderFacingText(source);
}

function traderFacingReason(value: string | null | undefined): string | null {
  return value?.trim() ? traderFacingText(value) : null;
}

function scopedUnavailableAccount(reason: string, source = '/api/v2/portfolio'): PaperAccountTruth {
  return {
    equity: null,
    totalPnl: null,
    realizedPnl: null,
    unrealizedPnl: null,
    cashBalance: null,
    totalNotional: null,
    openPositions: null,
    closedPositions: null,
    currency: 'USDT',
    accountMode: 'paper',
    source: traderFacingSource(source),
    reason: traderFacingReason(reason),
    generatedAt: null,
  };
}

export function typedPortfolioMatchesCurrentScope(
  portfolio: ApiV2Envelope<PortfolioData> | null,
  traderId: string | null,
  paperAccountId: string | null,
): boolean {
  const data = portfolio?.data;
  if (!portfolio || !data || !traderId || !paperAccountId) return false;
  const accountSpecific = data.account_specific === true || portfolio.account_scope?.scope_verified === true;
  if (!accountSpecific) return false;
  const dataTraderId = scopeToken(data.trader_id);
  const dataPaperAccountId = scopeToken(data.paper_account_id);
  const dataScopePresent = Boolean(dataTraderId || dataPaperAccountId);
  const dataMatches = dataTraderId === traderId && dataPaperAccountId === paperAccountId;
  const proofPresent = Boolean(portfolio.account_scope);
  const proofMatches = (
    portfolio.account_scope?.scope_verified === true
    && scopeToken(portfolio.account_scope.trader_id) === traderId
    && scopeToken(portfolio.account_scope.paper_account_id) === paperAccountId
  );
  if (dataScopePresent && !dataMatches) return false;
  if (proofPresent && portfolio.account_scope?.scope_verified === true && !proofMatches) return false;
  return dataMatches || proofMatches;
}

export function resolveTypedPortfolioAccount(
  portfolio: ApiV2Envelope<PortfolioData> | null,
  traderId: string | null,
  paperAccountId: string | null,
): PaperAccountTruth {
  const data = portfolio?.data;
  if (!portfolio || !data) {
    return scopedUnavailableAccount(
      portfolio?.warnings?.[0] ?? 'Trader-specific account source unavailable',
      portfolio?.endpoint ?? '/api/v2/portfolio',
    );
  }
  if (!typedPortfolioMatchesCurrentScope(portfolio, traderId, paperAccountId)) {
    return scopedUnavailableAccount(
      portfolio.warnings?.[0] ?? 'Trader-specific account data unavailable or withheld',
      portfolio.endpoint,
    );
  }
  const realizedPnl = finite(data.realized_pnl);
  const unrealizedPnl = finite(data.unrealized_pnl);
  const totalPnl = realizedPnl !== null && unrealizedPnl !== null
    ? realizedPnl + unrealizedPnl
    : null;
  return {
    equity: finite(data.equity),
    totalPnl,
    realizedPnl,
    unrealizedPnl,
    cashBalance: null,
    totalNotional: null,
    openPositions: Array.isArray(data.positions) ? data.positions.length : null,
    closedPositions: null,
    currency: 'USDT',
    accountMode: data.mode,
    source: traderFacingSource(portfolio.source),
    reason: portfolio.missing_fields.length
      ? 'Trader-specific account data incomplete'
      : traderFacingReason(portfolio.warnings?.[0]),
    generatedAt: portfolio.timestamp,
  };
}

export function resolvePaperAccountTruth(
  truth: PaperAccountTruthPayload | null,
  runtimePages: RuntimePagesPayload | null,
  portfolio: PortfolioStatePayload | null,
): PaperAccountTruth {
  const realizedPnl = firstNumber(portfolio?.realized_pnl_usd, truth?.paper_realized_pnl_usd);
  const unrealizedPnl = firstNumber(portfolio?.unrealized_pnl_usd, portfolio?.net_unrealized_pnl, truth?.paper_unrealized_pnl_usd);
  const summedPnl = realizedPnl !== null && unrealizedPnl !== null ? realizedPnl + unrealizedPnl : null;
  const totalPnl = firstNumber(portfolio?.total_pnl_usd, runtimePages?.paper_current_session_pnl, truth?.paper_pnl, summedPnl);

  return {
    equity: firstNumber(runtimePages?.paper_current_session_equity, truth?.paper_equity, portfolio?.equity),
    totalPnl,
    realizedPnl,
    unrealizedPnl,
    cashBalance: firstNumber(portfolio?.cash_balance),
    totalNotional: firstNumber(portfolio?.total_notional, portfolio?.open_position_notional),
    openPositions: firstNumber(portfolio?.open_positions_count, runtimePages?.paper_current_session_open_positions, truth?.paper_open_positions_count),
    closedPositions: firstNumber(portfolio?.closed_positions_count, truth?.paper_closed_positions_count),
    currency: 'USDT',
    accountMode: firstText(portfolio?.account_mode) ?? 'paper',
    source: traderFacingSource(firstText(portfolio?.paper_equity_source, truth?.paper_equity_source) ?? 'Trader account source'),
    reason: traderFacingReason(firstText(portfolio?.paper_equity_reason)),
    generatedAt: firstText(runtimePages?.generated_utc, runtimePages?.generated_est, truth?.generated_utc, truth?.generated_at, portfolio?.generated_utc),
  };
}

export function usePaperAccountTruth(intervalMs = 8_000, options: UsePaperAccountTruthOptions = {}): {
  account: PaperAccountTruth;
  loading: boolean;
  error: string | null;
  ageSeconds: number | null;
  paths: {
    truth: string;
    runtimePages: string;
    portfolio: string;
  };
} {
  const { user, loading: authLoading } = useAuth();
  const traderId = user?.trader_id ?? null;
  const paperAccountId = user?.paper_account_id ?? null;
  const [typedPortfolio, setTypedPortfolio] = useState<ApiV2Envelope<PortfolioData> | null>(null);
  const [typedLoading, setTypedLoading] = useState(Boolean(options.requireTraderScope));
  const fallbackPayloadsEnabled = options.requireTraderScope !== true;
  const truth = usePayloadFile<PaperAccountTruthPayload>(PAPER_ACCOUNT_TRUTH_PATH, intervalMs, { enabled: fallbackPayloadsEnabled });
  const runtimePages = usePayloadFile<RuntimePagesPayload>(RUNTIME_PAGES_PATH, intervalMs, { enabled: fallbackPayloadsEnabled });
  const portfolio = usePayloadFile<PortfolioStatePayload>(PORTFOLIO_STATE_PATH, intervalMs, { enabled: fallbackPayloadsEnabled });

  useEffect(() => {
    if (!options.requireTraderScope) return undefined;
    let active = true;
    setTypedPortfolio(null);
    if (!traderId || !paperAccountId) {
      setTypedLoading(false);
      return () => {
        active = false;
      };
    }

    async function loadTypedPortfolio(): Promise<void> {
      setTypedLoading(true);
      try {
        const next = await getV2Portfolio();
        if (!active) return;
        setTypedPortfolio(next);
      } catch {
        if (!active) return;
        setTypedPortfolio(null);
      } finally {
        if (active) setTypedLoading(false);
      }
    }

    void loadTypedPortfolio();
    const id = window.setInterval(loadTypedPortfolio, intervalMs);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [intervalMs, options.requireTraderScope, paperAccountId, traderId]);

  const account = useMemo(
    () => {
      if (!options.requireTraderScope) {
        return resolvePaperAccountTruth(truth.data, runtimePages.data, portfolio.data);
      }
      if (authLoading) {
        return scopedUnavailableAccount('Checking signed-in trader account scope');
      }
      if (!user) {
        return scopedUnavailableAccount('Sign in to view trader-specific account');
      }
      return resolveTypedPortfolioAccount(typedPortfolio, traderId, paperAccountId);
    },
    [authLoading, options.requireTraderScope, paperAccountId, portfolio.data, runtimePages.data, traderId, truth.data, typedPortfolio, user],
  );

  return {
    account,
    loading: options.requireTraderScope ? authLoading || typedLoading : truth.loading || runtimePages.loading || portfolio.loading,
    error: truth.error ?? runtimePages.error ?? portfolio.error,
    ageSeconds: runtimePages.ageSeconds ?? truth.ageSeconds ?? portfolio.ageSeconds,
    paths: {
      truth: PAPER_ACCOUNT_TRUTH_PATH,
      runtimePages: RUNTIME_PAGES_PATH,
      portfolio: PORTFOLIO_STATE_PATH,
    },
  };
}
