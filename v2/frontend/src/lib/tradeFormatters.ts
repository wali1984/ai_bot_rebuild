export function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function formatPrice(value: unknown, fallback = '—'): string {
  const n = finite(value);
  if (n === null) return fallback;
  const decimals = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 4 : 8;
  return `$${n.toLocaleString('en-US', {
    minimumFractionDigits: Math.min(2, decimals),
    maximumFractionDigits: decimals,
  })}`;
}

export function formatMoney(value: unknown, fallback = '—'): string {
  const n = finite(value);
  if (n === null) return fallback;
  // Normalize values that would display as "-0.00" (floating point noise or negative zero)
  const safe = Math.abs(n) < 0.005 ? 0 : n;
  return `$${safe.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatNumber(value: unknown, fallback = '—', maximumFractionDigits = 4): string {
  const n = finite(value);
  if (n === null) return fallback;
  return n.toLocaleString('en-US', { maximumFractionDigits });
}

export function formatCompact(value: unknown, fallback = '—'): string {
  const n = finite(value);
  if (n === null) return fallback;
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  return n.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

export function formatPercent(value: unknown, fallback = '—'): string {
  const n = finite(value);
  if (n === null) return fallback;
  const display = Math.abs(n) <= 1 ? n * 100 : n;
  return `${display.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}%`;
}

export function formatBps(value: unknown, fallback = '—'): string {
  const n = finite(value);
  if (n === null) return fallback;
  return `${n.toLocaleString('en-US', { maximumFractionDigits: 2 })} bps`;
}

export function formatAge(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Freshness unavailable';
  if (value < 60) return `${Math.round(value)}s ago`;
  if (value < 3600) return `${Math.floor(value / 60)}m ago`;
  if (value < 86400) return `${Math.floor(value / 3600)}h ago`;
  return `${Math.floor(value / 86400)}d ago`;
}

export function formatTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function signedClass(value: unknown): string {
  const n = finite(value);
  if (n === null || n === 0) return 'is-neutral';
  return n > 0 ? 'is-positive' : 'is-negative';
}
