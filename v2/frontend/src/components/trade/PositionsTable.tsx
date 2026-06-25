import { useState } from 'react';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatMoney, formatPrice, formatPercent, signedClass } from '../../lib/tradeFormatters';
import { tradeCopy } from '../../lib/tradeCopy';

interface PaperPos {
  position_id: string | null;
  symbol: string;
  side: string;
  notional_usd: number | null;
  leverage: number;
  entry_price?: number | null;
  avg_entry_price: number | null;
  mark_price?: number | null;
  last_mark_price: number | null;
  current_price?: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_bps: number | null;
  mark_price_age_seconds?: number | null;
  mark_price_source?: string | null;
  timeframe: string | null;
  strategy_id: string | null;
  market_regime_at_entry: string | null;
  position_age_seconds: number | null;
}
interface PaperStatusData {
  positions: PaperPos[];
  summary: { open_position_count?: number };
}

function ageStr(sec: number | null | undefined): string {
  if (sec == null) return '—';
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function markAgeStr(sec: number | null | undefined): string {
  if (sec == null) return 'mark age unavailable';
  if (sec < 1) return 'live mark <1s';
  if (sec < 60) return `live mark ${Math.round(sec)}s`;
  return `live mark ${Math.floor(sec / 60)}m`;
}

function positiveNumber(...values: Array<number | null | undefined>): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
  }
  return null;
}

export function PositionsTable({ state }: { state: TradeTerminalState }): JSX.Element {
  const [filter, setFilter] = useState('');

  const paperPositions = ((state.paper.activity.positions ?? []) as unknown as PaperPos[]).filter(p =>
    !filter || p.symbol.toLowerCase().includes(filter.toLowerCase()),
  );
  const summary = state.paper.activity.summary ?? {};
  const sourceStatus = String(summary.position_source_status ?? (state.paper.connected ? 'websocket' : state.paper.source));
  const retainedRows = String(summary.frontend_retained_rows ?? '');

  // Fall back to typed positions from state if Redis load fails
  const legacyRows = state.portfolio.openPositions;

  // Show spinner on initial load (no data yet at all)
  if (state.paper.loading && !paperPositions.length && !legacyRows.length) {
    return (
      <div style={{ padding: '24px 16px', color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
        Loading positions…
      </div>
    );
  }

  if (!paperPositions.length && !legacyRows.length) {
    return (
      <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
        No open positions. Positions appear here when the execution engine accepts fills.
        <br />
          <span style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
          Source: execution activity stream · See <strong>Executions</strong> tab for fill history.
        </span>
      </div>
    );
  }

  // Prefer Redis positions (real data)
  if (paperPositions.length > 0) {
    return (
      <div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
          <input
            placeholder="Filter…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{
              background: 'var(--bg-elevated)', border: '1px solid var(--line-soft)',
              borderRadius: 5, padding: '4px 8px', color: 'var(--text-primary)',
              fontSize: 12, width: 130,
            }}
          />
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {paperPositions.length} positions · {state.paper.connected ? 'WebSocket' : 'HTTP fallback'}
          </span>
          {retainedRows ? (
            <span style={{ fontSize: 11, color: 'var(--warn)' }}>last-known rows retained during transient empty frame</span>
          ) : null}
        </div>
        <div className="trade-table-shell">
          <div className="trade-table trade-table--paper-positions" role="table" aria-label="Positions">
          <div className="trade-table__row trade-table__row--paper-positions trade-table__row--head" role="row">
            <span>Symbol</span>
            <span>Side</span>
            <span>Trade Size</span>
            <span>Lev.</span>
            <span>TF</span>
            <span>Entry</span>
            <span>Mark</span>
            <span>Net PnL</span>
            <span>bps</span>
            <span>Strategy</span>
            <span>Regime</span>
            <span>Age</span>
          </div>
          {paperPositions.map((pos, i) => {
            const isLong = pos.side.toUpperCase().includes('BUY') || pos.side === 'LONG';
            const entryPrice = positiveNumber(pos.entry_price, pos.avg_entry_price);
            const markPrice = positiveNumber(pos.mark_price, pos.last_mark_price, pos.current_price);
            return (
              <div
                className="trade-table__row trade-table__row--paper-positions"
                role="row"
                key={pos.position_id ?? i}
              >
                <span data-label="Symbol" style={{ fontWeight: 700 }}>{pos.symbol}</span>
                <span data-label="Side" style={{ color: isLong ? 'var(--buy)' : 'var(--sell)', fontWeight: 700 }}>
                  {isLong ? '▲ L' : '▼ S'}
                </span>
                <span data-label="Trade Size">{formatMoney(pos.notional_usd)}</span>
                <span data-label="Lev.">{pos.leverage}x</span>
                <span data-label="TF">{pos.timeframe ?? '—'}</span>
                <span data-label="Entry">{formatPrice(entryPrice)}</span>
                <span data-label="Mark" title={String(pos.mark_price_source ?? '')}>{formatPrice(markPrice)}</span>
                <span data-label="Net PnL" className={signedClass(pos.unrealized_pnl)}>
                  {formatMoney(pos.unrealized_pnl)}
                </span>
                <span data-label="bps" className={signedClass(pos.unrealized_pnl_bps)}>
                  {pos.unrealized_pnl_bps != null ? pos.unrealized_pnl_bps.toFixed(1) : '—'}
                </span>
                <span data-label="Strategy" style={{ fontSize: 10 }}>{pos.strategy_id ?? '—'}</span>
                <span data-label="Regime" style={{ fontSize: 10 }}>{pos.market_regime_at_entry ?? '—'}</span>
                <span data-label="Age">{ageStr(pos.position_age_seconds)}</span>
              </div>
            );
          })}
          </div>
        </div>
      <p className="trade-table__note" style={{ color: 'var(--text-muted)', fontSize: 11 }}>
          Source: {sourceStatus} · {markAgeStr(paperPositions[0]?.mark_price_age_seconds)}
        </p>
      </div>
    );
  }

  // Legacy fallback
  return (
    <div className="trade-table" role="table" aria-label="Positions">
      <div className="trade-table__row trade-table__row--head" role="row">
        <span>Symbol</span><span>Side</span><span>Size</span><span>Entry</span><span>Mark</span><span>PnL</span><span>PnL %</span><span>Margin / Notional</span><span>Liq. price</span><span>TP/SL</span><span>Risk</span><span>Mode</span>
      </div>
      {legacyRows.map((position, index) => (
        <div className="trade-table__row" role="row" key={`${position.symbol ?? 'position'}-${index}`}>
          <span data-label="Symbol">{position.symbol ?? 'Connecting stream'}</span>
          <span data-label="Side">{tradeCopy(position.side)}</span>
          <span data-label="Size">{formatMoney(position.quantity, 'Connecting stream').replace('$', '')}</span>
          <span data-label="Entry">{formatPrice(position.entry_price)}</span>
          <span data-label="Mark">{formatPrice(position.current_price, 'Unavailable')}</span>
          <span data-label="PnL" className={signedClass(position.unrealized_pnl)}>{formatMoney(position.unrealized_pnl, 'Unavailable')}</span>
          <span data-label="PnL %" className={signedClass(position.unrealized_pnl_pct)}>{formatPercent(position.unrealized_pnl_pct, 'Unavailable')}</span>
          <span data-label="Margin / Notional">{formatMoney(position.notional)}</span>
          <span data-label="Liq. price">Unavailable</span>
          <span data-label="TP/SL">Unavailable</span>
          <span data-label="Risk">{tradeCopy(state.signal.riskDecision)}</span>
          <span data-label="Mode">Runtime</span>
        </div>
      ))}
      <p className="trade-table__note">Opened: {legacyRows[0]?.opened_utc ?? '—'}</p>
    </div>
  );
}
