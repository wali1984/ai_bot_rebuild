import React from 'react';

interface SparklineProps {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  showArea?: boolean;
}

export const Sparkline: React.FC<SparklineProps> = ({
  data,
  color = 'var(--buy)',
  width = 120,
  height = 40,
  showArea = false,
}) => {
  if (!data || data.length < 2) {
    return (
      <svg
        data-testid="sparkline"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        aria-label="No sparkline data"
      />
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const pad = 2;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * innerW;
    const y = pad + (1 - (v - min) / range) * innerH;
    return [x, y] as [number, number];
  });

  const linePath = points
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(' ');

  const areaPath =
    linePath +
    ` L${points[points.length - 1][0].toFixed(2)},${(pad + innerH).toFixed(2)}` +
    ` L${points[0][0].toFixed(2)},${(pad + innerH).toFixed(2)} Z`;

  return (
    <svg
      data-testid="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-label="Sparkline chart"
      style={{ display: 'block', overflow: 'visible' }}
    >
      {showArea && (
        <defs>
          <linearGradient id="sparkline-area-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
      )}
      {showArea && (
        <path d={areaPath} fill="url(#sparkline-area-grad)" stroke="none" />
      )}
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Last point dot */}
      <circle
        cx={points[points.length - 1][0]}
        cy={points[points.length - 1][1]}
        r="2.5"
        fill={color}
      />
    </svg>
  );
};

export default Sparkline;
