import { Metric, Panel } from './cockpitComponents';
import { usePayloadFile, fmtAge, ageClass } from '../hooks/usePayloadFile';
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export const EDGE_RECOVERY_PATH = '/v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/operator_dashboard_payload.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';
const BACKTEST_EDGE_PATH = '/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_symbol_all_timeframe_backtest_edge_status.json';

interface LiveGateRuntimePayload {
  live_gate?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
}

interface SymbolSummary {
  symbol?: string;
  after_cost_expectancy_bps?: number | null;
}

interface PublicIntelMode {
  mode?: string;
  outcome_sample_count?: number;
  after_cost_expectancy_bps?: number | null;
  after_cost_proof_state?: string;
}

interface StrategyRow {
  strategy?: string;
  selected_trade_count?: number;
  actionable_outcome_sample_count?: number;
  after_cost_expectancy_bps?: number | null;
  diagnostic_verdict?: string;
}

interface BacktestEdgePayload {
  after_cost_expectancy_bps?: number | null;
  after_cost_ci_lower_bps?: number | null;
  edge_claimed?: boolean;
  edge_verdict?: string;
  edge_verdict_reason?: string;
  status?: string;
  live_gate?: string;
  symbols_count?: number;
  sample_count?: number;
  sample_count_enough?: boolean;
  drawdown?: number | null;
  blockers?: string[];
  generated_est?: string;
}

interface EdgeRecoveryPayload {
  generated_est?: string;
  go_no_go?: string;
  live_gate?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
  why_live_is_blocked?: string[];
  summary?: {
    symbol_count?: number;
    classification_counts?: Record<string, number>;
    top_positive_symbols?: SymbolSummary[];
    top_negative_symbols?: SymbolSummary[];
    public_intel_modes?: PublicIntelMode[];
    calibration_error_bps?: number | null;
    high_confidence_loser_count?: number;
    risk_block_category_counts?: Record<string, number>;
    best_diagnostic_strategy?: StrategyRow;
    after_quality_fixes_expectancy_bps?: number | null;
    after_quality_fixes_ci_lower_bps?: number | null;
    pre_filter_after_cost_expectancy_bps?: number | null;
    pre_filter_after_cost_ci_lower_bps?: number | null;
    after_quality_fixes_candidate_count?: number;
    primary_live_recommendation?: string;
    website_sync_status?: string;
    next_automatic_action?: string;
  };
  strategy_fallback_edge_comparison?: {
    strategy_rows?: StrategyRow[];
  };
}

function chipClass(value?: string): string {
  const upper = (value ?? '').toUpperCase();
  if (upper.includes('BLOCK') || upper.includes('NEGATIVE') || upper.includes('NOT_PROVEN')) return 'chip solid-block';
  if (upper.includes('READY') || upper.includes('PASS') || upper.includes('SYNCED')) return 'chip solid-ok';
  return 'chip solid-paper';
}

function numberText(value: unknown, digits = 3): string {
  if (typeof value === 'string' && value.toUpperCase().includes('MISSING')) return 'Current edge value pending';
  if (typeof value !== 'number' || !Number.isFinite(value)) return value === null || value === undefined ? 'Current edge value pending' : String(value);
  return value.toFixed(Math.abs(value) >= 100 ? 0 : digits);
}

function bpsAsPercent(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return value === null || value === undefined ? 'Current edge value pending' : String(value);
  const pct = value / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(digits)}%`;
}

function countText(counts?: Record<string, number>): string {
  if (!counts) return 'Current edge count pending';
  return Object.entries(counts)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}: ${value}`)
    .join(' / ');
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function sortedCounts(counts?: Record<string, number>): Array<[string, number]> {
  return Object.entries(counts ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value) && value > 0)
    .sort(([, a], [, b]) => b - a);
}

function pctText(value: number): string {
  return `${value.toFixed(value >= 10 ? 0 : 1)}%`;
}

function tooltipValue(value: unknown, suffix = ''): string {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : null;
  if (n !== null) return `${n.toLocaleString('en-US', { maximumFractionDigits: 3 })}${suffix}`;
  return value === null || value === undefined ? 'Current value pending' : String(value);
}

function sanitizeRuntimeText(value: string): string {
  return value
    .replaceAll('blocked_human_only', 'archived human-only packet')
    .replaceAll('enabled_operator_approved', 'gate approved')
    .replaceAll('LIVE BLOCKED', 'archived packet blocked')
    .replaceAll('live_symbols=[]', 'live_symbols=none')
    .replaceAll('execution_live_symbols=[]', 'execution_live_symbols=none')
    .replaceAll('MISSING_EVIDENCE', 'current evidence pending')
    .replaceAll('MISSING_SOURCE', 'current source connecting');
}

function EdgeGauge({
  label,
  value,
  min,
  max,
  unit = '',
  goodAbove,
  goodBelow,
}: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  unit?: string;
  goodAbove?: number;
  goodBelow?: number;
}): JSX.Element {
  const pct = value === null ? 0 : clamp(((value - min) / (max - min || 1)) * 100, 0, 100);
  const tone = value === null
    ? 'neutral'
    : goodBelow !== undefined
      ? value <= goodBelow ? 'ok' : value <= goodBelow * 2 ? 'warn' : 'block'
      : goodAbove === undefined ? 'warn' : value >= goodAbove ? 'ok' : 'block';
  const color = tone === 'ok' ? 'var(--ok)' : tone === 'block' ? 'var(--block)' : 'var(--warn)';
  const background = `conic-gradient(${color} 0 ${pct}%, color-mix(in oklch, var(--surface-3) 78%, transparent) ${pct}% 100%)`;
  return (
    <div className={`edge-visual-card edge-visual-card--${tone}`}>
      <div className="edge-gauge" style={{ background }}>
        <span>{value === null ? 'NA' : `${numberText(value, 2)}${unit}`}</span>
      </div>
      <div>
        <strong>{label}</strong>
        <small>range {numberText(min, 0)} to {numberText(max, 0)}{unit}</small>
      </div>
    </div>
  );
}

function EdgeDonut({
  title,
  counts,
}: {
  title: string;
  counts?: Record<string, number>;
}): JSX.Element {
  const rows = sortedCounts(counts);
  const total = rows.reduce((sum, [, value]) => sum + value, 0);
  const palette = ['#14b8a6', '#ef4444', '#f59e0b', '#3b82f6', '#8b5cf6', '#64748b'];
  const chartRows = rows.map(([name, value]) => ({ name, value }));
  return (
    <div className="edge-donut-card">
      <div className="edge-donut edge-donut--recharts">
        {chartRows.length ? (
          <PieChart width={136} height={136}>
            <Pie data={chartRows} dataKey="value" nameKey="name" innerRadius={38} outerRadius={58} paddingAngle={2}>
              {chartRows.map((entry, index) => (
                <Cell key={entry.name} fill={palette[index % palette.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => tooltipValue(value)} />
          </PieChart>
        ) : null}
        <span>{total.toLocaleString('en-US')}</span>
      </div>
      <div className="edge-donut-card__body">
        <strong>{title}</strong>
        {rows.length ? rows.slice(0, 4).map(([label, value], index) => (
          <small key={label}>
            <i style={{ background: palette[index % palette.length] }} />
            {label}: {value.toLocaleString('en-US')} ({pctText((value / total) * 100)})
          </small>
        )) : <small>Current edge recovery rows are pending</small>}
      </div>
    </div>
  );
}

function EdgeBarList({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: SymbolSummary[];
  tone: 'positive' | 'negative';
}): JSX.Element {
  const values = rows.map((row) => Math.abs(finite(row.after_cost_expectancy_bps) ?? 0));
  const max = Math.max(1, ...values);
  const chartRows = rows.slice(0, 7).map((row) => ({
    symbol: row.symbol ?? 'NA',
    edge_pct: (finite(row.after_cost_expectancy_bps) ?? 0) / 100,
  }));
  return (
    <div className={`edge-bar-card edge-bar-card--${tone}`}>
      <h3>{title}</h3>
      {chartRows.length ? (
        <div className="edge-recharts-bars">
          <BarChart width={420} height={150} data={chartRows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <XAxis dataKey="symbol" tick={{ fontSize: 10 }} interval={0} minTickGap={0} />
            <YAxis tick={{ fontSize: 10 }} width={34} />
            <Tooltip formatter={(value) => tooltipValue(value, '%')} />
            <Bar dataKey="edge_pct" radius={[4, 4, 0, 0]} fill={tone === 'positive' ? '#14b8a6' : '#ef4444'} />
          </BarChart>
        </div>
      ) : null}
      {rows.length ? rows.slice(0, 7).map((row) => {
        const raw = finite(row.after_cost_expectancy_bps);
        const width = `${clamp((Math.abs(raw ?? 0) / max) * 100, 4, 100)}%`;
        return (
          <div className="edge-bar-row" key={`${title}-${row.symbol}`}>
            <span>{row.symbol ?? 'Current symbol pending'}</span>
            <div><i style={{ width }} /></div>
            <strong>{bpsAsPercent(raw)}</strong>
          </div>
        );
      }) : <p className="cockpit-evidence-note">Current edge recovery rows are pending.</p>}
    </div>
  );
}

function PublicIntelHeatmap({ rows }: { rows: PublicIntelMode[] }): JSX.Element {
  const values = rows.map((row) => finite(row.after_cost_expectancy_bps) ?? 0);
  const maxAbs = Math.max(1, ...values.map((value) => Math.abs(value)));
  return (
    <div className="edge-public-intel-grid">
      {rows.slice(0, 8).map((row) => {
        const value = finite(row.after_cost_expectancy_bps);
        const strength = clamp(Math.abs(value ?? 0) / maxAbs, 0.12, 1);
        const background = value === null
          ? 'var(--surface-2)'
          : value >= 0
            ? `color-mix(in oklch, var(--ok) ${Math.round(18 + strength * 34)}%, var(--surface-1))`
            : `color-mix(in oklch, var(--block) ${Math.round(16 + strength * 34)}%, var(--surface-1))`;
        return (
          <div className="edge-public-intel-cell" style={{ background }} key={row.mode ?? 'mode'}>
            <span>{row.mode ?? 'Current mode pending'}</span>
            <strong>{bpsAsPercent(value)}</strong>
            <small>{row.outcome_sample_count ?? 0} samples / {row.after_cost_proof_state ?? 'Current proof state pending'}</small>
          </div>
        );
      })}
    </div>
  );
}

export function EdgeRecoveryQualityPanel({ surface = 'runtime' }: { surface?: string }): JSX.Element {
  const { data, error, ageSeconds } = usePayloadFile<EdgeRecoveryPayload>(EDGE_RECOVERY_PATH, 30_000);
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const { data: backtestEdge, ageSeconds: backtestEdgeAge } = usePayloadFile<BacktestEdgePayload>(BACKTEST_EDGE_PATH, 30_000);
  const summary = data?.summary ?? {};
  const publicModes = summary.public_intel_modes ?? [];
  const strategyRows = data?.strategy_fallback_edge_comparison?.strategy_rows ?? [];
  const topPositive = summary.top_positive_symbols ?? [];
  const topNegative = summary.top_negative_symbols ?? [];
  const currentExecutionSymbols = liveGateRuntime?.execution_live_symbols ?? liveGateRuntime?.live_symbols ?? [];
  const whyBlocked = (data?.why_live_is_blocked?.length ? data.why_live_is_blocked : [
    sanitizeRuntimeText(`current live gate=${liveGateRuntime?.live_gate ?? 'runtime pending'}`),
    `execution_symbols=${currentExecutionSymbols.length}`,
    'edge diagnostics do not submit orders',
  ]).map(sanitizeRuntimeText);

  return (
    <Panel
      id={`edge-recovery-quality-${surface}`}
      title="Edge Recovery And Signal Quality"
      right={
        <div className="enterprise-cockpit-hero-chips">
          <span className={chipClass(data?.go_no_go)}>{data?.go_no_go ?? 'edge payload not loaded'}</span>
          <span className={`chip ${ageClass(ageSeconds, 300) === 'ok' ? 'solid-ok' : 'solid-warn'}`}>Age: {fmtAge(ageSeconds)}</span>
        </div>
      }
    >
      {backtestEdge && (
        <div className="cockpit-analytics-grid" style={{ marginBottom: '0.75rem' }}>
          <div className="metric">
            <span className="metric-label">Live edge status (fresh {fmtAge(backtestEdgeAge)})</span>
            <span className={`metric-value ${backtestEdge.edge_claimed ? 'metric--ok' : 'metric--block'}`}>
              {backtestEdge.edge_verdict ?? backtestEdge.status ?? '—'}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Expectancy</span>
            <span className={`metric-value ${(backtestEdge.after_cost_expectancy_bps ?? -1) > 0 ? 'metric--ok' : 'metric--block'}`}>
              {bpsAsPercent(backtestEdge.after_cost_expectancy_bps)}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">CI lower</span>
            <span className={`metric-value ${(backtestEdge.after_cost_ci_lower_bps ?? -1) > 0 ? 'metric--ok' : 'metric--block'}`}>
              {bpsAsPercent(backtestEdge.after_cost_ci_lower_bps)}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Symbols / Samples</span>
            <span className="metric-value">{backtestEdge.symbols_count ?? '—'} / {backtestEdge.sample_count?.toLocaleString('en-US') ?? '—'}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Live gate</span>
            <span className="metric-value metric--block">{backtestEdge.live_gate ?? '—'}</span>
          </div>
        </div>
      )}
      {error ? <p className="cockpit-evidence-gap" role="alert">{error}</p> : null}
      <p className="cockpit-evidence-note" style={{ marginBottom: '0.5rem' }}>
        Detailed analysis below is from archived edge recovery snapshot (age: {fmtAge(ageSeconds)}). Fresh live edge shown above.
      </p>
      <div className="cockpit-analytics-grid">
        <Metric label="Symbols" value={summary.symbol_count ?? 0} />
        <Metric label="Pre-filter expectancy" value={bpsAsPercent(summary.pre_filter_after_cost_expectancy_bps)} />
        <Metric label="Pre-filter CI lower" value={bpsAsPercent(summary.pre_filter_after_cost_ci_lower_bps)} />
        <Metric label="After-fix expectancy" value={bpsAsPercent(summary.after_quality_fixes_expectancy_bps)} />
        <Metric label="After-fix CI lower" value={bpsAsPercent(summary.after_quality_fixes_ci_lower_bps)} />
        <Metric label="After-fix candidates" value={summary.after_quality_fixes_candidate_count ?? 0} />
        <Metric label="Calibration error" value={bpsAsPercent(summary.calibration_error_bps)} />
        <Metric label="High-conf losers" value={summary.high_confidence_loser_count ?? 0} />
        <Metric label="Recommendation" value={summary.primary_live_recommendation ?? 'BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN'} />
        <Metric label="Website sync" value={summary.website_sync_status ?? 'Current website sync pending'} />
      </div>

      <div className="edge-visual-grid" aria-label="Edge quality visual summary">
        <EdgeGauge
          label="Pre-filter expectancy"
          value={finite(summary.pre_filter_after_cost_expectancy_bps) === null ? null : finite(summary.pre_filter_after_cost_expectancy_bps)! / 100}
          min={-0.3}
          max={0.3}
          unit="%"
          goodAbove={0}
        />
        <EdgeGauge
          label="After-fix expectancy"
          value={finite(summary.after_quality_fixes_expectancy_bps) === null ? null : finite(summary.after_quality_fixes_expectancy_bps)! / 100}
          min={-0.3}
          max={0.3}
          unit="%"
          goodAbove={0}
        />
        <EdgeGauge
          label="Calibration error"
          value={finite(summary.calibration_error_bps) === null ? null : finite(summary.calibration_error_bps)! / 100}
          min={0}
          max={1}
          unit="%"
          goodBelow={0.25}
        />
        <EdgeDonut title="Symbol classification" counts={summary.classification_counts} />
        <EdgeDonut title="Risk block mix" counts={summary.risk_block_category_counts} />
      </div>

      <div className="edge-flow-grid">
        <EdgeBarList title="Top positive edge candidates" rows={topPositive} tone="positive" />
        <EdgeBarList title="Top negative edge blocks" rows={topNegative} tone="negative" />
      </div>

      {publicModes.length ? <PublicIntelHeatmap rows={publicModes} /> : null}

      <div className="cockpit-card-grid" style={{ marginTop: '1rem' }}>
        <div className="cockpit-exchange-card">
          <h3>By-Symbol Edge</h3>
          <p className="cockpit-evidence-note">{countText(summary.classification_counts)}</p>
        </div>
        <div className="cockpit-exchange-card">
          <h3>Risk / Execution Blocks</h3>
          <p className="cockpit-evidence-note">{countText(summary.risk_block_category_counts)}</p>
        </div>
        <div className="cockpit-evidence-gap">
          <strong>Runtime gate context</strong>
          <p>{whyBlocked.join(' / ')}</p>
        </div>
        <div className="cockpit-evidence-gap">
          <strong>Next automatic action</strong>
          <p>{summary.next_automatic_action ?? 'Continue execution/shadow outcome mining with quality overlay.'}</p>
        </div>
      </div>

      <div className="cockpit-market-table" role="table" aria-label="Edge recovery symbol table" style={{ marginTop: '1rem' }}>
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Positive candidates</span><span>Edge %</span><span>Negative blocks</span><span>Edge %</span>
        </div>
        {Array.from({ length: Math.max(topPositive.length, topNegative.length, 1) }).slice(0, 8).map((_, index) => {
          const pos = topPositive[index];
          const neg = topNegative[index];
          return (
            <div className="cockpit-table-row" role="row" key={`edge-symbol-${index}`}>
              <span>{pos?.symbol ?? 'Current symbol pending'}</span>
              <span>{bpsAsPercent(pos?.after_cost_expectancy_bps)}</span>
              <span>{neg?.symbol ?? 'Current symbol pending'}</span>
              <span>{bpsAsPercent(neg?.after_cost_expectancy_bps)}</span>
            </div>
          );
        })}
      </div>

      <div className="cockpit-market-table" role="table" aria-label="Public intelligence contribution table" style={{ marginTop: '1rem' }}>
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Public-intel mode</span><span>Samples</span><span>After-cost edge</span><span>Proof state</span>
        </div>
        {publicModes.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.mode ?? 'mode'}>
            <span>{row.mode ?? 'Current mode pending'}</span>
            <span>{row.outcome_sample_count ?? 0}</span>
            <span>{bpsAsPercent(row.after_cost_expectancy_bps)}</span>
            <span>{row.after_cost_proof_state ?? 'Current proof state pending'}</span>
          </div>
        ))}
      </div>

      <div className="cockpit-market-table" role="table" aria-label="Strategy fallback comparison table" style={{ marginTop: '1rem' }}>
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Strategy</span><span>Selected</span><span>Samples</span><span>After-cost edge</span><span>Verdict</span>
        </div>
        {strategyRows.slice(0, 10).map((row) => (
          <div className="cockpit-table-row" role="row" key={row.strategy ?? 'strategy'}>
            <span>{row.strategy ?? 'Current strategy pending'}</span>
            <span>{row.selected_trade_count ?? 0}</span>
            <span>{row.actionable_outcome_sample_count ?? 0}</span>
            <span>{bpsAsPercent(row.after_cost_expectancy_bps)}</span>
            <span>{row.diagnostic_verdict ?? 'Current diagnostic pending'}</span>
          </div>
        ))}
      </div>

      <p className="cockpit-evidence-note">
        Source: {EDGE_RECOVERY_PATH}. Generated EST: {data?.generated_est ?? 'Current edge timestamp pending'}.
      </p>
    </Panel>
  );
}
