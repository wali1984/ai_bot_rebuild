import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Panel } from '../cockpitComponents';
import { fmtAge, usePayloadFile } from '../../hooks/usePayloadFile';

const BASE = '/operator_runtime/v2_zero_budget_orderbook/latest';

interface ProviderDecision {
  generated_at?: string;
  coinapi_renewal_required?: boolean;
  tardis_purchase_required?: boolean;
  primary_live_orderbook_source?: string;
  historical_l2_gap_status?: string;
  coinank_remains_derivatives_liquidation_source?: boolean;
  live_gate?: string;
}

interface ReplayStore {
  generated_at?: string;
  recorder_active?: boolean;
  active_exchanges?: string[];
  symbols_recorded?: number;
  symbols_by_exchange?: Record<string, string[]>;
  raw_delta_symbol_count?: number;
  feature_only_symbol_count?: number;
  sequence_gap_symbols?: string[];
  historical_sequence_gap_symbols?: string[];
  direct_feed_coverage?: DirectFeedCoverage;
  configured_symbol_coverage?: ConfiguredSymbolCoverage;
  disk_usage?: number;
  oldest_replay_timestamp?: string | null;
  newest_replay_timestamp?: string | null;
}

interface ConfiguredSymbolCoverage {
  configured_symbol_count?: number;
  complete_symbols?: string[];
  incomplete_symbols?: string[];
  all_configured_symbols_have_required_direct_feed_coverage?: boolean;
}

interface DirectFeedCoverage {
  binance_book_ticker_persisted?: boolean;
  binance_partial_depth_5_10_20_persisted?: boolean;
  binance_diff_depth_persisted?: boolean;
  binance_100ms_depth_persisted?: boolean;
  binance_250ms_depth_persisted?: boolean;
  binance_depth_levels?: Array<number | string>;
  binance_feed_speeds_ms?: Array<number | string>;
  kucoin_best_5_50_persisted?: boolean;
  kucoin_increment_best_500_persisted?: boolean;
  kucoin_100ms_depth_persisted?: boolean;
  kucoin_10ms_increment_persisted?: boolean;
  kucoin_depth_levels?: Array<number | string>;
  kucoin_feed_speeds_ms?: Array<number | string>;
}

interface ConsumptionStatus {
  generated_at?: string;
  source?: string;
  orderbook_feature_rows?: number;
  trainer_tensor_includes_orderbook_fields?: boolean;
  allocator_uses_real_spread_depth_price_impact?: boolean;
  paper_fills_have_real_spread_source?: boolean;
  paper_fills_have_real_depth_source?: boolean;
  paper_fills_have_slippage_source?: boolean;
}

function yesNo(value: unknown): string {
  return value === true ? 'YES' : value === false ? 'NO' : 'PENDING';
}

function StatusMetric({ label, value }: { label: string; value: string | number | null | undefined }): JSX.Element {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value ?? '—'}</span>
    </div>
  );
}

function listValue(values: Array<number | string> | string[] | null | undefined): string {
  return values && values.length > 0 ? values.join(', ') : '—';
}

function symbolCoverage(value: Record<string, string[]> | null | undefined): string {
  if (!value) return '—';
  const rows = Object.entries(value).map(([exchange, symbols]) => `${exchange}:${symbols.length}`);
  return rows.length > 0 ? rows.join(' ') : '—';
}

export default function OrderbookRuntimeTruthPage(): JSX.Element {
  const provider = usePayloadFile<ProviderDecision>(`${BASE}/zero_budget_provider_decision_status.json`, 15_000);
  const replay = usePayloadFile<ReplayStore>(`${BASE}/local_orderbook_replay_store_status.json`, 15_000);
  const trainer = usePayloadFile<ConsumptionStatus>(`${BASE}/trainer_orderbook_feature_consumption_status.json`, 15_000);
  const allocator = usePayloadFile<ConsumptionStatus>(`${BASE}/allocator_orderbook_consumption_status.json`, 15_000);
  const paper = usePayloadFile<ConsumptionStatus>(`${BASE}/paper_fill_orderbook_cost_evidence_status.json`, 15_000);
  const coverage = replay.data?.direct_feed_coverage;

  return (
    <article
      className="enterprise-cockpit-page"
      style={{
        background:
          'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)',
      }}
      data-testid="page-orderbook-runtime-truth"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Direct Feed Coverage</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="hero-meta">
          <span className="badge badge--neutral">LIVE_GATE: {provider.data?.live_gate ?? 'blocked_human_only'}</span>
        </div>
      </header>

      <Panel id="orderbook-provider-health" title="Orderbook Provider Health" right={<span className="chip">Updated {fmtAge(provider.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <StatusMetric label="CoinAPI required" value={yesNo(provider.data?.coinapi_renewal_required)} />
          <StatusMetric label="Tardis required" value={yesNo(provider.data?.tardis_purchase_required)} />
          <StatusMetric label="Primary source" value={provider.data?.primary_live_orderbook_source} />
          <StatusMetric label="Historical L2" value={provider.data?.historical_l2_gap_status} />
          <StatusMetric label="CoinAnk context" value={yesNo(provider.data?.coinank_remains_derivatives_liquidation_source)} />
        </div>
      </Panel>

      <Panel id="direct-feed-coverage" title="Direct Feed Coverage" right={<span className="chip">Replay {fmtAge(replay.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <StatusMetric label="Direct feeds active" value={yesNo(replay.data?.recorder_active)} />
          <StatusMetric label="Active exchanges" value={listValue(replay.data?.active_exchanges)} />
          <StatusMetric label="Symbols by exchange" value={symbolCoverage(replay.data?.symbols_by_exchange)} />
          <StatusMetric label="Symbols covered" value={replay.data?.symbols_recorded} />
          <StatusMetric label="Configured symbols" value={replay.data?.configured_symbol_coverage?.configured_symbol_count} />
          <StatusMetric label="Complete configured symbols" value={listValue(replay.data?.configured_symbol_coverage?.complete_symbols)} />
          <StatusMetric label="Incomplete configured symbols" value={listValue(replay.data?.configured_symbol_coverage?.incomplete_symbols)} />
          <StatusMetric label="Raw delta symbols" value={replay.data?.raw_delta_symbol_count} />
          <StatusMetric label="Feature-only symbols" value={replay.data?.feature_only_symbol_count} />
          <StatusMetric label="Current sequence gaps" value={listValue(replay.data?.sequence_gap_symbols)} />
          <StatusMetric label="Historical sequence gaps" value={listValue(replay.data?.historical_sequence_gap_symbols)} />
          <StatusMetric label="Disk bytes" value={replay.data?.disk_usage} />
          <StatusMetric label="Oldest replay" value={replay.data?.oldest_replay_timestamp} />
          <StatusMetric label="Newest replay" value={replay.data?.newest_replay_timestamp} />
        </div>
      </Panel>

      <Panel id="direct-feed-type-coverage" title="Direct Feed Type Coverage">
        <div className="cockpit-analytics-grid">
          <StatusMetric label="Binance book ticker" value={yesNo(coverage?.binance_book_ticker_persisted)} />
          <StatusMetric label="Binance depth 5/10/20" value={yesNo(coverage?.binance_partial_depth_5_10_20_persisted)} />
          <StatusMetric label="Binance diff depth" value={yesNo(coverage?.binance_diff_depth_persisted)} />
          <StatusMetric label="Binance 100ms" value={yesNo(coverage?.binance_100ms_depth_persisted)} />
          <StatusMetric label="Binance 250ms" value={yesNo(coverage?.binance_250ms_depth_persisted)} />
          <StatusMetric label="Binance levels" value={listValue(coverage?.binance_depth_levels)} />
          <StatusMetric label="KuCoin best 5/50" value={yesNo(coverage?.kucoin_best_5_50_persisted)} />
          <StatusMetric label="KuCoin increment" value={yesNo(coverage?.kucoin_increment_best_500_persisted)} />
          <StatusMetric label="KuCoin 100ms" value={yesNo(coverage?.kucoin_100ms_depth_persisted)} />
          <StatusMetric label="KuCoin 10ms" value={yesNo(coverage?.kucoin_10ms_increment_persisted)} />
          <StatusMetric label="KuCoin levels" value={listValue(coverage?.kucoin_depth_levels)} />
          <StatusMetric label="Configured coverage complete" value={yesNo(replay.data?.configured_symbol_coverage?.all_configured_symbols_have_required_direct_feed_coverage)} />
        </div>
      </Panel>

      <Panel id="orderbook-feature-consumption" title="Orderbook Feature Consumption">
        <div className="cockpit-analytics-grid">
          <StatusMetric label="Trainer rows" value={trainer.data?.orderbook_feature_rows} />
          <StatusMetric label="Trainer tensor fields" value={yesNo(trainer.data?.trainer_tensor_includes_orderbook_fields)} />
          <StatusMetric label="Allocator real cost" value={yesNo(allocator.data?.allocator_uses_real_spread_depth_price_impact)} />
          <StatusMetric label="Paper spread source" value={yesNo(paper.data?.paper_fills_have_real_spread_source)} />
          <StatusMetric label="Paper depth source" value={yesNo(paper.data?.paper_fills_have_real_depth_source)} />
          <StatusMetric label="Paper slippage source" value={yesNo(paper.data?.paper_fills_have_slippage_source)} />
        </div>
      </Panel>
    </article>
  );
}
