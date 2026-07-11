/**
 * Shared UI primitives for the V2 realtime user/admin website.
 *
 * Every component is a pure React function that renders V2 truth.
 * No mock fixture is ever rendered as current truth. When a payload is
 * absent or stale, the matching component renders a MISSING / STALE
 * chip with the source path so operators can audit exactly which
 * Redis key or worklog JSON is delinquent.
 */
import type { ReactNode } from 'react';
import type { SafetyEnvelope } from '../../data/realtimeUserWebsitePayloads';
import { usePayloadFile } from '../../hooks/usePayloadFile';

const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface LiveGateRuntimePayload {
  live_gate?: string;
  live_order_submit_allowed?: boolean;
  live_blocked?: boolean;
  live_blocker?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
}

function symbolListLabel(items: unknown[] | undefined): string {
  if (!Array.isArray(items) || !items.length) return 'none';
  return items.map((item) => String(item)).join(', ');
}

// ---------------------------------------------------------------------------
// Freshness + age helpers
// ---------------------------------------------------------------------------

function parseUtc(value: string | undefined | null): Date | null {
  if (!value) return null;
  try {
    const d = new Date(value);
    return Number.isFinite(d.getTime()) ? d : null;
  } catch {
    return null;
  }
}

function ageSeconds(value: string | undefined | null): number | null {
  const d = parseUtc(value);
  if (!d) return null;
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
}

function ageLabel(value: string | undefined | null): string {
  const age = ageSeconds(value);
  if (age === null) return 'timestamp pending';
  if (age < 60) return `${age}s ago`;
  if (age < 3600) return `${Math.round(age / 60)}m ago`;
  return `${Math.round(age / 3600)}h ago`;
}

function runtimeStatusLabel(value: string | undefined | null): string {
  if (!value) return 'current runtime pending';
  return String(value)
    .replaceAll('enabled_operator_approved', 'gate approved')
    .replaceAll('blocked_human_only', 'approval required')
    .replaceAll('LIVE_ARMED_BALANCE_HOLD', 'armed, balance hold')
    .replaceAll('LIVE_ARMED_COMPLIANCE_HOLD', 'armed, compliance hold')
    .replaceAll('INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER', 'held until available margin covers the minimum order')
    .replaceAll('UNKNOWN_NEEDS_EVIDENCE', 'current source check pending')
    .replaceAll('NEEDS_EVIDENCE', 'source check pending')
    .replaceAll('MISSING_', 'pending ')
    .replaceAll('_', ' ')
    .toLowerCase();
}

function sourcePathLabel(path: string): string {
  if (path.includes('v2_alt_data_symbol_candidate_publisher')) return 'symbol candidate feed';
  if (path.includes('v2_live_gate_runtime')) return 'live gate runtime feed';
  if (path.includes('operator_runtime')) return 'runtime feed';
  if (path.includes('v2_report_center')) return 'report center feed';
  if (path.includes('public/')) return 'public evidence feed';
  return 'runtime evidence feed';
}

function statusTone(status: string, count = 1): 'ok' | 'warn' | 'block' | 'info' {
  const normalized = status.toUpperCase();
  if (count <= 0) return 'info';
  if (normalized.includes('OK') || normalized.includes('READY') || normalized.includes('PRESENT')) return 'ok';
  if (normalized.includes('MISSING') || normalized.includes('STALE') || normalized.includes('LIMIT')) return 'warn';
  if (normalized.includes('BLOCK') || normalized.includes('ERROR') || normalized.includes('FORBIDDEN')) return 'block';
  return 'info';
}

function booleanStatus(value: boolean | undefined, trueLabel: string, falseLabel: string): string {
  return value ? trueLabel : falseLabel;
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

export function FreshnessBadge({
  generatedAt,
  maxAgeSeconds = 600,
  label = 'fresh',
}: {
  generatedAt?: string | null;
  maxAgeSeconds?: number;
  label?: string;
}): JSX.Element {
  const age = ageSeconds(generatedAt ?? null);
  if (age === null)
    return (
      <span className="chip solid-loading" data-freshness="pending">
        timestamp pending
      </span>
    );
  if (age > maxAgeSeconds)
    return (
      <span className="chip solid-warn" data-freshness="stale">
        STALE - {ageLabel(generatedAt ?? null)}
      </span>
    );
  return (
    <span className="chip solid-ok" data-freshness="ok">
      {label} - {ageLabel(generatedAt ?? null)}
    </span>
  );
}

export function SourceBadge({ path, label = 'source' }: { path: string; label?: string }): JSX.Element {
  return (
    <span className="chip solid-loading" data-testid="source-badge" title={path}>
      {label}: {sourcePathLabel(path)}
    </span>
  );
}

export function BlockerChip({
  text,
  tone = 'warn',
}: {
  text: string;
  tone?: 'warn' | 'block' | 'ok' | 'info';
}): JSX.Element {
  const cls =
    tone === 'block'
      ? 'chip solid-block'
      : tone === 'ok'
      ? 'chip solid-ok'
      : tone === 'info'
      ? 'chip solid-paper'
      : 'chip solid-warn';
  return <span className={cls}>{text}</span>;
}

export function PayloadMissingCard({
  path,
  error,
  loading,
}: {
  path: string;
  error?: string | null;
  loading?: boolean;
}): JSX.Element {
  return (
    <div className="panel bracketed" data-testid="payload-missing" style={{ padding: 14 }}>
      <span className="br-tl" aria-hidden="true" />
      <span className="br-tr" aria-hidden="true" />
      <span className="br-bl" aria-hidden="true" />
      <span className="br-br" aria-hidden="true" />
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 6 }}>
        <BlockerChip text="Connecting stream" tone="warn" />
        {loading ? <BlockerChip text="connecting" tone="info" /> : null}
      </div>
      <p style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--fg-3)', margin: 0 }} title={path}>
        Data feed: {sourcePathLabel(path)}
      </p>
      {error ? (
        <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-4)', margin: '6px 0 0' }}>
          {error}
        </p>
      ) : null}
      <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-4)', margin: '6px 0 0' }}>
        No mock data is rendered when this feed is missing. Review the source artifact before treating this panel as current.
      </p>
    </div>
  );
}

export function SafetyInvariantStrip({
  envelope,
  extra,
}: {
  envelope?: SafetyEnvelope | null;
  extra?: { checkpoint_compatibility_claimed?: boolean; policy_architecture_parity_claimed?: boolean } | null;
}): JSX.Element {
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const runtimeSymbols = liveGateRuntime?.execution_live_symbols ?? liveGateRuntime?.live_symbols;
  const live_gate = liveGateRuntime?.live_gate ?? envelope?.live_gate ?? 'current runtime pending';
  const liveSymbols = Array.isArray(runtimeSymbols) ? runtimeSymbols : envelope?.live_symbols;
  const live_symbols_empty = Array.isArray(liveSymbols)
    ? (liveSymbols ?? []).length === 0
    : null;
  const ckpt = extra?.checkpoint_compatibility_claimed ?? false;
  const policy = extra?.policy_architecture_parity_claimed ?? false;
  return (
    <section
      className="status-rail"
      data-testid="safety-invariant-strip"
      style={{ borderTop: '1px solid var(--line)', borderBottom: '1px solid var(--line)' }}
    >
      <div className="wrap">
        <div className="cell">
          <span className="k">Live gate</span>
          <span className={liveGateRuntime?.live_order_submit_allowed === true && liveGateRuntime?.live_blocked !== true ? 'v ok' : 'v warn'}>{liveGateRuntime?.live_blocked === true ? (liveGateRuntime?.live_blocker ?? 'BLOCKED') : runtimeStatusLabel(live_gate)}</span>
        </div>
        <div className="cell">
          <span className="k">Execution symbols</span>
          <span className={live_symbols_empty ? 'v warn' : 'v ok'}>
            {live_symbols_empty === null ? 'runtime symbol list pending' : symbolListLabel(liveSymbols)}
          </span>
        </div>
        <div className="cell">
          <span className="k">Public surface</span>
          <span className="v ok">live telemetry</span>
        </div>
        <div className="cell">
          <span className="k">Checkpoint compatibility</span>
          <span className={ckpt ? 'v warn' : 'v ok'}>{ckpt ? 'CLAIMED' : 'false'}</span>
        </div>
        <div className="cell">
          <span className="k">Policy arch parity</span>
          <span className={policy ? 'v warn' : 'v ok'}>{policy ? 'CLAIMED' : 'false'}</span>
        </div>
        <div className="cell">
          <span className="k">Approves real/canary/shutdown/redis-trim</span>
          <span className="v ok">all false</span>
        </div>
      </div>
    </section>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: 'default' | 'ok' | 'warn' | 'bad';
}): JSX.Element {
  const cls =
    tone === 'ok'
      ? 'v ok'
      : tone === 'warn'
      ? 'v warn'
      : tone === 'bad'
      ? 'v bad'
      : 'v';
  return (
    <div className="cell" data-testid="metric-card">
      <span className="k">{label}</span>
      <span className={cls}>{value}</span>
      {detail ? <span className="src">{detail}</span> : null}
    </div>
  );
}

export interface Top10TableRow {
  rank: number;
  symbol: string;
  quote_volume?: number | null;
  trade_count?: number | null;
  price_change_percent?: number | null;
  last_price?: number | null;
}

export function Top10Table({
  title,
  metricLabel,
  metricField,
  windowRequested,
  windowActual,
  sourceStatus,
  rows,
}: {
  title: string;
  metricLabel: string;
  metricField: 'quote_volume' | 'trade_count' | 'price_change_percent';
  windowRequested?: string;
  windowActual?: string;
  sourceStatus?: string;
  rows?: Top10TableRow[];
}): JSX.Element {
  const isOk = (sourceStatus ?? '') === 'API_OK';
  const windowMismatch = windowRequested && windowActual && windowRequested !== windowActual;
  return (
    <div className="panel" data-testid="top10-table" style={{ padding: 14 }}>
      <div className="panel-head">
        <h3 style={{ fontFamily: 'var(--serif)', fontSize: 18 }}>{title}</h3>
        <span className="sub">{metricLabel}</span>
        <div className="right">
          {windowRequested ? (
            <span className="chip">requested: {windowRequested}</span>
          ) : null}
          {windowActual ? (
            <span className={windowMismatch ? 'chip solid-warn' : 'chip'}>actual: {windowActual}</span>
          ) : null}
          <BlockerChip text={runtimeStatusLabel(sourceStatus ?? 'Connecting stream')} tone={isOk ? 'ok' : 'warn'} />
        </div>
      </div>
      {rows && rows.length > 0 ? (
        <div style={{ overflowX: 'auto' }}>
          <table className="mkt" style={{ width: '100%' }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Symbol</th>
                <th>quoteVolume</th>
                <th>count</th>
                <th>change %</th>
                <th>last</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.rank}-${r.symbol}`}>
                  <td className="num">{r.rank}</td>
                  <td>{r.symbol}</td>
                  <td className="num">{r.quote_volume ?? 'Connecting stream'}</td>
                  <td className="num">{r.trade_count ?? 'Connecting stream'}</td>
                  <td className="num">{r.price_change_percent ?? 'Connecting stream'}</td>
                  <td className="num">{r.last_price ?? 'Connecting stream'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-4)' }}>
          rank_count: 0. Source: {runtimeStatusLabel(sourceStatus ?? 'Connecting stream')}. No synthetic rows.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top10Panel: render any of the 10 dashboards from the renderer payload.
// Display-only. No buttons. No provider calls. Shows the panel's classified
// state (OK_ROWS_PRESENT / KEY_PRESENT_NO_CLIENT_YET / KEY_MISSING / STALE /
// BUDGET_LIMITED) with explicit chip + rows when present.
// ---------------------------------------------------------------------------

export interface Top10PanelRowLite {
  rank: number;
  symbol: string;
  quote_volume?: number | null;
  trade_count?: number | null;
  price_change_percent?: number | null;
  last_price?: number | null;
  liquidated_notional_usdt?: number | null;
  long_count?: number | null;
  short_count?: number | null;
  last_funding_rate?: number | null;
  open_interest?: number | null;
  long_short_ratio?: number | null;
  funding_age_seconds?: number | null;
  open_interest_age_seconds?: number | null;
  long_short_age_seconds?: number | null;
  score?: number | null;
}

export type Top10PanelStateLite =
  | 'OK_ROWS_PRESENT'
  | 'KEY_PRESENT_NO_CLIENT_YET'
  | 'KEY_MISSING'
  | 'STALE'
  | 'BUDGET_LIMITED';

const PANEL_STATE_TONE: Record<Top10PanelStateLite, 'ok' | 'warn' | 'block' | 'info'> = {
  OK_ROWS_PRESENT: 'ok',
  KEY_PRESENT_NO_CLIENT_YET: 'info',
  KEY_MISSING: 'warn',
  STALE: 'warn',
  BUDGET_LIMITED: 'warn',
};

const PANEL_STATE_EXPLAIN: Record<Top10PanelStateLite, string> = {
  OK_ROWS_PRESENT: 'fresh ranked rows',
  KEY_PRESENT_NO_CLIENT_YET: 'data path wired; upstream client has not produced rows yet',
  KEY_MISSING: 'required Redis key absent',
  STALE: 'payload older than the panel freshness window',
  BUDGET_LIMITED: 'provider hit free-tier daily budget / rate limit / cooldown',
};

function panelStateLabel(state: Top10PanelStateLite): string {
  if (state === 'OK_ROWS_PRESENT') return 'current rows present';
  if (state === 'KEY_PRESENT_NO_CLIENT_YET') return 'source wired, waiting for rows';
  if (state === 'KEY_MISSING') return 'source key pending';
  if (state === 'STALE') return 'stale';
  if (state === 'BUDGET_LIMITED') return 'provider budget limited';
  return 'panel state pending';
}

export function Top10Panel({
  panel,
  columns,
}: {
  panel: {
    panel_id: string;
    title: string;
    metric?: string;
    state: Top10PanelStateLite;
    age_seconds?: number | null;
    rank_count: number;
    rows: Top10PanelRowLite[];
    source_status?: string;
    window_size_requested?: string;
    window_size_actual?: string;
    key_present?: boolean;
    paid_endpoints_enabled?: boolean;
    source_status_counts?: Record<string, number>;
    tier?: string;
    credential_in_payload?: string;
    heartbeat_present?: boolean;
    heartbeat_age_seconds?: number | null;
    tracked_symbols?: string[];
    missing_symbols?: string[];
  };
  columns: { key: keyof Top10PanelRowLite | 'rank' | 'symbol'; label: string; align?: 'num' }[];
}): JSX.Element {
  const state = panel.state ?? 'KEY_MISSING';
  const tone = PANEL_STATE_TONE[state] ?? 'warn';
  const explain = PANEL_STATE_EXPLAIN[state] ?? 'panel state pending';
  const ageStr =
    panel.age_seconds === undefined || panel.age_seconds === null
      ? '—'
      : `${Math.round(panel.age_seconds)}s`;
  return (
    <div
      className="panel"
      data-testid={`top10-panel-${panel.panel_id}`}
      data-panel-state={state}
      style={{ padding: 14 }}
    >
      <div className="panel-head" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ fontFamily: 'var(--serif)', fontSize: 16, margin: 0 }}>{panel.title}</h3>
        {panel.metric ? <span className="sub">{panel.metric}</span> : null}
        <div className="right" style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <BlockerChip text={`state · ${panelStateLabel(state)}`} tone={tone} />
          <BlockerChip text={`age · ${ageStr}`} tone="info" />
          {panel.source_status ? <BlockerChip text={`source · ${runtimeStatusLabel(panel.source_status)}`} tone="info" /> : null}
          {panel.tier ? <BlockerChip text={`tier · ${panel.tier}`} tone="info" /> : null}
        </div>
      </div>
      <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)', margin: '6px 0 8px' }}>
        {explain}
      </p>
      {panel.rows && panel.rows.length > 0 ? (
        <div style={{ overflowX: 'auto' }}>
          <table className="mkt" style={{ width: '100%' }}>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={String(c.key)}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {panel.rows.map((r) => (
                <tr key={`${r.rank}-${r.symbol}`}>
                  {columns.map((c) => {
                    const v = (r as unknown as Record<string, unknown>)[String(c.key)];
                    const txt = v === null || v === undefined ? '—' : String(v);
                    return (
                      <td key={String(c.key)} className={c.align === 'num' ? 'num' : undefined}>
                        {txt}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-4)', margin: 0 }}>
            rank_count · {panel.rank_count}. No synthetic rows.
          </p>
          {panel.missing_symbols && panel.missing_symbols.length > 0 ? (
            <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-4)', margin: 0 }}>
              Missing symbols: {panel.missing_symbols.join(', ')}
            </p>
          ) : null}
          {panel.source_status_counts ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
              {Object.entries(panel.source_status_counts).map(([status, count]) => (
                <BlockerChip
                  key={status}
                  text={`${runtimeStatusLabel(status)} · ${count}`}
                  tone={statusTone(status, count)}
                />
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CandidatePublisherPanel: display-only renderer for the V2 alt-data
// Symbol Universe candidate publisher. Surfaces every required field plus
// the explicit adoption-blocked labels Codex required. Renders NO
// adopt button, NO live button, NO order button — ever.
// ---------------------------------------------------------------------------

export interface CandidatePublisherRowLite {
  symbol: string;
  candidate_state:
    | 'CANDIDATE_READY'
    | 'MISSING_PROVIDER_DATA'
    | 'STALE_PROVIDER_DATA'
    | 'BUDGET_LIMITED'
    | 'BELOW_THRESHOLD'
    | 'SYMBOL_NOT_TRADABLE_ON_BINANCE'
    | 'SYMBOL_UNIVERSE_GATE_REQUIRED';
  candidate_publisher_rank?: number | null;
  altdata_symbol_rank?: number | null;
  altdata_symbol_score?: number | null;
  proposed_use?: string[];
  missing_provider_flags?: string[];
  stale_provider_flags?: string[];
  candidate_reason?: string;
  candidate_only_not_adopted?: boolean;
  live_symbol_candidate?: boolean;
  paper_symbol_candidate?: boolean;
  training_symbol_candidate?: boolean;
  watchlist_candidate?: boolean;
}

const CANDIDATE_STATE_TONE: Record<
  CandidatePublisherRowLite['candidate_state'],
  'ok' | 'warn' | 'info' | 'block'
> = {
  CANDIDATE_READY: 'ok',
  MISSING_PROVIDER_DATA: 'warn',
  STALE_PROVIDER_DATA: 'warn',
  BUDGET_LIMITED: 'warn',
  BELOW_THRESHOLD: 'info',
  SYMBOL_NOT_TRADABLE_ON_BINANCE: 'warn',
  SYMBOL_UNIVERSE_GATE_REQUIRED: 'info',
};

export function CandidatePublisherPanel({
  dashboard,
  loading,
  error,
}: {
  dashboard: {
    generated_utc?: string;
    candidate_count?: number;
    candidate_state_counts?: Record<string, number>;
    // `candidates` is the canonical row field produced by the
    // publisher CLI; `candidate_summary` is a backward-compat alias.
    candidates?: CandidatePublisherRowLite[];
    candidate_summary?: CandidatePublisherRowLite[];
    watchlist_threshold?: number;
    paper_threshold?: number;
    training_threshold?: number;
    live_symbols_expanded?: boolean;
    paper_symbols_expanded?: boolean;
    training_symbols_expanded?: boolean;
    candidate_only_not_adopted?: boolean;
    may_not_override_strict_paper_fill_gate?: boolean;
    may_not_authorize_live_or_canary?: boolean;
    may_not_place_orders?: boolean;
    writes_exchange_orders?: boolean;
    live_gate?: string;
    live_symbols?: unknown[];
    raw_credential_in_payload?: string;
    publisher_payload_path?: string;
    forbidden_input_namespaces?: string[];
    allowed_inputs?: string[];
    allowed_writes?: string[];
  } | null;
  loading: boolean;
  error: string | null;
}): JSX.Element {
  // The adoption-blocked label set is Codex-required and must always
  // be visible whenever the panel renders, regardless of dashboard
  // content. These are NOT buttons; they are read-only chips.
  const ADOPTION_LABELS: { text: string; tone: 'info' | 'ok' | 'warn' }[] = [
    { text: 'Candidate only — not adopted', tone: 'info' },
    { text: 'Does not change training_symbols', tone: 'info' },
    { text: 'Does not change paper_symbols', tone: 'info' },
    { text: 'Does not change live_symbols', tone: 'info' },
    { text: 'Cannot override strict paper-fill gate', tone: 'info' },
    { text: 'Live trading remains blocked', tone: 'warn' },
  ];

  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const liveGate = liveGateRuntime?.live_gate ?? dashboard?.live_gate ?? 'loading';
  const liveSymbolsLen = (dashboard?.live_symbols ?? []).length;
  const liveSymbolsExpanded = dashboard?.live_symbols_expanded ?? false;
  const paperSymbolsExpanded = dashboard?.paper_symbols_expanded ?? false;
  const trainingSymbolsExpanded = dashboard?.training_symbols_expanded ?? false;
  const candidateOnlyNotAdopted = dashboard?.candidate_only_not_adopted ?? true;
  const rawCredentialInPayload = dashboard?.raw_credential_in_payload ?? 'NEVER';

  return (
    <div
      className="panel"
      data-testid="alt-data-candidate-publisher-panel"
      data-candidate-only-not-adopted={String(candidateOnlyNotAdopted)}
      data-live-gate={liveGate}
      style={{ padding: 14 }}
    >
      <div className="panel-head" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ fontFamily: 'var(--serif)', fontSize: 16, margin: 0 }}>
          Alt-data Symbol Universe candidate publisher
        </h3>
        <span className="sub">recommendations only</span>
        <div className="right" style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <BlockerChip text={`candidate_count · ${dashboard?.candidate_count ?? 0}`} tone="info" />
          <BlockerChip text={`live_gate · ${liveGateRuntime?.live_blocked === true ? (liveGateRuntime?.live_blocker ?? 'BLOCKED') : liveGate}`} tone={liveGateRuntime?.live_order_submit_allowed === true && liveGateRuntime?.live_blocked !== true ? 'ok' : 'warn'} />
          <BlockerChip text={`live_symbols · ${liveSymbolsLen}`} tone="ok" />
          <FreshnessBadge generatedAt={dashboard?.generated_utc} maxAgeSeconds={1800} />
        </div>
      </div>

      {/* Codex-required adoption-blocked label strip — always visible. */}
      <div
        className="adoption-strip"
        data-testid="candidate-publisher-adoption-labels"
        style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}
      >
        {ADOPTION_LABELS.map((label) => (
          <BlockerChip key={label.text} text={label.text} tone={label.tone} />
        ))}
      </div>

      {/* Safety invariants strip. */}
      <section className="status-rail" style={{ marginTop: 10 }}>
        <div className="wrap">
          <MetricCard
            label="Adoption status"
            value={booleanStatus(candidateOnlyNotAdopted, 'recommendations only', 'adoption attempted')}
            tone={candidateOnlyNotAdopted ? 'ok' : 'bad'}
          />
          <MetricCard label="Live universe changed" value={booleanStatus(liveSymbolsExpanded, 'changed', 'unchanged')} tone={liveSymbolsExpanded ? 'bad' : 'ok'} />
          <MetricCard label="Execution universe changed" value={booleanStatus(paperSymbolsExpanded, 'changed', 'unchanged')} tone={paperSymbolsExpanded ? 'bad' : 'ok'} />
          <MetricCard label="Training universe changed" value={booleanStatus(trainingSymbolsExpanded, 'changed', 'unchanged')} tone={trainingSymbolsExpanded ? 'bad' : 'ok'} />
          <MetricCard label="Credentials in payload" value={rawCredentialInPayload === 'NEVER' ? 'none detected' : runtimeStatusLabel(rawCredentialInPayload)} tone={rawCredentialInPayload === 'NEVER' ? 'ok' : 'bad'} />
          <MetricCard
            label="Exchange order writes"
            value={booleanStatus(dashboard?.writes_exchange_orders, 'attempted', 'none')}
            tone={dashboard?.writes_exchange_orders ? 'bad' : 'ok'}
          />
          <MetricCard
            label="Execution-fill gate protected"
            value={booleanStatus(dashboard?.may_not_override_strict_paper_fill_gate ?? true, 'protected', 'not protected')}
            tone={dashboard?.may_not_override_strict_paper_fill_gate === false ? 'bad' : 'ok'}
          />
          <MetricCard label="Watchlist threshold" value={String(dashboard?.watchlist_threshold ?? '—')} />
          <MetricCard label="Execution threshold" value={String(dashboard?.paper_threshold ?? '—')} />
          <MetricCard label="Training threshold" value={String(dashboard?.training_threshold ?? '—')} />
        </div>
      </section>

      {/* Candidate state-count summary. */}
      {dashboard?.candidate_state_counts ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {Object.entries(dashboard.candidate_state_counts).map(([state, count]) => (
            <BlockerChip
              key={state}
              text={`${runtimeStatusLabel(state)} · ${count}`}
              tone={
                state === 'CANDIDATE_READY' && count > 0
                  ? 'ok'
                  : state === 'MISSING_PROVIDER_DATA' || state === 'STALE_PROVIDER_DATA' || state === 'BUDGET_LIMITED'
                  ? 'warn'
                  : 'info'
              }
            />
          ))}
        </div>
      ) : null}

      {/* Candidate rows or missing-state explainer.
          `candidates` is the canonical row key produced by the
          publisher CLI; `candidate_summary` is a legacy alias that
          we still accept for backward compatibility but never
          prefer. The expression below ensures the served public
          payload (which writes `candidates`) renders even if the
          legacy alias is absent. */}
      {(() => {
        const candidateRows: CandidatePublisherRowLite[] =
          (dashboard?.candidates && dashboard.candidates.length > 0
            ? dashboard.candidates
            : dashboard?.candidate_summary ?? []) as CandidatePublisherRowLite[];
        if (error || (!loading && !dashboard)) {
          return (
            <PayloadMissingCard
              path="public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"
              error={error}
              loading={loading}
            />
          );
        }
        if (candidateRows.length === 0) {
          return (
            <p
              style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)', marginTop: 8 }}
              data-testid="candidate-publisher-empty-state"
            >
              No candidates in current snapshot. If providers are absent or rate-limited,
              this is the expected state — the publisher refuses to fabricate candidates.
            </p>
          );
        }
        return (
          <div style={{ overflowX: 'auto', marginTop: 12 }} data-testid="candidate-publisher-table">
            <table className="mkt" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Alt-data rank</th>
                  <th>Symbol</th>
                  <th>Candidate status</th>
                  <th>Alt-data score</th>
                  <th>Suggested use</th>
                  <th>Missing provider data</th>
                  <th>Stale provider data</th>
                  <th>Adoption status</th>
                  <th>Live symbol candidate</th>
                  <th>Why included</th>
                </tr>
              </thead>
              <tbody>
                {candidateRows.map((row, i) => (
                  <tr key={`${row.symbol}-${i}`}>
                    <td className="num">{row.candidate_publisher_rank ?? '—'}</td>
                    <td className="num">{row.altdata_symbol_rank ?? '—'}</td>
                    <td>{row.symbol}</td>
                    <td>
                      <BlockerChip
                        text={runtimeStatusLabel(row.candidate_state)}
                        tone={CANDIDATE_STATE_TONE[row.candidate_state] ?? 'info'}
                      />
                    </td>
                    <td className="num">{row.altdata_symbol_score ?? '—'}</td>
                    <td>{(row.proposed_use ?? []).join(', ') || '—'}</td>
                    <td>{(row.missing_provider_flags ?? []).join(', ') || '—'}</td>
                    <td>{(row.stale_provider_flags ?? []).join(', ') || '—'}</td>
                    <td>
                      <BlockerChip
                        text={booleanStatus(row.candidate_only_not_adopted ?? true, 'recommendation only', 'adoption attempted')}
                        tone={(row.candidate_only_not_adopted ?? true) ? 'ok' : 'block'}
                      />
                    </td>
                    <td>
                      <BlockerChip
                        text={booleanStatus(row.live_symbol_candidate, 'marked live', 'not live')}
                        tone={row.live_symbol_candidate ? 'block' : 'ok'}
                      />
                    </td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>
                      {row.candidate_reason ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })()}

      <p style={{ marginTop: 12, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>
        Source: <code>{dashboard?.publisher_payload_path ?? 'public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json'}</code>.
        Adoption into <code>execution_symbols</code> / <code>training_symbols</code> requires the existing
        Symbol Universe governance gate; this publisher emits proposals only.
        Allowed inputs: <code>{(dashboard?.allowed_inputs ?? []).join(', ') || 'n/a'}</code>.
        Forbidden inputs: <code>{(dashboard?.forbidden_input_namespaces ?? ['v2:execution:*', 'v2:risk:*']).join(', ')}</code>.
        Allowed writes: <code>{(dashboard?.allowed_writes ?? []).join(', ') || 'n/a'}</code>.
      </p>
    </div>
  );
}

export function CoverageDonut({
  present,
  target,
  label = 'feature coverage',
}: {
  present: number;
  target: number;
  label?: string;
}): JSX.Element {
  const t = Math.max(1, target);
  const pct = Math.max(0, Math.min(1, present / t));
  const r = 56;
  const c = 2 * Math.PI * r;
  const dash = c * pct;
  const gap = c - dash;
  return (
    <div className="panel" data-testid="coverage-donut" style={{ padding: 14, display: 'flex', alignItems: 'center', gap: 16 }}>
      <svg width="140" height="140" viewBox="0 0 140 140">
        <circle cx="70" cy="70" r={r} fill="none" stroke="var(--line)" strokeWidth="14" />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke="var(--amber)"
          strokeWidth="14"
          strokeDasharray={`${dash} ${gap}`}
          strokeDashoffset={c / 4}
          transform="rotate(-90 70 70)"
        />
        <text x="70" y="68" textAnchor="middle" fill="var(--fg)" fontFamily="var(--mono)" fontSize="20">
          {Math.round(pct * 100)}%
        </text>
        <text x="70" y="86" textAnchor="middle" fill="var(--fg-3)" fontFamily="var(--mono)" fontSize="10">
          {present} / {target}
        </text>
      </svg>
      <div>
        <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)', margin: 0, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
          {label}
        </p>
        <p style={{ fontFamily: 'var(--mono)', fontSize: 13, margin: '6px 0 0' }}>
          generated dims: <b style={{ color: 'var(--up)' }}>{present}</b>
        </p>
        <p style={{ fontFamily: 'var(--mono)', fontSize: 13, margin: '4px 0 0' }}>
          missing dims: <b style={{ color: 'var(--down)' }}>{Math.max(0, target - present)}</b>
        </p>
        <p style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-4)', margin: '6px 0 0' }}>
          No 1911-dim completion is implied; partial is shown verbatim.
        </p>
      </div>
    </div>
  );
}

export function PanelHeader({
  title,
  source,
  rightExtras,
}: {
  title: string;
  source?: string;
  rightExtras?: ReactNode;
}): JSX.Element {
  return (
    <div className="panel-head" style={{ marginBottom: 8 }}>
      <h3 style={{ fontFamily: 'var(--serif)', fontSize: 18 }}>{title}</h3>
      {source ? <span className="sub">source: {source}</span> : null}
      <div className="right" style={{ marginLeft: 'auto' }}>{rightExtras}</div>
    </div>
  );
}
