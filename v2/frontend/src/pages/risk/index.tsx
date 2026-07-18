import type { ReactNode } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import meta from './meta';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

const MOBILE_RISK_ENDPOINT = '/api/v2/mobile/risk-status';
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', info: '#60a5fa', muted: '#94a3b8' };

interface MobileRiskPayload {
  risk_state?: string | null;
  risk_classification?: string | null;
  kill_switch_active?: boolean | null;
  fail_closed?: boolean | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
  live_gate?: string | {
    gate?: string | null;
    label?: string | null;
    places_real_order?: boolean | null;
    live_trading_enabled?: boolean | null;
  } | null;
  real_trader_readiness?: {
    live_gate?: string | null;
    operator_flip_required?: boolean | null;
    live_ready?: boolean | null;
    order_submitted?: boolean | null;
    test_order_submitted?: boolean | null;
  } | null;
  adaptive_hedge_cross_margin?: {
    hedge_state?: string | null;
    hedge_rows?: number | null;
    portfolio_liquidation_buffer_usd?: number | null;
    cross_margin_available_buffer_usd?: number | null;
    worst_case_portfolio_loss_usd?: number | null;
    maintenance_margin_estimate_usd?: number | null;
    margin_call_risk?: string | null;
    cross_margin_state?: string | null;
  } | null;
  provider_readiness?: {
    altdata_trade_block_score?: number | null;
    altdata_reduce_size_score?: number | null;
    altdata_hedge_required_score?: number | null;
    confluence_hedge_required_score?: number | null;
  } | null;
  preemptive_edge_control?: {
    advanced_indicator_status?: string | null;
    advanced_indicators?: {
      sweep_risk_can_block_or_reduce?: boolean | null;
      status?: string | null;
    } | null;
  } | null;
}

function usd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'not reported';
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
}

function statusText(value: unknown, fallback = 'not reported'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value).replace(/_/g, ' ');
}

function boolStatus(value: unknown, truthy = 'true', falsy = 'false'): string {
  if (value === true) return truthy;
  if (value === false) return falsy;
  return 'not reported';
}

function liveGateText(value: MobileRiskPayload['live_gate']): string {
  if (!value) return 'blocked_human_only';
  if (typeof value === 'string') return value;
  return value.gate ?? value.label ?? 'blocked_human_only';
}

function scoreText(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? 'not reported' : value.toFixed(2);
}

function MetricCard({ label, value, tone = 'info' }: { label: string; value: ReactNode; tone?: keyof typeof SC }): JSX.Element {
  return (
    <div style={{ padding: '10px 12px', borderRadius: 7, border: `1px solid ${SC[tone]}44`, background: 'var(--bg-elevated)' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 750, fontFamily: 'var(--font-mono)', color: SC[tone], overflowWrap: 'anywhere' }}>{value}</div>
    </div>
  );
}

export default function RiskPage(): JSX.Element {
  const { envelope, loading, error } = useRealtimeResource<MobileRiskPayload>({
    url: MOBILE_RISK_ENDPOINT,
    source: MOBILE_RISK_ENDPOINT,
    pollIntervalMs: 10_000,
    staleThresholdMs: 45_000,
    mode: 'read_only',
  });
  const risk = envelope.data;
  const hedge = risk?.adaptive_hedge_cross_margin;
  const preemptive = risk?.preemptive_edge_control;
  const provider = risk?.provider_readiness;
  const squeezeCanBlock = preemptive?.advanced_indicators?.sweep_risk_can_block_or_reduce === true;
  const liveBlocked = risk?.routes_to_live !== true && risk?.places_real_order !== true;
  const hedgeScore = provider?.altdata_hedge_required_score ?? provider?.confluence_hedge_required_score;

  return (
    <main data-testid="page-risk" style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '18px clamp(14px, 2vw, 28px)', background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>
      <section style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <p style={{ margin: '0 0 4px', fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            {meta.title} runtime
          </p>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: 'var(--text-primary)' }}>Risk Runtime Truth</h1>
          <p style={{ margin: '6px 0 0', maxWidth: 760, color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.45 }}>
            Trader-safe read-only view of liquidation buffer, hedge state, sweep risk, kill switch, exchange permissions, live-ready status, and operator approval state.
          </p>
        </div>
        <div style={{ padding: '8px 10px', borderRadius: 7, border: `1px solid ${liveBlocked ? SC.warn : SC.error}66`, color: liveBlocked ? SC.warn : SC.error, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 800 }}>
          {liveBlocked ? 'LIVE BLOCKED / OPERATOR REQUIRED' : 'LIVE ROUTE REPORTED'}
        </div>
      </section>

      <section data-testid="risk-runtime-truth-panel" className="glass" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: 'var(--text-primary)' }}>Risk Runtime Truth</h2>
            <p style={{ margin: '3px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
              Source: {MOBILE_RISK_ENDPOINT} - freshness {envelope.freshness_status}; no admin overview request is required.
            </p>
          </div>
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: SC.muted }}>{MOBILE_RISK_ENDPOINT}</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
          <MetricCard label="Liquidation buffer" value={usd(hedge?.portfolio_liquidation_buffer_usd)} tone="ok" />
          <MetricCard label="Hedge state" value={statusText(hedge?.hedge_state)} tone={hedge?.hedge_state && hedge.hedge_state !== 'NO_HEDGE' ? 'warn' : 'info'} />
          <MetricCard label="Sweep risk" value={squeezeCanBlock ? 'sweep risk can block or reduce' : statusText(preemptive?.advanced_indicator_status)} tone={squeezeCanBlock ? 'warn' : 'info'} />
          <MetricCard label="Kill switch" value={risk?.kill_switch_active ? 'active' : 'not active'} tone={risk?.kill_switch_active ? 'warn' : 'ok'} />
          <MetricCard label="Cross-margin buffer" value={usd(hedge?.cross_margin_available_buffer_usd)} tone="info" />
          <MetricCard label="Maintenance margin" value={usd(hedge?.maintenance_margin_estimate_usd)} tone="info" />
          <MetricCard label="Margin-call risk" value={statusText(hedge?.margin_call_risk)} tone={hedge?.margin_call_risk === 'LOW' ? 'ok' : 'warn'} />
          <MetricCard label="Hedge required score" value={scoreText(hedgeScore)} tone={(hedgeScore ?? 0) > 0.5 ? 'warn' : 'info'} />
          <MetricCard label="Risk state" value={statusText(risk?.risk_state ?? risk?.risk_classification)} tone={risk?.fail_closed ? 'warn' : 'info'} />
          <MetricCard label="Operator approval" value={liveBlocked ? `blocked: ${liveGateText(risk?.live_gate)}` : 'live route reported'} tone={liveBlocked ? 'warn' : 'error'} />
          <MetricCard label="Live-ready status" value={boolStatus(risk?.real_trader_readiness?.live_ready, 'ready', 'not live-ready')} tone={risk?.real_trader_readiness?.live_ready ? 'error' : 'info'} />
          <MetricCard label="Exchange permissions" value={risk?.places_real_order === true || risk?.routes_to_live === true ? 'routes to live reported' : 'read-only or blocked'} tone={risk?.places_real_order === true || risk?.routes_to_live === true ? 'error' : 'ok'} />
        </div>

        {(loading || error) ? (
          <p style={{ margin: 0, fontSize: 12, color: error ? SC.error : 'var(--text-muted)' }} role={error ? 'alert' : undefined}>
            Risk contract status: {loading ? 'connecting' : 'loaded'}; errors: {error ?? 'none'}.
          </p>
        ) : null}

        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
          No order, test-order, leverage, or margin mutation is available from this page. Operator approval remains required and live remains blocked_human_only unless backend contracts prove otherwise.
        </p>
      </section>
    </main>
  );
}
