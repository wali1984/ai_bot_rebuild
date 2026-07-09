import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useEnterpriseRealtimeResource } from '../../lib/realtime/RealtimeProvider';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';

const TRAINER_ENDPOINT = '/api/v2/trainer/status';
const RISK_ENDPOINT = '/api/v2/risk/status';
const PAPER_RUNTIME_ENDPOINT = '/api/v2/paper/runtime-status';

const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };
function sColor(s?: string | null) {
  const v = (s || '').toLowerCase();
  if (v.includes('active') || v === 'ok') return SC.ok;
  if (v.includes('missing') || v.includes('error') || v === 'failed') return SC.error;
  if (v.includes('warn') || v.includes('degraded')) return SC.warn;
  return SC.unknown;
}

function Chip({ label, color }: { label: string; color: string }) {
  return <span style={{ padding: '2px 8px', borderRadius: 4, background: `${color}20`, border: `1px solid ${color}55`, color, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: '0.06em' }}>{label}</span>;
}

function Field({ label, value, mono, accent, full }: { label: string; value: string; mono?: boolean; accent?: string; full?: boolean }) {
  return (
    <div style={{ display: full ? 'block' : 'flex', justifyContent: 'space-between', alignItems: full ? undefined : 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--line-soft)' }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', display: full ? 'block' : undefined, marginBottom: full ? 2 : undefined }}>{label}</span>
      <span style={{ fontSize: 12, color: accent || 'var(--text-primary)', fontFamily: mono ? 'var(--font-mono)' : undefined, wordBreak: full ? 'break-all' : undefined, textAlign: full ? undefined : 'right' }}>{value}</span>
    </div>
  );
}

function flagText(value: boolean | null | undefined): string {
  if (value === true) return 'YES';
  if (value === false) return 'NO';
  return '—';
}

function numText(value: number | null | undefined, digits = 0): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function unitPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '—';
}

function bpsText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value / 100).toFixed(2)}%` : '—';
}

function runtimeSourceText(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value.trim()) return value;
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, entry]) => `${key}: ${String(entry)}`)
      .join(' · ') || fallback;
  }
  return fallback;
}

interface TrainerPayload {
  state?: string; checkpoint_id?: string; uptime_days?: number | null;
  win_rate_30d?: number | null; episodes_total?: number | null;
  drift_watch_count?: number | null; drift_alarm_count?: number | null;
  promotion_locked?: boolean | null; promotion_min_role?: string | null;
  cuda_active?: boolean; data_coverage?: number | null;
  model_source?: string; model_id?: string;
}

interface RiskPayload {
  data?: {
    latest_gateway_result?: {
      symbol?: string; side?: string; risk_action?: string; risk_result?: string;
      risk_reason_code?: string; live_blocked?: boolean; generated_at?: string;
      strategy_router_confidence?: number | null;
      required_blocks_checked?: string[];
    };
    heartbeat?: { decisions_processed_total?: number; finished_at?: string };
    active_profile?: { profile_name?: string; profile_id?: string };
  };
}

interface PaperTrainerModelQualityStatus {
  available?: boolean | null;
  status?: string | null;
  weights_update?: boolean | null;
  quality_metrics_current?: boolean | null;
  trusted_rows_loaded?: number | null;
  optimizer_steps_last_hour?: number | null;
  parameter_hash_changed?: boolean | null;
  checkpoint_written?: boolean | null;
  checkpoint_reload_verified?: boolean | null;
  directional_accuracy?: number | null;
  after_cost_expectancy_bps?: number | null;
  counts_as_a_grade_evidence?: boolean | null;
  a_grade_promotion_allowed?: boolean | null;
  routes_to_live?: boolean | null;
  places_real_order?: boolean | null;
  source?: unknown;
}

interface PaperRuntimePayload {
  live_gate_status?: string | null;
  paper_loop?: {
    paper_policy_owner?: string | null;
    production_grade_cost_coverage?: number | null;
    a_grade_rows?: number | null;
    guardian_status?: string | null;
    paper_trainer_model_quality_runtime_status?: PaperTrainerModelQualityStatus | null;
    trainer_model_quality_runtime_status?: PaperTrainerModelQualityStatus | null;
  } | null;
  blockers?: Array<{ id?: string; detail?: string; severity?: string }> | null;
}

interface EnterpriseAiPageContract {
  ppo_tensor_provider_features?: boolean;
  masa_tensor_provider_features?: boolean;
  provider_feature_count_by_provider?: Record<string, number>;
  provider_features_in_tensor?: unknown;
  provider_contribution_last_50?: { status?: string; sample_count?: number } | Record<string, unknown>;
  altdata_actionability?: {
    blocked?: number | null;
    reduced?: number | null;
    hedged?: number | null;
  };
  next_replay_or_backtest?: string;
  live_gate?: string;
  routes_to_live?: boolean;
  places_real_order?: boolean;
}

interface EnterpriseAiBrainSnapshot {
  ai_page_contract?: EnterpriseAiPageContract;
  provider_feature_counts?: Record<string, number>;
  provider_confluence_available?: boolean;
}

const TABS = ['Model', 'Predictions', 'Signals', 'Risk Checks'] as const;
type Tab = typeof TABS[number];

export default function AdminIntelligencePage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Model');
  const { envelope: te, loading } = useRealtimeResource<TrainerPayload>({ url: TRAINER_ENDPOINT, source: 'admin-intelligence', pollIntervalMs: 15_000 });
  const { envelope: re } = useRealtimeResource<RiskPayload>({ url: RISK_ENDPOINT, source: 'admin-risk-data', pollIntervalMs: 10_000 });
  const { envelope: pe } = useRealtimeResource<PaperRuntimePayload>({
    url: PAPER_RUNTIME_ENDPOINT,
    source: PAPER_RUNTIME_ENDPOINT,
    source_type: 'api',
    pollIntervalMs: 10_000,
    staleThresholdMs: 45_000,
    mode: 'paper',
  });
  const enterpriseAiSnapshot = useEnterpriseRealtimeResource<EnterpriseAiBrainSnapshot>('ai_brain');

  const t = te.data;
  const r = re.data?.data;
  const runtime = pe.data;
  const paperLoop = runtime?.paper_loop;
  const trainerQuality = paperLoop?.paper_trainer_model_quality_runtime_status
    ?? paperLoop?.trainer_model_quality_runtime_status
    ?? null;
  const hasRuntimeTrainerQuality = Boolean(
    trainerQuality?.available
    || trainerQuality?.status
    || trainerQuality?.quality_metrics_current != null,
  );
  const latestDecision = r?.latest_gateway_result;
  const enterpriseAiPayload = enterpriseAiSnapshot?.payload;
  const aiPageContract = enterpriseAiPayload?.ai_page_contract;
  const aiProviderCounts = aiPageContract?.provider_feature_count_by_provider
    ?? enterpriseAiPayload?.provider_feature_counts
    ?? {};
  const aiContractReady = Boolean(aiPageContract)
    && aiPageContract?.routes_to_live === false
    && aiPageContract?.places_real_order === false;

  const trainerOk = t?.state?.includes('ACTIVE');
  const stateColor = sColor(t?.state ?? trainerQuality?.status);
  const trainerStateLabel = t?.state
    ? t.state.replace(/_/g, ' ')
    : trainerQuality?.status
      ? trainerQuality.status.replace(/_/g, ' ')
      : loading
        ? '...'
        : 'runtime pending';
  const dataCoverageLabel = t?.data_coverage != null
    ? `${t.data_coverage.toFixed(1)}%`
    : trainerQuality?.trusted_rows_loaded != null
      ? `${trainerQuality.trusted_rows_loaded.toLocaleString()} trusted rows`
      : '-';
  const cudaLabel = t?.cuda_active != null
    ? (t.cuda_active ? 'ACTIVE' : 'NONE')
    : hasRuntimeTrainerQuality
      ? 'V2 CUDA'
      : '-';
  const cudaAccent = t?.cuda_active
    ? SC.ok
    : t?.cuda_active === false
      ? SC.warn
      : hasRuntimeTrainerQuality
        ? SC.ok
        : SC.unknown;
  const winRateLabel = t?.win_rate_30d != null
    ? `${(t.win_rate_30d * 100).toFixed(1)}%`
    : trainerQuality?.directional_accuracy != null
      ? `${(trainerQuality.directional_accuracy * 100).toFixed(1)}% directional`
      : '-';
  const episodesLabel = t?.episodes_total != null
    ? t.episodes_total.toLocaleString()
    : trainerQuality?.optimizer_steps_last_hour != null
      ? `${trainerQuality.optimizer_steps_last_hour} steps/hr`
      : '-';

  return (
    <div data-testid="admin-intelligence-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Intelligence</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Trainer state, model checkpoint, signal quality, and prediction stream</p>
        </div>
        <FreshnessBadge status={te.freshness_status} lagMs={te.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {[
          { label: 'TRAINER STATE', value: trainerStateLabel, accent: stateColor },
          { label: 'DATA COVERAGE', value: dataCoverageLabel },
          { label: 'CUDA', value: cudaLabel, accent: cudaAccent },
          { label: 'WIN RATE 30D', value: winRateLabel },
          { label: 'EPISODES', value: episodesLabel },
        ].map(({ label, value, accent }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      <div id="enterprise-ai-data-plane" style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Enterprise AI Data Plane</div>
          <Chip label={aiContractReady ? 'READY' : 'PARTIAL'} color={aiContractReady ? SC.ok : SC.warn} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0 18px' }}>
          <Field label="PPO tensor" value={aiPageContract?.ppo_tensor_provider_features ? 'provider features visible' : 'pending'} mono />
          <Field label="MASA tensor" value={aiPageContract?.masa_tensor_provider_features ? 'provider features visible' : 'pending'} mono />
          <Field label="Confluence" value={enterpriseAiPayload?.provider_confluence_available ? 'available' : 'pending'} mono />
          <Field label="Last 50 contribution" value={String((aiPageContract?.provider_contribution_last_50 as { status?: string } | undefined)?.status ?? 'not available')} mono />
          <Field label="Blocked / reduced / hedged" value={`${aiPageContract?.altdata_actionability?.blocked ?? 0} / ${aiPageContract?.altdata_actionability?.reduced ?? 0} / ${aiPageContract?.altdata_actionability?.hedged ?? 0}`} mono />
          <Field label="Replay" value={runtimeSourceText(aiPageContract?.next_replay_or_backtest, 'pending')} mono />
          <Field label="Live gate" value={runtimeSourceText(aiPageContract?.live_gate ?? 'blocked_human_only', 'blocked_human_only')} mono />
          <Field label="Routes to live" value={flagText(aiPageContract?.routes_to_live)} mono />
          <Field label="CoinGlass features" value={numText(aiProviderCounts.coinglass)} mono />
          <Field label="Santiment features" value={numText(aiProviderCounts.santiment)} mono />
          <Field label="Moralis features" value={numText(aiProviderCounts.moralis)} mono />
          <Field label="Tensor channel" value={aiPageContract?.provider_features_in_tensor ? 'present' : 'pending'} mono />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map(t2 => (
          <button key={t2} type="button" onClick={() => setTab(t2)}
            data-testid={`tab-${t2.toLowerCase().replace(/\s+/g, '-')}`}
            style={{
              padding: '7px 16px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 12, fontWeight: tab === t2 ? 700 : 400,
              color: tab === t2 ? 'var(--text-primary)' : 'var(--text-muted)',
              borderBottom: tab === t2 ? '2px solid var(--admin-accent)' : '2px solid transparent',
            }}>{t2}</button>
        ))}
      </div>

      {tab === 'Model' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Checkpoint</div>
            {loading && !t ? <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div> : t ? (
              <>
                <Field label="State" value={t.state || '—'} accent={stateColor} mono />
                <Field label="Checkpoint ID" value={t.checkpoint_id || '—'} mono full />
                <Field label="Model ID" value={t.model_id || '—'} mono full />
                <Field label="Source" value={t.model_source || '—'} mono />
                <Field label="Coverage" value={t.data_coverage != null ? `${t.data_coverage.toFixed(4)}%` : '—'} mono />
                <Field label="CUDA" value={t.cuda_active ? 'YES' : t.cuda_active === false ? 'NO' : '—'} accent={t.cuda_active ? SC.ok : SC.warn} mono />
                <Field label="Uptime" value={t.uptime_days != null ? `${t.uptime_days}d` : '—'} mono />
                <Field label="Promotion Locked" value={t.promotion_locked != null ? (t.promotion_locked ? 'YES' : 'NO') : '—'} mono accent={t.promotion_locked ? SC.warn : undefined} />
              </>
            ) : (
              <div style={{ padding: '8px 0', color: 'var(--text-muted)', fontSize: 12 }}>
                {hasRuntimeTrainerQuality
                  ? 'Direct trainer endpoint unavailable; using current paper runtime trainer quality contract.'
                  : 'Direct trainer endpoint unavailable; runtime trainer quality contract pending.'}
                <div style={{ marginTop: 6, fontSize: 11, fontFamily: 'var(--font-mono)', color: hasRuntimeTrainerQuality ? SC.ok : SC.warn }}>
                  Source: {hasRuntimeTrainerQuality ? PAPER_RUNTIME_ENDPOINT : TRAINER_ENDPOINT}
                </div>
              </div>
            )}
          </div>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Drift & Quality</div>
            <Field label="Drift Watches" value={t?.drift_watch_count != null ? String(t.drift_watch_count) : '—'} mono />
            <Field label="Drift Alarms" value={t?.drift_alarm_count != null ? String(t.drift_alarm_count) : '—'} mono accent={t?.drift_alarm_count ? SC.warn : undefined} />
            <Field label="Win Rate 30D" value={t?.win_rate_30d != null ? `${(t.win_rate_30d * 100).toFixed(2)}%` : '—'} mono />
            <Field label="Episodes Total" value={t?.episodes_total != null ? t.episodes_total.toLocaleString() : '—'} mono />
            <Field label="Promo Min Role" value={t?.promotion_min_role || '—'} mono />
          </div>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Paper Runtime Trainer Quality</div>
            <Field label="Runtime status" value={trainerQuality?.status || 'TRAINER_MODEL_QUALITY_RUNTIME_STATUS_UNAVAILABLE'} mono full accent={trainerQuality?.quality_metrics_current ? SC.ok : SC.warn} />
            <Field label="Weights update" value={flagText(trainerQuality?.weights_update)} mono accent={trainerQuality?.weights_update ? SC.ok : SC.warn} />
            <Field label="Optimizer steps last hour" value={numText(trainerQuality?.optimizer_steps_last_hour)} mono accent={(trainerQuality?.optimizer_steps_last_hour ?? 0) > 0 ? SC.ok : SC.warn} />
            <Field label="Trusted rows loaded" value={numText(trainerQuality?.trusted_rows_loaded)} mono />
            <Field label="Parameter hash changed" value={flagText(trainerQuality?.parameter_hash_changed)} mono accent={trainerQuality?.parameter_hash_changed ? SC.ok : SC.warn} />
            <Field label="Checkpoint written" value={flagText(trainerQuality?.checkpoint_written)} mono accent={trainerQuality?.checkpoint_written ? SC.ok : SC.warn} />
            <Field label="Checkpoint reload" value={flagText(trainerQuality?.checkpoint_reload_verified)} mono accent={trainerQuality?.checkpoint_reload_verified ? SC.ok : SC.warn} />
            <Field label="Directional accuracy" value={unitPercent(trainerQuality?.directional_accuracy)} mono />
            <Field label="After-cost expectancy" value={bpsText(trainerQuality?.after_cost_expectancy_bps)} mono />
            <Field label="A-grade promotion" value={trainerQuality?.a_grade_promotion_allowed ? 'ALLOWED' : 'BLOCKED'} mono accent={trainerQuality?.a_grade_promotion_allowed ? SC.ok : SC.warn} />
            <Field label="Paper owner / cost" value={`${paperLoop?.paper_policy_owner ?? '—'} / ${unitPercent(paperLoop?.production_grade_cost_coverage)}`} mono />
            <Field label="Guardian blocker" value={paperLoop?.guardian_status ?? runtime?.blockers?.[0]?.id ?? '—'} mono full accent={(paperLoop?.a_grade_rows ?? 0) > 0 ? SC.ok : SC.warn} />
            <Field label="Runtime source" value={runtimeSourceText(trainerQuality?.source, PAPER_RUNTIME_ENDPOINT)} mono full />
          </div>
        </div>
      )}

      {tab === 'Predictions' && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Latest Gateway Decision</div>
          {latestDecision ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              <Field label="Symbol" value={latestDecision.symbol || '—'} mono />
              <Field label="Side" value={latestDecision.side || '—'} mono />
              <Field label="Action" value={latestDecision.risk_action?.toUpperCase() || '—'} mono
                accent={latestDecision.risk_action === 'deny' ? SC.error : latestDecision.risk_action === 'allow' ? SC.ok : SC.warn} />
              <Field label="Result" value={latestDecision.risk_result || '—'} mono />
              <Field label="Reason" value={latestDecision.risk_reason_code || '—'} mono />
              <Field label="Confidence" value={latestDecision.strategy_router_confidence != null ? latestDecision.strategy_router_confidence.toFixed(4) : '—'} mono />
              <Field label="Generated" value={relativeAge(latestDecision.generated_at)} />
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No decision data. Risk gateway heartbeat pending.</div>
          )}
        </div>
      )}

      {tab === 'Signals' && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Signal stream data requires <span style={{ fontFamily: 'var(--font-mono)', color: SC.info }}>/api/v2/signals</span> endpoint. Wire signal publisher to populate this tab.</div>
        </div>
      )}

      {tab === 'Risk Checks' && latestDecision?.required_blocks_checked && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Required Blocks Checked ({latestDecision.required_blocks_checked.length})</div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {latestDecision.required_blocks_checked.map(b => <Chip key={b} label={b} color={SC.info} />)}
          </div>
          {r?.active_profile && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Active Risk Profile</div>
              <Field label="Profile" value={r.active_profile.profile_name || r.active_profile.profile_id || '—'} mono />
            </div>
          )}
        </div>
      )}
      {tab === 'Risk Checks' && !latestDecision?.required_blocks_checked && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-muted)', fontSize: 12 }}>
          No risk check data available. Risk gateway result pending.
        </div>
      )}
    </div>
  );
}
