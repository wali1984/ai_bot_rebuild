interface LongShortPoint {
  ts: string;
  longPct: number;   // 0-100
  shortPct: number;  // 0-100
}

interface LongShortChartProps {
  data: LongShortPoint[];
  currentLong?: number;
  currentShort?: number;
  width?: number;
  height?: number;
  className?: string;
}

export function LongShortChart({
  data,
  currentLong,
  currentShort,
  width = 600,
  height = 120,
  className,
}: LongShortChartProps): JSX.Element {
  const latestLong = currentLong ?? data[data.length - 1]?.longPct ?? 50;
  const latestShort = currentShort ?? data[data.length - 1]?.shortPct ?? 50;

  if (data.length === 0) {
    return (
      <div
        className={className}
        data-testid="long-short-chart-empty"
        style={{
          width,
          height: 60,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--chart-bg)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--text-muted)',
          fontSize: 12,
          fontFamily: 'var(--font-mono)',
          border: '1px solid var(--border)',
        }}
      >
        No long/short data
      </div>
    );
  }

  // Stacked area chart — long pct as filled area from bottom
  const n = data.length;
  const longPoints = data.map((d, i) => ({
    x: (i / Math.max(n - 1, 1)) * width,
    y: ((100 - d.longPct) / 100) * height,
  }));

  const longLinePath = longPoints
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(' ');
  const longAreaPath = `${longLinePath} L${width},${height} L0,${height} Z`;

  return (
    <div
      className={className}
      data-testid="long-short-chart"
      style={{ fontFamily: 'var(--font-mono)' }}
    >
      {/* Current ratio bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 6,
          fontSize: 12,
          color: 'var(--text-secondary)',
        }}
      >
        <span style={{ color: 'var(--buy)', fontWeight: 700 }}>L {latestLong.toFixed(1)}%</span>
        <div style={{ flex: 1, height: 8, borderRadius: 4, overflow: 'hidden', background: 'var(--sell-bg)' }}>
          <div
            style={{
              width: `${latestLong}%`,
              height: '100%',
              background: 'var(--buy)',
              borderRadius: 4,
              transition: 'width 0.4s ease',
            }}
          />
        </div>
        <span style={{ color: 'var(--sell)', fontWeight: 700 }}>S {latestShort.toFixed(1)}%</span>
      </div>

      {/* Area chart */}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        style={{ display: 'block', background: 'var(--chart-bg)', borderRadius: 'var(--radius-sm)' }}
        aria-label="Long/Short ratio chart"
      >
        <defs>
          <linearGradient id="long-gradient" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor="var(--buy)" stopOpacity={0.08} />
            <stop offset="100%" stopColor="var(--buy)" stopOpacity={0.3} />
          </linearGradient>
        </defs>

        {/* 50% reference line */}
        <line
          x1={0} y1={height / 2} x2={width} y2={height / 2}
          stroke="var(--chart-grid)"
          strokeWidth={1}
          strokeDasharray="4 4"
        />

        {/* Short area (full background) */}
        <rect x={0} y={0} width={width} height={height} fill="var(--sell-bg)" opacity={0.4} />

        {/* Long area */}
        <path d={longAreaPath} fill="url(#long-gradient)" />
        <path d={longLinePath} stroke="var(--buy)" strokeWidth={1.5} fill="none" />

        {/* Labels */}
        <text x={4} y={14} fill="var(--buy)" fontSize={10} fontFamily="var(--font-mono)">Long</text>
        <text x={4} y={height - 6} fill="var(--sell)" fontSize={10} fontFamily="var(--font-mono)">Short</text>
      </svg>
    </div>
  );
}
