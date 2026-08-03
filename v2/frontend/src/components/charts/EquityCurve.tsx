import { useMemo } from 'react';

interface EquityCurvePoint {
  ts: string;
  equity: number;
  pnl?: number;
}

interface EquityCurveProps {
  data: EquityCurvePoint[];
  width?: number;
  height?: number;
  showPnL?: boolean;
  className?: string;
}

function buildPath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return '';
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');
}

function buildArea(points: Array<{ x: number; y: number }>, height: number): string {
  if (points.length === 0) return '';
  const linePath = buildPath(points);
  const last = points[points.length - 1];
  const first = points[0];
  return `${linePath} L${last.x.toFixed(2)},${height} L${first.x.toFixed(2)},${height} Z`;
}

export function EquityCurve({
  data,
  width = 600,
  height = 200,
  showPnL = false,
  className,
}: EquityCurveProps): JSX.Element {
  const { points, minVal, maxVal, isUp } = useMemo(() => {
    if (data.length === 0) return { points: [], minVal: 0, maxVal: 1, isUp: true };
    const values = data.map((d) => d.equity);
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const range = maxV - minV || 1;
    const pad = range * 0.08;
    const lo = minV - pad;
    const hi = maxV + pad;
    const pts = data.map((d, i) => ({
      x: (i / Math.max(data.length - 1, 1)) * width,
      y: ((hi - d.equity) / (hi - lo)) * height,
    }));
    return { points: pts, minVal: lo, maxVal: hi, isUp: (data[data.length - 1]?.equity ?? 0) >= (data[0]?.equity ?? 0) };
  }, [data, width, height]);

  const color = isUp ? 'var(--buy)' : 'var(--sell)';
  const areaColor = isUp ? 'var(--buy-bg)' : 'var(--sell-bg)';

  if (data.length === 0) {
    return (
      <div
        className={className}
        style={{
          width,
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--chart-bg)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--text-muted)',
          fontSize: 12,
          fontFamily: 'var(--font-mono)',
        }}
        data-testid="equity-curve-empty"
      >
        No equity data
      </div>
    );
  }

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const val = minVal + (maxVal - minVal) * (1 - ratio);
    const y = ratio * height;
    return { val, y };
  });

  const linePath = buildPath(points);
  const areaPath = buildArea(points, height);

  return (
    <div
      className={className}
      data-testid="equity-curve"
      style={{ position: 'relative', fontFamily: 'var(--font-mono)' }}
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        style={{ display: 'block', background: 'var(--chart-bg)', borderRadius: 'var(--radius-sm)' }}
        aria-label="Equity curve chart"
      >
        {/* Grid */}
        {gridLines.map(({ val, y }) => (
          <g key={y}>
            <line
              x1={0} y1={y} x2={width} y2={y}
              stroke="var(--chart-grid)"
              strokeWidth={1}
              strokeDasharray="4 4"
            />
            <text
              x={4} y={y - 3}
              fill="var(--text-muted)"
              fontSize={9}
              fontFamily="var(--font-mono)"
            >
              {val >= 1000 ? `${(val / 1000).toFixed(1)}k` : val.toFixed(0)}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <defs>
          <linearGradient id="equity-area-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={isUp ? 'var(--buy)' : 'var(--sell)'} stopOpacity={0.22} />
            <stop offset="100%" stopColor={isUp ? 'var(--buy)' : 'var(--sell)'} stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#equity-area-gradient)" />

        {/* Equity line */}
        <path d={linePath} stroke={color} strokeWidth={1.5} fill="none" />
      </svg>

      {/* Last value badge */}
      {data.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: 6,
            right: 8,
            padding: '2px 8px',
            borderRadius: 'var(--radius-sm)',
            background: 'color-mix(in oklch, var(--bg-panel) 80%, transparent)',
            border: `1px solid ${color}`,
            color,
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          {data[data.length - 1]?.equity?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      )}
    </div>
  );
}
