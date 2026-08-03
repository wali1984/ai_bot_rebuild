import { Link } from 'react-router-dom';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { RealtimeStatusBar } from '../../components/data/RealtimeStatusBar';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  pnlWindow,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import type { PageMeta } from '../../types/page';

// ---------- types ----------
interface PortfolioData {
  paper_balance?: number | null;
  paper_equity?: number | null;
  equity?: number | null;
  realized_net_pnl_usd?: number | null;
  realized_gross_pnl_usd?: number | null;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  total_pnl_usd?: number | null;
  clean_session_valid_realized_pnl_usd?: number | null;
  clean_session_valid_unrealized_pnl_usd?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  pnl_source_key?: string | null;
  pnl_source_route?: string | null;
  pnl_source_type?: string | null;
  pnl_conflict_detected?: boolean | null;
  open_positions?: unknown[];
  account_mode?: string | null;
}

interface SignalData {
  active_signal?: {
    direction?: string | null;
    confidence?: number | null;
    strategy?: string | null;
    entry?: number | null;
    target_1?: number | null;
    stop?: number | null;
    risk_decision?: string | null;
    symbol?: string | null;
  } | null;
  signal_count?: number | null;
}

interface MarketOverviewData {
  tickers?: Array<{ symbol: string; last_price: number | null; change_24h: number | null }>;
  symbols?: string[];
  count?: number;
}

// ---------- formatting ----------
function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
  return '$' + n.toFixed(2);
}
function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}
function directionColor(dir: string | null | undefined): string {
  if (!dir) return 'var(--text-muted)';
  const d = dir.toLowerCase();
  if (d.includes('long') || d.includes('buy') || d === 'bullish') return 'var(--buy)';
  if (d.includes('short') || d.includes('sell') || d === 'bearish') return 'var(--sell)';
  return 'var(--ai)';
}
function confColor(c: number | null | undefined): string {
  if (c == null) return 'var(--text-muted)';
  const pct = c <= 1 ? c : c / 100;
  if (pct >= 0.75) return 'var(--conf-high)';
  if (pct >= 0.5) return 'var(--conf-mid)';
  return 'var(--conf-low)';
}
function pnlColor(n: number | null | undefined): string {
  if (n == null) return 'var(--text-secondary)';
  return n >= 0 ? 'var(--buy)' : 'var(--sell)';
}

// ---------- sub-components ----------
function KPICard({ label, value, meta: kMeta, valueColor, link }: {
  label: string;
  value: string;
  meta?: string;
  valueColor?: string;
  link?: string;
}): JSX.Element {
  const inner = (
    <div className="kpi-card" style={{ cursor: link ? 'pointer' : 'default' }}>
      <div className="kpi-card__label">{label}</div>
      <div className="kpi-card__value" style={valueColor ? { color: valueColor } : undefined}>{value}</div>
      {kMeta && <div className="kpi-card__meta">{kMeta}</div>}
    </div>
  );
  return link ? <Link to={link} style={{ textDecoration: 'none' }}>{inner}</Link> : inner;
}

function SectionHead({ title, action }: { title: string; action?: JSX.Element }): JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{title}</h2>
      {action}
    </div>
  );
}

function DataPanel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }): JSX.Element {
  return (
    <div
      className="glass"
      style={{
        padding: '16px 20px',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---------- Ticker pulse strip ----------
function MarketPulseRow({ tickers }: { tickers: Array<{ symbol: string; last_price: number | null; change_24h: number | null }> }): JSX.Element {
  const pinned = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT'];
  const sorted = [...tickers].sort((a, b) => {
    const ap = pinned.indexOf(a.symbol); const bp = pinned.indexOf(b.symbol);
    if (ap !== -1 && bp !== -1) return ap - bp;
    if (ap !== -1) return -1;
    if (bp !== -1) return 1;
    return 0;
  }).slice(0, 10);

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {sorted.map((t) => {
        const chg = t.change_24h;
        const chgColor = chg == null ? 'var(--text-muted)' : chg >= 0 ? 'var(--buy)' : 'var(--sell)';
        return (
          <Link
            key={t.symbol}
            to={`/market/${t.symbol}`}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 2,
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--border)',
              background: 'var(--bg-elevated)',
              textDecoration: 'none',
              minWidth: 90,
              transition: 'border-color var(--ease-fast)',
            }}
          >
            <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {t.symbol.replace('USDT', '')}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {t.last_price != null ? fmt(t.last_price) : '—'}
            </span>
            <span style={{ fontSize: 11, fontWeight: 500, fontFamily: 'var(--font-mono)', color: chgColor }}>
              {fmtPct(chg)}
            </span>
          </Link>
        );
      })}
      <Link
        to="/markets"
        style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 2,
          padding: '8px 12px',
          borderRadius: 'var(--radius-sm)',
          border: '1px dashed var(--border)',
          background: 'transparent',
          textDecoration: 'none',
          minWidth: 80,
          alignItems: 'center',
          color: 'var(--text-muted)',
          fontSize: 12,
        }}
      >
        View all markets →
      </Link>
    </div>
  );
}

// ---------- Main page ----------
export default function DashboardPage(): JSX.Element {
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const { envelope: portfolioEnv, loading: portfolioLoading } = useRealtimeResource<PortfolioData>({
    url: '/api/v2/portfolio?scope=current_session',
    source: '/api/v2/portfolio?scope=current_session',
    source_type: 'repository',
    pollIntervalMs: 30_000,
    staleThresholdMs: 120_000,
    mode: 'paper',
  });

  const { envelope: signalEnv, loading: signalLoading } = useRealtimeResource<SignalData>({
    url: '/api/v2/signals',
    source: '/api/v2/signals',
    source_type: 'repository',
    pollIntervalMs: 20_000,
    staleThresholdMs: 90_000,
    mode: 'paper',
  });

  const { envelope: aiEnv, loading: aiLoading } = useRealtimeResource<{ predictions: Array<{ action?: string | null; confidence?: number | null; model_version?: string | null }> }>({
    url: '/api/v2/ai/predictions',
    source: '/api/v2/ai/predictions',
    source_type: 'websocket',
    pollIntervalMs: 60_000,
    staleThresholdMs: 300_000,
    mode: 'read_only',
  });
  const { envelope: marketEnv } = useRealtimeResource<MarketOverviewData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 20_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
  });
  const marketTickers = marketEnv.data?.tickers ?? [];

  const portfolio = portfolioEnv.data;
  const equity = portfolio?.equity ?? portfolio?.paper_equity ?? portfolio?.paper_balance;
  const pnlToday =
    portfolio?.realized_net_pnl_usd
    ?? portfolio?.clean_session_valid_realized_pnl_usd
    ?? portfolio?.realized_pnl_usd
    ?? portfolio?.realized_pnl;
  const unrealizedPnl =
    portfolio?.unrealized_pnl_usd
    ?? portfolio?.clean_session_valid_unrealized_pnl_usd
    ?? portfolio?.unrealized_pnl;
  const openPositions = portfolio?.open_positions ?? [];
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const oneDay = pnlWindow(pnlHistory, '1d');
  const sevenDay = pnlWindow(pnlHistory, '7d');
  const thirtyDay = pnlWindow(pnlHistory, '30d');
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status ?? capitalStatus?.signal_prediction_accuracy_status ?? null;
  const missingAccuracyCells = missingAccuracyCellCount(accuracyStatus);

  const signal = signalEnv.data?.active_signal;
  const signalCount = signalEnv.data?.signal_count ?? (signal ? 1 : 0);

  const latestPred = aiEnv.data?.predictions?.[0];
  const aiConf = latestPred?.confidence;
  const aiAction = latestPred?.action;

  const freshness = signalEnv.freshness_status;

  return (
    <div
      data-testid="page-mission-control"
      data-page-id={(meta as PageMeta).id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100%',
        background:
          'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)',
      }}
    >
      <RealtimeStatusBar
        streams={[
          { name: 'Portfolio', status: portfolioEnv.freshness_status, lagMs: portfolioEnv.lag_ms },
          { name: 'Signals', status: signalEnv.freshness_status, lagMs: signalEnv.lag_ms },
          { name: 'AI', status: aiEnv.freshness_status, lagMs: aiEnv.lag_ms },
          { name: 'Market', status: marketEnv.freshness_status, lagMs: marketEnv.lag_ms },
        ]}
        compact
      />

      <div style={{ padding: '20px 24px', flex: 1, display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Page header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Dashboard</h1>
            <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Real-time platform · WebSocket telemetry · Risk-governed execution
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FreshnessBadge status={freshness} lagMs={signalEnv.lag_ms} />
            <span
              style={{
                padding: '4px 12px',
                borderRadius: 999,
                background: 'var(--sell-bg)',
                border: '1px solid var(--sell-border)',
                color: 'var(--error)',
                fontSize: 11,
                fontWeight: 600,
                fontFamily: 'var(--font-mono)',
              }}
            >
              OPERATOR GATED
            </span>
          </div>
        </div>

        {/* 6 KPI grid */}
        <div className="kpi-grid-6">
          <KPICard
            label="Portfolio Equity"
            value={portfolioLoading ? '…' : equity != null ? fmtMoney(equity) : 'Runtime account'}
            meta={portfolio?.account_mode?.replace(/paper/gi, 'runtime') ?? 'Runtime account'}
            link="/portfolio"
          />
          <KPICard
            label="Today PnL"
            value={portfolioLoading ? '…' : pnlToday != null ? fmtMoney(pnlToday) : '—'}
            meta={unrealizedPnl != null ? `Unrealized: ${fmtMoney(unrealizedPnl)}` : 'Realtime account feed'}
            valueColor={pnlToday != null ? pnlColor(pnlToday) : undefined}
            link="/portfolio"
          />
          <KPICard
            label="1D PnL"
            value={formatAdaptiveMoney(oneDay?.realized_pnl_usd)}
            meta={`${oneDay?.closed_trade_count ?? 0} closes`}
            valueColor={pnlColor(oneDay?.realized_pnl_usd)}
            link="/portfolio"
          />
          <KPICard
            label="1W PnL"
            value={formatAdaptiveMoney(sevenDay?.realized_pnl_usd)}
            meta={`${sevenDay?.closed_trade_count ?? 0} closes`}
            valueColor={pnlColor(sevenDay?.realized_pnl_usd)}
            link="/portfolio"
          />
          <KPICard
            label="30D PnL"
            value={formatAdaptiveMoney(thirtyDay?.realized_pnl_usd)}
            meta={`${thirtyDay?.closed_trade_count ?? 0} closes`}
            valueColor={pnlColor(thirtyDay?.realized_pnl_usd)}
            link="/portfolio"
          />
          <KPICard
            label="Capital Status"
            value={capitalStatus?.status ?? '—'}
            meta={capitalStatus?.capital_utilization_classification ?? 'Adaptive sizing'}
            valueColor={adaptiveStatusColor(capitalStatus?.status)}
            link="/portfolio"
          />
          <KPICard
            label="Active Signals"
            value={signalLoading ? '…' : signalCount != null ? String(signalCount) : '—'}
            meta={signal?.strategy ?? 'Signal stream monitored'}
            link="/signals"
          />
          <KPICard
            label="AI Confidence"
            value={aiLoading ? '…' : aiConf != null ? fmtPct(aiConf <= 1 ? aiConf : aiConf / 100) : '—'}
            meta={aiAction ? `Action: ${aiAction.replaceAll('_', ' ')}` : 'AI prediction monitored'}
            valueColor={aiConf != null ? confColor(aiConf) : undefined}
            link="/ai-predictions"
          />
          <KPICard
            label="Accuracy"
            value={formatAdaptivePercent(accuracyStatus?.overall_accuracy)}
            meta={`${accuracyStatus?.evaluated_row_count ?? 0} evaluated`}
            valueColor={adaptiveStatusColor(accuracyStatus?.status)}
            link="/signals"
          />
          <KPICard
            label="Accuracy Cells"
            value={`${accuracyStatus?.evaluated_symbol_timeframe_cell_count ?? 0}/${accuracyStatus?.symbol_timeframe_cell_count ?? accuracyStatus?.required_symbol_timeframe_cell_count ?? 0}`}
            meta={`${missingAccuracyCells ?? 0} missing evaluated cells`}
            valueColor={(missingAccuracyCells ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
            link="/signals"
          />
          <KPICard
            label="Open Positions"
            value={portfolioLoading ? '…' : String(openPositions.length)}
            meta="Live positions"
            link="/portfolio"
          />
          <KPICard
            label="Data Status"
            value={marketTickers.length > 0 ? 'Live' : 'Connecting'}
            meta={`${marketTickers.length} symbols connected`}
            link="/markets"
          />
        </div>

        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Capital Productivity + PnL + Accuracy"
          compact
          showMatrix
          maxMatrixHeight={220}
        />

        {/* Main content grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, minHeight: 0 }}>
          {/* Left: Market pulse */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <DataPanel>
              <SectionHead
                title="Market Pulse"
                action={
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <SourceBadge sourceType="api" source="/api/v2/market/overview" />
                    <Link to="/markets" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
                      Full screener →
                    </Link>
                  </div>
                }
              />
              {marketTickers.length > 0 ? (
                <MarketPulseRow tickers={marketTickers} />
              ) : (
                <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  Connecting to market feed…
                </div>
              )}
            </DataPanel>

            {/* Quick navigation */}
            <DataPanel>
              <SectionHead title="Quick Access" />
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                {[
                  { label: 'Trade Terminal', path: '/trade', desc: 'Chart + order ticket + book' },
                  { label: 'Markets', path: '/markets', desc: 'Full screener · 77 symbols' },
                  { label: 'Signals', path: '/signals', desc: 'Active · pending · history' },
                  { label: 'Derivatives', path: '/derivatives', desc: 'Funding · OI · liquidations' },
                  { label: 'AI Predictions', path: '/ai-predictions', desc: 'Forecast · confidence' },
                  { label: 'Portfolio', path: '/portfolio', desc: 'Equity · PnL · positions' },
                  { label: 'Backtests', path: '/backtests', desc: 'Equity curve · stats' },
                  { label: 'Alerts', path: '/alerts', desc: 'Price · signal · risk events' },
                ].map((item) => (
                  <Link
                    key={item.path}
                    to={item.path}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border)',
                      background: 'var(--bg-elevated)',
                      textDecoration: 'none',
                      transition: 'border-color var(--ease-fast)',
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{item.label}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.desc}</span>
                  </Link>
                ))}
              </div>
            </DataPanel>
          </div>

          {/* Right: Signal + account summary */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Current signal */}
            <DataPanel>
              <SectionHead
                title="Current Signal"
                action={
                  <Link to="/signals" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
                    All signals →
                  </Link>
                }
              />
              {signal ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        padding: '4px 12px',
                        borderRadius: 999,
                        border: '1px solid currentColor',
                        color: directionColor(signal.direction),
                        fontSize: 13,
                        fontWeight: 700,
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {(signal.direction ?? '—').toUpperCase().replaceAll('_', ' ')}
                    </span>
                    {signal.symbol && (
                      <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {signal.symbol}
                      </span>
                    )}
                  </div>
                  {[
                    ['Confidence', signal.confidence != null ? fmtPct(signal.confidence <= 1 ? signal.confidence : signal.confidence / 100) : '—'],
                    ['Entry', signal.entry != null ? fmt(signal.entry) : '—'],
                    ['Target', signal.target_1 != null ? fmt(signal.target_1) : '—'],
                    ['Stop', signal.stop != null ? fmt(signal.stop) : '—'],
                    ['Risk decision', signal.risk_decision ?? '—'],
                    ['Strategy', signal.strategy ?? '—'],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                      <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                      <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{v}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ padding: '16px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  {signalLoading ? 'Loading signal stream…' : 'No active signal'}
                  <div style={{ marginTop: 8 }}>
                    <Link to="/signals" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
                      View signal history
                    </Link>
                  </div>
                </div>
              )}
            </DataPanel>

            {/* Portfolio summary */}
            <DataPanel>
              <SectionHead
                title="Portfolio"
                action={
                  <Link to="/portfolio" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
                    Details →
                  </Link>
                }
              />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {[
                  ['Equity', portfolioLoading ? '…' : equity != null ? fmtMoney(equity) : 'Runtime account'],
                  ['Realized PnL', portfolioLoading ? '…' : pnlToday != null ? fmtMoney(pnlToday) : '—'],
                  ['Unrealized PnL', portfolioLoading ? '…' : unrealizedPnl != null ? fmtMoney(unrealizedPnl) : '—'],
                  ['1D PnL', formatAdaptiveMoney(oneDay?.realized_pnl_usd)],
                  ['1W PnL', formatAdaptiveMoney(sevenDay?.realized_pnl_usd)],
                  ['30D PnL', formatAdaptiveMoney(thirtyDay?.realized_pnl_usd)],
                  ['Capital Productivity', capitalStatus?.status ?? '—'],
                  ['Open Positions', portfolioLoading ? '…' : String(openPositions.length)],
                  ['Mode', portfolio?.account_mode ?? 'Execution restricted'],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                    <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{v}</span>
                  </div>
                ))}
              </div>
            </DataPanel>

            {/* AI prediction summary */}
            <DataPanel>
              <SectionHead
                title="AI Prediction"
                action={
                  <Link to="/ai-predictions" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}>
                    Full matrix →
                  </Link>
                }
              />
              {latestPred ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: directionColor(latestPred.action), fontFamily: 'var(--font-mono)' }}>
                      {(latestPred.action ?? '—').toUpperCase().replaceAll('_', ' ')}
                    </span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: confColor(aiConf), fontFamily: 'var(--font-mono)' }}>
                      {aiConf != null ? fmtPct(aiConf <= 1 ? aiConf : aiConf / 100) : '—'}
                    </span>
                  </div>
                  {latestPred.model_version && (
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Model: {latestPred.model_version}
                    </span>
                  )}
                  <SourceBadge sourceType={aiEnv.source_type} source="/api/v2/ai/predictions" />
                </div>
              ) : (
                <div style={{ padding: '12px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  {aiLoading ? 'Loading predictions…' : 'No prediction data'}
                </div>
              )}
            </DataPanel>
          </div>
        </div>
      </div>
    </div>
  );
}
