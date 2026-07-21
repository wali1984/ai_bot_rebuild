import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatAge, formatPercent } from '../../lib/tradeFormatters';

interface PipelineStatus {
  live_gate?: string;
  trader_execution_enabled?: boolean;
  allowed_run_types?: string[];
  symbols?: string[];
  live_gate_runtime_source?: string;
}

interface TrainerSummary {
  state?: string;
  win_rate_30d?: number | null;
  episodes_total?: number | null;
  drift_alarm_count?: number | null;
  checkpoint_id?: string | null;
  uptime_days?: number | null;
}

interface LiveGateStatus {
  go_no_go?: string;
  verdict?: string;
  live_gate?: string;
  backend_live_enable_callable?: boolean;
  source_reconciliation?: { current_go_no_go?: string };
}

function pill(tone: 'ok' | 'warn' | 'block' | 'neutral', label: string, value: string, detail?: string) {
  const colors: Record<string, string> = {
    ok: 'var(--buy)',
    warn: 'var(--gold, #f59e0b)',
    block: 'var(--sell)',
    neutral: 'var(--text-secondary)',
  };
  const bgs: Record<string, string> = {
    ok: 'color-mix(in oklch, var(--buy) 12%, var(--bg-elevated))',
    warn: 'color-mix(in oklch, var(--gold, #f59e0b) 12%, var(--bg-elevated))',
    block: 'color-mix(in oklch, var(--sell) 12%, var(--bg-elevated))',
    neutral: 'var(--bg-elevated)',
  };
  return (
    <div
      key={label}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 3,
        padding: '8px 14px',
        background: bgs[tone],
        border: `1px solid color-mix(in oklch, ${colors[tone]} 35%, var(--line-soft))`,
        borderRadius: 8,
        minWidth: 120,
        flex: '1 1 120px',
        minInlineSize: 0,
      }}
    >
      <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: colors[tone], textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 700 }}>
        {label}
      </span>
      <strong style={{ fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'normal', overflow: 'visible', textOverflow: 'clip', overflowWrap: 'anywhere', lineHeight: 1.2 }}>
        {value}
      </strong>
      {detail ? (
        <span style={{ fontSize: 10, color: 'var(--text-muted)', overflow: 'visible', textOverflow: 'clip', whiteSpace: 'normal', overflowWrap: 'anywhere', lineHeight: 1.25 }}>
          {detail}
        </span>
      ) : null}
    </div>
  );
}

function signalTone(side: unknown): 'ok' | 'block' | 'neutral' {
  const s = String(side ?? '').toLowerCase();
  if (s.includes('long') || s.includes('buy')) return 'ok';
  if (s.includes('short') || s.includes('sell')) return 'block';
  return 'neutral';
}

function gateTone(gate: string | undefined): 'ok' | 'warn' | 'block' {
  if (!gate) return 'neutral' as 'warn';
  if (gate === 'open') return 'ok';
  if (gate.includes('blocked')) return 'block';
  return 'warn';
}

function trainerTone(state: string | undefined): 'ok' | 'warn' | 'neutral' {
  if (!state) return 'neutral';
  const s = state.toLowerCase();
  // The trainer publishes states like ACTIVE_REDIS_EVIDENCE / REPLAY_AND_ONLINE_LEARNING /
  // WEIGHTS_UPDATING — all healthy. Match on substrings so a live trainer reads green.
  if (s.includes('error') || s.includes('crash') || s.includes('halt') || s.includes('frozen') || s.includes('stale') || s.includes('missing')) return 'warn';
  if (s.includes('active') || s.includes('running') || s.includes('learning') || s.includes('updating') || s.includes('ok') || s.includes('evidence')) return 'ok';
  return 'neutral';
}

export function TradeIntelligenceBar({ state }: { state: TradeTerminalState }): JSX.Element {
  const { envelope: pipelineEnv } = useRealtimeResource<PipelineStatus>({
    url: '/api/v2/pipeline/status',
    source: 'pipeline_service',
    pollIntervalMs: 30_000,
  });
  const { envelope: trainerEnv } = useRealtimeResource<TrainerSummary>({
    url: '/api/v2/trainer/summary',
    source: 'trainer_service',
    pollIntervalMs: 60_000,
  });
  const { envelope: riskEnv } = useRealtimeResource<LiveGateStatus>({
    url: '/api/v1/live-gate/status',
    source: 'live_gate_service',
    pollIntervalMs: 30_000,
  });

  const pipeline = pipelineEnv.data;
  const trainer = trainerEnv.data;
  const risk = riskEnv.data;

  const sig = state.signal;
  const hasSignal = sig.direction !== 'Signal connecting';
  const sigSide = hasSignal ? String(sig.direction).toUpperCase() : '—';
  const sigConf = sig.executableConfidence !== null ? formatPercent(sig.executableConfidence) : '—';
  // Signal-content staleness from the API payload (source_freshness/market_age_seconds):
  // the key may be re-published every cycle while the signal itself is days old.
  const sigStale = hasSignal && String(sig.sourceFreshness ?? '').toUpperCase() === 'STALE';
  const sigAge = sigStale && sig.marketAgeSeconds !== null ? formatAge(sig.marketAgeSeconds) : null;
  const sigDetail = hasSignal
    ? `${state.symbol} · ${sig.confidenceLabel} · selected ${formatPercent(state.signal.selectedConfidence)}${sigStale ? ` · STALE${sigAge ? ` · ${sigAge}` : ''}` : ''}`
    : 'No active signal';

  const gateLabel = pipeline?.live_gate ?? risk?.live_gate ?? '—';
  const gateDisplay = gateLabel.replace(/_/g, ' ').toUpperCase();

  const symbolCount = pipeline?.symbols?.length ?? 0;
  const runTypes = (pipeline?.allowed_run_types ?? []).join(' · ') || '—';

  const trainerState = trainer?.state ?? '—';
  const trainerWR = trainer?.win_rate_30d != null ? formatPercent(trainer.win_rate_30d) : '—';
  const trainerDetail = trainer?.checkpoint_id ? `ckpt ${trainer.checkpoint_id.slice(-8)}` : 'No checkpoint';

  const execEnabled = pipeline?.trader_execution_enabled === true;

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8,
        padding: '10px 0',
      }}
      aria-label="Intelligence status bar"
    >
      {pill(
        sigStale ? 'warn' : hasSignal ? signalTone(sig.direction) : 'neutral',
        sigStale ? 'AI Signal · Stale' : 'AI Signal',
        hasSignal ? `${sigSide} · ${sigConf}${sigStale && sigAge ? ` · ${sigAge}` : ''}` : 'No Signal',
        sigDetail,
      )}
      {pill(
        gateTone(pipeline?.live_gate ?? risk?.live_gate),
        'Execution Guard',
        gateDisplay,
        risk?.verdict ? risk.verdict.replace(/_/g, ' ').slice(0, 38) : 'Risk gate status',
      )}
      {pill(
        execEnabled ? 'ok' : 'block',
        'Execution',
        execEnabled ? 'ENABLED' : 'DISABLED',
        `${symbolCount} symbols monitored`,
      )}
      {pill(
        trainerTone(trainer?.state),
        'Trainer',
        trainerState.toUpperCase(),
        `WR ${trainerWR} · ${trainerDetail}`,
      )}
      {pill(
        'neutral',
        'Pipeline Modes',
        runTypes.split(' · ').length > 2 ? `${runTypes.split(' · ').slice(0, 2).join(' · ')}…` : runTypes,
        `${symbolCount} symbols in scope`,
      )}
    </div>
  );
}
