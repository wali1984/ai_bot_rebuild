import type { ReactNode } from 'react';
import type { Candle, CockpitPayload, DecisionRow, ExchangeConnector, Freshness, MonitorRow, QuarantinePayload, SettingRow } from './cockpitData';
import { statusClass, valueText } from './cockpitData';

export function CockpitLoading({ error }: { error: string | null }): JSX.Element | null {
  if (error) return <p className="cockpit-evidence-gap" role="alert">Evidence missing - cockpit payload unavailable: {error}</p>;
  return <p className="cockpit-evidence-gap">Loading cockpit evidence...</p>;
}

export function SafetyTopBar({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <section className="cockpit-topbar" data-testid="cockpit-topbar">
      <Metric label="Live trading" value={payload.live_gate_status} />
      <Metric label="Account mode" value={payload.account_mode} />
      <Metric label="Selected symbol" value={payload.selected_symbol} />
      <Metric label="Generated" value={payload.generated_at} />
    </section>
  );
}

export function Metric({ label, value, detail }: { label: string; value: unknown; detail?: string }): JSX.Element {
  return (
    <div className="cockpit-metric">
      <span>{label}</span>
      <strong className={statusClass(value)}>{valueText(value)}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="cockpit-panel" id={id} data-testid={`cockpit-${id}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function FreshnessBadge({ freshness }: { freshness: Freshness }): JSX.Element {
  return (
    <span className={statusClass(freshness.freshness_state)} title={freshness.source_pointer}>
      {freshness.freshness_state} / {freshness.mode}
    </span>
  );
}

export function MarketPulse({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <Panel id="market-pulse" title="Market Pulse">
      <div className="cockpit-analytics-grid">
        {payload.analytics_cards.map((card) => (
          <div className="cockpit-analytics-card" key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.detail}</small>
            <FreshnessBadge freshness={card.freshness} />
          </div>
        ))}
      </div>
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Symbol</span><span>Price</span><span>1H / 24H</span><span>Funding</span><span>OI</span><span>Long/Short</span><span>Risk</span><span>Freshness</span>
        </div>
        {payload.market_rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.symbol}>
            <span>{row.symbol}</span>
            <span>{row.price}</span>
            <span>{row.change_1h} / {row.change_24h}</span>
            <span>{row.funding_rate}</span>
            <span>{row.open_interest} ({row.oi_change_24h})</span>
            <span>{row.long_short_ratio}</span>
            <span className={statusClass(row.risk_state)}>{row.risk_state}</span>
            <FreshnessBadge freshness={row.freshness} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ChartPanel({ candles, decisions, sourceType }: { candles: Candle[]; decisions: DecisionRow[]; sourceType?: string }): JSX.Element {
  const width = 760;
  const height = 260;
  const prices = candles.flatMap((c) => [c.high, c.low]);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const y = (price: number) => height - 24 - ((price - min) / (max - min || 1)) * (height - 48);
  const step = width / Math.max(candles.length, 1);
  return (
    <Panel id="charting-market-data" title="BTCUSDT Chart, Signals, And Risk Markers">
      <svg className="cockpit-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="BTCUSDT candlestick chart with risk markers">
        <rect x="0" y="0" width={width} height={height} rx="6" />
        {candles.map((candle, index) => {
          const x = index * step + step / 2;
          const open = y(candle.open);
          const close = y(candle.close);
          const high = y(candle.high);
          const low = y(candle.low);
          const bodyTop = Math.min(open, close);
          const bodyHeight = Math.max(Math.abs(close - open), 2);
          const up = candle.close >= candle.open;
          return (
            <g key={candle.time}>
              <line x1={x} x2={x} y1={high} y2={low} className={up ? 'candle-up' : 'candle-down'} />
              <rect x={x - 5} y={bodyTop} width="10" height={bodyHeight} className={up ? 'candle-up' : 'candle-down'} />
              <rect x={x - 5} y={height - 18 - candle.volume / 900} width="10" height={candle.volume / 900} className="volume-bar" />
            </g>
          );
        })}
        {decisions.slice(0, 3).map((decision, index) => (
          <g key={decision.id}>
            <circle cx={80 + index * 180} cy={42 + index * 22} r="7" className={decision.risk_reason.includes('blocked') ? 'risk-marker' : 'signal-marker'} />
            <text x={94 + index * 180} y={47 + index * 22}>{decision.symbol} {decision.risk_reason}</text>
          </g>
        ))}
      </svg>
      <p className="cockpit-evidence-note">
        {sourceType === 'READONLY_MARKET_FEED'
          ? 'READONLY_MARKET_FEED: chart uses Binance USD-M public GET-only market data. It cannot place orders.'
          : 'STATIC_PROOF_FIXTURE: chart uses deterministic static proof candles until Binance USD-M `/fapi/v1/klines` read-only market data is wired. It cannot place orders.'}
      </p>
    </Panel>
  );
}

export function DecisionDrawers({ rows }: { rows: DecisionRow[] }): JSX.Element {
  return (
    <Panel id="decision-explainability" title="Decision Explainability Drawers">
      {rows.map((row) => (
        <details className="cockpit-decision-drawer" key={row.id} open={row.symbol === 'LABUSDT'}>
          <summary>
            <span>{row.symbol}</span>
            <span>{row.prediction_id}</span>
            <span className={statusClass(row.risk_reason)}>{row.risk_reason}</span>
          </summary>
          <div className="cockpit-lineage-grid">
            {([
              ['feature_snapshot_id', row.feature_snapshot_id],
              ['signal_id', row.signal_id],
              ['orchestrator_decision_id', row.orchestrator_decision_id],
              ['risk_decision_id', row.risk_decision_id],
              ['execution_intent_id', row.execution_intent_id],
              ['model/checkpoint', row.model_checkpoint],
              ['raw/calibrated/delta', `${row.confidence_raw} / ${row.confidence_calibrated} / ${row.confidence_delta}`],
              ['source freshness', row.source_freshness_by_ingestor],
              ['signal reason', row.signal_reason],
              ['orchestrator reason', row.orchestrator_reason],
              ['risk reason', row.risk_reason],
              ['result', row.result],
            ] satisfies Array<[string, unknown]>).map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{valueText(value)}</strong>
              </div>
            ))}
          </div>
          <div className="cockpit-mini-grid">
            <MiniList title="Top positive" items={row.top_positive} />
            <MiniList title="Top negative" items={row.top_negative} />
            <MiniList title="Stale flags" items={row.stale_flags} />
            <MiniList title="Missing flags" items={row.missing_flags.length ? row.missing_flags : ['Evidence missing - cannot explain without guessing']} />
          </div>
        </details>
      ))}
    </Panel>
  );
}

export function ExchangeManager({ rows }: { rows: ExchangeConnector[] }): JSX.Element {
  return (
    <Panel id="exchange-manager" title="Exchange Manager - Read Only Linking">
      <div className="cockpit-card-grid">
        {rows.map((row) => (
          <div className="cockpit-exchange-card" key={row.exchange}>
            <h3>{row.exchange}</h3>
            <Metric label="Status" value={row.status} />
            <Metric label="Read-only key" value={row.read_only_key_status} />
            <Metric label="Trade permission" value={row.trade_permission} />
            <Metric label="Order capability" value={row.order_capability} />
            <Metric label="IP restriction" value={row.ip_restriction_status} />
            <FreshnessBadge freshness={row.freshness} />
            <p>{row.notes}</p>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function MonitorTable({ rows }: { rows: MonitorRow[] }): JSX.Element {
  return (
    <Panel id="monitor-center" title="Monitor Center">
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Script</span><span>Status</span><span>Owner</span><span>Last success</span><span>Metrics</span><span>Redis</span><span>Logs</span><span>Processes</span><span>Alerts</span>
        </div>
        {rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.script_path}>
            <span>{row.script_path}</span>
            <span className={statusClass(row.status)}>{row.classification} / {row.status}</span>
            <span>{row.owner}</span>
            <span>{row.last_success}</span>
            <span>{valueText(row.metrics_emitted)}</span>
            <span>{valueText(row.redis_keys_watched)}</span>
            <span>{valueText(row.logs_watched)}</span>
            <span>{valueText(row.processes_watched)}</span>
            <span>{valueText(row.alerts)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ConfigTable({ rows }: { rows: SettingRow[] }): JSX.Element {
  return (
    <Panel id="config-admin" title="Config Admin - Safety Classified Settings">
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Setting</span><span>Value</span><span>Classification</span><span>Reason</span>
        </div>
        {rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.name}>
            <span>{row.name}</span>
            <span>{row.value}</span>
            <span className={statusClass(row.classification)}>{row.classification}</span>
            <span>{row.reason}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function QuarantinePanel({ payload }: { payload: QuarantinePayload | null }): JSX.Element {
  const rows = payload?.ownership_rows ?? [];
  return (
    <Panel id="external-manual-position-quarantine" title="External / Manual Position Quarantine">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload?.go_no_go ?? 'Evidence missing'} />
        <Metric label="Quarantined" value={payload?.summary?.quarantined_count ?? 'Evidence missing'} />
        <Metric label="Manual external" value={payload?.summary?.manual_external_count ?? 'Evidence missing'} />
        <Metric label="Duplicate accounting" value={payload?.summary?.duplicate_accounting_candidate_count ?? 'Evidence missing'} />
      </div>
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Symbol</span><span>Ownership</span><span>Reason</span><span>Missing</span><span>Allowed</span><span>Blocked</span>
        </div>
        {rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={valueText(row.evidence_id)}>
            <span>{valueText(row.symbol)}</span>
            <span className={statusClass(row.ownership_classification)}>{valueText(row.ownership_classification)}</span>
            <span>{valueText(row.quarantine_reason)}</span>
            <span>{valueText(row.missing_attribution_fields)}</span>
            <span>{valueText(row.allowed_actions)}</span>
            <span>{valueText(row.blocked_actions)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }): JSX.Element {
  return (
    <div className="cockpit-mini-list">
      <h3>{title}</h3>
      {items.map((item) => <span key={item}>{item}</span>)}
    </div>
  );
}
