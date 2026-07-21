# Adaptive end-to-end control, accounting, and change-impact map

**Evidence cut:** moving source/worktree based on `6997e4d99e`, reconciled through the coordinated 2026-07-17 source changes, plus read-only Redis observations through 19:17 UTC. The paper service was restarted at 2026-07-17 16:00:27 America/New_York for immediate hedge containment and emitted the expected disabled status two seconds later; that scoped reload does not prove deployment or behavior of every other moving trainer/allocator/paper change.

**Operating mode:** paper/shadow only; `places_real_order=false`, `routes_to_live=false`, and `live_gate=blocked_human_only`

**Certification:** **FAIL / NO-GO.** A+ has not been achieved. The measured paper state remains `HALTED_PERFORMANCE` with 23 governed post-repair closes, PF about 0.704, weighted expectancy about −7.701 bps, and trajectory constraint `NO_A_PLUS_SUPPLY`. The 1000x-in-90-days target is a research objective, not a promise or guarantee; current after-cost evidence does not support scaling toward it.

This is the dated low-level addendum to the 2026-07-16 reconstruction. It explains the adaptive-control repair in the current worktree, the data and key contracts it touches, and what remains unproved. Source-level mitigation, test success, deployed behavior, clean new outcomes, and A+ certification are five different states; this document never substitutes one for another.

## 1. End-to-end control and learning loop

```text
finalized provider observations
  -> point-in-time feature envelope / snapshot
  -> TrainingExample + model tensor
  -> native PPO-shaped/MASA-auxiliary policy
  -> prediction + replay snapshot
  -> orchestrator proposal/arbitration
       HOLD/flat/close/hedge -> held, never synthesized into an entry
       LONG/SHORT -> proposal with signed and side-directional edge
  -> canonical risk correlation ID -> risk decision record
  -> adaptive allocator -> notional/leverage/margin recommendation
  -> paper admission reducer
       ordinary A+ requires resolved canonical ALLOW
       bounded paper exploration remains a separate paper-only policy lane
  -> economic fill classifier -> generation-aware position lifecycle
  -> mark-to-market / close / net PnL / outcome label
  -> clean feedback or quarantine
  -> trainer/replay on a later cycle
```

No stage may manufacture evidence belonging to the next stage. In particular:

- an orchestrator selection is not risk approval;
- a risk-decision ID is not a risk `ALLOW`;
- an allocator recommendation is not reserved capital;
- a paper intent is not a fill;
- a fill is not automatically a clean training sample;
- a passing unit test is not deployed-runtime or profitability evidence.

## 2. Component-by-component low-level map

### 2.1 Feature and trainer input plane

Primary source surfaces include `v2:features:latest:{symbol}:{timeframe}`, `v2:features:snapshot:{feature_snapshot_id}`, finalized OHLCV families, market microstructure, funding/open-interest, liquidation, alternative-data, and paper-feedback keys. The exhaustive family list remains in `atlas/REDIS_KEY_USAGE_REGISTRY.json`; the table in §3 lists only the families directly traced in this repair.

The current trainer builds a `TrainingExample` containing a `FeatureTensorRecord`, action/return labels, row classification, and trust row. The repair adds an immutable top-level `decision_time` resolved in `TrainingExample.__post_init__` from the explicit field or the trust-row decision contract. It is canonicalized to UTC with microseconds. An invalid or absent value remains `None`; list order is never accepted as temporal evidence.

The same constructor resolves `label_available_at`, the instant at which the outcome label was fully knowable. It considers explicit example/trust/outcome timestamps (`label_available_at`, `outcome_available_at`, exit/close time) and `decision_time + positive label_horizon`; the latest valid candidate wins. Invalid timestamp/duration evidence makes `label_timing_valid=false` with an exact error instead of guessing. A label time must be strictly later than its decision time.

`_chronological_purged_split` then sorts the selected batch by immutable decision time, keeps equal decision timestamps on the same validation side, and purges candidate training rows whose `label_available_at >= validation_start_decision_time`. It emits validation rows only when both decision-time and label-horizon separation are proven. Missing/invalid timing, no distinct boundary, or a purge that removes all training rows returns no represented held-out rows and `validation_split_pit_safe=false`; candidate learning may continue, but checkpoint promotion cannot cite that batch as PIT-safe validation.

`build_example_windows` groups rows by `(symbol, timeframe)`, requires a finite positive decision time, sorts by `(decision_time, original_index)`, constructs the causal prefix ending at the target, and asserts that no frame is newer than the target. Rows without a vector or parseable time are omitted. `model_batch_tensor` now raises when temporal mode has no lookup or a row has no causal window. It no longer repeats the current frame to hide missing chronology.

Effect of a change:

- changing `TrainingExample.__post_init__` changes every temporal trainer/evaluator window that consumes `decision_time`;
- changing `_parse_decision_ms` changes inclusion and order of temporal samples;
- changing `build_example_windows` affects GRU inputs, validation, prediction parity, and any metric derived from temporal mode;
- changing `model_batch_tensor` changes the fail-open/fail-closed boundary for all temporal batches;
- none of these repairs proves that every contributing feature source preserved a truthful `available_at`; RE-003 remains open.

### 2.2 Trusted replay and labels

`build_trusted_replay_row` resolves finalized future candles and computes the raw 15-minute market return:

```text
raw_return_bps = (future_close - entry_price) / entry_price * 10,000
long_net_bps   =  raw_return_bps - abs(round_trip_cost_bps)
short_net_bps  = -raw_return_bps - abs(round_trip_cost_bps)
```

`_target_action_from_net_edges` chooses only a side whose own after-cost result is positive and clears the label threshold; otherwise it returns `hold`. Costs are subtracted from both sides and can no longer flip a losing market direction into a fabricated win. The row separately records:

- `counterfactual_long_net_pnl_bps`;
- `counterfactual_short_net_pnl_bps`;
- `counterfactual_target_net_pnl_bps` and best-action target;
- `actual_behavior_net_pnl_bps` for the normalized action actually selected;
- independent counterfactual and behavior outcomes/availability flags.

This repairs directional sign and separates two meanings that were previously collapsed. The follow-on trainer repair freezes `behavior_action_index` plus its matching action name on `TrainingExample`; it never falls back to hindsight `label_action_index`. PPO eligibility rejects a missing, non-finite, out-of-range, or conflicting index/name/alias pair. Torch gathers both current and optimizer-step log probabilities at this immutable behavior action, while supervised cross entropy continues to use a separate hindsight target tensor. Thus supervised LONG/SHORT-to-HOLD neutralization cannot redirect PPO to HOLD.

PPO eligibility also requires `behavior_policy_sampling_mode=CATEGORICAL_SAMPLE` and `behavior_policy_distribution_contract=RAW_LOGITS_SOFTMAX_V1`. The native publisher truthfully stamps the current selector as `DETERMINISTIC_ARGMAX_ALIGNMENT` over `EXPECTED_MOVE_ALIGNED_POLICY_V1`, sets `ppo_on_policy_entry_fields_present=false`, and records `DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED`. Paper signal enrichment, bounded entry snapshots, accepted-fill persistence, lifecycle, outcomes, and closed feedback preserve those fields. Therefore current deterministic rows cannot enter the clipped PPO lane even when log probability/value fields exist; valid realized rows remain `OUTCOME_SUPERVISED_PAPER`. Genuine PPO requires the action generator itself to draw a categorical action from the exact raw-softmax distribution and to persist that immutable proof. No source repair here changes action generation to sampling.

RE-014 remains open for trajectory/critic semantics rather than an active mixed-transform ratio: `done`, rollout ID and step remain presence gates rather than coherent ordered-trajectory proof; advantage remains one-step `reward - old_value`; AdamW state is not persisted; and old log probability is not numerically reconciled to the stored selected-action probability. If sampled action generation is introduced, the raw distribution, sampled action, log probability, checkpoint, and selector version must be bound as one immutable entry contract.

For checkpoint evidence, `_validation_policy_edge` executes the same expected-move-aligned serving selector on every held-out row and scores LONG as `label_after_cost`, SHORT as its negation, and HOLD as zero. HOLD remains in the denominator. It emits mean after-cost bps, sample standard error, and `lower_bound = mean - standard_error`. `_checkpoint_promotion_decision` hard-requires a PIT-safe purged split, complete one-for-one edge evaluation, positive mean, and positive lower bound before any ordinary validation-loss/overfit rule or first-checkpoint bootstrap can allow promotion. Missing, nonpositive, or uncertainty-nonpositive evidence fails closed. The rejection-streak path is telemetry only and cannot force promotion through these gates.

Runtime at 19:16:17 UTC had not loaded that source: it reported promotion allowed for `VALIDATION_GUARD_DISABLED`, 403 validation rows and a promoted outcome-supervised candidate while all PIT-split/edge fields were absent. PPO was false. That checkpoint is pre-repair evidence and cannot be certified retroactively. A post-reload cycle must show the mandatory gate fields and either a legitimate uncertainty-adjusted pass or fail-closed rejection/restore.

After a source-level promotion rejection, serving is allowed only if restoration of the prior checkpoint is independently verified. Without that proof, `model_serving_source=NONE_REJECTED_CANDIDATE_SUPPRESSED`, reason `REJECTED_CANDIDATE_WITHOUT_VERIFIED_PRIOR_RESTORE`, and `model_serving_allowed=false`. Policy backtest, forward inference, prediction construction/publication and downstream lineage are all suppressed; status exposes `SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE` and an explicit prediction-suppressed count. A rejected in-memory candidate is never rebranded as the current policy.

### 2.3 Prediction publication

The native publisher writes `v2:prediction:{symbol}:{timeframe}`. When replay is required it first writes `v2:replay:snapshots:{prediction_id}` with a 24-hour TTL, stamps the successful key/ID, revalidates the prediction trust contract, and then publishes the prediction. `publish_prediction` works on a private copy, but after the replay and prediction writes succeed it now commits the exact persisted metadata—including `replay_snapshot_write_success`, key, ID, and fail-closed mutations—back to the caller-owned payload. `run_hybrid_trainer_cycle` publishes orchestrator/risk lineage only when `publish_prediction` returns true. Replay/archive/prediction failure therefore suppresses the following lineage stage instead of letting stale pre-write state escape.

The dated publisher repair also lifts decision-temporal evidence from the immutable trust row into the prediction, orchestrator-decision record, risk record, and paper-signal payload. `DECISION_TEMPORAL_LINEAGE_FIELDS` carries `candle_closed_confirmed`, candle open/close times, source event/receipt/availability times, `masa_feature_cutoff`, `ppo_feature_cutoff`, and `ppo_decision_time`. In this publisher path MASA and PPO consume the same immutable tensor, so an explicitly recorded per-model cutoff wins; only when that value is absent does each internal cutoff inherit the tensor's canonical `feature_cutoff`. Candle finality is never inferred. `ppo_decision_time` is the generated decision time for this payload.

A routeable prediction contract includes at least:

- `prediction_id`, `decision_id`, `symbol`, `timeframe`, `selected_action`;
- raw/calibrated confidence and action probabilities;
- signed expected move after cost;
- `feature_snapshot_id`, feature/tensor hashes, model/checkpoint identity;
- `event_time`/source times, `available_at`, `feature_cutoff`, `decision_time`;
- exact `candle_closed_confirmed`, candle close time, MASA cutoff, PPO cutoff, and PPO decision time;
- replay/archive success and trust result;
- `paper_fill_allowed` only as upstream eligibility, never final fill authority.

Read-only runtime evidence at 2026-07-17 18:16:27 UTC still showed the pre-reload BTCUSDT 1m shape: the newly propagated finality/cutoff fields were absent and the row was safely unroutable. By 18:44:20 UTC a new attributable prediction carried `candle_closed_confirmed=true`, exact open/close times, identical 18:41:59.999 UTC tensor/MASA/PPO cutoffs, PPO/decision time 18:44:20.238 UTC, and `replay_snapshot_write_success=true`. Ordering held (`cutoff < available_at < decision_time`). It remained `routes_to_orchestrator=false` and `paper_fill_allowed=false` for explicit non-directional/confidence/after-cost-edge gate reasons. This proves the repaired prediction success shape is deployed; it does not yet prove cross-surface equality on a routeable prediction or failure-injection suppression.

This is a source-level mitigation for RE-007, not runtime closure. It still requires deployed failure injection and a new attributable row proving that durable replay metadata and downstream lineage are identical. A successful-looking lineage ID alone remains insufficient proof.

### 2.4 Orchestrator

`_prediction_to_proposal_and_signal` now recognizes only `long` and `short` as new-entry actions. `hold`, `flat`, `close`, `hedge`, and unknown actions return no routeable proposal. `run_once` emits those rows in `held_by_paper_fill_gate` with `side=flat`, `paper_fill_allowed=false`, `risk_decision_id=null`, and `routes_to_risk_gateway=false`.

The upstream expected move is in market-return sign space. The orchestrator preserves that as `expected_move_after_cost_bps_signed` and computes side-directional edge for ranking:

```text
directional_edge = signed_edge       for LONG
directional_edge = -signed_edge      for SHORT
```

Thus a −20 bps short opportunity and +20 bps long opportunity enter arbitration with equal favorable magnitude while retaining their original sign for audit and downstream allocation.

For a routeable winner:

```text
orchestrator_decision_id = "dec_" + prediction_id
risk_decision_id         = "rd_"  + orchestrator_decision_id
paper_fill_allowed       = false
paper_fill_gate_status   = "RISK_PENDING"
```

Read-only runtime evidence at 2026-07-17 17:50 UTC showed this repaired shape in `v2:signals:paper`: the signal carried `rd_dec_<prediction>`, retained signed/directional edge fields, and remained risk-pending rather than pre-approved.

### 2.5 Canonical risk records

`v2_risk_gateway_live_loop.run_once` reads `v2:orchestrator:decisions`. In the current disarmed deployment it deliberately evaluates with a rejected live trust envelope including `live_trading_disabled` and `market_state_envelope_missing`, so `risk_action=deny` is the expected fail-closed live state.

The gateway writes:

- a preview list at `v2:risk:gateway:decisions`;
- the last preview at `v2:risk:gateway:latest`;
- heartbeat at `v2:risk:gateway:heartbeat`;
- immutable-looking per-ID rows at `v2:decision:risk:{risk_decision_id}`;
- candidate/signal indexes at `v2:decision:index:by_candidate:{id}` and `...:by_signal:{id}`.

Per-ID rows and indexes have a two-hour TTL. The paper loop's `_paper_policy_intent_decision_dereference` requires exact ID, symbol, timeframe, freshness, and record presence. Missing, mismatched, or stale risk records now remain `PENDING:RISK_DECISION_RECORD_REQUIRED`; local pre-trade/fee observations cannot manufacture `PASS`. `_paper_decision_action` defaults to `deny`.

Legacy alias keys use a strict dereference-safe schema. A record stored at `v2:decision:risk:{alias_id}` carries `risk_decision_id={alias_id}`, `canonical_risk_decision_id={canonical_id}`, and `alias_of={canonical_id}`. The canonical record retains its canonical ID. The risk gateway owns this shape, preventing the former alias-key/embedded-ID mismatch while preserving provenance. An alias is compatibility correlation only; it does not change `risk_action`, freshness, producer, temporal evidence, or the canonical authority requirement.

The ordinary A+ reducer requires all three conditions:

```text
risk_decision_id present
AND risk_decision_record_resolved is true
AND normalized risk action == allow
```

The Redis-backed A+ context freshness boundary in `a_plus_trade_gate.service` is independently fail-closed for its regime, HTF, and trade-tape inputs. `_parse_utc` rejects blank, malformed, and timezone-naive strings instead of assuming UTC. `_fresh` requires at least one explicit generation alias (`generated_utc`, `generated_at`, or `generated_est`); multiple aliases must identify the same instant; generation cannot be future or older than `max_context_age_seconds`. If `available_at` is present it is a separate availability clock, must be aware, cannot precede generation, cannot be future, and must itself be within the age window. Missing/invalid evidence produces the context-specific stale/missing result and prevents A+.

This contract is intentionally described exactly: `available_at` is validated when present but is not yet mandatory on legacy context payloads. A fresh legacy generation clock without `available_at` remains eligible. The guard evaluates against the passed A+ evaluation `now`; it does not by itself establish an immutable earlier allocation/admission decision receipt. Cross-asset, microstructure, trainer-metric, side-performance, and feedback inputs have separate checks and do not all inherit `_fresh`. Therefore the repair closes naive/future/alias-conflict handling for three derived contexts, not RE-003's complete feature-enrichment lineage gap or RE-050's allocation receipt.

#### Frozen entry and preemptive decision inputs

The paper loop formerly evaluated some gates against a different Redis generation than the inputs used around allocation. `evaluate_entry_gate` could independently read cascade/liquidation evidence, adaptive confidence tuning, exact/aggregate outcome memory, and side performance. Preemptive `decision.evaluate_candidate` read the loss threshold while `candidate_loss_risk` separately read the microstructure threshold. A Redis mutation between those reads made the resulting admission impossible to replay from one state.

Current paper source establishes explicit materialization boundaries:

1. The cycle reads `v2:orchestrator:adaptive_gate_tuning_state` once and hashes the full canonical payload in `_adaptive_tuning_receipt`.
2. Trainer metrics, cross-asset context, feedback rows, and derived side performance are frozen once per cycle. Regime, HTF, tape, and the selected microstructure payload are read once per `(symbol,timeframe)` and cached with key, observed time, presence and full-payload hash lineage.
3. Before allocation, the candidate binds that A+ context plus one outcome-memory object, the already validated cascade context, the cycle-derived side performance, and a two-element confidence-floor tuple. The floor source distinguishes explicit tuning, mixed tuning/config, and cycle config default. `paper_entry_gate_snapshot` hashes these inputs and their observation/provenance fields.
4. `evaluate_entry_gate(..., runtime_evidence_preloaded=True, redis_client=None)` cannot fall back to Redis for any of those four evidence families. Relevant absence blocks with `RUNTIME_EVIDENCE_PRELOAD_MISSING:{CASCADE_CONTEXT|ADAPTIVE_CONFIDENCE_FLOORS|OUTCOME_MEMORY_BUCKET|SIDE_PERFORMANCE}`. Cascade is conditionally required only for short `trend_mode`. Floors must be exactly two finite, non-boolean values in `[0,1]`.
5. `paper_entry_gate_preloaded_evaluation_v1` binds the snapshot hash, evaluated time, allow/reasons, preload flag, exact confidence floor/source, outcome-memory source and side-gate result, then hashes the receipt. The intent, allocation, allocator model inputs, and risk row retain the relevant snapshot/evaluation hashes or receipt.

The entry service retains a compatibility read-through path only when `runtime_evidence_preloaded=false`; the paper-loop caller uses the strict path. This is a service API compatibility choice, not permission for future paper callers to omit the snapshot. Operators must validate the hashed strict receipt on a fresh row.

Preemptive control is separately pure with respect to runtime I/O. `evaluate_candidate(adaptive_tuning_state=..., decision_time=...)` deep-materializes the complete candidate and deep-copies one supplied tuning mapping before scoring; `decision.py` and `candidate_loss_risk.py` contain no Redis or environment reads. A deep-materialization failure yields `CANDIDATE_PAYLOAD_MISSING`/`NO_TRADE`, never a partial receipt. Threshold resolution is exact:

```text
loss threshold:
  explicit finite numeric [0,1] -> use it
  otherwise                     -> conservative 0.80

microstructure threshold:
  explicit finite numeric [0,1] -> use it
  else explicit enable_b_grade=true  -> 0.35
  else explicit enable_b_grade=false -> 0.40
  else                               -> conservative 0.45
```

A malformed explicit microstructure value never falls through to the relaxed B-grade threshold. Omitted decision time captures one aware UTC evaluator instant; an explicit aware time is UTC-normalized for deterministic replay. An invalid/naive explicit time makes entry `NO_TRADE` while preserving close/reduce-only handling. The canonical SHA-256 `preemptive_input_hash` covers the full candidate, resolved bucket, cost and advanced assessments, raw alternative-data evidence, frozen tuning, guardian/quarantine/control flags, and relevant clocks; `preemptive_decision_id` binds that hash. The receipt exposes schema/hash/algorithm, decision time/source/validity, tuning status/hash, and both used thresholds/sources. `summarize_preemptive_decisions` receives the same cycle tuning mapping. For the same nonempty mapping, `adaptive_tuning_state_hash` exactly equals the entry snapshot tuning payload hash; `preemptive_input_hash` is wider and intentionally differs.

These changes eliminate the identified late-read split in source, but do not prove deployment or atomic Redis state across the entire loop. The snapshot is process-local, multi-key source reads are not a Redis transaction, advanced-indicator strictness and complete allocation PIT remain separately open, and the first complete paper-loop run after these changes still contained unrelated failing fixtures. No source receipt can turn current negative expectancy into A+.

The trainer collision is removed in current source. `publish_lineage` writes only trainer-namespaced preview/handoff records and marks the orchestrator, risk, paper preview and returned signal with `authoritative_decision=false`, `record_authority=TRAINER_NON_AUTHORITATIVE_PROPOSAL`, and `proposal_source=V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER`. It no longer writes `v2:decision:risk:*`, `v2:decision:orchestrator:*`, or `v2:decision:index:*`. The paper loop's per-ID store is now a read-only observer and will not manufacture missing canonical records.

The broader policy architecture is still incomplete. The live-oriented risk gateway is the sole canonical risk/index writer found here and denies while live is disabled; bounded paper exploration remains a separate, explicitly non-A+ learning policy. The orchestrator is declared the intended producer of canonical per-ID orchestrator records, but the audited `v2_orchestrator_arbitration_loop.py` does not yet persist `v2:decision:orchestrator:{id}`. A dedicated paper risk policy/authority or deterministic reconciler still must define one policy version, expiry rule and final action for each paper candidate. This is now missing/segregated authority, not a trainer/risk last-writer race.

### 2.6 Adaptive allocator and leverage envelope

`AllocationInput` carries point-in-time equity, available margin, wallet balance, calibrated confidence, signed/side-normalized edge, integrity, volatility, liquidity, spread/slippage/fees/funding, drawdown, existing symbol/portfolio/correlation exposure, stop distance, exchange filters, PPO/MASA diagnostics, lineage IDs, and permitted leverage values.

`calculate_dynamic_risk_envelope` now uses continuous realized evidence rather than a sample-count pass/fail cliff. Its complete public input contract is:

```text
base_envelope
win_rate, profit_factor, closed_trade_count
current_drawdown_pct, model_avg_confidence, paper_mode
after_cost_edge_lower_bound_bps
after_cost_edge_evidence_count, after_cost_edge_evidence_source
edge_available_at
liquidity_score, regime_quality_score
market_context_source, market_context_available_at
decision_time
```

All numeric evidence rejects booleans and non-finite values. Counts must be positive integers. Win rate, confidence, liquidity and regime quality must be in `[0,1]`; profit factor and drawdown must be non-negative. All three evidence times must be timezone-aware and both `edge_available_at` and `market_context_available_at` must be no later than `decision_time`. A missing, naive, future, blank-provenance or invalid input cannot enable favorable leverage growth.

For valid performance evidence:

```text
evidence_weight        = n / (n + 25)
win_rate_evidence      = 2 * (win_rate - 0.5)
profit_factor_evidence = tanh(log(profit_factor))
realized_edge_evidence = 0.5 * (win_rate_evidence + profit_factor_evidence)
confidence_quality     = 0.5 + 0.5 * calibrated_confidence
drawdown_pressure      = current_drawdown / base_max_daily_drawdown

growth_evidence_valid = valid performance evidence
                        AND after_cost_edge_LCB > 0
                        AND positive-integer edge count
                        AND nonblank edge provenance
                        AND valid liquidity/regime scores
                        AND nonblank context provenance
                        AND edge/context available_at <= decision_time

joint_count          = min(closed_trade_count, edge_evidence_count)
growth_weight        = joint_count / (joint_count + 25)
context_quality      = sqrt(liquidity_score * regime_quality_score)

risk_log_factor = min(0, realized_edge_evidence)
                  * evidence_weight * confidence_quality
                  - 0.75 * drawdown_pressure
risk_factor     = clamp(exp(risk_log_factor), 0.20, 1.0)

losing_pressure      = min(0, realized_edge_evidence)
                       * evidence_weight * confidence_quality
favorable_growth     = max(0, realized_edge_evidence)
                       * growth_weight * confidence_quality * context_quality
context_pressure     = (1 - context_quality) * growth_weight * 0.5
                       # zero when growth evidence is invalid
leverage_log_factor  = losing_pressure + favorable_growth
                       - context_pressure - drawdown_pressure
leverage            = clamp(base_leverage * exp(leverage_log_factor), 1, 10)
```

Every paper risk maximum can only remain at or contract below the sanitized base. As risk contracts, the minimum available-margin and liquidation buffers expand by `max(1, 1/risk_factor)`. Paper leverage remains within the immutable `[1x,10x]` boundary and can rise above the base only when realized evidence is favorable and the complete growth-evidence contract passes; confidence cannot reverse losing evidence. The current paper caller explicitly offers the allocator 1x/2x/3x/5x/10x/20x, but the envelope's 10x hard cap makes 20x ineligible. (`AllocationInput` itself defaults to 1x/2x/3x.) Live mode bypasses all paper adaptation and returns the operator-supplied base object unchanged.

Invalid paper base values are sanitized defensively: invalid risk maxima collapse to zero, invalid margin buffer becomes 100%, invalid liquidation buffer becomes 10,000 bps, and invalid leverage becomes 1x before the `[1,10]` clamp. The returned `RiskEnvelope` has no evidence-status or rejection-reason fields. Therefore a consumer cannot distinguish “complete evidence produced no growth” from “growth evidence was missing” from the envelope alone; the upstream inputs must be retained as a separate immutable receipt.

The paper-loop source now wires all growth fields. `_paper_performance_circuit_breaker_status` takes only strict-governed closed outcomes with finite realized after-cost PnL bps and publishes:

```text
after_cost_edge_lower_bound_bps
after_cost_edge_evidence_count
after_cost_edge_evidence_source=STRICT_GOVERNED_CLOSED_OUTCOMES_REALIZED_AFTER_COST_PNL_BPS
after_cost_edge_available_at=<circuit status generated_utc>
```

The lower bound is `mean - 1.959963984540054 * population_stddev/sqrt(n)`; with one row it equals that row's result. This is a normal-approximation bound using population variance, not a bootstrap or Student-t interval. Non-strict exploration/bootstrap/reconstructed rows are excluded from this growth evidence. The status generation time is a conservative “not before” availability stamp, but it does not retain each outcome's individual label-availability receipt.

For market context, `_paper_dynamic_envelope_market_context` considers only actionable LONG/SHORT signals. Each liquidity/regime component must have its own nonblank source and timezone-aware availability field, or share an explicit `market_context_source`/`market_context_available_at` bundle. Generic signal `available_at` and `source_available_time` are not accepted. Naive, malformed, future or out-of-range components are invalid. Growth context exists only when **every** actionable signal has both components; the reducer then uses minimum liquidity, minimum regime quality, maximum component availability, and source `CURRENT_ACTIONABLE_SIGNAL_SET_COMPLETE_COMPONENT_PROVEN_CONTEXT`. No actionable signal or incomplete coverage yields null context and `INCOMPLETE_ACTIONABLE_SIGNAL_CONTEXT_COVERAGE`.

The cycle-local `portfolio_context.dynamic_envelope_evidence` records the LCB/count/source/time, aggregated liquidity/regime/time, decision time, valid/actionable counts, full-coverage boolean, component sources, rejection reason, and `growth_requires_positive_after_cost_lcb_and_pit_context=true`. It is still a partial input receipt, not a `growth_evidence_valid` result: it omits exact contributing signal IDs, base/output envelope and reason for the resulting leverage. At this source cut it is not copied into the emitted `risk_envelope_dynamic_budget_status` or allocator `model_inputs`, so deployed auditability still requires another persistence patch.

Two calibration/attribution limitations remain material. `after_cost_edge_lower_bound_bps` acts as a strict positive-admission gate; its positive magnitude does not scale `favorable_growth`, which is still driven by realized win rate/profit factor. Context coverage and component PIT proof are now fail-closed in source, but the durable receipt still lacks contributor identities and the output decision. The new source wiring and focused tests establish bounded mechanics, not that adaptive >3x leverage is deployed, statistically calibrated, profitable, or attributable. The containment-driven paper restart produced no attributable dynamic-envelope input/output receipt at this evidence cut.

This system is not stuck at 1x. The 86 closed rows observed on 2026-07-17 contained 43 at 1x, 41 at 2x, and two at 3x, all `isolated_paper_simulated`. Higher leverage is not progress while expectancy is negative: leverage scales both favorable and adverse PnL and cannot turn a negative edge positive.

#### Per-candidate allocation point-in-time boundary

The bracket-glue audit found that cycle-start `runtime_now` was later reused and labeled as the allocation decision even though candidate-specific reads occurred after it. Current source instead captures one timezone-aware `allocation_decision_time = datetime.now(timezone.utc)` after assembling the current candidate's price, feature, spread/depth, fee, exposure, strategy-size, and allocation inputs. That same immutable value governs the first bracket selection and the reduced halted-probe reallocation; the probe path changes only `paper_risk_budget_fraction` and must not read newer market evidence.

`_strict_aware_utc_time` accepts only an aware `datetime` or an ISO string with an explicit offset/`Z`; it rejects booleans, bare epochs, malformed strings, and naive datetimes rather than assuming UTC. `_paper_allocation_point_in_time_contract` normalizes every listed component clock to UTC, rejects any clock after the immutable decision, requires provenance fields conditionally when its associated economic component is present, and returns:

```text
status=PASS|BLOCKED
decision_time
decision_time_semantics=IMMUTABLE_CAPTURE_AFTER_ALL_CANDIDATE_ALLOCATION_INPUTS_BEFORE_FIRST_ALLOCATION
component_time_fields_checked[]
required_component_time_fields[]
observed_component_times{}
rejection_reasons[]
future_input_count
```

A non-PASS result sets `AllocationInput.risk_veto=true` and `risk_veto_reason=PAPER_ALLOCATION_POINT_IN_TIME_CONTRACT_BLOCKED`; it does not repair or restamp the input. The intent persists `paper_allocation_decision_time`, semantics, status, reasons, and the full PIT evidence object.

The first clock inventory was nevertheless incomplete, so its semantics string was stronger than its proof. A read-only adversarial source audit found allocation-relevant clocks missing for dynamic-envelope edge/context evidence, the read-only fee schedule, flattened TA/ATR generation/availability/cutoff/candle finality, correlation availability/cutoff/capture, strategy-snapshot and cascade context, advanced-indicator availability, and some microstructure states. `cost_source_timestamp` was listed even though it was attached after preallocation; long/short clocks were telemetry-only. Microstructure availability was conditionally required only for a numeric trust score even though action/status can still affect sizing or blocking. These were high-severity replay/audit gaps: capturing a late aggregate time cannot prove that an unclocked component was available before it.

Current hardening expands the fixed clock registry to 47 component-owned fields. All present fields must parse strictly and be no later than the allocation decision; the following conditional contracts determine which fields are mandatory and add internal ordering:

| Economic component | Exact current time/provenance contract |
|---|---|
| Entry price | When price provenance is present, require `entry_price_source_available_at` and `entry_price_utc`; source availability must not follow the price observation. `entry_price_source_generated_utc` is also checked when present. |
| Entry feature/model | An identified entry snapshot requires cutoff, availability, generation, and its source decision. Cutoff and availability must not follow the source decision; every clock must not follow allocation decision. |
| Strategy/router | Any selected/identified strategy requires `strategy_feature_cutoff`, `strategy_available_at`, `strategy_decision_time`, and `strategy_temporal_contract_status=PASS`. An attached feature snapshot additionally requires its cutoff/availability. |
| Cascade/squeeze context | `ATTACHED_PIT_VALID` requires event, availability, generation, and source decision; cutoff is checked when present. The component reader rejects missing/naive/future clocks and orders cutoff/availability before source decision, then source decision/generation before strategy decision. |
| Spread/admission | A non-fallback observed spread requires availability, capture, spread decision, and paper-admission decision; availability precedes capture/source decision and capture precedes admission. |
| Microstructure | Presence of a trust source, action, or any supported numeric trust score requires available/generated/source-decision clocks. Availability must precede the source decision. A no-trade/reduce action therefore cannot evade clock requirements merely because its score is missing. |
| Read-only fee schedule | When venue/account read-only fees govern, require `fee_schedule_available_at`; effective, generated, and ingested clocks are checked when present. A configured static paper fee has no false external-availability claim. |
| TA-flat ATR fallback | Require `entry_atr_feature_cutoff`, `entry_atr_available_at`, `entry_atr_generated_at`, closed-candle true, exact source `v2_ta_flat_hash_adapter_v1`, and a 64-character lower-hex source hash. This producer defines availability as upstream TA availability and generation as later flat-adapter publication, so its exact order is cutoff ≤ upstream availability ≤ adapter generation. |
| Correlation | A READY `MARKET_OHLCV_RETURN_CORRELATION` value requires cutoff, source availability, correlation decision, computation time, and a 64-character lower-hex aggregate source hash. Cutoff/availability ≤ correlation decision ≤ computation ≤ allocation decision. |
| Dynamic envelope | Always check envelope decision/computation when present. An envelope whose max leverage is above 1x additionally requires edge and market-context availability; both must precede envelope decision, which precedes computation. |
| Capital/open book | Present portfolio state requires portfolio available/generated and consumer observation, with event ≤ availability and available/generated ≤ observation. A nonempty ledger requires ledger generation ≤ observation. `portfolio_context_observed_at` and `open_exposure_observed_at` are required together when either participates. |

The fee reader preserves `effective_at`, `generated_at`, `ingested_at`, and true `available_at` without treating event/effective time as consumer availability. The TA adapter refuses unfinished candles before publishing. Correlation derives its governing cutoff/availability and a digest over source hashes. Strategy cascade is normalized through a separate strict adapter before it can affect routing. Dynamic-envelope clocks are copied from the cycle evidence into each candidate. Missing or malformed required evidence produces field-specific reasons; it is never repaired by stamping allocation time.

Advanced-indicator context remains a separately guarded boundary rather than one of the 47 allocation fields: its reader requires the producer contract/consumer flags and rejects availability or generation after the entry-feature decision, then carries aggregate availability/generation. Because that reader currently uses the permissive strategy-time parser and does not order every advertised event/source-decision field, it still needs a strict-contract proof or inclusion in the allocation receipt if any advanced field can affect admission. Full `run_once`, component-complete negative tests, broad regression, compaction/restart lineage equality, and fresh runtime evidence remain required; the docs reconciler's first narrow checks passed only 2 selected paper-loop and 3 selected lifecycle/exit tests.

#### Candidate leverage target and rung selection

The dynamic envelope supplies the paper candidate's hard leverage ceiling. `_adaptive_leverage_target_selection` no longer lets confidence override a recommendation-contract violation or a risk pressure. For finite evidence:

```text
cost_drag_bps = spread + slippage + fee + abs(funding)
edge_quality  = max(0, after_cost_edge)
                / (max(0, after_cost_edge) + cost_drag_bps + max(0, volatility))
drawdown_resilience   = 1 - clamp(drawdown / envelope_drawdown_cap, 0, 1)
correlation_resilience = 1 - clamp(correlation / envelope_correlation_cap, 0, 1)

adaptive_quality = clamp(
  confidence * edge_quality * liquidity * regime
  * drawdown_resilience * correlation_resilience,
  0, 1
)

continuous_target = 1 + (dynamic_envelope_cap - 1) * adaptive_quality
```

Any `validate_leverage_recommendation` violation hard-sets the target to 1x with `phase8_leverage_recommendation_invariant_violation_fail_closed`; otherwise the reason is `continuous_market_evidence_within_supplied_dynamic_envelope`. The raw recommendation tier remains diagnostic and does not select leverage. `_select_margin_configuration` chooses the highest supplied permitted rung no greater than the continuous target and envelope cap. The runtime caller supplies `(1,2,3,5,10,20)`, but the 10x envelope hard bound excludes 20x. Paper margin scarcity cannot justify moving to a rung above the evidence target; if no allowed rung fits margin and liquidation constraints, allocation blocks. Live leverage remains 1x/operator-gated and unchanged.

The adaptive result exposes `leverage_dynamic_envelope_cap`, confidence/edge/liquidity/regime quality, drawdown/correlation resilience, `leverage_adaptive_quality`, the formula string, target and selection reason in allocator `model_inputs`. Paper input validation rejects non-finite required fields/envelope fields before adaptive math and emits `paper_allocator_input_validation_status=FAIL_CLOSED` plus exact `paper_allocator_input_rejection_reasons` on a zero-sized block.

Paper order-step quantization is part of the capital boundary, not a presentation adjustment. The former sequence selected leverage and `allocated_margin` from the larger pre-step notional and only then rounded quantity down; for a $100 price, $800 target, three-unit step and 2x leverage it could emit six units/$600 notional with stale $400 margin. Current paper `_allocate` uses:

```text
N_pre  = adaptive target notional before step quantization
q      = floor_to_step(N_pre / price, step_size)
N_final = abs(q * price)

require q >= min_qty and N_final >= min_notional when those filters are positive
select leverage/margin configuration using N_final
M_final = N_final / L
liquidation_distance_usd = N_final * liquidation_buffer_bps / 10,000
allocator_raw_maintenance_estimate = N_final * maintenance_margin_rate
```

A zero quantity or a post-step minimum failure returns `BLOCK_EXCHANGE_MIN_ORDER`, zero size, and never rounds a reduced/probe order upward. `_result`, isolated margin, hedge inputs, candidate-level cross-margin stress, exposure, costs and max-loss values all receive the same `q`/`N_final`. The model-input receipt includes `paper_post_quantization_exchange_filter_status`, before/after notional, post-step quantity, and `paper_margin_configuration_uses_post_quantization_notional=true`. The allocator estimate deliberately uses the raw bracket ratio because its input contract has no cumulative deduction; executed-position lifecycle separately applies exact `max(0,N_mark*r_m-cum)`. The separately operator-gated live sequence was not changed.

Requested hedge-aware sizing no longer amplifies notional. A hedge request is not proof of an atomically filled, funded and cap-safe hedge, so sizing uses the full unhedged stop and `size_amplification=1.0`. When the dormant flag is requested, diagnostics say `DISABLED_NO_ATOMIC_FUNDED_HEDGE_PROOF`, `requested=true`, `enabled=false`, and retain the full stop. Hedge intent/stress telemetry may still be produced later; it does not retroactively justify a larger entry size.

#### Maintenance and margin-mode contract

`AllocationInput.maintenance_margin_rate` now defaults to null. Paper accepts only a finite `0 < r_m < 1`. Missing, NaN, zero, negative or `>=1` produces `BLOCK_LIQUIDATION_RISK`, zero size, null maintenance estimate/liquidation price/buffer, `maintenance_margin_evidence_status=MISSING_OR_INVALID_FAIL_CLOSED`, and `liquidation_simulation_status=NOT_RUN_MAINTENANCE_MARGIN_MISSING`. The 2,400-configuration counterfactual grid prunes every configuration with `MISSING_OR_INVALID_MAINTENANCE_MARGIN_RATE` instead of assuming 0.005.

Live behavior was deliberately not changed without operator approval. A missing/invalid live rate still receives the historical internal 0.005 compatibility value and stamps `maintenance_margin_evidence_status=LEGACY_LIVE_COMPATIBILITY_DEFAULT`, `maintenance_margin_rate_live_compatibility_defaulted=true`, and `maintenance_margin_live_contract_migration_requires_operator_approval=true`; live leverage remains 1x/operator-gated. That is an explicit migration debt, not exchange evidence.

#### Exchange leverage-bracket evidence and paper source integration

`services/binance_usdm_leverage_bracket_evidence.py` and `cli/v2_binance_usdm_leverage_bracket_evidence.py` add a narrow account-specific evidence plane for Binance USD-M signed USER_DATA `GET /fapi/v1/leverageBracket`. The connector uses the existing `BinanceUSDMAdapter.signed_get` transport and explicitly stamps read-only/no-order/no-leverage-mutation/no-margin-mutation. It stores neither exchange credentials, evidence-authentication secrets, signatures/headers nor the raw response. This is an account-data read, not an exchange-setting call.

The [official Binance USD-M account reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account#notional-and-leverage-brackets) identifies this as a signed USER_DATA read, defines `initialLeverage` as the maximum initial leverage, and describes `notionalCoef`/`cum` as bracket metadata. The connector consumes the account-returned floor/cap directly and preserves `notionalCoef` without applying an undocumented second scaling.

Producer and consumer must share one `EvidenceSecurityContext`. `evidence_security_context_for_adapter` proves that the configured credential binding is account-specific; compares the adapter API key and secret to that exact binding; derives `mainnet` or `testnet` only from the allowlisted origins `https://fapi.binance.com` and `https://testnet.binancefuture.com`; and requires safe `trader_id`, `credential_ref` and authentication-key IDs containing only letters, numbers, `_`, `.`, or `-`. Evidence authentication uses `BINANCE_BRACKET_EVIDENCE_HMAC_KEY` and `BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID`. The HMAC key must contain at least 32 bytes and must differ from the exchange API secret. Neither secret is serialized or printed.

The producer writes only:

```text
v2:binance_usdm:leverage_bracket:{mainnet|testnet}:{trader_id}:{credential_ref}:{SYMBOL}
v2:binance_usdm:leverage_bracket_status:{mainnet|testnet}:{trader_id}:{credential_ref}
```

Default evidence freshness is 600 seconds, cache TTL is 900 seconds, and the poll-loop default is 300 seconds; these are configurable operational cache controls, not strategy entry thresholds. Per-symbol evidence carries exact binding/environment/key metadata, `fetch_started_at`, `fetched_at`, `generated_at`, `ingested_at`, `available_at`, `expires_at`, `cache_expires_at`, optional upstream `notionalCoef`, canonical bracket rows, `content_checksum_sha256`, and `evidence_hmac_sha256`. `available_at` is captured after source validation and immediately before the final checksum/HMAC seal plus atomic Redis SET; it is explicitly not a Redis commit acknowledgement, so the later consumer observation is still mandatory. The checksum detects canonical-content changes; the HMAC authenticates that content, including the checksum, inside the configured process/Redis trust boundary. They are not interchangeable.

Each bracket row contains `bracket`, `initialLeverage`, `notionalFloor`, `notionalCap`, `maintMarginRatio`, and `cum`. Brackets must start at zero, be ID/range contiguous, have non-increasing leverage ceilings, non-decreasing maintenance ratios, finite `0 < maintMarginRatio < 1`, nonnegative `cum`, first-tier `cum=0`, and exact cumulative-deduction recurrence across tier boundaries. For whole-position notional `N`, the selected tier's maintenance is `max(0, N * maintMarginRatio - cum)`.

`select_paper_bracket_evidence(redis_client, *, security_context, symbol, candidate_notional, decision_time)` is fail closed. `candidate_notional` means **total absolute symbol position notional after the proposed fill**, not the incremental order. `decision_time` must be aware; floor is inclusive and cap exclusive. It verifies the exact account/environment/key binding, producer/schema/source/read-only/mutation stamps, canonical row set, content checksum, HMAC, and timestamp lineage. Producer time must satisfy `fetch_started_at <= fetched_at <= generated_at <= ingested_at <= available_at < expires_at`. The consumer captures `consumer_observed_at` after Redis GET and `current_checked_at` after validation, then requires `available_at <= decision_time <= consumer_observed_at <= current_checked_at` and evidence unexpired at decision, observation, and current check. Missing context/evidence, malformed/tampered content, a naive/future/regressing clock, stale evidence, or out-of-range notional returns null maintenance/leverage authority. A READY result supplies the selected rate, cumulative deduction, exact maintenance estimate, and exchange-reported `max_initial_leverage`; `allowed=true` means only “evidence usable”—never trade admission. A mutable current key is deliberately not historical replay evidence.

`initialLeverage` is an exchange ceiling, not a recommendation. Paper integration must intersect it with the dynamic envelope, local immutable safety caps, and permitted rung, and must propagate the selected `maintMarginRatio` plus `cum` through allocation, liquidation, account reservation, fill, position, same-side aggregation, mark update, partial close, restart, and close receipts. `notionalCoef` is preserved as upstream metadata but not reapplied because the returned user bracket floors/caps are consumed directly; revisit only with explicit authoritative semantics.

Paper source integration now resolves one secret-safe context once at `run_once` startup and publishes `v2:paper:maintenance_bracket_security_status`. Missing/mismatched account binding, origin, or HMAC configuration becomes a BLOCKED status rather than an exception or fallback. The same context is used for every allocation and lifecycle selection in that cycle.

Allocation chooses a conservative governing tier before sizing. It adds current gross symbol exposure to the fraction-adjusted envelope maximum incremental notional, selects the bracket at that high-water total, intersects permitted leverage rungs with `initialLeverage`, and calls the allocator with the selected raw rate. Because the allocator contract has no `cum`, its pre-fill maintenance simulation does **not** subtract the cumulative deduction; this overstates rather than understates maintenance. After quantization it selects again at observed total notional and compares usability, checksum, HMAC, binding, environment, authentication key ID, availability, and expiry. It intentionally retains a higher preselected tier when rounding places the result in a lower tier.

The independent glue audit demonstrated that an injected allocator could exceed the high-water and still return READY with a worse observed tier. Current `_paper_allocate_with_bracket_evidence` closes that source defect: `observed_total > conservative_total + max(1e-8, abs(conservative_total)*1e-9)` blocks, and the post-pass also rejects a greater maintenance rate or lower maximum initial leverage. Canonical bracket validation already requires nondecreasing rates, nonincreasing leverage ceilings, contiguous ranges, and the exact `cum` recurrence. This is a source invariant only until the post-audit regression and full-run proof are recorded.

Lifecycle intends to use the exact whole current net position at current mark. A discarded preflight reconciliation derives net quantities; the loop then selects authenticated evidence for `abs(net_quantity) * mark_price`, attaches rate, `cum`, ceiling, checksum/HMAC/binding/environment/key/times to the mark, and runs final reconciliation once from the original inputs. Same-side aggregation selects the more conservative complete fill-bound bracket until the next mark reselection rather than weighting rates.

The independent audit also demonstrated that lifecycle once accepted a forged partial `prevalidated` mapping. Current `PaperNetPosition.apply_maintenance_bracket_evidence` requires the complete field set: lower-hex SHA-256-shaped checksum and HMAC, evidence-hash/checksum equality, exact known environment and Binance source, an environment-prefixed three-part binding, nonempty key ID, valid rate/`cum`/ceiling, and aware `available_at <= consumer_observed_at <= mark_time < expires_at`. Missing or malformed evidence makes maintenance/liquidation unknown. This is stronger structural and temporal validation, but not lifecycle-side cryptographic authentication: lifecycle has neither the HMAC key/security context to recompute the MAC nor a sealed typed verified-selection token. The normal authenticated selector creates the mapping upstream.

Persistence recovery no longer depends only on the normalized nested object. The producer writes both legacy and canonical flat aliases, including explicit `maintenance_bracket_prevalidated`, source, rate, `cum`, evidence hash/checksum/HMAC, binding/environment/key, availability/expiry/consumer observation, and status. `maintenance_bracket_evidence_from_payload` normalizes either `maintenance_bracket_evidence`, raw selector-shaped `paper_maintenance_margin_bracket_evidence`, or flat payload/allocation fields into the same lifecycle schema; selector-shaped content must explicitly carry `prevalidated=true`, otherwise it remains untrusted. Focused flat/selector/restart tests pass, but a full `run_once` compaction/restart proof remains absent.

Tier-0 emergency exit now computes side-aware current mark-to-liquidation distance from `liquidation_price_estimate`, rather than reading the nonexistent `liquidation_distance_bps`; a crossed or side-inconsistent estimate maps to zero. Paper execution also no longer claims cross-margin liquidation safety: if the allocator recommends a non-isolated mode, `_attach_paper_sizing` preserves that value as counterfactual telemetry and forces `isolated_paper_simulated` with `CROSS_MARGIN_DISABLED_NO_ACCOUNT_WIDE_LIQUIDATION_MODEL`. The account-wide cross model is still absent.

Before the post-audit fixes, broad source validation was green at 49 connector service/CLI, 449 paper-loop, and 498 combined connector+paper tests; formatting/lint and compilation also passed. The independent targeted glue audit passed 5 helper/compaction, 8 lifecycle-bracket, and 60 combined-selection tests while exposing the defects above. At an intermediate hardening cut, the docs reconciler reran 93 lifecycle, 411 complete paper-service, 450 paper-loop, and 499 connector+loop tests successfully. A later audit then found materialization-boundary TOCTOU and post-allocator sizing mutations, so those counts are historical checkpoints rather than final regression. The remaining uncovered cases are:

- one per-candidate allocation time is now captured after current input assembly, but the first checked/required field inventory omits several economically active component clocks; see the exact RE-050 inventory;
- lifecycle structurally validates the HMAC/checksum/binding envelope but does not cryptographically reauthenticate it or consume a sealed typed receipt;
- no `run_once` integration test proves context resolution → two-pass exact tier → persisted lifecycle/close fields;
- no full-run test proves the now-normalized nested/raw/flat schema remains identical through every compaction and restart surface.

This is **not integration completion or runtime certification**. No connector systemd unit was installed, no exchange network call was made, no connector service was restarted, and no fresh paper allocation/lifecycle row proves the path against produced scoped keys. The paper allocator fails closed when security context/evidence is wholly absent, and lifecycle makes maintenance unknown when its required mapping is absent/stale/malformed, but the remaining trust/control cases above still require repair. Environment/account/credential scope is encoded in the connector key and payload; a connector consumer using any other context fails binding validation. After account, credential-reference, environment, or HMAC-key rotation, old rows cannot authorize the new connector context and must expire or be deliberately removed. Failed refreshes do not overwrite a previously good row, so embedded expiry and exact context—not key existence—govern.

Paper margin-mode preference is also continuous. Cross mode is requested only when `leverage > 1` and:

```text
cross_benefit = confidence * edge_quality * liquidity * regime
                * drawdown_resilience * correlation_resilience
                * leverage_utilization * liquidation_quality

contagion_pressure = max(
  correlation_pressure, drawdown_pressure, volatility_pressure,
  1-liquidity, 1-regime
)

cross_net_benefit = cross_benefit - contagion_pressure > 0
```

The requested `cross_paper_simulated` mode then passes through `simulate_cross_margin_stress`, which may downgrade it. Because no account-wide cross liquidation model exists, paper execution attachment now preserves any surviving non-isolated recommendation only as `margin_mode_counterfactual_upstream` and forces `isolated_paper_simulated` with `CROSS_MARGIN_DISABLED_NO_ACCOUNT_WIDE_LIQUIDATION_MODEL`. This never changes exchange margin mode. The stress helper is candidate-only: it uses aggregate equity/available margin plus the candidate, optional hedge and simple maintenance/loss arithmetic; it does not model the complete open-position vector, nonlinear symbol tiers, covariance/cascade contagion, funding shocks, insurance/ADL or exchange liquidation rules. Its own static margin-call/buffer cutoffs and default parameter remain legacy surfaces outside this scoped allocator repair. Therefore cross-paper selection is research telemetry, not executable cross-margin safety authority.

Fixed operating gates still remain in `_allocate`: market-state 30/70 (paper/live), confidence 0.30/0.50, liquidity 0.01/0.05, spread/slippage ratio 2/1, positive after-cost edge, and fixed hedge pressure/cap breakpoints. Envelope drawdown/liquidation limits are safety boundaries; the others require the RE-040 classification/adaptivity audit. The leverage rung list itself is intentionally discrete and stepwise.

Account-wide paper capacity now comes from canonical open-position economics rather than raw cash alone. `build_paper_margin_status` uses the conservative positive minimum of equity and wallet balance, so unrealized gains are not pre-spent and unrealized losses reduce capacity immediately:

```text
margin_base       = min(positive equity, positive wallet)  # one positive value if only one exists
used_margin       = sum(validated_executed_notional / validated_effective_leverage)
free_before       = max(0, margin_base - used_margin)
buffer            = free_before * dynamic_min_available_margin_buffer_pct
usable_pre_cycle  = max(0, free_before - buffer)
required(candidate) = abs(executed_qty * executed_price) / effective_leverage
```

For an open position, executed notional must come from actual quantity × entry/fill price or a `current_capital_accounting` record explicitly marked `execution_notional_validated=true`; target/order/recommended notional is never used to establish already-consumed margin. A recommendation-only leverage is likewise not execution evidence. A validated adaptive allocation above 1x requires its decision-time envelope cap; a missing cap falls back to 1x, while a leverage above the recorded cap or an execution/allocation mismatch is invalid and blocks. Missing actual notional, invalid leverage, or missing/invalid maintenance-rate evidence in any existing open position makes account accounting incomplete, sets allocator available margin to zero, and blocks all new candidates. Reported upstream notional/margin remains provenance and cannot manufacture buying power.

`reserve_paper_candidate_margin` runs once after normalization/churn and immediately before lifecycle. It sorts candidates deterministically—preferred majors, confidence descending, symbol, timeframe, side, identity—and cumulatively consumes one in-memory `usable_pre_cycle` snapshot. A candidate that does not fit moves to blocked with `PAPER_ACCOUNT_MARGIN_RESERVATION_BLOCKED` and its exact insufficient/invalid reason. Only reserved rows enter lifecycle. Lifecycle materialization commits them into canonical open positions; post-lifecycle recomputation prevents reservation double-counting. A close or partial close releases capacity by reducing/removing canonical quantity on the next recomputation.

The pre-lifecycle invariant is `margin_base = used + newly_reserved + free`; after committed reservations are represented in open positions it is `margin_base = used + free`. All free fields clamp at zero and any deficit is explicit. The allocator separately blocks zero paper free margin and any selected margin above the adaptive post-buffer budget. Live allocation branches are unchanged.

This is process/cycle-local atomicity, not a durable transactional reservation ledger. There is no Redis CAS, append-only reservation journal, cross-process lease, or crash recovery record. The reservation receipt explicitly emits `cross_process_atomic=false` and `single_active_writer_required=true`. Correctness relies on one active paper-loop owner; overlapping `run_once` writers could reserve the same snapshot. A pre-commit crash loses only in-memory paper reservations and the next cycle reconciles the ledger, but multi-writer capacity and publisher-snapshot lag remain P1 evidence risks.

The paper loop now stamps both account and reservation receipts with `generated_utc`; the standalone account key and embedded ledger account receipt are written from the same object, so their timestamp must match. The portfolio publisher independently reconstructs its view and stamps nested margin status with the same `generated_utc` as its portfolio payload. Read-only runtime at 2026-07-17 18:33–18:45 UTC still showed the older shape: the standalone schema-v1 arithmetic receipt lacked `generated_utc`, the simultaneous ledger omitted both embedded receipts, and all six open positions lacked generation IDs. That mixed shape is not end-to-end deployment PASS; reconcile/restart the single intended writer and require an attributable matching ledger/key pair with explicit non-atomicity fields.

#### Trainer leverage/margin study is separate

`evaluate_leverage_margin_grid` is a study-only backtest helper; it never sizes a paper fill and never routes live. Version 2 removes the former score identity `edge * leverage * (base_buffer/leverage)`, which algebraically reduced every leverage to the same score and made the first 1x grid item win ties. For a fixed explicit base margin and a leverage candidate `L`, it now computes:

```text
edge_lower_bound = measured_after_cost_edge - measured_edge_uncertainty
context_quality  = liquidity * (1 - regime_risk) * (1 - drawdown_bps / 10,000)
context_edge     = edge_lower_bound * context_quality
tail_loss_bps    = max(stop_distance_bps, modeled_adverse_move_bps)
                   + execution_uncertainty_bps
gross_notional   = base_margin_usd * L
loss_fraction    = gross_notional * tail_loss_bps / 10,000 / equity_usd
implied_win_bps  = (context_edge + loss_probability * tail_loss_bps)
                   / (1 - loss_probability)
gain_fraction    = gross_notional * implied_win_bps / 10,000 / equity_usd
certainty_equivalent_bps = 10,000 * [
  (1 - loss_probability) * ln(1 + gain_fraction)
  + loss_probability * ln(1 - loss_fraction)
]
```

It requires after-cost edge, uncertainty/count/source/`available_at`, loss probability, stop/adverse/execution uncertainty, equity, explicit base and available margin, supplied 1x liquidation buffer, drawdown, regime/liquidity, risk-context source/`available_at`, and decision time. Both availability timestamps must be no later than decision time. Missing, invalid, future, non-positive-lower-bound, or unsafe evidence returns `best_leverage=null` and `study_admission_allowed=false`; it does not pretend that 1x is a recommendation.

The immutable study envelope remains the existing 1x/2x/3x grid, stressed liquidation buffer at least 500 bps, and modeled max loss no more than 1% of equity. Callers can tighten but never widen those caps. Only isolated margin is evaluated. Cross margin explicitly returns `CROSS_MARGIN_REQUIRES_ACCOUNT_WIDE_STRESS_AND_CONTAGION_MODEL` because this local two-outcome study has no covariance/contagion model.

Crucially, the only integrated caller, `policy_backtest.py`, still supplies its older static four-field payload. It now fails closed with 16 missing-evidence reasons, `best_leverage=null`, and no margin mode. Therefore this repair proves that the study math can select different leverage under complete synthetic evidence; it does **not** mean >1x is production-flowing through the trainer study. Wiring requires a purged chronological held-out after-cost distribution plus a point-in-time account/market risk snapshot—never fabricated constants. The model still approximates liquidation as 1/L without nonlinear maintenance tiers, uses a two-outcome calibration, and does not evaluate cross margin.

### 2.7 Paper admission

The paper loop is the highest-blast-radius control file. The relevant reducer now behaves as follows:

1. Require real economic fields; confidence cannot excuse missing price/quantity/notional.
2. Resolve exact prediction, orchestrator, risk, feature, market and cost evidence.
3. Fail closed on missing pre-trade loss probability.
4. Evaluate strategy, pre-trade, fee, churn, integrity, time, dedupe and performance state.
5. Evaluate A+ with resolved canonical risk action.
6. Keep temporal rejection reasons immutable; confidence cannot clear them.
7. Require fee gate in the local conjunction.
8. Apply tier/exploration policy without generic confidence-only admission.
9. Require allocator completeness, direction, churn, freeze/preemptive and fill-write invariants.
10. Append through the common accepted-fill reducer and lifecycle.

Signal discovery remains bounded—no full Redis `SCAN` on the large shared database—but no longer depends on a populated aggregate key. `_read_paper_signals` first consumes `v2:signals:paper`; if that yields no symbols, it seeds from the canonical runtime symbol universe and checks, in sorted order and within its time budget, both `v2:signals:paper:{symbol}` and the five explicit `:{1m,5m,15m,1h,4h}` variants. Per-symbol-only publishers can therefore be discovered without an unbounded keyspace walk. Discovery is not admission: a found signal still remains blocked unless every downstream invariant resolves.

Paper-only orchestrator action normalization recognizes `allow`, `pass`, `approve`, `open_long`, `open_short`, `proceed_long`, and `proceed_short` as the orchestrator stage's PASS aliases. Empty/unknown defaults deny. This does not grant risk permission: ordinary A+ separately requires a resolved canonical risk record whose normalized risk action is allow.

The two confidence-only fast paths remain visible as unreachable `False and ...` branches for audit history; they no longer execute. The post-allocation leverage mutator is similarly retired because changing leverage after allocation left margin and liquidation state stale. Removing the dead branches entirely is maintainability work, not evidence that they still execute.

Explicit exploration remains intentionally separate. It can generate bounded paper-only evidence while the broad performance circuit is halted, but it must retain fee, churn, integrity, one-minute, dedupe, thesis-timeframe, temporal, market-evidence, bleed and bucket-specific circuit checks. Exploration evidence must be tagged and excluded from strict A+ governance until it meets the strict contract.

#### Halted-performance probe and outcome-memory valve

The halted-empty-book probe is a liveness/research lane, not ordinary A+ admission. Probe confidence accepts only explicit finite `confidence_calibrated`; missing/raw-only confidence fails closed. `_paper_halted_probe_preexisting_safety_blockers` prevents a probe from erasing an already-present entry/local/market/fill/integrity or unsizable-allocation block. The circuit marks only the performance exception plus `paper_halted_probe_size_fraction=0.25`; it does not force final fill permission.

`run_once` then rebuilds the `AllocationInput` with the existing `paper_risk_budget_fraction` multiplied by 0.25 and calls the allocator again. The allocator applies the resulting fraction to both the risk budget and gross-notional ceiling before quantity quantization, then re-runs leverage, margin, maintenance, liquidation, exposure, and exchange-filter derivation. If the reduced target is below venue minimum, it blocks with `paper_reduced_risk_budget_below_exchange_min_order` instead of rounding the probe back up.

Probe capacity now uses a two-phase token lifecycle. An attempt consumes the explicit attempt budget, but the token remains pending while downstream gates run. Slot and symbol capacity finalize only through the common helper when an intent is actually appended to `accepted`; a rejected candidate releases its pending token at the next signal boundary or loop end. Token plus normalized symbol identity is checked, duplicate-symbol finalization and admission above the adaptive slot count fail closed, and runtime trace exposes attempted, pending, finalized, and released counts. All three ordinary accepted-append paths use the same finalizer; the adaptive-hedge synthesis path is deliberately untouched. Focused probe tests passed, while the whole paper-loop result was still awaiting bracket-security API reconciliation at this intermediate cut.

That source mitigation does not make the probe lane certifiable. Remaining hazards are:

- “open since last close” counts any position after one global close timestamp, not exact tagged probe generations per bucket; an unrelated close can remove a still-open probe from the count;
- `_seconds_since_iso` converts a future timestamp to age zero and raises on naive time, while some open/close comparisons are lexicographic strings from mixed fields;
- 300/900/1,800-second ages, confidence floor 0.65–0.75, 0.25 size, slot cap three and three attempts remain static heuristics, and the floor/rank is calculated from pre-validation signals;
- probe outcomes are not isolated by behavior policy and probe policy before entering outcome memory, so they cannot causally prove the full-serving policy's edge.

The current source preserves every non-performance owning gate and correctly releases/finalizes cycle-local capacity, but it still needs durable exact-generation accounting rather than global-last-close inference. The receipt must bind bucket, policy, signal, timestamps, full/reduced allocation, margin, final admission token, and final outcome; probe outcomes must remain a separate evidence stratum.

Outcome memory now uses schema `v2_outcome_memory_updater_v2` and trust contract `OUTCOME_MEMORY_TRUST_PIT_V2`. `_event_ts` selects the first actual close/exit execution field and sorts parsed aware datetimes; processing `generated_at` no longer orders economic events. `_event_outcome_available_at` uses an explicit close/outcome availability field when present, or the synchronous close-execution timestamp as the earliest honest fallback with an explicit source label. Buckets store `last_outcome_event_time`, `last_outcome_available_at`, their source fields, and a separately labeled processing `last_updated=OUTCOME_MEMORY_PROCESSING_TIME_NOT_EVIDENCE_FRESHNESS`. The degraded aggregate loader ages only `last_outcome_available_at`, so an unrelated rebuild can no longer refresh old evidence.

Admission into the rolling 30-event window now requires finite realized PnL USD and return bps with consistent sign; actual aware close and availability not before close or in the future; directional action consistent with side; all prediction/signal/risk/orchestrator/feature/MTF/model/checkpoint identifiers; aware feature cutoff, feature availability, and decision time; `available_at <= decision_time <= close` and `feature_cutoff <= decision_time`; and a `source_hashes` mapping containing at least a non-placeholder `feature_vector_hash`. When an entry execution time is present, it must be aware and satisfy `decision_time <= entry_execution_time <= close`. Missing/non-finite economics is rejected rather than zero-filled. Rebuild/update summaries expose `quarantined_rows`, `trust_coverage_complete`, exact `rejection_reason_counts`, and `governance_evidence_policy=STRICT_PIT_VALID_ROWS_ONLY`.

Drawdown is no longer lifetime loss-only dollars. `recent_pnl_usd` and `recent_bps` each compute rolling peak-to-trough drawdown; `drawdown_contribution_usd` remains only a negative compatibility alias, and the fixed −$10 hard block is retired. Rolling win rate, EV, slippage failure, reversal, and missed-TP/stop statistics still use fixed thresholds after 20 events; drawdown is diagnostic rather than an absolute-dollar gate.

This repair closes the rebuild-time freshness, zero-fill, parsed-ordering, and permanent lifetime-loss defects, but does **not** make outcome memory A+ authority. Residuals are explicit:

- source-hash validation checks required shape/non-placeholder values and top-level conflicts; it does not cryptographically authenticate the producer or prove the hash against immutable feature bytes;
- “quarantined” means excluded and counted in the rebuild/update summary; no separate durable quarantine key/file with rejected row identity is proven here;
- after 5,400 seconds a stale degraded timeframe aggregate still becomes `allowed=true`, `blocked=false`, source `*_STALE_EVIDENCE_ADVISORY`, rather than a typed, bounded probe/shadow-only request;
- the 5,400-second valve and rolling thresholds remain static operating policy;
- probe, exploration, and full-serving outcomes are not yet behavior-policy/probe-policy stratified.

Before governance, add authenticated/content-addressed producer proof, durable rejection identity, strict runtime propagation, and a typed probe-only stale response with opportunity/candle/posterior decay. Ordinary A+ must never treat stale advisory or mixed/unverified outcome memory as recovered edge.

#### Adaptive hedge runtime containment

Allocator hedge-size amplification is disabled as described above. The paper loop also now hard-disables the deferred hedge runtime through `PAPER_ADAPTIVE_HEDGE_RUNTIME_SAFETY_INTERLOCK=true`; `_adaptive_hedge_enabled` returns false even if the environment and Redis operator flag request hedging. The paper service was restarted at 16:00:27 EDT for immediate containment. At 20:00:29.746 UTC, `v2:paper:adaptive_hedge_status` reported `resolved_enabled=false`, `runtime_safety_interlock=true`, block reason `HEDGE_DISABLED_NO_ATOMIC_FUNDED_EXACT_LINEAGE_EXECUTION_PROOF`, `enable_source=runtime_safety_interlock`, and zero synthesized fills even though `env_flag_at_import=true`. That is deployed containment evidence only; it does not validate the dormant implementation.

The dormant implementation remains unsafe and must not be re-enabled as written. It can turn a prior directive into a next-cycle fill at the directive-time mark instead of an executable fill price, reuse the parent position's risk/orchestrator IDs for the opposite hedge, fall back by symbol instead of exact generation, and perform non-atomic directive get/delete. Lifecycle can defer a parent ATR stop that is already hit for as long as 600 seconds, while the “protection” arithmetic counts loss already suffered. Re-enable only with an independent canonical hedge decision linked to exact parent generation, current executable price/slippage, atomic two-leg funded-margin reservation, idempotent directive/fill state, and a rule that an already-hit stop is never suppressed unless filled protection is proven.

### 2.8 Fill identity, lifecycle, and close suppression

Prediction and signal IDs can recur; they are lineage, not unique economic entries. `entry_generation_identity` hashes this canonical payload:

```text
{
  version: PAPER_POSITION_GENERATION_V1,
  source_identity: strongest fill/intent identity,
  entry_time_utc: normalized entry timestamp,
  symbol: uppercase symbol,
  timeframe: lowercase timeframe,
  side: normalized long/short
}
```

The SHA-256 digest is `position_generation_id`; a new position ID is `paper_pos_<symbol>_<first16>`, with a hedge suffix where applicable. A complete identity requires both source identity and real entry time. A signal/prediction ID alone cannot suppress a later reopen.

`closed_generation_match` prefers equal explicit generation IDs, then equal complete derived generations. Legacy strong IDs require temporal evidence; an accepted entry later than the prior close is never suppressed as already closed. `suppress_accepted_rows_already_closed`, lifecycle dedupe, prior-state carry, and mark-to-market suppression all use generation-aware evidence.

Lifecycle transition rules are:

- flat plus valid long/short -> open a new generation;
- same-side fill -> validate both positions' capital invariants, then aggregate;
- opposite-side fill -> close/net the existing quantity; a residual quantity becomes a new opposite generation only through the defined transition;
- already-closed same generation -> `CLOSED_PREVIOUSLY`, not reopened;
- missing economics, exposure violation, or capital mismatch -> `ENTRY_BLOCKED`.

### 2.9 Paper capital, margin, liquidation, and PnL equations

For absolute executed quantity `Q`, execution/average price `P`, validated effective leverage `L >= 1`, selected whole-position bracket rate `0 < r_m < 1`, cumulative deduction `c >= 0`, and current mark `P_mark`:

```text
entry_notional N_entry = abs(Q * P)
mark_notional  N_mark  = abs(Q * P_mark)
allocated_margin M     = N_entry / L
maintenance_margin MM  = max(0, N_mark * r_m - c)

long  liquidation ~= max(0, (Q*P - M - c) / (Q*(1-r_m)))
short liquidation ~=        (Q*P + M + c) / (Q*(1+r_m))

liquidation_buffer_bps = directional_distance(P, liquidation) / P * 10,000
```

The lifecycle reselects one bracket for the **whole current position**, never a notional-weighted average of per-fill rates. These are paper-only isolated-margin approximations, not an exchange liquidation engine. The bracket formula models the reported maintenance tier and cumulative deduction, but liquidation still omits fees at liquidation, funding, insurance/ADL, cross-margin offsets, and other exchange-specific mark/liquidation rules. The allocator's pre-fill safety simulation currently accepts only a rate and conservatively does not subtract `cum`; exact cumulative accounting begins only when complete bracket lineage reaches lifecycle.

`_ensure_margin_leverage_consistency_rows` makes executed quantity × price authoritative, validates leverage against the decision-time cap, resolves maintenance only from current-position/row/allocation evidence, and writes the current result under `current_capital_accounting`. It does not rewrite `adaptive_allocation`, which remains immutable entry-decision provenance. When upstream notional/margin/liquidation values differ, they are retained under `*_upstream` or reconciliation fields. If maintenance evidence is missing, maintenance estimate and liquidation price/buffer are null, status says `UNAVAILABLE_MAINTENANCE_MARGIN_EVIDENCE_MISSING`, and reservation admission fails closed rather than inventing a tier.

`position_from_fill` treats recommendation as advisory: without executed leverage it uses fail-safe 1x, and without a prevalidated bracket mapping it leaves maintenance/liquidation unavailable instead of inventing 0.005. `PaperNetPosition.apply_maintenance_bracket_evidence` structurally validates the required checksum/HMAC/environment/key/binding/economic fields and their top-level equality, plus `available_at <= mark_time < expires_at`; when `consumer_observed_at` is present it must lie between availability and mark time. It cannot cryptographically recompute the HMAC because lifecycle does not receive the secret security context or a sealed verified-selection token, so `prevalidated` remains an upstream trust assertion rather than lifecycle authentication. `recompute_capital_accounting` accepts only the resulting usable lineage, finite `0 < maintenance_margin_rate < 1`, nonnegative finite `maintenance_margin_cum`, and positive mark-basis notional. Missing, future, stale, or structurally invalid evidence clears maintenance, liquidation price, and buffer with a fail-closed reason. `to_payload` preserves those nulls and bracket lineage at both top level and in `current_capital_accounting`, including restart/legacy-zero reconstruction. Historical closed rows are not silently rewritten.

For same-side aggregation:

```text
N_total = N_old + N_new
M_total = M_old + M_new
L_total = N_total / M_total
P_avg   = (P_old * Q_old + P_new * Q_new) / (Q_old + Q_new)
temporary bracket = whichever complete fill-bound bracket produces the larger
                    max(0, N_total_mark * r_m - c)
next mark = reselect one exact bracket for total current mark notional
```

For a partial close, current notional, allocated margin, maintenance margin, liquidation price and buffer are recomputed from the remaining quantity. Entry-time upstream allocation remains provenance, not current capital truth.

At the pre-audit baseline, the cumulative whole-position lifecycle contract passed 84 tests in `test_lifecycle.py`; the complete `services/paper_trade_management` unit directory passed 402; the paper-loop bracket consumer passed 449; and the combined connector+paper-loop suite passed 498. Later source changes superseded those as current regression counts. They remain historical source checkpoints, not proof of a deployed bracket poller or fresh authenticated lifecycle record.

Gross PnL is side-aware:

```text
LONG  gross_pnl_usd = (exit_price - entry_price) * closed_quantity
SHORT gross_pnl_usd = (entry_price - exit_price) * closed_quantity
gross_pnl_bps       = side-adjusted price return * 10,000
fee_usd             = abs(notional) * fee_bps / 10,000
slippage_usd        = abs(notional) * slippage_bps / 10,000
net_pnl             = gross - fees - slippage +/- funding adjustments
```

At the runtime cut, all 86 closed rows had the three capital fields, but 45 violated `gross_notional_usd ~= allocated_margin_usd * effective_leverage` beyond `max($0.02, notional * 1e-6)`. They remain historical evidence and must fail G10/quarantine where strict capital consistency is required. New-source normalization does not retroactively certify them.

### 2.10 Outcomes and trainer feedback

`build_close_event` propagates position generation, capital reconciliation, entry lineage, cost, funding, excursion, and close evidence. The close/outcome schema now carries the full maintenance field set when present: rate, `cum`, estimate, maintenance notional/mark price/mark time, bracket ID/ratio/cumulative deduction/max initial leverage, content hash/checksum, HMAC, binding, environment, authentication key ID, source, availability, expiry, consumer-observed time, prevalidation flag, status, and reason. This permits a future auditor to compare the final lifecycle position with the outcome and detect lineage loss. It does not cure the upstream lifecycle authentication gap; completeness and validity must be asserted, not inferred from field availability.

The paper loop writes closed rows, outcome labels, clean feedback, and quarantine as separate surfaces. A trainer-consumable row must prove:

- complete entry generation and exact close;
- finalized outcome horizon;
- correct long/short after-cost sign;
- no future feature/candle and no stale/missing required lineage;
- matched risk/admission semantics for its declared evidence tier;
- valid accounting and costs;
- behavior-action identity if used for PPO;
- no train/validation/holdout overlap.

Counterfactual exploration can supervise research targets but must not be mislabeled a realized behavior outcome or strict on-policy PPO trajectory.

## 3. Redis contract and ownership map

Redis is runtime state, not durable audit proof. Related keys are written independently; there is no general atomic transaction spanning prediction, risk, fill, ledger, outcome and feedback. TTL means a missing key may mean expiry or eviction rather than a clean negative decision.

| Key family | Observed/source writer | Principal reader | TTL/evidence | Authority caveat |
|---|---|---|---|---|
| `v2:features:latest:{symbol}:{timeframe}` | feature pipeline | trainer, orchestrator, paper | producer-specific | Current enrichment still lacks complete per-source PIT proof. |
| `v2:features:snapshot:{feature_snapshot_id}` | snapshot/publisher plane | trainer, replay, paper | producer-specific | Presence alone does not prove archive durability. |
| `v2:trainer:feedback:outcomes` | paper loop | trainer | no TTL asserted here | Must contain only clean/evidence-tagged rows. |
| `v2:trainer:feedback:outcomes:quarantine` | paper loop | trainer/operator | no TTL asserted here | Quarantine must never be silently promoted. |
| `v2:prediction:{symbol}:{timeframe}` | native trainer publisher/other installed publishers | orchestrator | IO-layer policy | Multiple publisher authorities remain an operational concern. |
| `v2:replay:snapshots:{prediction_id}` | native trainer publisher | paper/trainer | 86,400 s | Write success must precede routeable prediction. |
| `v2:trainer:hybrid_cuda:{heartbeat,status,metrics}` | native trainer | monitors/API | producer-specific | Status is self-report, not outcome proof. |
| `v2:trainer:hybrid_cuda:{orchestrator_decision_preview,risk_decision_preview,paper_intent_preview,paper_ledger_preview}` | native trainer | observability/paper handoff | IO-layer policy | Explicit `TRAINER_NON_AUTHORITATIVE_PROPOSAL`; never canonical approval. |
| `v2:orchestrator:proposals` | orchestrator | operator/diagnostics | 600 s | Selection only. |
| `v2:orchestrator:decisions` | orchestrator | risk gateway, paper | 600 s | Contains winners/held rows; not risk approval. |
| `v2:signals:paper` | orchestrator | paper | 600 s | Routeable rows are `RISK_PENDING` after repair. |
| `v2:orchestrator:heartbeat` | orchestrator | monitor | 300 s | Freshness must be checked. |
| `v2:orchestrator:adaptive_gate_tuning_state` | adaptive orchestrator/tuning producer | paper entry and preemptive gates | producer-specific | Paper reads once per cycle and binds a payload hash; presence/current value is not historical evidence without the per-candidate receipt. |
| `v2:regime:gate:{symbol}:{timeframe}` / `v2:context:htf:{symbol}` / `v2:market:trade_tape_features:{symbol}` / selected `v2:microstructure:*` | respective context producers | A+/paper snapshot | producer-specific | Read once into the per-symbol/timeframe paper context cache; the snapshot hash binds key/payload/observation, but underlying multi-key reads are not atomic. |
| `v2:risk:gateway:{decisions,latest,heartbeat}` | live-oriented risk gateway | paper/operator | default 300 s | Current expected action is deny while live is disabled. |
| `v2:decision:risk:{risk_decision_id}` | risk gateway | paper dereference | 7,200 s | Canonical risk writer collision removed; policy remains live-oriented/deny while disarmed. |
| `v2:decision:orchestrator:{id}` | intended: orchestrator | paper dereference | required by paper freshness contract | Current orchestrator per-ID persistence not found; absence fails closed and is a blocker. |
| `v2:decision:index:by_candidate:{id}` / `...:by_signal:{id}` | risk gateway | paper/operator | 7,200 s | Index is a pointer, not permission; trainer no longer writes it. |
| `v2:paper:intents` / `...held_by_paper_fill_gate` | paper loop | API/operator | loop-specific | Candidate truth, not executed-position truth. |
| `v2:paper:accepted_fills` / `...:quarantine` | paper loop | lifecycle/operator | loop-specific | Accepted rows still require lifecycle classification. |
| `v2:paper:ledger` | paper loop | portfolio/API/trainer diagnostics | loop-specific | Main paper accounting aggregate; multi-key writes are non-atomic. |
| `v2:paper:positions` | paper loop | allocator/portfolio | loop-specific | Generation-aware identity is required for new rows. |
| `v2:paper:closed_trades` | paper loop | guardian/trainer/operator | loop-specific | Historical inconsistent rows remain immutable evidence. |
| `v2:paper:outcome_labels` | paper loop | trainer | loop-specific | Must distinguish behavior versus counterfactual target. |
| `v2:paper:outcome_memory:{symbol}:{timeframe}` | paper loop/rebuild | entry gate | loop-specific | v2 separates event/availability/processing times and excludes invalid rows, but stale degraded evidence still becomes generic advisory allow; trust is structural, quarantine is summary-only, and no runtime governance proof exists. Never A+ authority. |
| `v2:paper:performance_circuit_breaker_status` | paper loop | admission/trajectory/operator | loop-specific | At cut: `HALTED_PERFORMANCE`, new entries false. |
| `v2:paper:account_margin_status` | paper loop | allocator/operator | heartbeat TTL | Arithmetic/cycle-local capacity receipt; no durable cross-process reservation journal. |
| `v2:paper:adaptive_hedge_status` | paper loop | operator/monitor | transient TTL | Must remain interlocked/disabled; requested env/Redis enablement is not authority. |
| `v2:paper:maintenance_bracket_security_status` | paper loop | operator/ledger status | loop heartbeat | Secret-safe per-cycle shared-context readiness and lifecycle reselection counts; READY does not prove keys/data or allocation success. |
| `v2:binance_usdm:leverage_bracket:{env}:{trader_id}:{credential_ref}:{symbol}` | isolated signed-read connector | paper allocator/lifecycle | 600 s evidence / 900 s cache default | Exact account/environment-bound, checksum+HMAC evidence. Source consumer tests pass, but no poller/runtime evidence is deployed; not trade admission, and context plus embedded expiry govern. |
| `v2:binance_usdm:leverage_bracket_status:{env}:{trader_id}:{credential_ref}` | isolated signed-read connector | operator | 900 s default | Scoped fetch/cache health only; no systemd unit/network deployment exists at this cut. |
| `v2:portfolio:state` | portfolio publisher(s) | allocator/paper/API | documented 900 s | Publishes wallet/used/free/post-buffer margin, but duplicate publishers and snapshot lag weaken authority. |
| `v2:goal:trajectory_1000x` | trajectory tracker | operator/UI | producer-specific | Objective telemetry, never a guarantee or admission override. |

## 4. Point-in-time and immutable safety invariants

The following are hard correctness constraints, not tunable trading thresholds:

| Invariant | Fail-closed consequence |
|---|---|
| Source candle is final and its close has passed | Exclude source/sample/candidate. |
| Every source `available_at <= decision_time` | Dirty sample/candidate; quarantine or reject. |
| Aggregate `feature_cutoff` is the newest contributing information time and `<= decision_time` | Reject; never substitute the oldest timeframe cutoff. |
| MASA `feature_cutoff <= PPO decision_time` | Reject cross-model input. |
| Model decision `<=` paper admission `<= execution_time` | Reject temporally impossible path. |
| Temporal window frame time `<=` target decision time | Omit/raise; never use list order. |
| Required lineage, economic fields and finite numbers exist | Reject; confidence cannot fill missing evidence. |
| Canonical risk record exact-match and action allow for ordinary A+ | Reject/pending on missing, stale, mismatch or deny. |
| A+ regime/HTF/tape generation clocks are aware, nonfuture, mutually consistent and fresh; supplied `available_at` is aware, fresh and no earlier than generation | Mark the corresponding A+ check missing/stale and reject A+. Legacy rows without `available_at` remain a documented compatibility gap. |
| Strict paper entry evaluation uses only a preloaded hashed snapshot; relevant cascade/floor/outcome/side evidence exists and no Redis fallback occurs | Reject with the exact `RUNTIME_EVIDENCE_PRELOAD_MISSING:*` reason; never repair by a late read. |
| Preemptive decision uses one frozen tuning mapping and evaluator-owned aware time; its complete canonical input hash binds the decision ID | Entry becomes `NO_TRADE` on invalid time/input materialization; close/reduce remains available. |
| `N ~= M * L`, `L >= 1`, `N > 0`, `M > 0` | Recompute from executed economics or block. |
| Paper allocation `N = abs(q*price)` after step quantization, post-step exchange minima pass, and `M = N/L` | Block the allocation; never retain pre-step margin/stress or round a reduced allocation upward. |
| Maintenance rate is finite `0 < rate < 1`, cumulative deduction is finite `cum >= 0`, and both have explicit current whole-position evidence | Null maintenance/liquidation and block allocation/reservation. |
| Bracket evidence has exact account/environment binding, checksum+HMAC, `available_at <= decision_time <= consumer_observed_at <= current_checked_at < expires_at`, and contains total post-fill symbol notional | Return no bracket authority; remain blocked without another valid maintenance source. |
| Position generation/state transition valid | Block before fill/lifecycle mutation. |
| Duplicate generation already closed | Suppress as closed, never reopen from stale accepted row. |
| Live release/armed/symbol/filter/dedupe/risk checks | Remain disarmed; no edit in this repair. |

## 5. Adaptive operating controls versus fixed boundaries

“No static thresholds anywhere” is not a truthful description of the current repository. The correct target is: **adaptive operating decisions inside immutable safety and certification boundaries**.

Adaptive operating controls include continuous realized-evidence weighting, calibrated confidence quality, volatility/liquidity/spread/slippage, drawdown pressure, correlation/exposure, regime and outcome-memory evidence, and dynamic risk/leverage contraction. They should move smoothly with point-in-time market and performance state.

Immutable boundaries include temporal ordering, finalized candles, dirty-data rejection, exact risk/action identity, finite/economic fields, accounting equations, position transitions, exchange filters, maximum operator envelope, live disarm and credential isolation. These must not relax because confidence is high or a growth target is aggressive.

Static operating thresholds still exist, including high-precision paper constants, discrete leverage choices, baseline `RiskEnvelope` fields, some confidence/tier/entry/exit gates, and performance/certification sample requirements. Each must be classified as one of:

1. exchange/protocol constraint;
2. immutable safety limit;
3. evidence/certification minimum that does not affect trading;
4. adaptive operating policy that still needs replacement;
5. deprecated/dead branch.

Until that inventory is complete, the system cannot claim all operating thresholds are adaptive.

## 6. A+ and 1000x certification semantics

The external verifier has 16 gates:

- G01–G03: change files, independent review, and critical/high evidence chain;
- G04–G07: minimum post-policy outcomes, long/short evidence, and symbol diversity;
- G08–G10: accounting reconciliation, feedback quarantine, and capital-field/math consistency;
- G11: counterfactual capital sweep;
- G12: all 17 rare-event scenarios pass with **zero warnings**;
- G13–G14: positive after-cost expectancy and acceptable profit-factor/drawdown evidence;
- G15: no real order/exchange mutation;
- G16: backend/frontend/route/safety validation.

A+ means all gates pass on fresh, attributable evidence. `WARNING`, waived/zero data, stale artifact, missing provenance, or a source comment is not PASS. The repaired scripts now enforce:

- G10 fails on zero strict rows and on any `gross_notional ~= margin * leverage` violation;
- G12 fails when any rare-event scenario is WARNING, even if none is explicit FAIL;
- the rare-event producer itself exits nonzero unless all scenarios pass.

At the intermediate integration cut, trainer/PIT passed 374 in 98.82 seconds; the combined paper/lifecycle/outcome/connector/loop/portfolio/fill integration set passed 929; risk/orchestrator unit/domain/composition/integration passed 125; and allocator plus simulation passed 142 after one stale fixture was corrected to require categorical raw-softmax behavior-policy identity. Later source audits changed the entry-gate snapshot, reduced-tier allocation, materialization, and post-quantization margin boundaries; the affected 929/142 totals are therefore historical checkpoints pending a final rerun. These results prove only the source contracts at the exact cut tested. They do not change the economic/certification evidence below, prove deployment, or authorize live behavior.

Fresh evidence at this cut is decisively non-A+:

- counterfactual G11: **FAIL**, 0/5 configurations, 85 trades, mean −5.9123 bps, PF about 0.8632–0.8634, win rate 41.18%;
- rare-event G12 artifact: 9 PASS, 0 FAIL, 8 WARNING; its stored `status=PASS` was generated before strict warning semantics and is not valid certification;
- paper circuit at 17:48:48 UTC: `HALTED_PERFORMANCE`, 23 governed outcomes, PF 0.7037, notional-weighted expectancy −7.7010 bps, new entries false;
- trajectory at 17:48:35 UTC: equity $2,991.1964 from $3,000, multiple 0.997065, realized PnL −$9.9269, actual daily rate −0.0745% versus required 7.978%, `on_track=false`, binding constraint `NO_A_PLUS_SUPPLY`;
- 45/86 historical closed rows violate the capital invariant used by strict G10.

The supplied Claude transcript records why the earlier green-looking artifacts changed: it appended audit finding `CG-F047` to `goal_state/V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN/FINDINGS.jsonl` after rerunning the counterfactual sweep and rare-event producer. The referenced artifacts were generated at 2026-07-17 14:05:50 UTC (G11 sweep) and 14:06:10 UTC (rare events), replacing stale 2026-06-23 evidence. That provenance is useful, but its original prose called zero explicit failures plus eight warnings a fresh G12 “PASS.” Under the corrected zero-warning contract, the same artifact is G12 **FAIL**. `CG-F047` explains the stale-PASS-to-fresh-evidence transition; it cannot override the stricter verifier.

Therefore leverage/margin adaptivity is a risk-control and learning capability, not evidence that the objective is feasible. First prove positive clean after-cost expectancy; then prove robustness, capacity and controlled scaling.

## 7. Function-level change-impact matrix for this repair

| Function/symbol | Direct change | Downstream impact | Proof still required |
|---|---|---|---|
| `TrainingExample.__post_init__` | Resolve canonical decision time and latest valid label-availability time; freeze behavior action. | Temporal windows, purged validation, trainer/eval sample inclusion, PPO eligibility. | Runtime missing/invalid timing counts; source-specific label-time provenance. |
| `_chronological_purged_split` | Sort by decision time, keep timestamp ties together, purge training labels overlapping validation. | Validation metrics and checkpoint promotion evidence. | Global immutable final-holdout ledger/non-overlap across every online/offline run. |
| `_validation_policy_edge` / `_checkpoint_promotion_decision` | Score held-out serving actions after cost; require positive mean and one-SE lower bound plus PIT-safe split. | Checkpoint persistence/reload and trainer health. | Fresh runtime promotion/rejection receipts and calibration over larger independent samples. |
| `_rejected_candidate_serving_status` / runtime serving guard | Serve only a promoted candidate or a verified restored prior checkpoint; otherwise suppress backtest/inference/prediction/lineage. | Every trainer-produced evidence surface. | Deployed rejected-restore failure injection and zero downstream writes. |
| `_parse_decision_ms` | Reject bool/non-finite/non-positive time. | Window ordering/inclusion. | Property tests across formats/timezones. |
| `build_example_windows` | No list-order fallback; causal assertion. | GRU input history. | Deployed trainer reload and future-frame telemetry. |
| `model_batch_tensor` | Temporal missing lookup raises. | Trainer/evaluator failure mode. | Outer loop must surface/quarantine rather than mask. |
| `_target_action_from_net_edges` / `_normalized_action` | Side-specific after-cost target and behavior outcome. | Replay labels, confidence/action supervision. | Regenerate/version affected replay. |
| `TrainingExample.__post_init__` / `_behavior_action_identity` | Freeze and validate entry action index/name independently of hindsight labels. | PPO eligibility, row-lane selection, action metrics. | Fresh sampled entry-to-close evidence; numeric probability/log-prob reconciliation. |
| `_ppo_ineligibility_reason` and publisher/paper behavior-contract propagation | Require categorical raw-softmax sampling; label current deterministic adjusted-policy rows PPO-ineligible. | Prediction, signal, accepted fill, lifecycle, outcome, feedback, trainer lane. | Implement genuine action sampling only with separate strategy/risk approval; prove exact distribution/action/checkpoint binding. |
| PPO torch gather in `train` | Gather current/new log probabilities at immutable behavior action only for exact eligible rows. | Clipped ratio and KL telemetry. | Ordered trajectory/return proof; current deterministic runtime should report zero PPO rows. |
| `build_trusted_replay_row` | Separate counterfactual and behavior outcomes. | Reward/label/feedback consumers. | Consumer-by-consumer field audit; holdout enforcement. |
| `publish_prediction` / `run_hybrid_trainer_cycle` | Commit persisted replay metadata to caller; suppress lineage when publication fails. | Prediction, orchestrator, risk and replay durability. | Deployed success/failure injection and fresh identical lineage. |
| `build_prediction_payload` / `DECISION_TEMPORAL_LINEAGE_FIELDS` | Propagate exact candle finality and MASA/PPO cutoffs; never infer finality. | Prediction, orchestrator, risk, signal PIT proof. | Fresh post-reload record and cross-surface equality. |
| `_prediction_to_proposal_and_signal` | HOLD non-routeable; directional edge. | Arbitration mix, long/short balance, proposal score. | Runtime hold test and distribution monitoring. |
| `_hppm_gate` | Short uses directional edge; non-entry actions held. | High-precision admission. | Static thresholds still require adaptive-policy review. |
| orchestrator `run_once` | Canonical IDs and `RISK_PENDING`. | Risk correlation, signal schema, paper dereference. | Matched record latency/expiry and no stale alias acceptance. |
| risk gateway per-ID writer | Alias key ID matches embedded ID; preserve canonical/alias provenance and temporal envelope. | Paper exact-ID dereference and audit replay. | Deployed canonical/alias equality and expiry tests. |
| trainer `publish_lineage` | Mark trainer previews/handoff non-authoritative; remove every canonical decision/index write. | Decision ownership, paper dereference, dashboards. | Reload proof; consumers must not reinterpret previews as approval; implement/verify orchestrator per-ID owner. |
| `_row_has_economic_fill_fields` | Missing prices no longer excused by confidence. | Economic fill inventory/lifecycle. | Negative tests for every missing field. |
| `_paper_preemptive_admission_rejection_reasons` | Missing loss probability blocks. | Admission and counterfactual feedback. | Runtime reason counts/no silent exception. |
| `_paper_policy_intent_decision_dereference` | Canonical record required; no local PASS. | A+, tiering, audit lineage. | Dedicated paper risk policy/authority and canonical orchestrator per-ID production. |
| A+ `_parse_utc` / `_fresh` | Reject naive/future clocks and conflicting generation aliases; preserve generation/availability semantics. | Regime, HTF, and trade-tape A+ checks and final `paper_tradeable`/`live_candidate_eligible` booleans. | Make availability mandatory/versioned or explicitly quarantine legacy rows; persist the exact evaluated context-clock receipt at admission; extend equivalent temporal contracts to every A+ input. |
| entry `evaluate_entry_gate` preloaded boundary / paper snapshot caller | Disable four Redis fallback families; fail closed on relevant missing/malformed evidence; bind snapshot and evaluation hashes through intent/allocation/risk. | Symbol/timeframe/mode/confidence/outcome/side admission, tiering, allocation provenance and materialized-fill auditability. | Final full paper-loop regression and fresh deployed strict receipt; every future caller must select the preloaded contract. |
| preemptive `evaluate_candidate` / `candidate_loss_risk` / `summarize_decisions` | Remove runtime I/O, deep-materialize inputs, freeze one tuning mapping, own strict decision time, hash the complete receipt and bind decision ID. | Loss/microstructure thresholds, probation/exploration/no-trade classification, admission, inventory/status and replay audit. | Final full paper-loop regression, fresh deployed hash equality, and monitoring for invalid-input/time NO_TRADE counts. |
| `_paper_decision_action` | Default deny; normalize paper-only `open_*`/`proceed_*` orchestrator aliases. | Every unknown/missing decision consumer and orchestrator-stage dereference. | Prove canonical risk remains independently resolved ALLOW; enumerate legacy strings. |
| `_read_paper_signals` | Bounded aggregate plus canonical-universe per-symbol/timeframe discovery. | Candidate coverage and paper-loop input count. | Runtime universe completeness, time-budget truncation counters, duplicate-source tests. |
| `_paper_halted_probe_preexisting_safety_blockers` / token finalizer / `_paper_block_new_entry_by_performance_circuit` | Require explicit finite calibrated confidence; preserve non-performance blockers; separate attempt/pending/finalized/released token state; request a 0.25 pre-allocation fraction. | Halted-book liveness, performance exception, actual accepted-slot capacity, and downstream gate ownership. | Exact durable probe-generation/bucket accounting; strict timestamp parsing; probe-stratified outcomes. |
| `AllocationInput.paper_risk_budget_fraction` / allocator `_allocate` | Scale paper risk budget and notional ceiling before quantization; re-derive all capital/liquidation fields; block below venue minimum. | Probe quantity, max loss, exposure, margin, maintenance, liquidation and exchange-filter result. | Final integrated paper-loop proof; immutable full/reduced allocation receipt and realized probe outcome calibration. |
| allocator paper `_allocate` post-step boundary | Quantize quantity first, recheck `min_qty`/`min_notional`, select margin on `abs(q*price)`, and drive result/stress from that same final notional; leave live sequence unchanged. | Allocation notional, selected/isolated margin, liquidation-distance dollars, raw-ratio maintenance, hedge/cross stress, costs, max loss, exposure, reservation and downstream lifecycle input. | Final integrated allocator/paper regression; fresh accepted allocation proves the diagnostics and identities; reconcile the unrelated isolated/cross test expectation. |
| `load_outcome_memory_bucket` / `_event_rejection_reasons` / `_update_bucket` | Separate event/availability/processing time; strict PIT/economic admission; parsed close ordering; exclude/count rejected rows; rolling drawdown. | Timeframe entry blocks/advisory allow, probe availability, and feedback policy. | Replace stale generic allow with typed probe only; authenticate producer/content; durable quarantine identity; policy strata and deployed proof. |
| `_ensure_margin_leverage_consistency_rows` | Keep `adaptive_allocation` immutable; write executed-current reconciliation under `current_capital_accounting`; require execution notional, decision-time leverage-cap and maintenance evidence; preserve upstream liquidation as non-authoritative. | Ledger, positions, outcomes, trainer feedback and account reservation. | Fresh post-reload fills/closes; remove/version lifecycle maintenance defaults; historical rows stay failed. |
| `_strict_aware_utc_time` / `_paper_allocation_point_in_time_contract` | Capture one per-candidate allocation decision, reject naive/unparseable/future component clocks, persist checked/required/observed/rejected field evidence, and veto on failure. | Dynamic envelope, price, feature, TA/ATR, cost, liquidity, correlation, strategy, allocator, bracket, probe, fill and downstream replay lineage. | Expand the required clock/source inventory for every economically active input; ensure all attachments occur before validation; full `run_once` negative/positive proof and final regression. |
| paper `run_once` | Remove confidence-only effective bypasses; common reducer. | Admission, sizing, churn, freeze, PPO stamps, lifecycle. | Branch-complete isolated tests and runtime no-bypass counters. |
| `_paper_performance_circuit_breaker_status` / paper-loop envelope context reducer / `calculate_dynamic_risk_envelope` | Compute strict-governed after-cost normal-approximation LCB; aggregate finite PIT signal context; sanitize paper inputs; never grow risk above base; require the complete contract for >base leverage. | Allocation risk/leverage/margin buffers. Source now wires all inputs and keeps a partial cycle-local `dynamic_envelope_evidence` receipt. | Persist output/admission/rejection/contributor receipt; require context coverage; calibrate LCB estimator/magnitude, regime shifts and tails; fresh reload proof. |
| `_paper_input_rejection_reasons` / `_maintenance_margin_contract` | Reject non-finite paper inputs; require finite `0 < maintenance rate < 1`; zero-size/null liquidation on failure. Preserve and explicitly stamp live-only 0.005 compatibility behavior. | Allocator admission, liquidation/cross-stress fields, counterfactual evidence and live migration telemetry. | Controlled paper reload; separately approved live contract migration; audit every other stress-helper caller. |
| `fetch_and_cache_leverage_brackets` / `select_paper_bracket_evidence` | Normalize, checksum, HMAC, and cache signed read-only account/environment brackets; select a strict-current PIT tier for total post-fill symbol notional. | Paper conservative allocation rate/ceiling and exact lifecycle whole-position rate/`cum`; no trade permission. | Install approved poller; scoped runtime keys, rotation/freshness monitoring, and fresh allocation-to-outcome receipt; no live use without separate approval. |
| `_paper_maintenance_bracket_security_context` / `_paper_allocate_with_bracket_evidence` | Resolve one context per cycle; select the high-water preallocation tier and exchange-ceiling intersection; block post-allocation high-water overshoot, evidence-generation change, higher maintenance rate, or lower leverage ceiling; reuse one per-candidate decision for full/probe passes. | Allocator rate/rungs, margin/liquidation stress, allocation lineage. | Close RE-050's complete component-clock inventory and prove the complete `run_once`; final post-audit regression required. |
| lifecycle exact-net preflight / evidence normalizer / `apply_maintenance_bracket_evidence` / Tier-0 exit / sizing attachment | Reselect at whole current mark notional; normalize nested/raw/flat schemas; require complete structural/temporal provenance; compute `max(0,N*r-cum)` plus `cum`-aware isolated liquidation; derive current liquidation distance; force non-isolated recommendations back to isolated paper execution; carry lineage through restart/close. | Position maintenance/liquidation, reservation, partial close, outcome/feedback. | Cryptographically reauthenticate or consume a sealed typed receipt; full-run/post-audit validation and runtime evidence. |
| `_adaptive_leverage_target_selection` / `_select_margin_configuration` | Replace confidence overrides/static target tiers with continuous evidence quality inside the envelope; recommendation violation →1x; scarce margin cannot raise leverage above target. | Recommended/effective leverage, allocated margin, liquidation buffer, position/account capacity. | Calibrate formula/rungs on clean held-out outcomes; persist exact envelope input/output receipt; fresh >1x attribution. |
| `_adaptive_margin_mode_selection` / `simulate_cross_margin_stress` | Request cross-paper only on positive modeled benefit minus contagion pressure, then allow stress helper to downgrade; never mutate exchange. | Paper margin-mode telemetry and stress fields. | Full open-book/tier/covariance/cascade model; remove/classify helper static cutoffs/default; no cross claim before account-wide validation. |
| allocator hedge-aware sizing branch | Retire hedge-arm notional amplification; requested flag remains full-stop 1.0 with `DISABLED_NO_ATOMIC_FUNDED_HEDGE_PROOF`. | Target notional, max-loss consistency, margin/exposure and later hedge plan. | Atomic funded-hedge proof and failure/partial-fill model before any future amplification. |
| `_adaptive_hedge_enabled` / paper hedge-status writer | Hard runtime interlock overrides env/Redis enable requests and emits explicit disabled reason. | Deferred hedge synthesis, lifecycle stop behavior and operator telemetry. | Preserve the interlock; monitor every restart; never treat requested/operator flag as resolved enablement. |
| `_synthesize_adaptive_hedge_fills` / lifecycle hedge stop suppression | Dormant unsafe path retained but unreachable under the interlock. | Opposite-side fill price/IDs/generation, margin reservation, ATR stop timing and parent/hedge netting. | Current executable price, independent canonical hedge decision, exact generation, atomic reserve/idempotency and no stop suppression before filled protection. |
| `evaluate_leverage_for_candidate` / `evaluate_leverage_margin_grid` | Replace 1x tie identity with PIT-complete expected-log-equity study; fail closed without evidence. | Trainer backtest study telemetry only; no allocator/order mutation. | Wire real held-out/account context; nonlinear maintenance tiers; cross-margin model. |
| `canonical_margin_requirement` / `build_paper_margin_status` | Separate candidate estimates from `OPEN_EXECUTED_POSITION`; accept only actual/validated executed notional, validate >1x against the entry envelope, require maintenance evidence, and set numeric free margin to zero when any open row is incomplete. | Allocator input, ledger, portfolio, operator status. | Single-writer reconciliation, timestamped runtime equality, stale-publisher lag and maintenance-tier source/version proof. |
| `reserve_paper_candidate_margin` | Deterministic cumulative current-cycle reservation; receipt declares non-atomic cross-process scope/single-writer requirement. | Final pre-lifecycle admission and blocked evidence. | Redis transaction/lease or enforced single-owner proof; crash/concurrency soak. |
| `fill_identity` / `suppress_accepted_rows_already_closed` | Generation-aware close suppression. | Mark-to-market and reopened symbols. | Legacy incomplete identity quarantine. |
| `_prior_matches_position_generation` / `_carry_prior_position_state` | Carry only same generation; optional capital carry. | Stops/trailing/hedge/context after restart. | Restart/reopen integration tests. |
| `PaperNetPosition.recompute_capital_accounting` | Rebuild entry capital plus current-mark bracket maintenance/liquidation from rate and `cum`. | Open ledger, partial closes, liquidation telemetry. | Deployed fresh tier reselection; account-wide margin-call/liquidation mechanism is still unverified. |
| `PaperNetPosition.apply_same_side_fill` | Validate and aggregate notional/margin/leverage; choose the complete bracket with greater whole-total maintenance until next exact mark reselection, never weight rates. | DCA/netting exposure and close accounting. | Deployed multi-fill/tier-boundary receipt; source tests pass. |
| `position_from_fill` | Canonical generation/capital fields and upstream audit values. | Every new open position/outcome. | New runtime rows must carry generation IDs. |
| `reconcile_paper_lifecycle` | Generation dedupe, closed suppression, capital block. | Open/closed positions, outcomes, feedback. | Multi-key crash/restart reconciliation. |
| `build_close_event` | Carry generation/accounting plus full maintenance-bracket rate/`cum`/mark/authentication/time/status provenance. | Closed trades, outcome labels, feedback, guardian/verifier. | Fresh strict close with field equality to the final lifecycle position and no lineage loss. |
| guardian G10/G12 functions | Math consistency and zero-warning certification. | A+ state/goal completion. | Rerun fresh artifacts; do not reuse stale PASS. |

## 8. Unresolved blockers

### P0

- End-to-end feature enrichment is not yet point-in-time complete for every source/field family.
- Current deterministic serving rows are correctly excluded from PPO; genuine categorical raw-softmax action sampling and ordered trajectory/critic semantics do not yet exist end to end. Do not report PPO as active from log-probability fields alone.
- Trainer canonical-decision writes are removed, but paper still lacks one complete canonical decision plane: the live-oriented risk gateway denies while disarmed, bounded exploration is a separate non-A+ policy, and canonical per-ID orchestrator persistence is not yet source-proven.
- Publisher durable-write propagation is repaired in source but lacks deployed failure-injection proof. In-cycle validation is now chronological and label-purged, but global immutable final-holdout isolation across online/offline/persistent consumers remains open.
- Fresh post-repair runtime outcomes have not yet earned A+; negative expectancy is the binding economic blocker.
- The halted probe now preserves generic downstream safety blocks, uses allocator-native reduced risk, and releases/finalizes cycle-local slot tokens at the actual accepted-append boundary. It remains P0-incomplete because exact probe-generation/bucket accounting, durable receipts, and strict timestamps are missing, and outcomes are not probe/behavior-policy stratified.
- Outcome-memory v2 repairs rebuild freshness, PIT/economic admission, parsed ordering, zero-fill, and lifetime-loss drawdown, but governance remains unsafe: stale degradation becomes generic allow, hash/producer proof is only structural, rejection quarantine is not durable, and policy strata are mixed. It must not authorize ordinary A+.
- Bracket paper glue cannot yet be certified. Source now blocks high-water/more-restrictive-tier violations, derives Tier-0 mark-to-liquidation distance, forces non-isolated recommendations to isolated paper execution, requires the full lifecycle provenance field/time envelope, captures one per-candidate decision, and normalizes nested/raw/flat schemas. Lifecycle still performs structural rather than cryptographic HMAC validation of a plain `prevalidated` mapping; advanced-indicator integration remains outside the 47-field strict allocation receipt; no full `run_once` proves the chain; and no broad post-audit/runtime receipt exists. These residuals can misstate PIT/provenance and must fail closed before runtime deployment.

### P1

- Trainer feature-count tests are reconciled to the intended current 446/1,784 source contract and the combined suite is 374 passed, but audited deployment/history used 477/1,908. Checkpoint, cache, replay, backtest, and serving identity still need versioned digest migration before promotion evidence is portable across generations.
- Current-cycle candidate reuse is blocked by one deterministic reservation pass, but there is no durable cross-process transaction/journal; concurrent paper-loop writers could still reuse the same snapshot.
- Historical capital-inconsistent closed rows cannot pass strict G10 and should remain immutable/quarantined.
- Account capacity and per-position liquidation telemetry exist, but no verified account-wide maintenance-margin-call/cascade liquidation engine covers portfolio equity collapse.
- The corrected leverage study is not wired to complete production evidence; its current `policy_backtest` caller correctly returns no recommendation, so it cannot support a claim that the trainer is learning >1x profiles end to end.
- Dynamic-envelope inputs are now source-wired, but the partial cycle-local evidence object is not yet a persisted versioned admission/output receipt. It lacks invalid context-row reasons/contributor identities and exact `growth_evidence_valid`; positive LCB magnitude is not used beyond the `> 0` gate. No post-reload allocation proves the path.
- `position_from_fill` no longer promotes a recommendation to executed leverage or invents a 0.005 maintenance rate. Recompute/serialization preserves null maintenance/liquidation across legacy-zero reconstruction; the paper allocator and counterfactual grid now require `0 < rate < 1`. A live-only 0.005 compatibility value remains explicitly stamped because changing that path needs operator approval, and `simulate_cross_margin_stress` retains a default for other callers. Those surfaces require a separate caller/migration audit.
- The Binance USD-M connector itself is strongly scoped/authenticated. Connector count at the intermediate cut remained 49; intermediate loop/combined counts were 450/499, with 93 lifecycle and 411 complete paper-service tests. Later materialization-boundary edits require a new final run. No poller/network/runtime evidence is deployed, so the observed system has no bracket authority. `max_initial_leverage` is only an exchange ceiling.
- Candidate leverage is continuous inside the dynamic envelope, but the runtime rung list is discrete; multiple allocator entry/market/liquidity/spread and hedge breakpoints remain fixed. Cross-paper mode uses only candidate-level stress and cannot be called account-wide margin safety.
- Hedge-size amplification and deferred runtime hedging are now contained, including a fresh disabled status after the paper restart. The dormant synthesis/lifecycle implementation remains unsafe and must not be re-enabled without atomic funding, independent decisions, exact generation and stop-preservation proofs.
- Static operating thresholds remain and need classification/replacement where they are neither protocol nor safety constraints.
- Redis multi-key writes need a durable receipt/reconciler; eviction/RDB-only persistence weakens audit authority.
- The cloudflared credential exposed by diagnostic process output must be rotated/revoked and moved to protected credential handling. No secret value is reproduced here.

## 9. Live boundary

This repair did not edit, enable, invoke, submit, cancel, modify, or test a real exchange order. `places_real_order=false`, `routes_to_live=false`, and `live_gate=blocked_human_only` remain the required state. Source contains dormant exchange mutation paths; any change to those paths or their callers requires separate explicit operator approval and a new audit.
