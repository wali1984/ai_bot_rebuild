import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';

const EXCHANGES_ENDPOINT = '/api/v2/admin/exchanges/status';
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

function connColor(s?: string | null) {
  const v = (s || '').toLowerCase();
  if (v.includes('ok') || v.includes('active') || v.includes('live')) return SC.ok;
  if (v.includes('fallback') || v.includes('stale') || v.includes('warn')) return SC.warn;
  if (v.includes('error') || v.includes('disconnect')) return SC.error;
  return SC.unknown;
}

interface Exchange {
  id: string; name: string; status: string; connectivity: string;
  credential_status: string; live_trading_enabled: boolean; read_only: boolean;
  last_frame_at: string | null; lag_ms: number | null; mode: string;
  account_type: string; stream_stale: boolean; stream_source: string;
}
interface ExchangesPayload {
  exchanges?: Exchange[]; generated_at?: string;
  total?: number; connected?: number; stream_source?: string;
  stream_stale?: boolean; stream_last_at?: string | null; stream_lag_ms?: number | null;
}

export default function AdminExchangesPage(): JSX.Element {
  const { envelope, loading } = useRealtimeResource<ExchangesPayload>({ url: EXCHANGES_ENDPOINT, source: 'admin-exchanges', pollIntervalMs: 20_000 });
  const data = envelope.data;
  const exchanges = data?.exchanges || [];

  return (
    <div data-testid="admin-exchanges-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Exchanges</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Exchange connectivity, REST/WS status, rate limits, and market stream</p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      {/* Stat tiles */}
      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
          {[
            { label: 'EXCHANGES', value: String(data.total ?? exchanges.length) },
            { label: 'CONNECTED', value: String(data.connected ?? 0), accent: (data.connected ?? 0) > 0 ? SC.ok : SC.warn },
            { label: 'STREAM', value: data.stream_stale ? 'STALE' : 'LIVE', accent: data.stream_stale ? SC.warn : SC.ok },
            { label: 'STREAM LAG', value: data.stream_lag_ms != null ? `${Math.round(data.stream_lag_ms / 1000)}s` : '—' },
          ].map(({ label, value, accent }) => (
            <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
              <span style={{ fontSize: 15, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Stream banner */}
      {data && (
        <div style={{
          padding: '10px 14px', borderRadius: 6,
          background: data.stream_stale ? `${SC.warn}12` : `${SC.ok}12`,
          border: `1px solid ${data.stream_stale ? SC.warn : SC.ok}44`,
          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: data.stream_stale ? SC.warn : SC.ok, display: 'inline-block' }} />
          <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', fontWeight: 700, color: data.stream_stale ? SC.warn : SC.ok }}>
            MARKET STREAM: {data.stream_stale ? 'STALE' : 'LIVE'}
          </span>
          {data.stream_source !== undefined && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>source: {String(data.stream_source ?? 'unknown')}</span>}
          {data.stream_last_at && <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>last frame {relativeAge(data.stream_last_at)}</span>}
        </div>
      )}

      {loading && !data ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading exchange status…</div>
      ) : exchanges.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 12 }}>
          {exchanges.map(ex => (
            <div key={ex.id} data-testid={`exchange-card-${ex.id}`} style={{ padding: 16, borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>{ex.name}</div>
                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginTop: 2 }}>{ex.id} · {ex.account_type}</div>
                </div>
                <span style={{ padding: '2px 8px', borderRadius: 4, background: `${connColor(ex.status)}20`, border: `1px solid ${connColor(ex.status)}44`, color: connColor(ex.status), fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                  {(ex.status || 'unknown').toUpperCase()}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                {[
                  { label: 'Connectivity', value: ex.connectivity, c: connColor(ex.connectivity) },
                  { label: 'Mode', value: ex.mode || '—', c: ex.mode === 'live' ? SC.error : SC.info },
                  { label: 'Read Only', value: ex.read_only ? 'YES' : 'NO', c: ex.read_only ? SC.ok : SC.warn },
                  { label: 'Live Trading', value: ex.live_trading_enabled ? 'ENABLED' : 'OFF', c: ex.live_trading_enabled ? SC.error : SC.ok },
                  { label: 'Stream', value: ex.stream_stale ? 'STALE' : 'LIVE', c: ex.stream_stale ? SC.warn : SC.ok },
                  { label: 'Lag', value: ex.lag_ms != null ? `${Math.round(ex.lag_ms / 1000)}s` : '—', c: SC.unknown },
                ].map(({ label, value, c }) => (
                  <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', fontFamily: 'var(--font-mono)' }}>{label}</span>
                    <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: c, fontWeight: 600 }}>{value}</span>
                  </div>
                ))}
              </div>
              <div style={{ paddingTop: 6, borderTop: '1px solid var(--line-soft)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Credentials:</span>
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: ex.credential_status === 'ok' ? SC.ok : SC.warn }}>
                  {ex.credential_status || 'pending'}
                </span>
                {ex.last_frame_at && (
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)' }}>last frame {relativeAge(ex.last_frame_at)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ padding: '14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>No exchange data</div>
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: SC.info }}>{EXCHANGES_ENDPOINT}</div>
        </div>
      )}
    </div>
  );
}
