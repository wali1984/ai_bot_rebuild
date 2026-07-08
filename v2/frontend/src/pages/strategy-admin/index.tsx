import { useMemo } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface RuntimeStatus {
  runtime: string;
  runtime_state: string;
  performance?: {
    profit_factor?: number;
    notional_weighted_expectancy_bps?: number;
    win_rate?: number;
    closed_outcome_count?: number;
    governor_state?: string;
  };
  entry_freeze?: {
    new_entries_allowed?: boolean;
    halt_reasons?: string[];
    allow_close?: boolean;
    allow_reduce?: boolean;
  };
  a_plus_gate?: {
    evaluated_candidates?: number;
    a_plus_candidates?: number;
    rejected_reason_matrix?: Record<string, number>;
  };
}

interface RiskStatus {
  active_profile?: { profile_id?: string; profile_name?: string; fields?: Record<string, unknown> } | null;
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md, 10px)', padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

export default function StrategyAdminPage(): JSX.Element {
  const runtime = useRealtimeResource<RuntimeStatus>({
    url: '/api/v2/paper/runtime-status', source: '/api/v2/paper/runtime-status',
    source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 60_000, mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const risk = useRealtimeResource<RiskStatus>({
    url: '/api/v2/risk/status', source: '/api/v2/risk/status',
    source_type: 'websocket', pollIntervalMs: 15_000, staleThresholdMs: 90_000, mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const d = runtime.envelope.data;
  const perf = d?.performance ?? {};
  const freeze = d?.entry_freeze ?? {};
  const gate = d?.a_plus_gate ?? {};
  const profile = risk.envelope.data?.active_profile ?? null;
  const rejections = useMemo(
    () =>
      Object.entries(gate.rejected_reason_matrix ?? {})
        .sort(([, a], [, b]) => b - a)
        .slice(0, 12),
    [gate.rejected_reason_matrix],
  );
  const maxRejection = rejections.length ? rejections[0][1] : 1;

  return (
    <div data-testid="page-strategy-admin" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Strategy Admin</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
          Active paper strategy state · governor · entry gates · risk profile. Strategy mutations require operator approval and are disabled here.
        </p>
      </div>

      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12 }}>
        <KV label="Runtime" value={d?.runtime ?? '—'} />
        <KV label="State" value={d?.runtime_state?.replace(/_/g, ' ') ?? '—'}
          color={d?.runtime_state?.includes('ONLINE') ? 'var(--buy)' : 'var(--warn)'} />
        <KV label="Governor" value={perf.governor_state ?? '—'} color={perf.governor_state === 'ACTIVE' ? 'var(--buy)' : 'var(--warn)'} />
        <KV label="Profit factor" value={perf.profit_factor != null ? perf.profit_factor.toFixed(2) : '—'}
          color={(perf.profit_factor ?? 0) >= 1 ? 'var(--buy)' : 'var(--sell)'} />
        <KV label="Win rate" value={perf.win_rate != null ? `${(perf.win_rate * 100).toFixed(1)}%` : '—'}
          color={(perf.win_rate ?? 0) >= 0.5 ? 'var(--buy)' : 'var(--warn)'} />
        <KV label="Expectancy" value={perf.notional_weighted_expectancy_bps != null ? `${(perf.notional_weighted_expectancy_bps / 100).toFixed(2)}%` : '—'}
          color={(perf.notional_weighted_expectancy_bps ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)'} />
        <KV label="Closed outcomes" value={String(perf.closed_outcome_count ?? '—')} />
        <KV label="New entries" value={freeze.new_entries_allowed == null ? '—' : freeze.new_entries_allowed ? 'ALLOWED' : 'FROZEN'}
          color={freeze.new_entries_allowed ? 'var(--buy)' : 'var(--sell)'} />
      </div>

      {(freeze.halt_reasons?.length ?? 0) > 0 && (
        <div style={{ margin: '14px 24px 0', padding: '10px 14px', border: '1px solid var(--warn)', borderRadius: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--warn)' }}>Halt reasons: {freeze.halt_reasons!.join(', ')}</span>
        </div>
      )}

      <div style={{ padding: '20px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px' }}>
          <h2 style={{ margin: '0 0 4px', fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
            A+ Entry Gate — rejection reasons
          </h2>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'var(--text-muted)' }}>
            {gate.evaluated_candidates ?? 0} candidates evaluated · {gate.a_plus_candidates ?? 0} passed A+ quality
          </p>
          {rejections.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 12, margin: 0 }}>No rejection matrix published yet.</p>
          ) : (
            rejections.map(([reason, count]) => (
              <div key={reason} style={{ marginBottom: 7 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
                  <span style={{ color: 'var(--text-muted)' }}>{reason.replace(/_/g, ' ')}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{count}</span>
                </div>
                <div style={{ height: 5, borderRadius: 3, background: 'var(--bg-elevated)' }}>
                  <div style={{ width: `${(count / maxRejection) * 100}%`, height: 5, borderRadius: 3, background: '#CC7D22' }} />
                </div>
              </div>
            ))
          )}
        </div>

        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px' }}>
          <h2 style={{ margin: '0 0 4px', fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
            Active Risk Profile
          </h2>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'var(--text-muted)' }}>
            {profile?.profile_id ?? 'profile not published'} · enforced by the risk gateway; the strategy cannot override it
          </p>
          {profile?.fields ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 16px' }}>
              {Object.entries(profile.fields)
                .filter(([, v]) => typeof v === 'number' || typeof v === 'boolean')
                .map(([key, value]) => (
                  <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, borderBottom: '1px solid var(--border)', padding: '4px 0' }}>
                    <span style={{ color: 'var(--text-muted)' }}>{key.replace(/_/g, ' ')}</span>
                    <span style={{ color: typeof value === 'boolean' ? (value ? 'var(--sell)' : 'var(--buy)') : 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                      {String(value)}
                    </span>
                  </div>
                ))}
            </div>
          ) : (
            <p style={{ color: 'var(--sell)', fontSize: 12, margin: 0 }}>Risk profile missing from Redis — check risk gateway loop.</p>
          )}
        </div>
      </div>

      <div style={{ margin: '20px 24px 0', padding: '12px 16px', border: '1px solid var(--sell)', borderRadius: 8, background: 'color-mix(in oklch, var(--sell) 6%, transparent)' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--sell)' }}>
          STRATEGY MUTATIONS BLOCKED — enable/disable, leverage, and exposure changes require explicit human approval through the operator gate. This page is read-only by design.
        </span>
      </div>
    </div>
  );
}
