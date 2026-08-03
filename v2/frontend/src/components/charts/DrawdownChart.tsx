import { useMemo } from 'react';

interface DrawdownPoint {
  ts: string;
  drawdown: number; // negative pct, e.g. -0.15 = -15%
}

interface DrawdownChartProps {
  data: DrawdownPoint[];
  width?: number;
  height?: number;
  maxDrawdownThreshold?: number; // e.g. -0.2 = -20%
  className?: string;
}

export function DrawdownChart({
  data,
  width = 600,
  height = 120,
  maxDrawdownThreshold = -0.15,
  className,
}: DrawdownChartProps): JSX.Element {
  const { areaPath, minVal, maxVal } = useMemo(() => {
    if (data.length === 0) return { areaPath: '', minVal: 0, maxVal: 0 };
    const values = data.map((d) => d.drawdown);
    const minV = Math.min(...values);
    const maxV = 0;
    const range = maxV - minV || 0.01;
    const pad = range * 0.05;
    const lo = minV - pad;
    const hi = maxV + pad * 0.5;
    const scaleY = (v: number) => ((hi - v) / (hi - lo)) * height;
    const scaleX = (i: number) => (i / Math.max(data.length - 1, 1)) * width;

    const pathParts = data.map((d, i) => {
      const x = scaleX(i).toFixed(2);
      const y = scaleY(d.drawdown).toFixed(2);
      return `${i === 0 ? 'M' : 'L'}${x},${y}`;
    });
    const last = data[data.length - 1];
    const first = data[0];
    const zeroY = scaleY(0).toFixed(2);
    const area = [
      ...pathParts,
      `L${scaleX(data.length - 1).toFixed(2)},${zeroY}`,
      `L${scaleX(0).toFixed(2)},${zeroY}`,
      'Z',
    ].join(' ');

    return { areaPath: area, minVal: minV, maxVal: 0, first, last };
  }, [data, width, height]);

  const thresholdY = maxDrawdownThreshold < 0
    ? ((0 - maxDrawdownThreshold) / (0 - minVal || 0.01)) * height
    : 0;

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
        data-testid="drawdown-chart-empty"
      >
        No drawdown data
      </div>
    );
  }

  return (
    <div
      className={className}
      data-testid="drawdown-chart"
      style={{ position: 'relative' }}
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        style={{ display: 'block', background: 'var(--chart-bg)', borderRadius: 'var(--radius-sm)' }}
        aria-label="Drawdown chart"
      >
        <defs>
          <linearGradient id="drawdown-gradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--sell)" stopOpacity={0.38} />
            <stop offset="100%" stopColor="var(--sell)" stopOpacity={0.04} />
          </linearGradient>
        </defs>

        {/* Zero line */}
        <line x1={0} y1={4} x2={width} y2={4} stroke="var(--chart-grid)" strokeWidth={1} />

        {/* Threshold line */}
        {thresholdY > 0 && (
          <line
            x1={0} y1={thresholdY} x2={width} y2={thresholdY}
            stroke="var(--warn)"
            strokeWidth={1}
            strokeDasharray="6 3"
            opacity={0.7}
          />
        )}

        {/* Drawdown fill */}
        <path d={areaPath} fill="url(#drawdown-gradient)" />

        {/* Min label */}
        <text
          x={4} y={height - 4}
          fill="var(--sell)"
          fontSize={9}
          fontFamily="var(--font-mono)"
        >
          {(minVal * 100).toFixed(1)}%
        </text>
      </svg>
    </div>
  );
}
