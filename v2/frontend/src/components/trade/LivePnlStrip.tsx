/**
 * Live PnL trend strip for the trade terminal.
 *
 * Accumulates a client-side rolling series from the realtime paper activity
 * stream (same source as the account strip, so the numbers always agree)
 * and renders total / realized / unrealized PnL as a compact sparkline with
 * live badges. Pure SVG — no chart library cost in the hot path.
 */
import { useEffect, useRef, useState } from 'react';

interface Props {
  totalPnl: number | null;
  realizedPnl: number | null;
  unrealizedPnl: number | null;
  openNotional: number | null;
  connected: boolean;
}

const MAX_POINTS = 120;

export function LivePnlStrip({ totalPnl, realizedPnl, unrealizedPnl, openNotional, connected }: Props): JSX.Element | null {
  const [series, setSeries] = useState<number[]>([]);
  const lastValue = useRef<number | null>(null);

  useEffect(() => {
    if (totalPnl == null || totalPnl === lastValue.current) return;
    lastValue.current = totalPnl;
    setSeries((prev) => [...prev.slice(-(MAX_POINTS - 1)), totalPnl]);
  }, [totalPnl]);

  if (totalPnl == null) return null;
  const up = totalPnl >= 0;
  const color = up ? 'var(--buy, #21C784)' : 'var(--sell, #FF5D7A)';

  const width = 220;
  const height = 36;
  let path = '';
  if (series.length > 1) {
    const min = Math.min(...series);
    const max = Math.max(...series);
    const span = max - min || 1;
    path = series
      .map((value, index) => {
        const x = (index / (series.length - 1)) * (width - 6) + 3;
        const y = height - 4 - ((value - min) / span) * (height - 8);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }

  const fmt = (v: number | null) => (v == null ? '—' : `${v < 0 ? '-' : '+'}$${Math.abs(v).toFixed(2)}`);

  return (
    <div
      data-testid="live-pnl-strip"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        padding: '8px 16px',
        background: 'var(--bg-panel)',
        borderBottom: '1px solid var(--border)',
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>
          Session PnL
        </span>
        <span style={{ fontSize: 20, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{fmt(totalPnl)}</span>
      </div>

      {series.length > 1 && (
        <svg width={width} height={height} role="img" aria-label="PnL trend" style={{ flexShrink: 0 }}>
          <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          <circle
            cx={width - 3}
            cy={
              height - 4 -
              ((series[series.length - 1] - Math.min(...series)) / (Math.max(...series) - Math.min(...series) || 1)) * (height - 8)
            }
            r={3}
            fill={color}
          />
        </svg>
      )}

      <div style={{ display: 'flex', gap: 14, fontSize: 11, fontFamily: 'var(--font-mono)', flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--text-muted)' }}>
          Realized <strong style={{ color: realizedPnl != null && realizedPnl >= 0 ? 'var(--buy)' : 'var(--sell)' }}>{fmt(realizedPnl)}</strong>
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          Unrealized <strong style={{ color: unrealizedPnl != null && unrealizedPnl >= 0 ? 'var(--buy)' : 'var(--sell)' }}>{fmt(unrealizedPnl)}</strong>
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          Open notional <strong style={{ color: 'var(--text-primary)' }}>{openNotional != null ? `$${openNotional.toFixed(0)}` : '—'}</strong>
        </span>
      </div>

      <span
        style={{
          marginLeft: 'auto',
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.08em',
          color: connected ? 'var(--buy)' : 'var(--warn)',
        }}
      >
        {connected ? '● STREAMING' : '○ FALLBACK'}
      </span>
    </div>
  );
}
