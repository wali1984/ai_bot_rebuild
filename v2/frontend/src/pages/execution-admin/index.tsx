import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface ExecFill {
  order_id: string;
  symbol: string;
  side: string;
  action: string;
  result: string;
  reason: string;
  live_blocked: boolean;
  timestamp: string;
  confidence: number | null;
}

interface ExecFillsData {
  generated_at: string;
  mode: string;
  gate: string;
  orders_24h: number;
  fills_24h: number;
  rejects_24h: number;
  avg_fill_latency_ms: number | null;
  avg_slippage_pct: number | null;
  fills: ExecFill[];
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md, 10px)', padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

export default function ExecutionAdminPage(): JSX.Element {
  const fills = useRealtimeResource<ExecFillsData>({
    url: '/api/v2/admin/execution/fills', source: '/api/v2/admin/execution/fills',
    source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 60_000, mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const d = fills.envelope.data;
  const rows = (d?.fills ?? []).filter((f) => f.symbol && f.symbol !== '?');

  return (
    <div data-testid="page-execution-admin" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Execution Admin</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
          Paper execution pipeline · order flow · gate state · live is BLOCKED
        </p>
      </div>

      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
        <KV label="Mode" value={d?.mode?.toUpperCase() ?? '—'} color="var(--paper, #8FD3FF)" />
        <KV label="Gate" value={d?.gate ?? '—'} color={d?.gate === 'BLOCKED' ? 'var(--sell)' : 'var(--buy)'} />
        <KV label="Orders 24h" value={String(d?.orders_24h ?? '—')} />
        <KV label="Fills 24h" value={String(d?.fills_24h ?? '—')} color="var(--buy)" />
        <KV label="Rejects 24h" value={String(d?.rejects_24h ?? '—')} color={d?.rejects_24h ? 'var(--warn)' : 'var(--text-muted)'} />
        <KV label="Avg fill latency" value={d?.avg_fill_latency_ms != null ? `${d.avg_fill_latency_ms.toFixed(0)}ms` : 'no fills yet'} />
        <KV label="Avg slippage" value={d?.avg_slippage_pct != null ? `${d.avg_slippage_pct.toFixed(3)}%` : 'no fills yet'} />
      </div>

      <div style={{ padding: '20px 24px 0' }}>
        <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
          Recent Order Decisions ({rows.length})
        </h2>
        {fills.loading && !d ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Connecting execution stream…</p>
        ) : rows.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No paper order decisions recorded in the last 24h window.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-elevated)' }}>
                  {['Order', 'Symbol', 'Side', 'Confidence', 'Live blocked', 'Reason'].map((h) => (
                    <th key={h} style={{ padding: '8px 12px', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((f, i) => (
                  <tr key={`${f.order_id}-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                    <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 10, overflowWrap: 'anywhere', maxWidth: 260 }}>{f.order_id}</td>
                    <td style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--text-primary)' }}>{f.symbol}</td>
                    <td style={{ padding: '8px 12px', fontWeight: 700, color: f.side?.toLowerCase() === 'long' ? 'var(--buy)' : f.side?.toLowerCase() === 'short' ? 'var(--sell)' : 'var(--text-muted)' }}>
                      {f.side?.toUpperCase() ?? '—'}
                    </td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{f.confidence != null ? `${(f.confidence * 100).toFixed(1)}%` : '—'}</td>
                    <td style={{ padding: '8px 12px', fontWeight: 700, color: f.live_blocked ? 'var(--sell)' : 'var(--buy)' }}>{f.live_blocked ? 'BLOCKED' : 'open'}</td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{f.reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
