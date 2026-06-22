import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  pnlWindow,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import { formatMoney, formatPrice } from '../../lib/tradeFormatters';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

export default function ExecutionsPage(): JSX.Element {
  const state = useTradeTerminal();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const executions = state.activity.executions;
  const executionSource = state.activity.sources.executions;
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status ?? null;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? capitalStatus?.signal_prediction_accuracy_status
    ?? null;
  const oneDay = pnlWindow(pnlHistory, '1d');
  const sevenDay = pnlWindow(pnlHistory, '7d');
  const thirtyDay = pnlWindow(pnlHistory, '30d');

  return (
    <div
      data-testid="page-executions"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Executions</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Fills · Orders · Rejects · Slippage · Fees · Risk denials · {state.trader.accountScopeLabel}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>Live platform</span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--buy-bg)', color: 'var(--buy)', border: '1px solid var(--buy-border)' }}>Execution stream</span>
          </div>
        </div>
      </div>

      {/* Account context */}
      <div style={{ padding: '16px 24px 0' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
          {[
            { label: 'Trader', value: state.trader.displayName },
            { label: 'Account', value: state.trader.accountLabel },
            { label: 'Exchange', value: state.trader.exchangeLabel },
            { label: 'Executions', value: String(executions.length) },
            { label: 'Equity', value: formatMoney(state.account.equity) },
            { label: '1D PnL', value: formatAdaptiveMoney(oneDay?.realized_pnl_usd), color: (oneDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: '1W PnL', value: formatAdaptiveMoney(sevenDay?.realized_pnl_usd), color: (sevenDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: '30D PnL', value: formatAdaptiveMoney(thirtyDay?.realized_pnl_usd), color: (thirtyDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
            { label: 'Accuracy', value: formatAdaptivePercent(accuracyStatus?.overall_accuracy), color: adaptiveStatusColor(accuracyStatus?.status) },
            { label: 'Capital Status', value: capitalStatus?.status ?? '—', color: adaptiveStatusColor(capitalStatus?.status) },
            { label: 'Source', value: executionSource },
          ].map((item) => (
            <div key={item.label} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '12px 14px' }}>
              <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{item.label}</span>
              <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: item.color ?? 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>{item.value}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '0 24px 20px' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Execution PnL + Capital Productivity + Accuracy"
          compact
          showMatrix
          maxMatrixHeight={220}
        />
      </div>

      {/* Executions table/cards */}
      <div style={{ padding: '0 24px 24px' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
          Executions ({executions.length})
        </h2>
        {executions.length === 0 ? (
          <div style={{ padding: '28px', textAlign: 'center', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
              No execution records. Live order submission is disabled.
            </p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
              <thead>
                <tr style={{ background: 'var(--bg-elevated)' }}>
                  {['Symbol', 'Side', 'Quantity', 'Price', 'Fee', 'Status'].map((h) => (
                    <th key={h} style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {executions.map((ex, i) => {
                  const e = ex as Record<string, unknown>;
                  const side = String(e.side ?? '—');
                  return (
                    <tr key={`ex-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                      <td style={{ padding: '10px 12px', fontWeight: 600 }}>{String(e.symbol ?? '—')}</td>
                      <td style={{ padding: '10px 12px', fontWeight: 700, color: side.toLowerCase() === 'buy' || side.toLowerCase() === 'long' ? 'var(--buy)' : 'var(--sell)' }}>{side.toUpperCase()}</td>
                      <td style={{ padding: '10px 12px' }}>{String(e.quantity ?? e.qty ?? '—')}</td>
                      <td style={{ padding: '10px 12px' }}>{formatPrice(e.price as number | null)}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{formatMoney(e.fee as number | null)}</td>
                      <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{String(e.status ?? 'filled')}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--border)' }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Trader-scoped execution records — no live order submission. Source: {executionSource}
        </p>
      </div>
    </div>
  );
}
