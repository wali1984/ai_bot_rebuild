import { useRealtimeResource } from '../../hooks/useRealtimeResource';

// ── local primitives (mirrored from TradeSystemPanel to keep this file self-contained) ──
type Tone = 'ok' | 'warn' | 'block' | 'neutral';
const TONE_COLOR: Record<Tone, string> = {
  ok: 'var(--buy)',
  warn: 'var(--gold, #f59e0b)',
  block: 'var(--sell)',
  neutral: 'var(--text-secondary)',
};

function Row({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--line-soft)' }}>
      <span style={{ fontSize: 12, color: 'var(--text-secondary)', flexShrink: 0, marginRight: 8 }}>{label}</span>
      <strong style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: tone ? TONE_COLOR[tone] : 'var(--text-primary)', textAlign: 'right', maxWidth: '65%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</strong>
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

function pct(n: number | null | undefined, digits = 1): string {
  if (n == null) return '—';
  return `${(n * 100).toFixed(digits)}%`;
}
function fmt(n: number | null | undefined, digits = 4): string {
  if (n == null) return '—';
  return n.toFixed(digits);
}
function num(n: number | null | undefined): string {
  if (n == null) return '—';
  return String(n);
}

// ── payload shapes ──────────────────────────────────────────────────────────
interface BlockReason { reason: string; count: number; }

interface HourlyMonitorPayload {
  final_marker?: string;
  live_gate?: string;
  mutates_exchange?: boolean;
  generated_at?: string;
  soak?: {
    closed_trade_count?: number;
    soak_target?: number;
    soak_progress_pct?: number;
    soak_remaining?: number;
    soak_met?: boolean;
    win_rate?: number;
    win_rate_target?: number;
    blocker_3_status?: string;
  };
  quality_3h?: {
    verdict?: string;
    windows_evaluated?: number;
    clean_windows?: number;
    losing_windows?: number;
    total_closed_trades_3h?: number;
    total_realized_pnl_3h?: number;
  };
  monitor_summary?: {
    hourly_windows_computed?: number;
    cumulative_artifacts_written?: number;
    outcome_memory_buckets_updated?: number;
    closed_trades_all_time?: number;
    closed_trades_3h_windows?: number;
    shap_blocker_status?: string;
  };
  loss_recovery?: {
    tightening_active?: boolean;
    tightening_reason?: string | null;
    losing_windows?: number;
    clean_windows?: number;
    consecutive_clean_windows?: number;
    recovery_required_windows?: number;
    gate_overrides_active?: boolean;
    min_confidence_if_tightened?: number;
    min_edge_bps_if_tightened?: number;
  };
  pnl?: {
    fill_count?: number;
    closed_trade_count?: number;
    open_position_count?: number;
    blocked_count?: number;
    paper_realized_pnl?: number;
    paper_unrealized_pnl?: number;
    win_count?: number;
    loss_count?: number;
    win_rate?: number;
    profit_factor?: number;
    max_drawdown_usdt?: number;
    top_block_reasons?: BlockReason[];
    exit_reason_counts?: Record<string, number>;
    live_mutation_count_must_be_zero?: number;
  };
  orchestrator?: {
    total_decisions?: number;
    accepted_count?: number;
    blocked_count?: number;
    accept_rate?: number;
  };
  leverage?: {
    adaptive_leverage_recommendation_count?: number;
    adaptive_margin_recommendation_count?: number;
    note?: string;
  };
  shap?: {
    blocker_4_status?: string;
    shap_available?: boolean;
    attribution_method?: string;
    predictions_enriched?: number;
    waiveable_by_operator_for_paper?: boolean;
  };
  outcome_memory?: {
    buckets_updated?: number;
    events_processed?: number;
    bucket_keys?: string[];
    stores_updated?: number;
  };
}

export function HourlyMonitorPanel(): JSX.Element {
  const { envelope, loading, error } = useRealtimeResource<HourlyMonitorPayload>({
    url: '/api/v2/monitor/hourly',
    source: 'hourly_monitor',
    pollIntervalMs: 60_000,
  });

  const d = envelope.data;

  if (loading && !d) {
    return <div style={{ padding: '20px 12px', color: 'var(--text-secondary)', fontSize: 12 }}>Loading hourly monitor…</div>;
  }
  if (error && !d) {
    return <div style={{ padding: '20px 12px', color: 'var(--sell)', fontSize: 12 }}>Monitor unavailable: {String(error)}</div>;
  }
  if (!d) {
    return <div style={{ padding: '20px 12px', color: 'var(--text-secondary)', fontSize: 12 }}>No monitor data yet.</div>;
  }

  const soak = d.soak ?? {};
  const q3h = d.quality_3h ?? {};
  const mon = d.monitor_summary ?? {};
  const lr = d.loss_recovery ?? {};
  const pnl = d.pnl ?? {};
  const orch = d.orchestrator ?? {};
  const lev = d.leverage ?? {};
  const shap = d.shap ?? {};
  const om = d.outcome_memory ?? {};

  const markerText = d.final_marker ?? 'UNKNOWN';
  const markerBlocked = markerText.includes('BLOCKED');
  const soakMet = soak.soak_met === true;
  const verdictText = q3h.verdict ?? '—';
  const verdictOk = verdictText === 'PAPER_VALIDATED_3H_EDGE_CONFIRMED';
  const tighteningActive = lr.tightening_active === true;
  const mutZero = (pnl.live_mutation_count_must_be_zero ?? 0) === 0;
  const soakProgress = soak.soak_progress_pct ?? 0;

  return (
    <div style={{ padding: '4px 12px 24px', fontSize: 13, minHeight: 200 }}>

      {/* ── Final Marker / Gate ── */}
      <SectionHead
        title="Execution Guard / Final Marker"
        badge={markerBlocked ? 'BLOCKED' : 'VALIDATED'}
        tone={markerBlocked ? 'block' : 'ok'}
      />
      <Row label="Final Marker" value={markerText.slice(0, 60)} tone={markerBlocked ? 'block' : 'ok'} />
      <Row label="Execution Guard" value={(d.live_gate ?? '—').replace(/_/g, ' ').toUpperCase()} tone="block" />
      <Row label="Exchange Mutation" value={d.mutates_exchange ? 'YES — ALERT' : 'FALSE (safe)'} tone={d.mutates_exchange ? 'block' : 'ok'} />
      <Row label="Live Mutation Count" value={num(pnl.live_mutation_count_must_be_zero)} tone={mutZero ? 'ok' : 'block'} />
      <Row label="Last Updated" value={d.generated_at ?? '—'} tone="neutral" />

      {/* ── Soak Progress ── */}
      <SectionHead
        title="Soak Progress (BLOCKER-3)"
        badge={soakMet ? 'MET' : `${soakProgress.toFixed(1)}%`}
        tone={soakMet ? 'ok' : 'warn'}
      />
      <Row label="Closed Trades" value={`${soak.closed_trade_count ?? 0} / ${soak.soak_target ?? 500}`} tone={soakMet ? 'ok' : 'warn'} />
      <Row label="Remaining" value={num(soak.soak_remaining)} tone="neutral" />
      <Row label="All-Time Win Rate" value={pct(soak.win_rate)} tone={(soak.win_rate ?? 0) >= (soak.win_rate_target ?? 0.55) ? 'ok' : 'warn'} />
      <Row label="Win Rate Target" value={pct(soak.win_rate_target)} tone="neutral" />
      <Row label="BLOCKER-3 Status" value={soak.blocker_3_status ?? '—'} tone={soak.blocker_3_status === 'OPEN' ? 'warn' : 'ok'} />

      {/* ── 3H Quality ── */}
      <SectionHead
        title="3H Quality Windows"
        badge={verdictText.replace(/_/g, ' ').slice(0, 24)}
        tone={verdictOk ? 'ok' : 'warn'}
      />
      <Row label="Verdict" value={verdictText.replace(/_/g, ' ')} tone={verdictOk ? 'ok' : 'warn'} />
      <Row label="Windows Evaluated" value={num(q3h.windows_evaluated)} />
      <Row label="Clean Windows" value={num(q3h.clean_windows)} tone={(q3h.clean_windows ?? 0) >= 3 ? 'ok' : 'neutral'} />
      <Row label="Losing Windows" value={num(q3h.losing_windows)} tone={(q3h.losing_windows ?? 0) > 0 ? 'warn' : 'neutral'} />
      <Row label="Closed Trades (3H)" value={num(q3h.total_closed_trades_3h)} />
      <Row label="Realized PnL (3H)" value={`$${fmt(q3h.total_realized_pnl_3h, 4)}`} tone={(q3h.total_realized_pnl_3h ?? 0) >= 0 ? 'ok' : 'warn'} />

      {/* ── Loss Recovery ── */}
      <SectionHead
        title="Loss Recovery Loop"
        badge={tighteningActive ? 'TIGHTENING' : 'NORMAL'}
        tone={tighteningActive ? 'block' : 'ok'}
      />
      <Row label="Tightening Active" value={tighteningActive ? 'YES' : 'NO'} tone={tighteningActive ? 'block' : 'ok'} />
      <Row label="Tightening Reason" value={lr.tightening_reason ?? 'none'} tone={lr.tightening_reason ? 'warn' : 'neutral'} />
      <Row label="Losing Windows" value={num(lr.losing_windows)} tone={(lr.losing_windows ?? 0) > 0 ? 'warn' : 'neutral'} />
      <Row label="Clean Windows" value={num(lr.clean_windows)} />
      <Row label="Consecutive Clean" value={`${lr.consecutive_clean_windows ?? 0} / ${lr.recovery_required_windows ?? 3}`} tone={(lr.consecutive_clean_windows ?? 0) >= (lr.recovery_required_windows ?? 3) ? 'ok' : 'neutral'} />
      <Row label="Gate Overrides Active" value={lr.gate_overrides_active ? 'YES' : 'NO'} tone={lr.gate_overrides_active ? 'warn' : 'neutral'} />
      {tighteningActive ? (
        <>
          <Row label="Min Confidence (override)" value={fmt(lr.min_confidence_if_tightened, 2)} tone="warn" />
          <Row label="Min Edge % (override)" value={lr.min_edge_bps_if_tightened != null ? `${(lr.min_edge_bps_if_tightened / 100).toFixed(2)}%` : '—'} tone="warn" />
        </>
      ) : null}

      {/* ── PnL & Trade Counts ── */}
      <SectionHead title="Execution PnL & Trades" />
      <Row label="Realized PnL" value={`$${fmt(pnl.paper_realized_pnl, 6)}`} tone={(pnl.paper_realized_pnl ?? 0) >= 0 ? 'ok' : 'warn'} />
      <Row label="Unrealized PnL" value={`$${fmt(pnl.paper_unrealized_pnl, 6)}`} />
      <Row label="Fills (all)" value={num(pnl.fill_count)} />
      <Row label="Closed" value={num(pnl.closed_trade_count)} />
      <Row label="Open Positions" value={num(pnl.open_position_count)} />
      <Row label="Blocked" value={num(pnl.blocked_count)} />
      <Row label="Win / Loss" value={`${pnl.win_count ?? 0} W / ${pnl.loss_count ?? 0} L`} />
      <Row label="Win Rate" value={pct(pnl.win_rate)} tone={(pnl.win_rate ?? 0) >= 0.55 ? 'ok' : 'warn'} />
      <Row label="Profit Factor" value={fmt(pnl.profit_factor, 4)} tone={(pnl.profit_factor ?? 0) >= 1.0 ? 'ok' : 'warn'} />
      <Row label="Max Drawdown" value={`$${fmt(pnl.max_drawdown_usdt, 4)}`} />
      {(pnl.top_block_reasons ?? []).slice(0, 3).map((r) => (
        <Row key={r.reason} label={`Block: ${r.reason.replace(/deny_/g, '').replace(/_/g, ' ')}`} value={num(r.count)} tone="neutral" />
      ))}
      {Object.entries(pnl.exit_reason_counts ?? {}).map(([k, v]) => (
        <Row key={k} label={`Exit: ${k}`} value={String(v)} tone="neutral" />
      ))}

      {/* ── Orchestrator ── */}
      <SectionHead title="Orchestrator Decisions" />
      <Row label="Total Decisions" value={num(orch.total_decisions)} />
      <Row label="Accepted" value={num(orch.accepted_count)} />
      <Row label="Blocked" value={num(orch.blocked_count)} />
      <Row label="Accept Rate" value={pct(orch.accept_rate, 2)} tone={(orch.accept_rate ?? 0) > 0.01 ? 'ok' : 'neutral'} />

      {/* ── Leverage / Margin ── */}
      <SectionHead title="Leverage Recommendations" />
      <Row label="Rec Count" value={num(lev.adaptive_leverage_recommendation_count)} tone={(lev.adaptive_leverage_recommendation_count ?? 0) > 0 ? 'ok' : 'neutral'} />
      <Row label="Margin Rec Count" value={num(lev.adaptive_margin_recommendation_count)} />
      {lev.note ? <Row label="Note" value={lev.note.slice(0, 70)} tone="neutral" /> : null}

      {/* ── SHAP / Attribution ── */}
      <SectionHead
        title="SHAP Attribution (BLOCKER-4)"
        badge={shap.shap_available ? 'REAL SHAP' : 'HEURISTIC'}
        tone={shap.shap_available ? 'ok' : 'warn'}
      />
      <Row label="BLOCKER-4 Status" value={shap.blocker_4_status ?? '—'} tone={shap.blocker_4_status === 'OPEN' ? 'warn' : 'ok'} />
      <Row label="SHAP Available" value={shap.shap_available ? 'YES' : 'NO (heuristic)'} tone={shap.shap_available ? 'ok' : 'warn'} />
      <Row label="Method" value={(shap.attribution_method ?? '—').replace(/_/g, ' ')} tone="neutral" />
      <Row label="Predictions Enriched" value={num(shap.predictions_enriched)} />
      <Row label="Operator Waiveable" value={shap.waiveable_by_operator_for_paper ? 'YES' : 'NO'} tone="neutral" />

      {/* ── Outcome Memory ── */}
      <SectionHead title="Outcome Memory" />
      <Row label="Buckets Updated" value={num(om.buckets_updated)} />
      <Row label="Events Processed" value={num(om.events_processed)} />
      <Row label="Active Buckets" value={num((om.bucket_keys ?? []).length)} />
      <Row label="Stores/Bucket" value={num(om.stores_updated)} />

      {/* ── Monitor Health ── */}
      <SectionHead title="Monitor Runtime" />
      <Row label="Windows Computed" value={num(mon.hourly_windows_computed)} />
      <Row label="Artifacts Written" value={num(mon.cumulative_artifacts_written)} />
      <Row label="Closed All-Time" value={num(mon.closed_trades_all_time)} />
      <Row label="Closed in 3H Windows" value={num(mon.closed_trades_3h_windows)} />
      <Row label="SHAP Blocker" value={mon.shap_blocker_status ?? '—'} tone={mon.shap_blocker_status === 'OPEN' ? 'warn' : 'ok'} />
    </div>
  );
}
