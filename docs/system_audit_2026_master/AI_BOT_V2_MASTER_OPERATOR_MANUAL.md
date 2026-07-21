# AI Bot V2 master operator manual

> **2026-07-18 UTC source/runtime reconciliation:** the paper materialization boundary uses final-admission v3, revocable rereads and same-cycle reservation. A controlled one-shot completed 597/0/597 in 69.85 seconds at 4.70 GiB peak RSS and zero swap; current/adaptive contracts were hashable, historical 132-row evidence remained honestly FAIL_CLOSED, and bracket security stayed blocked for non-account-specific credential binding. Guardian independently returned semantic BLOCKED in 3.57 seconds at ~35 MiB/zero swap, with 99,644 PIT-valid coverage observations but zero accepted economic holdout rows. Redis remained about 25.49 GiB under `allkeys-lru`/no AOF; its Guardian list (6,054,941 rows/~6.23 GB) and counterfactual string (536,827,021 bytes) both had TTL −1. Corrected archive/hot-cache/consumer source checks pass 87, but no real migration ran. Seven high-memory research/trainer/replay services are held and both trainer timers are stopped pending controlled migration/burn-in. The paper-shadow microstructure monitor's stdout was compacted from full 149-symbol rows to bounded scalar telemetry and measured at >99.8% lower byte rate; compressed rotation preserved about 14 GB of its history in ~876 MiB. The 10.9 GB supervisor event log kept growing because its poll-amplification source repair was not deployed. Four trainer units now preserve their complete quoted path-with-spaces `PYTHONPATH`. Current trainer source integrates strict clocks/economics, immutable no-expiry receipts, full cache identity, candidate/rejected/serving checkpoints, exact claim/WAL/ledger/crash recovery and uncertainty-qualified confidence promotion. Configured paper/shadow fee and reference-notional identity is hash-bound and rederived. It is still **TRAINER NOT READY** because no held integrated cycle or cost-producer deployment/burn-in has run, a scarce latest PPO row can remain validation-only, process-local lane state remains open, and static thresholds remain; actual exchange-account fee-tier/discount/maker-taker authority is separately unproved for live transfer. Current promotion evidence remains `HALTED_PERFORMANCE`, negative edge and G11/G12 FAIL. Runtime PPO supply is 0 admitted/0 consumed. The 75/50/20 plus five-ATR paper authority is source/test-bound but not runtime-bound. A+ has not been achieved; 1000x/90d is not guaranteed.

> **Security action:** a cloudflared credential was exposed by a diagnostic service inspection. Its value is intentionally absent here. Rotate/revoke it, audit any diagnostic-output propagation, and do not print tunnel command lines, `ExecStart`, or environment until protected credential handling is installed.

**Updated:** 2026-07-18 UTC (source/runtime reconciliation; historical body remains the 2026-07-16 audit)

**Audience:** operator/SRE/developer maintaining the audited workstation

**Default stance:** observe first, preserve state, fail closed, keep live trading disarmed.

This is the safe operating manual for the current system. It reflects the deployed workstation, not merely checked-in service files. Commands are run from `/home/wali/Desktop/AI BOT REBUILD` unless an absolute path is shown.

## 0. Current paper-admission operating contract

The following is the minimum evidence chain for a newly accepted paper fill. A missing link means the row is blocked or quarantined; it does not mean an operator should loosen a gate.

| Stage | Required evidence | Operator interpretation |
|---|---|---|
| Exact venue constraints | `paper_exchange_symbol_filter_snapshot_v1` from `v2:exchange:symbol_filters:<SYMBOL>`, producer `v2_direct_orderbook_recorder`, status `READY`, unexpired Redis TTL, raw source hash and final reread unchanged | Missing/stale/substituted filter metadata blocks quantization/admission. Initial BTCUSDT/ETHUSDT/SOLUSDT rows were observed, but one initial seed does not prove the 15-minute refresh cadence. |
| Open-book truth | `paper_precycle_current_mark_exposure_snapshot_v1`, status `READY`, `validated_open_position_count == ledger_open_position_count`, every source fill joined from `v2:paper:accepted_fills`, current mark timestamps/hash valid | A legacy/unsealed open position, missing source-fill proof, stale mark, duplicate/reused fill ID or unequal positive max-loss aliases blocks new entries. Do not delete or rewrite history to make this pass; let valid exits close legacy rows. |
| Premium-index mark/index | Canonical `v2:market:mark_price:<SYMBOL>` preferred over funding/prices fallback; positive mark/index; source `event_time`; producer `generated_at`/`available_at`; declared cadence; consumer observation and `CURRENT`; `REDIS_KEY_OUTER_SELECTED_PATH_PAYLOAD_AND_FIELD_MAP_SHA256_V2` | Redis TTL is not market freshness. Reject missing/naive/misordered clocks, stale source event, incomplete values or bad hash. Metadata/native cache reuse is bounded to source-event age <=120 seconds. The public `!markPrice@arr@1s` worker writes only V2 keys, TTL 180, exits after 600 messages for systemd reconnect/universe refresh and performs no REST/account/order/leverage/margin mutation. Its 149/149 one-message coverage and sampled current rows prove the producer, not paper-cycle consumption; keep new entries blocked when `mark_index_divergence` is missing. |
| Allocator market evidence | `allocator_market_evidence_status=READY`; `microstructure_trust_score_v2` identity/times valid; finite trust score and adaptive minimum `(0,1]`; action `ALLOW`/`REDUCE_SIZE`; positive authoritative liquidity; executable complete-pair correlation; nonblocked intent-owned regime | Upstream signal liquidity/regime/correlation is not authority. Missing/invalid adaptive minimum, trust or action; only depth or only spread; missing regime; protective/no-trade action/label; missing explicit candle finality/availability; a naive ISO candle/decision clock; or any unresolved pair against existing **or same-cycle accepted** symbols risk-vetoes. Confidence cannot rescue missing evidence. Child correlation evidence is `paper_correlation_accepted_source_material_v2` under `SOURCE_KEY_DECISION_TIME_ACCEPTED_CLOSE_AVAILABLE_FINALITY_AND_REJECT_COUNTS_CANONICAL_SHA256_V2`; the governing material is `paper_correlation_aggregate_source_material_v1` under `DECISION_CANDIDATE_OPEN_SYMBOLS_AND_SORTED_CHILD_SOURCE_MATERIAL_CANONICAL_SHA256_V1`. The only zero-correlation exceptions are no open positions or only the same symbol already open. The trust payload has no canonical `expires_at` and the consumer does not validate remaining Redis TTL, so READY is not complete A+ freshness proof. |
| Same-cycle capacity | `paper_cycle_reservation_snapshot_v1` and `paper_cycle_reservation_commit_v1`, both exact-hash replayable and `PASS`; allocation input/output lineage contains `paper_cycle_reservation_snapshot_hash` | The snapshot subtracts earlier accepted candidates from total/symbol notional, available margin and projected stop loss. The commit must match the exact accepted prefix immediately before append and pass total, symbol, buffer, per-candidate and projected-drawdown checks. |
| Mutable safety controls | `paper_revocable_control_commit_revalidation_v1`, `PASS`, identical at top level and inside the v3 bound material | Confirm exact unchanged guardian, freeze, portfolio, adaptive tuning, paper session, positions-or-ledger and closed-trade source hashes; current session equals the candidate session; tuning semantic validation passes at reread and commit clocks; guardian TTL is 1–180 seconds; current risk is unchanged; and the current process is the only canonical paper writer. `cross_process_atomic` must be `false` and `residual_toctou_risk` must be present—those fields are honest limitations, not warnings to suppress. |
| Final seal | `paper_final_admission_contract_v3`, `PASS`, valid receipt/bound-material/projection hashes; cycle and revocable receipts embedded; `paper_only=true`, `routes_to_live=false`, `places_real_order=false` | Earlier PASS fields are inputs, not final authority. A v2/missing/mutated/coherently resealed semantic mismatch is invalid. Persistence must replay the intrinsic cycle proof and the sealed row projection after later collapse/netting. |

Adaptive tuning has two deliberately separate keys:

- `v2:orchestrator:adaptive_gate_tuning_state` is owned by `v2.backend.app.cli.v2_adaptive_gate_tuner` and current source must be `v2_adaptive_gate_tuning_state_v4` with policy `v2_adaptive_gate_policy_v4`, publication receipt `v2_adaptive_gate_tuning_receipt_v1`, exact source/session hashes and an unexpired aware clock chain.
- `v2:diagnostic:adaptive_gate_tuning:runtime_tuner_shadow` is `v2_adaptive_gate_tuning_shadow_v1`, `authoritative=false`, and diagnostic only. It must never be copied into the canonical key or used to authorize admission.
- Fewer than 20 clean same-session outcomes is an integrity/evidence floor and yields a canonical fail-closed state. V4 also requires 20 finalized rows for each exact BTCUSDT/ETHUSDT/SOLUSDT 1m closed-candle key, strict `close <= event <= available <= cutoff`, and latest availability inside three 60-second cadences. It learns empirical q25/median/q75 and maps the current percentile into bounded factor 0.70–1.50. Missing/untrusted market evidence blocks combined authority. These bounds are not to be bypassed, and historical close rows without truthful `outcome_available_at` are not to be backfilled or fabricated.
- New close rows use `PAPER_CLOSE_OUTCOME_AVAILABILITY_V1`: economics first stamps `close_event_time` and `outcome_generated_at`; lifecycle stamps aware UTC `outcome_available_at` only after realization and before publication. A naive or impossible `close_event_time <= outcome_generated_at <= outcome_available_at` chain blocks publication and retains the position. Entry-feature `available_at` is separate.
- The paper consumer now emits `paper_adaptive_tuning_semantic_validation_v1` and must show `status=PASS`, an empty rejection list, a valid receipt hash, exact current-session identity and a consumer observation inside `available_at <= observed_at < expires_at`. Failure must appear as `ADAPTIVE_TUNING_AUTHORITY_NOT_VALID`; the fallback 0.80 floors are a non-authoritative fail-closed projection, not permission to trade.
- The historical v3 runtime was 0 admitted/92 rejected and fail-closed. At 04:41:09.475673Z the canonical key published v4 with 91/92 outcomes admitted, one lineage conflict, 100/100 final candles for each required symbol, NORMAL / factor 1.12666667 and `EVIDENCE_BACKED_RESTRICTIVE_NONPOSITIVE_EDGE`. This proves the producer receipt, not paper propagation: the paper reload failed and was held. Redis ACL/exclusive-writer enforcement and unchanged semantic receipt propagation remain proof items.

Treat `v2:paper:adaptive_sizing_runtime_status` and `paper_adaptive_sizing_runtime_status.json` as bounded operator context only:

- `candidate_allocations_complete` must be false; `candidate_allocations_projection_only` and `candidate_allocations_full_payload_omitted` must be true. No more than five `paper_adaptive_sizing_operator_projection_v1` rows should be present.
- Every full source row must still have an ordered `source_row_canonical_sha256`; verify `candidate_allocations_aggregate_sha256`, `paper_candidate_allocation_operator_hash_contract_v1` and `paper_candidate_canonical_aggregate_contract_v1`. All-candidate zero-liquidation, hedge, leverage, margin-mode and capital claims come from the validated aggregate, never from the five projections.
- OOS must classify projections as `operator_projection_context_only`; a projection must never be accepted as canonical pending/final evidence. The hashes detect producer-side mutation but are not signatures or independent attestation.
- Before repair the old artifact reached about 5.29 GB, process RSS about 6.7 GB and write volume about 161 GB. The first reload still produced 873,406,311 top-level bytes and 596/621 null hashes. The controlled command `/usr/bin/time -v timeout 300 .venv/bin/python -m v2.backend.app.cli.v2_trade_management_paper_loop --once --out /tmp/ai_bot_paper_status_probe_20260718_0125.json` exited 0 in 69.85 seconds at 4,925,812 KB peak RSS and zero swap. It built 597 intents, blocked all 597, accepted none, wrote 551 keys and reported process/resource classification `PRODUCTION_OK`; this is not trading promotion. Temp/canonical artifacts were 5,017,701/4,160,870 bytes with no non-finite tokens. Adaptive was 622 sources/five projections/all hashable/Guardian-valid; current was zero-source/PASS; persistent was 132 sources/five projections/132 unhashable/FAIL_CLOSED. Exploration was ACTIVE, `NO_TRADE=597`, `SHADOW_ONLY=214`, all blocked. Do not erase or normalize the legacy rows. The service remains held; require repeated resident RSS/write/restart evidence before closure.

Treat host-resource containment as a hard operating gate:

- Redis was observed at about 25.49 GiB under a 32 GiB `allkeys-lru` cap with AOF disabled. `v2:guardian:pit_prediction_observations` was a TTL −1 list with 6,054,941 rows using 6,230,529,272 bytes; `v2:trainer:feedback:counterfactuals` was a TTL −1 string of 536,827,021 bytes. These runtime objects remain unbounded and unchanged. Current source gives them durable SQLite/bounded-hot contracts, but source tests are not an executed migration.
- Keep these exact seven services inactive/dead under `RefuseManualStart=yes` repair drop-ins: `ai-bot-v2-adaptive-capital-productivity`, `ai-bot-v2-continuous-edge-guardian`, `ai-bot-v2-edge-replay-factory`, `ai-bot-v2-native-cuda-trainer-persistent`, `ai-bot-v2-continuous-offline-gpu-trainer`, `ai-bot-v2-trainer-scheduled-pretrain` and `ai-bot-v2-native-ppo-masa-continuous-training-guard`. Keep the scheduled-pretrain and continuous-guard timers stopped. A self-healer previously restarted stopped units. No live unit was changed.
- The controlled Guardian one-shot used `--no-redis`, semantically exited 2/BLOCKED in 3.57 seconds at 35,896 KB peak RSS/zero swap, passed anti-metric-gaming and canonical aggregate validation, but retained `A_GRADE_HALTED_PERFORMANCE`. New A-grade entries remained blocked, only reduce/close/emergency de-risk was allowed, all 26 leverage recommendations were 1x, and 99,644 PIT-valid coverage observations admitted zero economic holdout rows. This is bounded process evidence, not resident health/A-grade proof.
- The streamed counterfactual probe handled 4,592,832 feasible configurations in 3:08.82 at ~1.65 GiB peak RSS/zero swap and exited 2 for the expected semantic `NO_GO` (missing OOS live-grade reverify). Do not reinterpret exit 2 as an OOM or reinterpret bounded execution as 1000x/A+ evidence.
- The paper-shadow `ai-bot-v2-microstructure-feed-quality-monitor.service` formerly printed the complete per-symbol payload every loop: 679,324 bytes in 4.62 seconds, approximately 12 GB/day. At diagnosis its active/rotated history totaled about 14 GB. Current source defaults `--loop-log-mode compact`; the deployed unit makes that mode explicit at a two-second interval. The compact `v2_microstructure_feed_quality_monitor_loop_log_v1` row contains only scalar/count telemetry and safety flags; the full authoritative 149-symbol rows remain in Redis and status artifacts.
- Thirteen focused monitor CLI tests passed. Restart authority covered this paper-shadow/no-order monitor only: PID 364367 was active, and a post-fix sample added 949 bytes in 4.95 seconds with a 149-symbol scalar summary, more than 99.8% below the prior byte rate. The worker declares no real/test order, cancel/modify, leverage, margin-mode, transfer or withdrawal mutation. This is a bounded write-rate sample, not A+ or trading promotion.
- `tools/native_cuda_trainer_logrotate.conf` now covers the persistent trainer, offline trainer, native PPO/MASA guard and microstructure monitor streams with `size 256M`, `rotate 4`, `copytruncate`, `compress`, `missingok`, `notifempty` and `nodateext`. `ai-bot-v2-trainer-logrotate.timer` checks it every ten minutes and is persistent. The 7.2 GB active monitor log compressed to about 367 MiB; the prior 6.8 GB archive was gzip-preserved at about 323 MiB; with the earlier 187 MiB archive and current ~28 KiB file, retained monitor history was about 876 MiB, a >93% disk reduction without evidence deletion.
- Do not switch a resident monitor to `--loop-log-mode full`; it is an explicit diagnostic escape hatch that recreates the amplification risk. `silent` suppresses stdout but does not replace validation of Redis/status publication. Rotation uses `copytruncate`, so validate writer continuity and archives after every config change. The 10.9 GB `agent_supervisor/events.jsonl` is intentionally untouched. Its stable poll observations added about 112 KB/10 seconds (~0.9 GiB/day). Source now keeps those observations only as bounded queue-status counts/sample, but that producer was not restarted/deployed; do not claim disk relief until measured after deployment.
- Workspace settings exclude `*.jsonl` and `claude_worklog` from file watching/search, and the exception that forcibly re-included generic `*.json` search was removed. This reduces extension indexing pressure only; it changes no runtime data and must not hide canonical artifacts from deliberate operator checks.
- Do not delete large logs, Redis keys or orphan temporary files blindly. Preserve active-writer detection and canonical-history provenance; implement versioned retention/rotation/quarantine before removing the holds.
- The original 62-test retention draft was rejected for Guardian retry loss and cost-blind counterfactual labels. Corrected source now passes 87 combined cases, including 18 focused consumer cases: a transactional SQLite outbox retries Guardian hot delivery; bounded legacy migration precedes trim; counterfactual labels carry explicit costs and immutable rewrite detection; and the Guardian consumer verifies publisher identity, content/semantic/archive hashes, strict UTC PIT/finality, dirty quarantine, fsynced sink replay and a complete cursor+migration+outbox trim gate. This source is accepted for controlled migration review, not automatic execution. Do not trim either TTL −1 object until before-state capture, writer quiescence/fencing, archive/cursor/sink count+chain closure, rollback and repeated resource observation are recorded.
- Guardian consumer defaults are source archive `.local_data/v2_guardian/pit_prediction_observations.sqlite3`, derived coverage `guardian_pit_predictions_append_only.jsonl`, and `--archive-consumer-batch-rows 10000`. Its status must be `DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_COMPLETE_VERIFIED`, `archive_consumer_caught_up_verified=true` and `redis_hot_cache_trim_safe=true`; also require `publisher_legacy_migration_complete=true`, migration cursor at least observed length, pending delivery count zero, exact source/consumer chain equality, and revalidated absolute sink path/count/chain. A quarantined row is preserved rejected evidence, not coverage. Any `BLOCKED_*`, sink change/tamper, malformed non-wrapper, chain mismatch or outbox/migration debt means no trim.

Treat `v2:paper:portfolio_cascade_guard` as diagnostic protection, not proof that cross margin is enabled:

- `portfolio_margin_evidence.schema_version` must be `paper_cascade_margin_join_v1` and status PASS before `portfolio_level_computed=true` is meaningful. Every open symbol must join exactly one valid `paper_account_margin_status.position_margin_rows` row with positive canonical notional/rate and `effective_leverage >= 1`.
- On missing, duplicate or invalid evidence require `portfolio_level_computed=false` and `risk_state=UNTRUSTED_MARGIN_EVIDENCE`. Do not infer safety from an empty positions list produced by alias mismatch.
- `cross_margin_liquidation_v2` accepts audited exchange/paper quantity, mark and leverage aliases and reports `leverage_evidence_complete` plus missing symbols. It mutates nothing. Allocations remain `isolated_paper_simulated`.
- Its BTC shock table (−5%, −10%, −20%, +10%) and beta table (BTC 1.0, ETH 1.15, SOL 1.35, other 1.6) are fixed approximations. Do not describe the result as exchange-exact or fully adaptive account-wide liquidation authority.
- A 04:40:17.785Z component receipt was PASS with 2/2 joined, maintenance margin $0.55807547, complete maintenance/leverage evidence, no directives and no modeled breach. This is one component snapshot; the held paper loop did not consume it in a completed cycle.

Treat PPO on-policy supply as a verified zero-row runtime blocker whose source repair still needs deployment and burn-in:

- Current 92-row closed evidence has 2 rows with `ppo_on_policy_entry_fields_present=true`, 42 false and 48 absent; only 2 have `old_log_prob`, and all 92 lack the required sampling-mode/distribution fields. Trainer `_has_on_policy_ppo_fields` admits 0. Current metrics are `ppo_on_policy_rows=0`, `ppo_rows_consumed=0`, `ppo_rows_missing_on_policy_fields=2014`, `ppo_rejected_missing_on_policy_fields=2014`, `ppo_objective_used=false`, and `ppo_clipped_surrogate_rows=0`. Genuine PPO is not training in this evidence window; outcome-supervised metrics separately report 2,014 rows, 1,609 batch rows and `outcome_supervised_update_used=true`.
- The historical runtime predicate expected authoritative `CATEGORICAL_SAMPLE` under `RAW_LOGITS_SOFTMAX_V1`; the current undeployed repair intentionally uses the stricter `POSITIVE_EDGE_MASKED_RAW_LOGITS_SOFTMAX_V1` contract. Do not mix the two when reading old evidence. The current source receipt schema is `v2_positive_edge_on_policy_behavior_receipt_v1`, with action source `NATIVE_CUDA_POLICY_CATEGORICAL_SAMPLE` and mask source `PIT_AFTER_COST_POSITIVE_ENTRY_ACTION_MASK_V1`.
- The adaptive lane schema `v2_adaptive_on_policy_paper_lane_plan_v1` accepts only final `TRAINABLE` rows with `candle_close <= feature_cutoff <= available_at < decision_time` and separately `candle_close < decision_time`. Require symbol/timeframe, exact served-policy fingerprint, real checkpoint ID, 64-hex checkpoint weight/evidence digests, fitted directional profitability confidence, valid raw logits, strictly positive after-cost LONG or SHORT edge, explicit free margin, clear paper-only entry freeze and `exact_cost_provenance_valid=true`. Its candidate credit remains evidence-derived; no fixed exploration fraction or market minimum `N` is permitted.
- Inspect `v2_exact_adaptive_cost_provenance_v1`, not just the scalar cost. It must bind the exact `v2:costs:round_trip_bps:<SYMBOL>` payload and nested `v2:orderbook:features:binance:<SYMBOL>` payload/hash/schema/symbol/sequence/clocks, adaptive median-plus-MAD expiry, TTL and consumer observation. Recompute nested spread, impact/depth and `2*taker_fee_bps_per_side + spread_bps + 2*impact_per_side_bps`; require `FRESH_ORDERBOOK`, no conservative floor and no fallback. Current source additionally hashes and rederives `paper_cost_fee_schedule_evidence_v1` (`CONFIGURED_TAKER_FEE_BPS_PER_SIDE`, value and source) and `paper_cost_notional_configuration_evidence_v1` (reference notional and source). That is sufficient identity for configured paper/shadow economics; it does not prove the actual exchange account's fee tier, discounts or maker-versus-taker applicability and therefore cannot support a live-transfer claim. The deployed BTC cost row observed on 2026-07-18 was old schema—adaptive clocks/provenance were null—so it is invalid for the exact lane. Restart/deploy review must include the cost producer, then wait for four distinct source clocks (three intervals) before expecting proof.
- For a selected candidate the mask retains HOLD and only profitable-after-cost entry directions. Masked softmax plus a cryptographic 53-bit uniform draw determines the action; no strategy action may replace it. Require the receipt self-hash to bind checkpoint ID, exact served-parameter fingerprint, mandatory checkpoint-weight and evidence digests, symbol/timeframe, feature tensor/vector, strict clocks/finality, plan, raw/masked distributions, action/probability/log-probability, policy value and the complete cost envelope. It is paper-learning-only, does not count as A+ evidence and cannot route live.
- Before treating a row as routeable, require immutable Redis key `v2:trainer:hybrid_cuda:on_policy_receipt:<receipt_hash>`, `behavior_policy_receipt_write_success=true`, exact hash/key bindings and every `BEHAVIOR_POLICY_LINEAGE_FIELDS` value across prediction→orchestrator→risk→fill→position→outcome→feedback. Current source writes exact receipts with `ex=None`: proof has no fixed seven-day expiry and an identical retry must not mutate it. Strategy-supply rows must have exact-policy proof stripped; a sampled, corrupt or previously consumed receipt must never fall back to outcome supervision.
- Also require the independent local archive proof. Schema `v2_durable_behavior_receipt_archive_v1` lives under `.local_data/v2_native_trainer/durable_behavior_receipt_archive`; publisher must fsync/read-back the content-addressed create-or-identical blob and append `PUBLISHED` before the Redis write can make an exact row eligible. Paper entry must reverify the blob, archive SHA, `PUBLISHED` event and configured fee identity before appending `ENTRY_ACCEPTED`; feedback must reverify `ENTRY_ACCEPTED` and append `OUTCOME_FINALIZED`. Any missing, conflicting or corrupt proof blocks exact PPO identity; an already sampled/corrupt receipt must not be relabeled as supervised merely to preserve supply.
- `receipt_lifecycle_status` must remain `retention_required=true` until `TRAINER_CONSUMED` binds the same `ppo_consumption_update_key`. Current source defines that event but does not append it after `v2_exact_ppo_consumption_ledger_v3` disposition. Do not delete archive blobs. There is currently no archive GC, capacity bound, keyed authentication, backup or restore proof; monitor `.local_data` growth during burn-in.
- Do not configure a fixed exploration fraction or fixed minimum `N` just to raise the counter. The implemented source derives supply from current evidence as above and preserves all downstream risk, margin, paper and final-admission gates. The exact-receipt repair passed 73 combined trainer/confidence/regularization tests, 16 receipt tests (including a real clipped optimizer delta and entry→position→close→feedback), five selected strategy/non-leak paper tests, eight mode-collapse tests and the full 54-case strategy-router file; compile/format/lint/diff checks passed. Controlled service burn-in and runtime nonzero supply remain pending; these green source tests do not supersede observed 0/0 or authorize release.
- Latest read-only handoff from the still-running old generation: predictions 745/failures 0, outcome-supervised rows 2,014, PPO admitted/consumed/clipped 0/0/0, objective false, validation edge −1.39286013 bps/LCB −2.25532918 bps and composed gate HALTED. Margin was PASS; MANA/ARB were 2x. The literal Redis reads were not root-reproduced. Treat this as negative deployment evidence: do not infer that source repair, PPO learning or profitable adaptive leverage is active.

Treat trainer profitability confidence as checkpoint-bound, action-conditioned evidence:

- For selected LONG/SHORT, current label semantics are `P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2`. Recompute gross from selected action/side, entry price, exit price and closed quantity; then recompute net exactly as `gross - entry_fee - exit_fee - entry_slippage - exit_slippage + signed_funding`. Require `PAPER_ROUND_TRIP_CLOSE_COST_V1`, `PAPER_ENTRY_COST_BASIS_V1`, exact rate scope/formula, entry/exit notionals, pro-rata partial-close quantities/fraction/final-close remainder, every component/source, complete provenance, fallback=false and exit-cost availability between decision and close. Claimed gross/net/bps/profitable/outcome fields are only equality checks. HOLD and CPU fallback remain zero/unfitted.
- Require per-direction head schema/order, label-purged training-only calibration, `validation_rows_used=0`, explicit final outcome time strictly after decision, row digest and exact final model-parameter fingerprint in the same NPZ/manifest. Missing fingerprint must load unfitted; any weight change must invalidate calibration.
- Require calibration schema `v2_profitability_confidence_calibration_v2`; every V1 calibration state must load unfitted. Reject legacy scalar-head checkpoints atomically. Do not use the external/global temperature file: its compatibility CLI must return `BLOCKED_EXTERNAL_CALIBRATION_BYPASS_DEPRECATED` without state mutation.
- Close outcomes, feedback enrichment and trainer loading now preserve unit-explicit `realized_gross_pnl_usd`, `closed_entry_notional_usd`, `fees_usd`, `slippage_usd` and signed `funding_pnl_usd`; focused lifecycle proof passed. Require those exact fields and never convert ambiguous legacy aliases by assumption. Until a controlled held-service cycle reports nonzero eligible V2 targets and both-action fit, treat runtime confidence-target supply as unproved.
- Require `v2_checkpoint_bound_confidence_promotion_gate_v1` before serving review. It must rederive its own fit/validation digest separation, fingerprint binding, zero validation-fit rows, global/LONG/SHORT row counts and same-row raw-versus-calibrated Brier/ECE. It must also reproduce paired Brier deltas, mean, standard error and one-standard-error upper bound plus ECE leave-one-out deltas, jackknife standard error and upper bound for all three scopes. Each upper bound must be nonpositive; there is no configured market sample minimum, but at least two rows per scope are mathematically required to identify uncertainty. This is a necessary gate only. No compatible checkpoint was trained/promoted/served by held services, so do not report runtime calibration quality or A+ confidence.

Treat Ridge/model-edge recovery as fail-closed research, not performance evidence:

- The current v2 Ridge challenger is paper-only B-grade, cannot fill, cannot promote A+ or route live, and writes no checkpoint. Its 16 focused tests cover durable hashes, finality/latest-unclosed proof, PIT clocks, explicit action-specific costs and purged holdout boundaries.
- The real 200-snapshot probe completed in 0.19 seconds at 29,208 KB RSS and produced 0 evaluable rows. Exact rejections were missing/invalid fee 145, missing/invalid slippage 145 and latest-unclosed exclusion unproven 55; the four-hour purge left train/validation/holdout 0/0/0. Do not report a model, edge improvement or “+30 bps,” and do not synthesize static costs or edit historical snapshots to make the counter rise.

Treat the 75x/50x/20x per-symbol leverage handoff as operator-approved paper authority whose source binding is tested and runtime binding remains under audit:

- Preserve `symbol_leverage_ceiling`: BTC/ETH 75, SOL/LTC/XRP 50 and other 20 ceilings, plus the default five-ATR liquidation rule. The paper dynamic envelope retains a 3x base, continuously earns toward the authorized ceiling only from favorable realized/PIT evidence and contracts under adverse/missing evidence. Candidate leverage is `min(Phase-8 recommendation, continuous target inside dynamic/symbol cap)`; recommendation violations fail to 1x.
- The authenticated bracket path generates every integer leverage from 1 through `floor(min(signed bracket max_initial_leverage, authorized symbol ceiling))`. Never grant leverage from symbol class alone. Require valid account/environment/symbol binding at exact post-fill notional plus PIT edge/volatility/liquidity/slippage/correlation/cascade/liquidation/drawdown/free-margin/concentration constraints.
- The controlled 597-intent run reported `BLOCKED:CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC`; no leverage was runtime-bound and no leverage/margin/order mutation occurred. Account margin still passed: equity/wallet $2,985.59472051, used $55.80754736, free $2,929.78717315, adaptive buffer $499.52893144, post-buffer free $2,430.25824171, 2/2 open positions accounted and zero newly reserved margin. Historical 2x positions prove only that the book was not pinned to 1x. Preserve `gross_notional ~= allocated_margin * effective_leverage`; do not enable cross margin or mutate live leverage.

The single-writer assumption is mandatory. Prefix comparison and exact rereads protect a sequential in-process append, but there is no Redis fencing token, multi-key CAS or durable reservation journal. If ownership shows more than one canonical writer, keep new entries blocked, preserve evidence and reconcile deployment; do not “fix” it by clearing keys.

Promotion truth remains adverse: `HALTED_PERFORMANCE`; LCB −47.0423 bps; PF 0.703666; weighted expectancy −7.70099 bps; win rate 0.43478. Tuner v4 and cascade join have component receipts; WSS covered 149/149. The controlled paper/Guardian one-shots were bounded and zero-swap, but they were not repeated resident-service burn-in; persistent history remains FAIL_CLOSED, seven research/trainer/replay services remain held, both trainer timers are stopped and Redis/host pressure remains. Bracket credential binding is blocked, so the approved leverage source did not bind runtime leverage. Ridge has zero trusted rows. Exact on-policy and corrected retention source lanes are green, but trainer adversarial blockers, runtime deployment/migration and burn-in remain. G11/G12 fail; no compatible calibrated checkpoint or A+ chain exists. Live remains disabled.

Current source regression evidence is green: 533/533 paper-loop (prior checkpoints 530 and 526), 331 trainer/PIT, 480 lifecycle/paper-trade-management, 207 allocator, 16 adaptive-tuning (prior checkpoint 15), 72 recorder/integration, 92 orchestrator/risk, 99 preemptive/A+, and 77 portfolio/microstructure tests. Compact-status dependents passed 91/91 OOS and 33/33 Guardian; post-fix preemptive-edge-control passed 77/77; margin/cascade passed 13/13; compact monitor logging passed 13 focused CLI tests. The final allocator + adaptive-productivity + Phase-8 suite passed 323/323; authenticated-bracket selection passed six cases with 531 deselected. Strict Ridge passed 16 focused tests; historical confidence passed 35 focused plus 66 adjacent and one refusal. Exact on-policy source checks passed 73 combined, 16 receipt, five selected paper, eight collapse and 54 full-router cases plus static checks. Confidence V2 passed 12 calibration/proportional plus 15 selected strict-economics cases; its concurrent checkpoint/confidence aggregate remained 36/39 pending integration. Retention's initial 62-test draft was rejected; the corrected combined set passes 87 with 18 focused consumer cases. Counts overlap. Source tests and bounded one-shots do not close trainer readiness, V2 confidence-row supply, held-service stability, an executed Redis migration, historical non-finite evidence, all-symbol candidate-time WSS coverage, compatible checkpoint/on-policy burn-in, account credential/bracket binding, G11/G12, deployed A+, negative edge or fixed-threshold debt.

The correct operator response is to retain the halt and repair evidence/account binding—not increase leverage, synthesize credentials, reinterpret warnings as PASS, delete legacy rows, or weaken fixed safety/PIT boundaries in the name of adaptivity.

## 1. Non-negotiable safety rules

1. **Do not enable, arm or test real order submission from this manual.** Real Binance order transport exists even though no authorized submitter was active at audit time.
2. **Do not edit exchange-touching, order, cancellation, modification, strategy, PPO, MASA or risk logic without explicit operator approval.**
3. **Do not repair/reload/start the failed orderbook replay rollover without approval.** Its enabled persistent timer already retries every six hours. Repairing the broken service path would let the next scheduled trigger apply a conflicting 100 GiB deletion policy to a replay tree observed between roughly 247 and 259 GiB during this audit.
4. **Do not run the full backend integration suite against the current workspace/Redis.** Tests have previously overwritten real paper state and destroyed closed-trade history.
5. **Do not treat a process, heartbeat, status JSON, dashboard, risk ID or “accepted” counter as proof of success.** Verify the authoritative contract and lineage.
6. **Do not use unfinished candles or a feature whose `available_at` is later than `decision_time`.** Preserve each timestamp’s meaning.
7. **Do not put passwords, API keys, cookies, bearer tokens, private URLs or raw environment values in commands, tickets, docs or chat.** No approved credential-retrieval mechanism or named security owner was proven at audit time. Do not retrieve credentials until the authorized human operator/security owner establishes a protected mechanism and a non-secret procedure reference.
8. **Do not repair/restart multiple services at once.** Capture before-state, change one authority, observe a full cycle, and retain rollback evidence.
9. **Do not assume Git describes deployment.** Effective user-systemd units/drop-ins run from mutable repo state and diverge from versioned files.
10. **Do not add manual deletion or change/pause/disable/mask retention without approval and a before-state capture.** A separate enabled 15-minute janitor is already non-dry-run and mutates replay/cache/log/temporary holdout artifacts; evidence preservation is racing that automation until authorities and protected datasets are reconciled.

## 2. What is running

The earlier 2026-07-16 operations snapshot found 157 installed `ai-bot*` user-unit files, 81 running services, 36 active timers and 3 failed services. A direct recheck found 156 installed basenames and 35 active timers. Counts change continuously.

> **Post-cut update (2026-07-16, evening):** re-measured **159** installed units, **84** running services, **36** active timers, **2** failed (`ai-bot-v2-autonomous-no-manual-next-task-policy`, `ai-bot-v2-closed-candle-replay-evidence`). Operational hardening this session: `out-of-sample-evidence-producer` **removed** (OOM-restart loop), `adaptive-capital-productivity` **memory-capped** (`MemoryHigh=6G`/`MemoryMax=8G`, was uncapped/leaking to ~15.5 GiB), `paper-equity-reconciliation-loop` set **`StandardOutput=null`** (had flooded syslog to ~35 GiB). Operator-pending: `tools/OPERATOR_crash_hardening_sudo.sh` (syslog truncate + journald cap, needs sudo), `tools/fix_cursor_state_bloat.sh` (Cursor `state.vscdb` reclaim, run with Cursor closed). See MASTER_SYSTEM_DOC.md → Post-cut reconciliation. LIVE remains BLOCKED.

Functional flow:

```text
provider/exchange readers
  → Redis market/provider keys
  → feature/TA/context/snapshot workers
  → persistent/offline trainers and publishers
  → all-timeframe publisher
  → orchestrator
  → risk records + paper signals
  → paper trade-management/lifecycle/accounting
  → portfolio/guardian/outcomes/replay
  → API/public artifacts/web/mobile
```

Automation supervisors, watchdogs, retention and report publishers operate around that flow. Two trainer authorities and two portfolio publishers were active. Backend ran four Uvicorn workers from the mutable repository on loopback port 8000. Vite preview served ignored `dist` on all interfaces at port 5173.

## 3. Operator truth hierarchy

Use the narrowest primary truth for the question:

| Question | Check first | Confirm with |
|---|---|---|
| Is a worker running? | `systemctl --user show` effective unit/PID/result | sanitized process identity and worker-specific heartbeat |
| Is data fresh? | producer payload’s event/available/generated/cutoff fields | TTL and upstream heartbeat |
| Did a prediction publish durably? | prediction payload plus replay/archive write evidence | lineage and archive/blob existence; publisher return handling is currently defective |
| Did risk allow? | matched risk record action | ID, decision/prediction hash and time; ID existence is not allow |
| Is a paper fill valid? | lifecycle/ledger record after invariant checks | admission path, risk action, position transition, accounting and execution time |
| Is the trainer learning? | accepted rows, optimizer/weight delta and checkpoint load evidence | rejection reasons and clean holdout exclusion |
| Is UI accurate? | primary Redis/file contract | public artifact age and client decode |
| Is live safe? | effective release/live/armed/transport state and active callers | live-readiness gates; never infer from one flag |

## 4. Start-of-shift snapshot

Run read-only checks and save the output in an operator-controlled incident/worklog location with secrets redacted.

### 4.1 Repository provenance

```bash
date --iso-8601=seconds
git rev-parse HEAD
git status --short --untracked-files=all
git log -5 --oneline --decorate
```

Interpretation:

- A dirty worktree is expected in this active workspace. Do not discard or overwrite changes you do not own.
- Git HEAD can advance while auditing. Record start/end commits and start/end
  content fingerprints for every in-scope mutable artifact; commit equality alone
  does not prove stable dirty-worktree bytes.
- Git status records path state, not file content. Preserve owned/concurrent diff
  provenance separately without copying secret values.
- Ignored runtime/model/frontend-build/effective-deployment files are not shown by
  ordinary Git status. Record their sizes and SHA-256 values in a secret-safe
  bundle manifest together with canonical docs, atlas, units/drop-ins, dist and
  checkpoints. No complete global bundle manifest was proven at audit time.

### 4.2 Installed/running systemd state

```bash
systemctl --user list-unit-files 'ai-bot*' --no-pager
systemctl --user list-units 'ai-bot*' --type=service --all --no-pager
systemctl --user list-timers 'ai-bot*' --all --no-pager
systemctl --user --failed --no-pager
```

For one service:

```bash
systemctl --user show SERVICE.service \
  -p Id -p LoadState -p ActiveState -p SubState -p Result \
  -p MainPID -p NRestarts -p FragmentPath -p DropInPaths \
  -p WorkingDirectory -p ExecStart --no-pager
```

Do not paste effective `Environment` or an unredacted process command into a report; credentials can be embedded in arguments.

### 4.3 Listener and HTTP liveness

Inspect listeners first:

```bash
ss -ltnp
```

Run each HTTP check separately so its captured output remains one valid JSON
document. Backend process liveness:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/health | \
  python3 -c 'import json,sys; p=json.load(sys.stdin); print(json.dumps(p, indent=2, sort_keys=True)); sys.exit(0 if p.get("status") == "ok" else "ERROR: backend health is not ok")'
```

Redis-backed backend health:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/api/v2/system/health | \
  python3 -c 'import json,sys; p=json.load(sys.stdin); print(json.dumps(p, indent=2, sort_keys=True)); sys.exit(0 if p.get("data", {}).get("redis_available") is True else "ERROR: backend answered but Redis is unavailable")'
```

Frontend listener:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:5173/ >/dev/null
```

`/health` proves only that the FastAPI process answered with its expected status.
`/api/v2/system/health` itself returns HTTP 200 in degraded mode, so `curl
--fail` alone is insufficient; the parser above exits nonzero unless
`data.redis_available` is exactly true. Neither check proves providers, trainer,
paper lifecycle or public tunnel routing.

### 4.4 Redis capacity and persistence

These commands do not dump values:

```bash
redis-cli --no-auth-warning PING
redis-cli --no-auth-warning DBSIZE
redis-cli --no-auth-warning INFO memory | \
  rg '^(used_memory_human|maxmemory_human|maxmemory_policy|used_memory_rss_human|used_memory_peak_human):'
redis-cli --no-auth-warning INFO persistence | \
  rg '^(rdb_last_bgsave_status|rdb_last_bgsave_time_sec|rdb_changes_since_last_save|aof_enabled):'
redis-cli --no-auth-warning INFO stats | \
  rg '^(evicted_keys|expired_keys|keyspace_hits|keyspace_misses|rejected_connections):'
```

Escalate if:

- `used_memory` approaches the 32 GiB cap;
- `evicted_keys` increases;
- RDB background save fails;
- changes-since-save remains large;
- RSS or swap pressure threatens the host.

Because policy is `allkeys-lru`, critical keys have no protected namespace. Do not respond by deleting keys ad hoc.

### 4.5 Disk state

```bash
df -hT /
du -sh v2/runtime .local_models claude_worklog goal_state legacy_reference raw_evidence logs 2>/dev/null
```

Do not start rollover or run cleanup from pressure alone. Capture the largest consumers, protected replay/evidence/model sets, active writers and both retention policies first.

At the read-only `2026-07-16T08:32:41Z` observation, both
`ai-bot-v2-orderbook-replay-rollover.timer` and
`ai-bot-v2-disk-retention-janitor.timer` were loaded, enabled, active and
persistent. The former last triggered at `03:06:24 EDT` and was next scheduled
for `09:06:24 EDT`; the latter last triggered at `04:27:21 EDT` and was next
scheduled for `04:42:21 EDT`. Refresh those values before acting:

```bash
systemctl --user list-timers \
  ai-bot-v2-orderbook-replay-rollover.timer \
  ai-bot-v2-disk-retention-janitor.timer --all --no-pager
systemctl --user cat \
  ai-bot-v2-orderbook-replay-rollover.timer \
  ai-bot-v2-orderbook-replay-rollover.service \
  ai-bot-v2-disk-retention-janitor.timer \
  ai-bot-v2-disk-retention-janitor.service --no-pager
```

The effective 15-minute service invokes
`claude_worklog/tools/v2_disk_retention_janitor.py` without `--dry-run`. That
script deletes replay day directories older than five days or beyond its 300 GiB
and free-space policies, tail-replaces oversized JSONL, truncates oversized `.out`
logs, and deletes `/tmp/holdout_tail_*` older than six hours
(`claude_worklog/tools/v2_disk_retention_janitor.py:31-62`, `:99-173`,
`:176-255`). Its status at `2026-07-16T08:27:21.352199+00:00` reported
`dry_run=false`, ten temporary holdout files deleted and 89,478 bytes reclaimed;
no replay directory, JSONL tail or `.out` log was changed in that particular
cycle. Mutation during the audit is therefore observed, not hypothetical.

> **Post-cut update (2026-07-16, evening):** the rollover/janitor conflict is
> **unchanged** — `ai-bot-v2-orderbook-replay-rollover.timer` remains enabled/active
> and the 15-minute janitor still runs without `--dry-run`. Repairing the rollover
> would let its timer invoke the harsher policy, so it stays an operator decision, not
> an automatic repair. Separately, `tools/OPERATOR_crash_hardening_sudo.sh` (needs sudo)
> truncates the 35 GiB `/var/log/syslog` flood and caps journald so a runaway service
> can no longer fill the disk; it is pending operator execution.

### 4.6 Live-readiness observation

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/api/v2/live-readiness | python3 -m json.tool
```

This is observation only. At audit time zero of eight gates passed. Never use the endpoint as an activation command or as proof that dormant live callers are absent.

## 5. Service-family checks

Service names may drift. Resolve the effective unit before relying on an example.

### 5.1 Market/provider ingestion

Check:

- unit active/result/restarts;
- producer heartbeat generated time;
- representative key TTL and payload timestamps;
- upstream connectivity/rate-limit state;
- symbol/timeframe coverage;
- final-candle and availability fields;
- error-rate/log growth.

Do not label a provider healthy merely because a credential name is present. Do not print credential values.

For a key, prefer metadata over content:

```bash
redis-cli --no-auth-warning TYPE 'v2:KEY'
redis-cli --no-auth-warning TTL 'v2:KEY'
redis-cli --no-auth-warning MEMORY USAGE 'v2:KEY'
```

When payload inspection is necessary, select only non-secret fields with a local parser. Never dump an entire provider/auth/order payload into a shared log.

### 5.2 Feature pipeline

Primary entrypoint: `v2.backend.app.cli.v2_feature_pipeline_native_loop`.

For a representative symbol/timeframe verify:

1. the newest candle is explicitly closed;
2. candle close is not later than `model_decision_time`;
3. every contributing source `available_at` is not later than `model_decision_time`;
4. snapshot `feature_cutoff` describes the newest information used;
5. MASA `feature_cutoff` is not later than the PPO `model_decision_time`;
6. per-source enrichment lineage exists;
7. missing/stale masks match data;
8. latest and archive writes succeeded;
9. snapshot age is within timeframe policy.

Current limitation: enrichment sources merged by `_merge_a_plus_context_features` and `_merge_external_v2_features` do not all carry a checked per-source temporal envelope. A green `feature_freshness_state` proves the core closed OHLCV state, not every merged field.

Use the exact stage fields throughout prediction, risk and paper investigation:

```text
each source available_at <= model_decision_time
MASA feature_cutoff <= PPO model_decision_time
model_decision_time <= paper_admission_decision_time <= execution_time
signal generated/available time <= paper_admission_decision_time < signal expiry/freshness deadline
```

`event_time` is when the source event occurred, `ingested_at` is receipt/persist
time, and `generated_at` is when a derived record was computed. They retain those
semantic roles; do not collapse them into generic `decision_time` or infer one
universal total ordering between `available_at` and `feature_cutoff`.

### 5.3 Trainer

Relevant active authorities at audit time:

- persistent native CUDA trainer;
- continuous offline GPU trainer;
- RL inference sidecar and checkpoint/evidence publishers.

Before diagnosing:

```bash
systemctl --user show ai-bot-v2-native-cuda-trainer-persistent.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p ExecStart --no-pager
systemctl --user show ai-bot-v2-continuous-offline-gpu-trainer.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p ExecStart --no-pager
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu \
  --format=csv,noheader
```

Trainer health requires all of:

- clean accepted-row count greater than zero;
- rejection reasons accounted for;
- generation-appropriate input dimension and exact feature schema hash/order (446/1,784 current source; 477/1,908 historical deployment only);
- finite loss/gradients/parameters;
- actual parameter/weight delta when a learning step is claimed;
- checkpoint blob safely loadable and tied to the reported manifest;
- publication/replay/archive success propagated;
- train/validation/holdout identities non-overlapping;
- no promotion by disabled/forced validation guard unless explicitly approved and labeled.

The deployment/history versus current-source generations are documented in
[TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md](components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md#5-tensor-abi-historical-4771908-and-current-4461784-generations).
The intended current 446-feature compact-JSON SHA-256 is
`f7ab7245c0919f0be4a2831d193dca5263b643c0d875f992a68ba8fe01e3c34c`;
the historical 477-feature digest was
`263b7ce4feae6fcbc34ff4aad593bb8bde7aa3e6469d6662ab8b5186c200b239`.
Width alone cannot detect a same-length reorder and the current digest does not
migrate an older checkpoint. This read-only AST check avoids importing trainer
runtime code and exits nonzero when the current source changes without an
approved ABI migration:

```bash
python3 - <<'PY'
import ast
import hashlib
import json
from pathlib import Path

path = Path("v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py")
tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
node = next(
    item for item in tree.body
    if isinstance(item, ast.AnnAssign)
    and getattr(item.target, "id", None) == "FEATURE_SPEC"
)
spec = ast.literal_eval(node.value)
expected = "f7ab7245c0919f0be4a2831d193dca5263b643c0d875f992a68ba8fe01e3c34c"
actual = hashlib.sha256(
    json.dumps(spec, separators=(",", ":")).encode()
).hexdigest()
print(json.dumps({
    "feature_count": len(spec),
    "ordered_spec_sha256": actual,
    "model_input_width": len(spec) * 4,
    "matches_current_source_contract": actual == expected,
}, sort_keys=True))
raise SystemExit(0 if len(spec) == 446 and len(spec) * 4 == 1784 and actual == expected else 1)
PY
```

Also compare the loaded checkpoint/status feature count, width and digest. A
446/1,784 source process loading an unidentified 477/1,908 artifact is a stop,
not a reason to relabel the artifact.

Do not restart trainers casually. AdamW and the AMP scaler are recreated on every
`train()` call, not only at process restart, so there is no ordinary cycle-to-cycle
optimizer/scaler continuity to preserve. A process restart additionally clears
the in-memory replay deque and GRU temporal buffers, then follows the configured
checkpoint-load/promotion path; that can change the effective prediction
authority. The scheduled pretrain unit includes auto-promote/auto-restart flags.
It and the native PPO/MASA continuous guard service are now held inactive/dead,
their timers are stopped, and the guard's former failed state was reset. Keep
that containment until the controlled burn-in below is complete.

Four trainer unit import environments were repaired at the 2026-07-18 cut:

```text
ai-bot-v2-native-cuda-trainer-persistent.service
  PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD
ai-bot-v2-continuous-offline-gpu-trainer.service
  PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD
ai-bot-v2-trainer-scheduled-pretrain.service
  PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD/v2/backend
ai-bot-v2-native-ppo-masa-continuous-training-guard.service
  PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD
```

The whole value is quoted in each installed `Environment=` assignment and its versioned `claude_worklog/systemd/user` mirror. Targeted `systemd-analyze --user verify` returned exit 0 with no diagnostic attributable to these four definitions, and effective `Environment` inspection preserved each full path. Verification also reported unrelated installed-unit warnings; do not claim the unit estate is globally clean. All four trainer services are inactive/dead under `RefuseManualStart=yes`; scheduled/guard timers are stopped. A corrected environment or successful unit parse does not prove a training iteration, checkpoint identity, PPO supply, weight delta or holdout edge.

Runtime truth has additional fail-closed rules:

- `checkpoint_retention_manifest.json` is a control file, never a checkpoint. Require schema `native_cuda_trainer_checkpoint_retention_manifest_v2`. Retention candidates must match `v2_hybrid_ckpt_*.json` or `.weights.npz` in serving/candidate/rejected stores; a recovered latest ID must name a complete metadata/weight pair. Active serving, latest candidate, any artifact intersecting a pending PPO claim and SQLite/WAL/SHM must be pinned; unreadable claim state must pin all rejected artifacts. Rollover may remove only complete unpinned JSON/NPZ pairs.
- Outer trainer status schema must remain `native_trainer_runtime_status_v1`. Do not accept a nested readiness schema as the document identity.
- `cycle_process_pid`/activity describe a direct/manual probe. `service_pid`/`service_active` describe systemd. A live probe does not prove the held service is running.
- Process and CUDA readiness require observed evidence. Missing evidence must report INACTIVE or `BLOCKED_NO_CUDA_INFERENCE_EVIDENCE`, never a hardcoded ACTIVE.
- Persistent promotion requires `V2_TRAINER_VALIDATION_CHECKPOINT_GUARD=true`; offline child nonzero exit must propagate to systemd. Do not remove the repair hold merely because restart policy can retry.

**Red stop — trainer cannot be restarted for ordinary learning yet.** The former equal-clock, corrupt-terminal/reward, four-token-cache, optional-checkpoint-hash, unfitted-calibration, absent-ledger and fixed-receipt-expiry probes are now source-mitigated. Do not keep reporting them as current source behavior. Current `run_hybrid_trainer_cycle` integrates the exact claim planner, separate serving/candidate/rejected stores, `v2_exact_ppo_consumption_ledger_v3`, optimizer write-ahead fence, startup artifact reconciliation, candidate/confidence/serving decisions, persisted disposition and verified serving restore. Receipt decision time is microsecond-aware, and exact receipts have no fixed expiry. The current stop is deployment and runtime proof:

- No held cycle has exercised cold-start candidate accumulation, unique exact-PPO claims, rejected-attempt persistence, crash reconciliation, verified-serving promotion or prior-serving restore against real eligible data.
- The deployed cost producer predates the adaptive provenance schema. Exact on-policy supply will remain zero until controlled producer deployment/restart and adaptive interval burn-in; static/fallback cost must continue to be ordinary-lane-only.
- The sole/latest PPO row can still land entirely in validation under the PIT-safe chronological split. Supply policy must prove nonzero optimizer PPO without moving future information backward or contaminating untouched validation.
- Configured paper/shadow fee and reference-notional evidence is now explicit, hashed and rederived; do not continue treating that source-level identity as missing. Before transferring evidence to live, independently bind the actual exchange account's fee tier, discounts and maker-versus-taker applicability. An account-specific rate mismatch could otherwise manufacture live edge.
- Candidate lane carry is process-local, and configured coverage/confidence/edge gates remain static-threshold inventory requiring classification or adaptive replacement. The former 0.25-bps exit-slippage minimum is removed: current close accounting uses exact observed half-spread; only missing spread invokes the configured reserve and marks fallback, which exact PPO must reject. Safety and PIT invariants must not be weakened.
- No held runtime has produced nonzero eligible V2 targets, both-direction uncertainty-qualified calibration, an integrated uniquely consumed PPO update, a promoted/loaded verified-serving checkpoint or positive untouched after-cost edge.
- The behavior-receipt archive lifecycle stops at `OUTCOME_FINALIZED`: `TRAINER_CONSUMED` is not yet appended after durable SQLite disposition. Until that exact post-ledger hook and its crash/idempotency tests exist, retention completion is unproved and the unbounded archive must remain untouched.

The safe order is: complete the final integrated source suite; run a no-training/read-only probe; deploy/restart only the cost producer under the approved protocol and wait for its adaptive proof; then run a bounded isolated cold-start→non-serving-candidate→unique optimizer update→checkpoint/calibration restore→rejection rollback→promotion cycle. Preserve before/after dataset, partition, parameter and artifact digests; verify the SQLite chain/claim/crash dispositions, exact receipt/finalized-outcome/reward identity, no supervised fallback, NPZ round trip/path containment, untouched PIT validation, RSS/swap/log/Redis growth and truthful service/PID/CUDA fields. Only repeated bounded resident evidence may justify reviewing one hold. Do not start either timer or release all holds together.

### 5.4 Prediction and publication

Verify:

- required trainer/model/live-block fields;
- feature snapshot/tensor/checkpoint IDs;
- per-source `event_time`, `ingested_at`, `available_at`, derived `generated_at`,
  `feature_cutoff`, and the stage-specific ordering above;
- replay snapshot ready and actual write success;
- durable archive write success;
- prediction Redis write return;
- downstream lineage emitted only after success.

Known defect: the publisher copies the payload, mutates only that copy on archive/replay failure, and the caller ignores its boolean before publishing lineage from the original. Treat lineage as unproven unless the durable writes are independently verified.

### 5.5 Orchestrator and risk

The orchestrator’s `risk_decision_id` is lineage, not an allow action by itself. Current source performs an exact final reread of the canonical risk and orchestrator records; deployed rows must still prove that contract.

For every candidate/fill being investigated, join on:

- prediction ID;
- orchestrator decision ID;
- exact risk decision ID;
- symbol/side/timeframe;
- model/checkpoint and feature snapshot IDs;
- `model_decision_time`, signal generated/available/expiry fields,
  `paper_admission_decision_time`, and `execution_time`;
- payload hashes where available.

Then require the matched risk action to be explicit allow and require the final v3 receipt to bind the reread record/hash. Historical rows and pre-repair deployed generations can contain the earlier deny/allow disagreement; segregate them from clean evidence.

### 5.6 Paper trade-management

Primary entrypoint: `v2.backend.app.cli.v2_trade_management_paper_loop`.

Do not judge it from the cycle summary alone. Inspect a candidate’s full path:

```text
prediction trust
→ orchestrator lineage
→ matched risk action
→ strategy/pre-trade/fee/A+/1m/temporal gates
→ tier and sizing
→ churn and portfolio freeze
→ preemptive admission
→ position transition
→ fill-write invariant
→ lifecycle reconciliation
→ accounting and PPO entry fields
```

The 2026-07-16 “known current behaviors” list—confidence-only gate relaxation, fee omission, fast-path skip, frozen fee mutation and non-authoritative risk deny—describes historical/pre-repair generations. Current source retires those effective paths and funnels accepted rows through the common append helper. Do not relabel old rows as repaired. A performance window is clean only when each row has a replayable v3 final receipt, cycle snapshot/commit, revocable receipt, current allocation identity, complete point-in-time clocks and generation-aware lifecycle provenance.

The supply bridge remains a separate operational blocker: its broad Redis discovery path is disabled because scanning the very large keyspace can stall the loop. No accepted-fill proof should be inferred from the bridge being disabled or from a cycle with zero candidates.

For restart/rehydration of a partially closed position, require all of the following before any new fill can net against it:

- `position_reconstruction_schema_version=PAPER_OPEN_POSITION_RECONSTRUCTION_V1` and a recomputed canonical `position_reconstruction_hash`;
- exact position/generation/version, symbol/side, positive remaining quantity/average entry, ordered unique source-fill IDs and aware ordered entry/open/reconstruction clocks, with reconstruction not later than current reconciliation observation;
- incurred = remaining + allocated conservation for both entry fee and entry slippage, including their materialized fallback rates, sources and complete basis status;
- OPEN_POSITION, paper-only, no-real-order safety flags and a byte-for-byte round trip after reconstruction;
- for every historical netting fill, a versioned receipt whose hash binds close ID, position generation, fill ID, side and `input_quantity = consumed_quantity + residual_quantity`;
- whole-generation suppression only when explicit final-close and `pre_close_quantity == closed_quantity` or zero remaining quantity both prove full consumption.

Legacy/tampered/future-clock/incomplete partial snapshots, invalid netting receipts and same-side merges with mixed complete/incomplete cost basis must be quarantined rather than re-inferred. Accepted-fill disk compaction must retain both the reconstruction and netting receipts. Source validation passed 509 full paper-management/persistence cases, 16 focused adversarial/persistence cases and four existing compaction/rehydration selectors; no runtime restart or migration has tested real stored state.

For a candidate that does reach finalization, inspect this exact order:

```text
_paper_precycle_current_mark_exposure_snapshot
-> build_cycle_reservation_snapshot
-> allocator (lineage binds snapshot_hash)
-> build_candidate_commit_receipt (strict current prefix)
-> _paper_final_admission_point_in_time_contract
   -> _paper_revocable_control_commit_revalidation
-> _paper_append_accepted_with_halted_probe_finalization
-> _paper_persisted_admission_rejection_reasons
   -> validate_intrinsic_candidate_commit_receipt
```

### 5.7 Portfolio and guardian

Portfolio state is derived from valid paper state and market prices. Verify:

- duplicate portfolio publisher processes;
- source ledger/session IDs;
- exclusion of invalid admission lineage;
- price freshness;
- initial-capital source rather than fallback;
- equity/PnL reconciliation;
- artifact generated time and Redis TTL.

Guardian output combines disk and Redis evidence. A stale disk artifact can disagree with current Redis state. Trace every blocker to its source artifact and generated time.

## 6. Backend, frontend and mobile

### 6.1 Backend

Effective deployment is four Uvicorn workers from mutable `v2/backend`, not the old release symlink. Before a backend restart capture:

```bash
systemctl --user show ai-bot-v2-public-website-backend.service \
  -p FragmentPath -p DropInPaths -p WorkingDirectory -p ExecStart \
  -p MainPID -p ActiveEnterTimestamp --no-pager
git rev-parse HEAD
git status --short --untracked-files=all
```

A restart can load dirty source. Four workers also mean:

- local JSON locks are not cross-process;
- in-memory metrics/history are fragmented;
- module globals/caches exist per worker;
- mixed import namespaces can duplicate state within a process.

### 6.2 API/auth

Do not infer auth from OpenAPI; it declares security on zero operations. Inspect route dependencies and actual middleware. Nine middleware layers are pass-through. Some API operations mutate paper/admin state or launch subprocesses.

Auth health:

```bash
curl --fail --connect-timeout 3 --max-time 10 --silent --show-error \
  http://127.0.0.1:8000/api/auth/health | python3 -m json.tool
```

At audit time auth was local-file/non-production, durable stores and MFA were not ready, and token/cookie behavior was development-oriented. Never include a login password in documentation. Tighten local file modes and rotate/migrate credentials only through an approved security change.

### 6.3 Frontend

Vite preview serves ignored `v2/frontend/dist`; source edits have no effect until a controlled build. The backend can also serve the same dist. Before deployment compare:

```bash
stat -c '%y %s %n' v2/frontend/dist/index.html v2/frontend/src/main.tsx v2/frontend/src/router.tsx
find v2/frontend/src -type f -newer v2/frontend/dist/index.html | wc -l
npm --prefix v2/frontend ls --depth=0
```

The last command currently fails because dependencies are incomplete; do not treat a failed build as a runtime outage without preserving the existing dist.

Runtime public assets require explicit build inclusion because ordinary public-directory copying is disabled.

### 6.4 Mobile/watch/CLI

Swift targets duplicate endpoint/client/model contracts. A backend schema change requires:

1. atlas lookup for the API path and field;
2. TypeScript client/reference review;
3. both Swift API/model definition reviews;
4. decode tests with missing/additional/null fields;
5. backwards-compatible server rollout before client release.

## 7. Failure triage playbooks

### 7.1 A service is failed or restarting

1. Capture effective unit, drop-ins, result, PID, restart count and Git state.
2. Identify whether nonzero is deliberate policy output, path/env syntax, worker exception, dependency failure or OOM.
3. Read the unit’s configured output destination; user journal may be empty.
4. Check whether a supervisor will restart it automatically.
5. Determine whether starting it is mutating/destructive.
6. Reproduce only in isolated non-live state if possible.
7. Change one thing, run `systemd-analyze --user verify`, then restart only with approval.

Do not “fix” the orderbook rollover failure under this generic playbook.

### 7.2 Redis memory/eviction pressure

1. Record memory/persistence/stats and key count.
2. Determine whether evictions are already increasing.
3. Capture key-pattern counts and memory sampling without dumping values.
4. Identify TTL/no-TTL producers in the atlas.
5. Protect paper/auth/risk/lineage evidence before any pruning.
6. Obtain approval for export/backup and for any maxmemory/retention change.
7. Validate restore before deleting.

Increasing memory or deleting keys without finding unbounded producers only delays recurrence.

For a fast-growing file-backed service, capture two byte/time samples and its exact PID/unit before restart. For the microstructure monitor, verify that each resident row has schema `v2_microstructure_feed_quality_monitor_loop_log_v1`, `symbols_count=149`, bounded scalar fields rather than nested `trust_rows`, and unchanged paper-only safety flags. Confirm full Redis/status outputs still advance and inspect the ten-minute rotation timer/service result. A small stdout file alone can mean `silent` logging, a dead producer or failed artifact writes; it is not sufficient health evidence.

### 7.3 Feature/prediction becomes stale

Trace upstream, do not restart everything:

```text
provider heartbeat/key
→ final candle/availability
→ feature worker heartbeat/latest/archive
→ tensor eligibility/rejection
→ trainer prediction/publication
→ all-timeframe/orchestrator consumption
```

If core OHLCV is current but an enrichment is stale/missing, the current pipeline may still mark aggregate freshness current. Inspect source-specific context.

### 7.4 Trainer reports no learning

Check, in order:

1. candidate-training generation versus immutable serving generation and whether a rejected candidate was durably retained;
2. loaded row count plus immutable row/receipt/outcome/rollout IDs;
3. clean trust classification, strict finality/clocks, reconciled economics and rejection reasons;
4. durable unique-consumption state, retry status and duplicate count;
5. on-policy field completeness versus outcome-supervised mode;
6. chronological batch/train/validation selection and whether optimizer PPO supply is nonzero without contaminating validation;
7. finite loss/gradients/optimizer steps and canonical terminal/reward identity;
8. full-content dataset/tensor-cache hash plus parameter hash/delta;
9. checkpoint weight/generation hash, action-conditioned calibration state and write/load round trip;
10. promotion decision, prediction publication result and rejected-candidate serving restoration;
11. feedback/replay label version, complete PIT cost provenance and rollout ordering;
12. untouched holdout overlap and repeated-service resource growth.

A heartbeat and GPU utilization alone are insufficient.

### 7.5 Paper fills stop

Do not lower gates reflexively. Count rejection reasons at each stage and distinguish:

- no candidate supply;
- stale/dirty data;
- publication/archive failure;
- orchestrator arbitration;
- risk deny;
- local strategy/pre-trade/A+/temporal gates;
- tier/sizing/churn/freeze;
- `PAPER_ALLOCATOR_MARKET_EVIDENCE_BLOCKED` from missing/invalid microstructure schema, clocks, trust, adaptive minimum or action; partial/missing liquidity; missing/no-trade intent-owned regime; candle-finality/availability failure; or any required existing/same-cycle correlation pair;
- `ADAPTIVE_TUNING_AUTHORITY_NOT_VALID` from an invalid/expired/tampered canonical envelope or a current-session mismatch;
- `PAPER_CYCLE_RESERVATION_SNAPSHOT_BLOCKED` from legacy/unsealed open rows, missing source-fill proof, stale current mark or exhausted adaptive notional/margin/loss/drawdown capacity;
- final-v3 cycle-commit, revocable-control, guardian-TTL, owner-projection, exchange-filter or bracket rejection;
- invalid position transition;
- lifecycle/accounting quarantine;
- runtime exception such as frozen fee mutation.

Gate relaxation changes the research policy and requires explicit approval and tests.

Even when allocator market evidence is `READY`, retain NO-GO for A+ certification until microstructure trust validates canonical expiry/remaining TTL. READY currently means executable fail-closed evidence, not complete freshness or profitability proof.

### 7.6 Paper fills occur despite risk deny or without v3 authority

This was a known pre-repair defect and is now an invariant breach if a new row appears. Preserve:

- exact prediction/orchestrator/risk/fill IDs and payload hashes;
- risk action and generated time;
- local gate result and override markers;
- admission tier/path;
- fast-path marker;
- position/lifecycle/accounting records;
- whether PPO entry fields exist;
- `paper_final_admission_contract_v3`, its bound/receipt/projection hashes, exact risk/orchestrator reread, cycle snapshot/commit and revocable-control receipt, including every rejection reason.

Quarantine the row from performance/training evidence. Do not rewrite/delete history.

### 7.7 Website is wrong but workers look healthy

Trace:

```text
primary Redis/file state
→ backend route/resource-plane payload
→ public runtime JSON generated time
→ explicit Vite build copy/prune
→ dist artifact
→ Vite/backend static serving
→ browser cache/client decode
```

Remember that source can be newer than dist and remote tunnel routing is provider-side.

## 8. Restart and deployment change protocol

There is no trustworthy global “restart all” procedure. For a single non-live service:

### Before

- explicit scope/approval;
- Git HEAD, dirty-state and in-scope content-fingerprint capture;
- effective unit/drop-ins and environment-key names (not values);
- authoritative state and last-good artifact/checkpoint IDs;
- consumer list/change-impact review;
- rollback command/path;
- proof the service is non-destructive and not a live submitter;
- one-cycle acceptance criteria.

### Validate definition

```bash
systemd-analyze --user verify /home/wali/.config/systemd/user/SERVICE.service
```

For a timer, verify both service and timer. Warnings about paths with spaces, bad URL escapes, wrong sections and unknown escapes are material.

### Restart only after approval

```bash
systemctl --user restart SERVICE.service
systemctl --user show SERVICE.service \
  -p ActiveState -p SubState -p Result -p MainPID -p NRestarts --no-pager
```

Then verify primary outputs and downstream consumers for a complete cycle. Do not use this protocol for live transport, order, destructive retention, trainer promotion, paper/risk policy or multi-service restarts without a dedicated approved plan.

## 9. Backup and recovery requirements

The current system has no proven full recovery. Before claiming backup readiness, capture and restore-test:

- Redis consistent snapshot/export, config, key/TTL schema and version;
- model NPZ blobs, manifests, architecture/schema and checksums;
- replay/archive blobs, indexes, manifest/tombstones and label versions;
- paper lifecycle/ledger/closed trades/portfolio source state;
- auth users/revocations with protected permissions;
- SQLite main DB plus WAL/SHM using SQLite backup/checkpoint semantics;
- installed unit files/drop-ins and enable/mask/link state;
- frontend dist hash and exact source/dependency build provenance;
- Cloudflare routing export and newly rotated credential reference;
- OS/Python/Node/Swift/CUDA/Redis package versions;
- operator/runbook commit plus exact content hashes for dirty/untracked canonical
  docs and the validated `atlas/ATLAS_BUILD_MANIFEST.json`;
- secret-safe bundle manifest for effective units/drop-ins, dist, checkpoints and
  other ignored deployment artifacts whose bytes Git cannot identify.

Copying a live SQLite main file without its WAL is not a backup. A checkpoint directory is not a full-system backup. An RDB without a tested restore and post-snapshot loss bound is not disaster recovery.

## 10. Retention/change control

Current automatic mutation must be recorded even when the operator initiates no
cleanup. The six-hour persistent rollover timer repeatedly invokes a currently
broken service whose source would delete oldest replay directories until the
tree is at most 100 GiB (`tools/orderbook_replay_rollover.py:10-12`, `:46-83`).
Merely fixing/reloading that service can let the already-active timer execute it.
The separate 15-minute non-dry-run janitor is already executing the mutation
surfaces listed in §4.5. Pausing, disabling or masking either timer is itself a
state change and requires approval; until then, preservation/holdout work must
account for the race and capture every trigger/result.

Before changing retention:

1. inventory all writers and readers;
2. classify raw replay, derived cache, audit evidence, current authority and reconstructible data;
3. reconcile 100 GiB and 300 GiB policies;
4. produce a dry-run deletion manifest with bytes/date/count;
5. protect manifest/checksum/index integrity;
6. confirm no holdout/training/paper investigation references the candidate data;
7. back up and restore-test;
8. obtain approval;
9. delete in bounded batches with free-space and service monitoring.

## 11. Change-impact checklist

For every code/config/unit/schema change:

- exact file/symbol/line and owner;
- why current behavior is wrong;
- callers/importers from `atlas/CHANGE_IMPACT_INDEX.json`;
- Redis readers/writers and TTLs;
- env/config consumers and safe default behavior;
- data fields and client decoders;
- API producers/consumers;
- timestamp/finality/dirty-sample consequences;
- strategy/PPO/MASA/risk/live-execution classification;
- position-state transition impact;
- tests using isolated state;
- deployment/drop-in/import-namespace impact;
- rollback and evidence preservation;
- atlas regeneration and doc update.

## 12. Incident severity

| Severity | Examples | Immediate stance |
|---|---|---|
| SEV-0 | active unauthorized real order/mutation, credential compromise | do not improvise: no single vetted repository-wide kill procedure was proven; immediately escalate to the authorized human operator/security incident owner, preserve evidence, and contain/rotate only under an approved scope-specific procedure |
| SEV-1 | invalid paper fills contaminating training, future leakage, Redis data loss/eviction, destructive retention activation | stop affected producer/consumer with approval, quarantine evidence, preserve state |
| SEV-2 | trainer/publisher outage, stale features, broken API/auth state, repeated crash loop | isolate component, prevent bad downstream data, restore last-good non-live state |
| SEV-3 | dashboard/report drift, optional provider outage, noncritical automation failure | record and repair without broad restarts |

Never use severity as permission to enable live behavior or make an unreviewed strategy/risk change.

The two discovered disarm tools are not interchangeable and do not constitute a
vetted repository-wide SEV-0 procedure. `v2_live_canary_kill_switch.py` writes only
the `v2:live_canary:*` namespace and its default arm expires after 86,400 seconds
(`v2/backend/app/cli/v2_live_canary_kill_switch.py:1-18`, `:86-102`;
`v2/backend/app/services/live_canary/execution_adapter.py:106`).
`v2_live_submit_disarm.py` can mutate broader live-gate, trader-execution and
transport state; it requires an explicit Redis URL, reason and `--apply`, and its
backups expire by default (`v2/backend/app/cli/v2_live_submit_disarm.py:128-197`,
`:200-217`). Before either is promoted into emergency guidance, an authorized
owner must identify every active caller/transport, approve exact stop/disarm
actions, define credential-containment and evidence-preservation steps, and test
post-action verification and escalation.

## 13. End-of-shift handoff

Record:

- time/timezone, Git start/end HEAD and in-scope start/end content fingerprints;
- dirty/untracked files separated into owned versus concurrent, with secret-safe
  hashes/bundle-manifest references for bytes not identified by HEAD;
- installed/running/failed service/timer counts;
- Redis memory, eviction and persistence state, including TTL/type/length/bytes for the Guardian PIT list and trainer counterfactual string;
- disk state; every automatic janitor/rollover trigger, result, deletion count
  and bytes reclaimed; and any separate operator-initiated retention action;
- exact seven-service repair-hold and two-timer state; trainer authorities, service/cycle PIDs, observed CUDA state, checkpoint IDs/complete-pair/load state, confidence-head/calibration fingerprint and clean-row/PPO metrics;
- feature/prediction/risk/paper/portfolio sample lineage;
- readiness blockers;
- incidents and quarantined sample IDs;
- exact commands run and exit status;
- files changed;
- approvals and next safe action.

The canonical issue list is `CURRENT_FINDINGS_AND_RISK_REGISTER.md`; exact source/contract impact is in `atlas/`; reconstruction requirements are in `REBUILD_BLUEPRINT.md`.
