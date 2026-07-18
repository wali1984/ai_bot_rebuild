import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';

const LOGS_ENDPOINT = '/api/v2/admin/logs/recent';
const TABS = ['Events', 'Errors'] as const;
type Tab = typeof TABS[number];
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

interface LogEntry { id: string; level: string; service: string; message: string; timestamp: string; meta?: Record<string, unknown>; }
interface LogsPayload { entries?: LogEntry[]; error_count_1h?: number; warn_count_1h?: number; }

function levelColor(level: string) {
  switch (level.toLowerCase()) {
    case 'error': return SC.error;
    case 'warn': case 'warning': return SC.warn;
    case 'info': return SC.info;
    default: return SC.unknown;
  }
}

export default function AdminLogsPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Events');
  const { envelope, loading } = useRealtimeResource<LogsPayload>({ url: LOGS_ENDPOINT, source: 'admin-logs', pollIntervalMs: 10_000 });
  const data = envelope.data;
  const entries = data?.entries || [];
  const errors = entries.filter(e => e.level.toLowerCase() === 'error');
  const shown = tab === 'Errors' ? errors : entries;

  return (
    <div data-testid="admin-logs-page" style={{ display: 'flex', flexDirection: 'column', gap: 18, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Logs</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Structured event log stream and error aggregation</p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {[
          { label: 'ERRORS 1H', value: String(data?.error_count_1h ?? errors.length), accent: (data?.error_count_1h ?? errors.length) > 0 ? SC.error : SC.ok },
          { label: 'WARNINGS 1H', value: String(data?.warn_count_1h ?? '—'), accent: (data?.warn_count_1h ?? 0) > 10 ? SC.warn : undefined },
          { label: 'TOTAL EVENTS', value: String(entries.length) },
        ].map(({ label, value, accent }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map(t => (
          <button key={t} type="button" onClick={() => setTab(t)} style={{
            padding: '7px 16px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t ? 700 : 400, color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)',
            borderBottom: tab === t ? '2px solid var(--admin-accent)' : '2px solid transparent',
          }}>{t}</button>
        ))}
      </div>

      {loading && !data ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading logs…</div>
      ) : shown.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {shown.slice(0, 50).map((entry, i) => (
            <div key={entry.id || i} style={{ display: 'grid', gridTemplateColumns: 'auto auto 1fr', gap: 10, alignItems: 'baseline', padding: '7px 12px', borderRadius: 5, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: levelColor(entry.level), fontWeight: 700, minWidth: 36 }}>{entry.level.toUpperCase()}</span>
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', minWidth: 80 }}>{entry.service || '—'}</span>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
                <span style={{ fontSize: 12, color: levelColor(entry.level) === SC.error ? SC.error : 'var(--text-primary)', wordBreak: 'break-word' }}>{entry.message}</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', flexShrink: 0 }}>{relativeAge(entry.timestamp)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ padding: '12px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-muted)', fontSize: 12 }}>
          {tab === 'Errors' ? (
            <span style={{ color: SC.ok }}>✓ No errors in log buffer</span>
          ) : (
            <>No log entries. Source: <span style={{ fontFamily: 'var(--font-mono)', color: SC.info }}>{LOGS_ENDPOINT}</span></>
          )}
        </div>
      )}
    </div>
  );
}
