import { useEffect, useState } from 'react';
import { FreshnessBadge } from './FreshnessBadge';
import type { FreshnessStatus } from '../../types/dataContract';

interface StreamStatus {
  name: string;
  status: FreshnessStatus;
  lagMs?: number | null;
}

interface Props {
  streams?: StreamStatus[];
  backendUrl?: string;
  compact?: boolean;
}

export function RealtimeStatusBar({ streams = [], backendUrl, compact = false }: Props) {
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

  useEffect(() => {
    if (!backendUrl) return;
    const check = async () => {
      try {
        const r = await fetch(backendUrl, { signal: AbortSignal.timeout(3000) });
        setBackendUp(r.ok);
      } catch {
        setBackendUp(false);
      }
    };
    void check();
    const id = setInterval(() => void check(), 30_000);
    return () => clearInterval(id);
  }, [backendUrl]);

  const allFresh = streams.every(s => s.status === 'fresh');
  const hasError = streams.some(s => s.status === 'offline' || s.status === 'stale');
  const overallStatus: FreshnessStatus = backendUp === false
    ? 'offline'
    : hasError
    ? 'stale'
    : allFresh
    ? 'fresh'
    : 'delayed';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: compact ? 8 : 16,
        padding: compact ? '4px 12px' : '6px 16px',
        background: 'var(--bg-elevated)',
        borderBottom: '1px solid var(--border)',
        fontSize: 11,
        overflowX: 'auto',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
        <FreshnessBadge status={overallStatus} compact={compact} />
        {!compact && (
          <span style={{ color: 'var(--text-muted)' }}>
            {backendUp === false ? 'API offline' : overallStatus === 'fresh' ? 'Realtime' : 'Degraded'}
          </span>
        )}
      </div>
      {streams.map(s => (
        <div
          key={s.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            flexShrink: 0,
            color: 'var(--text-muted)',
          }}
        >
          <span style={{ fontSize: 10 }}>{s.name}</span>
          <FreshnessBadge status={s.status} lagMs={s.lagMs} compact />
        </div>
      ))}
      <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
        <span
          style={{
            fontSize: 10,
            color: 'var(--text-muted)',
            background: 'var(--bg-hover)',
            padding: '2px 6px',
            borderRadius: 3,
          }}
        >
          EXECUTION RESTRICTED
        </span>
      </div>
    </div>
  );
}
