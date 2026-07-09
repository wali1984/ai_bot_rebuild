import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useEnterpriseRealtimeResource } from '../../lib/realtime/RealtimeProvider';

interface RuntimePerformance {
  profit_factor?: number | null;
  expectancy_usd?: number | null;
  realized_pnl_usd?: number | null;
  notional_weighted_expectancy_bps?: number | null;
  win_rate?: number | null;
  closed_outcome_count?: number | null;
  governor_state?: string | null;
}

interface RuntimeEntryFreeze {
  new_entries_allowed?: boolean | null;
  halt_reasons?: string[] | null;
  future_gate_blockers?: string[] | null;
  allow_close?: boolean | null;
  allow_reduce?: boolean | null;
}

interface RuntimeAPlusGate {
  evaluated_candidates?: number | null;
  a_plus_candidates?: number | null;
  rejected_reason_matrix?: Record<string, number | null> | null;
  gate_is_hard_entry_condition?: boolean | null;
}

interface RuntimeReducedSizeBootstrap {
  final_a_plus_candidates?: number | null;
  reduced_size_bootstrap_candidates?: number | null;
  closed_rows?: number | null;
  counts_as_final_a_plus?: boolean | null;
  routes_to_live?: boolean | null;
  paper_only?: boolean | null;
  generated_at?: string | null;
  stale?: boolean | null;
}

interface RuntimeTrainerLearning {
  effective_trainer_mode?: string | null;
  online_learning_status?: string | null;
  last_successful_weight_update_at?: string | null;
  checkpoint_id?: string | null;
}

interface RuntimeTrainerQuality {
  status?: string | null;
  trusted_rows_loaded?: number | null;
  feedback_rows?: number | null;
  optimizer_steps_last_hour?: number | null;
  weights_update?: boolean | null;
  checkpoint_written?: boolean | null;
}

interface RuntimeMarketFeed {
  freshness_state?: string | null;
  source?: string | null;
  generated_at?: string | null;
  age_seconds?: number | null;
}

interface RuntimePaperLoop {
  paper_trainer_model_quality_runtime_status?: RuntimeTrainerQuality | null;
  trainer_model_quality_runtime_status?: RuntimeTrainerQuality | null;
}

interface RuntimeReadiness {
  live_gate?: string | null;
  live_ready?: boolean | null;
  order_submitted?: boolean | null;
  test_order_submitted?: boolean | null;
}

interface RuntimeHighConfidenceLossCluster {
  status?: string | null;
  active?: boolean | null;
  cluster_detected?: boolean | null;
  cluster_count?: number | null;
  high_confidence_loss_count?: number | null;
  affected_symbols?: string[] | null;
  affected_buckets?: {
    sides?: string[] | null;
    timeframes?: string[] | null;
    strategy_modes?: string[] | null;
    blocked_bucket_keys?: string[] | null;
  } | null;
  guardian_state?: string | null;
  guardian_new_entries_allowed?: boolean | null;
  reduce_size_bootstrap_allowed?: boolean | null;
  why_reduce_size_blocked?: string | null;
  post_patch_recovery_status?: string | null;
}

interface RuntimePostPatchRecovery {
  status?: string | null;
  five_trade_gate?: string | null;
  fifty_trade_gate?: string | null;
  three_hundred_trade_gate?: string | null;
}

interface RuntimePreemptiveEdgeControl {
  status?: string | null;
  candidate_count?: number | null;
  accepted_count?: number | null;
  decision_counts?: Record<string, number | null> | null;
  action_counts?: Record<string, number | null> | null;
  preemptive_action?: string | null;
  preemptive_allowed?: boolean | null;
  preemptive_block_reasons?: string[] | null;
  pre_trade_expected_net_pnl_usd?: number | null;
  pre_trade_loss_probability?: number | null;
  confidence_overstatement_risk?: number | null;
  regime_compatibility_score?: number | null;
  exit_feasibility_score?: number | null;
  bucket_profit_factor?: number | null;
  positive_edge_probation_status?: string | null;
  positive_edge_probation_supply_state?: string | null;
  positive_edge_probation_candidates?: number | null;
  positive_edge_probation_accepted?: number | null;
  closed_probation_trade_count?: number | null;
  probation_5_trade_gate_status?: string | null;
  probation_counts_as_final_a_plus?: boolean | null;
  probation_counts_as_live_ready?: boolean | null;
  why_trade_was_prevented?: string[] | null;
  governor_auto_action?: string | null;
  next_remediation?: string | null;
  hard_fail?: boolean | null;
  advanced_indicators?: RuntimeAdvancedIndicators | null;
  advanced_indicator_status?: string | null;
  advanced_indicator_block_reason_counts?: Record<string, number | null> | null;
  advanced_indicator_caution_reason_counts?: Record<string, number | null> | null;
}

interface RuntimeAdvancedIndicators {
  status?: string | null;
  candidate_count?: number | null;
  fvg_present_count?: number | null;
  fvg_side_aligned_count?: number | null;
  accepted_advanced_indicator_block_count?: number | null;
  fvg_standalone_allows_trade?: boolean | null;
  fvg_alone_can_approve_trade?: boolean | null;
  sweep_risk_can_block_or_reduce?: boolean | null;
  block_reason_counts?: Record<string, number | null> | null;
  caution_reason_counts?: Record<string, number | null> | null;
}

interface RuntimeAdaptiveHedgeCrossMargin {
  status?: string | null;
  recommended_leverage_distribution?: number[] | null;
  recommended_margin_mode_distribution?: string[] | null;
  current_notional_distribution_usd?: number[] | null;
  hedge_state?: string | null;
  hedge_rows?: number | null;
  cross_margin_state?: string | null;
  cross_margin_safe?: boolean | null;
  net_delta_usd?: number | null;
  gross_exposure_usd?: number | null;
  portfolio_liquidation_buffer_usd?: number | null;
  worst_case_portfolio_loss_usd?: number | null;
  margin_call_risk?: string | null;
  operator_display_currency?: string | null;
  operator_display_timezone?: string | null;
}

interface RuntimeProviderReadiness {
  status?: string | null;
  coinglass_status?: string | null;
  moralis_status?: string | null;
  coinglass_dashboard_color?: string | null;
  moralis_dashboard_color?: string | null;
  coinglass_actual_payload_present?: boolean | null;
  moralis_actual_payload_present?: boolean | null;
  coinglass_heartbeat_only?: boolean | null;
  moralis_heartbeat_only?: boolean | null;
  moralis_feature_bridge_ready?: boolean | null;
  moralis_feature_count?: number | null;
  moralis_required_feature_count?: number | null;
  moralis_missing_feature_flags?: string[] | null;
  moralis_stale_feature_flags?: string[] | null;
  moralis_missing_mask_true?: boolean | null;
  moralis_stale_mask_true?: boolean | null;
  moralis_token_map_count?: number | null;
  moralis_wallet_watchlist_count?: number | null;
  provider_tensor_consumption?: boolean | null;
  provider_risk_consumption?: boolean | null;
  provider_orchestrator_consumption?: boolean | null;
  provider_allocator_consumption?: boolean | null;
  provider_paper_consumption?: boolean | null;
  provider_live_dryrun_consumption?: boolean | null;
  provider_feedback_attribution?: boolean | null;
  ppo_provider_feature_count?: number | null;
  masa_provider_feature_count?: number | null;
  confluence_trade_block_score?: number | null;
  confluence_reduce_size_score?: number | null;
  confluence_hedge_required_score?: number | null;
  altdata_single_provider_can_approve?: boolean | null;
  heartbeat_only_green_allowed?: boolean | null;
  raw_keys_exposed?: boolean | null;
  invalid_subscription_blocks_core_system?: boolean | null;
}

interface PaperRuntimeStatus {
  performance?: RuntimePerformance | null;
  entry_freeze?: RuntimeEntryFreeze | null;
  a_plus_gate?: RuntimeAPlusGate | null;
  reduced_size_bootstrap?: RuntimeReducedSizeBootstrap | null;
  high_confidence_loss_cluster?: RuntimeHighConfidenceLossCluster | null;
  post_patch_recovery?: RuntimePostPatchRecovery | null;
  preemptive_edge_control?: RuntimePreemptiveEdgeControl | null;
  adaptive_hedge_cross_margin?: RuntimeAdaptiveHedgeCrossMargin | null;
  hedge_cross_margin?: RuntimeAdaptiveHedgeCrossMargin | null;
  provider_readiness?: RuntimeProviderReadiness | null;
  providers?: RuntimeProviderReadiness | null;
  trainer_learning?: RuntimeTrainerLearning | null;
  paper_loop?: RuntimePaperLoop | null;
  real_trader_readiness?: RuntimeReadiness | null;
  market_feed?: RuntimeMarketFeed | null;
  top_blockers?: string[] | null;
  source?: string | null;
  source_type?: string | null;
  generated_at?: string | null;
}

interface PortfolioRuntimeTruth {
  paper_session_id?: string | null;
  equity?: number | null;
  equity_usd?: number | null;
  paper_equity?: number | null;
  paper_balance?: number | null;
  net_pnl_usd?: number | null;
  realized_net_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  open_position_count?: number | null;
  closed_trade_count?: number | null;
  portfolio_source?: string | null;
  portfolio_source_type?: string | null;
  fallback_used?: boolean | null;
}

type RuntimeTruthSurface = 'public' | 'trader' | 'admin';

function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function text(value: unknown, fallback = 'not reported'): string {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return fallback;
}

function money(value: unknown): string {
  const parsed = num(value);
  if (parsed === null) return 'not reported';
  return `$${parsed.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fixed(value: unknown, digits = 2): string {
  const parsed = num(value);
  return parsed === null ? 'not reported' : parsed.toFixed(digits);
}

function percent(value: unknown): string {
  const parsed = num(value);
  if (parsed === null) return 'not reported';
  const pct = Math.abs(parsed) <= 1 ? parsed * 100 : parsed;
  return `${pct.toFixed(1)}%`;
}

function boolState(value: unknown, trueText: string, falseText: string): string {
  if (value === true) return trueText;
  if (value === false) return falseText;
  return 'not reported';
}

function compactAge(seconds: unknown): string {
  const parsed = num(seconds);
  if (parsed === null) return 'age not reported';
  if (parsed < 60) return `${Math.max(0, Math.round(parsed))}s`;
  if (parsed < 3600) return `${Math.round(parsed / 60)}m`;
  return `${Math.round(parsed / 3600)}h`;
}

function uniqueReasons(...groups: Array<string[] | null | undefined>): string[] {
  const reasons: string[] = [];
  for (const group of groups) {
    for (const reason of group ?? []) {
      if (reason && !reasons.includes(reason)) reasons.push(reason);
    }
  }
  return reasons;
}

function governorLabel(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value;
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return text(record.state ?? record.status);
  }
  return 'not reported';
}

function Item({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'ok' | 'warn' | 'bad';
}): JSX.Element {
  const color =
    tone === 'ok'
      ? 'var(--buy, #10b981)'
      : tone === 'warn'
        ? 'var(--warn, #f59e0b)'
        : tone === 'bad'
          ? 'var(--sell, #ef4444)'
          : 'var(--text-secondary)';

  return (
    <span
      style={{
        minWidth: 0,
        overflowWrap: 'anywhere',
        wordBreak: 'break-word',
        color: 'var(--text-muted)',
      }}
    >
      <strong style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{label}</strong>
      {' '}
      <span style={{ color }}>{value}</span>
    </span>
  );
}

export function RuntimeTruthStrip({ surface = 'trader' }: { surface?: RuntimeTruthSurface }): JSX.Element {
  const runtime = useRealtimeResource<PaperRuntimeStatus>({
    url: '/api/v2/paper/runtime-status',
    source: '/api/v2/paper/runtime-status',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'paper',
  }).envelope.data;

  const portfolio = useEnterpriseRealtimeResource<PortfolioRuntimeTruth>('portfolio')?.payload ?? null;

  const performance = runtime?.performance;
  const entryFreeze = runtime?.entry_freeze;
  const aPlusGate = runtime?.a_plus_gate;
  const reduced = runtime?.reduced_size_bootstrap;
  const highConfidenceCluster = runtime?.high_confidence_loss_cluster;
  const postPatchRecovery = runtime?.post_patch_recovery;
  const preemptive = runtime?.preemptive_edge_control;
  const trainer = runtime?.trainer_learning;
  const trainerQuality =
    runtime?.paper_loop?.paper_trainer_model_quality_runtime_status
    ?? runtime?.paper_loop?.trainer_model_quality_runtime_status
    ?? null;
  const readiness = runtime?.real_trader_readiness;
  const marketFeed = runtime?.market_feed;
  const blockers = uniqueReasons(
    runtime?.top_blockers,
    entryFreeze?.halt_reasons,
    entryFreeze?.future_gate_blockers,
  );

  const sessionId = text(portfolio?.paper_session_id, 'paper_session_id not reported');
  const equity = portfolio?.paper_equity ?? portfolio?.equity ?? portfolio?.paper_balance ?? portfolio?.equity_usd;
  const newEntriesAllowed = entryFreeze?.new_entries_allowed;
  const liveReady = readiness?.live_ready;
  const liveGate = text(readiness?.live_gate, 'blocked_human_only');
  const finalAPlusRows = reduced?.final_a_plus_candidates ?? aPlusGate?.a_plus_candidates;
  const reduceRows = reduced?.reduced_size_bootstrap_candidates ?? reduced?.closed_rows;
  const highConfidenceClusterActive =
    highConfidenceCluster?.active === true || highConfidenceCluster?.cluster_detected === true;
  const highConfidenceClusterCount =
    highConfidenceCluster?.cluster_count ?? highConfidenceCluster?.high_confidence_loss_count;
  const affectedBuckets = [
    ...(highConfidenceCluster?.affected_buckets?.sides ?? []).map((value) => `side:${value}`),
    ...(highConfidenceCluster?.affected_buckets?.timeframes ?? []).map((value) => `tf:${value}`),
    ...(highConfidenceCluster?.affected_buckets?.strategy_modes ?? []).map((value) => `strategy:${value}`),
  ];
  const affectedBucketText =
    affectedBuckets.length > 0
      ? affectedBuckets.slice(0, 4).join(', ')
      : (highConfidenceCluster?.affected_symbols ?? []).slice(0, 4).join(', ') || 'none reported';
  const feedbackRows = trainerQuality?.feedback_rows ?? trainerQuality?.trusted_rows_loaded;
  const microstructureBlocks = aPlusGate?.rejected_reason_matrix?.microstructure_trust_confirms;
  const whyBlocked = blockers.length > 0 ? blockers.slice(0, 3).join(', ') : 'no blocker reported';
  const preventedReasons = preemptive?.why_trade_was_prevented ?? [];
  const whyPrevented =
    preventedReasons.length > 0
      ? preventedReasons.slice(0, 3).join(', ')
      : 'no prevented trade reason reported';
  const blockedPreemptiveCount =
    (num(preemptive?.decision_counts?.['NO_TRADE']) ?? 0)
    + (num(preemptive?.decision_counts?.['SHADOW_ONLY']) ?? 0);
  const probationCandidates = num(preemptive?.positive_edge_probation_candidates) ?? 0;
  const probationAccepted = num(preemptive?.positive_edge_probation_accepted) ?? 0;
  const probationClosed = num(preemptive?.closed_probation_trade_count) ?? 0;
  const probationSupplyState = text(preemptive?.positive_edge_probation_supply_state);
  const advanced = preemptive?.advanced_indicators;
  const hedgeCrossMargin = runtime?.adaptive_hedge_cross_margin ?? runtime?.hedge_cross_margin;
  const providers = runtime?.provider_readiness ?? runtime?.providers;
  const advancedStatus = text(advanced?.status ?? preemptive?.advanced_indicator_status);
  const advancedFvgCount = num(advanced?.fvg_present_count) ?? 0;
  const acceptedAdvancedBlocks = num(advanced?.accepted_advanced_indicator_block_count) ?? 0;
  const advancedBlockReasons = advanced?.block_reason_counts ?? preemptive?.advanced_indicator_block_reason_counts ?? {};
  const topAdvancedBlocker =
    Object.entries(advancedBlockReasons)
      .sort((a, b) => (num(b[1]) ?? 0) - (num(a[1]) ?? 0))[0]?.[0] ?? 'none';
  const background =
    surface === 'admin'
      ? 'color-mix(in oklch, var(--bg-elevated) 90%, var(--admin-bg, var(--bg-base)))'
      : 'var(--bg-elevated)';

  return (
    <section
      aria-label="Runtime truth"
      data-testid={`runtime-truth-strip-${surface}`}
      data-paper-session-id={sessionId}
      data-new-entries-allowed={newEntriesAllowed === true ? 'true' : 'false'}
      data-live-gate={liveGate}
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(165px, 1fr))',
        gap: '4px 12px',
        alignItems: 'center',
        padding: '7px 16px',
        borderBottom: '1px solid var(--border)',
        background,
        color: 'var(--text-secondary)',
        fontSize: 11,
        lineHeight: 1.35,
        fontFamily: 'var(--font-mono)',
      }}
    >
      <Item label="paper_session_id" value={sessionId} />
      <Item label="paper equity" value={money(equity)} />
      <Item
        label="new_entries_allowed"
        value={boolState(newEntriesAllowed, 'true', 'false halted')}
        tone={newEntriesAllowed ? 'ok' : 'bad'}
      />
      <Item label="governor" value={governorLabel(performance?.governor_state)} tone="bad" />
      <Item label="PF" value={fixed(performance?.profit_factor, 3)} tone={(num(performance?.profit_factor) ?? 0) >= 1 ? 'ok' : 'bad'} />
      <Item
        label="Expectancy"
        value={`${money(performance?.expectancy_usd)} avg/trade`}
        tone={(num(performance?.expectancy_usd) ?? -1) > 0 ? 'ok' : 'bad'}
      />
      <Item label="Realized PnL" value={money(performance?.realized_pnl_usd)} tone={(num(performance?.realized_pnl_usd) ?? 0) >= 0 ? 'ok' : 'bad'} />
      <Item label="Win rate" value={percent(performance?.win_rate)} />
      <Item label="A+ final rows" value={`${text(finalAPlusRows, '0')} / evaluated ${text(aPlusGate?.evaluated_candidates, '0')}`} tone={(num(finalAPlusRows) ?? 0) > 0 ? 'ok' : 'warn'} />
      <Item
        label="REDUCE_SIZE bootstrap rows"
        value={`${text(reduceRows, '0')} · paper-only · final A+ ${boolState(reduced?.counts_as_final_a_plus, 'true', 'false')}`}
        tone={reduced?.counts_as_final_a_plus ? 'bad' : 'warn'}
      />
      <Item
        label="High-confidence loss cluster"
        value={`${highConfidenceClusterActive ? 'active' : 'inactive'} · count ${text(highConfidenceClusterCount, '0')}`}
        tone={highConfidenceClusterActive ? 'bad' : 'ok'}
      />
      <Item
        label="Affected buckets"
        value={affectedBucketText}
        tone={highConfidenceClusterActive ? 'bad' : 'neutral'}
      />
      <Item
        label="REDUCE_SIZE allowed"
        value={`${boolState(highConfidenceCluster?.reduce_size_bootstrap_allowed, 'true', 'false blocked')} · ${text(highConfidenceCluster?.why_reduce_size_blocked, 'policy gate')}`}
        tone={highConfidenceCluster?.reduce_size_bootstrap_allowed ? 'warn' : 'bad'}
      />
      <Item
        label="Post-patch recovery"
        value={text(postPatchRecovery?.status ?? highConfidenceCluster?.post_patch_recovery_status)}
        tone={highConfidenceClusterActive ? 'bad' : 'warn'}
      />
      <Item
        label="Preemptive action"
        value={text(preemptive?.preemptive_action)}
        tone={preemptive?.preemptive_allowed ? 'ok' : blockedPreemptiveCount > 0 ? 'bad' : 'neutral'}
      />
      <Item
        label="Pre-trade loss risk"
        value={`${fixed(preemptive?.pre_trade_loss_probability, 3)} · blocked ${blockedPreemptiveCount}`}
        tone={(num(preemptive?.pre_trade_loss_probability) ?? 0) >= 0.8 ? 'bad' : blockedPreemptiveCount > 0 ? 'warn' : 'neutral'}
      />
      <Item
        label="Confidence overstatement"
        value={fixed(preemptive?.confidence_overstatement_risk, 3)}
        tone={(num(preemptive?.confidence_overstatement_risk) ?? 0) >= 0.75 ? 'bad' : 'neutral'}
      />
      <Item
        label="Regime compatibility"
        value={fixed(preemptive?.regime_compatibility_score, 3)}
        tone={(num(preemptive?.regime_compatibility_score) ?? 1) < 0.45 ? 'bad' : 'neutral'}
      />
      <Item
        label="Exit feasibility"
        value={fixed(preemptive?.exit_feasibility_score, 3)}
        tone={(num(preemptive?.exit_feasibility_score) ?? 1) < 0.55 ? 'bad' : 'neutral'}
      />
      <Item
        label="Bucket health"
        value={`PF ${fixed(preemptive?.bucket_profit_factor, 3)} · ${text(preemptive?.status)}`}
        tone={(num(preemptive?.bucket_profit_factor) ?? 1) < 1 ? 'bad' : 'neutral'}
      />
      <Item
        label="Adaptive leverage"
        value={`${(hedgeCrossMargin?.recommended_leverage_distribution ?? []).join(', ') || 'none'}x · notional ${money((hedgeCrossMargin?.current_notional_distribution_usd ?? [])[0])}`}
        tone={(hedgeCrossMargin?.recommended_leverage_distribution ?? []).some((value) => value > 1) ? 'warn' : 'neutral'}
      />
      <Item
        label="Hedge / delta"
        value={`${text(hedgeCrossMargin?.hedge_state)} · net ${money(hedgeCrossMargin?.net_delta_usd)} · gross ${money(hedgeCrossMargin?.gross_exposure_usd)}`}
        tone={text(hedgeCrossMargin?.hedge_state) === 'NO_HEDGE' ? 'neutral' : 'warn'}
      />
      <Item
        label="Cross-margin simulation"
        value={`${boolState(hedgeCrossMargin?.cross_margin_safe, 'safe', 'isolated/no trade')} · ${text(hedgeCrossMargin?.margin_call_risk)} risk`}
        tone={hedgeCrossMargin?.cross_margin_safe ? 'warn' : 'neutral'}
      />
      <Item
        label="Provider actual data"
        value={`CG ${text(providers?.coinglass_dashboard_color, text(providers?.coinglass_status))}/${boolState(providers?.coinglass_actual_payload_present, 'actual', 'no actual')} · Moralis ${text(providers?.moralis_dashboard_color, text(providers?.moralis_status))}/${boolState(providers?.moralis_actual_payload_present, 'actual', 'no actual')}`}
        tone={providers?.raw_keys_exposed || providers?.invalid_subscription_blocks_core_system ? 'bad' : 'neutral'}
      />
      <Item
        label="Provider consumer proof"
        value={`tensor ${boolState(providers?.provider_tensor_consumption, 'yes', 'no')} · risk ${boolState(providers?.provider_risk_consumption, 'yes', 'no')} · alloc ${boolState(providers?.provider_allocator_consumption, 'yes', 'no')} · paper ${boolState(providers?.provider_paper_consumption, 'yes', 'no')} · live dry-run ${boolState(providers?.provider_live_dryrun_consumption, 'yes', 'no')}`}
        tone={
          providers?.provider_tensor_consumption &&
          providers?.provider_risk_consumption &&
          providers?.provider_allocator_consumption &&
          providers?.provider_paper_consumption
            ? 'neutral'
            : 'warn'
        }
      />
      <Item
        label="Alt-data confluence"
        value={`PPO ${fixed(providers?.ppo_provider_feature_count, 0)} · MASA ${fixed(providers?.masa_provider_feature_count, 0)} · block ${fixed(providers?.confluence_trade_block_score, 3)} · reduce ${fixed(providers?.confluence_reduce_size_score, 3)} · hedge ${fixed(providers?.confluence_hedge_required_score, 3)} · standalone ${boolState(providers?.altdata_single_provider_can_approve, 'allowed', 'blocked')}`}
        tone={providers?.altdata_single_provider_can_approve ? 'bad' : 'neutral'}
      />
      <Item
        label="Why trade was prevented"
        value={whyPrevented}
        tone={blockedPreemptiveCount > 0 || preemptive?.hard_fail ? 'bad' : 'neutral'}
      />
      <Item
        label="Positive-edge probation"
        value={`${probationSupplyState} · candidates ${probationCandidates} · accepted ${probationAccepted}`}
        tone={probationCandidates > 0 ? 'warn' : 'bad'}
      />
      <Item
        label="Probation 5-trade gate"
        value={`${text(preemptive?.probation_5_trade_gate_status)} · closes ${probationClosed}`}
        tone="warn"
      />
      <Item
        label="Probation proof flags"
        value={`final A+ ${boolState(preemptive?.probation_counts_as_final_a_plus, 'true', 'false')} · live ${boolState(preemptive?.probation_counts_as_live_ready, 'true', 'false')}`}
        tone={preemptive?.probation_counts_as_final_a_plus || preemptive?.probation_counts_as_live_ready ? 'bad' : 'neutral'}
      />
      <Item
        label="Governor auto-action"
        value={text(preemptive?.governor_auto_action)}
        tone={preemptive?.governor_auto_action?.includes('halt') ? 'bad' : 'neutral'}
      />
      <Item
        label="Next remediation"
        value={text(preemptive?.next_remediation)}
        tone="warn"
      />
      <Item
        label="Trainer"
        value={`${text(trainer?.online_learning_status)} · feedback rows ${text(feedbackRows, '0')}`}
        tone={trainer?.online_learning_status === 'WEIGHTS_UPDATING' ? 'ok' : 'warn'}
      />
      <Item
        label="Market data freshness"
        value={`${text(marketFeed?.freshness_state)} · ${compactAge(marketFeed?.age_seconds)} · source ${text(marketFeed?.source)}`}
      />
      <Item
        label="Microstructure trust"
        value={`blocked rows ${text(microstructureBlocks, '0')} · public book alone not final A+`}
        tone={(num(microstructureBlocks) ?? 0) > 0 ? 'warn' : 'ok'}
      />
      <Item
        label="Advanced Market Structure"
        value={`${advancedStatus} · FVG ${advancedFvgCount}`}
        tone={advancedStatus.includes('BLOCK') ? 'bad' : advancedStatus.includes('WAITING') ? 'warn' : 'neutral'}
      />
      <Item
        label="Liquidity Sweep Risk"
        value={`can block/reduce ${boolState(advanced?.sweep_risk_can_block_or_reduce, 'true', 'false')} · accepted blocks ${acceptedAdvancedBlocks}`}
        tone={acceptedAdvancedBlocks > 0 ? 'bad' : 'neutral'}
      />
      <Item
        label="FVG Zones"
        value={`standalone approval ${boolState(advanced?.fvg_alone_can_approve_trade ?? advanced?.fvg_standalone_allows_trade, 'true', 'false')} · blocker ${topAdvancedBlocker}`}
        tone={(advanced?.fvg_alone_can_approve_trade ?? advanced?.fvg_standalone_allows_trade) ? 'bad' : 'neutral'}
      />
      <Item label="Live gate" value={liveGate} tone={liveGate.includes('blocked') ? 'bad' : 'warn'} />
      <Item
        label="Real trader readiness"
        value={boolState(liveReady, 'live_ready true', 'live_ready false')}
        tone={liveReady ? 'warn' : 'bad'}
      />
      <Item label="Top blockers" value={whyBlocked} tone={blockers.length > 0 ? 'bad' : 'ok'} />
      <Item label="Why blocked" value={whyBlocked} tone={blockers.length > 0 ? 'bad' : 'ok'} />
    </section>
  );
}
