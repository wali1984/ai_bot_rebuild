import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { MissingSourceIncident } from '../../components/data/MissingSourceIncident';
import { AuditResultPanel } from '../../components/controls/AuditResultPanel';
import { relativeAge } from '../../data/adminFieldRegistry';

const AUDIT_ENDPOINT = '/api/v2/admin/audit/chain';

interface AuditEntry {
  audit_id: string;
  actor: string;
  action: string;
  result: 'success' | 'failure' | 'pending';
  timestamp: string;
  reason?: string;
  evidence?: string;
}

interface AuditPayload {
  entries?: AuditEntry[];
  chain_length?: number;
  last_entry_at?: string;
}

export default function AdminAuditPage(): JSX.Element {
  const { envelope, loading, error } = useRealtimeResource<AuditPayload>({ url: AUDIT_ENDPOINT, source: 'admin-audit', pollIntervalMs: 15_000 });
  const data = envelope.data;

  return (
    <div data-testid="admin-audit-page" style={{ display: 'flex', flexDirection: 'column', gap: 20, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>Audit</h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>
            Append-only chain of every governance event and control-action decision.
          </p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      <div
        data-testid="audit-superadmin-notice"
        style={{ padding: '10px 16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 13, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
      >
        SUPERADMIN ONLY — Audit chain is immutable. Every entry is recorded with actor, action, reason, result, and evidence ID.
      </div>

      {data && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ padding: '8px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>Chain Length</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{data.chain_length?.toLocaleString() ?? '—'}</span>
          </div>
          <div style={{ padding: '8px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>Last Entry</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{relativeAge(data.last_entry_at)}</span>
          </div>
        </div>
      )}

      {error && <MissingSourceIncident page="Audit" component="AuditChain" source={AUDIT_ENDPOINT} owner="v2-audit" remediation="Check /api/v2/admin/audit/chain. Verify audit service is running." adminOnly />}

      {!error && (
        loading && !data ? <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading audit chain…</div> :
        !data?.entries?.length ? (
          <MissingSourceIncident page="Audit" component="AuditChainTable" source={AUDIT_ENDPOINT} owner="v2-audit" remediation="No audit entries returned. Wire /api/v2/admin/audit/chain." adminOnly />
        ) : (
          <div data-testid="audit-chain" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.entries.map((e) => (
              <AuditResultPanel
                key={e.audit_id}
                actor={e.actor}
                action={e.action}
                result={e.result}
                timestamp={e.timestamp}
                reason={e.reason}
                evidence={e.evidence}
              />
            ))}
          </div>
        )
      )}
    </div>
  );
}
