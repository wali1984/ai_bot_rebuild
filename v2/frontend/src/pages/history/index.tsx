import { useState } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { TradeBottomTabs } from '../../components/trade/TradeBottomTabs';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import {
  formatAdaptiveMoney,
  pnlWindow,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import { formatMoney } from '../../lib/tradeFormatters';
import { tradeCopy } from '../../lib/tradeCopy';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

export default function HistoryPage(): JSX.Element {
  const state = useTradeTerminal();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const historyCount = state.activity.orderHistory.length;
  const executionCount = state.activity.executions.length;
  const auditEventCount = state.activity.auditEvents.length;
  const openPositionCount = state.portfolio.openPositions.length;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.pnl_history
    ?? null;
  const oneDay = pnlWindow(pnlHistory, '1d');
  const sevenDay = pnlWindow(pnlHistory, '7d');
  const thirtyDay = pnlWindow(pnlHistory, '30d');

  return (
    <div
      data-testid="page-history"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', paddingBottom: 48 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>History</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Trade journal · Signal history · Performance stats · {state.trader.accountScopeLabel}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>Execution restricted</span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--buy-bg)', color: 'var(--buy)', border: '1px solid var(--buy-border)' }}>Execution history</span>
          </div>
        </div>
      </div>

      {/* Summary stats */}
      <div style={{ padding: '16px 24px 0' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
          {[
            { label: 'Trader', value: state.trader.displayName },
            { label: 'Account', value: state.trader.accountLabel },
            { label: 'Equity', value: formatMoney(state.account.equity) },
            { label: 'Realized PnL', value: formatMoney(state.account.realizedPnl), color: (state.account.realizedPnl ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: '1D PnL', value: formatAdaptiveMoney(oneDay?.realized_pnl_usd), color: (oneDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: '1W PnL', value: formatAdaptiveMoney(sevenDay?.realized_pnl_usd), color: (sevenDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: '30D PnL', value: formatAdaptiveMoney(thirtyDay?.realized_pnl_usd), color: (thirtyDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: 'Open Positions', value: String(openPositionCount) },
            { label: 'Order History', value: String(historyCount) },
            { label: 'Executions', value: String(executionCount) },
            { label: 'Audit Events', value: String(auditEventCount) },
          ].map((item) => (
            <div key={item.label} className="glass" style={{ padding: '12px 14px' }}>
              <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{item.label}</span>
              <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: item.color ?? 'var(--text-primary)', lineHeight: 1.2, overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word', display: 'block' }}>{item.value}</span>
            </div>
          ))}
        </div>

        <div style={{ marginBottom: 20 }}>
          <AdaptiveCapitalTelemetryPanel
            payload={adaptiveCapital.data}
            title="Capital Productivity + PnL + Accuracy"
            compact
            showMatrix
            maxMatrixHeight={220}
          />
        </div>

        <div className="glass" style={{ padding: '10px 14px', marginBottom: 20, fontSize: 12, color: 'var(--text-muted)' }}>
          Mode: <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{tradeCopy(state.mode.traderState, 'Realtime trading workspace')}</span>
          {' · '}Signal source: <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{state.activity.sources.signals}</span>
        </div>
      </div>

      {/* Trade tabs */}
      <div style={{ padding: '0 24px 24px' }}>
        <TradeBottomTabs state={state} initialTab="Order History" />
      </div>
    </div>
  );
}
