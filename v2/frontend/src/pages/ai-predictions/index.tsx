import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  publicRuntimeId,
  runtimeAgeSeconds,
  runtimeNumber,
  runtimeRecord,
  runtimeText,
  type CurrentRuntimeLineagePayload,
  useCurrentRuntimeLineage,
} from '../../data/currentRuntimeLineage';
import {
  accuracyCell as lookupAccuracyCell,
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  type SignalPredictionAccuracyCell,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types ─────────────────────────────────────────────────────────────────

interface PredRow {
  symbol: string;
  timeframe: string;
  action: string | null;
  confidence_calibrated: number | null;
  confidence_raw: number | null;
  data_coverage_percent: number | null;
  market_state_integrity_score: number | null;
  missing_feature_count: number | null;
  top_action: string | null;
  top_prob: number | null;
  second_action: string | null;
  second_prob: number | null;
  cuda_available: boolean | null;
  checkpoint_id: string | null;
  generated_at: string | null;
  age_seconds: number | null;
  action_probs: Record<string, number> | null;
  masa_signal: number | null;
  policy_value: number | null;
  temperature: number | null;
  coverage_factor: number | null;
  price_target: number | null;
  expected_move_bps: number | null;
}

interface PredMatrixData {
  rows: PredRow[];
  count: number;
  symbols: string[];
  symbol_count: number;
  timeframes: string[];
  missing: string[];
}

interface ExplainData {
  symbol: string;
  timeframe: string;
  generated_at: string | null;
  explanation: {
    summary: string;
    signal_strength: string;
    confidence_narrative: string;
    data_quality_narrative: string;
    market_integrity_narrative: string;
    technical_drivers: string;
    price_target_narrative: string;
    risk_gate_narrative: string;
    pipeline_state_narrative: string;
    full_text: string;
  };
  key_numbers: {
    action: string;
    confidence_calibrated: number;
    confidence_raw: number;
    dominant_prob: number;
    expected_move_bps: number;
    price_target: number | null;
    data_coverage_pct: number;
    integrity_score: number;
    masa_signal: number | null;
    policy_value: number | null;
    missing_feature_count: number;
  };
}

interface TrainerSummary {
  state: string;
  checkpoint_id?: string | null;
  uptime_days?: number | null;
  win_rate_30d?: number | null;
  episodes_total?: number | null;
  drift_watch_count?: number | null;
  drift_alarm_count?: number | null;
}

// ─── Constants ─────────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'] as const;
type TF = typeof TIMEFRAMES[number];
const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT', 'ADAUSDT'];
// BTC/ETH/SOL are always pinned; additional symbols come from liquidation volume ranking
const PINNED_CORE = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'] as const;
const ACTION_COLORS: Record<string, string> = {
  long: '#26c281', long_strong: '#0fa86a', long_scaled: '#4ade80',
  short: '#ef5350', short_strong: '#d32f2f', short_scaled: '#ff7875',
  close_long: '#f59e0b', close_short: '#f59e0b', reduce: '#f59e0b',
  hold: '#f59e0b', hedge_reserved_fail_closed: 'var(--text-muted)',
};

// ─── Helpers ──────────────────────────────────────────────────────────────

function actionColor(a: string | null | undefined): string {
  if (!a) return 'var(--text-muted)';
  const key = a.toLowerCase();
  if (key.includes('short')) return ACTION_COLORS.short;
  if (key.includes('long_strong')) return ACTION_COLORS.long_strong;
  if (key.includes('long_scaled')) return ACTION_COLORS.long_scaled;
  if (key.includes('long')) return ACTION_COLORS.long;
  if (key.includes('hold')) return ACTION_COLORS.hold;
  if (key.includes('close') || key.includes('reduce')) return ACTION_COLORS.close_long;
  return ACTION_COLORS[key] ?? 'var(--text-muted)';
}
function confColor(c: number | null | undefined): string {
  if (c == null) return 'var(--text-muted)';
  const v = Math.abs(c) <= 1 ? c : c / 100;
  if (v >= 0.75) return '#26c281';
  if (v >= 0.55) return '#f59e0b';
  return '#ef5350';
}
function fmtConf(c: number | null | undefined): string {
  if (c == null) return '—';
  const v = Math.abs(c) <= 1 ? c * 100 : c;
  return `${v.toFixed(1)}%`;
}
function fmtAge(s: number | null | undefined): string {
  if (s == null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
function fmtPrice(p: number | null | undefined): string {
  if (p == null) return '—';
  return `$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function predictionRowFromLineage(payload: CurrentRuntimeLineagePayload | null | undefined): PredRow | null {
  if (!payload) return null;
  const trainer = runtimeRecord(payload.trainer_prediction);
  const signal = runtimeRecord(payload.signal);
  const risk = runtimeRecord(payload.risk_decision);
  const rawOutput = runtimeRecord(trainer.raw_output);
  const drivers = runtimeRecord(trainer.reasoning_drivers);
  const generatedAt = runtimeText(trainer.generated_at, signal.generated_at, risk.generated_at, payload.generated_at);
  const symbol = runtimeText(trainer.symbol, signal.symbol);
  if (!symbol) return null;
  const topAction = runtimeText(rawOutput.side, signal.side, trainer.direction);
  const topProb = runtimeNumber(trainer.confidence_raw, drivers.confidence_raw);
  return {
    symbol,
    timeframe: runtimeText(trainer.timeframe) ?? '1m',
    action: runtimeText(rawOutput.side, signal.side, trainer.direction),
    confidence_calibrated: runtimeNumber(trainer.confidence_calibrated, signal.confidence_calibrated, drivers.confidence_calibrated),
    confidence_raw: topProb,
    data_coverage_percent: runtimeNumber(trainer.data_coverage_pct, drivers.data_coverage_pct),
    market_state_integrity_score: runtimeNumber(drivers.market_state_integrity_score),
    missing_feature_count: runtimeNumber(drivers.missing_feature_count),
    top_action: topAction,
    top_prob: topProb,
    second_action: null,
    second_prob: null,
    cuda_available: null,
    checkpoint_id: runtimeText(trainer.model_checkpoint, trainer.model_version),
    generated_at: generatedAt,
    age_seconds: runtimeNumber(trainer.market_age_seconds, signal.market_age_seconds, runtimeAgeSeconds(generatedAt)),
    action_probs: null,
    masa_signal: runtimeNumber(drivers.masa_signal),
    policy_value: runtimeNumber(drivers.policy_value),
    temperature: null,
    coverage_factor: null,
    price_target: null,
    expected_move_bps: runtimeNumber(risk.expected_move_after_cost_bps, risk.expected_move_bps, trainer.expected_move_bps),
  };
}

function AccuracyBadge({ cell }: { cell: SignalPredictionAccuracyCell | null }): JSX.Element {
  if (!cell || !cell.evaluated_count) {
    return (
      <div style={{ fontFamily: 'var(--font-mono)' }}>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)' }}>—</span>
        <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)' }}>no outcomes</span>
      </div>
    );
  }
  return (
    <div style={{ fontFamily: 'var(--font-mono)' }}>
      <span style={{ display: 'block', fontSize: 12, fontWeight: 800, color: adaptiveStatusColor(cell.status) }}>
        {formatAdaptivePercent(cell.accuracy)}
      </span>
      <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)' }}>
        {cell.correct_count ?? 0}/{cell.evaluated_count} hits
      </span>
      <span style={{ display: 'block', fontSize: 9, color: (cell.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
        {formatAdaptiveMoney(cell.realized_pnl_usd)} pnl
      </span>
    </div>
  );
}

// ─── Prob bars ────────────────────────────────────────────────────────────

function ProbBar({ label, prob, maxProb = 1 }: { label: string; prob: number; maxProb?: number }): JSX.Element {
  const color = actionColor(label);
  const pct = (prob / Math.max(maxProb, 0.01)) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <div style={{ minWidth: 130, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label.replace(/_/g, ' ')}</div>
      <div style={{ flex: 1, height: 10, background: 'rgba(255,255,255,0.05)', borderRadius: 5, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 5 }} />
      </div>
      <div style={{ minWidth: 46, textAlign: 'right', fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700, color }}>{(prob * 100).toFixed(2)}%</div>
    </div>
  );
}

// ─── Calibration gauge ────────────────────────────────────────────────────

function CalibGauge({ raw, calibrated, temperature, coverageFactor }: { raw: number | null; calibrated: number | null; temperature: number | null; coverageFactor: number | null }): JSX.Element {
  const rawPct = raw != null ? Math.min(100, (Math.abs(raw) <= 1 ? raw : raw / 100) * 100) : 0;
  const calPct = calibrated != null ? Math.min(100, (Math.abs(calibrated) <= 1 ? calibrated : calibrated / 100) * 100) : 0;
  const calColor = confColor(calibrated);
  return (
    <div style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '10px 14px' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Confidence Calibration</div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>Raw</div>
          <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{fmtConf(raw)}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', color: 'var(--text-muted)', fontSize: 14, alignSelf: 'center' }}>→</div>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>Calibrated</div>
          <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: calColor }}>{fmtConf(calibrated)}</div>
        </div>
      </div>
      <div style={{ position: 'relative', height: 14, background: 'rgba(255,255,255,0.05)', borderRadius: 7, overflow: 'hidden', marginBottom: 8 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${rawPct}%`, background: 'rgba(255,255,255,0.15)', borderRadius: 7 }} />
        <div style={{ position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)', height: 6, width: `${calPct}%`, background: calColor, borderRadius: 3 }} />
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {[
          ['Temp', temperature?.toFixed(2) ?? '—'],
          ['Cov. Factor', coverageFactor?.toFixed(3) ?? '—'],
          ['Delta', raw != null && calibrated != null ? `${((calibrated - raw) * 100).toFixed(1)}pp` : '—'],
        ].map(([l, v]) => (
          <div key={l}>
            <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: 4 }}>{l}</span>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── AI Reasoning panel ────────────────────────────────────────────────────

function ReasoningPanel({ symbol, timeframe }: { symbol: string; timeframe: string }): JSX.Element {
  const { envelope, loading } = useRealtimeResource<ExplainData>({
    url: `/api/v2/predictions/explain?symbol=${symbol}&timeframe=${timeframe}`,
    source: 'ai_explain',
    pollIntervalMs: 120_000,
    mode: 'read_only',
  });
  const exp = envelope.data?.explanation;
  const nums = envelope.data?.key_numbers;

  if (loading && !exp) {
    return (
      <div style={{ padding: '14px 18px', background: 'rgba(99,102,241,0.04)', borderRadius: 8, border: '1px solid rgba(99,102,241,0.15)' }}>
        <span style={{ fontSize: 12, color: '#6366f1' }}>Loading AI analysis from live model data…</span>
      </div>
    );
  }
  if (!exp) {
    return (
      <div style={{ padding: '12px 16px', background: 'rgba(0,0,0,0.15)', borderRadius: 8 }}>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>AI reasoning not yet available — backend explain endpoint may need deploying.</p>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {nums && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
          {[
            { label: 'MASA Signal', value: nums.masa_signal?.toFixed(3) ?? '—', color: nums.masa_signal != null ? (nums.masa_signal < -0.5 ? '#ef5350' : nums.masa_signal > 0.5 ? '#26c281' : '#f59e0b') : 'var(--text-muted)', note: 'momentum alignment score' },
            { label: 'Policy Value', value: nums.policy_value?.toFixed(3) ?? '—', color: nums.policy_value != null ? (nums.policy_value < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)', note: 'RL policy head output' },
            { label: 'Dominant Prob', value: `${(nums.dominant_prob * 100).toFixed(1)}%`, color: nums.dominant_prob > 0.9 ? '#26c281' : '#f59e0b', note: 'top action certainty' },
            { label: 'Missing Features', value: String(nums.missing_feature_count), color: nums.missing_feature_count > 30 ? '#ef5350' : nums.missing_feature_count > 15 ? '#f59e0b' : '#26c281', note: 'imputed via backfill' },
          ].map(kpi => (
            <div key={kpi.label} style={{ minWidth: 100 }}>
              <div style={{ fontSize: 14, fontWeight: 800, fontFamily: 'var(--font-mono)', color: kpi.color }}>{kpi.value}</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{kpi.label}</div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', fontStyle: 'italic' }}>{kpi.note}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10 }}>
        {[
          { icon: '📊', title: 'What the model sees', text: exp.summary },
          { icon: '💪', title: 'Why this signal strength', text: exp.signal_strength },
          { icon: '🎯', title: 'How confidence was calibrated', text: exp.confidence_narrative },
          { icon: '📉', title: 'Data quality impact', text: exp.data_quality_narrative },
          { icon: '🏗️', title: 'Market state integrity', text: exp.market_integrity_narrative },
          { icon: '⚡', title: 'What drove the prediction', text: exp.technical_drivers },
          { icon: '💰', title: 'Why this price target', text: exp.price_target_narrative },
        ].filter(s => s.text).map(section => (
          <div key={section.title} style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.025)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>{section.icon} {section.title}</div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{section.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Expanded row ─────────────────────────────────────────────────────────

function PredExpandedRow({ row }: { row: PredRow }): JSX.Element {
  const [tab, setTab] = useState<'probs' | 'calibration' | 'reasoning'>('probs');
  const probs = row.action_probs ?? {};
  const maxProb = Math.max(...Object.values(probs), 0.01);
  return (
    <tr>
      <td colSpan={11} style={{ padding: 0 }}>
        <div style={{ background: 'rgba(10,10,18,0.95)', borderBottom: '2px solid var(--border)', padding: '16px 20px' }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: 12 }}>
            {([['probs', '📊 Action Probs'], ['calibration', '🎯 Calibration'], ['reasoning', '🧠 AI Reasoning']] as const).map(([t, label]) => (
              <button key={t} onClick={() => setTab(t)} style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: tab === t ? 700 : 400, cursor: 'pointer',
                border: `1px solid ${tab === t ? '#6366f1' : 'rgba(255,255,255,0.1)'}`,
                background: tab === t ? 'rgba(99,102,241,0.12)' : 'transparent',
                color: tab === t ? '#6366f1' : 'var(--text-secondary)',
              }}>{label}</button>
            ))}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
              {row.checkpoint_id && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>ckpt: {publicRuntimeId(row.checkpoint_id)?.slice(0, 16)}…</span>}
              {row.cuda_available != null && <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, border: `1px solid ${row.cuda_available ? '#26c28140' : 'var(--border)'}`, color: row.cuda_available ? '#26c281' : 'var(--text-muted)' }}>{row.cuda_available ? '⚡ CUDA' : '🖥 CPU'}</span>}
            </div>
          </div>
          {tab === 'probs' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 20 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>All Action Probabilities (raw softmax output)</div>
                {Object.keys(probs).length > 0
                  ? Object.entries(probs)
                      .sort((a, b) => b[1] - a[1])
                      .map(([action, prob]) => <ProbBar key={action} label={action} prob={prob} maxProb={maxProb} />)
                  : <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>Probability stream connecting</p>
                }
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Signal Metadata</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {([
                    ['MASA Signal', row.masa_signal?.toFixed(4) ?? '—', row.masa_signal != null ? (row.masa_signal < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)'],
                    ['Policy Value', row.policy_value?.toFixed(4) ?? '—', row.policy_value != null ? (row.policy_value < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)'],
                    ['Coverage', row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(1)}%` : '—', (row.data_coverage_percent ?? 0) >= 80 ? '#26c281' : '#f59e0b'],
                    ['Missing Feats', row.missing_feature_count != null ? `${row.missing_feature_count}` : '—', (row.missing_feature_count ?? 0) > 20 ? '#f59e0b' : '#26c281'],
                    ['Price Target', fmtPrice(row.price_target), actionColor(row.action)],
                    ['Expected Move', row.expected_move_bps != null ? `${(row.expected_move_bps / 100).toFixed(2)}%` : '—', actionColor(row.action)],
                    ['Integrity', row.market_state_integrity_score != null ? `${row.market_state_integrity_score.toFixed(0)}/100` : '—', (row.market_state_integrity_score ?? 0) >= 90 ? '#26c281' : '#f59e0b'],
                    ['Generated', row.generated_at ? new Date(row.generated_at).toLocaleString() : '—', 'var(--text-muted)'],
                  ] as const).map(([l, v, color]) => (
                    <div key={String(l)} style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6 }}>
                      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>{l}</div>
                      <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: String(color) }}>{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          {tab === 'calibration' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
              <CalibGauge raw={row.confidence_raw} calibrated={row.confidence_calibrated} temperature={row.temperature} coverageFactor={row.coverage_factor} />
              <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>What this means</div>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.65 }}>
                  Raw confidence ({fmtConf(row.confidence_raw)}) is the model's softmax output directly.
                  Temperature {row.temperature?.toFixed(2) ?? '?'} smooths overconfident predictions — values &gt; 1.0 reduce confidence.
                  Coverage factor ({row.coverage_factor?.toFixed(3) ?? '?'}) penalizes {row.missing_feature_count ?? '?'} imputed features.
                  Final calibrated confidence: {fmtConf(row.confidence_calibrated)}.
                  {(row.confidence_raw ?? 0) - (row.confidence_calibrated ?? 0) > 0.05
                    ? ' Significant downward calibration — model was overconfident before adjustment.'
                    : ' Calibration was modest — data coverage was adequate.'}
                </p>
              </div>
            </div>
          )}
          {tab === 'reasoning' && <ReasoningPanel symbol={row.symbol} timeframe={row.timeframe} />}
        </div>
      </td>
    </tr>
  );
}

// ─── Trainer card ─────────────────────────────────────────────────────────

function TrainerCard(): JSX.Element {
  const { envelope } = useRealtimeResource<TrainerSummary>({
    url: '/api/v2/trainer/summary',
    source: '/api/v2/trainer/summary',
    pollIntervalMs: 30_000,
    mode: 'read_only',
  });
  const t = envelope.data;
  const state = t?.state ?? 'LOADING';
  const stateColor = state === 'MISSING_EVIDENCE' ? '#f59e0b' : state === 'OK' ? '#26c281' : state === 'LOADING' ? 'var(--text-muted)' : '#ef5350';
  return (
    <div style={{ background: 'rgba(99,102,241,0.04)', border: '1px solid rgba(99,102,241,0.15)', borderRadius: 10, padding: '12px 16px', display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>🧠</span>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Trainer</div>
          <div style={{ fontSize: 13, fontWeight: 800, fontFamily: 'var(--font-mono)', color: stateColor }}>{state}</div>
        </div>
      </div>
      {t?.checkpoint_id && <div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>Checkpoint</div>
        <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{t.checkpoint_id.slice(0, 20)}…</div>
      </div>}
      {t?.uptime_days != null && <div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>Uptime</div>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{t.uptime_days.toFixed(1)}d</div>
      </div>}
      {t?.win_rate_30d != null && <div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>Win Rate 30d</div>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: t.win_rate_30d >= 0.6 ? '#26c281' : '#f59e0b' }}>{(t.win_rate_30d * 100).toFixed(1)}%</div>
      </div>}
      {t?.episodes_total != null && <div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>Episodes</div>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{t.episodes_total.toLocaleString()}</div>
      </div>}
      {t?.drift_alarm_count != null && <div>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>Drift Alarms</div>
        <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: t.drift_alarm_count > 0 ? '#ef5350' : '#26c281' }}>{t.drift_alarm_count}</div>
      </div>}
      <div style={{ marginLeft: 'auto' }}>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>
    </div>
  );
}

// ─── Sort header ──────────────────────────────────────────────────────────

type SortKey = 'symbol' | 'timeframe' | 'action' | 'confidence_calibrated' | 'age_seconds' | 'data_coverage_percent' | 'missing_feature_count';
type SortDir = 'asc' | 'desc';

function SortTh({ label, col, current, dir, onSort }: { label: string; col: SortKey; current: SortKey; dir: SortDir; onSort: (c: SortKey) => void }): JSX.Element {
  const active = current === col;
  return (
    <th onClick={() => onSort(col)} style={{ padding: '8px 12px', textAlign: 'left', cursor: 'pointer', userSelect: 'none', borderBottom: '1px solid var(--border)', color: active ? '#6366f1' : 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, whiteSpace: 'nowrap', background: 'var(--bg-panel)' }}>
      {label}{active ? (dir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────

export default function AIPredictionsPage(): JSX.Element {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set(DEFAULT_SYMBOLS));
  const [selectedTFs, setSelectedTFs] = useState<Set<TF>>(new Set(TIMEFRAMES));
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [showAllSymbols, setShowAllSymbols] = useState(false);
  const [symbolSearch, setSymbolSearch] = useState('');
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const currentLineage = useCurrentRuntimeLineage(10_000);

  const symbolsParam = Array.from(selectedSymbols).join(',');
  const tfsParam = Array.from(selectedTFs).join(',');
  const url = `/api/v2/predictions/matrix?symbols=${symbolsParam}&timeframes=${tfsParam}`;

  const { envelope, loading, refetch } = useRealtimeResource<PredMatrixData>({
    url, source: '/api/v2/predictions/matrix', source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 20_000, mode: 'read_only',
  });
  const { envelope: allEnv } = useRealtimeResource<PredMatrixData>({
    url: '/api/v2/predictions/matrix', source: '/api/v2/predictions/matrix', source_type: 'websocket', pollIntervalMs: 60_000, mode: 'read_only',
  });

  // Keep top-liquidity defaults attached to the shared liquidation resource stream.
  const { envelope: liqHeatmapEnv } = useRealtimeResource<{ pinned_defaults?: string[] }>({
    url: '/api/v2/liquidation/levels-heatmap', source: '/api/v2/liquidation/levels-heatmap',
    source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 30_000, mode: 'read_only', initialFetch: true,
  });
  useEffect(() => {
    const pinned = liqHeatmapEnv.data?.pinned_defaults;
    if (!pinned || pinned.length === 0) return;
    // Only auto-select if user hasn't deviated from core defaults
    setSelectedSymbols(prev => {
      const hasCustom = Array.from(prev).some(s => !DEFAULT_SYMBOLS.includes(s));
      if (hasCustom) return prev;
      const next = new Set([...PINNED_CORE, ...pinned.slice(0, 5)]);
      return next;
    });
  }, [liqHeatmapEnv.data?.pinned_defaults?.join(',')]);

  const lineagePredictionRow = useMemo(() => predictionRowFromLineage(currentLineage.envelope.data), [currentLineage.envelope.data]);
  const matrixRows = envelope.data?.rows ?? [];
  const rows = useMemo(
    () => matrixRows.length ? matrixRows : lineagePredictionRow ? [lineagePredictionRow] : [],
    [lineagePredictionRow, matrixRows],
  );
  const usingLineageFallback = matrixRows.length === 0 && rows.length > 0;
  const allSymbols = useMemo(() => {
    const next = new Set(allEnv.data?.symbols ?? []);
    if (lineagePredictionRow?.symbol) next.add(lineagePredictionRow.symbol);
    return Array.from(next);
  }, [allEnv.data?.symbols, lineagePredictionRow?.symbol]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      let av: string | number = 0, bv: string | number = 0;
      if (sortKey === 'symbol') { av = a.symbol; bv = b.symbol; }
      else if (sortKey === 'timeframe') { const o: Record<string, number> = { '1m': 0, '5m': 1, '15m': 2, '1h': 3, '4h': 4 }; av = o[a.timeframe] ?? 99; bv = o[b.timeframe] ?? 99; }
      else if (sortKey === 'action') { av = a.action ?? ''; bv = b.action ?? ''; }
      else if (sortKey === 'confidence_calibrated') { av = a.confidence_calibrated ?? -1; bv = b.confidence_calibrated ?? -1; }
      else if (sortKey === 'age_seconds') { av = a.age_seconds ?? 999999; bv = b.age_seconds ?? 999999; }
      else if (sortKey === 'data_coverage_percent') { av = a.data_coverage_percent ?? -1; bv = b.data_coverage_percent ?? -1; }
      else if (sortKey === 'missing_feature_count') { av = a.missing_feature_count ?? 999; bv = b.missing_feature_count ?? 999; }
      if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const handleSort = useCallback((col: SortKey) => {
    if (col === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortKey(col); setSortDir('asc'); }
  }, [sortKey]);

  const displayedSymbols = useMemo(() => {
    const filter = symbolSearch.trim().toUpperCase();
    const pool = showAllSymbols ? allSymbols : DEFAULT_SYMBOLS;
    return filter ? pool.filter(s => s.includes(filter)) : pool;
  }, [showAllSymbols, allSymbols, symbolSearch]);

  const avgCal = rows.length > 0 ? rows.reduce((s, r) => s + (r.confidence_calibrated ?? 0), 0) / rows.length : null;
  const coverageAvg = rows.length > 0 ? rows.reduce((s, r) => s + (r.data_coverage_percent ?? 0), 0) / rows.length : null;
  const predictionFeedReady = rows.length > 0;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.signal_prediction_accuracy_status
    ?? null;
  const evaluatedAccuracyCells = accuracyStatus?.evaluated_symbol_timeframe_cell_count;
  const totalAccuracyCells = accuracyStatus?.symbol_timeframe_cell_count
    ?? accuracyStatus?.required_symbol_timeframe_cell_count;
  const missingAccuracyCells = missingAccuracyCellCount(accuracyStatus);

  return (
    <div data-testid="page-ai-predictions" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>

      {/* Header — distinct purple/indigo theme vs signals blue */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '2px solid rgba(99,102,241,0.2)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>🧠</span>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>AI Predictions</h1>
              <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(99,102,241,0.12)', color: '#6366f1', border: '1px solid rgba(99,102,241,0.3)', fontFamily: 'var(--font-mono)' }}>RAW MODEL OUTPUT</span>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              Action probability distributions · Softmax output · Confidence calibration (temperature + coverage) · MASA/policy signals · {predictionFeedReady ? rows.length : '—'} active predictions
              {usingLineageFallback ? ' · current runtime lineage' : ''}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid rgba(99,102,241,0.3)', background: 'rgba(99,102,241,0.08)', color: '#6366f1', fontSize: 11, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>

        <div style={{ marginBottom: 12 }}><TrainerCard /></div>

        {/* KPI strip */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          {[
            { label: 'Total Predictions', value: predictionFeedReady ? rows.length : '—', color: 'var(--text-primary)' },
            { label: 'Avg Calibrated Conf', value: avgCal != null ? fmtConf(avgCal) : '—', color: confColor(avgCal) },
            { label: 'Avg Feature Coverage', value: coverageAvg != null ? `${coverageAvg.toFixed(1)}%` : '—', color: (coverageAvg ?? 0) >= 80 ? '#26c281' : '#f59e0b' },
            { label: 'Long Bias', value: predictionFeedReady ? rows.filter(r => (r.action ?? '').includes('long')).length : '—', color: '#26c281' },
            { label: 'Short Bias', value: predictionFeedReady ? rows.filter(r => (r.action ?? '').includes('short')).length : '—', color: '#ef5350' },
            { label: 'Hold', value: predictionFeedReady ? rows.filter(r => r.action === 'hold').length : '—', color: '#f59e0b' },
            { label: 'Accuracy', value: formatAdaptivePercent(accuracyStatus?.overall_accuracy), color: adaptiveStatusColor(accuracyStatus?.status) },
            { label: 'Evaluated', value: accuracyStatus?.evaluated_row_count ?? '—', color: 'var(--text-primary)' },
            { label: 'In Universe', value: allSymbols.length || '—', color: 'var(--text-muted)' },
            { label: 'TF Cells', value: evaluatedAccuracyCells != null || totalAccuracyCells != null ? `${evaluatedAccuracyCells ?? 0}/${totalAccuracyCells ?? 0}` : '—', color: 'var(--text-primary)' },
            { label: 'Missing Cells', value: missingAccuracyCells ?? '—', color: (missingAccuracyCells ?? 0) > 0 ? '#ef5350' : '#26c281' },
          ].map(k => (
            <div key={k.label} style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 10px', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k.label}</span>
              <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: k.color }}>{k.value}</span>
            </div>
          ))}
        </div>

        {/* Symbol selector */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Symbols</span>
            <input value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)} placeholder="Filter..." style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 11, width: 90, outline: 'none' }} />
            <button onClick={() => setShowAllSymbols(s => !s)} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>
              {showAllSymbols ? `Default (${DEFAULT_SYMBOLS.length})` : `All (${allSymbols.length || '—'})`}
            </button>
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxHeight: 64, overflowY: 'auto' }}>
            {displayedSymbols.map(s => (
              <button key={s} onClick={() => {
                setSelectedSymbols(prev => { const n = new Set(prev); if (n.has(s)) { if (n.size > 1) n.delete(s); } else n.add(s); return n; });
              }} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 10, fontWeight: selectedSymbols.has(s) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedSymbols.has(s) ? '#6366f1' : 'var(--border)'}`, background: selectedSymbols.has(s) ? 'rgba(99,102,241,0.12)' : 'transparent', color: selectedSymbols.has(s) ? '#6366f1' : 'var(--text-secondary)' }}>
                {s.replace('USDT', '')}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: 4 }}>Timeframes</span>
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => {
              setSelectedTFs(prev => { const n = new Set(prev); if (n.has(tf)) { if (n.size > 1) n.delete(tf); } else n.add(tf); return n; });
            }} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 11, fontWeight: selectedTFs.has(tf) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedTFs.has(tf) ? '#6366f1' : 'var(--border)'}`, background: selectedTFs.has(tf) ? 'rgba(99,102,241,0.12)' : 'transparent', color: selectedTFs.has(tf) ? '#6366f1' : 'var(--text-secondary)' }}>
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: '12px 16px 0' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Prediction Accuracy + Capital Productivity"
          compact
          showMatrix
          maxMatrixHeight={260}
        />
      </div>

      {/* Table */}
      <div style={{ padding: 16 }}>
        {loading && sorted.length === 0 && <LoadingSkeleton rows={8} />}
        {!loading && sorted.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', background: 'var(--bg-panel)', borderRadius: 12, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>🧠</div>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>Prediction stream connecting. Existing panels stay mounted while WebSocket and HTTP fallback connect.</p>
          </div>
        )}
        {sorted.length > 0 && (
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    <SortTh label="Symbol" col="symbol" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="TF" col="timeframe" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Prediction" col="action" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Conf Cal." col="confidence_calibrated" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Accuracy / PnL</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Top Probs</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Price Target</th>
                    <SortTh label="Coverage" col="data_coverage_percent" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Missing" col="missing_feature_count" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Age" col="age_seconds" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(row => {
                    const rowKey = `${row.symbol}:${row.timeframe}`;
                    const expanded = expandedRow === rowKey;
                    const topColor = actionColor(row.top_action);
                    const secondColor = actionColor(row.second_action);
                    const accuracy = lookupAccuracyCell(accuracyStatus, row.symbol, row.timeframe);
                    return (
                      <React.Fragment key={rowKey}>
                        <tr onClick={() => setExpandedRow(expanded ? null : rowKey)}
                          style={{ cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.04)', background: expanded ? 'rgba(99,102,241,0.04)' : 'transparent' }}
                          onMouseEnter={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'; }}
                          onMouseLeave={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>
                            {row.symbol.replace('USDT', '')}<span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 10, marginLeft: 2 }}>USDT</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#6366f1', padding: '2px 6px', background: 'rgba(99,102,241,0.06)', borderRadius: 4, border: '1px solid rgba(99,102,241,0.15)' }}>{row.timeframe}</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            {row.action ? (
                              <span style={{ padding: '3px 10px', borderRadius: 5, fontSize: 11, fontWeight: 800, fontFamily: 'var(--font-mono)', color: actionColor(row.action), background: `${actionColor(row.action)}15`, border: `1px solid ${actionColor(row.action)}30` }}>
                                {row.action.replace(/_/g, ' ').toUpperCase()}
                              </span>
                            ) : <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>}
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{ width: 56, height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                                <div style={{ height: '100%', width: `${Math.min(100, (row.confidence_calibrated ?? 0) * 100)}%`, background: confColor(row.confidence_calibrated), borderRadius: 3 }} />
                              </div>
                              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: confColor(row.confidence_calibrated), fontWeight: 700 }}>{fmtConf(row.confidence_calibrated)}</span>
                              <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>/{fmtConf(row.confidence_raw)}</span>
                            </div>
                          </td>
                          <td style={{ padding: '10px 12px' }}><AccuracyBadge cell={accuracy} /></td>
                          <td style={{ padding: '10px 12px' }}>
                            <div style={{ display: 'flex', gap: 4 }}>
                              {row.top_action && <span style={{ padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', color: topColor, background: `${topColor}18`, border: `1px solid ${topColor}30` }}>{row.top_action.replace(/_/g, ' ')} {row.top_prob != null ? `${(row.top_prob * 100).toFixed(0)}%` : ''}</span>}
                              {row.second_action && row.second_prob != null && row.second_prob >= 0.05 && <span style={{ padding: '2px 6px', borderRadius: 4, fontSize: 9, fontFamily: 'var(--font-mono)', color: secondColor, opacity: 0.7 }}>{row.second_action.replace(/_/g, ' ')} {(row.second_prob * 100).toFixed(0)}%</span>}
                            </div>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            {row.price_target ? (
                              <div>
                                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12, color: actionColor(row.action) }}>{fmtPrice(row.price_target)}</div>
                                {row.expected_move_bps != null && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{(row.expected_move_bps / 100).toFixed(2)}%</div>}
                              </div>
                            ) : <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: (row.data_coverage_percent ?? 0) >= 80 ? '#26c281' : '#f59e0b' }}>
                            {row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(0)}%` : '—'}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: (row.missing_feature_count ?? 0) > 20 ? '#f59e0b' : '#26c281' }}>
                            {row.missing_feature_count ?? '—'}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: (row.age_seconds ?? 0) < 3600 ? 'var(--text-secondary)' : '#ef5350' }}>
                            {fmtAge(row.age_seconds)}
                          </td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{expanded ? '▲' : '▶'}</td>
                        </tr>
                        {expanded && <PredExpandedRow row={row} />}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div style={{ marginTop: 12, padding: '8px 0', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
            Prediction source: Redis v2:prediction:* · Raw model output · {sorted.length} rows
          </p>
        </div>
      </div>
    </div>
  );
}
