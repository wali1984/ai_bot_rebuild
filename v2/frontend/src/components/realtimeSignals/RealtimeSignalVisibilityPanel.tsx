import { useEffect, useMemo, useState } from 'react';
import { Metric, Panel } from '../../pages/cockpitComponents';
import { valueText } from '../../pages/cockpitData';
import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';
import { useOptionalAuth } from '../../hooks/useAuth';
import { useRoles } from '../../auth/rbac';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { getV2Signals } from '../../api/v2Signals';
import type { SignalData } from '../../types/apiV2';
import {
  accuracyCell as lookupAccuracyCell,
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  type SignalPredictionAccuracyCell,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';

export const REALTIME_SIGNALS_PAYLOAD_PATH = '/operator_runtime/v2_signals/latest/signals_payload.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

const MATRIX_CORE_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'];
const MATRIX_FALLBACK_SYMBOLS = [
  'BNBUSDT',
  'XRPUSDT',
  'AVAXUSDT',
  'DOGEUSDT',
  'ADAUSDT',
  'DOTUSDT',
  'LINKUSDT',
  'ARBUSDT',
];
const MATRIX_DEFAULT_EXTRA_SYMBOLS = 5;
const MATRIX_ACTIVE_SIGNAL_PREVIEW = 8;
const MATRIX_LINEAGE_PREVIEW = 8;
const MATRIX_DEFAULT_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'];
const MATRIX_EMPTY_SYMBOLS: string[] = [];
const MATRIX_TIMEFRAME_ORDER = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '1w'];
const LOCAL_TRADER_PREVIEW_ID = 'trader-wajidali1984';
const LOCAL_PAPER_PREVIEW_ID = 'paper-wajidali1984';
const MATRIX_DECISION_CHART_LABELS: Record<ActionBucket, string> = {
  BUY: 'Long signal',
  SELL: 'Short signal',
  HOLD: 'Hold / No action',
};

type ActionBucket = 'BUY' | 'SELL' | 'HOLD';

interface DecisionBucket {
  key: ActionBucket;
  label: string;
  color: string;
  count: number;
}

function dedupe(values: string[]): string[] {
  return [...new Set(values)];
}

function orderTimeframes(values: string[]): string[] {
  const set = new Set(values.filter((value) => typeof value === 'string' && value.trim().length > 0));
  const ordered = [...set].sort((a, b) => {
    const aIdx = MATRIX_TIMEFRAME_ORDER.indexOf(a);
    const bIdx = MATRIX_TIMEFRAME_ORDER.indexOf(b);
    if (aIdx === -1 || bIdx === -1) {
      return aIdx === -1 && bIdx === -1 ? a.localeCompare(b) : aIdx === -1 ? 1 : -1;
    }
    return aIdx - bIdx;
  });
  return ordered;
}

function sameStringList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function compactAction(action: string | null | undefined): string {
  const text = String(action ?? '').toUpperCase();
  if (!text) return 'Hold';
  if (text.includes('LONG') || text.includes('BUY')) return 'Buy / Long';
  if (text.includes('SHORT') || text.includes('SELL')) return 'Sell / Short';
  if (text.includes('HOLD') || text.includes('NEUTRAL')) return 'Hold';
  return action === null || action === undefined ? 'Hold' : action;
}

function actionBucket(action: string | null | undefined): ActionBucket {
  const text = String(action ?? '').toUpperCase();
  if (text.includes('LONG') || text.includes('BUY')) return 'BUY';
  if (text.includes('SHORT') || text.includes('SELL')) return 'SELL';
  return 'HOLD';
}

function decisionBuckets(rows: ActiveSignal[]): DecisionBucket[] {
  const counts = { BUY: 0, SELL: 0, HOLD: 0 };
  for (const row of rows) {
    const bucket = actionBucket(row.action);
    counts[bucket] += 1;
  }
  return [
    {
      key: 'BUY',
      label: MATRIX_DECISION_CHART_LABELS.BUY,
      count: counts.BUY,
      color: 'var(--buy, #00d4a3)',
    },
    {
      key: 'SELL',
      label: MATRIX_DECISION_CHART_LABELS.SELL,
      count: counts.SELL,
      color: 'var(--sell, #f6465d)',
    },
    {
      key: 'HOLD',
      label: MATRIX_DECISION_CHART_LABELS.HOLD,
      count: counts.HOLD,
      color: 'var(--text-secondary, #6b7c93)',
    },
  ];
}

function shortSymbol(symbol: string): string {
  return symbol.replace(/USDT$/, '');
}

function readableStatus(raw: unknown, fallback = 'pending'): string {
  if (raw === null || raw === undefined || raw === '') return fallback;
  const text = String(raw).trim();
  if (text === 'true') return 'passed';
  if (text === 'false') return 'blocked';
  return text
    .replace(/paper/gi, 'execution')
    .replaceAll('_', ' ')
    .toLowerCase();
}

function readableTitle(raw: unknown, fallback = 'pending'): string {
  const text = readableStatus(raw, fallback);
  return text.replace(/^./u, (char) => char.toUpperCase());
}

interface LiveGateRuntimePayload {
  execution_live_symbols?: string[];
  live_gate?: string;
  live_symbols?: string[];
  order_transport_submit_enabled?: boolean;
  trader_execution_enabled?: boolean;
  live_order_submit_allowed?: boolean;
  live_blocked?: boolean;
  live_blocker?: string;
  places_real_order?: boolean;
}

interface PredictionRow {
  symbol: string;
  timeframe: string;
  status: string;
  generated_est?: string | null;
  trainer_source?: string | null;
  model_source?: string | null;
  selected_action?: string | null;
  confidence_calibrated?: number | null;
  expected_move_bps?: number | null;
  expected_move_after_cost_bps?: number | null;
  last_price?: number | null;
  price_target?: number | null;
  feature_snapshot_id?: string | null;
  prediction_id?: string | null;
  freshness_seconds?: number | null;
  missing_stale_reason?: string | null;
  implementation_task?: string | null;
}

interface RuntimeSurface {
  surface_id: string;
  source_redis_key: string;
  publisher_process_service: string;
  payload_path: string;
  freshness_seconds?: number | null;
  symbols_covered?: string[];
  timeframes_covered?: string[];
  missing_stale_reason?: string | null;
  generated_est?: string | null;
}

interface ActiveSignal {
  signal_id?: string | null;
  prediction_id?: string | null;
  risk_decision_id?: string | null;
  orchestrator_decision_id?: string | null;
  symbol?: string | null;
  timeframe?: string | null;
  action?: string | null;
  price_target?: number | null;
  confidence?: number | null;
  expected_move_after_cost_bps?: number | null;
  last_price?: number | null;
  risk_state?: string | null;
  risk_status_label?: string | null;
  orchestrator_state?: string | null;
  orchestrator_status_label?: string | null;
  paper_state?: string | null;
  paper_status_label?: string | null;
  ledger_status_label?: string | null;
  paper_intent_id?: string | null;
  paper_ledger_id?: string | null;
  ledger_id?: string | null;
  paper_fill_status?: string | null;
  reason?: string | null;
  blocked_reason?: string | null;
  generated_est?: string | null;
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_specific?: boolean | null;
  lineage_ids?: {
    trainer_prediction_id?: string | null;
    risk_decision_id?: string | null;
    orchestrator_decision_id?: string | null;
    paper_intent_id?: string | null;
    paper_ledger_id?: string | null;
  };
}

function scopeToken(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function signalVisibleForTrader(signal: ActiveSignal, traderId: string | null, paperAccountId: string | null): boolean {
  const rowTraderId = scopeToken(signal.trader_id);
  const rowPaperAccountId = scopeToken(signal.paper_account_id);
  const accountSpecific = signal.account_specific === true || Boolean(rowTraderId || rowPaperAccountId);
  if (!accountSpecific) return true;
  if (!traderId || !paperAccountId) return false;
  return rowTraderId === traderId && rowPaperAccountId === paperAccountId;
}

interface LineageRow {
  signal_id?: string | null;
  symbol?: string | null;
  timeframe?: string | null;
  trainer_prediction_exists?: boolean;
  risk_decision_exists?: boolean;
  orchestrator_decision_exists?: boolean;
  paper_intent_exists?: boolean;
  paper_ledger_exists?: boolean;
  exact_blocker?: string | null;
}

interface DeploymentRouteHash {
  route: string;
  http_status?: number | null;
  content_hash?: string | null;
  error?: string | null;
}

interface RealtimeSignalsPayload {
  generated_at?: string;
  generated_est?: string;
  safety?: {
    live_gate?: string;
    live_symbols?: string[];
    execution_live_symbols?: string[];
    approves_live?: boolean;
    approves_canary?: boolean;
    writes_exchange_orders?: boolean;
    writes_legacy_redis?: boolean;
    redis_trim_performed?: boolean;
    test_order_endpoint_called?: boolean;
    leverage_changed?: boolean;
    margin_mode_changed?: boolean;
    raw_credentials_exposed?: boolean;
  };
  summary?: {
    symbols_count?: number;
    timeframes_count?: number;
    prediction_rows_count?: number;
    present_prediction_count?: number;
    missing_prediction_count?: number;
    active_signal_count?: number;
    live_gate?: string;
    live_symbols?: string[];
    execution_live_symbols?: string[];
  };
  runtime_source_inventory?: {
    missing_or_stale_count?: number;
    surfaces?: RuntimeSurface[];
  };
  prediction_contract?: {
    status?: string;
    required_timeframes?: string[];
    timeframes_covered?: string[];
    symbols_covered?: string[];
    prediction_rows?: PredictionRow[];
    implementation_tasks?: string[];
  };
  price_target_generation?: {
    status?: string;
    validation_status?: string;
    invalid_or_missing_count?: number;
  };
  signal_publisher?: {
    status?: string;
    signal_count?: number;
    published_signals?: ActiveSignal[];
    publish_contract?: {
      redis_writes_performed?: boolean;
      old_redis_writes_performed?: boolean;
      no_live_order_keys?: boolean;
      intended_v2_redis_keys?: string[];
      public_payload?: string;
    };
  };
  signal_lineage?: {
    status?: string;
    chain_complete_count?: number;
    missing_lineage_count?: number;
    lineage_rows?: LineageRow[];
  };
  website_deployment_truth?: {
    status?: string;
    local_dev_server_bundle_hash?: string | null;
    public_payload_hash?: string | null;
    production_base_url?: string;
    production_route_hashes?: DeploymentRouteHash[];
    deploy_build_command_path?: string;
    claim_scope?: string;
  };
}

function present(value: unknown, fallback = 'unpublished'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString('en-US') : fallback;
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  return String(value);
}

function compact(value: unknown, fallback = 'unpublished', max = 32): string {
  const text = present(value, fallback);
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function finiteNumber(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

function bps(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} bps` : 'unpublished';
}

function statusTone(status?: string | null): 'ok' | 'warn' | 'block' | 'paper' {
  const upper = String(status ?? '').toUpperCase();
  if (upper.includes('PRESENT') || upper.includes('VALID') || upper.includes('READY') || upper.includes('VISIBLE')) return 'ok';
  if (upper.includes('MISSING') || upper.includes('BLOCK') || upper.includes('STALE') || upper.includes('ERROR')) return 'block';
  if (upper.includes('PARTIAL') || upper.includes('WARN')) return 'warn';
  return 'paper';
}

function chip(status?: string | null, label?: string): JSX.Element {
  const tone = statusTone(status);
  return <span className={`chip solid-${tone}`}>{label ?? present(status, 'current source pending')}</span>;
}

function boolStatus(value: boolean | undefined): string {
  return value ? 'present' : 'missing';
}

function gateText(raw: unknown, fallback: string): string {
  return readableStatus(raw, fallback).replace(/^./u, (char) => char.toUpperCase());
}

function gateShortStatus(raw: unknown, fallback: string): string {
  return readableStatus(raw, fallback);
}

function gateReason(signal: ActiveSignal, showAdvanced = false): string {
  const reason = signal.blocked_reason ?? signal.reason;
  return showAdvanced ? compact(reason, 'none', 56) : compact(readableStatus(reason, 'none'), 'none', 56);
}

function expectedMoveDistance(target: unknown, lastPrice: unknown): string {
  const targetValue = finiteNumber(target);
  const lastValue = finiteNumber(lastPrice);
  if (targetValue === null || lastValue === null || lastValue <= 0) return 'target distance pending';
  const pct = ((targetValue - lastValue) / lastValue) * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function statusSentence(raw: unknown, fallback: string): string {
  if (raw === null || raw === undefined || raw === '') return fallback;
  if (raw === true) return 'passed';
  if (raw === false) return 'blocked';
  return String(raw).replace(/paper/gi, 'execution').replaceAll('_', ' ').toLowerCase();
}

function activeSignalStatusLine(signal: ActiveSignal): string {
  const risk = gateShortStatus(signal.risk_status_label ?? signal.risk_state, 'risk pending');
  const routing = gateShortStatus(signal.orchestrator_status_label ?? signal.orchestrator_state, 'routing pending');
  const execution = gateShortStatus(signal.paper_status_label ?? signal.paper_state ?? signal.paper_fill_status, 'execution pending');
  const blocker = gateReason(signal);
  const hasBlocker = blocker !== 'none';
  return `Risk ${risk} · Routing ${routing} · Execution ${execution}${hasBlocker ? ` · Blocker ${blocker}` : ''}`;
}

function activeSignalLineageTrail(signal: ActiveSignal, showAdvanced: boolean): string {
  const ids = signal.lineage_ids;
  if (!ids) return 'lineage chain not yet published';
  const trail = [
    ['prediction', ids.trainer_prediction_id],
    ['risk', ids.risk_decision_id],
    ['orchestrator', ids.orchestrator_decision_id],
    ['execution intent', ids.paper_intent_id],
    ['execution ledger', ids.paper_ledger_id],
  ];
  return showAdvanced
    ? trail.map(([label, id]) => `${label}: ${compact(id, 'pending', 12)}`).join(' · ')
    : trail
        .map(([label, id]) => `${label}: ${id ? 'set' : 'pending'}`)
        .join(' · ');
}

function formatTargetTargetLabel(signal: ActiveSignal): string {
  const move = bps(signal.expected_move_after_cost_bps);
  const distance = expectedMoveDistance(signal.price_target, signal.last_price);
  if (move === 'unpublished' && distance === 'target distance pending') return 'No target yet';
  if (move === 'unpublished') return `Target ${distance}`;
  if (distance === 'target distance pending') return `${move} expected`;
  return `${move} expected · ${distance}`;
}

function tradeActionTone(action: string | null | undefined): 'ok' | 'warn' | 'paper' {
  const text = compactAction(action).toLowerCase();
  if (text.includes('buy') || text.includes('long')) return 'ok';
  if (text.includes('sell') || text.includes('short')) return 'warn';
  return 'paper';
}

function confidenceText(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'unpublished';
  return `${(value * 100).toFixed(1)}%`;
}

function accuracyOutcomeLine(cell: SignalPredictionAccuracyCell | null): string {
  if (!cell || !cell.evaluated_count) return 'Accuracy pending · no evaluated PnL';
  return `${formatAdaptivePercent(cell.accuracy)} · ${cell.correct_count ?? 0}/${cell.evaluated_count} hits · ${formatAdaptiveMoney(cell.realized_pnl_usd)} PnL`;
}

function accuracyOutcomeColor(cell: SignalPredictionAccuracyCell | null): string {
  if (!cell || !cell.evaluated_count) return 'var(--text-muted)';
  return adaptiveStatusColor(cell.status);
}

function chainReadinessPlainText(signal: ActiveSignal): string {
  const risk = signal.risk_status_label ?? signal.risk_state ?? 'risk pending';
  const routing = signal.orchestrator_status_label ?? signal.orchestrator_state ?? 'routing pending';
  const execution = signal.paper_status_label ?? signal.paper_state ?? signal.paper_fill_status ?? 'execution pending';
  return `Risk ${gateShortStatus(risk, 'risk pending')} · Routing ${gateShortStatus(routing, 'routing pending')} · Execution ${gateShortStatus(execution, 'execution pending')}`;
}

function GateCell({
  state,
  fallback,
  reason,
}: {
  state: string | null | undefined;
  fallback: string;
  reason: string;
}): JSX.Element {
  const status = gateText(state, fallback);
  const statusState = status.toLowerCase();
  const isBlocked = statusState.includes('blocked') || statusState.includes('denied') || statusState.includes('failed') || statusState.includes('not ready');
  return (
    <div className="realtime-signal-gate-cell">
      {chip(status, status)}
      <small>{isBlocked ? reason : status === fallback ? 'Waiting for gate decision.' : 'Decision evaluated.'}</small>
    </div>
  );
}

function chainReadiness(row: LineageRow): string {
  const checks = [
    row.trainer_prediction_exists,
    row.risk_decision_exists,
    row.orchestrator_decision_exists,
    row.paper_intent_exists,
    row.paper_ledger_exists,
  ];
  const passed = checks.filter(Boolean).length;
  if (passed === checks.length) return 'Fully ready';
  if (passed >= checks.length - 1) return 'Mostly ready';
  if (passed > 1) return 'Partially ready';
  return 'In review';
}

function rowKey(row: PredictionRow): string {
  return `${row.symbol}::${row.timeframe}`;
}

function rowNeedsContractFallback(row: PredictionRow | undefined): boolean {
  if (!row) return true;
  const status = String(row.status ?? '').toUpperCase();
  if (status.includes('PRESENT') && row.selected_action) return false;
  return (
    status.includes('MISSING') ||
    status.includes('STALE') ||
    status.includes('UNAVAILABLE') ||
    status.includes('ERROR') ||
    !row.selected_action
  );
}

function tfLabel(row: PredictionRow | undefined, accuracy: SignalPredictionAccuracyCell | null): JSX.Element {
  if (!row) {
    return (
      <span className="realtime-tf-cell__empty">
        <strong>Data source unavailable</strong>
        <small style={{ color: accuracyOutcomeColor(accuracy) }}>{accuracyOutcomeLine(accuracy)}</small>
      </span>
    );
  }
  const isCurrent = row.status === 'PRESENT_CURRENT' || row.status === 'PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY';
  const distance = expectedMoveDistance(row.price_target, row.last_price);
  const expectedMove = bps(row.expected_move_after_cost_bps);
  const confidence = row.confidence_calibrated == null ? 'confidence pending' : `${(row.confidence_calibrated * 100).toFixed(0)}%`;
  const blocker = row.missing_stale_reason ?? row.implementation_task ?? row.status;
  return (
    <span className={`realtime-tf-cell realtime-tf-cell--${statusTone(row.status)}`}>
      <strong>{isCurrent ? compactAction(row.selected_action) : present(row.status, 'Timeframe prediction source unavailable')}</strong>
      {isCurrent ? (
        <small>
          {distance} · {expectedMove} · {confidence}
        </small>
      ) : (
        <small>{compact(blocker, 'Data source unavailable', 48)}</small>
      )}
      <small style={{ color: accuracyOutcomeColor(accuracy) }}>{accuracyOutcomeLine(accuracy)}</small>
    </span>
  );
}

type RealtimeSignalVisibilityVariant = 'trader' | 'admin';

interface MatrixContractEntry {
  prediction: PredictionRow;
  signal: ActiveSignal;
}

function signalField(signal: Record<string, unknown>, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(signal, key) ? signal[key] : undefined;
}

function matrixEntryFromSignal(
  symbol: string,
  timeframe: string,
  signalData: SignalData | null,
): MatrixContractEntry | null {
  const active = signalData?.active_signal;
  if (!active || typeof active !== 'object') return null;
  const signal = active as Record<string, unknown>;
  const selectedAction = present(signalField(signal, 'selected_action') ?? signalField(signal, 'action') ?? signalField(signal, 'direction'), 'hold');
  const confidence = finiteNumber(signalField(signal, 'confidence_calibrated') ?? signalField(signal, 'confidence'));
  const expectedMoveAfterCostBps = finiteNumber(signalField(signal, 'expected_move_after_cost_bps'));
  const priceTarget = finiteNumber(
    signalField(signal, 'price_target_after_cost') ??
    signalField(signal, 'price_target') ??
    signalField(signal, 'target_1'),
  );
  const lastPrice = finiteNumber(signalField(signal, 'last_price'));
  const blockedReason = present(signalField(signal, 'blocked_reason') ?? signalField(signal, 'risk_result'), '');
  return {
    prediction: {
      symbol,
      timeframe,
      status: 'PRESENT_CURRENT',
      selected_action: selectedAction,
      confidence_calibrated: confidence,
      expected_move_after_cost_bps: expectedMoveAfterCostBps,
      last_price: lastPrice,
      price_target: priceTarget,
      prediction_id: present(signalField(signal, 'prediction_id') ?? signalField(signal, 'model_version'), ''),
      feature_snapshot_id: present(signalField(signal, 'market_state_id'), ''),
      missing_stale_reason: blockedReason || null,
    },
    signal: {
      signal_id: present(signalField(signal, 'signal_id'), ''),
      prediction_id: present(signalField(signal, 'prediction_id') ?? signalField(signal, 'model_version'), ''),
      symbol,
      timeframe,
      action: selectedAction,
      price_target: priceTarget,
      confidence,
      expected_move_after_cost_bps: expectedMoveAfterCostBps,
      last_price: lastPrice,
      risk_state: present(signalField(signal, 'risk_result') ?? signalField(signal, 'risk_state'), ''),
      orchestrator_state: present(signalField(signal, 'orchestrator_state'), ''),
      paper_state: present(signalField(signal, 'paper_state') ?? signalField(signal, 'paper_fill_status'), ''),
      blocked_reason: blockedReason || null,
      generated_est: present(signalField(signal, 'generated_est'), ''),
      account_specific: false,
    },
  };
}

export function RealtimeSignalVisibilityPanel({
  surface = 'runtime',
  variant = 'trader',
}: {
  surface?: string;
  variant?: RealtimeSignalVisibilityVariant;
}): JSX.Element {
  const { data, error, ageSeconds } = usePayloadFile<RealtimeSignalsPayload>(REALTIME_SIGNALS_PAYLOAD_PATH, 8_000);
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const { user } = useOptionalAuth();
  const sessionRole = useRoles();
  const localTraderPreview = !user && sessionRole === 'trader';
  const scopedTraderId = user?.trader_id ?? (localTraderPreview ? LOCAL_TRADER_PREVIEW_ID : null);
  const scopedPaperAccountId = user?.paper_account_id ?? (localTraderPreview ? LOCAL_PAPER_PREVIEW_ID : null);
  const showDiagnostics = variant === 'admin';
  const safeId = surface.replace(/[^a-z0-9_-]/gi, '-').toLowerCase();
  const rows = data?.prediction_contract?.prediction_rows ?? [];
  const timeframes = data?.prediction_contract?.timeframes_covered ?? MATRIX_DEFAULT_TIMEFRAMES;
  const symbols = data?.prediction_contract?.symbols_covered ?? MATRIX_EMPTY_SYMBOLS;
  const [matrixContractEntries, setMatrixContractEntries] = useState<Record<string, MatrixContractEntry>>({});
  const rowMap = new Map(rows.map((row) => [rowKey(row), row]));
  Object.entries(matrixContractEntries).forEach(([key, entry]) => {
    if (rowNeedsContractFallback(rowMap.get(key))) rowMap.set(key, entry.prediction);
  });
  const rawActiveSignals = data?.signal_publisher?.published_signals ?? [];
  const contractActiveSignals = Object.values(matrixContractEntries).map((entry) => entry.signal);
  const mergedRawActiveSignals = [...rawActiveSignals, ...contractActiveSignals];
  const activeSignals = showDiagnostics
    ? mergedRawActiveSignals
    : mergedRawActiveSignals.filter((signal) => signalVisibleForTrader(signal, scopedTraderId, scopedPaperAccountId));
  const withheldActiveSignalCount = Math.max(0, mergedRawActiveSignals.length - activeSignals.length);
  const surfaces = data?.runtime_source_inventory?.surfaces ?? [];
  const lineageRows = data?.signal_lineage?.lineage_rows ?? [];
  const deploymentRows = data?.website_deployment_truth?.production_route_hashes ?? [];
  const implementationTasks = data?.prediction_contract?.implementation_tasks ?? [];
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.signal_prediction_accuracy_status
    ?? null;
  const currentLiveGate = liveGateRuntime?.live_gate ?? data?.summary?.live_gate ?? data?.safety?.live_gate ?? 'loading';
  const currentLiveGateLabel = valueText(currentLiveGate);
  const currentLiveSymbols = liveGateRuntime?.live_symbols ?? data?.summary?.live_symbols ?? data?.safety?.live_symbols ?? [];
  const currentExecutionSymbols = liveGateRuntime?.execution_live_symbols ?? data?.summary?.execution_live_symbols ?? data?.safety?.execution_live_symbols ?? [];
  const decisionChartData = decisionBuckets(activeSignals);
  const activeDecisionCount = activeSignals.length || 0;

  const matrixSymbolOptions = useMemo(
    () => dedupe([...symbols, ...MATRIX_CORE_SYMBOLS, ...MATRIX_FALLBACK_SYMBOLS]),
    [symbols],
  );
  const matrixTimeframeOptions = useMemo(
    () => orderTimeframes(timeframes.length ? timeframes : MATRIX_DEFAULT_TIMEFRAMES),
    [timeframes],
  );
  const defaultMatrixSymbols = useMemo(() => {
    const preferred = dedupe([
      ...MATRIX_CORE_SYMBOLS.filter((symbol) => matrixSymbolOptions.includes(symbol)),
      ...MATRIX_FALLBACK_SYMBOLS.filter((symbol) => matrixSymbolOptions.includes(symbol)),
      ...matrixSymbolOptions.filter(
        (symbol) => !MATRIX_CORE_SYMBOLS.includes(symbol) && !MATRIX_FALLBACK_SYMBOLS.includes(symbol),
      ),
    ]);
    return preferred.slice(0, MATRIX_CORE_SYMBOLS.length + MATRIX_DEFAULT_EXTRA_SYMBOLS);
  }, [matrixSymbolOptions]);
  const defaultMatrixTimeframes = useMemo(() => {
    if (matrixTimeframeOptions.includes('5m')) return ['5m'];
    return matrixTimeframeOptions.length ? [matrixTimeframeOptions[0]] : ['5m'];
  }, [matrixTimeframeOptions]);

  const [selectedMatrixSymbols, setSelectedMatrixSymbols] = useState<string[]>(defaultMatrixSymbols);
  const [selectedMatrixTimeframes, setSelectedMatrixTimeframes] = useState<string[]>(defaultMatrixTimeframes);
  const [matrixSymbolSelectionTouched, setMatrixSymbolSelectionTouched] = useState(false);
  const [matrixTimeframeSelectionTouched, setMatrixTimeframeSelectionTouched] = useState(false);
  const [showAllMatrixSymbols, setShowAllMatrixSymbols] = useState(false);
  const [showAdvancedIds, setShowAdvancedIds] = useState(false);
  const [showAllActiveSignals, setShowAllActiveSignals] = useState(false);
  const [showAllLineageRows, setShowAllLineageRows] = useState(false);

  useEffect(() => {
    setSelectedMatrixSymbols((prev) => {
      if (!matrixSymbolSelectionTouched) return sameStringList(prev, defaultMatrixSymbols) ? prev : defaultMatrixSymbols;
      const active = (prev.length ? prev : defaultMatrixSymbols).filter((symbol) => matrixSymbolOptions.includes(symbol));
      const next = active.length === 0 ? defaultMatrixSymbols : dedupe(active);
      return sameStringList(prev, next) ? prev : next;
    });
    setSelectedMatrixTimeframes((prev) => {
      if (!matrixTimeframeSelectionTouched) return sameStringList(prev, defaultMatrixTimeframes) ? prev : defaultMatrixTimeframes;
      const active = (prev.length ? prev : defaultMatrixTimeframes).filter((tf) => matrixTimeframeOptions.includes(tf));
      const next = active.length === 0 && matrixTimeframeOptions.length > 0 ? defaultMatrixTimeframes : active;
      return sameStringList(prev, next) ? prev : next;
    });
  }, [
    defaultMatrixSymbols,
    defaultMatrixTimeframes,
    matrixSymbolOptions,
    matrixTimeframeOptions,
    matrixSymbolSelectionTouched,
    matrixTimeframeSelectionTouched,
  ]);

  const quickMatrixSymbols = useMemo(() => {
    const ordered = dedupe([
      ...MATRIX_CORE_SYMBOLS.filter((s) => matrixSymbolOptions.includes(s)),
      ...MATRIX_FALLBACK_SYMBOLS.filter((s) => matrixSymbolOptions.includes(s)),
      ...matrixSymbolOptions.filter((s) => !MATRIX_CORE_SYMBOLS.includes(s) && !MATRIX_FALLBACK_SYMBOLS.includes(s)),
    ]);
    return ordered.slice(0, MATRIX_CORE_SYMBOLS.length + MATRIX_DEFAULT_EXTRA_SYMBOLS);
  }, [matrixSymbolOptions]);

  const extendedMatrixSymbols = useMemo(
    () => matrixSymbolOptions.filter((symbol) => !quickMatrixSymbols.includes(symbol)),
    [matrixSymbolOptions, quickMatrixSymbols],
  );
  const matrixSymbols = selectedMatrixSymbols.length > 0 ? selectedMatrixSymbols : defaultMatrixSymbols;
  const matrixTimeframes = selectedMatrixTimeframes.length > 0 ? selectedMatrixTimeframes : defaultMatrixTimeframes;
  const selectableQuickMatrixSymbols = useMemo(
    () => quickMatrixSymbols.filter((symbol) => !matrixSymbols.includes(symbol)),
    [quickMatrixSymbols, matrixSymbols],
  );

  const visibleActiveSignals = showAllActiveSignals ? activeSignals : activeSignals.slice(0, MATRIX_ACTIVE_SIGNAL_PREVIEW);
  const visibleLineageRows = showAllLineageRows ? lineageRows : lineageRows.slice(0, MATRIX_LINEAGE_PREVIEW);
  const isMatrixDefaultSymbols =
    matrixSymbols.length === defaultMatrixSymbols.length &&
    defaultMatrixSymbols.every((symbol) => matrixSymbols.includes(symbol));
  const isMatrixDefaultTimeframes =
    matrixTimeframes.length === defaultMatrixTimeframes.length &&
    defaultMatrixTimeframes.every((tf) => matrixTimeframes.includes(tf));
  const isMatrixAllTimeframes = matrixTimeframes.length >= matrixTimeframeOptions.length;

  const selectAllMatrixSymbols = (): void => {
    setMatrixSymbolSelectionTouched(true);
    setSelectedMatrixSymbols(matrixSymbolOptions);
  };

  const resetMatrixSymbols = (): void => {
    setMatrixSymbolSelectionTouched(false);
    setSelectedMatrixSymbols(defaultMatrixSymbols);
  };

  const selectAllMatrixTimeframes = (): void => {
    setMatrixTimeframeSelectionTouched(true);
    setSelectedMatrixTimeframes(matrixTimeframeOptions);
  };

  const resetMatrixTimeframes = (): void => {
    setMatrixTimeframeSelectionTouched(false);
    setSelectedMatrixTimeframes(defaultMatrixTimeframes);
  };

  const toggleMatrixSymbol = (symbol: string): void => {
    setMatrixSymbolSelectionTouched(true);
    setSelectedMatrixSymbols((prev) => {
      const active = prev.length ? prev : matrixSymbols;
      if (active.includes(symbol)) {
        const next = active.filter((entry) => entry !== symbol);
        return next.length > 0 ? next : defaultMatrixSymbols;
      }
      return [...active, symbol];
    });
  };

  const toggleMatrixTimeframe = (tf: string): void => {
    setMatrixTimeframeSelectionTouched(true);
    setSelectedMatrixTimeframes((prev) => {
      const active = prev.length ? prev : matrixTimeframes;
      if (active.includes(tf)) {
        const next = active.filter((entry) => entry !== tf);
        return next.length > 0 ? next : defaultMatrixTimeframes;
      }
      return [...active, tf];
    });
  };

  const gridTemplate = `minmax(150px, 0.8fr) repeat(${matrixTimeframes.length}, minmax(165px, 1fr))`;

  useEffect(() => {
    const missingPairs = matrixSymbols.flatMap((symbol) => (
      matrixTimeframes.map((timeframe) => ({ symbol, timeframe, key: `${symbol}::${timeframe}` }))
    )).filter(({ key }) => rowNeedsContractFallback(rowMap.get(key)));
    if (!missingPairs.length) return;
    let cancelled = false;
    void Promise.all(
      missingPairs.map(async ({ symbol, timeframe, key }) => {
        const response = await getV2Signals(symbol, timeframe);
        return [key, matrixEntryFromSignal(symbol, timeframe, response.data)] as const;
      }),
    ).then((entries) => {
      if (cancelled) return;
      setMatrixContractEntries((prev) => {
        const next = { ...prev };
        for (const [key, entry] of entries) {
          if (entry) next[key] = entry;
        }
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [matrixSymbols.join('|'), matrixTimeframes.join('|'), rows]);

  if (error) {
    return (
      <Panel
        id={`realtime-signal-visibility-${safeId}`}
        title={showDiagnostics ? 'Realtime Signal Visibility' : 'Signal Feed Visibility'}
        right={<span className="chip solid-block">{showDiagnostics ? 'PAYLOAD ERROR' : 'SOURCE ERROR'}</span>}
      >
        <p className="cockpit-evidence-gap">
          {showDiagnostics
            ? `missing signal source (${error})`
            : 'Signal feed is unavailable after checking the current signal contracts. Trader-facing evidence remains withheld until the source responds.'}
        </p>
      </Panel>
    );
  }

  return (
    <section className="realtime-signal-visibility" data-testid={`realtime-signal-visibility-${safeId}`}>
      <Panel
        id={`realtime-signal-summary-${safeId}`}
        title={showDiagnostics ? 'Realtime Signal Visibility' : 'Signal Feed Visibility'}
        right={
          <>
            {showDiagnostics
              ? chip(data?.prediction_contract?.status ?? 'loading')
              : <span className={`chip solid-${statusTone(data?.prediction_contract?.status)}`}>{readableTitle(data?.prediction_contract?.status, 'Signal feed pending')}</span>}
            <span className={`chip solid-${ageClass(ageSeconds, 120)}`}>{fmtAge(ageSeconds)}</span>
          </>
        }
      >
        <div className="cockpit-analytics-grid">
          <Metric label="Live trading" value={liveGateRuntime?.live_order_submit_allowed === true && liveGateRuntime?.live_blocked !== true ? 'Live trading active' : 'Live platform guarded'} />
          {showDiagnostics ? <Metric label="Live symbols" value={currentLiveSymbols.length ? currentLiveSymbols.join(', ') : 'none'} /> : null}
          {showDiagnostics ? <Metric label="Execution symbols" value={currentExecutionSymbols.length ? currentExecutionSymbols.join(', ') : 'none'} /> : null}
          <Metric label="Symbols" value={data?.summary?.symbols_count ?? 'unpublished'} />
          <Metric label="Timeframes" value={timeframes.join(', ')} />
          <Metric label="Present predictions" value={data?.summary?.present_prediction_count ?? 'unpublished'} />
          <Metric label="Missing predictions" value={data?.summary?.missing_prediction_count ?? 'unpublished'} />
          <Metric label="Active signals" value={data?.summary?.active_signal_count ?? 'unpublished'} />
          <Metric label="Price targets" value={readableTitle(data?.price_target_generation?.status ?? data?.price_target_generation?.validation_status, 'unpublished')} />
          <Metric label="Signal readiness" value={readableTitle(data?.signal_lineage?.status, 'unpublished')} />
          <Metric label="Updated" value={data?.generated_est ?? 'unpublished'} />
          <Metric label={showDiagnostics ? 'Signal source' : 'Signal feed'} value={showDiagnostics ? 'Realtime signal source' : 'Current execution signal contracts'} />
        </div>
        {activeSignals.length > 0 ? (
          <div style={{ marginTop: '1rem', display: 'grid', gridTemplateColumns: '1fr 260px', gap: 16, alignItems: 'center' }}>
            <div>
              <p style={{ margin: '0 0 10px', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                Active decision balance for the last published signals.
              </p>
              <div className="cockpit-lineage-grid">
                {decisionChartData.map((bucket) => (
                  <div key={bucket.key}>
                    <span>{bucket.label}</span>
                    <strong>{bucket.count.toLocaleString('en-US')}</strong>
                    <small>{activeDecisionCount ? `${((bucket.count / activeDecisionCount) * 100).toFixed(0)}% of active set` : '—'}</small>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ height: 180, width: '100%', border: '1px solid var(--line-soft)', borderRadius: 10, padding: 8, background: 'rgba(255,255,255,0.02)' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={decisionChartData.filter((item) => item.count > 0)}
                    dataKey="count"
                    nameKey="label"
                    cx="50%"
                    cy="50%"
                    outerRadius={70}
                    innerRadius={34}
                    paddingAngle={1}
                  >
                    {decisionChartData.map((bucket) => (
                      <Cell key={bucket.key} fill={bucket.color} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => Number(value).toLocaleString('en-US')} />
                </PieChart>
              </ResponsiveContainer>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', margin: '4px 0 0', textAlign: 'center' }}>
                Decision mix from active signal queue.
              </p>
            </div>
          </div>
        ) : null}
        </Panel>

      <Panel
        id={`realtime-active-signals-${safeId}`}
        title={showDiagnostics ? 'Active Signal / Price Target / Lineage' : 'Active Signals And Price Targets'}
        right={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className={liveGateRuntime?.live_order_submit_allowed === true && liveGateRuntime?.live_blocked !== true ? 'chip solid-live' : 'chip solid-paper'}>
              {showDiagnostics ? (liveGateRuntime?.live_blocked === true ? (liveGateRuntime?.live_blocker ?? 'GUARDED') : valueText(currentLiveGate)) : 'Live platform guarded'}
            </span>
            {showDiagnostics ? (
              <button
                className="lineage-raw-toggle"
                type="button"
                onClick={() => setShowAdvancedIds((value) => !value)}
              >
                {showAdvancedIds ? 'Hide technical lineages' : 'Show technical lineages'}
              </button>
            ) : null}
          </div>
        }
      >
        <p className="cockpit-evidence-note" style={{ marginTop: 0 }}>
          Showing {visibleActiveSignals.length} of {mergedRawActiveSignals.length} active signal rows with trader-readable status.
          {withheldActiveSignalCount > 0 && !showDiagnostics
            ? ` ${withheldActiveSignalCount} account-specific signal row${withheldActiveSignalCount === 1 ? '' : 's'} withheld for this trader scope.`
            : ''}
        </p>
        {activeSignals.length > 0 ? (
          <div className="trainer-prediction-scroll-window" role="region" aria-label="Scrollable active realtime signals">
            <div className="realtime-signal-table" role="table" aria-label="Active realtime signals">
              <div className="realtime-signal-row realtime-signal-row--head" role="row">
                <span>Signal</span><span>Decision</span><span>Trade setup</span><span>Confidence</span><span>Risk</span><span>Routing</span><span>Execution</span><span>Readiness</span><span>Block reason</span><span>Updated</span>
              </div>
              {visibleActiveSignals.map((signal) => (
                <div className="realtime-signal-row" role="row" key={`${present(signal.symbol)}-${present(signal.timeframe)}-${present(signal.action)}`}>
                  <span>
                    {shortSymbol(present(signal.symbol))} {present(signal.timeframe)}
                  </span>
                  <span>
                    <span className={`status-${tradeActionTone(signal.action)}`}>
                      {compactAction(signal.action)}
                    </span>
                  </span>
                  <span>{formatTargetTargetLabel(signal)}</span>
                  <span>{confidenceText(signal.confidence)}</span>
                  <span>
                    <GateCell
                      state={signal.risk_status_label ?? signal.risk_state}
                      fallback="Risk decision pending"
                      reason={statusSentence(signal.blocked_reason, 'Awaiting risk decision details.')}
                    />
                  </span>
                  <span>
                    <GateCell
                      state={signal.orchestrator_status_label ?? signal.orchestrator_state}
                      fallback="Routing decision pending"
                      reason={statusSentence(signal.blocked_reason, 'Awaiting routing details.')}
                    />
                  </span>
                  <span>
                    <GateCell
                      state={signal.paper_status_label ?? signal.paper_state ?? signal.paper_fill_status}
                      fallback="Execution gate pending"
                      reason={statusSentence(signal.blocked_reason, 'Awaiting execution gate details.')}
                    />
                  </span>
                  <span>
                    <strong>{activeSignalStatusLine(signal)}</strong>
                    <small>{chainReadinessPlainText(signal)}</small>
                    {showDiagnostics && showAdvancedIds ? (
                      <small>{activeSignalLineageTrail(signal, true)}</small>
                    ) : showDiagnostics ? (
                      <small>{activeSignalLineageTrail(signal, false)}</small>
                    ) : null}
                  </span>
                  <span>{showDiagnostics ? compact(signal.blocked_reason ?? signal.reason, 'No blocker', 72) : compact(readableStatus(signal.blocked_reason ?? signal.reason, 'No blocker'), 'No blocker', 72)}</span>
                  <span>{present(signal.generated_est)}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="cockpit-evidence-gap">Active signal rows are not published by the explainer yet; checking Redis-backed execution signal contracts for the selected symbol/timeframe grid.</p>
        )}
        {activeSignals.length > MATRIX_ACTIVE_SIGNAL_PREVIEW ? (
          <button
            className="lineage-raw-toggle"
            onClick={() => setShowAllActiveSignals((value) => !value)}
            style={{ marginTop: 8 }}
          >
            {showAllActiveSignals ? 'Show fewer active signals' : `Show all ${activeSignals.length} active signals`}
          </button>
        ) : null}
      </Panel>

      <Panel id={`realtime-tf-matrix-${safeId}`} title="Signal Forecast Grid" right={<span className="chip">{symbols.length} symbols</span>}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          <button
            type="button"
            className="lineage-raw-toggle"
            onClick={selectAllMatrixSymbols}
            disabled={selectedMatrixSymbols.length >= matrixSymbolOptions.length}
          >
            Select all symbols
          </button>
          <button
            type="button"
            className="lineage-raw-toggle"
            onClick={resetMatrixSymbols}
            disabled={isMatrixDefaultSymbols}
          >
            Reset defaults
          </button>
          <button
            type="button"
            className="lineage-raw-toggle"
            onClick={selectAllMatrixTimeframes}
            disabled={isMatrixAllTimeframes}
          >
            Select all timeframes
          </button>
          <button
            type="button"
            className="lineage-raw-toggle"
            onClick={resetMatrixTimeframes}
            disabled={isMatrixDefaultTimeframes}
          >
            Core timeframe focus
          </button>
        </div>
        <div className="prediction-matrix-controls">
          <div className="tf-picker">
            {matrixTimeframeOptions.map((tf) => (
              <button
                key={tf}
                type="button"
                className={`tf-picker__btn${matrixTimeframes.includes(tf) ? ' tf-picker__btn--active' : ''}`}
                onClick={() => toggleMatrixTimeframe(tf)}
              >
                {tf}
              </button>
            ))}
          </div>
          <div className="cockpit-evidence-note" style={{ margin: 0 }}>
            {isMatrixDefaultSymbols
              ? `Default market focus: ${matrixSymbols.length.toLocaleString('en-US')} symbols.`
              : `Filtered trainer symbol universe: ${matrixSymbols.length.toLocaleString('en-US')} selected of ${matrixSymbolOptions.length.toLocaleString('en-US')}.`}
          </div>
          <div className="symbol-picker">
            {selectableQuickMatrixSymbols.map((sym) => (
              <span
                key={sym}
                className={`symbol-chip${matrixSymbols.includes(sym) ? ' symbol-chip--active' : ''}`}
                onClick={() => toggleMatrixSymbol(sym)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && toggleMatrixSymbol(sym)}
              >
                {shortSymbol(sym)}
              </span>
            ))}
            {extendedMatrixSymbols.length > 0 ? (
              <span
                className="symbol-chip symbol-chip--more"
                onClick={() => setShowAllMatrixSymbols((value) => !value)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && setShowAllMatrixSymbols((value) => !value)}
              >
                {showAllMatrixSymbols ? '− Less' : '+ More symbols'}
              </span>
            ) : null}
          </div>
          {showAllMatrixSymbols && extendedMatrixSymbols.length > 0 ? (
            <div className="symbol-picker-extended">
              {extendedMatrixSymbols.map((sym) => (
                <span
                  key={sym}
                  className={`symbol-chip${matrixSymbols.includes(sym) ? ' symbol-chip--active' : ''}`}
                  onClick={() => toggleMatrixSymbol(sym)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && toggleMatrixSymbol(sym)}
                >
                  {shortSymbol(sym)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <p className="cockpit-evidence-note">
          Showing {matrixSymbols.length.toLocaleString('en-US')} selected symbols across {matrixTimeframes.length} selected timeframes.
          5m is the default focus window. Use the controls above to add or remove symbols and timeframes.
        </p>
        <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--matrix" role="region" aria-label="Scrollable all timeframe prediction matrix">
          <div className="realtime-tf-matrix" role="table" aria-label="Signal forecast grid">
            <div
              className="realtime-tf-matrix__row realtime-tf-matrix__row--head"
              role="row"
              style={{ gridTemplateColumns: gridTemplate }}
            >
              <span>Symbol</span>
              {matrixTimeframes.map((tf) => <span key={tf}>{tf}</span>)}
            </div>
            {matrixSymbols.map((symbol) => (
              <div
                className="realtime-tf-matrix__row"
                role="row"
                key={symbol}
                style={{ gridTemplateColumns: gridTemplate }}
              >
                <button
                  aria-label={`Remove ${shortSymbol(symbol)} from selected symbols`}
                  className="realtime-tf-symbol"
                  onClick={() => toggleMatrixSymbol(symbol)}
                  type="button"
                >
                  {shortSymbol(symbol)}
                </button>
                {matrixTimeframes.map((tf) => (
                  <span key={`${symbol}-${tf}`}>
                    {tfLabel(rowMap.get(`${symbol}::${tf}`), lookupAccuracyCell(accuracyStatus, symbol, tf))}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </Panel>

      {showDiagnostics ? (
      <Panel id={`realtime-lineage-${safeId}`} title="Risk / Orchestrator / Paper Lineage">
        {lineageRows.length > 0 ? (
          <>
            <p className="cockpit-evidence-note" style={{ marginTop: 0 }}>
              Showing {visibleLineageRows.length} of {lineageRows.length} rows to keep this panel scannable.
            </p>
            <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--compact" role="region" aria-label="Scrollable lineage summary">
              <div className="cockpit-lineage-grid">
                {visibleLineageRows.map((row) => {
                  const trainer = row.trainer_prediction_exists;
                  const risk = row.risk_decision_exists;
                  const orchestrator = row.orchestrator_decision_exists;
                  const intent = row.paper_intent_exists;
                  const ledger = row.paper_ledger_exists;
                  const chainOk = !!trainer && !!risk && !!orchestrator && !!intent && !!ledger;
                  return (
                    <div key={`${present(row.symbol)}-${present(row.timeframe)}`}>
                      <span>Symbol / TF</span>
                      <strong>{present(row.symbol)} {present(row.timeframe)}</strong>
                      <span>Chain readiness</span>
                      <strong>{chainReadiness(row)}</strong>
                      <span>Risk / Orchestrator / Execution / Ledger</span>
                      <strong className={chainOk ? 'status-ok' : 'status-warn'}>
                        {`Training ${boolStatus(trainer)} · Risk ${boolStatus(risk)} · Orchestrator ${boolStatus(orchestrator)} · Execution ${boolStatus(intent)} · Ledger ${boolStatus(ledger)}`}
                      </strong>
                      <span>Primary blocker</span>
                      <strong>{row.exact_blocker ? compact(row.exact_blocker, 'none') : 'none'}</strong>
                    </div>
                  );
                })}
              </div>
            </div>
            {lineageRows.length > MATRIX_LINEAGE_PREVIEW ? (
              <button
                className="lineage-raw-toggle"
                onClick={() => setShowAllLineageRows((value) => !value)}
                style={{ marginTop: 8 }}
              >
                {showAllLineageRows ? 'Show fewer lineage rows' : `Show all ${lineageRows.length} lineage rows`}
              </button>
            ) : null}
          </>
        ) : (
          <p className="cockpit-evidence-gap">Signal lineage rows are unpublished in the current signal source.</p>
        )}
      </Panel>
      ) : null}

      {showDiagnostics ? (
      <Panel id={`realtime-source-inventory-${safeId}`} title="Runtime Source Inventory" right={<span className="chip solid-warn">{data?.runtime_source_inventory?.missing_or_stale_count ?? 0} gaps</span>}>
        <div className="realtime-source-table" role="table" aria-label="Runtime source inventory">
          <div className="realtime-source-row realtime-source-row--head" role="row">
            <span>Surface</span><span>Source key</span><span>Publisher</span><span>Endpoint</span><span>Freshness</span><span>Coverage</span><span>Status</span>
          </div>
          {surfaces.map((surface) => (
            <div className="realtime-source-row" role="row" key={surface.surface_id}>
              <span>{surface.surface_id}</span>
              <span><code>{surface.source_redis_key}</code></span>
              <span>{surface.publisher_process_service}</span>
              <span>{surface.payload_path ? 'configured endpoint' : 'missing endpoint'}</span>
              <span>{surface.freshness_seconds == null ? 'unpublished' : fmtAge(surface.freshness_seconds)}</span>
              <span>{(surface.symbols_covered?.length ?? 0).toLocaleString('en-US')} symbols / {(surface.timeframes_covered ?? []).join(', ') || 'unpublished'}</span>
              <span>{surface.missing_stale_reason ? chip(surface.missing_stale_reason) : chip('PRESENT_CURRENT', 'CURRENT')}</span>
            </div>
          ))}
        </div>
      </Panel>
      ) : null}

      {showDiagnostics ? (
      <Panel id={`realtime-deployment-${safeId}`} title="Deployment Truth" right={chip(data?.website_deployment_truth?.status ?? 'unpublished')}>
        <div className="cockpit-analytics-grid">
          <Metric label="Production" value={data?.website_deployment_truth?.production_base_url ?? 'missing endpoint'} />
          <Metric label="Local bundle" value={compact(data?.website_deployment_truth?.local_dev_server_bundle_hash, 'Data source unavailable', 20)} />
          <Metric label="Public source hash" value={compact(data?.website_deployment_truth?.public_payload_hash, 'Data source unavailable', 20)} />
          <Metric label="Claim scope" value={data?.website_deployment_truth?.claim_scope ?? 'local-only until production route updated'} />
        </div>
        <div className="realtime-deploy-grid">
          {deploymentRows.map((row) => (
            <div key={row.route} className="cockpit-evidence-gap">
              <strong>{row.route}</strong>
              <p>{row.error ? `Deployment stale or unverified: ${row.error}` : `HTTP ${row.http_status ?? 'pending'} / ${compact(row.content_hash, 'Data source unavailable', 18)}`}</p>
            </div>
          ))}
        </div>
        <p className="cockpit-evidence-note">{data?.website_deployment_truth?.deploy_build_command_path ?? 'deployment command unpublished in current source'}</p>
      </Panel>
      ) : null}

      {showDiagnostics ? (
      <Panel id={`realtime-disabled-controls-${safeId}`} title="Disabled Live / Order Controls" right={<span className="chip solid-block">NO LIVE MUTATION</span>}>
        <div className="cockpit-lineage-grid">
          {[
            ['Live trading enablement', `held by current guard: ${currentLiveGateLabel}; submit requires accepted symbols, lineage, risk, filters, kill switch, and available margin`],
            ['Canary approval', 'disabled: canary approval requires separate human gate and audit contract'],
            ['Exchange order submit/cancel/modify', 'disabled: missing typed backend request/response and audit-ledger authorization'],
            ['Leverage or margin mutation', 'disabled: missing authorization/audit contract'],
            ['Flatten/cancel-all real account', 'disabled: no backend endpoint may affect real account'],
            ['Legacy restart / old Redis mutation', 'disabled: old Redis writes and legacy restarts are unsupported'],
          ].map(([label, reason]) => (
            <div key={label}><span>{label}</span><strong className="status-block">{reason}</strong></div>
          ))}
        </div>
        {implementationTasks.length > 0 ? (
          <div className="realtime-task-strip">
            {implementationTasks.slice(0, 8).map((task) => <span className="chip solid-warn" key={task}>{task}</span>)}
            {implementationTasks.length > 8 ? <span className="chip">+{implementationTasks.length - 8} more missing TF tasks</span> : null}
          </div>
        ) : null}
      </Panel>
      ) : null}
    </section>
  );
}
