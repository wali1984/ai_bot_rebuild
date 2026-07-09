export interface HealthTone {
  bg: string;
  color: string;
  label: string;
}

export function healthStatusTone(status: string | null | undefined): HealthTone {
  const normalized = (status ?? '').trim().toLowerCase();
  if (['ok', 'healthy', 'ready', 'live', 'current', 'active'].includes(normalized)) {
    return {
      bg: 'color-mix(in oklch, var(--buy,#10b981) 14%, transparent)',
      color: 'var(--buy,#10b981)',
      label: 'OK',
    };
  }
  if (['partial', 'degraded', 'warn', 'warning', 'gray', 'configured_no_watchlist'].includes(normalized)) {
    return {
      bg: 'color-mix(in oklch, #f59e0b 14%, transparent)',
      color: '#f59e0b',
      label: normalized === 'degraded' ? 'DEGRADED' : 'PARTIAL',
    };
  }
  if (['pending', 'building', 'connecting', 'configuring'].includes(normalized)) {
    return {
      bg: 'color-mix(in oklch, var(--text-muted) 14%, transparent)',
      color: 'var(--text-muted)',
      label: 'PENDING',
    };
  }
  if (['error', 'offline', 'failed', 'unavailable'].includes(normalized)) {
    return {
      bg: 'color-mix(in oklch, var(--sell,#ef4444) 14%, transparent)',
      color: 'var(--sell,#ef4444)',
      label: 'ERROR',
    };
  }
  return {
    bg: 'color-mix(in oklch, var(--text-muted) 14%, transparent)',
    color: 'var(--text-muted)',
    label: normalized ? normalized.replace(/_/g, ' ').toUpperCase() : 'UNKNOWN',
  };
}
