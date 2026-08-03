# Pass 4A Real-Time Trainer / Signal / Prediction Observation: 20260613_190847

Generated: `2026-06-13T19:08:47Z`

Scope: read-only four-hour trainer, prediction, signal, symbol, sizing, strategy, MTF, hedge, and liquidity-sweep observation. Documentation/report updates only. No code, config, runtime, exchange, strategy, PPO, MASA, provider, leverage, margin, approval-token, funding, or live-canary changes are allowed during the observation window without explicit approval.

## Observation status

| Field | Value |
|---|---:|
| Observation status | `IN_PROGRESS` |
| Start time UTC | `2026-06-13T19:08:47Z` |
| Current update | `T+0 baseline` |
| Live submit disabled | `true` |
| Live canary disabled | `true` |
| Live order submitted | `false` |
| Exchange action taken | `false` |
| Resolution applied | `none` |

## Live-control baseline

| State | Observed |
|---|---:|
| `live_gate` | `blocked_human_only` |
| `order_transport_submit_enabled` | `false` |
| `live_trading_enabled` | `false` |
| `live_blocked` | `true` |
| `operator_approved` | `false` |
| `places_real_order` | `false` |
| `exchange_action_taken` | `false` |
| `release_mode` | `NON_LIVE` |
| `order_submitted` | `false` |
| `writes_exchange_orders` | `false` |

## Trust and recorded-state baseline

| Check | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence_pass4a/20260613_190852` |
| Strict verifier exit | `0` |
| Strict critical failures | `0` |
| Strict total findings | `184` |
| Recorded-state run | `recorded_state_verification_pass4a/20260613_190852` |
| Recorded-state critical failures | `0` |
| Recorded-state total findings | `184` |
| Recorded-state invalid state count | `18` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Training samples rejected count | `0` |
| Trades blocked by data quality | `0` |
| Position transition reject count | `0` |

## Runtime counts at T+0

| Redis pattern | Count |
|---|---:|
| `v2:prediction:*` | `10` |
| `v2:signals:paper:*` | `10` |
| `v2:risk:decisions` | `1` |
| `v2:risk:gateway:decisions` | `1` |
| `v2:orchestrator:decisions` | `1` |
| `v2:paper:intents` | `1` |
| `v2:paper:ledger` | `1` |
| `v2:replay:snapshots:*` | `12` |
| `v2:market:mtf_snapshot:*` | `12` |
| `v2:decision:mtf_snapshot:*` | `0` |
| `v2:mtf_snapshot:*` | `0` |
| `v2:trainer:prediction_shadow:*` | `50` |

## Trainer baseline

| Field | Value |
|---|---:|
| Training loop active | `true` |
| CUDA active | `true` |
| Trained model available | `true` |
| Trainer native readiness claimed | `false` |
| V2 native trainer ready | `false` |
| Checkpoint source | `V2_LOCAL_TRAINED` |
| Checkpoint id | `v2_hybrid_ckpt_3357a88ca657796c46bf9949` |
| GPU | `NVIDIA GeForce RTX 5080` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `330955` |
| Replay rows loaded | `330685` |
| Labels loaded | `41656` |
| Minimum train rows | `64` |
| Minimum sample satisfied | `true` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |
| Published shadow predictions | `50` |
| Canonical prediction writes blocked | `true` |
| Did not overwrite stronger existing prediction | `true` |
| Paper block reasons | `confidence_below_threshold`, `replay_snapshot:ALL_TIMEFRAME_CANDLE_TIMESTAMPS_MISSING`, `replay_snapshot:SOURCE_EVENT_TIMES_MISSING` |

## Prediction baseline

| Category | Count |
|---|---:|
| Trusted canonical predictions | `10` |
| Actionable predictions | `0` |
| HOLD/no-trade predictions | `10` |
| Blocked predictions | `10` |
| Predictions with `pipeline_trust_v3` | `10` |
| Predictions with replay snapshot id | `10` |
| Predictions with MTF snapshot id | `10` |
| Predictions routed to live | `0` |
| Live order allowed predictions | `0` |
| Matured prediction accuracy rows in this observation window | `0` |

Canonical trusted prediction symbols at baseline:

| Symbol | Action | Confidence | Expected move | Trust |
|---|---:|---:|---:|---|
| `1000BONKUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `1000FLOKIUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `1000LUNCUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `1000PEPEUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `1000SHIBUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `1INCHUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `AAVEUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `ADAUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `ALGOUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |
| `ALICEUSDT` | `hold` | `0.0` | `0.0` | `pipeline_trust_v3` |

## Signal baseline

| Category | Count |
|---|---:|
| Paper signals | `10` |
| Paper signals with action `hold` | `10` |
| Paper signals with paper intent | `0` |
| Paper signals with paper fill allowed | `0` |
| Paper signals routed to live | `0` |

Observed paper signal state: `NO_PAPER_INTENT_FOR_ALL_TF_SIGNAL`.

## Data-quality baseline

Recorded-state verification has zero critical failures, but non-critical data-quality findings remain:

| Finding type | Status |
|---|---|
| Missing candle gaps | observed |
| Duplicate candles | observed |
| Non-positive volume candles | observed |
| Invalid feature values | observed |
| MASA/PPO directional disagreement | observed |
| Live/paper/backtest parity differences | observed |

Per Pass 4A rules, these are documented only. No remediation is applied during the observation window.

## Findings register

### Finding 1: Runtime is safe for observation

| Section | Detail |
|---|---|
| OBSERVED | Live submit, live canary, transport submit, operator approval, real-order placement, and exchange action are disabled. |
| HYPOTHESIS | The runtime is safe for read-only observation. |
| EVIDENCE | `v2:live_gate:state`, `v2:trader:execution_state`, and `v2:live_order_transport:status` all show disabled/non-live states. |
| RESOLUTION PROPOSED | None. Continue observation. |
| RESOLUTION APPLIED | None. |

### Finding 2: Trust is green, but edge sample remains insufficient

| Section | Detail |
|---|---|
| OBSERVED | Strict verifier exit is `0`; recorded-state critical failures are `0`; canonical trusted predictions exist, but all 10 are HOLD/no-trade. |
| HYPOTHESIS | The system is no longer blocked by trust architecture; it is blocked by signal actionability and sample size. |
| EVIDENCE | `v2:prediction:* = 10`, all canonical predictions have `pipeline_trust_v3`, replay, and MTF linkage, but action is `hold` with confidence `0.0`. |
| RESOLUTION PROPOSED | Continue paper/shadow collection; inspect why canonical publisher preserves HOLD records while shadow predictions exist. |
| RESOLUTION APPLIED | None. |

### Finding 3: Trainer is active, but native readiness and canonical publication are constrained

| Section | Detail |
|---|---|
| OBSERVED | Training loop is active, CUDA is active, trained model exists, and 50 shadow predictions are published. Native readiness is false and canonical prediction writes are blocked/preserved. |
| HYPOTHESIS | The trainer can train and shadow-publish, but downstream publication or readiness gates may be preventing actionable canonical decisions. |
| EVIDENCE | `v2:trainer:training:status` shows `training_loop_active=true`; `v2:trainer:prediction_publisher_status` shows `published_count=50`, `canonical_prediction_writes_blocked=true`, and `did_not_overwrite_stronger_existing_prediction=true`. |
| RESOLUTION PROPOSED | After observation, review canonical overwrite/readiness criteria and paper block reasons. Do not patch during the 4-hour window. |
| RESOLUTION APPLIED | None. |

### Finding 4: Paper/signal path is currently no-trade only

| Section | Detail |
|---|---|
| OBSERVED | All 10 paper signals are HOLD/no paper intent. |
| HYPOTHESIS | The paper path is mostly blocked by confidence, all-timeframe signal state, and replay snapshot metadata completeness in trainer/paper block reasons. |
| EVIDENCE | Paper signal state is `NO_PAPER_INTENT_FOR_ALL_TF_SIGNAL`; trainer block reasons include `confidence_below_threshold`, `replay_snapshot:ALL_TIMEFRAME_CANDLE_TIMESTAMPS_MISSING`, and `replay_snapshot:SOURCE_EVENT_TIMES_MISSING`. |
| RESOLUTION PROPOSED | Continue observing whether new trusted predictions become actionable; later inspect replay snapshot metadata for shadow-to-canonical publication path. |
| RESOLUTION APPLIED | None. |

### Finding 5: No prediction accuracy can be claimed at baseline

| Section | Detail |
|---|---|
| OBSERVED | No matured actionable prediction horizon has occurred inside the observation window. Baseline canonical predictions are HOLD with zero expected move. |
| HYPOTHESIS | Accuracy and edge cannot be measured until new predictions with horizons mature. |
| EVIDENCE | Matured prediction accuracy rows for the current observation window: `0`. |
| RESOLUTION PROPOSED | Only score predictions whose horizon matures during the observation window. |
| RESOLUTION APPLIED | None. |

## Interim classification

Current interim classification is `OBSERVATION_SIGNALS_NOT_ACTIONABLE` with a secondary state of `OBSERVATION_READY_FOR_MORE_PAPER_COLLECTION`.

This is not a final verdict. Final classification requires at least four hours of observation.

## Commands run

```bash
date -u +%Y%m%d_%H%M%S
redis-cli --raw GET v2:live_gate:state
redis-cli --raw GET v2:trader:execution_state
redis-cli --raw GET v2:live_order_transport:status
./export_pipeline_trust_evidence --redis-url redis://127.0.0.1:6379/0 --output-dir pipeline_trust_evidence_pass4a
./verify_pipeline_trust --input pipeline_trust_evidence_pass4a/20260613_190852 --output-dir pipeline_trust_evidence_pass4a/20260613_190852/report --strict-unknown
.venv/bin/python -m v2.backend.app.cli.run_recorded_state_verification --input pipeline_trust_evidence_pass4a/20260613_190852 --output-dir recorded_state_verification_pass4a/20260613_190852
redis-cli --raw --scan --pattern '<runtime-patterns>' | wc -l
redis-cli --raw GET '<selected trainer/prediction/signal keys>'
ps -eo pid,etimes,cmd | rg -i 'trainer|ppo|prediction|publisher|cuda|masa' | rg -v 'rg -i|pytest|codex|claude'
jq '{summary: .summary, counts: .counts, critical_failures: .critical_failures, active_stale_count: .active_stale_count, replay_snapshot_count: .replay_snapshot_count, mtf_snapshot_count: .mtf_snapshot_count}' pipeline_trust_evidence_pass4a/20260613_190852/report/pipeline_trust_report.json
find recorded_state_verification_pass4a/20260613_190852 -maxdepth 1 -type f -print -exec sed -n '1,220p' {} \;
```

---

## PASS4A UPDATE T+15

Timestamp UTC: `2026-06-13T19:23:02Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Exchange action taken | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T19:21:40Z` |
| Latest training finished | `2026-06-13T19:22:14Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `330955` |
| Replay rows loaded | `330685` |
| Labels loaded | `41656` |
| Trained model available | `true` |
| Minimum sample satisfied | `true` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |

### Prediction count

| Category | Count |
|---|---:|
| Trusted canonical predictions | `10` |
| Canonical selected action `hold` | `10` |
| Actionable canonical predictions | `0` |
| Paper signals | `10` |
| Paper signal action `hold` | `10` |
| Replay snapshots | `12` |
| MTF snapshots | `12` |
| Shadow predictions | `50` |

### New matured prediction accuracy

No new matured prediction accuracy is available yet. Current canonical predictions remain HOLD/no-trade with `confidence_calibrated=0.0` and `expected_move_after_cost_bps=0.0`.

### Signal generation summary

The paper signal path remains no-trade only. Paper block reasons remain:

- `confidence_below_threshold`
- `replay_snapshot:ALL_TIMEFRAME_CANDLE_TIMESTAMPS_MISSING`
- `replay_snapshot:SOURCE_EVENT_TIMES_MISSING`

### Symbol selection summary

No new actionable selected symbols appeared. Existing canonical trusted predictions remain the same 10 symbols from baseline.

### Data quality findings

No new critical trust failure was observed. Baseline non-critical data-quality findings remain tracked only.

### Sizing / margin findings

No live sizing path was activated. Existing live controls remain disabled. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

Observed canonical behavior is still HOLD/no-trade. MTF/replay evidence exists, but the trainer/paper block reasons indicate metadata completeness issues in at least one replay-snapshot path. Hedge behavior remains inactive in this interval.

### Liquidity sweep observations

No actionable sweep-related signal was observed in this interval.

### Issues found

#### Finding 6: Training cycles continue, but canonical actionability is unchanged

| Section | Detail |
|---|---|
| OBSERVED | A training cycle completed at `2026-06-13T19:22:14Z`, but canonical predictions stayed at 10 total and 10 HOLD/no-trade. |
| HYPOTHESIS | The trainer is running, but the publication/actionability gate is not producing new canonical actionable predictions. |
| EVIDENCE | `v2:trainer:training:status` updated; `v2:prediction:*` remains `10`; `selected_action_summary=10 hold`; publisher status still has `canonical_prediction_writes_blocked=true`. |
| RESOLUTION PROPOSED | Continue observation. If this persists through the window, inspect canonical prediction overwrite/readiness gates after the window. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Continue observation through the full window.
- Later, review why `canonical_prediction_writes_blocked=true` persists while shadow predictions exist.
- Later, inspect replay snapshot metadata completeness for the trainer/paper path.

### Applied resolutions

None.

---

## PASS4A UPDATE T+30

Timestamp UTC: `2026-06-13T19:39:31Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T19:38:29Z` |
| Latest training finished | `2026-06-13T19:39:03Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `330955` |
| Replay rows loaded | `330685` |
| Labels loaded | `41656` |
| Trained model available | `true` |
| Minimum sample satisfied | `true` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |

Trainer metrics key did not expose scalar loss metrics in this snapshot: `loss`, `policy_loss`, `value_loss`, `entropy`, `kl_divergence`, `explained_variance`, and `reward_mean` were null from `v2:trainer:hybrid_cuda:metrics`.

### Prediction count

| Category | Count |
|---|---:|
| Trusted canonical predictions | `10` |
| Canonical selected action `hold` | `10` |
| Actionable canonical predictions | `0` |
| Paper signals | `10` |
| Paper signal action `hold` | `10` |
| Replay snapshots | `12` |
| MTF snapshots | `12` |
| Shadow predictions | `50` |
| Canonical prediction generated range | `2026-06-12T22:39:30-04:00` to `2026-06-12T22:40:52-04:00` |

### New matured prediction accuracy

No new matured actionable prediction accuracy is available. Canonical predictions are still old HOLD/no-trade records, so no direction or magnitude edge can be scored from this interval.

### Signal generation summary

Paper signals remain unchanged: `10` total, all HOLD. No new paper intent conversion was observed.

### Symbol selection summary

No new selected/actionable symbols appeared. The canonical prediction set did not refresh during this interval.

### Data quality findings

No new critical safety or trust findings were observed in this snapshot. Baseline recorded-state non-critical data-quality findings remain tracked only.

### Sizing / margin findings

No live sizing path was activated. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

The observed runtime remains in no-trade behavior. MTF/replay evidence exists for the canonical predictions, but trainer/paper block reasons still include confidence and replay metadata completeness blockers.

### Liquidity sweep observations

No actionable signal or symbol candidate emerged to evaluate sweep response.

### Issues found

#### Finding 7: Canonical trusted predictions appear stale relative to active training cycles

| Section | Detail |
|---|---|
| OBSERVED | Training completed another cycle at `2026-06-13T19:39:03Z`, but canonical trusted predictions remain generated on `2026-06-12T22:39:30-04:00` through `2026-06-12T22:40:52-04:00`. |
| HYPOTHESIS | The trainer is active, but the canonical prediction publication path is not refreshing trusted decisions during the observation window. |
| EVIDENCE | `v2:trainer:training:status` timestamp advanced; `v2:prediction:*` stayed at `10`; canonical generated range did not advance; publisher status still has `canonical_prediction_writes_blocked=true`. |
| RESOLUTION PROPOSED | After the observation window, inspect canonical publication gating and freshness/overwrite policy. Do not patch during observation. |
| RESOLUTION APPLIED | None. |

#### Finding 8: Trainer scalar learning metrics are not surfaced in the observed metrics key

| Section | Detail |
|---|---|
| OBSERVED | The metrics key returned null for loss, policy loss, value loss, entropy, KL/divergence, explained variance, and reward mean. |
| HYPOTHESIS | Either metrics are stored in another status payload or trainer observability is incomplete for learning-quality analysis. |
| EVIDENCE | `v2:trainer:hybrid_cuda:metrics` did not expose these scalar fields at T+30. |
| RESOLUTION PROPOSED | Continue using available status/output evidence during observation; after the window, map the exact trainer metrics source if missing persists. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Continue observation.
- After the window, inspect canonical publisher freshness/overwrite gates.
- After the window, identify where scalar PPO/training metrics are persisted or add observability only with approval.

### Applied resolutions

None.

---

## PASS4A UPDATE T+45

Timestamp UTC: `2026-06-13T19:55:41Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T19:55:09Z` |
| Latest training finished | `2026-06-13T19:55:15Z` |
| Train rows | `0` |
| Validation rows | `0` |
| Row count | `270` |
| Replay rows loaded | `0` |
| Labels loaded | `37279` |
| Trained model available | `false` |
| Minimum sample satisfied | `false` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |
| Legacy trainer log stale seconds | `1620223` |
| Legacy trainer errors | `[]` |

### Prediction count

| Category | Count |
|---|---:|
| Trusted canonical predictions | `10` |
| Canonical selected action `hold` | `10` |
| Actionable canonical predictions | `0` |
| Paper signals | `10` |
| Paper signal action `hold` | `10` |
| Replay snapshots | `12` |
| MTF snapshots | `12` |
| Shadow predictions | `50` |
| Shadow prediction generated range | `2026-06-12T18:28:39Z` to `2026-06-12T18:28:39Z` |

Shadow sample at T+45 shows confidence approximately `0.5` and expected move approximately `-7 bps` for sampled 1m/5m symbols, generated on `2026-06-12T18:28:39Z`.

### New matured prediction accuracy

No new matured actionable prediction accuracy is available. No fresh canonical or shadow prediction timestamps advanced in this interval.

### Signal generation summary

Paper signals remain `10`, all HOLD/no-trade. No paper intent conversion was observed.

### Symbol selection summary

No fresh symbol selection was observed. Existing canonical and shadow prediction sets appear stale relative to current training-loop timestamps.

### Data quality findings

No new critical safety/trust issue was observed. The latest training cycle reports zero train/validation rows and zero replay rows loaded, which is now tracked as a trainer/data availability issue rather than an immediate trust failure.

### Sizing / margin findings

No live sizing path was activated. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

Observed strategy output remains no-trade. No hedge behavior was observed. MTF evidence count stayed constant.

### Liquidity sweep observations

No actionable signal or refreshed prediction was available to inspect for liquidity-sweep response.

### Issues found

#### Finding 9: Latest trainer cycle has no train/validation rows

| Section | Detail |
|---|---|
| OBSERVED | At T+45, `v2:trainer:training:status` reports `train_rows=0`, `validation_rows=0`, `replay_rows_loaded=0`, `minimum_sample_satisfied=false`, and `trained_model_available=false`, while `training_loop_active=true`. |
| HYPOTHESIS | The training loop is running but currently lacks eligible rows in the active window, or the status payload is reporting a failed/empty cycle after an earlier successful cycle. |
| EVIDENCE | T+30 status showed `train_rows=3583`, `trained_model_available=true`; T+45 status shows `train_rows=0`, `trained_model_available=false`. |
| RESOLUTION PROPOSED | Continue observing whether this is transient. After the window, inspect training row eligibility/replay loading if empty cycles persist. |
| RESOLUTION APPLIED | None. |

#### Finding 10: Shadow predictions are also stale

| Section | Detail |
|---|---|
| OBSERVED | Shadow predictions remain at `50`, generated at `2026-06-12T18:28:39Z`; sampled confidence is ~`0.5` and expected move is ~`-7 bps`. |
| HYPOTHESIS | The shadow prediction publisher is not refreshing during the observation window, or its source status is stale while training loop status updates independently. |
| EVIDENCE | `shadow_generated_range=2026-06-12T18:28:39Z` to `2026-06-12T18:28:39Z`; `v2:trainer:prediction_shadow:* = 50`. |
| RESOLUTION PROPOSED | Continue observing. After the window, inspect the shadow publisher loop and its readiness criteria if timestamps remain stale. |
| RESOLUTION APPLIED | None. |

#### Finding 11: Legacy trainer log observer is stale

| Section | Detail |
|---|---|
| OBSERVED | `v2:legacy_log_observer:trainer` points to `/home/wali/Desktop/AI BOT/logs/hybrid_trainer.log`, reports `new_bytes=0`, and `trainer_log_stale_seconds=1620223`. |
| HYPOTHESIS | The legacy log observer is not a reliable source for current trainer liveness in this runtime. |
| EVIDENCE | Redis training status updates in 2026-06-13T19:55Z, while legacy log observer reports a very stale log. |
| RESOLUTION PROPOSED | Use Redis runtime status as primary evidence for this observation; after the window, update or deprecate stale legacy log observer wiring only if approved. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Continue observation to distinguish transient empty trainer cycles from persistent data starvation.
- After the window, inspect training row eligibility/replay loading if empty cycles persist.
- After the window, inspect shadow/canonical publisher refresh criteria if timestamps remain stale.

### Applied resolutions

None.

---

## PASS4A CRITICAL UPDATE T+60

Timestamp UTC: `2026-06-13T20:11:54Z`

This update interrupts the normal cadence because the hourly fresh trust verification failed.

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

No live order path was armed and no exchange mutation was observed.

### Fresh trust check at T+60

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence_pass4a/20260613_201154` |
| Strict verifier exit | `1` |
| Strict critical failures | `4` |
| Strict total findings | `338` |
| Recorded-state verifier exit | `1` |
| Recorded-state critical failures | `3` |
| Recorded-state invalid state count | `7392` |
| Recorded-state invalid state rate | `0.7809` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Position transition reject count | `0` |

### Critical failures observed

| Check | Severity | Summary |
|---|---|---|
| `mtf_alignment.unfinished_higher_tf` | Critical | Unfinished higher-timeframe candles detected in decision/evidence windows. Example: `BANKUSDT` 5m/15m/1h/4h candles have `candle_closed_confirmed=false`, `closed_candle=false`, `is_closed=false`, while appearing in verifier decision context. |
| `replay_snapshot.missing` | Critical | `v2:risk:decisions` records in exported execution evidence are missing replay snapshot evidence. Example symbols include `DASHUSDT`, `CELRUSDT`, `LINKUSDT`, `ADAUSDT`, `STRKUSDT`. |
| `mtf_snapshot.missing` | Critical | The same `v2:risk:decisions` examples are missing MTF snapshot evidence. |
| `runtime_trust.active_stale_missing_contract` | Critical | Active/pre-trade-like risk records are missing `trust_schema_version`, `decision_id`, `mtf_snapshot_id`, `replay_snapshot_id`, `feature_cutoff`, `available_at`, and `all_tf_candle_timestamps`. |

### Signal/risk blocker interpretation

The risk evidence examples are important because they show `pre_trade_allowed=true`, `risk_manager_final_authority=true`, and strategy mode `no_trade_mode` with `strategy_allowed_actions=["hold"]`. That means the runtime is creating approval-like risk records for no-trade/hold strategy output without the full v3 contract, and the strict verifier correctly rejects them.

### Issues found

#### Finding 12: Fresh runtime evidence became strict-trust invalid during observation

| Section | Detail |
|---|---|
| OBSERVED | Baseline strict verifier passed, but the T+60 fresh export failed strict verification with critical failures. |
| HYPOTHESIS | A live runtime writer or exporter classification path is producing active/pre-trade-like risk records without full v3 replay/MTF linkage, and/or MTF evidence is including unfinished higher-timeframe candles. |
| EVIDENCE | `pipeline_trust_evidence_pass4a/20260613_201154/report/pipeline_trust_report.json` reports `critical_failures=4`, including `runtime_trust.active_stale_missing_contract`, `replay_snapshot.missing`, `mtf_snapshot.missing`, and `mtf_alignment.unfinished_higher_tf`. |
| RESOLUTION PROPOSED | Keep live disabled. After the observation window, fix only the responsible writer/classification/MTF-closed-candle path. Do not change strategy or trust rules. |
| RESOLUTION APPLIED | None. |

#### Finding 13: Runtime appears to be using or exporting unfinished higher-timeframe candles

| Section | Detail |
|---|---|
| OBSERVED | Verifier examples include `BANKUSDT` 5m/15m/1h/4h candles with `candle_closed_confirmed=false`, `closed_candle=false`, `is_closed=false`. |
| HYPOTHESIS | The MTF evidence/exporter path is including open/current candles, or the source incorrectly writes incomplete REST backfill rows into decision context. |
| EVIDENCE | `mtf_alignment.unfinished_higher_tf` critical failure affects 15m, 1h, 4h, and 5m across many symbols. |
| RESOLUTION PROPOSED | After the window, inspect closed-candle selection and MTF snapshot/exporter boundaries. No current/open candles may enter tensors or decision snapshots. |
| RESOLUTION APPLIED | None. |

#### Finding 14: Risk records are approval-like but missing v3 trust contract evidence

| Section | Detail |
|---|---|
| OBSERVED | Exported `v2:risk:decisions` examples show `pre_trade_allowed=true` and `risk_manager_final_authority=true` but miss v3 trust fields and replay/MTF snapshot ids. |
| HYPOTHESIS | An alternate paper/risk/orchestrator writer is still bypassing the shared v3 trust contract, or the verifier/exporter is classifying hold/no-trade risk records as active approvals because `pre_trade_allowed=true`. |
| EVIDENCE | Critical examples list missing `trust_schema_version`, `decision_id`, `mtf_snapshot_id`, `replay_snapshot_id`, `feature_cutoff`, `available_at`, and `all_tf_candle_timestamps`. |
| RESOLUTION PROPOSED | After the window, inspect the exact writer for `v2:risk:decisions` and decide whether hold/no-trade risk records should be denied/inactive or must carry full v3 contract. Do not patch now. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Keep live disabled and do not consider any canary activation.
- Continue observation to see whether the failures persist or clear on the next export.
- After the window, fix only the exact trust-invalid writer/classification/MTF closed-candle issue.

### Applied resolutions

None.

---

## PASS4A UPDATE T+75

Timestamp UTC: `2026-06-13T20:28:40Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Fresh trust check

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence_pass4a/20260613_202841` |
| Strict verifier exit | `1` |
| Strict critical failures | `4` |
| Recorded-state verifier exit | `1` |
| Recorded-state critical failures | `3` |
| Recorded-state invalid state count | `7365` |
| Recorded-state invalid state rate | `0.780273` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T20:28:03Z` |
| Latest training finished | `2026-06-13T20:28:35Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `331206` |
| Replay rows loaded | `330936` |
| Labels loaded | `41692` |
| Trained model available | `true` |
| Minimum sample satisfied | `true` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |

### Prediction count

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `72` |
| Canonical selected action `long` | `522` |
| Canonical selected action `short` | `76` |
| Paper signals | `671` |
| Paper signal action `hold` | `74` |
| Paper signal action `long` | `522` |
| Paper signal action `short` | `74` |
| Replay snapshots | `15973` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### New matured prediction accuracy

Not scored. Although many long/short predictions now exist, the fresh strict verifier fails, so these records cannot be counted as trusted edge evidence.

### Signal generation summary

Signals became actionable-looking by action label, but the evidence is not strict-trust valid. Current paper block reason list narrowed to:

- `confidence_below_threshold`

### Symbol selection summary

The verifier critical examples show new risk decisions for `BANKUSDT` and `DASHUSDT`; T+60 examples included `DASHUSDT`, `CELRUSDT`, `LINKUSDT`, `ADAUSDT`, and `STRKUSDT`. This suggests symbol selection is active, but the selected/risk records are not v3-contract complete.

### Data quality findings

Critical findings persist:

- unfinished higher-timeframe candles in MTF alignment
- active/pre-trade-like risk records missing replay snapshot evidence
- active/pre-trade-like risk records missing MTF snapshot evidence
- active/pre-trade-like risk records missing trust contract fields

### Sizing / margin findings

No live sizing path was activated. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

Strategy metadata in verifier examples shows `strategy_selected_mode=no_trade_mode` in prior examples, with block reasons such as `EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD` and `MASA_FUTURE_CUTOFF_BLOCK`. At T+75, action labels show long/short predictions, but strict evidence failure prevents treating them as validated strategy output.

### Liquidity sweep observations

No validated sweep response can be scored because the new actionable-looking records fail strict trust.

### Issues found

#### Finding 15: Runtime began producing long/short predictions, but they are not trust-valid for edge scoring

| Section | Detail |
|---|---|
| OBSERVED | `v2:prediction:*` increased from `10` to `670`, with `522 long` and `76 short`, but strict verifier still exits `1`. |
| HYPOTHESIS | The prediction/signal path is active, but one or more downstream writer/exporter paths is not enforcing v3 trust contract and closed-candle MTF requirements. |
| EVIDENCE | T+75 strict critical failures include `replay_snapshot.missing`, `mtf_snapshot.missing`, `runtime_trust.active_stale_missing_contract`, and `mtf_alignment.unfinished_higher_tf`. |
| RESOLUTION PROPOSED | Do not score these as edge. After the observation window, fix the exact risk/orchestrator/MTF writer path without weakening trust gates. |
| RESOLUTION APPLIED | None. |

#### Finding 16: Replay snapshot count exploded while MTF snapshot count stayed nearly flat

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots increased to `15973`, while MTF snapshots increased only to `13`. |
| HYPOTHESIS | Replay snapshot generation is running broadly, but MTF snapshot creation/linkage is not keeping pace or is keyed differently from exporter expectations. |
| EVIDENCE | T+75 Redis counts: `v2:replay:snapshots:* = 15973`, `v2:market:mtf_snapshot:* = 13`. |
| RESOLUTION PROPOSED | After the window, inspect MTF snapshot write/link/export patterns for the active prediction/risk path. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Keep live disabled.
- Do not count T+75 long/short records toward Pass 2B edge proof while strict verifier fails.
- After observation, fix exact trust/MTF writer or classification path.

### Applied resolutions

None.

---

## PASS4A UPDATE T+90

Timestamp UTC: `2026-06-13T20:45:37Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T20:44:44Z` |
| Latest training finished | `2026-06-13T20:45:17Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `331359` |
| Replay rows loaded | `331089` |
| Labels loaded | `41735` |
| Trained model available | `true` |
| Minimum sample satisfied | `true` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |

### Prediction count

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `83` |
| Canonical selected action `long` | `523` |
| Canonical selected action `short` | `64` |
| Paper signals | `671` |
| Paper signal action `hold` | `71` |
| Paper signal action `long` | `534` |
| Paper signal action `short` | `65` |
| Paper signal non-object records | `1` |
| Replay snapshots | `23316` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### New matured prediction accuracy

Not scored. Previous T+75 strict verifier failed; these records remain ineligible for trusted edge scoring unless strict verification returns to zero critical failures.

### Signal generation summary

Action labels are changing while key counts remain stable, indicating active updates or overwrites. Paper block reason remains `confidence_below_threshold`.

### Symbol selection summary

Symbol universe remains active, but trusted scoring is blocked by the unresolved T+75/T+60 strict failures.

### Data quality findings

No new verifier run was performed at this interval. The most recent fresh verifier result remains strict exit `1` and recorded-state exit `1` from T+75.

### Sizing / margin findings

No live sizing path was activated. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

Prediction action mix changed during the interval, but MTF snapshot count stayed static at `13` while replay snapshots grew to `23316`. This continues to point to a mismatch between replay generation and MTF snapshot/linkage coverage.

### Liquidity sweep observations

No validated sweep response can be scored while strict trust remains invalid.

### Issues found

#### Finding 17: Prediction action mix is updating without MTF snapshot growth

| Section | Detail |
|---|---|
| OBSERVED | Prediction keys stayed at `670`, but action mix changed to `523 long`, `64 short`, and `83 hold`; replay snapshots grew to `23316`, while MTF snapshots stayed at `13`. |
| HYPOTHESIS | The prediction/replay path is active, but MTF snapshot creation/linkage is not operating at the same cadence or exporter pattern. |
| EVIDENCE | T+90 Redis counts and action summaries. |
| RESOLUTION PROPOSED | After the window, inspect MTF snapshot writer/linker/exporter for active prediction/risk path. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Continue observation.
- Do not score edge until strict verifier returns zero critical failures.
- After the window, inspect MTF snapshot linkage and risk decision trust contract writer.

### Applied resolutions

None.

---

## PASS4A UPDATE T+105

Timestamp UTC: `2026-06-13T21:01:40Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T21:00:52Z` |
| Latest training finished | `2026-06-13T21:01:24Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `331384` |
| Replay rows loaded | `331114` |
| Labels loaded | `41745` |
| Trained model available | `true` |
| Minimum sample satisfied | `true` |
| Universe count | `135` |
| Timeframes | `1m`, `5m` |

### Prediction count

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `74` |
| Canonical selected action `long` | `529` |
| Canonical selected action `short` | `67` |
| Paper signals | `671` |
| Paper signal action `hold` | `76` |
| Paper signal action `long` | `527` |
| Paper signal action `short` | `67` |
| Paper signal non-object records | `1` |
| Replay snapshots | `31325` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### New matured prediction accuracy

Not scored. Latest known strict verifier status remains failed.

### Signal generation summary

Action mix continues to update. Paper block reason remains `confidence_below_threshold`.

### Symbol selection summary

The symbol universe remains active through the prediction/signal key set, but trusted scoring remains blocked by strict verification failure.

### Data quality findings

No fresh verifier run was performed at this interval. Latest known fresh verifier result remains T+75 strict exit `1`.

### Sizing / margin findings

No live sizing path was activated. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

The action mix remains long-heavy, but MTF snapshot count remains static while replay snapshots grow. This is now a repeated observation across T+75, T+90, and T+105.

### Liquidity sweep observations

Not scored because strict trust remains invalid.

### Issues found

#### Finding 18: Repeated replay/MTF growth divergence

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots grew from `23316` at T+90 to `31325` at T+105, while MTF snapshots stayed at `13`. |
| HYPOTHESIS | Replay snapshots are being written for active prediction/signal activity, but MTF snapshot generation/linkage remains blocked, stale, or exporter-invisible. |
| EVIDENCE | T+90 and T+105 Redis counts. |
| RESOLUTION PROPOSED | After observation, inspect MTF snapshot writer/linkage and exporter patterns for the active path. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Continue observation.
- Keep live disabled.
- Do not score predictions until strict verifier returns zero critical failures.

### Applied resolutions

None.

---

## PASS4A UPDATE T+120

Timestamp UTC: `2026-06-13T21:17:37Z`

### Runtime safety

| Field | Value |
|---|---:|
| Live disabled | `true` |
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

### Fresh trust check

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence_pass4a/20260613_211737` |
| Strict verifier exit | `1` |
| Strict critical failures | `4` |
| Strict total findings | `337` |
| Recorded-state verifier exit | `1` |
| Recorded-state critical failures | `3` |
| Recorded-state invalid state count | `7374` |
| Recorded-state invalid state rate | `0.780483` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Position transition reject count | `0` |

Critical check IDs remain:

- `mtf_alignment.unfinished_higher_tf`
- `mtf_snapshot.missing`
- `replay_snapshot.missing`
- `runtime_trust.active_stale_missing_contract`

### Trainer status

| Field | Value |
|---|---:|
| Training loop active | `true` |
| Latest training started | `2026-06-13T21:11:58Z` |
| Latest training finished | `2026-06-13T21:12:32Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Row count | `331384` |
| Replay rows loaded | `331114` |
| Labels loaded | `41745` |
| Trained model available | `true` |
| Minimum sample satisfied | `true` |

### Prediction count

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `67` |
| Canonical selected action `long` | `537` |
| Canonical selected action `short` | `66` |
| Replay snapshots | `38662` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### New matured prediction accuracy

Not scored. Strict verification failed again, so prediction edge cannot be evaluated as trusted evidence.

### Signal generation summary

Signals/predictions continue updating, but the risk/evidence layer remains strict-invalid.

### Symbol selection summary

Active symbols continue to be evaluated, but symbol-level accuracy and quality cannot be scored while evidence is strict-invalid.

### Data quality findings

The T+120 verifier confirms the T+60/T+75 failure is persistent, not transient.

### Sizing / margin findings

No live sizing path was activated. No leverage or margin mutation occurred.

### Strategy / hedge / MTF observations

Long-heavy action mix persists, but the observation cannot determine valid strategy edge because strict evidence remains invalid.

### Liquidity sweep observations

Not scored because strict trust remains invalid.

### Issues found

#### Finding 19: T+60 critical trust anomaly persisted through T+120

| Section | Detail |
|---|---|
| OBSERVED | Fresh verifier at T+120 still fails with the same critical check IDs as T+75. |
| HYPOTHESIS | The runtime has an active persistent writer/classification/MTF-closed-candle issue, not a one-off transient export artifact. |
| EVIDENCE | T+120 strict exit `1`, strict critical failures `4`, recorded-state exit `1`, recorded-state critical failures `3`. |
| RESOLUTION PROPOSED | After the observation window, stop edge work and fix only these exact critical trust failures before any further Pass 2B/3C consideration. |
| RESOLUTION APPLIED | None. |

### Proposed resolutions

- Continue read-only observation to complete the requested four-hour window.
- Do not score edge or recommend canary review while strict verifier fails.
- After the window, fix the exact trust-invalid writer/classification/MTF path.

### Applied resolutions

None.

---

## PASS4A UPDATE T+135

Timestamp UTC: `2026-06-13T21:34:08Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Trainer status

Latest observed training cycle: `2026-06-13T21:28:40Z` to `2026-06-13T21:29:12Z`. Training remains populated with `train_rows=3583`, `validation_rows=894`, `trained_model_available=true`, and `minimum_sample_satisfied=true`.

### Prediction / signal summary

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `79` |
| Canonical selected action `long` | `529` |
| Canonical selected action `short` | `62` |
| Paper signals | `671` |
| Replay snapshots | `47338` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### Accuracy / edge status

Not scored. Latest verifier state remains strict-invalid, so these predictions cannot be treated as trusted edge evidence.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots increased from `38662` at T+120 to `47338` at T+135, while MTF snapshots stayed at `13`. |
| HYPOTHESIS | Replay generation is active, but MTF snapshot linkage remains stalled or exporter-invisible. |
| EVIDENCE | T+135 Redis counts. |
| RESOLUTION PROPOSED | After the observation window, inspect MTF snapshot writer/linkage/exporter for the active prediction path. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

## PASS4A UPDATE T+150

Timestamp UTC: `2026-06-13T21:49:51Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Trainer status

Latest observed training cycle: `2026-06-13T21:45:18Z` to `2026-06-13T21:45:51Z`. Training remains populated with `train_rows=3583`, `validation_rows=894`, `row_count=331680`, `replay_rows_loaded=331410`, `labels_loaded=41787`, and `trained_model_available=true`.

### Prediction / signal summary

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `82` |
| Canonical selected action `long` | `519` |
| Canonical selected action `short` | `69` |
| Paper signals | `671` |
| Replay snapshots | `53350` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### Accuracy / edge status

Not scored. Latest verifier state remains strict-invalid.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots increased from `47338` at T+135 to `53350` at T+150, while MTF snapshots stayed at `13`. |
| HYPOTHESIS | The active prediction/replay path is running continuously, but MTF snapshot generation/linkage remains stalled. |
| EVIDENCE | T+150 Redis counts. |
| RESOLUTION PROPOSED | After the observation window, inspect MTF writer/linker/exporter and active risk writer. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

## PASS4A UPDATE T+165

Timestamp UTC: `2026-06-13T22:05:33Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Trainer status

Latest observed training cycle: `2026-06-13T22:01:58Z` to `2026-06-13T22:02:31Z`. Training remains populated with `train_rows=3583`, `validation_rows=894`, `row_count=331779`, `replay_rows_loaded=331509`, `labels_loaded=41812`, and `trained_model_available=true`.

### Prediction / signal summary

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `82` |
| Canonical selected action `long` | `519` |
| Canonical selected action `short` | `69` |
| Paper signals | `671` |
| Replay snapshots | `60030` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### Accuracy / edge status

Not scored. Latest verifier state remains strict-invalid.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Action mix is unchanged from T+150, replay snapshots grew to `60030`, and MTF snapshots stayed at `13`. |
| HYPOTHESIS | Active replay generation continues independently of MTF snapshot linkage. |
| EVIDENCE | T+150 and T+165 Redis counts. |
| RESOLUTION PROPOSED | After observation, inspect MTF linkage and active risk/pre-trade writer. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

## PASS4A UPDATE T+180

Timestamp UTC: `2026-06-13T22:21:15Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Fresh trust check

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence_pass4a/20260613_222115` |
| Strict verifier exit | `1` |
| Strict critical failures | `4` |
| Strict total findings | `337` |
| Recorded-state verifier exit | `1` |
| Recorded-state critical failures | `3` |
| Recorded-state invalid state count | `7351` |
| Recorded-state invalid state rate | `0.779616` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Position transition reject count | `0` |

Critical check IDs remain unchanged:

- `mtf_alignment.unfinished_higher_tf`
- `mtf_snapshot.missing`
- `replay_snapshot.missing`
- `runtime_trust.active_stale_missing_contract`

### Trainer / prediction summary

| Category | Value |
|---|---:|
| Latest training started | `2026-06-13T22:18:39Z` |
| Latest training finished | `2026-06-13T22:19:21Z` |
| Train rows | `3583` |
| Validation rows | `894` |
| Trained model available | `true` |
| Canonical predictions | `670` |
| Canonical selected action `hold` | `81` |
| Canonical selected action `long` | `523` |
| Canonical selected action `short` | `66` |
| Replay snapshots | `67377` |
| MTF snapshots | `13` |

### Accuracy / edge status

Not scored. Strict verification failed again.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Strict verifier has failed at T+60, T+75, T+120, and T+180 with the same critical check IDs. |
| HYPOTHESIS | The runtime has a persistent trust/MTF writer or exporter classification problem. |
| EVIDENCE | Repeated strict exit `1`, critical check IDs unchanged. |
| RESOLUTION PROPOSED | After the observation window, fix the exact runtime trust and MTF closed-candle defects before any edge or canary work. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

## PASS4A UPDATE T+195

Timestamp UTC: `2026-06-13T22:37:40Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Trainer status

Latest observed training cycle: `2026-06-13T22:35:30Z` to `2026-06-13T22:36:04Z`. Training remains populated with `train_rows=3583`, `validation_rows=894`, `row_count=331907`, `replay_rows_loaded=331637`, `labels_loaded=41843`, and `trained_model_available=true`.

### Prediction / signal summary

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `82` |
| Canonical selected action `long` | `523` |
| Canonical selected action `short` | `65` |
| Paper signals | `671` |
| Replay snapshots | `72721` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### Accuracy / edge status

Not scored. Latest verifier state remains strict-invalid.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots increased from `67377` at T+180 to `72721` at T+195, while MTF snapshots stayed at `13`. |
| HYPOTHESIS | Same persistent replay/MTF divergence. |
| EVIDENCE | T+195 Redis counts. |
| RESOLUTION PROPOSED | After observation, inspect MTF linkage and active risk/pre-trade writer. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

## PASS4A UPDATE T+210

Timestamp UTC: `2026-06-13T22:53:24Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Trainer status

Latest observed training cycle: `2026-06-13T22:52:15Z` to `2026-06-13T22:52:50Z`. Training remains populated with `train_rows=3583`, `validation_rows=894`, `row_count=331961`, `replay_rows_loaded=331691`, `labels_loaded=41855`, and `trained_model_available=true`.

### Prediction / signal summary

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `82` |
| Canonical selected action `long` | `520` |
| Canonical selected action `short` | `68` |
| Paper signals | `671` |
| Replay snapshots | `78733` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### Accuracy / edge status

Not scored. Latest verifier state remains strict-invalid.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots increased from `72721` at T+195 to `78733` at T+210; MTF snapshots stayed at `13`. |
| HYPOTHESIS | Persistent active replay generation without matching MTF evidence. |
| EVIDENCE | T+210 Redis counts. |
| RESOLUTION PROPOSED | After observation, inspect MTF linkage and active risk/pre-trade writer. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

## PASS4A UPDATE T+225

Timestamp UTC: `2026-06-13T23:09:08Z`

### Runtime safety

Live remains disabled: `live_gate=blocked_human_only`, `release_mode=NON_LIVE`, `order_transport_submit_enabled=false`, `live_trading_enabled=false`, `places_real_order=false`, `order_submitted=false`, `writes_exchange_orders=false`, `leverage_changed=false`, and `margin_mode_changed=false`.

### Trainer status

Latest observed training cycle: `2026-06-13T23:08:32Z` to `2026-06-13T23:09:04Z`. Training remains populated with `train_rows=3583`, `validation_rows=894`, `row_count=332024`, `replay_rows_loaded=331754`, `labels_loaded=41870`, and `trained_model_available=true`.

### Prediction / signal summary

| Category | Count |
|---|---:|
| Canonical predictions | `670` |
| Canonical selected action `hold` | `88` |
| Canonical selected action `long` | `514` |
| Canonical selected action `short` | `68` |
| Paper signals | `671` |
| Replay snapshots | `84745` |
| MTF snapshots | `13` |
| Shadow predictions | `50` |

### Accuracy / edge status

Not scored. Latest verifier state remains strict-invalid.

### Findings update

| Section | Detail |
|---|---|
| OBSERVED | Replay snapshots increased from `78733` at T+210 to `84745` at T+225; MTF snapshots stayed at `13`. |
| HYPOTHESIS | Persistent replay/MTF divergence. |
| EVIDENCE | T+225 Redis counts. |
| RESOLUTION PROPOSED | After observation, inspect MTF linkage and active risk/pre-trade writer. |
| RESOLUTION APPLIED | None. |

### Applied resolutions

None.

---

# PASS4A FINAL REPORT

## Final observation window

| Field | Value |
|---|---:|
| Start time UTC | `2026-06-13T19:08:47Z` |
| End time UTC | `2026-06-13T23:24:53Z` |
| Total duration | `4h 16m 6s` |
| Final verdict | `OBSERVATION_DATA_INVALID` |
| Live canary should remain blocked | `true` |
| Code/config/runtime changes applied | `none` |
| Documentation/report updates applied | `yes` |

## Final runtime safety state

| Field | Value |
|---|---:|
| Live gate | `blocked_human_only` |
| Release mode | `NON_LIVE` |
| Order transport submit enabled | `false` |
| Live trading enabled | `false` |
| Operator approved | `false` |
| Places real order | `false` |
| Exchange action taken | `false` |
| Order submitted | `false` |
| Writes exchange orders | `false` |
| Leverage changed | `false` |
| Margin mode changed | `false` |

No live order was submitted. No exchange state was mutated.

## Final trust and recorded-state result

| Field | Value |
|---|---:|
| Final evidence run | `pipeline_trust_evidence_pass4a/20260613_232453` |
| Final strict verifier exit | `1` |
| Final strict critical failures | `4` |
| Final strict total findings | `338` |
| Final recorded-state run | `recorded_state_verification_pass4a/20260613_232453` |
| Final recorded-state verifier exit | `1` |
| Final recorded-state critical failures | `3` |
| Final invalid state count | `7379` |
| Final invalid state rate | `0.780104` |
| Future feature leak count | `0` |
| MASA/PPO cutoff mismatch count | `0` |
| Position transition reject count | `0` |
| Training samples rejected count | `0` |
| Trades blocked by data quality | `0` |

Critical check IDs:

- `mtf_alignment.unfinished_higher_tf`
- `mtf_snapshot.missing`
- `replay_snapshot.missing`
- `runtime_trust.active_stale_missing_contract`

## Trainer health summary

| Field | Baseline | Final |
|---|---:|---:|
| Training loop active | `true` | `true` |
| Train rows | `3583` | `3583` |
| Validation rows | `894` | `894` |
| Row count | `330955` | `332178` |
| Replay rows loaded | `330685` | `331908` |
| Labels loaded | `41656` | `41894` |
| Trained model available | `true` | `true` |
| Minimum sample satisfied | `true` | `true` |
| Final training cycle | n/a | `2026-06-13T23:19:41Z` to `2026-06-13T23:20:15Z` |

Interpretation: the trainer loop is alive and repeatedly producing populated cycles. One transient empty cycle was observed at T+45, but later cycles recovered. The bigger blocker is not trainer liveness; it is trust-valid decision/evidence output.

## Training accepted/rejected rows

| Field | Value |
|---|---:|
| Final train rows | `3583` |
| Final validation rows | `894` |
| Final training samples rejected count from recorded-state verifier | `0` |
| NO_TRUSTED_TRAINING_ROWS observed | `not directly observed` |

## Prediction summary

| Field | Baseline | Final |
|---|---:|---:|
| Canonical predictions | `10` | `670` |
| Paper signals | `10` | `671` |
| Replay snapshots | `12` | `90757` |
| MTF snapshots | `12` | `13` |
| Shadow predictions | `50` | `50` |
| Final long predictions | n/a | `513` |
| Final short predictions | n/a | `74` |
| Final HOLD/no-trade predictions | `10` | `83` |

Interpretation: the bot moved from mostly HOLD/no-trade to active long/short prediction labels, but those records cannot be scored as trusted because strict verification fails.

## Prediction accuracy by horizon

Accuracy was not scored.

Reason: after actionable long/short records appeared, fresh strict verification failed and remained failed through T+240. Per Pass 4A rules, untrusted or strict-invalid predictions must not be counted as edge evidence.

## Signal conversion funnel

| Stage | Count / status |
|---|---:|
| Final canonical predictions | `670` |
| Final paper signals | `671` |
| Final paper intents | `1` |
| Final paper ledger keys | `1` |
| Trusted actionable decisions eligible for edge scoring | `0` |
| Closed trusted paper trades eligible for edge scoring | `0` |

## Symbol selection analysis

Observed symbols in verifier examples included `BANKUSDT`, `DASHUSDT`, `CELRUSDT`, `LINKUSDT`, `ADAUSDT`, and `STRKUSDT`, and the affected unfinished-higher-timeframe set covered 134 symbols.

Interpretation: symbol evaluation is active and broad, but trusted symbol-level accuracy cannot be scored while MTF and active risk evidence are invalid.

## Sizing / margin analysis

No live sizing path was activated during Pass 4A. No leverage mutation or margin-mode mutation occurred. The prior Pass 3C candidate sizing issue remains a future pre-canary blocker, but it was not exercised here.

## Strategy behavior

Observed strategy/risk evidence showed:

- `strategy_selected_mode=no_trade_mode` in exported risk examples.
- `strategy_allowed_actions=["hold"]` in several examples while `pre_trade_allowed=true` was also present.
- `strategy_router_block_reason` examples included `EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD` and `MASA_FUTURE_CUTOFF_BLOCK`.
- Runtime selected-action mix later became long-heavy, but strict trust invalidity prevents treating it as validated strategy output.

Interpretation: the system has active no-trade/risk gating and can produce long/short labels, but the active risk/evidence contract is inconsistent.

## Hedge behavior

No live hedge behavior was observed. No hedge transition, leverage mutation, margin mutation, or exchange state mutation occurred. The live canary state machine remained unactivated.

## MTF behavior

MTF behavior is the central blocker observed in this window:

- MTF snapshots barely changed: `12` to `13`.
- Replay snapshots grew dramatically: `12` to `90757`.
- Strict verifier repeatedly failed `mtf_alignment.unfinished_higher_tf`.
- Verifier examples showed higher-timeframe candles with `candle_closed_confirmed=false`, `closed_candle=false`, and `is_closed=false`.

Interpretation: the active prediction/replay path is not producing or linking valid closed-candle MTF evidence at runtime.

## Liquidity sweep analysis

Not scored.

Reason: actionable-looking long/short records appeared, but strict trust failed. Liquidity sweep behavior cannot be evaluated as strategy evidence until prediction/risk records are strict-valid.

## Edge / profitability assessment

No edge can be claimed.

| Field | Value |
|---|---:|
| Trusted actionable decisions eligible for edge scoring | `0` |
| Trusted closed paper trades eligible for edge scoring | `0` |
| Net expectancy after fees/slippage | `not available` |
| Profit factor | `not available` |
| Max drawdown | `not available` |
| Edge verdict | `not valid due strict trust failure` |

## $10k/month feasibility assessment

This observation does not support a $10k/month claim.

| Capital | Monthly return required for $10k/month |
|---:|---:|
| `$10,000` | `100%` |
| `$25,000` | `40%` |
| `$50,000` | `20%` |
| `$100,000` | `10%` |
| `$200,000` | `5%` |

Current blocker is not capital sizing. It is evidence validity and trusted edge measurement. Required evidence before scaling:

- strict verifier exit `0`
- recorded-state verifier exit `0`
- active risk/prediction records carry full v3 contract
- no unfinished higher-timeframe candles in MTF decision evidence
- enough trusted actionable paper/shadow decisions
- enough trusted closed paper trades
- positive expectancy after fees/slippage
- acceptable drawdown and profit factor

## Top 10 blockers

1. Strict verifier final exit `1`.
2. Active/pre-trade-like risk records missing v3 trust contract evidence.
3. Active risk records missing replay snapshot evidence.
4. Active risk records missing MTF snapshot evidence.
5. Unfinished higher-timeframe candles appear in MTF decision/evidence context.
6. Replay snapshots grew from `12` to `90757`, while MTF snapshots only grew from `12` to `13`.
7. Actionable-looking predictions cannot be scored because evidence is strict-invalid.
8. Recorded-state invalid state rate remained about `78%` after failures appeared.
9. Scalar PPO/trainer metrics were not reliably surfaced in the observed metrics key.
10. Liquidity sweep, MTF accuracy, and edge cannot be evaluated until trust evidence is valid.

## Top 10 recommended next fixes

These are proposed only. None were applied.

1. Identify the writer producing `v2:risk:decisions` with `pre_trade_allowed=true` but missing v3 contract fields.
2. Enforce deny/inactive state or full v3 contract for hold/no-trade risk records that otherwise look approval-like.
3. Fix MTF snapshot generation/linkage for the active prediction/risk path.
4. Ensure exporter patterns see the same MTF snapshot keys used by active decisions.
5. Fix closed-candle filtering so unfinished 5m/15m/1h/4h candles cannot enter decision/evidence context.
6. Add a regression test for active risk decisions missing replay/MTF fields.
7. Add a regression test for unfinished higher-timeframe candles in exported MTF evidence.
8. Add or repair runtime observability for scalar trainer metrics: loss, policy loss, value loss, entropy, KL, explained variance, reward trend.
9. Re-run Pass 2B edge proof only after strict and recorded-state verifiers return to zero critical failures.
10. Keep live canary blocked until trust-valid paper/shadow evidence exists again.

## Recommended code changes

Code changes are recommended after the observation window, but none were applied during Pass 4A.

Recommended change scope should be surgical:

- active risk decision writer/classifier
- MTF snapshot writer/linker/exporter
- closed higher-timeframe candle filter
- tests for the exact critical failures

No strategy, PPO, MASA, indicator, provider, live transport, leverage, or margin changes are recommended from this observation.

## Final verdict

`OBSERVATION_DATA_INVALID`

The system is learning/running enough to produce predictions, but the runtime evidence became strict-invalid during the observation. Live canary must remain blocked. The next pass should fix only the exact trust-invalid writer/classification/MTF closed-candle path, then rerun strict verification and Pass 2B edge proof.
