import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  adaptiveStatusColor,
  formatAdaptiveMoney,
  pnlWindow,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import { formatMoney, formatPercent, formatPrice } from '../../lib/tradeFormatters';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

const SOURCE_URL_LABELS: Record<string, string> = {
  '/api/v2/portfolio': 'Trader account source',
  'unavailable': 'Connecting stream',
};

export function sourceText(input: string): string {
  return SOURCE_URL_LABELS[input] ?? input;
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  );
}

function capitalStatusText(status: string | null | undefined): string {
  const token = status?.trim();
  if (!token) return '—';
  const upper = token.toUpperCase();
  if (upper.includes('INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE')) return 'Needs productivity evidence';
  if (upper === 'PASSED' || upper === 'READY') return 'Ready';
  if (upper.includes('NO_GO')) return 'Needs review';
  return token
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default function PortfolioPage(): JSX.Element {
  const state = useTradeTerminal();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const openPositions = state.portfolio.openPositions;
  const { equity, realizedPnl, unrealizedPnl, source } = state.account;
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const oneDay = pnlWindow(pnlHistory, '1d');
  const sevenDay = pnlWindow(pnlHistory, '7d');
  const thirtyDay = pnlWindow(pnlHistory, '30d');

  return (
    <div
      data-testid="page-positions"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Portfolio</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Positions · Balances · Exposure · PnL · {state.trader.accountScopeLabel} · Real-time account telemetry
            </p>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>Live platform</span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--buy-bg)', color: 'var(--buy)', border: '1px solid var(--buy-border)' }}>Execution telemetry</span>
          </div>
        </div>
      </div>

      {/* KPI row */}
      <div style={{ padding: '16px 24px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
        {[
          { label: 'Equity', value: formatMoney(equity), color: 'var(--text-primary)' },
          { label: 'Realized PnL', value: formatMoney(realizedPnl), color: (realizedPnl ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
          { label: 'Unrealized PnL', value: formatMoney(unrealizedPnl), color: (unrealizedPnl ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
          { label: '1D PnL', value: formatAdaptiveMoney(oneDay?.realized_pnl_usd), color: (oneDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
          { label: '1W PnL', value: formatAdaptiveMoney(sevenDay?.realized_pnl_usd), color: (sevenDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
          { label: '30D PnL', value: formatAdaptiveMoney(thirtyDay?.realized_pnl_usd), color: (thirtyDay?.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' },
          { label: 'Capital Productivity', value: capitalStatusText(capitalStatus?.status), color: adaptiveStatusColor(capitalStatus?.status) },
          { label: 'Open Positions', value: String(openPositions.length) },
        ].map((item) => (
          <div key={item.label} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '14px 16px' }}>
            <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{item.label}</span>
            <span style={{ display: 'block', fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-mono)', color: item.color, overflowWrap: 'anywhere', lineHeight: 1.15 }}>{item.value}</span>
          </div>
        ))}
      </div>

      <div style={{ padding: '0 24px 16px' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Capital Productivity + PnL + Accuracy"
          compact
          showMatrix
          maxMatrixHeight={220}
        />
      </div>

      {/* Account scope */}
      <div style={{ padding: '0 24px 16px' }}>
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 18px' }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Account Scope</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
            <KV label="Trader" value={state.trader.displayName} />
            <KV label="Account" value={state.trader.accountLabel} />
            <KV label="Exchange" value={state.trader.exchangeLabel} />
            <KV label="Access" value={state.trader.credentialStatus} />
            <KV label="Mode" value="Runtime" />
            <KV label="Source" value={source} />
          </div>
        </div>
      </div>

      {/* Open positions */}
      <div style={{ padding: '0 24px 24px' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
          Open Positions ({openPositions.length})
        </h2>
        {openPositions.length === 0 ? (
          <div style={{ padding: '28px', textAlign: 'center', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>No open positions available for the current account.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {openPositions.map((pos, i) => {
              const p = pos as Record<string, unknown>;
              const upnlPct = p.unrealized_pnl_pct as number | null;
              const pnlColor = upnlPct == null ? 'var(--text-muted)' : upnlPct >= 0 ? 'var(--buy)' : 'var(--sell)';
              return (
                <div key={`pos-${i}`} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 18px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <span style={{ fontWeight: 700, fontSize: 14, fontFamily: 'var(--font-mono)' }}>{String(p.symbol ?? 'Unknown')}</span>
                    <span style={{ fontWeight: 700, fontSize: 12, color: String(p.side ?? '').toLowerCase() === 'long' ? 'var(--buy)' : 'var(--sell)' }}>
                      {String(p.side ?? '—').toUpperCase()}
                    </span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <KV label="Qty" value={String(p.quantity ?? p.size ?? '—')} />
                    <KV label="Entry" value={formatPrice(p.entry_price as number | null)} />
                    <KV label="Mark" value={formatPrice(p.mark_price as number | null)} />
                    <KV label="Unrealized PnL" value={formatPercent(upnlPct)} color={pnlColor} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--border)' }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Trader-scoped account. Source: {source}
        </p>
      </div>
    </div>
  );
}
