import { useState, type ReactNode } from 'react';
import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { SectionLabel } from '../../components/layout/SectionLabel';
import { CanonicalMetricCard, CanonicalMetricValue } from '../../components/data/CanonicalMetric';
import { EquityAreaChart, PnLBars, Donut, DonutLegend, RadialGauge, ChartFrame } from '../../components/charts/NervyxCharts';
import { buildEquityCharts } from '../../components/charts/nervyxChartTheme';
import {
  adaptiveStatusColor,
  formatAdaptiveMoney,
  pnlWindow,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import { formatMoney, formatPrice } from '../../lib/tradeFormatters';
import { selectAccountMetric, selectSectionMetric } from '../../selectors/accountSelectors';
import { selectPositionMetric, selectPositions } from '../../selectors/positionSelectors';
import { selectRiskStatus } from '../../selectors/riskSelectors';
import { sourceText, capitalStatusText } from '../../lib/traderPageHelpers';
import type { PortfolioData } from '../../types/apiV2';
import type { TraderRealtimeState } from '../../stores/traderRealtimeStore';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';
export { sourceText };

type PositionTab = 'open' | 'closed' | 'historical';
const PORTFOLIO_ENDPOINT = '/api/v2/portfolio';

export interface RuntimePositionEvidence {
  positions?: Array<Record<string, unknown>>;
  closed_trades?: Array<Record<string, unknown>>;
  equity_curve?: Array<{ t?: string; pnl?: number; winner?: boolean }>;
  summary?: {
    open_position_count?: number | null;
    closed_trade_count?: number | null;
  };
}

function KV({ label, value, color }: { label: string; value: ReactNode; color?: string }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', lineHeight: 1.2, overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>{value}</span>
    </div>
  );
}

function publicPositionText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return '—';
  return value
    .replace(/paper fill/gi, 'execution decision')
    .replace(/paper/gi, 'runtime')
    .replace(/_/g, ' ')
    .trim();
}

function formatAgeSeconds(value: unknown): string {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : null;
  if (n === null) return 'Freshness unavailable';
  if (n < 60) return `${Math.round(n)}s ago`;
  if (n < 3600) return `${Math.floor(n / 60)}m ago`;
  return `${Math.floor(n / 3600)}h ago`;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const n = finiteNumber(value);
    if (n !== null) return n;
  }
  return null;
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function pnlTone(value: unknown): string {
  const n = finiteNumber(value);
  if (n === null) return 'var(--text-primary)';
  return n >= 0 ? 'var(--buy)' : 'var(--sell)';
}

function statusText(value: unknown, fallback = 'Unavailable'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value).replace(/_/g, ' ').trim();
}

function positivePrice(value: unknown): number | null {
  const n = finiteNumber(value);
  return n !== null && n > 0 ? n : null;
}

function firstPositivePrice(...values: unknown[]): number | null {
  for (const value of values) {
    const price = positivePrice(value);
    if (price !== null) return price;
  }
  return null;
}

function formatHoldSeconds(value: unknown): string {
  const n = finiteNumber(value);
  if (n === null) return '—';
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.round(n)}s`;
}

function formatFeeUsd(value: unknown): string {
  const n = finiteNumber(value);
  if (n === null) return '—';
  return `$${Math.abs(n) < 1 ? n.toFixed(4) : n.toFixed(2)}`;
}

export function PositionEvidenceCard({
  row,
  mode,
  traderState,
  canonical,
}: {
  row: Record<string, unknown>;
  mode: PositionTab;
  traderState: TraderRealtimeState;
  canonical: boolean;
}): JSX.Element {
  const reasoning = row.decision_reasoning && typeof row.decision_reasoning === 'object'
    ? row.decision_reasoning as Record<string, unknown>
    : null;
  const metric = (fieldId: string) => selectPositionMetric(traderState, row, fieldId);
  const side = String(row.side ?? '—').toUpperCase();
  const isLong = side.includes('LONG') || side === 'BUY';
  const isClosed = mode !== 'open' || String(row.status ?? '').toLowerCase().includes('closed') || row.exit_price != null;
  const entry = firstPositivePrice(row.entry_price, row.avg_entry_price, row.paper_entry_price, row.entry_fill_price, row.open_price);
  const terminal = isClosed
    ? firstPositivePrice(row.exit_price, row.paper_exit_price, row.close_price, row.closing_price, row.filled_exit_price)
    : firstPositivePrice(row.mark_price, row.last_mark_price, row.current_price);
  const terminalLabel = isClosed ? 'Exit' : 'Mark';
  // Canonical NET realized PnL first — gross realized_pnl_usd excludes fees and
  // would disagree with every headline Realized PnL (net) on the same screens.
  const pnl = isClosed
    ? finiteNumber(row.realized_net_pnl_usd ?? row.realized_pnl_usd ?? row.realized_pnl)
    : finiteNumber(row.unrealized_pnl);
  const pnlColor = pnl == null ? 'var(--text-muted)' : pnl >= 0 ? 'var(--buy)' : 'var(--sell)';
  const markStale = row.mark_price_stale === true;

  return (
    <div className="glass glass-hover" style={{ padding: '16px 18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 12 }}>
        <span style={{ minWidth: 0, fontWeight: 700, fontSize: 14, fontFamily: 'var(--font-mono)', overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>
          {canonical ? <CanonicalMetricValue metric={metric('position.symbol')} /> : String(row.symbol ?? 'Unknown')}
        </span>
        <span style={{ fontWeight: 700, fontSize: 12, color: isLong ? 'var(--buy)' : 'var(--sell)', whiteSpace: 'nowrap' }}>
          {canonical ? <CanonicalMetricValue metric={metric('position.side')} /> : side}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
        <KV label="Qty" value={canonical ? <CanonicalMetricValue metric={metric('position.quantity')} /> : String(row.quantity ?? row.net_quantity ?? row.size ?? '—')} />
        <KV label="Entry" value={canonical ? <CanonicalMetricValue metric={metric('position.entry_price')} /> : formatPrice(entry)} />
        <KV label={terminalLabel} value={canonical ? <CanonicalMetricValue metric={metric(isClosed ? 'position.exit_price' : 'position.mark_price')} /> : formatPrice(terminal)} color={!isClosed && markStale ? 'var(--warn)' : undefined} />
        <KV label={isClosed ? 'Realized PnL' : 'Unrealized PnL'} value={canonical ? <CanonicalMetricValue metric={metric(isClosed ? 'position.realized_pnl' : 'position.unrealized_pnl')} /> : formatMoney(pnl)} color={pnlColor} />
        <KV label="Entry Source" value={canonical ? <CanonicalMetricValue metric={metric('position.entry_price_source')} /> : publicPositionText(row.entry_price_source)} />
        {isClosed ? (
          <KV label="Exit Source" value={canonical ? <CanonicalMetricValue metric={metric('position.exit_price_source')} /> : publicPositionText(row.exit_price_source)} />
        ) : (
          <KV label="Mark Age" value={canonical ? <CanonicalMetricValue metric={metric('position.mark_age_ms')} /> : formatAgeSeconds(row.mark_price_age_seconds)} color={markStale ? 'var(--warn)' : undefined} />
        )}
        {isClosed ? (
          // Closed-trade schema: risk_status/mark_price_source/stop/targets never
          // exist on closed rows (verified across all closed rows) — render the
          // fields the API actually serves instead of permanent em-dashes.
          <>
            <KV label="Hold" value={formatHoldSeconds(row.hold_time_seconds)} />
            <KV label="Notional" value={formatMoney(row.notional_usd)} />
            <KV label="Fees" value={formatFeeUsd(row.fees)} />
            <KV label="Close Reason" value={publicPositionText(row.close_reason)} />
          </>
        ) : (
          <>
            <KV label="Risk" value={canonical ? <CanonicalMetricValue metric={metric('position.risk_status')} /> : publicPositionText(row.risk_status)} />
            <KV label="Mark Source" value={canonical ? <CanonicalMetricValue metric={metric('position.mark_price_source')} /> : publicPositionText(row.mark_price_source)} />
            <KV label="Stop" value={canonical ? <CanonicalMetricValue metric={metric('position.stop')} /> : publicPositionText(row.stop)} />
            <KV label="Targets" value={canonical ? <CanonicalMetricValue metric={metric('position.targets')} /> : publicPositionText(row.targets)} />
          </>
        )}
        <KV label="Signal" value={canonical ? <CanonicalMetricValue metric={metric('position.signal_id')} /> : publicPositionText(reasoning?.signal_id ?? row.signal_id)} />
        <KV label="Prediction" value={canonical ? <CanonicalMetricValue metric={metric('position.prediction_id')} /> : publicPositionText(reasoning?.prediction_id ?? row.prediction_id)} />
      </div>
      {reasoning ? (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)', display: 'grid', gap: 8 }}>
          <h3 style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>AI Reasoning</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
            <KV label="Action" value={publicPositionText(reasoning.action)} />
            <KV label="Confidence" value={typeof reasoning.confidence === 'number' ? `${Math.round(reasoning.confidence * 100)}%` : '—'} />
            <KV label="Reason" value={publicPositionText(reasoning.reason ?? row.close_reason)} />
            {/* risk_state exists only in the open-position schema — hide on closed cards. */}
            {!isClosed ? <KV label="Risk" value={publicPositionText(reasoning.risk_state)} /> : null}
            <KV label="Regime" value={publicPositionText(reasoning.market_regime ?? row.market_regime_at_entry)} />
            <KV label="Source" value={publicPositionText(reasoning.source)} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PortfolioCanonicalPnlPanel(): JSX.Element {
  const { envelope, loading, error } = useRealtimeResource<PortfolioData>({
    url: PORTFOLIO_ENDPOINT,
    source: PORTFOLIO_ENDPOINT,
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 30_000,
    mode: 'paper',
  });
  const data = envelope.data;
  const realized = firstNumber(data?.paper_realized_pnl_usd, data?.realized_net_pnl_usd, data?.realized_pnl_usd, data?.realized_pnl);
  const unrealized = firstNumber(data?.paper_unrealized_pnl_usd, data?.unrealized_pnl_usd, data?.unrealized_pnl);
  const total = firstNumber(data?.paper_total_pnl_usd, data?.total_pnl_usd, realized !== null && unrealized !== null ? realized + unrealized : null);
  const equity = firstNumber(data?.paper_equity_usd, data?.equity, data?.paper_equity, data?.paper_balance);
  const generatedAt = firstText(data?.source_generated_utc, data?.generated_at, data?.generated_utc) ?? (typeof envelope.timestamp === 'number' ? new Date(envelope.timestamp).toISOString() : null);
  const source = firstText(data?.data_source, data?.pnl_source_key, data?.pnl_source_route, envelope.source) ?? PORTFOLIO_ENDPOINT;
  const sourceRoute = firstText(data?.pnl_source_route, envelope.endpoint) ?? PORTFOLIO_ENDPOINT;
  const sourceType = firstText(data?.pnl_source_type, data?.source_type, envelope.source_type) ?? 'source pending';
  const staleness = firstNumber(data?.staleness_seconds, envelope.lag_ms != null ? envelope.lag_ms / 1000 : null);
  const conflict = data?.pnl_conflict_detected === true;

  return (
    <div style={{ padding: '0 24px 16px' }}>
      <section
        data-testid="portfolio-canonical-pnl-panel"
        style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 18px' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Canonical Paper PnL</h2>
            <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
              Single source: {sourceRoute} · {statusText(sourceType)}
            </p>
          </div>
          <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', background: conflict ? 'color-mix(in oklch, var(--sell) 14%, transparent)' : 'color-mix(in oklch, var(--buy) 12%, transparent)', color: conflict ? 'var(--sell)' : 'var(--buy)', border: `1px solid ${conflict ? 'color-mix(in oklch, var(--sell) 40%, var(--border))' : 'color-mix(in oklch, var(--buy) 36%, var(--border))'}` }}>
            {conflict ? 'PNL CONFLICT' : 'PNL RECONCILED'}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
          <KV label="paper_realized_pnl_usd" value={formatMoney(realized)} color={pnlTone(realized)} />
          <KV label="paper_unrealized_pnl_usd" value={formatMoney(unrealized)} color={pnlTone(unrealized)} />
          <KV label="paper_total_pnl_usd" value={formatMoney(total)} color={pnlTone(total)} />
          <KV label="paper_equity_usd" value={formatMoney(equity)} />
          <KV label="paper_session_id" value={firstText(data?.paper_session_id) ?? 'paper_session_id unavailable'} />
          <KV label="data_source" value={source} />
          <KV label="generated_at" value={generatedAt ?? 'generated_at unavailable'} />
          <KV label="staleness_seconds" value={staleness !== null ? `${Math.round(staleness)}s` : envelope.freshness_status} color={envelope.freshness_status === 'stale' ? 'var(--warn)' : undefined} />
        </div>
        <p style={{ margin: '12px 0 0', fontSize: 11, color: error ? 'var(--warn)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {loading && !data ? 'Canonical PnL connecting' : `source=${source} · freshness=${data?.freshness_status ?? envelope.freshness_status} · live_gate=blocked_human_only`}
          {data?.pnl_conflict_reason ? ` · ${statusText(data.pnl_conflict_reason)}` : ''}
          {error ? ` · ${error}` : ''}
        </p>
      </section>
    </div>
  );
}

export default function PortfolioPage(): JSX.Element {
  const [positionTab, setPositionTab] = useState<PositionTab>('open');
  const state = useTradeTerminal();
  const traderSnapshot = useTraderSnapshot();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const canonicalOpenPositions = selectPositions(traderSnapshot);
  const canonicalOpenAvailable = Boolean(traderSnapshot.snapshot) && traderSnapshot.snapshot?.positions.meta.quality !== 'missing';
  const openPositions = (canonicalOpenAvailable ? canonicalOpenPositions : state.portfolio.openPositions) as Array<Record<string, unknown>>;
  const accountMetric = (fieldId: string) => selectAccountMetric(traderSnapshot, fieldId);
  const riskMetric = selectSectionMetric(traderSnapshot, 'risk', 'position.risk_status', selectRiskStatus(traderSnapshot));
  const { envelope: runtimePositions } = useRealtimeResource<RuntimePositionEvidence>({
    url: '/api/v2/paper/status',
    source: '/api/v2/paper/status',
    pollIntervalMs: 8_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
  });
  const runtimeData = runtimePositions.data ?? null;
  const closedPositions = runtimeData?.closed_trades ?? [];
  const selectedPositions = positionTab === 'open'
    ? openPositions as Array<Record<string, unknown>>
    : closedPositions;
  const positionTabs: Array<{ key: PositionTab; label: string; count: number }> = [
    { key: 'open', label: 'Open', count: openPositions.length },
    { key: 'closed', label: 'Closed', count: runtimeData?.summary?.closed_trade_count ?? closedPositions.length },
    // "Historical" was an exact duplicate of "Closed" (no distinct source), so it
    // is dropped rather than showing the same rows twice.
  ];
  const { source } = state.account;
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const oneDay = pnlWindow(pnlHistory, '1d');
  // Chart-ready performance derivations (shared helper) from the closed-trade curve.
  const equityNum = (fieldId: string): number | null => {
    const v = accountMetric(fieldId).value;
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  };
  const charts = buildEquityCharts(runtimeData?.equity_curve, {
    equity: equityNum('account.equity'),
    totalPnl: equityNum('account.total_pnl'),
  });
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status ?? capitalStatus?.signal_prediction_accuracy_status ?? null;

  return (
    <div
      data-testid="page-positions"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48, position: 'relative', overflow: 'hidden' }}
    >
      {/* Ambient depth — gives the frosted panels colour to refract. */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 0,
          background:
            'radial-gradient(46% 32% at 16% 0%, rgba(124,92,255,0.13), transparent 70%), radial-gradient(40% 34% at 92% 8%, rgba(45,212,191,0.09), transparent 72%)',
        }}
      />
      {/* Header */}
      <div style={{ position: 'relative', zIndex: 1, padding: '20px 24px 16px', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Portfolio</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Positions · Balances · Exposure · PnL · {state.trader.accountScopeLabel} · Real-time account telemetry
            </p>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>Market data live</span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'color-mix(in oklch, var(--warn) 10%, transparent)', color: 'var(--warn)', border: '1px solid color-mix(in oklch, var(--warn) 42%, var(--border))' }}>Execution restricted</span>
          </div>
        </div>
      </div>

      {/* KPI row */}
      <div style={{ position: 'relative', zIndex: 1, padding: '16px 24px' }}>
        <SectionLabel hint={state.trader.accountScopeLabel}>Account · at a glance</SectionLabel>
        <div className="trader-metric-grid">
          <CanonicalMetricCard label="Equity" metric={accountMetric('account.equity')} />
          <CanonicalMetricCard
            label="Available Balance"
            metric={accountMetric('account.available_balance')}
            emptyText="Paper balance unavailable; live signed account not read"
          />
          <CanonicalMetricCard label="Realized PnL" metric={accountMetric('account.realized_pnl')} />
          <CanonicalMetricCard label="Unrealized PnL" metric={accountMetric('account.unrealized_pnl')} />
          <CanonicalMetricCard label="Daily PnL" metric={accountMetric('account.daily_pnl')} />
          <CanonicalMetricCard label="Drawdown" metric={accountMetric('account.drawdown')} />
          <CanonicalMetricCard label="Exposure" metric={accountMetric('account.exposure')} />
          <CanonicalMetricCard label="Open Positions" metric={accountMetric('account.open_position_count')} />
          <CanonicalMetricCard
            label="Risk Status"
            metric={riskMetric}
            emptyText="Fail-closed: no current risk record"
          />
          <div className="trader-metric-card">
            <span className="trader-metric-card__label">1D PnL Window</span>
            <span className="trader-metric-card__value" style={{ fontSize: 18, color: (oneDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' }}>{formatAdaptiveMoney(oneDay?.realized_pnl_usd)}</span>
          </div>
          <div className="trader-metric-card">
            <span className="trader-metric-card__label">Capital Productivity</span>
            <span className="trader-metric-card__value" style={{ fontSize: 15, color: adaptiveStatusColor(capitalStatus?.status) }}>{capitalStatusText(capitalStatus?.status)}</span>
          </div>
        </div>
      </div>

      {/* Positions — what the trader is holding right now, surfaced directly under the KPIs */}
      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px 16px' }}>
        <SectionLabel hint={`${openPositions.length} open · ${runtimeData?.summary?.closed_trade_count ?? closedPositions.length} closed`}>Positions</SectionLabel>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg-panel)' }}>
            {positionTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setPositionTab(tab.key)}
                style={{
                  border: 'none',
                  borderRight: tab.key === 'historical' ? 'none' : '1px solid var(--border)',
                  background: positionTab === tab.key ? 'color-mix(in oklch, var(--accent) 16%, transparent)' : 'transparent',
                  color: positionTab === tab.key ? 'var(--text-primary)' : 'var(--text-muted)',
                  fontSize: 12,
                  fontWeight: positionTab === tab.key ? 700 : 500,
                  padding: '8px 12px',
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {tab.label} <span style={{ fontFamily: 'var(--font-mono)', opacity: 0.75 }}>{tab.count}</span>
              </button>
            ))}
          </div>
        </div>
        {selectedPositions.length === 0 ? (
          <div className="glass" style={{ padding: '28px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
              No {positionTab} position evidence available for the current account.
            </p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {selectedPositions.map((row, i) => (
              <PositionEvidenceCard
                key={`${positionTab}-${String(row.position_id ?? row.close_id ?? row.id ?? i)}`}
                row={row}
                mode={positionTab}
                traderState={traderSnapshot}
                canonical={positionTab === 'open' && canonicalOpenAvailable}
              />
            ))}
          </div>
        )}
      </div>

      {/* Performance charts — real closed-trade equity curve, per-trade PnL, win/loss, accuracy */}
      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px 16px' }}>
        <SectionLabel hint={`${charts.trades} closed paper trades`}>Performance</SectionLabel>
        <section className="glass glass-sheen" style={{ padding: '14px 16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)', gap: 14 }}>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
              <ChartFrame title="Equity curve" subtitle="cumulative · paper" height={200}>
                {charts.equitySeries.length >= 2
                  ? <EquityAreaChart data={charts.equitySeries} height={200} color="#7c5cff" />
                  : <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12, border: '1px dashed var(--border)', borderRadius: 8 }}>Awaiting closed trades</div>}
              </ChartFrame>
            </div>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <ChartFrame title="Prediction accuracy" height={160}>
                <RadialGauge value={accuracyStatus?.overall_accuracy} height={160} label="accuracy" />
              </ChartFrame>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginTop: 14 }}>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
              <ChartFrame title="Per-trade PnL" subtitle="realized, each closed trade" height={160}>
                {charts.perTradePnl.length
                  ? <PnLBars data={charts.perTradePnl} height={160} />
                  : <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12, border: '1px dashed var(--border)', borderRadius: 8 }}>No closed trades yet</div>}
              </ChartFrame>
            </div>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
              <ChartFrame title="Win / loss split" height={160}>
                {charts.winLossData.length
                  ? <><Donut data={charts.winLossData} height={150} centerValue={charts.winRate != null ? `${charts.winRate.toFixed(0)}%` : '—'} centerLabel="win rate" /><DonutLegend data={charts.winLossData} /></>
                  : <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12, border: '1px dashed var(--border)', borderRadius: 8 }}>No outcomes yet</div>}
              </ChartFrame>
            </div>
          </div>
        </section>
      </div>

      {/* Capital & accounting internals — dense reconciliation surfaces, kept last */}
      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px 4px' }}>
        <SectionLabel>Capital &amp; accounting internals</SectionLabel>
      </div>
      <div style={{ position: 'relative', zIndex: 1 }}>
        <PortfolioCanonicalPnlPanel />
      </div>

      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px 16px' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Capital Productivity + PnL + Accuracy"
          compact
          showMatrix
          maxMatrixHeight={220}
        />
      </div>

      {/* Account scope */}
      <div style={{ position: 'relative', zIndex: 1, padding: '0 24px 16px' }}>
        <div className="glass" style={{ padding: '16px 18px' }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Account Scope</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
            <KV label="Trader" value={state.trader.displayName} />
            <KV label="Account" value={state.trader.accountLabel} />
            <KV label="Exchange" value={state.trader.exchangeLabel} />
            <KV label="Access" value={state.trader.credentialStatus} />
            <KV label="Mode" value="Runtime" />
            <KV label="Source" value={source} />
          </div>
        </div>
      </div>

      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--border)' }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Trader-scoped account. Source: {source}
        </p>
      </div>
    </div>
  );
}
