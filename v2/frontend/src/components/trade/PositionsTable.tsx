import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatMoney, formatPrice, formatPercent, signedClass } from '../../lib/tradeFormatters';
import { tradeCopy, TRADE_ENDPOINTS } from '../../lib/tradeCopy';
import { MissingDataState } from './TradeShared';

interface PaperPos {
  position_id: string | null;
  symbol: string;
  side: string;
  notional_usd: number | null;
  leverage: number;
  avg_entry_price: number | null;
  last_mark_price: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_bps: number | null;
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

export function PositionsTable({ state }: { state: TradeTerminalState }): JSX.Element {
  const [filter, setFilter] = useState('');

  const { envelope } = useRealtimeResource<PaperStatusData>({
    url: '/api/v2/paper/status',
    source: '/api/v2/paper/status',
    pollIntervalMs: 8_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
  });

  const paperPositions = (envelope.data?.positions ?? []).filter(p =>
    !filter || p.symbol.toLowerCase().includes(filter.toLowerCase()),
  );

  // Fall back to typed positions from state if Redis load fails
  const legacyRows = state.portfolio.openPositions;

  if (!paperPositions.length && !legacyRows.length) {
    return (
      <MissingDataState
        title="No open paper positions"
        detail="No paper position rows found in Redis (v2:paper:positions). The paper engine may not have any active fills."
        endpoint={TRADE_ENDPOINTS.positions}
      />
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
            {paperPositions.length} positions · Redis live
          </span>
        </div>
        <div className="trade-table" role="table" aria-label="Paper Positions">
          <div className="trade-table__row trade-table__row--head" role="row">
            <span>Symbol</span>
            <span>Side</span>
            <span>Trade Size</span>
            <span>Lev.</span>
            <span>TF</span>
            <span>Entry</span>
            <span>Mark</span>
            <span>Unreal. PnL</span>
            <span>bps</span>
            <span>Strategy</span>
            <span>Regime</span>
            <span>Age</span>
          </div>
          {paperPositions.map((pos, i) => {
            const isLong = pos.side.toUpperCase().includes('BUY') || pos.side === 'LONG';
            return (
              <div
                className="trade-table__row"
                role="row"
                key={pos.position_id ?? i}
                style={{ gridTemplateColumns: '1fr 0.7fr 1fr 0.4fr 0.4fr 0.8fr 0.8fr 0.9fr 0.6fr 1fr 0.7fr 0.6fr' }}
              >
                <span data-label="Symbol" style={{ fontWeight: 700 }}>{pos.symbol}</span>
                <span data-label="Side" style={{ color: isLong ? 'var(--buy)' : 'var(--sell)', fontWeight: 700 }}>
                  {isLong ? '▲ L' : '▼ S'}
                </span>
                <span data-label="Trade Size">{formatMoney(pos.notional_usd)}</span>
                <span data-label="Lev.">{pos.leverage}x</span>
                <span data-label="TF">{pos.timeframe ?? '—'}</span>
                <span data-label="Entry">{formatPrice(pos.avg_entry_price)}</span>
                <span data-label="Mark">{formatPrice(pos.last_mark_price)}</span>
                <span data-label="Unreal. PnL" className={signedClass(pos.unrealized_pnl)}>
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
        <p className="trade-table__note" style={{ color: 'var(--text-muted)', fontSize: 11 }}>
          Source: v2:paper:positions · All fills simulated · places_real_order: false
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
          <span data-label="Symbol">{position.symbol ?? 'Data unavailable'}</span>
          <span data-label="Side">{tradeCopy(position.side)}</span>
          <span data-label="Size">{formatMoney(position.quantity, 'Data unavailable').replace('$', '')}</span>
          <span data-label="Entry">{formatPrice(position.entry_price)}</span>
          <span data-label="Mark">{formatPrice(position.current_price, 'Unavailable')}</span>
          <span data-label="PnL" className={signedClass(position.unrealized_pnl)}>{formatMoney(position.unrealized_pnl, 'Unavailable')}</span>
          <span data-label="PnL %" className={signedClass(position.unrealized_pnl_pct)}>{formatPercent(position.unrealized_pnl_pct, 'Unavailable')}</span>
          <span data-label="Margin / Notional">{formatMoney(position.notional)}</span>
          <span data-label="Liq. price">Unavailable</span>
          <span data-label="TP/SL">Unavailable</span>
          <span data-label="Risk">{tradeCopy(state.signal.riskDecision)}</span>
          <span data-label="Mode">Paper</span>
        </div>
      ))}
      <p className="trade-table__note">Opened: {legacyRows[0]?.opened_utc ?? '—'}</p>
    </div>
  );
}
