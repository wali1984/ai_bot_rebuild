import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';

interface PipelineStatus {
  live_gate?: string;
  live_gate_runtime_source?: string;
  trader_execution_enabled?: boolean;
  allowed_run_types?: string[];
  symbols?: string[];
  schema_version?: string;
  generated_utc?: string;
}

interface TrainerSummary {
  state?: string;
  win_rate_30d?: number | null;
  episodes_total?: number | null;
  drift_alarm_count?: number | null;
  drift_watch_count?: number | null;
  checkpoint_id?: string | null;
  uptime_days?: number | null;
  promotion_locked?: boolean;
}

interface LiveGateStatus {
  go_no_go?: string;
  verdict?: string;
  live_gate?: string;
  backend_live_enable_callable?: boolean;
  service_id?: string;
  source_reconciliation?: {
    current_go_no_go?: string;
    current_verdict?: string;
    missing_acceptance_fields?: string[];
    proposed_risk_profiles?: string[];
    proposed_live_symbols?: string[];
  };
}

function Row({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warn' | 'block' | 'neutral' }) {
  const colors = { ok: 'var(--buy)', warn: 'var(--gold, #f59e0b)', block: 'var(--sell)', neutral: 'var(--text-secondary)' };
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--line-soft)' }}>
      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{label}</span>
      <strong style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: tone ? colors[tone] : 'var(--text-primary)', textAlign: 'right', maxWidth: '60%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</strong>
    </div>
  );
}

function SectionHead({ title, badge, tone }: { title: string; badge?: string; tone?: 'ok' | 'warn' | 'block' }) {
  const bg = tone === 'ok' ? 'var(--buy)' : tone === 'block' ? 'var(--sell)' : 'var(--gold, #f59e0b)';
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0 6px', marginTop: 12 }}>
      <h3 style={{ margin: 0, fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)' }}>{title}</h3>
      {badge ? <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 999, background: `color-mix(in oklch, ${bg} 18%, var(--bg-elevated))`, color: bg, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{badge}</span> : null}
    </div>
  );
}

export function TradeSystemPanel({ state }: { state: TradeTerminalState }): JSX.Element {
  const { envelope: pipelineEnv, loading: pLoading } = useRealtimeResource<PipelineStatus>({
    url: '/api/v2/pipeline/status',
    source: 'pipeline_service',
    pollIntervalMs: 30_000,
  });
  const { envelope: trainerEnv, loading: tLoading } = useRealtimeResource<TrainerSummary>({
    url: '/api/v2/trainer/summary',
    source: 'trainer_service',
    pollIntervalMs: 60_000,
  });
  const { envelope: riskEnv, loading: rLoading } = useRealtimeResource<LiveGateStatus>({
    url: '/api/v1/live-gate/status',
    source: 'live_gate_service',
    pollIntervalMs: 30_000,
  });

  const p = pipelineEnv.data;
  const t = trainerEnv.data;
  const r = riskEnv.data;

  const gateOpen = p?.live_gate === 'open';
  const gateTone = gateOpen ? 'ok' : p?.live_gate ? 'block' : 'neutral' as 'ok' | 'warn' | 'block';

  return (
    <div style={{ padding: '4px 12px 16px', fontSize: 13, minHeight: 200 }}>
      {/* Signal summary */}
      <SectionHead title="Active Signal" badge={state.signal.direction !== 'Signal unavailable' ? 'LIVE' : 'NONE'} tone={state.signal.direction !== 'Signal unavailable' ? 'ok' : undefined} />
      <Row label="Symbol" value={state.symbol} />
      <Row label="AI Direction" value={String(state.signal.direction).toUpperCase()} tone={state.signal.direction !== 'Signal unavailable' ? 'ok' : 'neutral'} />
      <Row label="Confidence" value={state.signal.confidence !== null ? `${((state.signal.confidence as number) * 100).toFixed(1)}%` : '—'} />
      <Row label="Risk Decision" value={String(state.signal.riskDecision)} tone={String(state.signal.riskDecision).includes('allow') ? 'ok' : String(state.signal.riskDecision).includes('unavailable') ? 'neutral' : 'warn'} />
      <Row label="Signal Source" value={state.signal.source} />

      {/* Orchestrator / Pipeline */}
      <SectionHead
        title="Orchestrator / Pipeline"
        badge={pLoading ? 'Loading…' : p ? 'CONNECTED' : 'UNAVAILABLE'}
        tone={p ? 'ok' : 'warn'}
      />
      <Row label="Live Gate" value={p?.live_gate?.replace(/_/g, ' ').toUpperCase() ?? '—'} tone={gateTone} />
      <Row label="Gate Source" value={p?.live_gate_runtime_source ?? '—'} />
      <Row label="Execution" value={p?.trader_execution_enabled ? 'ENABLED' : 'DISABLED'} tone={p?.trader_execution_enabled ? 'ok' : 'block'} />
      <Row label="Symbols in Scope" value={p?.symbols?.length != null ? String(p.symbols.length) : '—'} />
      <Row
        label="Allowed Run Types"
        value={(p?.allowed_run_types ?? []).join(' · ') || '—'}
      />
      <Row label="Schema" value={p?.schema_version ?? '—'} />

      {/* Risk Gate */}
      <SectionHead
        title="Risk Gate"
        badge={rLoading ? 'Loading…' : r?.live_gate ? r.live_gate.replace(/_/g, ' ').toUpperCase() : 'UNAVAILABLE'}
        tone={gateOpen ? 'ok' : 'block'}
      />
      <Row label="Go / No-Go" value={r?.go_no_go?.replace(/_/g, ' ') ?? '—'} tone={gateOpen ? 'ok' : 'block'} />
      <Row label="Verdict" value={(r?.verdict ?? '—').replace(/_/g, ' ').slice(0, 50)} />
      <Row label="Live Enable Callable" value={r?.backend_live_enable_callable ? 'YES' : 'NO'} tone={r?.backend_live_enable_callable ? 'ok' : 'block'} />
      {r?.source_reconciliation?.missing_acceptance_fields?.length ? (
        <Row label="Missing Acceptance" value={r.source_reconciliation.missing_acceptance_fields.slice(0, 2).join(', ')} tone="warn" />
      ) : null}

      {/* Trainer */}
      <SectionHead
        title="Trainer"
        badge={tLoading ? 'Loading…' : t?.state?.toUpperCase() ?? 'UNKNOWN'}
        tone={t?.state === 'running' || t?.state === 'active' ? 'ok' : t ? 'warn' : undefined}
      />
      <Row label="State" value={t?.state?.toUpperCase() ?? '—'} />
      <Row label="Win Rate 30d" value={t?.win_rate_30d != null ? `${((t.win_rate_30d as number) * 100).toFixed(1)}%` : '—'} />
      <Row label="Episodes" value={t?.episodes_total != null ? String(t.episodes_total) : '—'} />
      <Row label="Drift Alarms" value={t?.drift_alarm_count != null ? String(t.drift_alarm_count) : '—'} tone={t?.drift_alarm_count ? 'warn' : 'neutral'} />
      <Row label="Uptime Days" value={t?.uptime_days != null ? `${t.uptime_days}d` : '—'} />
      <Row label="Checkpoint" value={t?.checkpoint_id ?? '—'} />
      <Row label="Promotion Locked" value={t?.promotion_locked != null ? (t.promotion_locked ? 'YES' : 'NO') : '—'} tone={t?.promotion_locked ? 'warn' : 'ok'} />

      {/* Account */}
      <SectionHead title="Account" />
      <Row label="Account Equity" value={state.account.equity != null ? `$${(state.account.equity as number).toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '—'} />
      <Row label="Unrealized PnL" value={state.account.unrealizedPnl != null ? `$${(state.account.unrealizedPnl as number).toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '—'} />
      <Row label="Trader" value={state.trader.displayName ?? '—'} />
      <Row label="Mode" value={state.mode.label} />
      <Row label="Account Label" value={state.trader.accountLabel ?? '—'} />
      <Row label="Exchange Account" value={state.trader.exchangeLabel ?? '—'} />
      <Row label="Account Scope" value={state.trader.accountScopeLabel ?? '—'} />
      <Row label="Account Binding" value={state.trader.accountBindingStatus ?? '—'} tone={state.trader.accountBindingVerified ? 'ok' : 'warn'} />
      <Row label="Account Readiness" value={state.trader.accountReadinessStatus ?? '—'} />
      <Row label="Account Access" value={state.trader.exchangeReadStatus ?? '—'} />
      <Row label="Credential Status" value={state.trader.credentialStatus ?? '—'} />
    </div>
  );
}
