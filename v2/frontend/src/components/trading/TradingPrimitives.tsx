import type { ReactNode } from 'react';

export type PillTone = 'ok' | 'warn' | 'block' | 'info' | 'neutral';

function ageSeconds(generatedAt: string | null | undefined): number | null {
  if (!generatedAt) return null;
  const ms = new Date(generatedAt).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.round((Date.now() - ms) / 1000));
}

function ageLabel(age: number | null): string {
  if (age === null) return 'timestamp pending';
  if (age < 60) return `${age}s`;
  if (age < 3600) return `${Math.floor(age / 60)}m`;
  if (age < 86400) return `${Math.floor(age / 3600)}h`;
  return `${Math.floor(age / 86400)}d`;
}

function toneClass(tone: PillTone): string {
  if (tone === 'ok') return 'solid-ok';
  if (tone === 'warn') return 'solid-warn';
  if (tone === 'block') return 'solid-block';
  if (tone === 'info') return 'solid-paper';
  return 'solid-loading';
}

export function StatusPill({ tone = 'neutral', children }: { tone?: PillTone; children: ReactNode }): JSX.Element {
  return <span className={`chip ${toneClass(tone)}`}>{children}</span>;
}

export function DataFreshnessBadge({
  generatedAt,
  source,
  staleAfterSeconds = 120,
}: {
  generatedAt?: string | null;
  source: string;
  staleAfterSeconds?: number;
}): JSX.Element {
  const age = ageSeconds(generatedAt);
  const tone: PillTone = age === null ? 'warn' : age > staleAfterSeconds ? 'warn' : 'ok';
  return (
    <span className={`chip ${toneClass(tone)}`} title={source} data-testid="data-freshness-badge">
      {source}: {ageLabel(age)}
    </span>
  );
}

export function SourceBadge({ source, endpoint }: { source: string; endpoint?: string }): JSX.Element {
  return (
    <span className="chip solid-loading" title={endpoint ?? source} data-testid="source-badge">
      {source}
    </span>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: PillTone;
}): JSX.Element {
  return (
    <div className={`trading-metric trading-metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function ProTable({
  columns,
  rows,
  getKey,
}: {
  columns: ReadonlyArray<{ key: string; label: string }>;
  rows: ReadonlyArray<Record<string, ReactNode>>;
  getKey: (row: Record<string, ReactNode>, index: number) => string;
}): JSX.Element {
  return (
    <div className="pro-table" role="table">
      <div className="pro-table__row pro-table__row--head" role="row">
        {columns.map((column) => <span key={column.key}>{column.label}</span>)}
      </div>
      {rows.map((row, index) => (
        <div className="pro-table__row" role="row" key={getKey(row, index)}>
          {columns.map((column) => <span key={column.key}>{row[column.key] ?? 'source field pending'}</span>)}
        </div>
      ))}
    </div>
  );
}

export function ChartPanel({
  title,
  source,
  children,
}: {
  title: string;
  source: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <section className="chart-panel panel bracketed">
      <span className="br-bl" aria-hidden="true" />
      <span className="br-br" aria-hidden="true" />
      <div className="panel-head">
        <h2 className="panel-title">{title}</h2>
        <SourceBadge source={source} />
      </div>
      {children}
    </section>
  );
}

export function EvidenceDrawer({
  title,
  source,
  children,
  defaultOpen = false,
}: {
  title: string;
  source: string;
  children: ReactNode;
  defaultOpen?: boolean;
}): JSX.Element {
  return (
    <details className="evidence-drawer" open={defaultOpen}>
      <summary>
        <span>{title}</span>
        <SourceBadge source={source} />
      </summary>
      <div className="evidence-drawer__body">{children}</div>
    </details>
  );
}

export function EventTimeline({ events }: { events: ReadonlyArray<{ label: string; detail: ReactNode; tone?: PillTone }> }): JSX.Element {
  return (
    <ol className="event-timeline">
      {events.map((event) => (
        <li key={event.label}>
          <StatusPill tone={event.tone ?? 'neutral'}>{event.label}</StatusPill>
          <span>{event.detail}</span>
        </li>
      ))}
    </ol>
  );
}

export function SystemActionButton({
  label,
  reason,
}: {
  label: string;
  reason: string;
}): JSX.Element {
  return (
    <button type="button" className="system-action-button" disabled aria-disabled="true" title={reason}>
      {label}
    </button>
  );
}

export function ControlConfirmationDialog({ action, reason }: { action: string; reason: string }): JSX.Element {
  return (
    <div className="control-confirmation-dialog" role="note">
      <strong>{action}</strong>
      <span>{reason}</span>
    </div>
  );
}

function userFacingSource(source: string): string {
  const trimmed = source.trim();
  if (!trimmed) return 'Trading data service';
  if (trimmed.startsWith('/api/v2/backtests')) return 'Backtest service';
  if (trimmed.startsWith('/api/v2/research')) return 'Research source pending';
  if (trimmed.startsWith('/api/v2/')) return 'Trading platform service';
  if (trimmed.startsWith('/api/')) return 'Platform service';
  if (trimmed.includes('/operator_runtime/') || trimmed.includes('.json')) return 'Runtime data feed';
  return trimmed
    .replace(/\boperator[_\s-]*dashboard\b/gi, 'dashboard')
    .replace(/\bpayloads?\b/gi, 'data feed');
}

export function EmptyStateWithMissingData({
  title,
  source,
  detail,
}: {
  title: string;
  source: string;
  detail: string;
}): JSX.Element {
  return (
    <section className="empty-state-missing panel" data-testid="missing-data-state">
      <StatusPill tone="warn">Connecting stream</StatusPill>
      <h2>{title}</h2>
      <p>{detail}</p>
      <span className="empty-state-missing__source">{userFacingSource(source)}</span>
    </section>
  );
}

export function ErrorStateWithSource({ source, error }: { source: string; error: string }): JSX.Element {
  return (
    <section className="empty-state-missing panel" role="alert">
      <StatusPill tone="block">source error</StatusPill>
      <p>{error}</p>
      <code>{source}</code>
    </section>
  );
}

export function StaleDataWarning({ source, generatedAt }: { source: string; generatedAt?: string | null }): JSX.Element {
  return (
    <p className="stale-data-warning">
      <DataFreshnessBadge generatedAt={generatedAt} source={source} staleAfterSeconds={120} />
      Data older than the freshness window cannot be used as current trading evidence.
    </p>
  );
}
