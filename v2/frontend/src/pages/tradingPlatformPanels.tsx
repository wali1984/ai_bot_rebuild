import { Metric, Panel } from './cockpitComponents';
import { statusClass, valueText } from './cockpitData';
import type { CoinankMarketIntelligencePayload, OperatorTruthPayload, PaperOnlineRuntimePayload } from './operatorTruthData';

const MISSING = 'MISSING_EVIDENCE';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function lineageIds(payload: PaperOnlineRuntimePayload | null): Record<string, unknown> {
  return asRecord(asRecord(payload?.current_signal_lineage).lineage_ids);
}

function signalRecord(payload: PaperOnlineRuntimePayload | null): Record<string, unknown> {
  return asRecord(asRecord(payload?.current_signal_lineage).signal);
}

function executionIntent(payload: PaperOnlineRuntimePayload | null): Record<string, unknown> {
  return asRecord(asRecord(payload?.current_signal_lineage).execution_intent);
}

function riskDecision(payload: PaperOnlineRuntimePayload | null): Record<string, unknown> {
  return asRecord(payload?.current_risk_decision);
}

function trainerPrediction(payload: PaperOnlineRuntimePayload | null): Record<string, unknown> {
  return asRecord(payload?.trainer_prediction);
}

function latestPaperEvent(payload: PaperOnlineRuntimePayload | null): Record<string, unknown> {
  return asRecord(payload?.last_paper_event);
}

function latestLegacyExecution(payload: OperatorTruthPayload | null): Record<string, unknown> {
  const bridge = asRecord(asRecord(payload?.live_observer_shadow_twin).legacy_read_only_bridge);
  const streams = asRecord(bridge.streams);
  const executed = asRecord(streams.executed_signals);
  const latest = asRecord(executed.latest_entry);
  return asRecord(asRecord(latest.fields).data);
}

function sourceNote(path: string): JSX.Element {
  return <p className="cockpit-evidence-note">Source/freshness: {path}. Missing optional fields are shown as {MISSING}, not mocked.</p>;
}

export function MissionTradingPlatformPanel({
  paperRuntime,
  coinankPayload,
  truthPayload,
}: {
  paperRuntime: PaperOnlineRuntimePayload | null;
  coinankPayload: CoinankMarketIntelligencePayload | null;
  truthPayload: OperatorTruthPayload | null;
}): JSX.Element {
  const ids = lineageIds(paperRuntime);
  const signal = signalRecord(paperRuntime);
  const risk = riskDecision(paperRuntime);
  const paper = latestPaperEvent(paperRuntime);
  const trainer = trainerPrediction(paperRuntime);
  const availability = coinankPayload?.availability ?? {};
  const endpointCounts = coinankPayload?.endpoint_key_counts ?? {};
  const legacyExecution = latestLegacyExecution(truthPayload);
  return (
    <Panel id="trading-platform-mission-overview" title="Trading Platform Overview" right={<span className="chip solid-block">Live blocked</span>}>
      <div className="cockpit-analytics-grid">
        <Metric label="Live gate" value={paperRuntime?.live_gate_status ?? truthPayload?.live_gate_status ?? 'blocked_human_only'} />
        <Metric label="Paper equity" value={paperRuntime?.paper_account?.equity ?? MISSING} />
        <Metric label="Paper PnL" value={paperRuntime ? `${paperRuntime.paper_account.realized_pnl} realized / ${paperRuntime.paper_account.unrealized_pnl} unrealized` : MISSING} />
        <Metric label="Selected symbol" value={paperRuntime?.market_feed?.symbol ?? 'BTCUSDT'} />
        <Metric label="Observed price" value={paperRuntime?.market_feed?.price ?? MISSING} />
        <Metric label="Market source" value={paperRuntime?.market_feed?.source_type ?? MISSING} />
        <Metric label="SMC" value={String(availability.indicator_smc ?? false)} />
        <Metric label="CVD keys" value={endpointCounts.agg_cvd ?? MISSING} />
        <Metric label="Weighted funding" value={endpointCounts.weighted_funding ?? MISSING} />
        <Metric label="Liquidation rank" value={String(availability.liquidation_rank ?? availability.liquidation_orders ?? false)} />
        <Metric label="Legacy latest execution" value={legacyExecution.exchange_order_id ?? 'read-only import missing'} />
        <Metric label="Current blocker count" value={truthPayload?.current_blockers.length ?? 0} />
      </div>
      <div className="cockpit-card-grid">
        <div className="cockpit-exchange-card">
          <h3>Latest Prediction</h3>
          <Metric label="prediction_id" value={ids.prediction_id ?? trainer.prediction_id ?? MISSING} />
          <Metric label="feature_snapshot_id" value={ids.feature_snapshot_id ?? trainer.feature_snapshot_id ?? MISSING} />
          <Metric label="confidence" value={signal.confidence ?? trainer.confidence_calibrated ?? MISSING} />
        </div>
        <div className="cockpit-exchange-card">
          <h3>Latest Signal</h3>
          <Metric label="signal_id" value={ids.signal_id ?? signal.signal_id ?? MISSING} />
          <Metric label="action" value={signal.proposed_action ?? MISSING} />
          <Metric label="age/source" value={signal.source_freshness ?? paperRuntime?.freshness?.status ?? MISSING} />
        </div>
        <div className="cockpit-exchange-card">
          <h3>Risk Decision</h3>
          <Metric label="risk_decision_id" value={ids.risk_decision_id ?? risk.risk_decision_id ?? MISSING} />
          <Metric label="result" value={risk.risk_result ?? MISSING} />
          <Metric label="reason" value={risk.risk_reason_code ?? MISSING} />
        </div>
        <div className="cockpit-exchange-card">
          <h3>Paper Execution</h3>
          <Metric label="execution_intent_id" value={ids.execution_intent_id ?? paper.execution_intent_id ?? MISSING} />
          <Metric label="paper result" value={paper.paper_result ?? MISSING} />
          <Metric label="live order" value={String(paper.live_order ?? false)} />
        </div>
      </div>
      {sourceNote('operator_runtime/paper_online/latest + operator_runtime/coinank_market_intelligence/latest + operator_truth/latest')}
    </Panel>
  );
}

export function TradingPlatformRoutePanel({
  routeId,
  paperRuntime,
  coinankPayload,
  truthPayload,
}: {
  routeId: string;
  paperRuntime: PaperOnlineRuntimePayload | null;
  coinankPayload: CoinankMarketIntelligencePayload | null;
  truthPayload: OperatorTruthPayload | null;
}): JSX.Element | null {
  if (routeId === 'symbols' || routeId === 'market-intelligence') {
    return <MarketIntelligencePlatformPanel paperRuntime={paperRuntime} coinankPayload={coinankPayload} />;
  }
  if (routeId === 'signals') {
    return <SignalsPlatformPanel paperRuntime={paperRuntime} />;
  }
  if (routeId === 'executions') {
    return <ExecutionsPlatformPanel paperRuntime={paperRuntime} truthPayload={truthPayload} />;
  }
  if (routeId === 'positions') {
    return <PortfolioPlatformPanel paperRuntime={paperRuntime} truthPayload={truthPayload} />;
  }
  return null;
}

function MarketIntelligencePlatformPanel({
  paperRuntime,
  coinankPayload,
}: {
  paperRuntime: PaperOnlineRuntimePayload | null;
  coinankPayload: CoinankMarketIntelligencePayload | null;
}): JSX.Element {
  const availability = coinankPayload?.availability ?? {};
  const endpointCounts = coinankPayload?.endpoint_key_counts ?? {};
  const missing = coinankPayload?.missing_evidence ?? [];
  const hotSymbols = Array.isArray(coinankPayload?.hot_symbols) ? coinankPayload.hot_symbols : [];
  const radarSymbols = asList(coinankPayload?.radar_symbols);
  const symbol = paperRuntime?.market_feed?.symbol ?? 'BTCUSDT';
  return (
    <Panel id="platform-market-intelligence" title="Markets / CoinAnk Intelligence" right={<span className="chip solid-ok">{coinankPayload?.source ?? MISSING}</span>}>
      <div className="cockpit-analytics-grid">
        <Metric label="Radar symbols" value={radarSymbols.length || hotSymbols.length || MISSING} />
        <Metric label="SMC" value={String(availability.indicator_smc ?? false)} />
        <Metric label="Agg CVD" value={endpointCounts.agg_cvd ?? MISSING} />
        <Metric label="Weighted funding" value={endpointCounts.weighted_funding ?? MISSING} />
        <Metric label="Long/short" value={String(availability.long_short ?? false)} />
        <Metric label="Liquidation rank/orders" value={String(availability.liquidation_rank ?? availability.liquidation_orders ?? false)} />
        <Metric label="Open interest" value={endpointCounts.open_interest ?? MISSING} />
        <Metric label="Missing optional data" value={missing.length} />
      </div>
      <div className="cockpit-market-table" role="table" aria-label="Market intelligence table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Symbol</span><span>Price</span><span>Funding</span><span>OI</span><span>Long/Short</span><span>Liquidation</span><span>Risk</span><span>Freshness</span>
        </div>
        <div className="cockpit-table-row" role="row">
          <span>{symbol}</span>
          <span>{valueText(paperRuntime?.market_feed?.price ?? MISSING)}</span>
          <span>{endpointCounts.weighted_funding ? 'LIVE_COINANK_READONLY' : 'MISSING_EVIDENCE'}</span>
          <span>{endpointCounts.open_interest ? 'LIVE_COINANK_READONLY' : 'MISSING_EVIDENCE'}</span>
          <span>{availability.long_short ? 'LIVE_COINANK_READONLY' : 'MISSING_EVIDENCE'}</span>
          <span>{availability.liquidation_orders || availability.liquidation_rank ? 'LIVE_COINANK_READONLY' : 'MISSING_EVIDENCE'}</span>
          <span className={statusClass(paperRuntime?.current_risk_decision?.risk_result)}>{valueText(paperRuntime?.current_risk_decision?.risk_result ?? MISSING)}</span>
          <span>{paperRuntime?.freshness?.status ?? MISSING}</span>
        </div>
      </div>
      {sourceNote('operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json')}
    </Panel>
  );
}

function SignalsPlatformPanel({ paperRuntime }: { paperRuntime: PaperOnlineRuntimePayload | null }): JSX.Element {
  const ids = lineageIds(paperRuntime);
  const signal = signalRecord(paperRuntime);
  const risk = riskDecision(paperRuntime);
  return (
    <Panel id="platform-current-signals" title="Current Signals" right={<span className="chip solid-ok">REALTIME_RUNTIME_EVIDENCE</span>}>
      <div className="cockpit-market-table" role="table" aria-label="Current signals table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>signal_id</span><span>prediction_id</span><span>symbol</span><span>side/action</span><span>confidence</span><span>age</span><span>feature_snapshot_id</span><span>risk_decision_id</span><span>status/reason</span>
        </div>
        <div className="cockpit-table-row" role="row">
          <span>{valueText(ids.signal_id ?? signal.signal_id ?? MISSING)}</span>
          <span>{valueText(ids.prediction_id ?? signal.prediction_id ?? MISSING)}</span>
          <span>{valueText(signal.symbol ?? paperRuntime?.market_feed?.symbol ?? MISSING)}</span>
          <span>{valueText(signal.proposed_action ?? MISSING)}</span>
          <span>{valueText(signal.confidence ?? MISSING)}</span>
          <span>{valueText(paperRuntime?.freshness?.runtime_age_seconds ?? MISSING)}</span>
          <span>{valueText(ids.feature_snapshot_id ?? signal.feature_snapshot_id ?? MISSING)}</span>
          <span>{valueText(ids.risk_decision_id ?? risk.risk_decision_id ?? MISSING)}</span>
          <span>{valueText(risk.risk_result ?? MISSING)} / {valueText(risk.risk_reason_code ?? MISSING)}</span>
        </div>
      </div>
      {sourceNote('operator_runtime/paper_online/latest/current_signal_lineage.json')}
    </Panel>
  );
}

function ExecutionsPlatformPanel({
  paperRuntime,
  truthPayload,
}: {
  paperRuntime: PaperOnlineRuntimePayload | null;
  truthPayload: OperatorTruthPayload | null;
}): JSX.Element {
  const ids = lineageIds(paperRuntime);
  const intent = executionIntent(paperRuntime);
  const paper = latestPaperEvent(paperRuntime);
  const legacy = latestLegacyExecution(truthPayload);
  return (
    <Panel id="platform-current-executions" title="Paper And Imported Execution Ledger" right={<span className="chip solid-block">No live order control</span>}>
      <div className="cockpit-market-table" role="table" aria-label="Current executions table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>source</span><span>execution_intent_id</span><span>exchange_order_id</span><span>dedupe</span><span>attribution</span><span>PnL</span><span>latency</span><span>margin/leverage</span><span>module</span>
        </div>
        <div className="cockpit-table-row" role="row">
          <span>V2 paper</span>
          <span>{valueText(ids.execution_intent_id ?? paper.execution_intent_id ?? MISSING)}</span>
          <span>{valueText(paper.exchange_order_id ?? 'none_paper_only')}</span>
          <span>dedupe_required_before_live</span>
          <span>{valueText(ids.signal_id ? 'ATTRIBUTED_CURRENT_LINEAGE' : MISSING)}</span>
          <span>{valueText(paper.pnl ?? paper.realized_pnl ?? MISSING)}</span>
          <span>{valueText(paper.latency_ms ?? MISSING)}</span>
          <span>live_margin_leverage_blocked</span>
          <span>paper_online_runtime</span>
        </div>
        <div className="cockpit-table-row" role="row">
          <span>legacy read-only import</span>
          <span>{valueText(legacy.execution_intent_id ?? MISSING)}</span>
          <span>{valueText(legacy.exchange_order_id ?? MISSING)}</span>
          <span>read_only_forensics</span>
          <span>{valueText(legacy.signal_id ? 'LEGACY_ATTRIBUTION_PRESENT' : 'LEGACY_ATTRIBUTION_GAP')}</span>
          <span>{valueText(legacy.net_pnl_usd ?? MISSING)}</span>
          <span>{valueText(legacy.latency_ms ?? MISSING)}</span>
          <span>{valueText(legacy.margin_mode ?? MISSING)} / {valueText(legacy.leverage ?? MISSING)}</span>
          <span>legacy_live_bridge_readonly</span>
        </div>
      </div>
      {sourceNote('operator_runtime/paper_online/latest/paper_ledger_tail.json + operator_runtime/live_observer/latest')}
    </Panel>
  );
}

function PortfolioPlatformPanel({
  paperRuntime,
  truthPayload,
}: {
  paperRuntime: PaperOnlineRuntimePayload | null;
  truthPayload: OperatorTruthPayload | null;
}): JSX.Element {
  return (
    <Panel id="platform-portfolio-positions" title="Execution / Portfolio" right={<span className="chip solid-paper">Paper/read-only</span>}>
      <div className="cockpit-analytics-grid">
        <Metric label="Paper equity" value={paperRuntime?.paper_account?.equity ?? MISSING} />
        <Metric label="Realized PnL" value={paperRuntime?.paper_account?.realized_pnl ?? MISSING} />
        <Metric label="Unrealized PnL" value={paperRuntime?.paper_account?.unrealized_pnl ?? MISSING} />
        <Metric label="Open paper positions" value={paperRuntime?.paper_account?.open_position_count ?? MISSING} />
        <Metric label="Position source" value={paperRuntime?.paper_account?.position_source ?? MISSING} />
        <Metric label="Legacy trader state" value={truthPayload?.runtime_monitor_status.trader_status ?? MISSING} />
      </div>
      {sourceNote('operator_runtime/paper_online/latest/paper_positions.json and legacy observer read-only process snapshot')}
    </Panel>
  );
}
