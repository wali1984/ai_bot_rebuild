import type { CSSProperties } from 'react';
import { metricDataAttributes, type CanonicalMetric } from '../../selectors/accountSelectors';
import '../../styles/trader.css';

const usdFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function precision(metric: CanonicalMetric): number {
  return metric.definition?.decimalPrecision ?? 2;
}

function formatNumber(value: number, digits: number): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercentValue(value: number, digits: number): string {
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(digits)}%`;
}

function formatAgeMs(value: number): string {
  if (value < 1_000) return `${Math.max(0, Math.round(value))}ms`;
  if (value < 60_000) return `${(value / 1_000).toFixed(1)}s`;
  return `${Math.floor(value / 60_000)}m`;
}

export function canonicalMetricDisplay(metric: CanonicalMetric, emptyText = 'Source offline'): string {
  const value = metric.value;
  if (value === null || value === undefined || value === '') {
    if (metric.quality === 'invalid') return 'Data validation error';
    if (metric.quality === 'missing' || metric.sourceType === 'unavailable') return emptyText;
    return 'No records for this period';
  }

  const formatter = metric.definition?.displayFormatter;
  const num = finiteNumber(value);
  if (formatter === 'usd') return num === null ? String(value) : usdFormatter.format(num);
  if (formatter === 'price') return num === null ? String(value) : formatNumber(num, precision(metric));
  if (formatter === 'quantity') return num === null ? String(value) : formatNumber(num, precision(metric));
  if (formatter === 'percent') return num === null ? String(value) : formatPercentValue(num, precision(metric));
  if (formatter === 'ratio') return num === null ? String(value) : formatNumber(num, precision(metric));
  if (formatter === 'integer') return num === null ? String(value) : Math.round(num).toLocaleString('en-US');
  if (formatter === 'ageMs') return num === null ? String(value) : formatAgeMs(num);
  if (formatter === 'timestamp') {
    const parsed = new Date(String(value));
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
  }
  if (formatter === 'jsonList') {
    if (Array.isArray(value)) return value.length ? value.map((item) => String(item)).join(', ') : 'No records for this period';
    return String(value);
  }
  return String(value);
}

export function CanonicalMetricValue({
  metric,
  className,
  style,
  emptyText,
}: {
  metric: CanonicalMetric;
  className?: string;
  style?: CSSProperties;
  emptyText?: string;
}): JSX.Element {
  return (
    <span
      {...metricDataAttributes(metric)}
      className={className}
      style={style}
      title={`${metric.source} | ${metric.sourceType} | ${metric.quality}`}
    >
      {canonicalMetricDisplay(metric, emptyText)}
    </span>
  );
}

export function CanonicalMetricCard({
  label,
  metric,
  color,
  emptyText,
}: {
  label: string;
  metric: CanonicalMetric;
  color?: string;
  emptyText?: string;
}): JSX.Element {
  return (
    <div className="trader-metric-card">
      <span className="trader-metric-card__label">{label}</span>
      <CanonicalMetricValue
        metric={metric}
        emptyText={emptyText}
        className="trader-metric-card__value"
        style={{ color: color ?? undefined }}
      />
      <span className="trader-metric-card__meta">
        {metric.quality} | {metric.timestamp ? new Date(metric.timestamp).toLocaleTimeString() : 'no timestamp'}
      </span>
    </div>
  );
}
