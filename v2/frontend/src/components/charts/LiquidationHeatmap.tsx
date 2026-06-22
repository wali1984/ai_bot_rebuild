interface LiquidationLevel {
  price: number;
  longLiquidations: number; // USD value
  shortLiquidations: number; // USD value
}

interface LiquidationHeatmapProps {
  data: LiquidationLevel[];
  currentPrice?: number;
  width?: number;
  height?: number;
  priceLabel?: string;
  className?: string;
}

function formatUSD(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

export function LiquidationHeatmap({
  data,
  currentPrice,
  width = 600,
  height = 240,
  priceLabel = 'USDT',
  className,
}: LiquidationHeatmapProps): JSX.Element {
  if (data.length === 0) {
    return (
      <div
        className={className}
        data-testid="liquidation-heatmap-empty"
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
          border: '1px solid var(--border)',
        }}
      >
        Liquidation stream connecting
      </div>
    );
  }

  const prices = data.map((d) => d.price);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const priceRange = maxPrice - minPrice || 1;

  const maxLiq = Math.max(
    ...data.map((d) => Math.max(d.longLiquidations, d.shortLiquidations)),
    1,
  );

  const barWidth = Math.max(2, (width / data.length) * 0.45);
  const labelWidth = 60;
  const chartWidth = width - labelWidth;
  const barMaxHeight = height - 30;

  return (
    <div
      className={className}
      data-testid="liquidation-heatmap"
      style={{ fontFamily: 'var(--font-mono)', userSelect: 'none' }}
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        style={{ display: 'block', background: 'var(--chart-bg)', borderRadius: 'var(--radius-sm)', overflow: 'visible' }}
        aria-label="Liquidation heatmap"
      >
        {/* Price axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const price = minPrice + priceRange * ratio;
          const y = height - 15 - ratio * barMaxHeight;
          return (
            <g key={ratio}>
              <line x1={labelWidth} y1={y} x2={width} y2={y} stroke="var(--chart-grid)" strokeWidth={0.5} />
              <text x={labelWidth - 4} y={y + 4} fill="var(--text-muted)" fontSize={8} textAnchor="end">
                {price >= 1000 ? price.toFixed(0) : price.toFixed(2)}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {data.map((level, i) => {
          const priceRatio = (level.price - minPrice) / priceRange;
          const y = height - 15 - priceRatio * barMaxHeight;
          const longH = (level.longLiquidations / maxLiq) * barMaxHeight * 0.45;
          const shortH = (level.shortLiquidations / maxLiq) * barMaxHeight * 0.45;
          const xCenter = labelWidth + (i / (data.length - 1)) * chartWidth;

          return (
            <g key={i}>
              {/* Long (green) bars — left side */}
              {longH > 0 && (
                <rect
                  x={xCenter - barWidth}
                  y={y - longH / 2}
                  width={barWidth}
                  height={Math.max(longH, 1)}
                  fill="var(--buy)"
                  opacity={0.7}
                />
              )}
              {/* Short (red) bars — right side */}
              {shortH > 0 && (
                <rect
                  x={xCenter}
                  y={y - shortH / 2}
                  width={barWidth}
                  height={Math.max(shortH, 1)}
                  fill="var(--sell)"
                  opacity={0.7}
                />
              )}
            </g>
          );
        })}

        {/* Current price line */}
        {currentPrice !== undefined && (
          (() => {
            const ratio = (currentPrice - minPrice) / priceRange;
            const y = height - 15 - ratio * barMaxHeight;
            return (
              <g>
                <line x1={labelWidth} y1={y} x2={width} y2={y} stroke="var(--accent)" strokeWidth={1.5} />
                <text x={width - 4} y={y - 3} fill="var(--accent)" fontSize={9} textAnchor="end">
                  {currentPrice.toLocaleString()} {priceLabel}
                </text>
              </g>
            );
          })()
        )}

        {/* Legend */}
        <g transform={`translate(${labelWidth + 4}, 8)`}>
          <rect x={0} y={0} width={8} height={8} fill="var(--buy)" opacity={0.8} rx={1} />
          <text x={11} y={7.5} fill="var(--text-secondary)" fontSize={9}>Long liq</text>
          <rect x={60} y={0} width={8} height={8} fill="var(--sell)" opacity={0.8} rx={1} />
          <text x={71} y={7.5} fill="var(--text-secondary)" fontSize={9}>Short liq</text>
        </g>
      </svg>

      {/* Max value note */}
      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, textAlign: 'right' }}>
        Max: {formatUSD(maxLiq)} at single level
      </div>
    </div>
  );
}
