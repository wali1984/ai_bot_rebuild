import { useEffect, useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { EmptyState } from '../../components/ui/EmptyState';
import meta from './meta';
import rbac from './rbac';
import route from './route';

const AUDIT_ENDPOINT = '/api/v2/admin/audit/chain';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

interface AuditEvent {
  id?: string;
  audit_id?: string;
  actor: string;
  action: string;
  resource?: string;
  result: string;
  reason: string | null;
  evidence: string | null;
  timestamp: string;
}

interface AuditData {
  events?: AuditEvent[];
  entries?: AuditEvent[];
  total?: number;
  chain_length?: number;
  last_entry_at?: string | null;
  generated_at?: string | null;
  immutable?: boolean;
}

function resultColor(r: string): string {
  if (r.toLowerCase() === 'allow' || r.toLowerCase() === 'success') return 'var(--buy)';
  if (r.toLowerCase() === 'deny' || r.toLowerCase() === 'blocked' || r.toLowerCase() === 'fail') return 'var(--sell)';
  return 'var(--text-secondary)';
}

export default function AuditLedgerPage(): JSX.Element {
  const [actorFilter, setActorFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');

  const { envelope, loading, error, refetch } = useRealtimeResource<AuditData>({
    url: AUDIT_ENDPOINT,
    source: AUDIT_ENDPOINT,
    source_type: 'repository',
    pollIntervalMs: 30_000,
    staleThresholdMs: 120_000,
    mode: 'read_only',
  });

  const data = envelope.data;
  const allEvents = data?.events ?? data?.entries ?? [];
  const eventTotal = data?.total ?? data?.chain_length ?? allEvents.length;
  const immutable = data?.immutable ?? true;
  const filtered = allEvents.filter((e) => {
    if (actorFilter && !e.actor.toLowerCase().includes(actorFilter.toLowerCase())) return false;
    if (actionFilter && !e.action.toLowerCase().includes(actionFilter.toLowerCase())) return false;
    return true;
  });

  return (
    <div
      data-testid="page-audit-ledger"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 64 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Audit Ledger</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Immutable audit · Actor · Action · Reason · Result · Evidence · {eventTotal} events
              {immutable && <span style={{ marginLeft: 8, color: 'var(--buy)' }}>✓ Immutable</span>}
            </p>
            <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Read-only source: {AUDIT_ENDPOINT}. High-privilege admin audit remains at /admin/audit.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input
            placeholder="Filter by actor…"
            value={actorFilter}
            onChange={(e) => setActorFilter(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 12, outline: 'none', width: 180 }}
          />
          <input
            placeholder="Filter by action…"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 12, outline: 'none', width: 180 }}
          />
        </div>
      </div>

      {loading && !data && <div style={{ padding: 24 }}><LoadingSkeleton rows={8} /></div>}
      {!loading && error && !data && (
        <div style={{ padding: 24 }}>
          <EmptyState title="Audit ledger unavailable" message={`Audit data source error: ${error}. No records fabricated.`} />
        </div>
      )}
      {!loading && !error && filtered.length === 0 && (
        <div style={{ padding: 24 }}>
          <EmptyState title="No audit events" message={actorFilter || actionFilter ? 'No events match these filters.' : 'Audit chain is reachable and empty. No records fabricated.'} />
        </div>
      )}

      {filtered.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg-elevated)' }}>
                {['Timestamp', 'Actor', 'Action', 'Resource', 'Result', 'Reason', 'Evidence'].map((h) => (
                  <th key={h} style={{ padding: '10px 12px', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((ev, i) => (
                <tr key={ev.id ?? ev.audit_id ?? `${ev.timestamp}:${ev.action}:${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                  <td style={{ padding: '8px 12px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{new Date(ev.timestamp).toLocaleString()}</td>
                  <td style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--text-secondary)' }}>{ev.actor}</td>
                  <td style={{ padding: '8px 12px', fontWeight: 600 }}>{ev.action}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{ev.resource ?? ev.audit_id ?? 'audit-chain'}</td>
                  <td style={{ padding: '8px 12px', fontWeight: 700, color: resultColor(ev.result) }}>{ev.result.toUpperCase()}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-muted)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.reason ?? '—'}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-muted)', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.evidence ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--border)', marginTop: 8 }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Immutable audit ledger — read-only authenticated view. Source: {envelope.source ?? AUDIT_ENDPOINT}
        </p>
      </div>
    </div>
  );
}
