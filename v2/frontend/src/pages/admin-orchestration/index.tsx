import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { DangerousControlPanel } from '../../components/controls/DangerousControlPanel';
import meta from './meta';

const PIPELINE_ENDPOINT = '/api/v2/pipeline/status';

const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa', accent: '#a78bfa' };
function gateColor(g?: string) {
  if (!g) return SC.unknown;
  if (g.includes('blocked')) return SC.error;
  if (g.includes('live')) return SC.ok;
  return SC.warn;
}

function Chip({ label, color, small }: { label: string; color: string; small?: boolean }) {
  return <span style={{ padding: small ? '1px 6px' : '2px 8px', borderRadius: 4, background: `${color}20`, border: `1px solid ${color}44`, color, fontSize: small ? 10 : 11, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{label}</span>;
}

interface PipelinePayload {
  schema_version?: string; generated_utc?: string; live_gate?: string;
  live_symbols?: string[]; execution_live_symbols?: string[];
  trader_execution_enabled?: boolean; live_gate_runtime_source?: string;
  exchange_action_taken?: boolean; control_stream_key?: string;
  control_last_request_key?: string; allowed_run_types?: string[];
  symbols?: string[];
}

interface APlusGateBlock {
  evaluated_candidates?: number | null;
  a_plus_candidates?: number | null;
  strict_a_plus_candidates?: number | null;
  adaptive_override_candidates?: number | null;
  rejected_reason_matrix?: Record<string, number> | null;
  candidate_matrix_preview?: Array<{
    symbol?: string | null;
    timeframe?: string | null;
    side?: string | null;
    failed_checks?: string[] | null;
    passed_check_count?: number | null;
    check_count?: number | null;
  }> | null;
  full_candidate_count?: number | null;
}

interface PaperRuntimeStatusPayload {
  a_plus_gate?: APlusGateBlock | null;
}

function APlusGatePanel({ gate }: { gate: APlusGateBlock | null }): JSX.Element {
  const rejections = Object.entries(gate?.rejected_reason_matrix ?? {}).sort(([, a], [, b]) => b - a).slice(0, 12);
  const maxRejection = rejections.length ? rejections[0][1] : 1;
  const preview = gate?.candidate_matrix_preview ?? [];
  return (
    <div data-testid="admin-a-plus-gate-panel" style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>
        A+ Entry Gate — rejection funnel
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
        {gate?.evaluated_candidates ?? 0} evaluated · {gate?.strict_a_plus_candidates ?? 0} strict A+ · {gate?.adaptive_override_candidates ?? 0} adaptive-override (paper exploration, not strict A+)
      </div>
      {rejections.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No rejection matrix published — check paper loop freshness.</div>
      ) : rejections.map(([reason, count]) => (
        <div key={reason} style={{ marginBottom: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
            <span style={{ color: 'var(--text-muted)' }}>{reason.replace(/_/g, ' ')}</span>
            <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{count}/{gate?.evaluated_candidates ?? '—'}</span>
          </div>
          <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-base)' }}>
            <div style={{ width: `${Math.min(100, (count / maxRejection) * 100)}%`, height: 4, borderRadius: 2, background: SC.warn }} />
          </div>
        </div>
      ))}
      {preview.length > 0 && (
        <div style={{ marginTop: 10, borderTop: '1px solid var(--line-soft)', paddingTop: 8, overflowX: 'auto' }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>
            Per-candidate failed checks (first {preview.length} of {gate?.full_candidate_count ?? gate?.evaluated_candidates ?? '—'})
          </div>
          {preview.map((row, i) => (
            <div key={`${row.symbol}-${row.timeframe}-${row.side}-${i}`} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--line-soft)', fontSize: 11 }}>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', whiteSpace: 'nowrap', minWidth: 150 }}>{row.symbol ?? '—'} {row.timeframe ?? ''} {row.side ?? ''}</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: (row.failed_checks?.length ?? 0) === 0 ? SC.ok : SC.warn, whiteSpace: 'nowrap' }}>{row.passed_check_count ?? '—'}/{row.check_count ?? '—'}</span>
              <span style={{ color: (row.failed_checks?.length ?? 0) === 0 ? SC.ok : 'var(--text-muted)' }}>
                {(row.failed_checks?.length ?? 0) === 0 ? 'none — strict A+' : (row.failed_checks ?? []).join(', ').replace(/_/g, ' ')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TABS = ['Orchestrator', 'Symbols', 'Control'] as const;
type Tab = typeof TABS[number];

export default function AdminOrchestrationPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Orchestrator');
  const [symFilter, setSymFilter] = useState('');
  const { envelope, loading } = useRealtimeResource<PipelinePayload>({ url: PIPELINE_ENDPOINT, source: 'admin-orchestration', pollIntervalMs: 15_000 });
  const p = envelope.data;
  const { envelope: paperRuntimeEnvelope } = useRealtimeResource<PaperRuntimeStatusPayload>({
    url: '/api/v2/paper/runtime-status', source: '/api/v2/paper/runtime-status',
    pollIntervalMs: 15_000, staleThresholdMs: 90_000, mode: 'read_only', unwrapEnvelopeData: false,
  });
  const aPlusGate = paperRuntimeEnvelope.data?.a_plus_gate ?? null;

  const gate = p?.live_gate || '—';
  const symbols = p?.symbols || [];
  const filtered = symFilter ? symbols.filter(s => s.toLowerCase().includes(symFilter.toLowerCase())) : symbols;
  const allowedTypes = p?.allowed_run_types || [];

  return (
    <div data-testid="admin-orchestration-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Orchestration</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Pipeline control, live gate, symbol universe, and run-type management</p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {[
          { label: 'LIVE GATE', value: gate.replace(/_/g, ' '), accent: gateColor(gate) },
          { label: 'SYMBOLS', value: String(symbols.length) },
          { label: 'LIVE SYMBOLS', value: String(p?.live_symbols?.length ?? 0), accent: (p?.live_symbols?.length ?? 0) > 0 ? SC.error : SC.ok },
          { label: 'EXECUTION', value: p?.trader_execution_enabled ? 'ENABLED' : 'BLOCKED', accent: p?.trader_execution_enabled ? SC.error : SC.warn },
          { label: 'EXCHANGE ACTION', value: p?.exchange_action_taken ? 'YES' : 'NO', accent: p?.exchange_action_taken ? SC.error : SC.ok },
        ].map(({ label, value, accent }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Gate banner */}
      {p && (
        <div style={{ padding: '10px 14px', borderRadius: 6, background: `${gateColor(gate)}15`, border: `1px solid ${gateColor(gate)}44`, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: gateColor(gate), fontFamily: 'var(--font-mono)' }}>GATE: {gate.toUpperCase()}</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>source: {p.live_gate_runtime_source || '—'}</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {allowedTypes.map(t2 => <Chip key={t2} label={t2.replace(/_/g, ' ')} color={SC.info} />)}
          </div>
        </div>
      )}

      <DangerousControlPanel controlIds={meta.dangerousControlIds} />

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map(t2 => (
          <button key={t2} type="button" onClick={() => setTab(t2)} style={{
            padding: '7px 16px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t2 ? 700 : 400, color: tab === t2 ? 'var(--text-primary)' : 'var(--text-muted)',
            borderBottom: tab === t2 ? '2px solid var(--admin-accent)' : '2px solid transparent',
          }}>{t2}</button>
        ))}
      </div>

      {tab === 'Orchestrator' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Pipeline Status</div>
            {loading && !p ? <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div> : p ? (
              [
                ['Schema', p.schema_version || '—'],
                ['Generated', p.generated_utc || '—'],
                ['Live Gate', p.live_gate || '—'],
                ['Gate Source', p.live_gate_runtime_source || '—'],
                ['Control Stream', p.control_stream_key || '—'],
                ['Last Request Key', p.control_last_request_key || '—'],
                ['Execution Enabled', p.trader_execution_enabled ? 'YES' : 'NO'],
                ['Exchange Action Taken', p.exchange_action_taken ? 'YES' : 'NO'],
              ].map(([label, value]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--line-soft)' }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 }}>{label}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', textAlign: 'right', wordBreak: 'break-all', maxWidth: '65%' }}>{value}</span>
                </div>
              ))
            ) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No pipeline data</div>}
          </div>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Allowed Run Types</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {allowedTypes.length > 0 ? allowedTypes.map(rt => (
                <div key={rt} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', borderRadius: 6, background: `${SC.info}10`, border: `1px solid ${SC.info}33` }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: SC.ok, display: 'inline-block' }} />
                  <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: SC.info }}>{rt.replace(/_/g, ' ')}</span>
                </div>
              )) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No allowed run types</div>}
            </div>
          </div>
          <APlusGatePanel gate={aPlusGate} />
        </div>
      )}

      {tab === 'Symbols' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <input
              value={symFilter}
              onChange={e => setSymFilter(e.target.value)}
              placeholder="Filter symbols…"
              style={{ flex: 1, maxWidth: 240, padding: '6px 10px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-primary)', fontSize: 12, fontFamily: 'var(--font-mono)', outline: 'none' }}
            />
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{filtered.length} / {symbols.length}</span>
          </div>
          {symbols.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
              {filtered.map(sym => (
                <span key={sym} style={{ padding: '3px 8px', borderRadius: 4, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{sym}</span>
              ))}
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No symbols in pipeline</div>
          )}
        </div>
      )}

      {tab === 'Control' && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Pipeline Control</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Pipeline run controls (trainer_cycle, replay, backtest, full_pipeline) are triggered via <span style={{ fontFamily: 'var(--font-mono)', color: SC.info }}>POST /api/v2/pipeline/run</span>. Implement control buttons here after operator approval gate is confirmed.</div>
        </div>
      )}
    </div>
  );
}
