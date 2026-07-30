# Operator validation and monitoring runbook — adaptive paper repair

**Applies to:** the 2026-07-17 trainer/orchestrator/allocator/paper-risk/accounting repair

**Current decision:** **NO-GO for live and FAIL for A+**

**Safety boundary:** this runbook observes or validates the paper/shadow system. It does not authorize a live order, cancellation, modification, exchange leverage/margin change, credential test, or live-gate enablement.

The 1000x-in-90-days value is an objective tracker, not a guaranteed result. A+ has not been achieved. The current measured paper state remains `HALTED_PERFORMANCE` with 23 governed post-repair closes, PF about 0.704, weighted expectancy about −7.701 bps, and trajectory constraint `NO_A_PLUS_SUPPLY`. The operator's first job is to protect temporal, risk, accounting, and position truth. Scaling a negative edge only compounds losses faster.

## 1. Truth order

When sources disagree, use this order:

1. exact source and current Git/worktree provenance;
2. effective installed service and active process state;
3. fresh raw Redis records and TTLs;
4. immutable per-ID lineage records;
5. isolated test output;
6. derived heartbeat/dashboard/artifact;
7. historical worklog or prose.

A dashboard PASS never overrides a fresh raw FAIL. A source fix is not deployed until the intended worker is reloaded and emits new attributable records. Historical rows are not repaired by changing their display fields.

## 2. Before every validation window

Run from the repository root:

```bash
git status --short --branch
git rev-parse HEAD
git log -1 --date=iso-strict --format='%H %ad %s'
git diff --stat
```

Record the exact commit and dirty files. Do not assume a moving worktree is a stable release. Do not discard, reset, checkout, stage, or commit unrelated concurrent work.

Check only safe service-state properties:

```bash
systemctl --user is-active \
  ai-bot-v2-orchestrator-arbitration-loop.service \
  ai-bot-v2-risk-gateway-live-loop.service \
  ai-bot-v2-trade-management-paper-loop.service \
  ai-bot-v2-native-cuda-trainer-persistent.service
```

`active` proves only that systemd sees a running unit; it does not prove correct code, current Redis, or successful learning.

Security restriction: do not inspect or copy tunnel process command lines, `ExecStart`, environment, or raw status output when it can contain a credential. A cloudflared credential was exposed in diagnostic output during this audit. Rotate/revoke it through the provider and move it to protected credential handling. Never paste its value into tickets, logs, commands, or documentation.

## 3. Confirm the non-live boundary first

```bash
redis-cli --raw GET v2:live_gate:state | jq '{
  live_gate,trader_execution_enabled,live_symbols,execution_live_symbols,
  operator_approved,order_transport_submit_enabled,places_real_order
}'

redis-cli --raw GET v2:trader:execution_state | jq '{
  live_gate,trader_execution_enabled,live_symbols,execution_live_symbols,
  operator_approved,order_transport_submit_enabled,places_real_order
}'

redis-cli --raw GET v2:goal:trajectory_1000x | jq '{
  generated_utc,paper_only,places_real_order,routes_to_live,live_gate,
  equity_usd,multiple_now,on_track,binding_constraint
}'

redis-cli --raw GET v2:paper:performance_circuit_breaker_status | jq '{
  generated_utc,paper_only,places_real_order,routes_to_live,live_path_changed,
  state,new_entries_allowed,block_reasons
}'
```

Required fail-closed state:

```text
paper_only=true
trader_execution_enabled=false
live_symbols=[]
execution_live_symbols=[]
operator_approved=false
order_transport_submit_enabled=false where the field exists
places_real_order=false
routes_to_live=false
live_gate=blocked_human_only
live_path_changed=false where the field exists
```

Immediately before the approved paper-worker restart in this audit, both authoritative gate surfaces satisfied that disabled shape. That is a prerequisite snapshot, not a standing guarantee; re-read both keys after every restart and stop if they disagree.

Stop and escalate if any field changes unexpectedly. Do not “test” the state by attempting an order.

## 4. Freshness and TTL

```bash
for key in \
  v2:prediction:BTCUSDT:1m \
  v2:orchestrator:decisions \
  v2:signals:paper \
  v2:risk:gateway:decisions \
  v2:risk:gateway:heartbeat \
  v2:paper:ledger \
  v2:paper:closed_trades \
  v2:paper:performance_circuit_breaker_status
do
  printf '%s type=' "$key"
  redis-cli --raw TYPE "$key"
  printf '%s ttl=' "$key"
  redis-cli --raw TTL "$key"
done
```

`TTL=-2` means absent; `TTL=-1` means no expiry. Presence without a current `generated_utc` is not freshness proof. A missing per-ID decision must block/pending, never fall back to local PASS.

## 5. Prediction and point-in-time audit

Inspect one prediction without dumping its full tensor:

```bash
redis-cli --raw GET v2:prediction:BTCUSDT:1m | jq '{
  prediction_id,decision_id,symbol,timeframe,selected_action,
  available_at,feature_cutoff,decision_time,feature_snapshot_id,
  candle_closed_confirmed,candle_open_time,candle_close_time,
  masa_feature_cutoff,ppo_feature_cutoff,ppo_decision_time,
  behavior_policy_sampling_mode,behavior_policy_distribution_contract,
  ppo_on_policy_entry_fields_present,ppo_on_policy_ineligible_reason,
  replay_snapshot_id,replay_snapshot_key,replay_snapshot_write_success,
  trust_gate_result,routes_to_orchestrator,routes_to_orchestrator_reason,
  paper_fill_allowed,paper_fill_gate_block_reasons
}'
```

Required invariants:

- every contributing candle is final;
- every source `available_at <= decision_time`;
- newest contributing cutoff `<= decision_time`;
- MASA `feature_cutoff <= PPO decision_time`;
- replay write succeeded when required.

For a post-repair prediction, the exact trust-row finality and per-model cutoff fields must also appear at top level and remain identical when copied into orchestrator/risk/signal lineage. Missing `candle_closed_confirmed` must never be inferred from close time or current time. It must leave `routes_to_orchestrator=false` and `paper_fill_allowed=false`. The 18:16:27 UTC BTCUSDT row was a safely blocked pre-reload shape. At 18:44:20 UTC a new row carried exact finality/cutoffs, valid ordering, and successful replay metadata but remained blocked for explicit gate reasons. Use that as prediction-stage deployment evidence only; wait for a routeable row before asserting downstream equality.

Reject/quarantine a missing or future value. Never replace a missing timestamp with `generated_utc`, list order, current time, or another stage's timestamp.

The current selector is expected to report:

```text
behavior_policy_sampling_mode=DETERMINISTIC_ARGMAX_ALIGNMENT
behavior_policy_distribution_contract=EXPECTED_MOVE_ALIGNED_POLICY_V1
ppo_on_policy_entry_fields_present=false
ppo_on_policy_ineligible_reason=DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED
```

That is the truthful success shape. Do not change those fields to `CATEGORICAL_SAMPLE`/`RAW_LOGITS_SOFTMAX_V1` unless the action generator actually sampled that exact distribution. Paper persistence and closed feedback must retain the original contract.

## 6. HOLD, direction, and canonical IDs

```bash
redis-cli --raw GET v2:orchestrator:decisions | jq '{
  generated_utc,considered_count,
  winner_count:(.bucket_winners|length),held_by_paper_fill_gate_count,
  held_actions:[.held_by_paper_fill_gate[]? | {
    prediction_id,selected_action,side,paper_fill_allowed,risk_decision_id,
    routes_to_risk_gateway,paper_fill_gate_status
  }]
}'

redis-cli --raw GET v2:signals:paper | jq '[.[] | {
  prediction_id,selected_action,side,
  expected_move_after_cost_bps_signed,
  expected_move_after_cost_bps_directional,
  orchestrator_decision_id,risk_decision_id,
  paper_fill_allowed,paper_fill_gate_status
}] | .[:20]'
```

Expected:

- HOLD/flat/close/hedge is held with `side=flat`, no risk ID, and no risk route;
- only long/short is routeable;
- long directional edge equals signed edge; short directional edge is its negative;
- `risk_decision_id = "rd_" + orchestrator_decision_id`;
- orchestrator output remains `paper_fill_allowed=false`, `RISK_PENDING`.

Any HOLD-derived long/short entry is a P0 stop-the-line event.

If the aggregate signal array is empty, bounded per-symbol discovery must still work from the canonical runtime universe. Inspect only the intended symbols/timeframes—do not full-scan the large Redis database:

```bash
for key in \
  v2:signals:paper:BTCUSDT \
  v2:signals:paper:BTCUSDT:1m \
  v2:signals:paper:BTCUSDT:5m \
  v2:signals:paper:BTCUSDT:15m \
  v2:signals:paper:BTCUSDT:1h \
  v2:signals:paper:BTCUSDT:4h
do
  printf '%s type=' "$key"
  redis-cli --raw TYPE "$key"
done
```

Finding a per-symbol row proves discovery only. `open_long`, `open_short`, `proceed_long`, or `proceed_short` may normalize the paper-only orchestrator stage to PASS, but canonical risk must still resolve independently to ALLOW. Missing A+/preemptive evidence must remain blocked.

Inspect the three Redis contexts whose A+ freshness check now has the strict generation/availability contract:

```bash
for key in \
  v2:regime:gate:BTCUSDT:1m \
  v2:context:htf:BTCUSDT \
  v2:market:trade_tape_features:BTCUSDT
do
  printf '%s\n' "$key"
  redis-cli --raw GET "$key" | jq '{
    generated_utc,generated_at,generated_est,available_at,
    regime,fail_closed,source,status
  }'
done
```

Every supplied clock must include an explicit timezone offset, be no later than the A+ evaluation time, and lie within the configured age. Multiple generation aliases must represent the exact same instant. A supplied `available_at` must be no earlier than generation. Missing `available_at` is still accepted for legacy context rows, so record it as a compatibility gap rather than inventing availability from generation. These checks cover regime/HTF/tape only; do not infer that cross-asset, microstructure, trainer, side-performance, feedback, prediction-feature, allocation, or materialization clocks were thereby certified.

For a new paper intent, inspect the frozen entry/preemptive receipts rather than rereading current Redis and assuming it is the old decision state:

```bash
redis-cli --raw GET v2:paper:intents | jq '[.[]? | {
  symbol,timeframe,prediction_id,
  entry_snapshot_hash:.paper_entry_gate_snapshot_hash,
  entry_snapshot:.paper_entry_gate_snapshot,
  entry_evaluation_hash:.paper_entry_gate_evaluation_hash,
  entry_evaluation:.paper_entry_gate_evaluation,
  preemptive_decision_id,
  preemptive_input_schema_version,preemptive_input_hash,
  preemptive_input_hash_algorithm,
  preemptive_decision_time,preemptive_decision_time_source,
  preemptive_decision_time_input_valid,
  adaptive_tuning_state_status,adaptive_tuning_state_hash,
  adaptive_loss_probability_threshold_used,
  adaptive_loss_probability_threshold_source,
  adaptive_microstructure_trust_threshold_used,
  adaptive_microstructure_trust_threshold_source
}] | .[:25]'
```

Require entry schema `paper_entry_gate_preloaded_evaluation_v1`, `runtime_evidence_preloaded=true`, nonblank 64-lower-hex snapshot/evaluation hashes, a source-specific confidence-floor label, and identical evaluation receipt/hash across intent, allocation/model inputs, and risk. Relevant missing evidence must block with `RUNTIME_EVIDENCE_PRELOAD_MISSING:*`. Require preemptive SHA-256 fields, aware evaluator-owned time, input-valid true, and a decision ID bound to the full input hash. For the same nonempty tuning snapshot, `adaptive_tuning_state_hash` must equal `paper_entry_gate_snapshot.adaptive_tuning.payload_hash`; it is not expected to equal the wider `preemptive_input_hash`. Stop if a fresh paper row uses the legacy entry read-through path, lacks either receipt, carries a partial candidate hash after materialization failure, or is accepted with invalid/naive time.

## 7. Risk correlation and authority

```bash
redis-cli --raw GET v2:risk:gateway:decisions | jq '{
  count:length,
  actions:(group_by(.risk_action)|map({action:.[0].risk_action,count:length})),
  sample:[.[:5][] | {
    prediction_id,orchestrator_decision_id,risk_decision_id,risk_action,
    risk_reason_code,generated_utc
  }]
}'

risk_id="$(redis-cli --raw GET v2:signals:paper | jq -r '.[0].risk_decision_id // empty')"
test -n "$risk_id"
redis-cli --raw GET "v2:decision:risk:$risk_id" | jq '{
  schema_version,producer,risk_decision_id,canonical_risk_decision_id,alias_of,
  candidate_id,prediction_id,
  symbol,timeframe,side,risk_action,reasons,generated_utc,expires_at,
  candle_closed_confirmed,candle_close_time,masa_feature_cutoff,
  ppo_feature_cutoff,ppo_decision_time,routes_to_live,places_real_order
}'
```

The expected live-oriented gateway state is `risk_action=deny` while live is disabled. That is healthy fail-closed behavior. Ordinary A+ must not accept it. A paper exploration row may exist only through its explicit bounded policy and must remain paper-only/exploration evidence—not canonical live-risk approval.

Trainer preview keys are never authority:

```bash
redis-cli --raw GET v2:trainer:hybrid_cuda:risk_decision_preview | jq '{
  authoritative_decision,record_authority,proposal_source,
  risk_decision_id,risk_action,routes_to_live,places_real_order
}'
```

Required trainer shape is `authoritative_decision=false` and `record_authority=TRAINER_NON_AUTHORITATIVE_PROPOSAL`. The trainer must write zero keys under `v2:decision:risk:*`, `v2:decision:orchestrator:*`, and `v2:decision:index:*`; do not use a broad Redis `KEYS` scan to prove this on the large database. Verify source/test ownership and inspect only exact candidate IDs. The risk gateway must be the producer on a canonical risk row. A missing canonical `v2:decision:orchestrator:{id}` must fail closed; the audited orchestrator source has not yet proven that per-ID persistence.

For a legacy alias key, embedded `risk_decision_id` must equal the alias requested, while `canonical_risk_decision_id` and `alias_of` must both identify the canonical row. The action and temporal envelope must remain unchanged. Escalate on key/embedded-ID, canonical provenance, symbol/timeframe/side, or temporal mismatch; missing/stale/expired record; unknown producer; canonical DENY accepted as A+; or trainer/gateway writers alternating without a reconciled authority receipt.

## 8. Admission and circuit monitoring

```bash
redis-cli --raw GET v2:paper:performance_circuit_breaker_status | jq '{
  generated_utc,state,new_entries_allowed,aggregate,rolling_25,rolling_50,
  blocked_bucket_keys,block_reasons,allow_close,allow_reduce,
  allow_mark_to_market,allow_feedback_recording
}'

redis-cli --raw GET v2:paper:ledger | jq '{
  generated_utc,current_cycle_accepted_count,held_by_paper_fill_gate_count,
  open_position_count,closed_trade_count,paper_new_entries_halted,
  paper_entry_freeze,paper_preemptive_admission_status,
  paper_performance_circuit_breaker_status
}'
```

With negative evidence, expected state is `HALTED_PERFORMANCE` and `new_entries_allowed=false` for broad strict entry. Close, reduce, mark-to-market, and feedback should remain allowed. Explicit probes/exploration must be bounded, attributed, and excluded from strict A+ until qualified.

Inspect halted probes as a separate evidence class:

```bash
redis-cli --raw GET v2:paper:intents | jq '[.[]? | select(.paper_halted_empty_book_probe==true) | {
  symbol,timeframe,prediction_id,position_generation_id,
  confidence_calibrated,paper_halted_book_probe_slots,
  paper_halted_book_probe_open_positions,paper_halted_probe_size_fraction,
  paper_probe_preserves_all_non_performance_gates,
  paper_halted_probe_allocator_recomputed,
  paper_halted_probe_pre_fraction_allocation_id,
  paper_halted_probe_pre_fraction_target_notional_usdt,
  paper_halted_probe_reallocation_sizable,paper_fill_allowed,
  gross_notional_usd,allocated_margin_usd,effective_leverage,
  allocator:{
    decision:.adaptive_allocation.allocator_decision,
    reason:.adaptive_allocation.allocator_reason,
    target_notional:.adaptive_allocation.target_notional_usdt,
    target_quantity:.adaptive_allocation.target_quantity,
    risk_fraction:.adaptive_allocation.model_inputs.paper_risk_budget_fraction,
    risk_before:.adaptive_allocation.model_inputs.risk_budget_before_paper_fraction_usd,
    risk_after:.adaptive_allocation.model_inputs.risk_budget_after_paper_fraction_usd,
    ceiling_before:.adaptive_allocation.model_inputs.gross_notional_ceiling_before_paper_fraction_usd,
    ceiling_after:.adaptive_allocation.model_inputs.gross_notional_ceiling_after_paper_fraction_usd
  },
  paper_only,routes_to_live,places_real_order
}]'
```

Current source fixes the undefined-confidence crash, rejects missing/raw-only confidence, and preserves every pre-existing non-performance blocker. A probe is not scaled by mutating a completed allocation: `run_once` requests a second allocator pass after multiplying the existing `paper_risk_budget_fraction` by 0.25; the allocator reduces risk budget and gross-notional ceiling before quantization, then re-derives leverage, margin, maintenance, liquidation, and exposure. A reduced target below venue minimum must block rather than round up.

Cycle capacity now has two phases: an attempt creates one token and consumes attempt budget; only a successful common accepted append finalizes slot/symbol capacity. A downstream rejection releases the pending token at the next signal boundary or loop end. Require `paper_halted_probe_reservation_state=FINALIZED_ACCEPTED` only on an accepted probe; `FINALIZATION_FAILED` must be blocked, and duplicate symbol/token/capacity mismatch must never append. The lane is still not safe as ordinary admission authority because open-slot accounting is not keyed to exact probe generation/bucket, timestamp parsing/comparison is not strict, and outcomes are not probe/behavior-policy stratified. Stop if a probe erases a temporal, churn, canonical-risk, maintenance, position-transition, or other immutable block; lacks a fresh reduced allocation receipt; or shows max loss/notional/margin inconsistent with the 0.25 allocator fraction.

Outcome-memory processing time is not outcome freshness. For each relevant timeframe inspect both values:

```bash
for tf in 1m 5m 15m 1h 4h; do
  redis-cli --raw GET "v2:paper:outcome_memory:__ALL__:${tf}" | jq '{
    symbol,timeframe,trade_count,
    last_outcome_event_time,last_outcome_event_time_source,
    last_outcome_available_at,last_outcome_available_at_source,
    last_updated,last_updated_source,trust_validation_version,
    degraded,block_reason,stale_evidence_advisory,
    rolling_win_rate,rolling_ev_bps,max_drawdown_bps,
    drawdown_contribution_usd,rolling_max_drawdown_usd,
    drawdown_evidence_policy,
    trust_evidence_status,trusted_trade_count,untrusted_trade_count,
    outcome_memory_can_block_entries
  }'
done
```

`last_updated` remains rebuild/processing time by design and must have source `OUTCOME_MEMORY_PROCESSING_TIME_NOT_EVIDENCE_FRESHNESS`; only `last_outcome_available_at` can age the aggregate. A v2 bucket must show `OUTCOME_MEMORY_TRUST_PIT_V2`, parsed close/availability sources, rolling—not lifetime—drawdown policy, and trusted counts derived only from complete finite PIT-valid rows. Rebuild/update status must also report quarantined-row counts and exact rejection reasons; “quarantined” currently means excluded/count-reported, not necessarily durably persisted.

The stale valve's fixed 5,400-second decay remains unsafe for ordinary authority: it still turns a degraded aggregate into `allowed=true` generic advisory rather than a typed probe-only request. Source hashes are structurally checked for `feature_vector_hash`, but no cryptographic producer/content verification is proven. Treat stale, mixed/unverified, or policy-unstratified outcome memory as shadow/probe telemetry only and stop if ordinary A+ uses it as recovered-edge proof.

Never clear temporal, missing-economic, canonical-risk, invalid-transition, fee, or accounting invariants because confidence is high.

## 9. Margin, leverage, identity, and liquidation

The hardened paper envelope has two distinct behaviors:

```text
risk maxima: may remain at or shrink below base; never grow above base
paper leverage: [1x,10x], but may exceed base only with complete positive PIT evidence
live envelope: exact operator-supplied base, unchanged by paper evidence
```

The paper-loop source now supplies all growth inputs. The edge LCB comes only from finite realized after-cost bps on strict-governed closed outcomes. Current signal rows supply liquidity/regime context only when values are finite/in range and their availability timestamp is timezone-aware and no later than the cycle decision. A value at or below the default 3x base is not evidence that the allocator is “stuck at 1x”; losing, missing or low-quality evidence is expected to hold or shrink it. A value above 3x must be treated as unexplained until an immutable input receipt proves all of:

```text
after_cost_edge_lower_bound_bps > 0
closed_trade_count and after_cost_edge_evidence_count are positive integers
after_cost_edge_evidence_source and market_context_source are nonblank
liquidity_score and regime_quality_score are finite in [0,1]
edge_available_at <= decision_time
market_context_available_at <= decision_time
all three timestamps are timezone-aware
```

`RiskEnvelope` contains no `growth_evidence_valid` or rejection reasons. The source builds `portfolio_context.dynamic_envelope_evidence`, but that partial cycle-local object is not yet copied into the emitted envelope-status or allocator-model-input record. It now carries actionable/valid context counts, coverage, component sources and rejection reason, but still lacks contributor IDs, base/output envelope and selected-leverage explanation. Preserve upstream evidence separately; do not infer validity from a leverage number. The LCB uses a 1.96 normal approximation with population variance (one row returns its own result), and its positive magnitude is currently only an admission gate, not a growth multiplier.

For certification, require component-specific liquidity/regime source and availability, or one explicit market-context bundle source/time, on every actionable LONG/SHORT signal. Generic signal timestamps cannot authorize >base leverage. Expected incomplete shape is `market_context_coverage_complete=false`, null context scores/time, and `market_context_rejection_reason=INCOMPLETE_ACTIONABLE_SIGNAL_CONTEXT_COVERAGE`.

Inspect the per-candidate allocation PIT receipt before interpreting any leverage or size:

```bash
redis-cli --raw GET v2:paper:intents | jq '[.[]? |
  select(.paper_allocation_decision_time != null) |
  (.paper_allocation_point_in_time_evidence // {}) as $pit |
  {
    symbol,timeframe,prediction_id,
    allocation_decision_time:.paper_allocation_decision_time,
    allocation_pit_status:.paper_allocation_point_in_time_status,
    decision_time_semantics:.paper_allocation_decision_time_semantics,
    required_fields:($pit.required_component_time_fields // []),
    checked_field_count:(($pit.component_time_fields_checked // [])|length),
    observed_times:($pit.observed_component_times // {}),
    required_but_unobserved:[
      ($pit.required_component_time_fields // [])[] |
      select(($pit.observed_component_times[.] // null) == null)
    ],
    future_input_count:($pit.future_input_count // null),
    rejection_reasons:($pit.rejection_reasons // []),
    strategy_temporal_contract_status,
    strategy_cascade_context_status,
    entry_atr_bps_source,ta_flat_atr_candle_closed_confirmed,
    correlation_input_status,correlation_input_source,
    fee_bps_readonly_schedule,
    dynamic_envelope_max_effective_leverage,
    portfolio_state_present,paper_ledger_open_position_count
  }
]'
```

The current registry contains 47 component-owned clocks. A usable row requires `allocation_pit_status=PASS`, `future_input_count=0`, empty rejection/missing arrays, the immutable per-candidate semantics string, and every conditionally required field represented in `observed_times`. Source-specific checks also require strategy temporal PASS; complete cascade clocks when attached; microstructure available/generated/decision when any action/source/score is used; read-only fee availability; closed/hash-authenticated TA-flat ATR; cutoff/availability/decision/computation plus hash for READY derived correlation; edge/context clocks for an envelope above 1x; and portfolio/ledger/exposure observations when those states participate. Stop if a candidate with PIT BLOCKED reaches accepted fill, or if an adapter-generated aggregate timestamp is being used as a substitute for upstream availability.

The allocator then computes a candidate target continuously inside that envelope:

```text
cost_drag = spread + slippage + fee + abs(funding)
edge_quality = max(0, after_cost_edge)
               / (max(0, after_cost_edge) + cost_drag + max(0, volatility))
adaptive_quality = clamp(
  confidence * edge_quality * liquidity * regime
  * (1 - drawdown_pressure) * (1 - correlation_pressure),
  0, 1
)
target = 1 + (dynamic_envelope_cap - 1) * adaptive_quality
```

Inspect `leverage_dynamic_envelope_cap`, all six quality/resilience fields, `leverage_adaptive_quality`, `leverage_target`, `leverage_selection_reason`, the selected rung, and maintenance evidence in the same immutable allocation. A recommendation-contract violation must set the target to 1x. The selected paper leverage is the highest supplied rung no greater than both target and envelope cap; scarce margin must block, not force a higher rung. The runtime ladder is 1x/2x/3x/5x/10x/20x, but the envelope's 10x hard cap makes 20x ineligible. A discrete jump is therefore expected; it is not proof that the selector itself uses static confidence tiers.

Paper maintenance is mandatory execution evidence. Allocator admission requires finite `0 < maintenance_margin_rate < 1`; lifecycle additionally requires finite `maintenance_margin_cum >= 0` plus complete current whole-position bracket lineage. Missing, NaN, zero, negative, or `rate >= 1` must produce zero size, `BLOCK_LIQUIDATION_RISK`, null maintenance/liquidation/buffer, `MISSING_OR_INVALID_FAIL_CLOSED`, and `NOT_RUN_MAINTENANCE_MARGIN_MISSING`; the counterfactual grid must prune the same input. Live still has an explicitly stamped 0.005 legacy compatibility fallback because changing an exchange-touching path requires separate operator approval. That fallback is migration debt and is never paper/exchange evidence.

An isolated signed-read Binance USD-M bracket connector and paper consumer passed their suites at earlier/intermediate source cuts, but later materialization edits require a final regression and no evidence poller or runtime data path is deployed. Do not treat source presence or an old green count as deployment. If an approved paper-only deployment is later made, set the three **non-secret binding identifiers** to the exact configured context and inspect only the paper context status, that connector status, and one intended symbol. Never print the exchange secret or `BINANCE_BRACKET_EVIDENCE_HMAC_KEY`:

```bash
BRACKET_ENV=mainnet
BRACKET_TRADER_ID='<safe trader_id>'
BRACKET_CREDENTIAL_REF='<safe credential_ref>'
BRACKET_SYMBOL=BTCUSDT

redis-cli --raw GET v2:paper:maintenance_bracket_security_status | jq '{
  schema_version,status,reason,generated_utc,paper_only,read_only,
  exchange_environment,credential_binding_id,trader_id,credential_ref,
  evidence_auth_algorithm,evidence_auth_key_id,
  lifecycle_exact_net_preflight_used,lifecycle_reselection_count,
  lifecycle_reselection_status_counts,
  credential_fields_exposed,evidence_auth_key_exposed,
  places_real_order,order_submitted,leverage_mutated,margin_mutated
}'

redis-cli --raw GET "v2:binance_usdm:leverage_bracket_status:${BRACKET_ENV}:${BRACKET_TRADER_ID}:${BRACKET_CREDENTIAL_REF}" | jq '{
  schema_version,status,reason,source_endpoint,security_type,
  exchange_environment,credential_binding_id,trader_id,credential_ref,
  evidence_auth_algorithm,evidence_auth_key_id,
  fetched_at,generated_at,available_at,symbols_requested,symbols_received,
  symbols_published,missing_symbols,invalid_symbols,
  redis_write_failed_symbols,read_only,places_real_order,
  order_submitted,leverage_mutated,margin_mutated
}'

redis-cli --raw GET "v2:binance_usdm:leverage_bracket:${BRACKET_ENV}:${BRACKET_TRADER_ID}:${BRACKET_CREDENTIAL_REF}:${BRACKET_SYMBOL}" | jq '{
  schema_version,producer,symbol,source,account_scope,exchange_environment,
  credential_binding_id,trader_id,credential_ref,
  evidence_auth_algorithm,evidence_auth_key_id,
  fetch_started_at,fetched_at,generated_at,ingested_at,available_at,expires_at,
  cache_expires_at,freshness_seconds,cache_ttl_seconds,notionalCoef,
  candidate_notional_contract,authorization_scope,
  initialLeverage_semantics,maintenance_margin_formula,brackets,
  content_checksum_sha256,evidence_hmac_sha256,
  read_only,raw_response_stored,credential_fields_stored,evidence_auth_key_stored,
  exchange_api_secret_used_for_evidence_auth,
  places_real_order,order_submitted,leverage_mutated,margin_mutated
}'
```

READY is only fetch/cache health. Consumer readiness additionally requires the exact same `EvidenceSecurityContext`, aware clocks, `available_at <= decision_time <= consumer_observed_at <= current_checked_at`, evidence unexpired at all three later times, a valid content checksum plus HMAC, exact binding/canonical row set, and `candidate_notional=TOTAL_ABSOLUTE_SYMBOL_POSITION_NOTIONAL_AFTER_CANDIDATE_FILL` within a floor-inclusive/cap-exclusive bracket. The selected tier supplies `maintMarginRatio`, `cum`, and `max(0, N*maintMarginRatio-cum)`; `initialLeverage` is an exchange ceiling that must be intersected with every dynamic/local safety cap. Consumer `allowed=true` means evidence usable only—not admission. A current Redis row is not historical replay evidence.

Paper allocation uses the tier at `current gross symbol exposure + fraction-adjusted envelope incremental ceiling`, then confirms the same evidence generation after quantized sizing; it never downgrades risk inputs to a less conservative tier. Lifecycle performs a discarded net-position preflight and reselects at `abs(net_quantity) * current_mark_price` before one final reconciliation. Expect the allocator's formula mode `CONSERVATIVE_RAW_BRACKET_RATIO;CUM_RETAINED_AS_LINEAGE_NOT_SUBTRACTED`, followed by lifecycle's exact `max(0,N*r-cum)`. Any context/evidence failure must block or leave maintenance unknown—never substitute 0.005 in paper.

Current glue is not ready for deployment despite green pre-audit broad suites. Source now implements four required fail-closed invariants:

- observed post-allocation total notional above the conservative high-water plus tolerance blocks, as does a higher observed maintenance rate or lower observed leverage ceiling;
- lifecycle requires checksum, HMAC, binding, environment, key, source, consumer time, valid economics, and strict time ordering before READY;
- Tier-0 exit derives current side-aware distance from mark and the canonical liquidation-price estimate;
- every non-isolated upstream paper recommendation is preserved only as counterfactual telemetry and execution is forced to `isolated_paper_simulated` until an account-wide cross model exists.
- nested normalized, selector-shaped raw, and flat bracket persistence records now normalize to one lifecycle field schema; selector-shaped evidence without explicit `prevalidated=true` remains untrusted.

Stop and escalate until all remaining invariants are implemented and tested:

- lifecycle cryptographically reauthenticates a sealed receipt with the exact security context, or consumes an unforgeable typed verified-selection token; SHA/HMAC shape and field-equality checks alone are insufficient;
- every economically active input is present in the per-candidate PIT checked/required inventory and its applicable cutoff/finality/availability/capture clocks are no later than the captured decision; current source fixed the cycle-start label but RE-050 records missing component coverage;
- one full `run_once` test proves context → conservative selection → post-size selection → persisted nested/flat lifecycle fields → close/outcome, including all negative cases;
- the final post-audit regression and a fresh attributable paper-only runtime chain pass without any exchange-setting mutation.

Until those are closed, a bracket READY row is connector evidence only—not proof of safe paper sizing or exit protection.

The connector uses the account-specific binding already resolved for `BinanceUSDMAdapter.from_env`; never display credential values. It accepts only the known Binance USD-M mainnet/testnet HTTPS origins. Evidence authentication additionally requires `BINANCE_BRACKET_EVIDENCE_HMAC_KEY` (at least 32 bytes and different from the exchange secret) plus safe `BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID`. Its read-only REST call is blocked unless the existing `BINANCE_REST_FALLBACK_ALLOWED` policy explicitly permits the endpoint reason. Redis uses `V2_REDIS_URL` then `REDIS_URL`. Failed refresh does not overwrite prior good data, so exact context and embedded expiry—not key existence—govern. Refresh after any binding/environment/HMAC rotation; scoped namespaces prevent a different context from authorizing an old row.

The allocator may request `cross_paper_simulated` only for leverage above 1x when modeled candidate benefit exceeds the maximum observed contagion pressure, and `simulate_cross_margin_stress` may downgrade it. Paper execution attachment now preserves any non-isolated recommendation only as counterfactual telemetry and forces `isolated_paper_simulated` with `CROSS_MARGIN_DISABLED_NO_ACCOUNT_WIDE_LIQUIDATION_MODEL`. The upstream score remains candidate-only research telemetry—not a full open-book stress test, account-wide maintenance call, exchange margin-mode mutation, or proof of cascade safety. Its helper still contains legacy fixed cutoffs/defaults for other callers.

Hedge intent cannot increase entry size. When hedge-aware sizing is requested, require `enabled=false`, `size_amplification=1.0`, full-stop sizing, and `DISABLED_NO_ATOMIC_FUNDED_HEDGE_PROOF`. Any larger size without an atomic filled/funded/cap-safe two-leg receipt is a stop-the-line event.

The deferred paper hedge runtime must also remain interlocked:

```bash
redis-cli --raw GET v2:paper:adaptive_hedge_status | jq '{
  generated_utc,writer_pid,env_flag_at_import,resolved_enabled,
  runtime_safety_interlock,runtime_safety_block_reason,enable_source,
  fill_synthesis
}'
```

Required deployed shape is `resolved_enabled=false`, `runtime_safety_interlock=true`, reason `HEDGE_DISABLED_NO_ATOMIC_FUNDED_EXACT_LINEAGE_EXECUTION_PROOF`, `enable_source=runtime_safety_interlock`, and zero synthesized fills. The 20:00:29.746 UTC post-restart row satisfied this shape even though `env_flag_at_import=true`. Stop if the key is absent/stale after restart, resolved enablement is true, a directive synthesizes a fill, or the environment/Redis request overrides the interlock. The dormant path uses unsafe directive-time pricing/parent IDs/non-atomic state and can delay an already-hit ATR stop; it is not authorized for re-enable.

Do not report “no static thresholds anywhere.” Current allocator source still contains fixed market-state 30/70, confidence 0.30/0.50, liquidity 0.01/0.05, spread/slippage 2/1, positive-edge, hedge breakpoint/cap and discrete-rung gates. Classify each as protocol/exchange, immutable safety, evidence-only certification, adaptive operating policy, or obsolete. Only the fourth category should be replaced with bounded PIT adaptation; immutable safety limits must remain fail closed.

After a controlled reload, inspect both the performance source and emitted envelope status:

```bash
redis-cli --raw GET v2:paper:performance_circuit_breaker_status | jq '{
  generated_utc,state,governed_closed_rows,
  after_cost_edge_lower_bound_bps,after_cost_edge_evidence_count,
  after_cost_edge_evidence_source,after_cost_edge_available_at,
  aggregate,block_reasons
}'

redis-cli --raw GET v2:paper:trade_management:status | jq '{
  generated_utc,
  risk_envelope_dynamic_budget_status
}'
```

At this source cut the emitted nested object does not yet carry `dynamic_envelope_evidence`; absence is an open auditability defect, not permission to infer it.

Inspect recent paper allocation rows for the post-step capital boundary:

```bash
redis-cli --raw GET v2:paper:intents | jq '[.[]? | select(.adaptive_allocation|type=="object") | {
  symbol,timeframe,
  price:(.adaptive_allocation.model_inputs.price),
  quantity:(.adaptive_allocation.target_quantity),
  notional:(.adaptive_allocation.target_notional_usdt),
  gross_notional:(.adaptive_allocation.gross_notional_usd),
  margin:(.adaptive_allocation.allocated_margin_usd),
  leverage:(.adaptive_allocation.effective_leverage),
  isolated_margin:(.adaptive_allocation.isolated_margin_required_usd),
  maintenance_estimate:(.adaptive_allocation.maintenance_margin_estimate_usd),
  liquidation_distance_usd:(.adaptive_allocation.liquidation_distance_usd),
  post_step:{
    status:.adaptive_allocation.model_inputs.paper_post_quantization_exchange_filter_status,
    before:.adaptive_allocation.model_inputs.paper_target_notional_before_step_quantization_usd,
    quantity:.adaptive_allocation.model_inputs.paper_target_quantity_after_step_quantization,
    after:.adaptive_allocation.model_inputs.paper_target_notional_after_step_quantization_usd,
    margin_basis:.adaptive_allocation.model_inputs.paper_margin_configuration_uses_post_quantization_notional
  }
}] | .[:25]'
```

For every newly allowed paper allocation require `post_step.status=PASS`, `margin_basis=true`, `notional ~= abs(quantity*price)`, `gross_notional ~= notional`, and `margin ~= notional/leverage` within the system's rounding tolerance. The allocator's candidate maintenance estimate is the conservative raw ratio `notional*rate`; only lifecycle has authenticated bracket `cum` and applies `max(0,N_mark*rate-cum)`. A zero/post-step-below-minimum row must be blocked with zero size, never rounded upward. Missing diagnostics on a post-reload row mean the new allocator boundary is not deployed.

Check closed-row leverage and capital consistency:

```bash
redis-cli --raw GET v2:paper:closed_trades | jq '{
  count:length,
  leverage_distribution:(
    group_by((.effective_leverage // "missing")|tostring)
    | map({leverage:.[0].effective_leverage,count:length})
  ),
  capital_rows_checked:(
    map(select(
      (.gross_notional_usd|type)=="number" and
      (.allocated_margin_usd|type)=="number" and
      (.effective_leverage|type)=="number"
    )) | length
  ),
  capital_invariant_violations:(
    map(
      select(
        (.gross_notional_usd|type)=="number" and
        (.allocated_margin_usd|type)=="number" and
        (.effective_leverage|type)=="number"
      )
      | . as $r
      | select(
        (($r.gross_notional_usd -
          ($r.allocated_margin_usd * $r.effective_leverage))|fabs)
        > ([0.02, ($r.gross_notional_usd|fabs)*0.000001]|max)
      )
    ) | length
  )
}'
```

At the evidence cut: 86 rows, leverage 43×1x/41×2x/2×3x, and 45 historical invariant violations. Do not rewrite those rows to make G10 green.

Inspect current positions:

```bash
redis-cli --raw GET v2:paper:ledger | jq '[.open_positions[]? | {
  symbol,position_id,legacy_position_id,position_generation_id,
  position_id_version,entry_generation_time_utc,side,net_quantity,
  avg_entry_price,gross_notional_usd,allocated_margin_usd,
  allocated_margin_usd_upstream,effective_leverage,margin_mode_simulated,
  maintenance_margin_rate,maintenance_margin_estimate,
  maintenance_margin_cum,maintenance_margin_notional_usd,
  maintenance_margin_mark_price,maintenance_margin_mark_time,
  liquidation_price_estimate,liquidation_buffer_bps,
  maintenance_bracket_id,maintenance_bracket_evidence_hmac_sha256,
  maintenance_bracket_binding,maintenance_bracket_environment_id,
  maintenance_bracket_available_at,maintenance_bracket_expires_at,
  paper_liquidation_validation_status,
  capital_accounting_reconciled,capital_accounting_reconciliation_reasons,
  current_capital_accounting,
  entry_allocation:{
    effective_leverage:.adaptive_allocation.effective_leverage,
    maintenance_margin_rate:.adaptive_allocation.model_inputs.maintenance_margin_rate,
    risk_envelope:.adaptive_allocation.model_inputs.risk_envelope
  }
}]'
```

Required for a new post-repair generation:

```text
position_generation_id present
position_id_version=PAPER_POSITION_GENERATION_V1
gross_notional_usd ~= abs(net_quantity * avg_entry_price)
allocated_margin_usd ~= gross_notional_usd / effective_leverage
maintenance_margin_estimate ~= max(
  0,
  maintenance_margin_notional_usd * maintenance_margin_rate
     - maintenance_margin_cum
)
maintenance_margin_notional_usd ~= abs(net_quantity * maintenance_margin_mark_price)
one whole-position bracket governs; do not weight per-fill rates
side-correct liquidation price and positive buffer
margin_mode_simulated=isolated_paper_simulated
current_capital_accounting.accounting_scope=CURRENT_EXECUTED_PAPER_POSITION
current_capital_accounting.execution_notional_validated=true, or actual net_quantity × avg_entry_price is independently reconstructable
effective leverage <= entry allocation model_inputs.risk_envelope.max_effective_leverage
maintenance rate has an explicit current-position/row/allocation evidence source
```

Accounting rules are deliberately asymmetric:

- an existing open position's used notional can come only from actual executed quantity × actual entry/fill price or explicitly validated current executed capital;
- target, order, recommended and unscoped reported notional cannot create used-margin truth;
- `recommended_leverage` alone cannot reduce required margin; absent validated allocation/execution leverage, use the fail-safe 1x result;
- allocation-derived leverage above 1x without its decision-time envelope cap falls back to 1x; leverage above the cap or disagreeing with the allocation is invalid;
- missing/non-finite maintenance evidence, a rate outside `0 < rate < 1`, negative/missing `cum`, stale/future evidence, or an unbound bracket makes maintenance/liquidation null and reservation fail closed;
- `_ensure_margin_leverage_consistency_rows` writes the current result under `current_capital_accounting` and must not rewrite the immutable entry `adaptive_allocation`.

Expected normalized-fill missing-maintenance failure shape:

```text
maintenance_margin_rate=null
maintenance_margin_estimate=null
liquidation_price_estimate=null
liquidation_buffer_bps=null
paper_liquidation_validation_status=UNAVAILABLE_MAINTENANCE_MARGIN_EVIDENCE_MISSING
paper_margin_accounting_invalid_reason=MAINTENANCE_MARGIN_RATE_MISSING_OR_INVALID
reservation/admission blocked
```

If upstream liquidation values were present, they may remain under `liquidation_price_estimate_upstream` and `liquidation_buffer_bps_upstream`; they are provenance, not authority.

Legacy positions without generation IDs show that fresh post-deploy evidence is still needed. Never carry old trailing/hedge/capital state into a later reopen merely because the symbol matches.

## 10. Account-wide margin reservation

Inspect the cycle-local account receipt, embedded ledger receipt, and portfolio projection together:

```bash
redis-cli --raw GET v2:portfolio:state | jq '{
  generated_utc,equity,cash_balance,wallet_balance,used_margin_usd,
  available_margin,free_margin_usd,free_margin_after_buffer_usd,
  open_position_count,
  margin_status_generated_utc:.paper_account_margin_status.generated_utc,
  paper_account_margin_status
}'

redis-cli --raw GET v2:paper:ledger | jq '{
  generated_utc,total_open_notional,open_position_count,
  allocated_open_margin:([.open_positions[]?.allocated_margin_usd // 0] | add // 0),
  paper_account_margin_status,
  reservation:(.paper_margin_reservation_status | {
    generated_utc,cross_process_atomic,single_active_writer_required,
    reservation_status,reserved_candidate_count,blocked_candidate_count,
    invariant_holds
  })
}'

redis-cli --raw GET v2:paper:account_margin_status | jq '{
  schema_version,status,generated_utc,margin_base_usd,used_margin_usd,
  newly_reserved_margin_usd,free_margin_usd,margin_buffer_usd,
  free_margin_after_buffer_usd,accounting_complete,invariant_holds,
  failure_reasons,cycle_reserved_candidate_count,
  cycle_margin_blocked_candidate_count,source,paper_only,routes_to_live,
  places_real_order
}'
```

Required source equations:

```text
margin_base = conservative min(equity, wallet)
used = sum(abs(open_qty * avg_entry_price) / leverage)
buffer = max(0, margin_base - used) * dynamic buffer percent
pre-lifecycle: margin_base = used + newly_reserved + free
post-lifecycle: margin_base = used + free
```

`accounting_complete=false`, missing base, invalid open-position execution notional, invalid/uncapped leverage, missing maintenance evidence, a negative/deficit invariant, or insufficient post-buffer capacity must block new candidates. When any existing open row is incomplete, numeric free margin must be zero even if some used margin is measurable. The blocked row must include `PAPER_ACCOUNT_MARGIN_RESERVATION_BLOCKED` plus the exact reason. A close/partial close releases margin only through the canonical post-lifecycle/next-cycle recomputation.

Do not treat `status=PASS` as cross-process atomicity. A new receipt must explicitly say `cross_process_atomic=false` and `single_active_writer_required=true`. The current implementation is one in-memory reservation pass per `run_once`; it has no Redis CAS/lease or durable reservation journal. Confirm exactly one intended paper-loop owner before interpreting capacity. The standalone account-key `generated_utc` must exactly equal the embedded account receipt timestamp. At 2026-07-17 18:33–18:45 UTC the standalone key passed its arithmetic invariant but lacked `generated_utc`, the simultaneous ledger lacked the embedded receipts, and all six open positions were legacy identity rows. That mismatch is a deployment reconciliation failure, not A+.

The portfolio publisher's nested margin-status timestamp must equal the top-level portfolio `generated_utc`. It is a separately reconstructed projection and may be later than the paper-ledger receipt; compare source and open-position counts before interpreting the difference.

This module does not liquidate. Maintenance/liquidation fields are per position; no account-wide maintenance-margin-call or cascade-liquidation engine is proven.

`position_from_fill` no longer promotes a recommendation to executed leverage or invents 0.005 maintenance. Recompute accepts only finite `0 < rate < 1`, never derives a rate from an estimate, and serialization preserves missing/invalid maintenance and liquidation as null at top level and inside `current_capital_accounting`; legacy-zero reconstruction is covered by a focused regression. Static compatibility/default values in allocator/live/counterfactual paths were separately under active repair at this cut. Treat any 0.005 rate without explicit source/version as unproven rather than exchange truth.

If trainer status exposes `leverage_margin_exploration`, interpret the v2 contract exactly:

```text
study_only=true
routes_to_live=false
places_real_order=false
input_evidence_complete=true before any recommendation
point_in_time_safe=true before any recommendation
study_admission_allowed=true only with best_leverage in {1,2,3}
best_margin_mode=isolated
cross margin evaluated=false
```

The current `policy_backtest` integration is expected to show `study_admission_allowed=false`, `best_leverage=null`, and missing-evidence reasons. Do not rewrite missing inputs with constants to make it choose >1x. The study becomes actionable only after every field is derived from purged held-out after-cost evidence and a PIT account/risk snapshot; even then the paper allocator remains final sizing authority.

Inspect trainer checkpoint evidence without interpreting a self-report as profitability proof:

```bash
redis-cli --raw GET v2:trainer:hybrid_cuda:status | jq '{
  generated_utc,online_learning_status,checkpoint_id,
  feature_dim,input_dim,expected_input_dim,feature_schema_status,
  checkpoint_promotion_allowed,checkpoint_promotion_rejected,
  checkpoint_promotion_reason,validation_split_pit_safe,
  validation_split_reason,validation_policy_edge_status,
  validation_policy_edge_after_cost_bps,
  validation_policy_edge_lower_confidence_bound_bps,
  validation_policy_edge_rows_evaluated,
  checkpoint_restore_after_rejection_status,
  checkpoint_restore_after_rejection_verified,
  model_serving_allowed,model_serving_source,
  rejected_candidate_serving_suppressed,model_serving_suppression_reason,
  prediction_suppressed_count,cuda_inference_status,prediction_publication_status,
  learning_metrics:(.learning_metrics | {
    learning_update_lane,ppo_objective_used,validation_rows_evaluated,
    checkpoint_promoted_this_cycle,checkpoint_restore_after_rejection_verified
  })
}'
```

Promotion must remain false when the split is not PIT-safe, edge is unavailable/nonpositive, or its one-standard-error lower bound is nonpositive. A long rejection streak is never authority to override those results. `ppo_objective_used=false` is expected while serving remains deterministic; do not “repair” it by relabeling rows.

After rejection, serving is valid only with `checkpoint_restore_after_rejection_verified=true` and `model_serving_source=VERIFIED_PRIOR_CHECKPOINT_AFTER_REJECTION`. Otherwise backtest/inference/prediction/lineage must be suppressed with reason `REJECTED_CANDIDATE_WITHOUT_VERIFIED_PRIOR_RESTORE`. Any prediction from that rejected un-restored candidate is a stop-the-line defect.

`feature_schema_status=ALIGNED` only proves `input_dim == 4 * current FEATURE_SPEC`; it does not resolve the 477/1,908 audited-deployment versus 446/1,784 current-source drift. Record all four fields and the checkpoint hash before interpreting training or restore evidence.

## 11. Isolated source validation

Run against isolated fixtures, not production Redis/state files:

```bash
.venv/bin/python -m py_compile \
  v2/backend/app/services/market_state_integrity/replay_snapshot.py \
  v2/backend/app/services/market_state_integrity/sample_rejection.py \
  v2/backend/app/cli/v2_orchestrator_arbitration_loop.py \
  v2/backend/app/cli/v2_risk_gateway_live_loop.py \
  v2/backend/app/cli/v2_trade_management_paper_loop.py \
  v2/backend/app/cli/v2_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py \
  v2/backend/app/services/binance_usdm_leverage_bracket_evidence.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/temporal_windowing.py \
  v2/backend/app/services/native_trainer/trusted_replay/dataset.py \
  v2/backend/app/services/paper_trade_management/generation_identity.py \
  v2/backend/app/services/paper_trade_management/margin_accounting.py \
  v2/backend/app/services/paper_trade_management/position_state.py \
  v2/backend/app/services/paper_trade_management/lifecycle.py

.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/native_trainer/test_temporal_windowing.py \
  v2/backend/tests/unit/services/native_trainer/test_trusted_replay_bootstrap.py \
  v2/backend/tests/unit/services/native_trainer/test_hybrid_cuda_trainer_runtime.py \
  v2/backend/tests/unit/services/native_trainer/test_hybrid_trainer_regularization_and_validation.py \
  v2/backend/tests/unit/services/native_trainer/test_historical_missing_mask_admission.py \
  v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py

.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py

.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py

.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/adaptive_capital_allocator

.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/execution/test_stealth_and_intent.py \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/cli/test_v2_binance_usdm_leverage_bracket_evidence.py
```

Validated checkpoints are: 374 combined trainer/PIT tests (98.82 seconds); intermediate 93 lifecycle; intermediate 411 complete `services/paper_trade_management`; 49 connector service/CLI; intermediate 450 paper-loop; intermediate 499 combined connector+loop; 125 risk/orchestrator; and intermediate 142 allocator/simulation. Known later moving-cut complete gates were red: paper loop 441 passed/9 failed and allocator 126 passed/1 failed, before the subsequent fixture/materialization work. The 93/411/450/499, coordinated 929, and 142 allocator results predate later entry-snapshot/final-materialization and post-quantization margin hardening and must be superseded by literal final commands before being called current. A different count or failure requires reconciliation before runtime use. Source counts never substitute for deployed scoped evidence and a fresh attributable allocation/lifecycle/outcome receipt.

Do not run broad integration tests against authoritative paper files/Redis unless isolation is independently confirmed. A historical integration fixture has overwritten paper state before.

## 12. Certification and expected failure

These commands write goal artifacts; preserve existing evidence first:

```bash
.venv/bin/python scripts/guardian_phase10_rare_event_tests.py
.venv/bin/python scripts/verify_claude_guardian_completion.py
```

Current expected result is nonzero/FAIL:

- G10: 45 historical capital invariant violations;
- G11: negative counterfactual expectancy;
- G12: eight warnings mean fail;
- G13/G14: expectancy/profit-factor evidence fails;
- strict verifier observed 10/16 gates passed.

Treat an unexpected PASS as an incident until freshness, warning count, row population, provenance, and script version are verified. Insufficient data is not performance proof.

## 13. Restart and monitoring boundary

A restart mutates runtime state. Before an approved paper-only restart:

1. record Git HEAD/worktree and Redis timestamps;
2. confirm the unit is paper/shadow and does not route live;
3. run scoped tests;
4. preserve current ledger/artifacts under the approved evidence policy;
5. restart only the intended unit;
6. confirm `active` and a fresh heartbeat;
7. recheck §3 non-live fields;
8. inspect the first new signal/fill/generation before trusting aggregates.

Do not restart/enable live submitters, mutate the live gate, or call an exchange endpoint. Do not use destructive Git reset/checkout as rollback in a dirty shared worktree.

At 30–60 second intervals record:

- heartbeat/TTL freshness;
- HOLD held and routeable counts;
- risk ID equality, producer, action, and expiry;
- canonical deny/missing/stale accepted count, which must be zero for ordinary A+;
- accepted fills by explicit tier/path;
- halted probes by exact generation/bucket, provisional/final slot and downstream release result;
- outcome latest valid availability versus processing `last_updated`;
- hedge interlock status and synthesized-fill count;
- position generation IDs and accounting equations;
- available-versus-allocated margin discrepancy;
- clean/quarantined feedback;
- rolling after-cost PF/expectancy/drawdown;
- guardian/verifier generation time and results.

Safe display loop:

```bash
watch -n 30 'redis-cli --raw GET v2:paper:performance_circuit_breaker_status | jq -c "{generated_utc,state,new_entries_allowed,rolling_25,block_reasons}"'
```

Stop and escalate on any live flag, HOLD-derived entry, risk-deny A+ acceptance, future timestamp, missing economic/generation field, new capital invariant failure, cross-generation state carry, unexplained state shrink, Redis partial write/eviction, or false green grade.

## 14. Exit criteria

Runtime verification requires fresh post-deploy evidence that:

- non-live flags remain blocked;
- temporal/dirty-sample negative tests and runtime rejects work;
- HOLD never routes or fills;
- every signal/risk ID correlates and ordinary A+ requires resolved allow;
- every new position has generation identity and consistent capital;
- any exchange-bracket-derived paper maintenance/leverage ceiling has a current hash-valid account-bound receipt selected for total post-fill symbol notional at decision time;
- same-side add, partial close, reversal, and reopen preserve equations/state;
- no path bypasses the common invariant reducer;
- feedback clean/quarantine classification is stable;
- G10/G11/G12/G13/G14 pass honestly on sufficient data;
- outcome memory uses validated outcome availability/lineage and cannot turn stale degradation into generic A+ allow;
- halted probes preserve owning-gate blocks, release rejected reservations and retain probe-policy outcome identity;
- hedge runtime remains interlocked until independent decision, executable-price, exact-generation, atomic funding and stop-preservation proofs pass;
- all 16 verifier gates pass with provenance.

Even then, A+ is evidence for the tested paper system—not a guarantee of 1000x and not automatic authority to enable live trading.
