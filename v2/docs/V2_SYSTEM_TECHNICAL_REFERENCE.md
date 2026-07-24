# AI Bot V2 system technical reference

**Reconstructed:** 2026-07-16

**Runtime evidence:** audited workstation, read-only observation 2026-07-16 America/New_York

**Current safety mode:** non-live/paper-shadow; real exchange mutation code exists but no active authorized submitter was observed

**Recommendation:** live NO-GO; current paper/training evidence is not clean enough for promotion.

> **Current-source and post-reload addendum through 2026-07-18 UTC:** the dated trainer/accounting map remains [ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md](../../docs/system_audit_2026_master/ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md), but section 0 below supersedes its final-materialization and same-cycle-reservation details. A controlled paper one-shot completed 597/0/597 in 69.85 seconds at 4.70 GiB peak RSS/zero swap with bounded current/adaptive artifacts; persistent 132-row history truthfully remained FAIL_CLOSED and bracket credentials remained unbound. Guardian independently returned semantic BLOCKED in 3.57 seconds at ~35 MiB/zero swap: 99,644 PIT-valid coverage observations admitted zero economic holdout rows. A separate 4,592,832-configuration counterfactual probe peaked at 1.65 GiB/zero swap and semantically returned NO_GO. Redis remained about 25.49 GiB under `allkeys-lru`/no AOF, with an unexpired 6,054,941-row/~6.23-GB Guardian list and an unexpired 536,827,021-byte counterfactual string. Corrected archive/hot-cache/consumer source checks pass 87, but no real Redis migration ran. Seven research/trainer/replay services are held and both trainer timers are stopped pending controlled migration and repeated burn-in. The microstructure monitor's resident stdout was compacted with >99.8% sampled byte-rate reduction, ~14 GB history was compression-preserved as ~876 MiB under bounded rotation, IDE watcher scope was narrowed, and four trainer units received quoted complete import paths. The 10.9 GB supervisor event log was still growing because its source fix was not deployed. None is trainer/trading promotion proof. Performance remains `HALTED_PERFORMANCE`; G11/G12 fail. A+ and 1000x were not achieved or guaranteed.

This reference describes implementation, not aspiration. It supersedes the 2026-07-11 version, which was already stale. Function-level details are generated in `docs/system_audit_2026_master/atlas/`; operational procedures are in the master operator manual.

## 0. 2026-07-18 paper finality and authority addendum

### 0.1 Materialization state machine

The current paper admission path is a sequence of immutable evidence transformations, not one distributed transaction:

```text
Redis/file/process snapshots
  -> paper_precycle_current_mark_exposure_snapshot_v1
  -> paper_cycle_base_resource_evidence_v1
  -> paper_dynamic_envelope_reservation_evidence_v1
  -> paper_cycle_reservation_snapshot_v1
  -> adaptive_capital_allocation_input_v1 / allocation
  -> paper_cycle_reservation_commit_v1
  -> paper_revocable_control_commit_revalidation_v1
  -> paper_final_admission_contract_v3
  -> accepted list
  -> paper_persisted_ledger_contract_v1 or quarantine
```

`_paper_append_accepted_with_halted_probe_finalization` is the common append boundary. It calls `build_candidate_commit_receipt` against the exact current `accepted` prefix, stamps the commit on the intent, calls `_paper_final_admission_point_in_time_contract`, copies the nested revocable receipt to top-level aliases, and appends only a PASS row. The same boundary finalizes a halted-probe token only after the append succeeds.

`_paper_final_admission_point_in_time_contract` captures validation start and commit clocks, replays component point-in-time/economic contracts, rereads canonical risk/orchestrator/filter/bracket evidence, invokes `_paper_revocable_control_commit_revalidation`, and builds `paper_final_admission_contract_v3`. `bound_material` includes identity, component clocks, source hashes, tier and canonical-decision contracts, frozen gate contracts, preemptive semantics, the exact revocable receipt, the exact cycle snapshot/commit, allocator input/economic identities, filter/bracket rereads, sizing, safety flags and a sealed persisted-row projection. The receipt is SHA-256 over canonical JSON.

`_paper_persisted_admission_rejection_reasons` requires the v3 receipt/hash/status aliases, exact revocable receipt at nested/top-level/bound locations, cycle contract replay, bound-material hash and an unchanged `_paper_persisted_admission_projection`. `_seal_paper_persisted_ledger_contract` then binds that projection into `paper_persisted_ledger_contract_v1`. A downstream addition outside the projected key set can remain telemetry; a change/deletion/type mutation inside critical fields or nested payload hashes quarantines the row.

### 0.2 Revocable controls and residual race

`_paper_revocable_control_source_materials` obtains exact typed source material for:

| Role | Redis/process source |
|---|---|
| `continuous_edge_guardian` | `v2:continuous_edge_guardian:a_grade_execution_gate` |
| `paper_entry_freeze_source` | `v2:paper:entry_freeze` |
| `portfolio_state_source` | `v2:portfolio:state` |
| `adaptive_tuning_source` | `v2:orchestrator:adaptive_gate_tuning_state` |
| `paper_position_or_ledger_source` | `v2:paper:positions`, with ledger fallback only when positions is genuinely missing |
| `paper_closed_trades_source` | `v2:paper:closed_trades` |
| `paper_runtime_owner` | procfs/systemd projection from `_paper_active_runtime_owner_status` |

`_paper_revocable_control_commit_revalidation` requires each current canonical JSON material hash and source label to equal the frozen pre-cycle receipt, recomputes the effective freeze and current risk, requires guardian TTL `0 < ttl <= 180`, and requires exactly one current canonical paper writer with no forbidden/duplicate owner. Portfolio-truth/nonoverridable freeze cannot be waived. It emits `paper_revocable_control_commit_revalidation_v1` with `paper_only=true`, `routes_to_live=false`, `places_real_order=false`, `cross_process_atomic=false` and the explicit residual race string.

That last flag is essential: independently owned Redis keys, procfs inspection and list append are not one transaction. Exact rereads reduce the stale-PASS window but do not provide a Redis fencing token, CAS, durable generation lease or crash-recovery journal. A second process can race after the reread. Runtime ownership must therefore remain single-writer and any duplicate is a hard new-entry block.

### 0.3 Current-mark/source-fill exposure and cycle reservation

`_paper_accepted_fill_proof_source` reads only the bounded exact list at `v2:paper:accepted_fills`; it does not reconstruct a proof from compact position rows. `_paper_precycle_current_mark_exposure_snapshot`:

1. Enumerates open position rows and stable generation/position/fill/allocation identities.
2. Reads one current mark evidence row per symbol and requires source-material hash, CURRENT freshness and aware event/generated/available/observed ordering inside the snapshot window.
3. Resolves every position's durable source-fill IDs, rejects reuse across positions, and joins every ID to an accepted-fill proof with the same symbol.
4. Calls `_paper_persisted_admission_rejection_reasons` for every source fill and requires exactly equal positive allocator `max_loss_if_stop_hit` and `max_loss_usd` aliases.
5. Computes current gross notional as `sum(abs(quantity) * current_mark)` and projected open loss as the conservative sum of every durable source-fill max loss. Partial reductions do not release loss until sealed fill-quantity attribution exists.

Any missing/stale/tampered/legacy/partially joined open row changes the snapshot to BLOCKED and prevents new entry; exits are not disabled. The schema binds ledger/proof observation and snapshot start/completion clocks, per-symbol/total current-mark notional, projected loss, row/source-fill projections, source hashes and reasons.

`cycle_reservation.py` is pure: it reads no Redis, clock, file or exchange. `build_cycle_reservation_snapshot` receives caller-supplied hashes and dynamic limits, validates every prior accepted row's final v3/revocable/cycle/allocation proof, and derives:

- total and same-symbol notional before the candidate;
- remaining total/symbol envelope, with the optional emergency symbol cap;
- remaining margin after the adaptive buffer and the allocator margin adapter;
- realized drawdown + precycle open loss + same-cycle accepted loss;
- remaining stress loss and per-candidate risk fraction.

The allocation input and allocation output must both bind `paper_cycle_reservation_snapshot_hash`. `_build_candidate_commit_receipt_intrinsic` replays allocation identity/economic aliases and checks total notional, symbol notional, margin buffer, per-candidate risk and projected stress drawdown. The public `build_candidate_commit_receipt` additionally calls `cycle_reservation_prior_rows_rejection_reasons`, so add/remove/reorder/mutation between allocation and append blocks. Persistence calls `intrinsic_candidate_commit_receipt_rejection_reasons` / `validate_intrinsic_candidate_commit_receipt` because a later lifecycle collapse can legitimately change the current accepted list without changing the historical prefix that governed this row.

### 0.4 Allocator market-evidence authority

`_build_allocation_input` no longer treats candidate-supplied favorable context as allocation authority:

- `_read_v2_microstructure_trust` searches exact `v2:microstructure:trust_score:<SYMBOL>:<TIMEFRAME>` keys and accepts only schema `microstructure_trust_score_v2`, matching symbol/timeframe and aware `generated_at <= available_at <= decision_time`. Contract/future-clock failures are returned as typed diagnostic status and contribute no authority. The producer key has a Redis TTL, but the payload has no canonical `expires_at` and this consumer does not check remaining TTL; arbitrarily old still-present evidence is unresolved freshness debt.
- `_derive_allocator_liquidity_score` records signal/prediction/feature liquidity as `upstream_reported_liquidity_score` with `authoritative=false`. Executable liquidity comes only from the current microstructure payload's explicit positive score or the complete pair of current orderbook depth and spread. Depth-only returns `FAIL_CLOSED_PARTIAL_ORDERBOOK_LIQUIDITY_DEPTH_ONLY`; spread-only returns `...SPREAD_ONLY`; neither returns `FAIL_CLOSED_NO_AUTHORITATIVE_LIQUIDITY_SCORE`; nonpositive explicit evidence returns `FAIL_CLOSED_NON_POSITIVE_EXPLICIT_LIQUIDITY_SCORE`. When both exist, the score is `min(depth_score, spread_score)`. `_depth_liquidity_score` is a fixed step adapter: positive depth below $5k→0.2; $5k/$10k/$25k/$50k/$100k/$250k→0.35/0.5/0.65/0.8/0.9/1.0. `_spread_liquidity_score` is 1.0 through 2 bps, then `clamp(1 - (spread-2)/48, 0, 1)`.
- The microstructure trust gate separately requires a finite score, a finite `microstructure_adaptive_minimum` in `(0,1]`, and recognized `ALLOW`/`REDUCE_SIZE`. Missing/invalid minimum, missing/invalid trust, unknown action or `NO_TRADE`/`SHADOW_ONLY`/`CLOSE_OR_REDUCE_ONLY` sets liquidity to zero with an exact blocker. `REDUCE_SIZE` or trust below the adaptive minimum caps liquidity at 0.35. `_attach_runtime_cost_capture_contract` applies the same missing/invalid-minimum and action rejection, guards all comparisons, and makes A-grade false without a valid minimum. Confidence is not an evidence substitute.
- `_derive_allocator_regime_score` retains all signal/prediction/feature score/label/mode/regime values as non-authoritative diagnostics. Executable authority is limited to an explicit intent/`strategy_explanation` score or intent-owned `strategy_regime_labels`/selected mode; allocator strategy/mode fields do not fall back to signal/prediction. Missing evidence returns `0.0` / `FAIL_CLOSED_NO_REGIME_SCORE`; invalid nonpositive explicit score returns `FAIL_CLOSED_INVALID_REGIME_SCORE`; no-trade/blocked returns 0.2 / `REGIME_LABEL_NO_TRADE_OR_BLOCKED`. Label adapters are fixed: chop/range 0.75, high volatility/liquidation risk 0.85, mean reversion 0.9, trend/momentum/breakout 1.0.
- `_derive_candidate_correlation_contexts` reads Binance 1m OHLCV returns and recomputes absolute Pearson correlation for the candidate against every distinct existing-open and already accepted same-cycle symbol. `_read_symbol_correlation_returns` probes `v2:market:ohlcv_closed:binance:<SYMBOL>:1m` before generic `...ohlcv...`, falls through when a present source is unusable, and accepts a dict candle only with an explicit true finality flag, positive close, close time and `available_at/ingested_at` no later than decision. `_parse_epoch_ms` accepts numeric exchange epochs or aware ISO only; `_correlation_returns_from_candles` requires an aware decision. Naive values yield typed rejects. Each child diagnostic's `source_hash` is canonical SHA-256 over schema `paper_correlation_accepted_source_material_v2`, source key, exact decision, accepted points `{candle_close_time_epoch_ms, close, available_at_epoch_ms, finality_evidence}`, and sorted reject counts. Its contract is `SOURCE_KEY_DECISION_TIME_ACCEPTED_CLOSE_AVAILABLE_FINALITY_AND_REJECT_COUNTS_CANONICAL_SHA256_V2`. The governing `correlation_source_hash` is canonical SHA-256 over schema `paper_correlation_aggregate_source_material_v1`, the exact decision, sorted candidate/open-symbol sets and sorted child source material; its contract is `DECISION_CANDIDATE_OPEN_SYMBOLS_AND_SORTED_CHILD_SOURCE_MATERIAL_CANONICAL_SHA256_V1`. Candidate-supplied `correlation_exposure_pct` is retained only as `signal_reported_correlation_exposure_pct` with `authoritative=false`. Missing candidate returns, last candle older than 21,600 seconds, fewer than 30 returns/aligned points or **any** unresolved required pair yields exposure 1.0 and a fail-closed status. Partial coverage stamps `INCOMPLETE_REQUIRED_OPEN_PAIR_COVERAGE`, `MISSING_PAIRWISE_RETURNS_FAIL_CLOSED`, exact pair/required counts and unresolved symbols. No open positions and the sole same symbol are the only pair-safe zero cases.

The caller explicitly includes `same_cycle_symbols` when deriving the candidate context. Therefore a first candidate changes the correlation requirements for the second even before lifecycle publishes an open position. `_build_allocation_input` accepts correlation only for `READY/MARKET_OHLCV_RETURN_CORRELATION`, `NO_OPEN_POSITIONS`, or `ONLY_SAME_SYMBOL_OPEN`; otherwise it appends `CANONICAL_CORRELATION_EVIDENCE_NOT_EXECUTABLE`. Any zero liquidity, non-executable correlation or missing/no-trade regime sets `allocator_market_evidence_status=BLOCKED` and `AllocationInput.risk_veto=true` with `PAPER_ALLOCATOR_MARKET_EVIDENCE_BLOCKED:<reasons>`.

The constants `CORRELATION_MIN_RETURN_POINTS=30`, `CORRELATION_MAX_CANDLE_AGE_SECONDS=21600` and fail-closed exposure 1.0 are fixed evidence/safety boundaries in current source. They disprove a literal “no static thresholds anywhere” claim and must be classified under RE-040; they are not permission to relax missing evidence.

### 0.4.1 Premium-index producer and mark/index consumer provenance

The observed 352/0/352 paper cycle exposed a producer self-echo, not an over-strict paper consumer. `v2_binance_public_metadata_ingestor.py` and `v2_native_ingestors_live_loop.py` could read premium-index keys they also wrote, reserialize approximately 23-hour-old source events, refresh Redis TTL and omit truthful production/availability clocks. TTL therefore appeared current while market event time was stale. The paper loop correctly produced no executable `mark_index_divergence` for all 352 candidates.

The repaired producer set is `v2_binance_mark_price_wss_seeder.py`, `v2_binance_public_metadata_ingestor.py` and `v2_native_ingestors_live_loop.py`. Output preserves the upstream Binance `event_time` and separately stamps producer `generated_at`, `available_at` and `expected_update_interval_seconds`. Metadata/native reuse checks event age directly and accepts no missing or older-than-120-second source event; it never treats renewed Redis TTL as event freshness. That 120-second constant is an immutable upstream publication/cadence safety bound, not a strategy score or admission relaxation.

`_read_v2_mark_index_evidence` now probes, in order, `v2:market:mark_price:<SYMBOL>`, `v2:market:funding:<SYMBOL>` and `v2:market:prices:<SYMBOL>`. For a nested prices row it explicitly selects `funding`; otherwise it selects the root. It requires positive finite mark and index, aware `event_time <= generated_at <= available_at <= observed_at`, a positive producer cadence (or the funding-key immutable PIT cadence), and event age no greater than `cadence * PAPER_SIGNAL_ADAPTIVE_STALE_CANDLE_MULTIPLIER`. `mark_index_source_material` binds Redis key, full outer payload, selected path, selected payload and the exact field-resolution map. Its contract is `REDIS_KEY_OUTER_SELECTED_PATH_PAYLOAD_AND_FIELD_MAP_SHA256_V2`. Consumers use the resulting mark for divergence stress and current-mark open-book valuation; missing evidence fails closed.

Source validation passed 14 focused cases, both affected producer modules' complete 10-test set, compilation and relevant Ruff. After the 2026-07-17 23:50:19 EDT reload, BTC evidence had event `03:50:20Z`, generated/available `03:50:21.773Z`, cadence 30 seconds and REST-fallback-cache source; the consumer reported `CURRENT`, age 16.108 seconds, divergence −4.45870196 bps and the V2 hash contract. The 03:53:19 UTC cycle still built 61, accepted 0 and blocked 61 because candidate reads around 03:53:20 preceded sequential symbol refresh around 03:53:38–44.

The next source is `tools/systemd_units/ai-bot-v2-binance-mark-price-wss-seeder.service`. It runs only the public Binance USD-M `!markPrice@arr@1s` stream, writes `v2:market:mark_price:<SYMBOL>` at TTL 180 seconds, and carries explicit paper-only/no-order/no-account-mutation flags. `--max-messages 600` deliberately exits the worker after 600 arrays; systemd `Restart=always` reconnects and re-resolves the adaptive symbol universe. A one-shot array wrote 149/149 symbols. The persistent unit was active from 23:57:20 EDT; sampled T/BTC/ARB/MANA receipts about five seconds later were `CURRENT`, age about 1.14–1.16 seconds, cadence 1 second and `event_time <= generated_at = available_at`. Their divergences were −102.3003121, −3.60992258, +1.62180574 and −17.46874577 bps. This proves producer activation and sampled consumer shape, not cycle-level closure. The controlled paper one-shot built 597 blocked candidates, but the supplied receipt does not enumerate every candidate's WSS evidence/reasons or prove zero missing-mark/index reasons. Do not widen freshness or substitute TTL.

### 0.4.2 Bounded adaptive-sizing operator projection

`_paper_adaptive_sizing_runtime_status` is an observability reducer, not a second allocation ledger. The former implementation embedded every full `_paper_candidate_allocation_publication_row`, including nested model inputs, feature snapshots, preemptive/replay evidence, stress maps and final receipts. The resulting public JSON reached about 5.29 GB; the paper process reached about 6.7 GB RSS and approximately 161 GB of writes. The worker was stopped while this repair was loaded.

Current source performs one pass over `allocation_rows`:

1. Build the unchanged full publication row and compute its canonical SHA-256 using sorted-key, compact JSON with `allow_nan=false`.
2. Append `{source_row_index, source_row_canonical_sha256}` to the ordered hash inventory.
3. Derive complete all-candidate zero-liquidation, hedge and capital/leverage/margin facts.
4. Build `paper_adaptive_sizing_operator_projection_v1` from allowlisted scalars and bounded lists; Python string slices are capped at 512 characters, list values at 20 and list strings at 256 characters.
5. Retain at most `ADAPTIVE_SIZING_OPERATOR_PROJECTION_LIMIT=5` projections, while replacing every full row in local status calculation with a compact summary.

The status is written to Redis `v2:paper:adaptive_sizing_runtime_status` and `v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/paper_adaptive_sizing_runtime_status.json`. It declares `candidate_allocations_complete=false`, `candidate_allocations_projection_only=true`, `candidate_allocations_full_payload_omitted=true` and `candidate_allocations_authoritative_sources_unchanged=true`. `candidate_allocations_source_hashes` binds every full source row. `candidate_allocations_aggregate_sha256` hashes the ordered array of those hashes under `paper_candidate_allocation_operator_hash_contract_v1`. `paper_candidate_canonical_aggregate_contract_v1` binds exact all-row contract-fact hashes, zero-liquidation and hedge blockers, leverage/margin-mode counts, capital counts/sums and its `contract_hash`.

The max-five projection is never used to infer all-candidate safety. Guardian validates projection bindings, source coverage, ordered aggregate and canonical aggregate contract; a missing/tampered contract fails closed. A hostile sixth-row test preserved exact `{2x:5,7x:1}` and margin-mode counts and blocked zero-liquidation/hedge claims even though the visible first five were safe. `v2_out_of_sample_reverify_evidence_producer.py` identifies the marker as `operator_projection_context_only` and rejects it as canonical pending/final allocation evidence. The hashes are producer-bound mutation detection, not signatures or independent attestation; canonical decisions/intents/ledgers remain authoritative.

`write_payload` now creates a unique same-directory temporary file, preserves the existing mode, streams `json.dump`, flushes and file-fsyncs, uses atomic `os.replace`, directory-fsyncs and cleans up on failure. This prevents shared-temp collisions and partial target replacement but does not atomically couple file, Redis and canonical ledgers. Final affected validation passed 533 paper-loop, 91 OOS, 33 Guardian and 77 post-fix preemptive-edge-control tests. A synthetic 622-heavy-row status measured 149,442 bytes compact / 177,657 bytes pretty versus 4,365,409,284 bytes for the former shape.

The first controlled reload found two further failures. The compact subdocument was bounded at about 212–273 KB, but top-level `v2_trade_management_paper_live_status.json` was atomically replaced at 873,406,311 bytes and RSS reached about 1.4 GB. The 621-row receipt had only 25 valid hashes: 596 `source_row_canonical_sha256` values were null, `candidate_allocations_unhashable_source_row_count=596` and `candidate_allocations_all_source_rows_hashable=false`. Guardian correctly rejected `CANONICAL_CANDIDATE_SOURCE_HASH_INVALID` / `CANONICAL_CONTRACT_SOURCE_ROWS_NOT_ALL_HASHABLE`; this failed evidence remains part of the audit.

Post-fix read-only evidence is bounded and internally consistent for current rows:

- top live status 2,372,035 bytes versus a later pre-fix 907,518,822 bytes (~99.74% reduction); adaptive sizing 145,593 bytes; exploration tier 116,939 bytes;
- one materialized cycle with 11 signals/intents, 11 blocked, 0 accepted and 132 persistent shadows;
- adaptive sizing 5/36 projections, 36/36 valid source hashes, zero nulls and Guardian canonical-contract validation with no errors;
- exploration 5/11 projections and 11/11 valid source hashes;
- persistent-shadow projection subtree 45,270 bytes for 5 projections/132 sources, nested exploration 96,333 bytes and current shadow `[]` two bytes;
- projection and contract hashes recompute; all three public artifacts contain zero `Infinity`, `NaN` or `-Infinity` tokens.

Historical integrity remains intentionally fail closed. All 132 pre-existing persistent canonical history rows contain legacy `Infinity`; they were not rewritten, and their top operator contract reports 132 unhashable sources plus `FAIL_CLOSED`. New/current producer rows are JSON-safe.

The controlled command was:

```text
/usr/bin/time -v timeout 300 .venv/bin/python -m v2.backend.app.cli.v2_trade_management_paper_loop --once --out /tmp/ai_bot_paper_status_probe_20260718_0125.json
```

It exited 0 in 69.85 seconds with peak RSS 4,925,812 KB (~4.70 GiB), zero swap, 597 intents built, 0 accepted, 597 blocked, 551 Redis keys written and process/resource classification `PRODUCTION_OK`; that classification is not promotion. The top temp/canonical artifacts were 5,017,701/4,160,870 bytes with no `Infinity` or `NaN`. Current shadow had zero sources and PASS; adaptive sizing had 622 sources/five projections/zero unhashable, all hashes valid and Guardian validation valid; persistent history had 132 sources/five projections/132 unhashable and FAIL_CLOSED. Exploration was ACTIVE with tier counts `NO_TRADE=597`, `SHADOW_ONLY=214` and all 597 blocked. This closes one-shot boundedness, not repeated resident RSS/write-rate/restart stability. The systemd paper service remains held/inactive.

### 0.4.3 Paper cascade margin join and cross-margin diagnostic

`cross_margin_liquidation.py` remains a pure diagnostic engine. Schema `cross_margin_liquidation_v2` normalizes quantity from `positionAmt`, `position_amt`, `net_quantity`, `qty` or `quantity`; mark from `markPrice`, `mark_price`, `current_mark_price`, `last_mark_price`, `last_mark_est`, then entry fallbacks; and leverage from `leverage`, `effective_leverage` or `recommended_leverage`. Each normalized row has `leverage_evidence_available`; the snapshot exposes `leverage_evidence_complete` and `leverage_evidence_missing_symbols` instead of silently presenting missing leverage as complete.

`v2_portfolio_cascade_guard_loop.py::_paper_margin_inputs` is the current paper adapter. It reads `v2:paper:ledger.paper_account_margin_status.position_margin_rows`, indexes exactly one row per uppercase symbol and joins every open position. `paper_cascade_margin_join_v1` is PASS only when:

- every position has one nonduplicated row;
- each row is `valid=true` and `maintenance_margin_evidence_valid=true`;
- `canonical_notional_usd > 0`, `maintenance_margin_rate > 0` and `effective_leverage >= 1`;
- account margin status is PASS with `accounting_complete=true`; and
- margin base is positive while used/free margin are finite and nonnegative.

Only PASS calls `build_portfolio_liquidation_snapshot`. Otherwise the guard emits `portfolio_level_computed=false` and `risk_state=UNTRUSTED_MARGIN_EVIDENCE`. The join prevents current paper positions from silently using the pure engine's legacy direct-call 0.005 maintenance fallback. Thirteen risk/cascade tests passed. A component receipt at 04:40:17.785Z joined 2/2 open positions to two margin rows, computed maintenance margin $0.55807547, reported complete maintenance/leverage evidence, no directives and no modeled breach. Because the paper loop was held, this is component proof rather than cycle consumption.

This does not enable cross margin. The allocator continues to force `isolated_paper_simulated`; no exchange mode or leverage is mutated. `SHOCK_SCENARIOS` is a fixed approximation—BTC −5%, −10%, −20%, +10%—and `DEFAULT_BETA` is BTC 1.0, ETH 1.15, SOL 1.35, other 1.6. The result is not exchange-exact liquidation or an adaptive account-wide authority. Any change to these scenarios/aliases/join rules affects cascade directives, portfolio guard status, downstream paper exits and evidence grading, and requires PIT calibration plus complete join/fail-closed tests.

### 0.4.4 Operator-approved per-symbol ceilings and binding paper integration

The operator confirmed that `claude_worklog/codex/CODEX_PER_SYMBOL_LEVERAGE_ENVELOPE_HANDOFF.md` describes an implemented and authorized paper recommendation: ceilings of 75x for BTC/ETH, 50x for SOL/LTC/XRP and 20x for other symbols, plus liquidation distance at least five ATRs. Preserve that policy. Current source now binds it into the paper dynamic-envelope/allocator path; it still authorizes no live mutation.

The source has layered authority:

- Recommendation: `paper_trade_management/leverage_recommendation.py::symbol_leverage_ceiling` returns the authorized environment-tunable 75/50/20 values. `_liquidation_safe_max_leverage` uses `PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT` default 5. `LeverageRecommendationConfig` also fixes confidence 0.55/0.75/0.85, ATR 30/80 bps, strong-edge 20 bps, fee buffer 25 bps, maximum budget 5% and $50 loss. These are operator policy/safety adapters and must be preserved/versioned and classified accurately.
- Dynamic envelope: `calculate_dynamic_risk_envelope(..., symbol=None)` imports `PAPER_MAX_LEVERAGE` and `symbol_leverage_ceiling`. The `RiskEnvelope.max_effective_leverage` base remains 3.0. With valid favorable realized evidence, positive after-cost LCB, complete provenance and PIT liquidity/regime clocks, `growth_quality` continuously interpolates base toward the symbol ceiling or no-symbol global 75. Adverse/missing evidence contracts exponentially; output is clamped `[1, ceiling]`; live returns the supplied base unchanged.
- Candidate allocator: `_adaptive_leverage_target` first caps the envelope by the exact symbol tier. It computes continuous candidate quality from confidence, after-cost edge versus cost/volatility, liquidity, regime, drawdown and correlation, then selects `min(phase8_recommended_leverage, 1 + (envelope_cap - 1) * adaptive_quality)`. A recommendation-contract violation fails to 1x. The Phase-8 minimum is mandatory: it prevents the continuous path from bypassing the five-ATR liquidation ceiling.
- Authenticated bracket adapter: `_paper_allocate_with_bracket_evidence::input_from_evidence` requires finite signed `max_initial_leverage >= 1` and maintenance rate in `(0,1)`, then constructs all Binance integer choices `1..floor(min(max_initial_leverage, symbol_leverage_ceiling))`. Lineage records the bracket HMAC/checksum/account/environment/key/bracket clocks, `authorized_symbol_leverage_ceiling`, `evidence_bound_leverage_ceiling` and source `AUTHENTICATED_MAINTENANCE_BRACKET_AND_AUTHORIZED_SYMBOL_CEILING`.

The focused 223-test adaptive allocator + Phase-8 suite was green and the later allocator + adaptive-productivity + Phase-8 superset passed 323 tests, including a high-volatility BTC case whose Phase-8 raw recommendation, continuous target and selected leverage all remain 1x despite a 75x envelope. A separate authenticated-bracket selection passed six cases (531 deselected): BTC signed 100→1..75, SOL→1..50, DOGE→1..20, BTC signed 17→1..17 and conservative/missing-evidence behavior. Compilation and scoped F821/F811 Ruff were clean.

This remains source/test proof. Binding authority still requires authenticated maintenance-bracket evidence for the exact environment/account/symbol and total post-fill notional; actual maintenance/cumulative deduction; PIT edge uncertainty, volatility, liquidity/slippage, correlation/cascade, drawdown and concentration; liquidation buffer; and free margin. It must preserve `gross_notional_usd ~= allocated_margin_usd * effective_leverage`, isolated-paper mode and fail-closed bracket/account binding. Credential binding is blocked and the paper service is held. Current negative LCB/expectancy and restrictive nonpositive-edge tuner policy contract rather than earn high leverage; the observed two positions at 2x prove only that historical runtime was not pinned to 1x.

### 0.4.5 Counterfactual streaming and fail-closed resource holds

The adaptive-productivity crash was not only an output-serialization issue. `adaptive_capital_allocator/counterfactual.py::run_counterfactual_sweep` formerly appended every candidate's feasible configuration rows into process-wide `all_results`, then rescanned that list for configuration-space coverage and hedge accounting. With millions of combinations, exactness was bought with unbounded memory.

Current source replaces cross-candidate row retention with bounded exact accumulators:

- `_empty_feasible_axis_values` / `_accumulate_feasible_axis_values` retain sets for notional multiplier, leverage, margin mode, stop distance, take-profit plan and hedge flag;
- `_empty_hedge_accounting_accumulator` / `_accumulate_hedge_accounting` retain exact counts, maxima, reduction-factor set and missing-field counts;
- theoretical/considered/feasible/pruned counts and pruned reasons accumulate as scalars;
- `candidate_configuration_audit_sample` is capped at 20, while `best_by_signal` retains one selected row per candidate;
- output stamps `feasible_rows_materialized_across_candidates=false` and `feasible_rows_aggregated_streaming=true`;
- missing or invalid `maintenance_margin_rate` no longer falls back to 0.005; `_simulate_candidate` prunes the full candidate grid with `MISSING_OR_INVALID_MAINTENANCE_MARGIN_RATE`. Tests use explicit synthetic maintenance evidence.

The full allocator + adaptive-productivity + Phase-8 lane passed 323 tests. A real production-data probe reconciled 4,592,832 feasible configurations in 3:08.82, peak RSS 1,733,372 KB (~1.65 GiB), zero swap and about 23 MB outputs. Process exit 2 was the expected semantic `NO_GO`: the 1000x status lacked out-of-sample live-grade revalidation. It was neither an OOM nor a promotion result.

Other resource planes remain unsafe. Earlier snapshots showed Redis at 26.52 GB/430,228 keys after 288,016 evictions and later 26.42 GiB/437,559 keys. The final reconciliation sample was about **25.49 GiB** under a 32 GiB `allkeys-lru` limit with AOF disabled. The dominant durable-looking hot objects were not durable or bounded at runtime: `v2:guardian:pit_prediction_observations` was a TTL −1 list with **6,054,941 rows** and `MEMORY USAGE=6,230,529,272` bytes; `v2:trainer:feedback:counterfactuals` was a TTL −1 string with `STRLEN=536,827,021`. No runtime trim, delete or migration was performed. Prior service peaks were adaptive productivity 6.97 GB cgroup plus 6.4 GB swap, Guardian 22.94 GB, persistent trainer 16.13 GB and offline GPU trainer 21.25 GB. Disk inspection also found ~10.9 GB supervisor events, ~1.329 GB pending replay bundle, ~1.104 GB symbol-universe log, large orphan paper-status temporaries and duplicated ~334 MB paper-event files.

The first bounded-hot/durable-archive draft's 62-test suite was correctly release-blocked for archive-before-Redis retry loss and cost-blind counterfactual labels. Current source supersedes those two defects: Guardian uses a SQLite transactional outbox for at-least-once hot-cache delivery and migrates the legacy Redis list in bounded batches before any trim; the counterfactual lane requires explicit after-fee/slippage/funding economics, rejects immutable-identity label rewrites, archives every unique row before selecting/replacing the bounded Redis hot set and verifies readback. The complete publisher+consumer+edge-replay+integration set now passes **87 tests**; this accepts current source mechanics, not runtime migration.

`pit_prediction_counter.py::consume_durable_guardian_pit_archive` makes SQLite stream `v2_guardian_pit_prediction_observations_unique_v1` authoritative and treats Redis only as diagnostic hot cache. It consumes at most 10,000 unique records per invocation under consumer `guardian_pit_prediction_counter_v1`, with cursor/status metadata keys `consumer_cursor:guardian_pit_prediction_counter_v1` and `consumer_status:guardian_pit_prediction_counter_v1` inside the archive. Each clean coverage row must match publisher identity `guardian_pit:` plus the canonical hash of `prediction_id` and `source_redis_key`; content and semantic hashes, sequence/sort key, cumulative archive chain, exact producer/source/schema, explicit UTC clocks, `candle_close == feature_cutoff <= available_at <= decision_time <= generated_at`, strict close-before-decision and final timeframe boundary must verify. All no-live/no-order/no-A+ safety flags must be explicitly false.

Exact invalid-legacy wrappers and content-authentic but semantically dirty historical rows advance the verified source chain/cursor into counted quarantine; they never enter coverage, A+, or live evidence. Malformed non-wrapper rows, identity/content/semantic/sort/chain corruption hard-block. The derived Guardian JSONL sink is append-fsynced, directory-fsynced, read back by absolute path/count/chain and replayed idempotently after append-before-cursor crashes; deletion, tamper or path change blocks. `redis_hot_cache_trim_safe` becomes true only when the consumer cursor/count/chain reaches the exact current archive tip, publisher legacy migration is complete with its cursor covering the observed length, the delivery outbox is empty, and the sink still revalidates. Focused consumer tests pass 18/18. No service used this contract against the real 6,054,941-row list, no source Redis object changed, and the seven repair holds remain until controlled migration plus repeated RSS/write/key-growth burn-in succeeds.

The feed-quality log had a specific high-rate producer. `v2_microstructure_feed_quality_monitor.py::main` formerly serialized the full run payload—including the complete 149-symbol `trust_rows` collection—on every loop. The measured pre-fix writer produced 679,324 bytes in 4.62 seconds, approximately 12 GB/day; active/rotated history totaled about 14 GB. Current `parse_args` defines `--loop-log-mode` as `compact|full|silent` with `compact` default. The deployed service explicitly runs `--loop --loop-log-mode compact --interval-seconds 2 --write-redis --write-status --ttl-seconds 180`.

`_loop_log_payload` emits schema `v2_microstructure_feed_quality_monitor_loop_log_v1` and bounded scalar material: worker/goal and start/finish/run clocks, loop index/interval/max runs, timeframe/exchanges, symbol/trust/low-trust/A+-eligible/feed counts, minimum/maximum trust, Redis/status output counts, Redis availability, live gate and every no-mutation flag. It does not copy the per-symbol evidence. Full authority remains in Redis and status artifacts written before logging. The telemetry-only `low_trust_rows` display uses the row's `adaptive_minimum` or a fixed 0.65 fallback; it is diagnostic threshold debt and cannot authorize allocation. Explicit `full` mode remains capable of recreating the old amplification and must not be used resident without a bounded sink; `silent` does not prove artifact publication.

Thirteen focused CLI tests passed. The only restarted unit was this paper-shadow/no-order monitor; it was active as PID 364367. A post-fix sample added 949 bytes in 4.95 seconds and its row summarized 149 symbols, more than 99.8% below the prior byte rate. Its output continued to declare `places_real_order=false`, `test_orders=false`, `cancel_or_modify_order=false`, `leverage_mutation=false`, `margin_mode_mutation=false` and `transfer_or_withdrawal=false`. This is root-cause and short-sample proof for one stdout writer, not repeated disk/Redis/extension-stability burn-in.

`tools/native_cuda_trainer_logrotate.conf` now binds seven persistent/offline/guard/monitor log and error paths into one block: `size 256M`, `rotate 4`, `copytruncate`, `missingok`, `notifempty`, `compress`, `nodateext`. Versioned and installed `ai-bot-v2-trainer-logrotate.service` run `/usr/sbin/logrotate` with a per-user state file; its persistent timer starts after two minutes and checks every ten minutes. The 7.2 GB active monitor log compressed to ~367 MiB, the previous 6.8 GB archive to ~323 MiB, and the earlier ~187 MiB archive plus ~28 KiB current file brought the gzip-preserved total to ~876 MiB, over 93% lower disk without deleting evidence. `copytruncate` is necessary for append descriptors but creates a copy/truncate observation window; writer continuity, archive readability and state-file ownership remain test items.

The 10.9 GB `agent_supervisor/events.jsonl` remains untouched and blocked for a separate retention contract. A sampled stable-governor loop still added about 112 KB/10 seconds (~0.9 GiB/day). Commit `097fc01b46` changes `agent_supervisor.py::append_event` so repeated `task_skipped_by_non_drift_governor_lock` and `task_not_selected_by_non_drift_governor_lock` observations remain as bounded exact counts/sample in `queue_status.json` but are not appended as durable state transitions. That is a source fix only: the writer was not restarted/deployed, so measured growth continued and the existing file was not truncated. `.vscode/settings.json` excludes `*.jsonl` and `claude_worklog` from watcher/search planes and removed the search rule that forcibly re-included generic `*.json`. This reduces extension enumeration pressure only; it changes no producer, Redis key, canonical artifact or trading authority, and operators must still inspect excluded evidence deliberately.

Stopping services did not hold because the self-healer restarted them. Seven workstation-only `99-codex-repair-hold.conf` drop-ins therefore set `RefuseManualStart=yes`, `Restart=no`, clear `ExecStart` and use `/usr/bin/true` for:

```text
ai-bot-v2-adaptive-capital-productivity.service
ai-bot-v2-continuous-edge-guardian.service
ai-bot-v2-edge-replay-factory.service
ai-bot-v2-native-cuda-trainer-persistent.service
ai-bot-v2-continuous-offline-gpu-trainer.service
ai-bot-v2-trainer-scheduled-pretrain.service
ai-bot-v2-native-ppo-masa-continuous-training-guard.service
```

All seven inspected inactive/dead with zero restarts and `RefuseManualStart=yes`. The scheduled-pretrain and native PPO/MASA continuous-guard timers were also stopped. The separate paper and Guardian one-shots were run directly while their systemd services remained held. No live unit was changed. Missing Guardian freshness keeps A-grade closed. Because the drop-ins are unversioned deployment state, keep them until bounded repeated-service RSS/swap/write/key-growth evidence exists, then version the intended ownership/retention policy before removal.

The controlled Guardian command used `--once --no-redis` and returned process exit 2 as its expected semantic BLOCKED result in 3.57 seconds, peak RSS 35,896 KB and zero swap. It emitted `A_GRADE_HALTED_PERFORMANCE`; anti-metric-gaming was PASSED and the canonical allocation aggregate hash contract was valid. New A-grade entry stayed false while reduce/close/emergency de-risk remained allowed. All 26 leverage recommendations were 1x with `BLOCKED_UNTIL_A_GRADE_EDGE_PROVEN`. Phase-3 coverage contained 99,644 PIT-valid predictions across 135 symbols/five timeframes, but `accepted_row_count=0`: the rows were coverage only, with no countable pre-outcome A-grade holdout rows or passed reverify manifest. Redis publication was skipped by caller. This materially bounds one invocation versus the historical 22.94-GB peak; it does not establish resident Guardian stability or A-grade evidence.

Four installed trainer units also had their path-with-spaces import environment repaired and mirrored under `claude_worklog/systemd/user`:

| Unit | Effective intended `PYTHONPATH` | Runtime boundary at this cut |
|---|---|---|
| `ai-bot-v2-native-cuda-trainer-persistent.service` | `/home/wali/Desktop/AI BOT REBUILD` | inactive under hold |
| `ai-bot-v2-continuous-offline-gpu-trainer.service` | `/home/wali/Desktop/AI BOT REBUILD` | inactive under hold |
| `ai-bot-v2-trainer-scheduled-pretrain.service` | `/home/wali/Desktop/AI BOT REBUILD/v2/backend` | inactive/dead under hold; timer stopped |
| `ai-bot-v2-native-ppo-masa-continuous-training-guard.service` | `/home/wali/Desktop/AI BOT REBUILD` | inactive/dead under hold; failed state reset and timer stopped |

Each `Environment=` value is now quoted as a whole. Effective-environment inspection preserved the embedded spaces, and targeted `systemd-analyze --user verify` exited 0 with no diagnostic attributable to these four definitions. The same verify invocation exposed unrelated installed-unit warnings; this does not certify the unit estate. A correct import root is only launchability evidence: it proves no training row, optimizer/weight delta, checkpoint identity, PPO receipt, held-out edge or promotion state.

The persistent service now explicitly sets `V2_TRAINER_VALIDATION_CHECKPOINT_GUARD=true`; a prior effective override had disabled the guard and could have allowed promotion despite validation-domain regression. `tools/continuous_offline_gpu_trainer_loop.sh` now returns the trainer child's nonzero status instead of `trainer || echo ... continuing`, and the versioned offline unit uses `Restart=on-failure`, `StartLimitBurst=5`, `StartLimitIntervalSec=600`. The repair hold intentionally overrides restart while validation is incomplete. These changes make failure observable; they do not establish a successful training cycle.

### 0.5 Adaptive tuner authority and truthful outcomes

Canonical authority is `cli/v2_adaptive_gate_tuner.py` writing `v2:orchestrator:adaptive_gate_tuning_state`. Current source emits producer `v2.backend.app.cli.v2_adaptive_gate_tuner`, state `v2_adaptive_gate_tuning_state_v4`, policy `v2_adaptive_gate_policy_v4` and publication receipt `v2_adaptive_gate_tuning_receipt_v1`, with exact raw source hashes, manifest, current paper-session identity, admitted/rejected outcome evidence, outcomes cutoff, canonical policy material/hash/ID, generated/available/expiry clocks and a one-hour TTL. Fewer than 20 clean current-session outcomes yields a canonical fail-closed policy.

V4 adds three exact market sources to the manifest:

```text
v2:market:ohlcv_closed:binance:BTCUSDT:1m
v2:market:ohlcv_closed:binance:ETHUSDT:1m
v2:market:ohlcv_closed:binance:SOLUSDT:1m
```

`learn_market_regime` calls `_market_source_analysis` for each raw payload at one aware tuning cutoff. `_market_candle_row` requires exact symbol/timeframe, `is_closed`, `closed_candle`, `candle_closed_confirmed` and `feature_eligible` all true, unique close identity, positive ordered OHLC, nonnegative volume and `candle_close_time <= event_time <= available_at <= cutoff`. Naive strings, unfinished/unavailable rows and malformed values are rejected. Each symbol needs `MIN_FINAL_CANDLES_PER_SYMBOL=20`; its freshest `available_at` must be no older than `MARKET_CANDLE_MAX_STALENESS_CADENCES=3` times `MARKET_CANDLE_CADENCE_SECONDS=60`.

For each sufficient source, the function computes range bps, an isqrt-sized recent-window median, empirical q25/median/q75 and the current empirical percentile. It median-combines the three sources, labels HIGH above empirical q75, LOW below empirical q25 and NORMAL otherwise, then computes the continuous bounded factor `0.70 + (1.50 - 0.70) * empirical_percentile`. Missing/untrusted evidence returns regime UNTRUSTED, factor 1.50 and makes the combined tuner authority fail closed. A read-only probe admitted 100/100 rows for each symbol with no rejects and produced LOW / 0.964. That proves the reader against those snapshots, not publication or consumer propagation of a canonical v4 state.

`services/adaptive_gate_tuning/runtime_tuner.py` no longer shares that writer key. Its compatibility `GATE_TUNING_KEY` resolves to `v2:diagnostic:adaptive_gate_tuning:runtime_tuner_shadow`; schema `v2_adaptive_gate_tuning_shadow_v1` is `authoritative=false`, `may_control_admission=false`, TTL 60, diagnostic only. Its reader consults the canonical key, never its own shadow.

New lifecycle outcomes distinguish three times. `build_close_event` computes economics and stamps `close_event_time`, `outcome_generated_at`, schema `PAPER_CLOSE_OUTCOME_AVAILABILITY_V1`, status `PENDING_LIFECYCLE_PUBLICATION`, but does not claim availability. `_close_position` then calls `capture_close_outcome_availability` after realization and before publication; it requires aware UTC and `close_event_time <= outcome_generated_at <= outcome_available_at`, emits source `PAPER_LIFECYCLE_POST_ECONOMIC_REALIZATION_PRE_PUBLICATION_CLOCK`, status READY, and blocks a naive or impossible seal while retaining the position. Entry-feature `available_at` remains distinct. Carried historical rows are never backfilled. The tuner prioritizes `outcome_available_at`.

`adaptive_gate_tuning_rejection_reasons` is the reusable pure envelope validator. It verifies canonical producer/key/schema/policy/authority and paper-safety flags; paper-session alias/source/current-session identity; publication clock ordering, fixed one-hour TTL and consumer availability/expiry; exact ordered source-manifest hashes and source bindings; canonical policy material/hash/ID and every bound policy value; types/ranges/derived `permissive_authority`, authority/policy status and mandatory fail-closed values; and the publication receipt/hash. `_paper_adaptive_tuning_semantic_validation` wraps it with current-session and consumer clocks and seals `paper_adaptive_tuning_semantic_validation_v1` over state hash, identities, clocks and rejection reasons.

`run_once` uses the raw canonical state only when that receipt is `PASS`. Otherwise it adds `ADAPTIVE_TUNING_AUTHORITY_NOT_VALID` to P0 and passes downstream evaluators an internal `CONSUMER_FAIL_CLOSED_PROJECTION`: 0.80 confidence, loss and side floors; B/A disabled; expectancy floor 0; freeze allowance 0; `permissive_authority=false`. That projection cannot authorize an entry because P0 remains blocked. The semantic receipt/hash/status is embedded in the frozen entry snapshot and revalidated by the final intrinsic contract. `_paper_revocable_control_commit_revalidation` then exact-rereads both tuning and paper-session sources, resolves current identity, reruns semantic validation at reread time and again at `checked_at`, and rejects expiry, session change, semantic failure or byte change.

This closes the identified in-process paper-consumer semantic gap in source. Historical runtime v3 validated with 0 admitted/92 rejected and `CANONICAL_FAIL_CLOSED`. At 04:41:09.475673Z the canonical key published v4: policy version v4, receipt v1, source manifest count 6, 91/92 outcomes admitted, one `PREDICTION_LINEAGE_CONFLICT`, both outcome and market evidence sufficient, NORMAL regime, volatility factor 1.12666667, authority `CANONICAL_EVIDENCE_BACKED_RESTRICTIVE` and policy `EVIDENCE_BACKED_RESTRICTIVE_NONPOSITIVE_EDGE`. This is bounded producer/receipt proof. The paper loop's failed reload/hold means no accepted fill proves entry→allocation→revocable→persisted propagation. Redis ACL/exclusive-writer proof and cross-process fencing remain open.

### 0.5.1 PPO on-policy supply audit

`claude_worklog/codex/CODEX_PPO_ON_POLICY_STARVATION_FINDING.md` retracts an earlier “active PPO uses cost-blind reward” statement and instead identifies PPO starvation. Among 92 current closed rows, `ppo_on_policy_entry_fields_present` is true for 2, false for 42 and missing for 48; only 2 rows have `old_log_prob`. Those two are not trainer-eligible: every stored row lacks the required sampling-mode/distribution fields. `_has_on_policy_ppo_fields` admits 0. Runtime metrics report `ppo_on_policy_rows=0`, `ppo_rows_consumed=0`, `ppo_rows_missing_on_policy_fields=2014`, `ppo_rejected_missing_on_policy_fields=2014`, `ppo_clipped_surrogate_rows=0` and `ppo_objective_used=false`. Outcome-supervised training is distinct: 2,014 rows, 1,609 batch rows and `outcome_supervised_update_used=true`; effective serving mode remains `INFERENCE_ONLY`.

At the time of the old-generation recount, the paper predicate at `_entry_is_exact_on_policy_sample` required:

```text
entry_sampling_mode == CATEGORICAL_SAMPLE
entry_distribution_contract == RAW_LOGITS_SOFTMAX_V1
entry_log_prob is finite/present
entry_policy_value is finite/present
```

Otherwise the old strategy-supply path stamped `STRATEGY_SUPPLY_ACTION_NOT_SAMPLED_FROM_CUDA_POLICY`. Trainer `_has_on_policy_ppo_fields` imposed additional old-value/reward/done/rollout/action/distribution checks. Its checkpoint/model fingerprint had to identify the exact served artifact. The sole fingerprint present was a static paper-owner constant, not a served checkpoint/content hash. Consequently the verified result is zero genuine PPO rows admitted or consumed in that evidence window; the two legacy-looking rows do not prove plumbing completeness or an optimizer step. This paragraph describes the observed generation, not the current source contract below.

The handoff's fixed exploration fraction and minimum batch `N` are not accepted. They conflict with the adaptive mandate and could create low-edge behavior for counter supply. A valid paper-only sampler must derive exploration capacity from PIT policy uncertainty and clean behavior-coverage deficit, then intersect it with current after-cost edge, liquidity/regime, risk, margin and all hard gates. It must execute the actual sampled action without strategy override and persist an immutable decision receipt containing the exact served-checkpoint/model-content fingerprint plus raw distribution/action/log-prob/value/rollout identity. It must remain non-A+/non-live and demonstrate causal no-leakage training plus positive purged held-out after-cost evidence. Off-policy correction still requires the complete behavior distribution.

**Current source plan.** `on_policy_behavior.py::adaptive_on_policy_lane_plan` emits `v2_adaptive_on_policy_paper_lane_plan_v1`. Before candidate scoring it requires a passing paper margin invariant, `paper_only=true`, `routes_to_live=false`, `places_real_order=false`, positive `margin_base_usd` and `free_margin_after_buffer_usd`; the entry-freeze snapshot must explicitly allow new paper entries while denying live/order behavior. Margin headroom is `min(1, free_after_buffer / margin_base)`. Each candidate must be `TRAINABLE`, prove final candle state and aware ordering `candle_close_time <= feature_cutoff <= available_at < decision_time` plus independent `candle_close_time < decision_time`, bind symbol/timeframe, exact served-policy fingerprint, real checkpoint generation, 64-hex weight/evidence digests and `exact_cost_provenance_valid=true`, expose fitted calibrated directional confidence in `[0,1]`, provide valid raw logits, and have at least one strictly positive directional edge after the exact round-trip cost.

For each eligible candidate the plan computes normalized raw-policy entropy, profitability uncertainty `1 - abs(2p - 1)`, positive-edge quality `positive_edge / (positive_edge + abs(cost))`, and the fourth root of their product with margin headroom. Credit is `adaptive_score / (1 + adaptive_score)`. The sample request is `floor(carry_in + sum(candidate_credit))`; candidates rank by descending adaptive score and then a canonical identity hash. A multi-candidate cycle caps samples at `candidate_count - 1`, structurally reserving at least one ordinary lane. A one-candidate cycle samples only after its integer ordinary-lane credit has accumulated, so ordinary and exploration supply alternate rather than collapse. Fractional carry is capped to `[0,1]`. The plan hashes its complete inputs and output and explicitly records `market_static_sampling_threshold_used=false`, `paper_only=true`, no live route and no real order.

The canonical plan output and each candidate audit expose these replication fields:

```text
plan = schema_version, formula, input_hash, safety_gate_passed,
       safety_rejection_reasons, candidate_count, eligible_candidate_count,
       requested_sample_count, selected_sample_count, selected_indices,
       ordinary_lane_reserved_count, structural_ordinary_lane_reservation,
       market_static_sampling_threshold_used, token_budget_before_selection,
       carry_in, carry_out, single_candidate_ordinary_credit_in,
       single_candidate_ordinary_credit_out, candidate_audit, paper_only,
       routes_to_live, places_real_order, plan_hash
candidate_audit[] = index, symbol, timeframe, feature_tensor_id, feature_cutoff,
       available_at, candle_close_time, candle_closed_confirmed, decision_time,
       row_classification, eligible, rejection_reasons,
       policy_entropy_normalized, profitability_uncertainty,
       profitability_confidence_calibrated, confidence_candidate_action,
       expected_move_bps, round_trip_cost_bps, raw_policy_logits_hash,
       positive_after_cost_edge_bps, positive_edge_quality,
       paper_margin_headroom, adaptive_score, candidate_token_credit,
       rank_tiebreak_hash
```

`model_parameter_fingerprint` hashes the exact in-memory object used for the forward pass. Its SHA-256 domain begins `v2_in_memory_served_policy_parameters_v1\0`, includes `model_id`, then—on Torch—each sorted `state_dict` name, dtype, shape and contiguous CPU tensor bytes. CPU fallback packs every finite fallback weight as a network-order double. Missing/non-finite parameters raise rather than invent identity. This content fingerprint is stronger than the architecture-derived `model_id`; current receipt admission separately requires a 64-hex `checkpoint_weight_sha256`, checkpoint-evidence digest and verified checkpoint identity.

Three source/runtime residuals matter before acceptance. First, plan carry and single-candidate ordinary credit live only in process-global `_ADAPTIVE_ON_POLICY_LANE_STATE`; restart resets both to zero, and separate trainer authorities do not share or fence the budget. Second, exact sampling now rejects the ordinary fixed-age/fallback adapter and requires `v2_exact_adaptive_cost_provenance_v1`. It hashes and rederives `paper_cost_fee_schedule_evidence_v1` (`CONFIGURED_TAKER_FEE_BPS_PER_SIDE`, rate and source) and `paper_cost_notional_configuration_evidence_v1` (reference notional and source), closing configured paper/shadow source identity. Actual exchange-account fee tier, discounts and maker-versus-taker applicability remain unproved for live transfer, not for the paper exact lane. Third, `market_static_sampling_threshold_used=false` describes plan selection only: publisher paper eligibility still applies configured minimum data coverage, calibrated confidence and absolute after-cost edge. The deployed cost producer observed on 2026-07-18 emitted its old schema with null adaptive fields, so current exact source correctly has no usable runtime cost proof.

`build_exact_cost_provenance` requires exact keys `v2:costs:round_trip_bps:<SYMBOL>` and `v2:orderbook:features:binance:<SYMBOL>`, estimator `adaptive_cost_model_v1`, paper-only scope, `FRESH_ORDERBOOK`, live spread, depth-observed impact, no floor/fallback and continuous order-book sequence. It embeds the entire estimator payload and nested order-book payload, hashes both, matches schema/symbol/clocks and proves

```text
orderbook event <= orderbook available <= orderbook generated
                <= cost generated <= cost available
                <= consumer observed <= adaptive expires
round_trip_cost_bps = 2*taker_fee_bps_per_side
                    + spread_bps
                    + 2*impact_per_side_bps
```

Spread is matched to the embedded payload. Impact is recomputed either from embedded exchange impact/reference notional or from thin-side depth and half-spread. Adaptive expiry uses `RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD`, at least three source intervals and a TTL no longer than remaining source life. Three intervals normally require four distinct availability clocks after producer start.

**Current source receipt.** A selected row builds `v2_positive_edge_on_policy_behavior_receipt_v1` with sampling mode `CATEGORICAL_SAMPLE`, distribution `POSITIVE_EDGE_MASKED_RAW_LOGITS_SOFTMAX_V1`, action source `NATIVE_CUDA_POLICY_CATEGORICAL_SAMPLE` and mask source `PIT_AFTER_COST_POSITIVE_ENTRY_ACTION_MASK_V1`. Softmax requires exactly the seven finite logits ordered `hold`, `long`, `short`, `close_long`, `close_short`, `reduce`, `hedge_reserved_fail_closed`, plus a nonempty seven-element mask. The mask always retains HOLD/index 0, retains LONG/index 1 only when `expected_move_bps - round_trip_cost_bps > 0`, and retains SHORT/index 2 only when `-expected_move_bps - round_trip_cost_bps > 0`; all other action logits are masked. `secrets.randbelow(2**53)` supplies a uniform integer whose ratio to `2**53` drives categorical selection, with the last positive action as the floating-point tail fallback. The canonical receipt hash requires and covers symbol/timeframe, prediction/checkpoint ID, exact served fingerprint, weight/evidence digests, feature tensor/vector, strict finality/clocks, plan hashes, raw/masked distribution, sampled action/probability/log-probability, value, expected move, both directional nets and the complete exact-cost envelope. It remains paper-learning-only, non-A+ and non-live.

```text
receipt = schema_version, prediction_id, decision_time, feature_cutoff,
          available_at, candle_close_time, candle_closed_confirmed,
          symbol, timeframe, feature_tensor_id, feature_vector_hash,
          model_id, checkpoint_id, checkpoint_weight_sha256,
          checkpoint_evidence_digest, served_policy_fingerprint,
          behavior_policy_sampling_mode, behavior_policy_distribution_contract,
          behavior_action_source, behavior_action_mask_source,
          on_policy_sampling_selected, on_policy_sampling_lane,
          on_policy_sampling_plan_hash, on_policy_sampling_plan_input_hash,
          on_policy_sampling_evidence_class,
          on_policy_sampling_counts_as_a_plus_evidence,
          on_policy_sampling_routes_to_live, action_labels, raw_action_logits,
          raw_action_probabilities, behavior_action_mask, action_probabilities,
          selected_action_index, selected_action, selected_action_probability,
          selected_action_log_prob, policy_value, expected_move_bps,
          round_trip_cost_bps, cost_provenance,
          cost_source_payload_sha256, long_after_cost_bps, short_after_cost_bps,
          positive_edge_required, sample_draw_u53, sample_draw_denominator,
          strategy_supply_hypothesis, paper_only, routes_to_live,
          places_real_order, receipt_hash
```

**Durability and propagation.** Redis is a lookup/cache plane, not the only durable receipt authority. `durable_behavior_receipt_archive.py` owns blob schema `v2_durable_behavior_receipt_archive_v1`, event schema `v2_behavior_receipt_lifecycle_event_v1` and default root `.local_data/v2_native_trainer/durable_behavior_receipt_archive`. A blob path is `receipts/<hash[0:2]>/<hash[2:4]>/<receipt_hash>.json`; lifecycle files are `lifecycle/<hash[0:2]>/<receipt_hash>/<event_hash>.json`. Canonical JSON is create-or-identical, fsynced, directory-fsynced and read back. A per-receipt `fcntl.flock` spans lifecycle read/check/write/readback; multiple stored events of one type are corruption and fail closed. Every blob rederives both archive content SHA and embedded receipt hash. Every event rederives its content hash and is immutable/paper-only/non-live/non-order.

The enforced event type order is `PUBLISHED`, `ENTRY_ACCEPTED`, `OUTCOME_FINALIZED`, `TRAINER_CONSUMED`; later types require all earlier types. `PUBLISHED` binds prediction/checkpoint/archive identity. `ENTRY_ACCEPTED` binds fill/prediction/symbol/timeframe and the actual entry fee-schedule SHA. `OUTCOME_FINALIZED` binds outcome ID/digest and `ppo_consumption_update_key`. `TRAINER_CONSUMED` binds that same 64-hex update key. Duplicate identical identity is idempotent; a same-type binding conflict fails closed.

`V2HybridPredictionPublisher.publish_prediction` considers only a valid directional exact receipt whose paper and orchestrator gates already pass. It must archive/read-back the blob and append `PUBLISHED` before immutable Redis write at `v2:trainer:hybrid_cuda:on_policy_receipt:<receipt_hash>` with `ex=None`; archive or Redis failure clears exact paper/orchestrator/prediction/risk eligibility. The Redis record has no fixed expiry, and an identical retry verifies rather than mutating it. The common `BEHAVIOR_POLICY_LINEAGE_FIELDS` plus `DURABLE_RECEIPT_LINEAGE_FIELDS` carry proof through prediction, orchestrator, risk, accepted fill, position, close outcome and feedback; strategy supply strips it. Paper entry re-verifies archive/hash/`PUBLISHED`, matches the materialized entry fee evidence SHA to the receipt, then appends `ENTRY_ACCEPTED`. Close feedback re-verifies archive, `ENTRY_ACCEPTED` and fee binding; builds `v2_exact_ppo_finalized_outcome_v1` with exact gross/component/funding/provenance/clock arithmetic and reward `realized_net_pnl_bps/100`; and appends `OUTCOME_FINALIZED`. PPO rejects `done != true`, negative/fractional trajectory index, reward/digest mismatch and sampled/corrupt/consumed rows falling into supervised mode.

The last hook is not integrated: after `v2_exact_ppo_consumption_ledger_v3` durably records disposition, trainer must append `TRAINER_CONSUMED` for the identical update key. Until then `v2_behavior_receipt_lifecycle_status_v1.retention_required=true`. No archive GC exists, so blobs are never physically deleted today; this is safe against premature removal but unbounded on local disk. The hashes are tamper-evident/self-authenticating, not keyed authentication, off-host backup or restore proof.

```text
BEHAVIOR_POLICY_LINEAGE_FIELDS =
  action_labels, raw_action_logits, raw_action_probabilities,
  action_probabilities, selected_action_index, selected_action_probability,
  selected_action_log_prob, policy_value, behavior_action_index,
  behavior_action, behavior_action_mask, behavior_action_source,
  behavior_policy_sampling_mode, behavior_policy_distribution_contract,
  behavior_policy_fingerprint, behavior_policy_checkpoint_hash,
  behavior_policy_receipt, behavior_policy_receipt_hash,
  behavior_policy_receipt_key, behavior_policy_receipt_write_success,
  on_policy_action_receipt_valid, on_policy_sampling_selected,
  on_policy_sampling_requested, on_policy_sampling_plan_hash,
  on_policy_sampling_plan_input_hash, on_policy_sampling_lane,
  on_policy_sampling_evidence_class,
  on_policy_sampling_counts_as_a_plus_evidence,
  on_policy_sampling_routes_to_live, ppo_on_policy_entry_fields_present,
  ppo_on_policy_ineligible_reason, entry_policy_fields_source
```

**Source repair/runtime boundary:** final scoped checks passed 73/73 combined trainer/confidence/regularization, 16/16 exact-receipt cases including a real clipped optimizer delta and entry→position→close→feedback propagation, five selected paper strategy/non-leak cases, 8/8 mode-collapse integration and all 54 strategy-router cases. Compilation, focused format/lint, undefined-name lint and scoped diff checks passed. The repair has not been deployed or exercised as a controlled held-service burn-in. Until runtime evidence is accepted, this section's verified 0/0 diagnosis and fail-closed operating decision remain authoritative; source tests are not A+/live permission.

The workstream's read-only runtime handoff confirms old code remained active on the publishing/status plane: 745 predictions, zero publication failures, 2,014 outcome-supervised rows, PPO admitted/consumed/clipped rows 0/0/0 and `ppo_objective_used=false`. Serving-policy validation edge was −1.39286013 bps with lower bound −2.25532918 bps, and the composed gate remained HALTED. Paper margin was PASS; MANA and ARB each showed 2x. The root did not independently reproduce the literal Redis reads, so these are handoff-reported observations, not a new controlled probe. They do not prove deployment, earned leverage, PPO weight updates or promotion.

### 0.5.2 Ridge champion/challenger is fail-closed with zero evaluable runtime rows

`native_trainer/model_edge_recovery_challenger.py` now owns schema `v2_model_edge_recovery_champion_challenger_v2`, validity policy v2 and model source `V2_MODEL_EDGE_RECOVERY_TRUSTED_REPLAY_RIDGE_V2`. It is paper-only and local: even a successful challenger is `B_GRADE_EXPLORATION_PAPER`, `paper_fill_allowed=false`, A-grade promotion false, live gate `blocked_human_only` and checkpoint ID null.

Dataset admission requires:

```text
feature_cutoff <= available_at <= decision_time       # all aware UTC
candle_closed_confirmed == true
latest_unclosed_kline_excluded == true
mtf_snapshot_id present
durable snapshot content_sha256 recomputes exactly
no FUTURE_LABEL_PREFIX feature
explicit PIT fee_bps, expected_slippage_bps, expected_funding_bps
```

The action-specific cost policy is `fee + slippage + abs(funding)` on both LONG and SHORT; a legacy static cost is diagnostic only and cannot fill a missing component. Future labels use finalized available candles at 5m/15m/1h/4h, with 15m as the target and actual maximum label availability. Features and normalization are fit on training only, hyperparameters on validation only, and the decision-time-grouped 70/15/15 duration split applies a four-hour embargo. Final evaluation uses the untouched holdout and nested decision-time/symbol clustered bootstrap.

Sixteen focused tests and scoped lint passed. A 200-snapshot real archive probe completed in 0.19 seconds at 29,208 KB peak RSS and nevertheless yielded zero evaluable rows. Rejections were exact: `ACTION_SPECIFIC_FEE_EVIDENCE_MISSING_OR_INVALID=145`, `ACTION_SPECIFIC_SLIPPAGE_EVIDENCE_MISSING_OR_INVALID=145` and `LATEST_UNCLOSED_KLINE_EXCLUSION_UNPROVEN=55`. The four-hour purge left train/validation/untouched-holdout at 0/0/0; other blockers included incomplete action-specific cost coverage and insufficient distinct decision-time groups. Thus there is no model, after-cost edge claim, enabled challenger or paper permission, and the claimed +30-bps improvement remains unproven. Routes/live/checkpoint writes were unchanged and no service restart occurred.

The source retains fixed `DEFAULT_RIDGE_LAMBDAS=(0.1,1,10,100,1000)`, discrete prediction thresholds through 50 bps, a 32-feature cap, 50-bps target clip, 300-trade/3% validation-supply defaults, 400 bootstrap replicates and a 0.05 LCB quantile. These must be classified/calibrated as evidence or safety policy; they do not make the result adaptive merely because model fitting is data-driven.

### 0.5.3 Action-conditioned profitability confidence and checkpoint-bound calibration

Current source replaces the ambiguous scalar confidence head with schema `v2_per_directional_action_profitability_head_v1` and ordered actions `("long", "short")`. Its current label contract is `P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2`: for the action fixed at decision time, the target is derived only from recomputed USD economics,

```text
recomputed_gross_pnl_usd = side_sign
                         * (exit_price - entry_price)
                         * closed_quantity
recomputed_net_pnl_usd = recomputed_gross_pnl_usd
                       - entry_fee_usd - exit_fee_usd
                       - entry_slippage_usd - exit_slippage_usd
                       + funding_pnl_usd
recomputed_net_pnl_bps = recomputed_net_pnl_usd
                       / close_specific_entry_notional_usd * 10_000
target = 1 iff recomputed_net_pnl_usd > 0
```

The target builder requires selected action/side agreement, positive entry/exit prices and closed quantity, aware `candle_close <= feature_cutoff <= available_at < decision_time < final outcome` ordering and MASA cutoff no later than PPO decision. It requires `PAPER_ROUND_TRIP_CLOSE_COST_V1`, formula `realized_gross_pnl_usd - entry_fee_usd - exit_fee_usd - entry_slippage_usd - exit_slippage_usd + funding_pnl_usd`, rate scope `PER_SIDE_BPS_APPLIED_TO_CORRESPONDING_NOTIONAL`, entry basis `PAPER_ENTRY_COST_BASIS_V1`, allocation `PRO_RATA_BY_CLOSED_QUANTITY_WITH_FINAL_CLOSE_REMAINDER`, complete entry/exit provenance and fallback=false. It rederives entry/exit notionals, allocation fraction/quantities, each per-side bps rate and causal exit-slippage availability. Every gross/net/fee/slippage/funding alias is an equality check only. Missing, nonfinite, conflicting or unit-ambiguous evidence fails closed. HOLD is excluded from fitting and returns zero/unfitted.

The network emits two sigmoid probabilities. Inference selects the probability indexed by the chosen LONG/SHORT and publishes both directional raw/calibrated records for diagnosis. It no longer uses `max(policy_probability, confidence_head)`: action selection probability is not profitability probability. The CPU algebraic fallback has no profitability head and therefore emits zero/unfitted confidence instead of relabeling its policy score.

Calibration schema `v2_profitability_confidence_calibration_v2` uses fit partition `PURGED_TRAIN_ONLY`. V1 states intentionally normalize to unfitted because their label economics can no longer be trusted under V2. The trainer builds action-conditioned targets only from the label-purged chronological training partition, fits temperature there, records separate LONG/SHORT sample counts, train Brier/ECE before/after, row digest and the post-training model-parameter fingerprint, and reports `validation_rows_used=0`. `set_confidence_calibration_state` rechecks that fingerprint against the current weights; any later weight change makes the state unfitted. The state travels inside NPZ format v2 and the checkpoint manifest beside the exact weights. Environment/file temperature overrides are never adopted. The old external fitter is retained only as a compatibility command that returns `BLOCKED_EXTERNAL_CALIBRATION_BYPASS_DEPRECATED` and never reads rows or writes/adopts state.

Legacy NPZs without the exact two-action head schema/action order raise `ConfidenceHeadCheckpointIncompatibleError`; the checkpoint manager reports the load failed and does not partially restore or broadcast a legacy scalar across opposing actions. A nominally fitted checkpoint calibration missing its model fingerprint loads unfitted. Historical 35/66/1 and initial V2 12/15/36-of-39 results remain chronological evidence in the command ledger; they do not describe the final integrated source test state, which is recorded in the later supersession entry.

`confidence_promotion_decision` emits `v2_checkpoint_bound_confidence_promotion_gate_v1`. It rederives candidate/state/metric fingerprint equality, purged-fit/untouched-validation digest disjointness, zero validation rows used in fit, label semantics and global/LONG/SHORT count equality. For every scope it checks point Brier/ECE and recomputes paired per-row Brier deltas, mean, sample standard error and one-standard-error upper bound; it also recomputes ECE leave-one-out deltas, jackknife standard error and upper bound. A scope passes only when both uncertainty upper bounds are nonpositive. There is no configured market row threshold, but `n >= 2` is the mathematical identifiability minimum. The decision explicitly sets `serving_authorized=false`; it is necessary, never sufficient.

This closes the known source label forgery, field-drop and point-metric-only promotion gaps, and `run_hybrid_trainer_cycle` now invokes the gate. It still does not establish trainer liveness because no held runtime has demonstrated nonzero eligible V2 targets, both-direction fit, untouched-forward uncertainty, compatible promotion, prediction distribution, A+ grade or 1000x result.

### 0.5.4 Trainer checkpoint retention and runtime-truth repairs

`checkpoint_retention_status` formerly included every file in the model directory, so `checkpoint_retention_manifest.json` could select itself as `latest_checkpoint`. It now considers only `v2_hybrid_ckpt_*.json` and `v2_hybrid_ckpt_*.weights.npz`, recalculates remaining bytes after deletion and excludes control/status files. Current checkpoint source writes NPZ plus manifest under an exclusive `flock`, fsync/atomic replacement and create-or-identical semantics. Semantic ID `v2_hybrid_ckpt_<model8>_<parameter16>_<state12>` binds model, full parameter fingerprint and state digest; state includes calibration and `v2_hybrid_checkpoint_evidence_v1`. The manifest binds lineage role, parent identity, ordered PPO update keys, partition digest, checkpoint-evidence digest, NPZ byte SHA/size and calibration/parameter semantics.

Loading scans manifests fail closed: corrupt metadata cannot silently fall back to an older artifact. Every historical manifest can be verified without mutating a serving model. `_resolve_weight_path` ignores manifest-controlled paths and permits only the exact manager-owned `model_dir/{checkpoint_id}.weights.npz`, preventing external NPZ substitution. Same semantic state is create-or-identical, not metadata overwrite. `checkpoint_retention_status` now emits `native_cuda_trainer_checkpoint_retention_manifest_v2`: it scans serving/candidate/rejected stores; pins active serving, latest candidate, any artifact whose consumed keys intersect a pending SQLite claim and the ledger/WAL/SHM; deletes only complete unpinned pairs; and pins every rejected artifact if claim state is unreadable. Deployed rollover/restart proof remains open.

Outer runtime documents retain schema `native_trainer_runtime_status_v1`; merging `online_learning_global_readiness_override_v1` no longer overwrites that identity. A manual cycle reports `cycle_process_pid`/`cycle_process_active` separately from systemd `service_pid`/`service_active` and can no longer make a held service look active merely because the probe process exists. `trainer_process_status` and `cuda_inference_status` are derived from observed service/cycle and CUDA fields; absence becomes INACTIVE/`BLOCKED_NO_CUDA_INFERENCE_EVIDENCE` instead of hardcoded ACTIVE. A later status probe can recover checkpoint identity through the complete-artifact rule above.

These repairs correspond to commits `1db7a9fee1`, `aae14956e4`, `1be4e78cdd`, `dd275e5e4c` and `da8b6a44e3`. They are not deployment/burn-in proof. The four trainer services remain held inactive/dead and both trainer timers remain stopped.

### 0.5.5 Trainer adversarial liveness and semantic blockers

The trainer verdict remains **TRAINER NOT READY**, but the negative probes below are a historical reproduction checkpoint. They motivated later helper/source repairs and must not be repeated as current helper behavior. The current source boundary is:

| Component | Current low-level contract | Remaining release boundary |
|---|---|---|
| Exact finalized outcome | `v2_exact_ppo_finalized_outcome_v1`; action/side/price/quantity gross recomputation; every entry/exit fee/slippage/funding component; exact paper versions/formula/rate scope; partial-close allocation; fallback=false; strict clocks; reward=`net_bps/100`; complete canonical digest | Runtime must produce nonzero exact rows; receipts are immutable with no fixed expiry |
| PPO eligibility/cache | `done is true`; nonnegative integer trajectory; exact finalized digest/reward; sampled/corrupt/consumed rows cannot become supervised; `v2_trainer_full_ordered_tensor_cache_digest_v1` covers ordered features, masks, targets, clocks and trust rows | Scarce/latest PPO may still be validation-only; no integrated runtime optimizer supply |
| Candidate progress | `v2_non_serving_candidate_progress_gate_v1`; PIT-safe untouched validation, real optimizer/delta, loss and comparable edge-LCB non-regression, strict improvement; `serving_authorized=false` | Main cycle now invokes it; controlled cold-start accumulation is unproved |
| Exact consumption | update key `v2_exact_ppo_consumption_update_key_v1`; ordered partition `v2_exact_ppo_training_partition_v1`; SQLite `v2_exact_ppo_consumption_ledger_v3`; WAL/FULL; boot/PID/start owner; claims; optimizer write-ahead fence; artifact reconciliation; ambiguous dead post-fence consumption | Main cycle now calls claim/fence/record/startup reconcile; no crash-injected held cycle; chain is tamper-evident, not authenticated |
| Receipt lifecycle | fsynced content-addressed `v2_durable_behavior_receipt_archive_v1`; immutable `v2_behavior_receipt_lifecycle_event_v1`; PUBLISHED/ENTRY/OUTCOME/ TRAINER order; exact fee/outcome/update-key binding; no-expiry Redis cache | Source reaches OUTCOME only; append TRAINER only after durable ledger disposition; no GC/capacity/backup/burn-in proof |
| Checkpoint generation | semantic state ID; full parameter/NPZ SHA/evidence; candidate/rejected/`VERIFIED_SERVING_POLICY`; exact manager-owned path only; every artifact non-mutating verification | Main cycle performs role transition and serves only verified prior/promoted policy; controlled retention/restart proof absent |
| Confidence promotion | `v2_checkpoint_bound_confidence_promotion_gate_v1`; purged-fit/untouched-forward digests; global/LONG/SHORT same-row Brier/ECE; paired Brier one-SE and ECE jackknife one-SE non-regression; no configured market sample threshold | Main cycle calls it; runtime target/fit/reliability counts are unproved |
| Adaptive cost | `v2_exact_adaptive_cost_provenance_v1`; embedded/hashes order-book source; strict clocks/sequence/adaptive expiry; recomputed spread/depth/impact/total; hashed/rederived configured paper fee and reference-notional evidence; no fallback | Actual exchange-account fee authority remains required before live transfer; deployed producer is old schema; restart plus four-clock burn-in required |

`run_hybrid_trainer_cycle` now integrates the lifecycle: separate stores, startup reconciliation before dead-claim recovery, consumed-row removal, verified-serving/non-serving/fresh parent choice, fixed-point claim plan, optimizer fence, candidate/confidence/serving decisions, candidate/rejected/serving artifact disposition, ledger record and serve-only-verified restore. Decision time uses `_utc_iso_microseconds()`. The runtime evidence is nevertheless still old PPO 0/0 because held services have not exercised this generation.

Other open debt is deliberately not hidden: archive `TRAINER_CONSUMED` is not appended after durable ledger disposition and the archive is physically unbounded; `_ADAPTIVE_ON_POLICY_LANE_STATE` is process-local; actual exchange-account fee tier/discount/maker-taker authority is not independently authenticated for live transfer; the deployed cost key is old; downstream coverage/confidence/edge gates remain static inventory; and no controlled trainer service has generated a compatible serving checkpoint or positive untouched after-cost edge. Configured paper/shadow fee and notional identity is already hash-bound and rederived and is not listed as a paper blocker. The former 0.25-bps exit-slippage minimum is also gone: observed exit half-spread is used exactly; configured reserve applies only when spread evidence is missing, sets fallback and cannot qualify as exact PPO economics.

The following table records the **historical pre-mitigation probes** preserved for audit chronology:

| Severity | Low-level path | Reproduced behavior | Required invariant before release |
|---|---|---|---|
| P0 | `runtime.py` cycle construction/load/train/promotion at approximately lines 362–407, 520–544, 751–754 and 796–843 | Each cycle creates a model and loads the latest compatible serving checkpoint. If none exists, a fresh candidate must already pass positive PIT validation mean edge and positive LCB. `VALIDATION_POLICY_EDGE_NONPOSITIVE` rejects the candidate and no separate durable non-serving candidate lineage/checkpoint remains to accumulate later learning. This can deadlock cold start indefinitely. | Separate immutable serving generation from a durable candidate-training generation; train and checkpoint the candidate without serving it; accumulate only clean PIT rows; promote atomically only after its untouched evidence passes; restore serving independently after rejection/crash. |
| P0 | feedback/replay load → `_has_on_policy_ppo_fields` → `V2HybridPPOTrainer.train`; metric `ppo_rows_consumed=len(ppo_rows)` near `ppo_trainer.py:678` | There is no durable receipt/outcome consumption journal keyed by immutable feedback/receipt/rollout identity. A row that remains eligible can be loaded and credited again in later cycles; the metric reports list length, not unique exactly-once or explicitly versioned repeated use. | Persist an idempotent consumption transaction with dataset/checkpoint generation, receipt/outcome hashes, optimizer-step identity and committed status; replay after crash without double credit; expose unique/duplicate/retry counts. |
| P1 | `_chronological_purged_split` after PPO-first assembly | A direct three-row probe put `sole_ppo_latest` wholly in validation while `replay_early` and `replay_mid` formed training. The split correctly stayed PIT-safe, but the optimizer received no PPO row. | Design a PIT-safe supply/split policy that preserves untouched validation while separately demonstrating nonzero optimizer PPO supply; never move a future row backward merely to fill training. |
| P1 | `_checkpoint_promotion_decision` | A candidate with `confidence_calibration_fitted=false`, status `CHECKPOINT_CALIBRATION_UNFITTED` and null Brier/ECE still returned `PIT_EDGE_BOOTSTRAP_PASS`. | Promotion must require checkpoint-bound fitted calibration, minimum evidence by action, valid untouched reliability metrics and exact post-fit weight fingerprint; missing evidence fails closed. |
| P1, source-mitigated; runtime proof open | `confidence.py::profitability_target_from_trust_row` plus outcome→feedback→loader enrichment | The pre-V2 probe accepted a claimed positive net despite negative gross and overwhelming costs. Current V2 recomputes `gross_usd - fees_usd - slippage_usd + signed_funding_usd`, derives bps from positive close-specific notional, treats claimed labels as checks and now propagates all unit-explicit inputs through close outcome, feedback and loader. | Preserve the exact unit-qualified fields and arithmetic identity; prove nonzero eligible V2 targets, both-action calibration and deterministic V1 invalidation in controlled held-service data. |
| P1 | `ppo_trainer.py::_ppo_ineligibility_reason` | An otherwise exact row with `done=false`, `trajectory_index=-0.5` and `reward=999.0` returned no ineligibility reason. Presence/finite checks do not prove terminal outcome, nonnegative integer ordering or reward/outcome identity. | Require terminal semantics for closed outcomes, nonnegative integer trajectory index, rollout uniqueness/order, canonical reward derivation and equality to the receipt-bound realized outcome; reject arbitrary overrides. |
| P1 | `build_positive_edge_behavior_receipt` temporal admission | `candle_close_time == decision_time` was accepted. A candle is only available after final close processing; equality does not prove it was final and available before the decision. | Require `candle_close_time < decision_time` in addition to `candle_close_time <= feature_cutoff <= available_at <= decision_time`, with explicit source availability/finality evidence. |
| P1 | train-tensor cache | The cache fingerprint covers only four boundary tokens. Interior row/tensor/target mutation can collide with the same boundary identity and reuse stale tensors. | Hash every ordered admitted row identity, feature vector/mask, target, label availability, schema/order and generation; verify before cache reuse. |
| P1 | confidence temperature fit | One temperature is pooled across LONG and SHORT even though the model has two action-conditioned heads and emits per-action counts. | Fit and validate action-conditioned calibration state, or prove statistically that a shared parameter is warranted on an untouched partition; preserve per-action sufficiency and failure. |
| P1 | behavior/checkpoint identity | `checkpoint_weight_sha256` is optional/pending, architecture-derived checkpoint ID can be overwritten, behavior generation is not independently immutable/reloadable, and the receipt does not bind symbol/timeframe. | Require exact weight hash and immutable generation ID, durable generation manifest, symbol/timeframe plus source universe, and deterministic load/forward reproduction from the receipt. |
| P1 | adaptive lane and cost adapters | `_ADAPTIVE_ON_POLICY_LANE_STATE` is process-local/unfenced. Cost reads use a fixed 600-second age and flat fallback while the receipt records only the numeric scalar. | Persist/fence carry and ordinary-lane credit across all authorities; bind cost source/key/schema/event/generated/available/observed clocks, confidence and fallback reason; replace/classify fixed age/defaults through evidence or immutable safety policy. |
| P1 | publisher supply gates | Config still applies approximately 70% coverage, 0.55 confidence and 4-bps edge minima after the threshold-free plan. | Inventory every threshold, label protocol/safety/operator-policy versus market-static behavior, and derive market-sensitive decision boundaries where it is not an immutable safety constraint. |

The direct probes were intentionally negative and made no runtime writes. They established:

```text
split train:                         replay_early, replay_mid
split validation:                    sole_ppo_latest
split PIT safety/reason:              true / PIT_SAFE_CHRONOLOGICAL_PURGED_SPLIT
equal close/decision receipt:         accepted; checkpoint_weight_sha256=None
pre-V2 contradictory economics target: eligible=true, target=1 (now superseded by V2 fail-closed recomputation)
corrupt terminal/reward ineligibility: None
unfitted-confidence promotion:        PIT_EDGE_BOOTSTRAP_PASS
cold-start negative-edge promotion:   VALIDATION_POLICY_EDGE_NONPOSITIVE
```

Those outputs describe the source at the instant of the probe. Later source rejects equal clocks, missing checkpoint hash, nonterminal/fractional/arbitrary reward, contradictory economics, interior-cache mutation and unfitted/uncertainty-regressing promotion; it integrates candidate, consumption and checkpoint state and persists exact receipts without a fixed expiry. The command ledger preserves both the negative reproduction and supersession. The operational hold remains because runtime eligible rows are zero/unproved, the deployed cost producer is stale and fee/static-threshold/burn-in residuals are open. Release requires the final integrated negative suite followed by a bounded isolated cold-start → non-serving learning → unique optimizer disposition → checkpoint/calibration restore → rejection rollback → promoted serving round trip with exact row/partition/artifact/weight deltas, no reuse, PIT-safe untouched evidence and bounded resource growth.

### 0.6 Exact symbol-filter producer

`v2_direct_orderbook_recorder.py` is the exact filter producer. `_safe_symbol_filter_cache_set` writes shared metadata plus exact `v2:exchange:symbol_filters:<SYMBOL>` keys using public `GET /fapi/v1/exchangeInfo` only as an explicitly authorized metadata fallback. It stamps schema `binance_usdm_symbol_filter_cache_v1`, source/endpoint/writer, source-payload hash, fetched/ingested/available times, 24-hour TTL and paper-only/no-order flags. `_validated_canonical_symbol_filter_cache_payload` requires exact symbol, `TRADING`, USD-M `PERPETUAL`, USDT quote, one each of `LOT_SIZE`, `MARKET_LOT_SIZE`, `MIN_NOTIONAL`, no `NOTIONAL`, finite positive market min/step/max and minimum notional, matching aliases/hash/times and positive TTL. `_canonical_symbol_filter_cache_refresh_due` uses a 15-minute refresh interval.

The paper consumer `_paper_exchange_filter_snapshot` requires that producer contract, uses `MARKET_LOT_SIZE` for its simulated MARKET order, hashes the raw and full cache payload, and carries fetched/available/observed clocks. Final admission rereads the exact key and requires its economic/filter identity unchanged. Initial BTCUSDT/ETHUSDT/SOLUSDT exact keys were observed; a later fetched-time advance on the periodic schedule was not yet proven.

### 0.7 Function/key/schema blast radius

| Surface changed | Direct callers/consumers and mandatory regression |
|---|---|
| `_paper_precycle_current_mark_exposure_snapshot`; `v2:paper:accepted_fills`; `paper_precycle_current_mark_exposure_snapshot_v1` | open lifecycle rows, mark-index evidence, source-fill generation identity, persisted v3 validator, projected loss/drawdown, cycle snapshot, new-entry block, exit continuity, compaction/restart |
| premium-index producer set, WSS unit, `_read_v2_mark_index_evidence`; `v2:market:mark_price:<SYMBOL>` | public-stream/no-mutation scope, 600-message reconnect/universe refresh, source event age versus Redis TTL, event/generated/available/observed ordering, declared cadence, canonical-key priority/fallback selection, V2 source-material hash, mark/index divergence, precycle mark valuation, every candidate symbol's pre-decision coverage and fail-closed reasons |
| `_read_v2_microstructure_trust`; `_derive_allocator_liquidity_score`; `_derive_allocator_regime_score`; `_derive_candidate_correlation_contexts` | trust schema/symbol/timeframe/clocks plus payload-expiry/consumer-TTL debt, finite adaptive minimum/action, complete depth+spread and its fixed adapter, intent-owned regime and fixed label adapter, strict candle timezone/finality/availability, child `paper_correlation_accepted_source_material_v2`/SHA256-V2 contract, aggregate `paper_correlation_aggregate_source_material_v1`/SHA256-V1 contract, closed→generic fallback, every open/same-cycle symbol pair, allocator risk veto, leverage/risk/notional and exploration attribution |
| `build_cycle_reservation_snapshot`; `paper_cycle_reservation_snapshot_v1` | allocator inputs/lineage, dynamic envelope, total/symbol exposure, margin/risk adapters, prior-row v3 replay, candidate commit, final bound material and persistence |
| `build_candidate_commit_receipt`; `paper_cycle_reservation_commit_v1` | accepted-prefix order, allocation aliases, append helper, intrinsic persistence replay, collapse/netting behavior and quarantine |
| `_paper_revocable_control_commit_revalidation`; `paper_revocable_control_commit_revalidation_v1` | seven Redis control roles including paper session, tuning semantic checks at reread/commit clocks, guardian TTL, freeze/current-risk composition, process ownership, final clock, v3 receipt/projection and ledger persistence |
| `_paper_final_admission_point_in_time_contract`; `paper_final_admission_contract_v3` | every component time/hash producer, risk/orchestrator/filter/bracket reread, allocation/cycle/revocable proof, accepted append, lifecycle copy, accepted-fill key, quarantine and feedback eligibility |
| `_paper_adaptive_sizing_runtime_status`, `write_payload`, its Redis/public status or projection/hash/aggregate schemas | source-row publication identity/order/canonicalization, per-row and aggregate hashes, max-five projection bounds, exact all-candidate zero-liquidation/hedge/capital facts, OOS context-only rejection, guardian missing/tamper/omitted-sixth-row behavior, atomic file replacement, file/Redis size, RSS/write rate and canonical-ledger nonmutation |
| `_paper_margin_inputs`; `cross_margin_liquidation_v2`; `paper_cascade_margin_join_v1` | paper-margin row uniqueness/completeness, alias resolution, positive notional/rate, leverage completeness, maintenance/account arithmetic, portfolio-computation suppression, cascade directives, isolated-paper invariant and static shock/beta calibration |
| `symbol_leverage_ceiling`; `_liquidation_safe_max_leverage`; `PAPER_MAX_LEVERAGE`; `calculate_dynamic_risk_envelope`; `_adaptive_leverage_target`; authenticated integer leverage ladder; any leverage environment variable | tier/five-ATR recommendation as mandatory candidate ceiling; favorable-PIT interpolation and adverse/missing contraction; account/environment bracket maximum at total post-fill notional; PIT edge/volatility/liquidity/correlation/cascade/drawdown/margin; liquidation and maintenance; G10 identity; isolated mode; static-threshold inventory; negative-edge behavior |
| `run_counterfactual_sweep`, feasible-axis/hedge accumulators, maintenance fallback or productivity outputs | exact count/axis/hedge parity against materialized reference; bounded audit/best-row retention; missing-maintenance pruning; production-scale RSS/swap/output; semantic exit code; OOS reverify; Redis/list/string growth; systemd hold/self-healer ownership; log/temp retention; no live-service mutation |
| `_loop_log_payload`, `--loop-log-mode`, monitor/logrotate units or `native_cuda_trainer_logrotate.conf` | compact schema/field boundedness; no nested per-symbol rows; authoritative Redis/status advancement; 149-symbol count parity; before/after byte rate; 256MiB/four-archive/ten-minute semantics; `copytruncate` window; archive readability; active writer; `full`-mode misuse; safety flags; paper-only restart scope; no order/leverage/margin mutation |
| Any of the four repaired trainer-unit `Environment=PYTHONPATH` lines or `.vscode/settings.json` exclusions | installed/versioned mirror equality; whole quoted value; effective import root; targeted verify; remaining unrelated diagnostics; hold/failure state; module identity; controlled iteration/checkpoint/weight/PPO/holdout proof; extension load versus deliberate access to excluded evidence |
| `v2:orchestrator:adaptive_gate_tuning_state` or tuner v4/policy/receipt | canonical writer, outcome/session/candle source manifests, 20-row finality and three-cadence checks, empirical quartiles/percentile, 0.70–1.50 factor, entry/preemptive consumer validation, frozen snapshot/hash, revocable reread, allocation lineage and expiry monitoring |
| `on_policy_behavior.py`; `_entry_is_exact_on_policy_sample`; `BEHAVIOR_POLICY_LINEAGE_FIELDS`; PPO receipt/distribution fields; any exploration sampler | plan input/output hashes, carry/ordinary-lane accounting and restart/fleet fencing; margin/freeze/PIT/finality/positive-cost-edge eligibility; exact served-parameter/weight/evidence/symbol/timeframe identity; masked raw-logit distribution, action mask/U53 draw/sample/probability/log-probability/value; complete cost source payload/clock/arithmetic and configured paper fee/notional identity; actual exchange-account fee authority before live transfer; immutable no-expiry receipt; strategy-proof stripping; prediction→outcome propagation; finalized reward; claim/fence/ledger; candidate/rejected/serving roles; causal rollout, PIT purging and held-out after-cost edge |
| `confidence.py`; the two-output confidence head; profitability target/calibration state; NPZ/checkpoint manifest | selected LONG/SHORT action identity; explicit after-fee/slippage/funding net outcome; final outcome/label availability; purged-train-only fit and zero validation use; per-direction counts/records; model-parameter fingerprint and row digest; HOLD/CPU fallback zero-unfitted behavior; legacy scalar-head atomic rejection; predictor/publisher/admission confidence semantics and compatible-checkpoint migration |
| `model_edge_recovery_challenger.py`; its dataset/cost/split/model/status schemas | durable content hash, finality/latest-unclosed proof, exact feature/available/decision clocks, future-label exclusion, explicit PIT fee/slippage/funding, action-specific costs, immutable split IDs/hashes, embargo, holdout nonselection, clustered LCB, B-grade/no-fill/no-A+/no-live boundary and static-grid inventory |
| `checkpoint_retention_status`; `online_learning_runtime_fields`; `build_learning_readiness`; trainer service validation/restart environment | checkpoint-artifact glob/control-file exclusion; complete JSON+NPZ pair; latest/best pinning; remaining bytes; outer runtime schema; manual cycle PID versus systemd PID/liveness; observed CUDA/process truth; validation/promotion guard; child exit propagation; service restart limit; held-service status and controlled burn-in |
| `v2:guardian:pit_prediction_observations`; SQLite stream `v2_guardian_pit_prediction_observations_unique_v1`; Guardian publisher outbox/migration; archive consumer cursor/status and coverage JSONL; `v2:trainer:feedback:counterfactuals`; edge-replay archive/hot-set publisher; supervisor `append_event` | publisher/consumer stable identity parity; unique/occurrence counts, bounded legacy cursor, transactional outbox retry/order; content/semantic/sort/chain/schema/PIT/finality verification; dirty-row quarantine versus corruption hard-block; consumer cursor/count/chain and fsynced sink replay/readback; machine trim gate including migration/outbox; Redis diagnostic role/TTL/memory; explicit fee/slippage/funding label arithmetic and immutable rewrite conflict; active-writer quiescence; migration rollback; source deployment; resident key/file growth; poll observation versus durable state transition |
| `v2:diagnostic:adaptive_gate_tuning:runtime_tuner_shadow` | diagnostic dashboards only; any admission consumer is a defect |
| `v2:exchange:symbol_filters:<SYMBOL>` or cache schema | recorder seed/refresh, TTL/clock/source hash, MARKET quantization, min-notional validation, allocation notional/margin/leverage identity and final reread |

Current source evidence at this cut: **533/533 paper-loop** (prior checkpoints 530 and 526), **331 trainer/PIT**, **480 lifecycle/paper-trade-management**, **207 allocator**, **16 adaptive-tuning** (prior checkpoint 15), **72 recorder/integration**, **92 orchestrator/risk**, **99 preemptive/A+**, and **77 portfolio/microstructure** tests. Compact-status dependents passed **91/91 OOS**, **33/33 Guardian** and **77/77** post-fix preemptive-edge-control tests; margin/cascade passed **13/13** focused cases; compact monitor logging passed **13** focused CLI tests. Allocator + adaptive-productivity + Phase-8 passed **323/323**, superseding the 223-test leverage checkpoint; authenticated bracket selection passed six cases with 531 deselected. Strict Ridge passed 16 focused tests; historical profitability confidence passed 35 focused plus 66 adjacent and one external-fitter refusal. Exact on-policy source repair passed 73 combined, 16 receipt, five selected paper, eight collapse and 54 full-router cases plus static checks. Confidence V2 later passed 12 calibration/proportional plus 15 selected strict-economics tests; a concurrent checkpoint-SHA/confidence aggregate remained 36/39 pending cross-workstream reconciliation. Retention's initial 62-test draft was rejected; its corrected publisher+Guardian-consumer+counterfactual suite now passes 87, including 18 focused consumer cases. The premium-index fix passed 14 focused cases and related lanes. Counts overlap. Tests and bounded probes do not close trainer readiness, V2 confidence-target supply, held-service, Redis/host retention, compatible-checkpoint burn-in or historical-canonical integrity blockers. On-policy controlled runtime burn-in and a controlled retention migration remain pending and are not deployment/A+ claims.

Runtime remains NO-GO: `HALTED_PERFORMANCE`, LCB −47.0423 bps, PF 0.703666, weighted expectancy −7.70099 bps and win rate 0.43478. The paper, Guardian and 4.59-million-configuration counterfactual probes were bounded/zero-swap, and the monitor's stdout/disk amplification is repaired in a short sample. Guardian still admitted 0 economic holdout rows despite 99,644 PIT-valid coverage observations; Ridge admitted 0 trusted rows. Seven research/trainer/replay services remain held, both trainer timers are stopped, Redis contains unexpired ~6.23-GB/~536.8-MB evidence objects and the 10.9 GB supervisor log continued growing because its source repair was not deployed. The 132 historical canonical rows remain non-finite/unhashable/FAIL_CLOSED. The one-shot margin receipt passed with equity $2,985.59472051, used $55.80754736, free $2,929.78717315, buffer $499.52893144, post-buffer free $2,430.25824171 and 2/2 positions accounted, but bracket security was `BLOCKED:CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC`; no leverage binding/mutation/order occurred. No repeated WSS/Guardian/trainer/productivity burn-in, compatible calibrated checkpoint or A+ chain exists. On-policy and corrected retention source checks are green, but old-generation PPO remains 0/0 and no real Redis archive migration ran. Redis fencing/ACL/retention, microstructure expiry/TTL, G11/G12, fixed-threshold debt and model-edge proof remain open. Live is disabled.

## 1. How to use this reference

Three evidence planes must agree:

1. **Source plane:** tracked files and the static atlas.
2. **Deployment plane:** effective installed systemd units/drop-ins, working directories, commands and environments.
3. **State plane:** Redis, disk, model/archive, API, process and provider observations at a specific time.

Do not infer deployment from a unit file in Git or behavior from a service name. Do not infer success from a heartbeat/status write. Do not infer risk approval from an identifier. Do not infer temporal validity from a field called `feature_cutoff` without checking how it was derived.

The exhaustive static atlas covers 9,272 tracked paths, 32,272 Python symbols, 3,334 TypeScript/JavaScript symbols, 693 Swift symbols, 161,112 call references with 38,744 resolved, 25,389 imports with 8,708 resolved, 1,807 contracts, 905 API definition/reference records, 2,918 env keys, 2,040 Redis patterns and 39,538 field names.

Canonical artifacts:

```text
docs/system_audit_2026_master/atlas/
  FILE_MODULE_CATALOG.json
  PYTHON_SYMBOL_CATALOG.json
  PYTHON_IMPORT_GRAPH.json
  PYTHON_CALL_GRAPH.json
  TYPESCRIPT_JAVASCRIPT_ATLAS.json
  SWIFT_SYMBOL_CONTRACT_CATALOG.json
  DATA_CONTRACTS.json
  DATA_CONTRACT_FIELD_REGISTRY.json
  CONFIG_ENV_REGISTRY.json
  REDIS_KEY_USAGE_REGISTRY.json
  API_ROUTE_REGISTRY.json
  ENTRYPOINT_SERVICE_REGISTRY.json
  EXCHANGE_MUTATION_REFERENCE_REGISTRY.json
  CHANGE_IMPACT_INDEX.json
  ATLAS_BUILD_MANIFEST.json
```

`ATLAS_BUILD_MANIFEST.json` is published last as the generation commit marker.
It records source/analyzer provenance and the size/SHA-256 of every staged atlas
artifact; validate the machine catalogs against it before consuming them.

## 2. Repository architecture

```text
v2/backend/app/
  adapters/            external/storage/integration adapters
  api/                 FastAPI v1/v2/auth routes and middleware
  auth/                user store, token, revocation and role logic
  cli/                 hundreds of service/job entrypoints
  composition/         dependency composition/builders
  core/                shared primitives
  domain/              contracts/value/state models
  services/            feature/model/risk/paper/live/business logic
  closed_loop/         automation lease/task state

v2/frontend/           React/TypeScript/Vite application
v2/mobile/             SwiftUI iOS/watch and CLI package
v2/scripts/            deployment/validation scripts
v2/ops/                partial CI/ops scaffolding
tools/                 operational and atlas tooling
claude_worklog/         large automation/evidence/runtime corpus
legacy_reference/       historical legacy system inputs
docs/                   canonical and historical documentation
```

The first-party backend trace found 1,181 application modules and about 423,000 lines. The paper loop and large market API modules are unusually monolithic. Preserved legacy code is not automatically inactive: two deployed CoinAnk units call direct legacy-style scripts.

### Import-root defect

Source mixes `app.*` and `v2.backend.app.*`; active processes use both. With different cwd/PYTHONPATH, Python can load one physical file twice under two module identities, duplicating module globals, locks, caches, classes, registries and import-time side effects. The baseline found eight installed unit files with invalid unquoted path-with-spaces `PYTHONPATH`; four trainer units are now repaired as detailed in 0.4.5, while four unrelated installed units still retain the defect. This narrows but does not close import-root ambiguity.

## 3. Effective deployed topology

At the main operations snapshot:

- 157 installed `ai-bot*` user units;
- 81 running services;
- 36 active timers in the earlier trace and 35 on direct recheck;
- 3 failed services;
- 57 installed basenames absent from versioned unit directories and 33 versioned names not installed;
- 10 failure-masking service wrappers and 83 `Restart=always` declarations;
- duplicate portfolio publisher processes;
- persistent CUDA and continuous offline GPU trainers active concurrently.

The detailed service/timer inventory is in `docs/system_audit_2026_master/components/RUNTIME_PROCESS_AND_DEPLOYMENT.md`.

Core runtime:

```text
providers/exchanges
 → Redis raw/derived market plane
 → native feature/TA/context/snapshot workers
 → persistent native trainer + offline candidate trainer
 → prediction/all-timeframe publishers
 → orchestrator
 → risk gateway records
 → paper trade-management/lifecycle/accounting
 → portfolio/guardian/outcomes/replay/feedback
 → API/public artifacts/web/mobile
```

Effective backend is four Uvicorn workers on `127.0.0.1:8000` from mutable repo `v2/backend`; drop-ins override the older immutable release symlink. Effective frontend is Vite preview on `0.0.0.0:5173`, serving ignored prebuilt `dist`. Public routing is Cloudflare-side external state.

## 4. Time and lineage contract

### 4.1 Canonical meanings

| Field | Meaning |
|---|---|
| `event_time` | Economic/source time the fact occurred. |
| `ingested_at` | Time this system received or first persisted it. |
| `available_at` | Earliest time the exact fact was safe for a consumer. |
| `generated_at` | Time a derived record was computed/published. |
| `feature_cutoff` | Newest information actually represented; preserve per-source/timeframe cutoffs too. |
| `decision_time` | Immutable policy-decision cutoff. |
| `execution_time` | Paper/live materialization or exchange acknowledgment time. |

Required order:

```text
source event/finality → ingestion/availability
all contributing close_time <= decision_time
all contributing available_at <= decision_time
truthful feature_cutoff <= decision_time
MASA feature_cutoff <= PPO decision_time
decision_time <= execution_time
```

`generated_at` is not a substitute for event, available, decision or execution time.

### 4.2 Canonical trust code

Principal modules:

- `services/market_state_integrity/canonical_candles.py`
- `services/market_state_integrity/trust.py`
- `services/market_state_integrity/sample_rejection.py`
- `services/market_state_integrity/scoring.py`
- `services/market_state_integrity/validators.py`

`TRUST_SCHEMA_VERSION` is `pipeline_trust_v3`, with an enforcement epoch. `ACTIVE_TRUST_REQUIRED_FIELDS` includes decision/prediction/MTF/replay IDs, cutoff, availability and all timeframe timestamps. Active flags span prediction/risk/paper/trainer usage.

Canonical candle/aligner code rejects future availability/cutoff, unfinished/missing required candles, gaps/latency and MASA/PPO ordering violations. This is the strongest point-in-time layer.

### 4.3 Temporal gaps

- current Redis enrichment values are merged without all per-source availability/cutoff checks;
- list/REST candle arrays use close time without explicit finality/receipt time;
- provider bridge can accept missing timestamps/stale values;
- MTF scalar cutoff uses the minimum selected close, understating newer information;
- publisher can set top-level decision time to publication time while preserving original separately;
- source availability bits mostly mean a numeric value exists;
- native prediction lineage lacks one canonical execution time until later paper paths.

End-to-end point-in-time safety is therefore incomplete even though canonical candle tests are strong.

## 5. Market/provider ingestion

Source families under `app/cli`, adapters and provider services ingest:

- Binance USDM/COINM klines, aggregate trades, order book and liquidations;
- KuCoin public market state;
- CoinAPI WebSocket/REST;
- CoinAnk derivatives context;
- CoinGlass, Santiment, Moralis, Nansen, LunarCrush, AICoin and public-intel/news sources;
- derived funding/OI/long-short, microstructure and liquidation state.

Current deployment is read-only at these market-data boundaries, but credentialed providers exist. A provider health record must include source event/receipt/availability/generated times, symbol/timeframe, finality, schema/hash, rate/latency and missing/stale reasons. Credential presence is not health.

Typical state families include `v2:market:*`, `v2:orderbook:*`, `v2:microstructure:*`, `v2:liquidations:*`, `v2:features:*`, provider-specific and context keys. Use the Redis atlas for exact producer/consumer sites.

## 6. Candle finality and MTF snapshot

`canonical_candles.py` recognizes explicit closed flags (including WebSocket finality), parses close and availability, and builds the required 1m/5m/15m/1h/4h decision snapshot. `_latest_available_closed_candle_at_or_before` chooses a final available candle no later than decision.

`build_multi_timeframe_decision_snapshot` records selected candle IDs/open/close/availability/event/source/hash and rejection reasons. At lines around 468-473 it currently chooses `min(close_times)` as scalar `feature_cutoff`; this is a known semantic defect if the field means newest information. The full selected-candle vector remains necessary even after correcting it.

The native feature loop’s `_closed_klines`:

- requires explicit closed flags for dict rows;
- rejects dict availability later than decision;
- accepts list rows with at least seven values using the close timestamp at index 6;
- includes rows whose close is no later than decision.

List rows cannot prove the final value’s actual ingestion/availability.

## 7. Native feature pipeline

Primary entrypoint: `cli/v2_feature_pipeline_native_loop.py`.

`run_once`:

1. captures current generation/decision time;
2. reads raw/canonical closed klines;
3. builds market state and derived OHLCV/TA/cost features;
4. reads orderbook, OI, long-short and liquidation evidence;
5. merges A+ context and external V2 features;
6. marks missing/stale core fields and candle finality;
7. constructs a `v2_native_feature_snapshot_v1` payload;
8. adds provider consumer context when available;
9. hashes the payload into a snapshot ID;
10. writes latest, archive and related feature/TA surfaces with TTLs.

Snapshot core fields include symbol/timeframe, feature map/counts, missing/stale flags, finality/open/close, source event/received/available, feature cutoff, decision estimate, external source names/count, cost evidence, live block and generated times.

### Enrichment gap

`_merge_a_plus_context_features` and `_merge_external_v2_features` read latest Redis HTF/cross-asset/regime/tape/TA/liquidation/unified/orderbook/WSDS/microstructure/alternative data and merge numeric fields. They do not preserve and gate a complete source envelope per contributing value before merge. `run_once` then stamps aggregate receipt/availability/generated as current time. Historical/as-of reconstruction can therefore attach present state to older candle context.

Provider context built with a decision time is better, but missing timestamps/freshness rules are not uniformly fail-closed and optional exceptions are swallowed.

## 8. Feature and tensor contract

The authoritative ordered contract is `services/native_trainer/hybrid_cuda_trainer/tensor_builder.py::FEATURE_SPEC`. The 2026-07-16 audited deployment had **477 feature slots**; intended 2026-07-17 source has **446**. The exact ordered-name digest and width are one versioned ABI and must match the checkpoint/replay generation.

Model vector:

```text
current source:
values[446]
|| missing_mask[446]
|| stale_mask[446]
|| source_availability[446]
= 1,784 inputs

historical audited deployment:
four 477-value channels = 1,908 inputs
```

For each feature, the builder resolves prioritized source values, converts finite numeric values, inserts zero only as a placeholder when missing and sets masks. Important caveats:

- truthiness `a or b` fallback can replace a valid zero;
- family-level stale markers may not match every field name;
- availability is numeric presence, not temporal proof;
- current source state cannot safely reconstruct an archived historical tensor unless archived source context is complete;
- tensor/snapshot IDs do not independently encode the full temporal envelope.

Any feature addition/removal/reorder affects snapshot schema, input dimension/order, architecture/checkpoint compatibility, replay/cache, prediction identity, status, tests and every downstream policy. Reorder with unchanged length is still incompatible.

### Parallel snapshot abstractions

Domain feature models under `domain/features/*` and `services/feature_snapshots/*` are distinct from the active native snapshot in the CLI/data loader. API/domain schema names must not be assumed to describe native trainer input.

## 9. Dataset and dirty-sample admission

Principal sources:

- `hybrid_cuda_trainer/data_loader.py`
- `market_state_integrity/sample_rejection.py`
- `native_trainer/feedback_enrichment.py`
- `native_trainer/trusted_replay/dataset.py`
- `native_trainer/trusted_replay/bootstrap.py`

The loader combines fresh prediction examples, trusted replay/backfill/frontier rows and closed feedback. Correct gates reject future availability/cutoff, invalid/unfinalized MTF/replay lineage, missing price targets, non-finite required values, stale mandatory features and explicit quarantine/coverage failures.

Weaknesses:

- high-confidence feedback logic can remove missing-trust rejection reasons;
- optional/cost/schema-evolution masked rows can remain trainable;
- historical REST receipt timing can be fabricated from close time;
- a rebuilt closed-trade path does not uniformly re-run the complete final classifier;
- normal training does not enforce persistent holdout boundaries/IDs.

“Missing masked” is not globally dirty, but temporal/required lineage must never be waived as if optional data.

## 10. Native model

Primary source: `hybrid_cuda_trainer/model.py`.

### 10.1 Architecture

Default source configuration:

- input 1,784 from the intended current 446-feature schema (the audited deployed generation used 1,908);
- hidden width 1,024;
- 3 residual blocks;
- dropout 0.10;
- optional four-block multihead attention off;
- optional GRU temporal encoder off;
- seven action logits;
- scalar value;
- expected move bounded to ±120 bps;
- two sigmoid action-conditioned profitability-confidence outputs ordered LONG/SHORT;
- tanh MASA.

Observed persistent service configured hidden 2,048 and 4 blocks. The network normalizes finite values with signed `log1p`, applies projection/LayerNorm/GELU, residual blocks and five head families. Optional attention treats values/missing/stale/availability as four tokens; optional temporal path projects frames, runs a GRU and fuses the final state. The confidence family is schema-bound to two outputs, not one scalar; section 0.5.3 defines its label/calibration contract.

### 10.2 Actions

The configured seven-action head includes position-management actions, but `_expected_move_aligned_policy` selects only the first three opening actions: hold, long and short. Close/reduce/hedge actions are architecturally present without equivalent selection lifecycle in this native inference helper.

Expected move biases long/short probability and disagreement can force hold.

### 10.3 MASA

`masa.py` is a deterministic auxiliary adapter. Model inference blends its learned tanh head with the adapter signal 50/50. This implementation is not multiple communicating agents. Reproducing current MASA means reproducing the scalar target/head/blend.

### 10.4 Identity

`model_id` remains architecture identity only. Exact current source weight identity is `model_parameter_fingerprint`, which hashes sorted tensor names, dtype, shape and bytes; checkpoint state additionally binds NPZ SHA, calibration and canonical evidence into a semantic state ID. Prediction/receipt consumers must require those exact digests and never treat `model_id` alone as learned-policy identity. Main-cycle adoption and deployed round-trip proof remain open.

## 11. Training/PPO implementation

Primary source: `hybrid_cuda_trainer/ppo_trainer.py`.

### 11.1 Row modes

Current-source on-policy PPO requires `done is true`, a nonnegative integer trajectory index, immutable rollout/action identity, `CATEGORICAL_SAMPLE` and `POSITIVE_EDGE_MASKED_RAW_LOGITS_SOFTMAX_V1`. `_ppo_ineligibility_reason` revalidates `v2_positive_edge_on_policy_behavior_receipt_v1`, immutable receipt key/write, checkpoint weight/evidence/policy identity, symbol/timeframe, prediction/feature/strict clocks/plan, raw/masked distribution, sample probability/log-probability/value, positive-edge semantics and paper-only/non-A+/non-live flags. It also rebuilds `v2_exact_ppo_finalized_outcome_v1`, requires its digest, and checks `reward == realized_net_pnl_bps/100`. A row carrying sampled proof that is invalid, corrupt or already consumed cannot fall back to outcome supervision. Deterministic strategy-supply rows remain outcome-supervised only when their separate realized-outcome contract is valid. Training can be PPO-only, supervised-only or mixed. The old-generation recount referenced elsewhere used historical `RAW_LOGITS_SOFTMAX_V1`; do not treat that name as the current admitted contract.

The in-cycle split now sorts by immutable decision time, keeps equal timestamps together and purges every training row whose label was unavailable before validation begins. Missing/invalid timing produces no represented validation set and blocks promotion. This fixes the former tail-of-input split, but it is not a globally immutable final-holdout exclusion ledger shared by every online/offline/persistent consumer.

### 11.2 Objective

Supervised base approximates:

```text
cross_entropy(action)
+ 0.01  * expected_move_mse
+ 0.001 * value_mse
+ 0.001 * masa_mse
+ 0.05  * selected_direction_profitability_confidence_mse
```

PPO mode adds clipped policy/value and additional auxiliary terms. The confidence loss is masked to the row's immutable LONG/SHORT decision and targets strictly positive realized net PnL after explicit costs; HOLD does not train either directional output. Because base and PPO auxiliary losses coexist, effective move/value/MASA/confidence weights are larger in PPO batches than their individual labels suggest.

Current source gathers both old and new probabilities at the frozen entry behavior action and admits PPO only when that action came from the receipt-bound positive-edge-masked raw-logit distribution. Hindsight `label_action_index` cannot redefine the behavior action; deterministic expected-move-aligned rows are explicitly ineligible. This repairs the former cross-transform/future-label ratio defect in source. Runtime supply remains verified empty on the old generation: `_has_on_policy_ppo_fields` admitted 0, metrics reported 0 consumed and 2,014 missing-field rejections, and every one of the 92 stored rows lacked sampling/distribution identity. The two rows carrying old log probability also carried only a static paper-owner fingerprint rather than exact served-checkpoint identity (section 0.5.1).

Advantage is immediate realized reward minus old value. `PPO_GAMMA` is parsed/reported but native training does not construct discounted returns or GAE; `done` and trajectory fields gate row presence rather than drive a multi-step return. Critic/auxiliary targets include move-oriented supervision.

### 11.3 Optimizer and direct mutations

AdamW is recreated in the training function; optimizer moments are not persisted/checkpointed. Post-optimizer logic can directly nudge expected-move and policy-head biases and recover saturation/runaway. Those mutations bypass optimizer-state/weight-decay accounting.

A single-direction batch guard still neutralizes directional expected-move labels in some all-long/all-short batches. Temporal rows now canonicalize the trust decision time, sort within symbol/timeframe, omit missing chronology and assert every frame is no later than its target; the temporal tensor path fails when the required lookup/window is absent. This repairs the former list-index future-frame fallback, subject to upstream per-source availability itself being truthful.

Because advantage remains one-step and optimizer/trajectory semantics remain incomplete, this is still accurately described as a hybrid one-step PPO-shaped/supervised trainer, not conventional trajectory PPO. Current evidence verifies that the strict PPO lane consumed zero rows rather than actively dominating learning.

## 12. Rewards, costs and labels

Runtime prediction cost uses:

```text
2 × (fee_per_side + slippage_per_side)
```

Current defaults imply 12 bps round trip. Trusted replay/backtest paths contain a 2 bps assumption. Environment actions may charge round trip on entry and close. These differences change eligibility, reward, confidence target, label, paper economics and promotion.

`trusted_replay/dataset.py` calculates directional trade outcome with `abs(after_cost)` for long and short, making a non-flat directional counterfactual a win regardless of sign. MFE/MAE use raw price direction rather than side-adjusted excursion. Expected-move negative penalties can also mis-handle valid shorts in some reward paths.

Cost/label corrections require new schema/version and replay regeneration, not in-place reinterpretation of historical rows.

## 13. Replay, feedback and holdout

Ordinary selection prioritizes trusted replay backfill/frontier then fresh closed feedback. A bounded in-memory replay buffer is configured up to 16,384 rows. With 1,784-wide current-source or 1,908-wide historical-generation Python objects plus trust metadata, memory is far above old small-schema estimates.

Strengths:

- finalized outcome horizon/embargo;
- explicit trust and replay IDs;
- completeness/rejection scan reports;
- immutable-ish archived source concept.

Gaps:

- masked/missing-trust exceptions;
- historical rows rely on stored temporal assertions;
- provider state is not reproducible unless archived;
- strict 70/15/15 manifest exists but normal training does not exclude holdout;
- H2L overlap is against a heldout cache, not cryptographically bound actual training IDs;
- pickle caches can outlive raw-data assumptions.

The persistent holdout evaluator can evaluate rows that may already have been used for training. Current out-of-sample evidence is not demonstrably untouched.

## 14. Checkpoints

Primary source: `hybrid_cuda_trainer/checkpoint.py`, with weight serialization in `model.py`.

Strengths:

- NPZ v2 tensors plus exact confidence-head schema/action order and checkpoint-bound calibration state;
- `allow_pickle=False`;
- strict name/shape and finite checks;
- exclusive write lock, temporary/atomic replacement and fsync behavior;
- input-dimension filtering;
- retention considers only `v2_hybrid_ckpt_*` JSON/NPZ artifacts and can recover the newest complete pair when a probe supplies no ID;
- legacy scalar-confidence checkpoints fail atomically instead of partially restoring incompatible weights;
- manifest binds NPZ SHA/size, full parameter fingerprint, calibration, lineage/parent, ordered consumed PPO keys, partition and canonical checkpoint evidence;
- semantic checkpoint ID binds model, parameter and state digests; a same-state retry is create-or-identical;
- malformed manifest scan fails closed and every artifact can be verified without mutating a serving model;
- weight resolution ignores manifest-selected paths and permits only exact manager-owned `{checkpoint_id}.weights.npz`.

Gaps:

- the main trainer cycle now uses candidate/rejected/serving lineage, rederives canonical promotion evidence and loads only semantically verified artifacts, but no held/deployed cycle has exercised those transitions;
- the append-only PPO ledger is hash-chained/tamper-evident but not authenticated;
- retention v2 source pins serving, latest candidate, pending-reconciliation artifacts and ledger files and deletes only complete unpinned pairs; real cleanup/restart proof remains absent;
- compatibility does not encode all behavior config;
- optimizer state intentionally absent;
- no deployed restart/reconciliation/promotion round trip exists.

Offline/H2L dataset caches use pickle and must remain trusted-local; loading an untrusted pickle executes code.

## 15. Prediction publication

Primary sources: `hybrid_cuda_trainer/publisher.py` and `runtime.py`.

`build_prediction_payload` produces policy/model/data IDs, times, probabilities/move/confidence/MASA, costs/eligibility, replay snapshot and live-block assertions. `publish_prediction` validates required source/safety fields, appends durable snapshot, writes replay snapshot and prediction key, and validates trust.

### Split-brain failure

1. Payload begins with replay key/ID but write success false.
2. `publish_prediction` shallow-copies the payload.
3. Archive/replay success/failure blocks mutate only the copy.
4. Runtime appends the original to predictions, ignores publisher boolean and calls `publish_lineage` on the original.
5. Trust accepts replay key+ID presence when no client verifies existence.

Thus replay/archive failure can still emit orchestrator/risk/paper lineage. Successful writes also do not update the caller’s original success flag. Counts measure payload construction more than confirmed publication.

Correct contract is archive → replay → prediction → lineage, with one immutable typed receipt and no downstream write after required failure.

## 16. Orchestrator and risk

`cli/v2_orchestrator_arbitration_loop.py` reads/normalizes predictions, arbitrates/group-selects candidates and emits proposals/paper signals. It creates a provisional risk-decision ID and paper-fill flag before risk evaluation.

`cli/v2_risk_gateway_live_loop.py` emits independent allow/deny records. In current non-live state it denies live-disabled/invalid state. Correct consumers must match exact proposal/prediction/hash/time and require action allow.

The 2026-07-16 ordinary paper generation recorded a real deny but later constructed `risk_result.allowed` from risk-ID existence plus local pre-trade; exploration policy required allow, so paths disagreed. Current source requires an exact canonical allow and rereads/binds the risk record at final-admission v3. Historical rows remain suspect, and deployment is not certified until a fresh row proves the complete current contract. See the execution component document for the historical source order and section 0 for the current boundary.

## 17. Paper trade management

Primary owner: `cli/v2_trade_management_paper_loop.py`; supporting modules under `services/paper_trade_management`, `services/trade_management_paper` and `services/paper_exploration`.

Responsibilities include:

- proposal/prediction/risk dereference;
- runtime/market trust;
- strategy router, pre-trade, fee, A+, one-minute and temporal gates;
- opportunity tiering and adaptive capital/sizing;
- direction, churn, exposure and portfolio freeze;
- preemptive loss/admission;
- position transition and fill invariant;
- lifecycle, exits, dedupe/netting and accounting;
- outcome/PPO/feedback and status artifacts.

### Historical defects and current boundary

The risk-deny disagreement, confidence-only relaxation, fee omission, ≥0.65 fast path and frozen fee mutation above were verified in the 2026-07-16/pre-repair generation. Current source retires those effective admissions and funnels rows through the common append/final-v3 boundary described in section 0. Historical rows remain contaminated unless they carry the complete new proof chain; they must not be rewritten or inferred clean from current source.

Current unresolved behavior includes the disabled broad supply bridge, no cross-process reservation/commit fence, no deployed/ACL proof for the source-implemented canonical tuning consumer and sole writer, legacy/unsealed open positions that correctly block new entries, bracket evidence blocked without an account-specific binding, no account-wide cross-margin liquidation engine, and sequential non-transactional Redis persistence. Later lifecycle/churn filters remain defense in depth, not substitutes for a replayable v3 admission.

## 18. Position, lifecycle, portfolio and guardian

Paper subservices implement entry/exit validity, lifecycle reconciliation, net position state, dedupe/netting, accounting, outcome generation and performance telemetry. Invalid transitions must fail before a fill/order boundary; the required model is explicit flat/open/close/replace state, not ID presence.

### 18.1 Partial-close restart reconstruction

`PaperNetPosition.reconstruction_envelope` emits `PAPER_OPEN_POSITION_RECONSTRUCTION_V1`. Canonical SHA-256 material includes position ID/version/generation, entry generation, aware entry/open/reconstruction clocks, symbol/side, `net_quantity`, `avg_entry_price`, ordered source fill IDs, realized PnL, entry-cost accounting version, and incurred/remaining/allocated fee and slippage ledgers with materialized fallback rates, sources and status. It also binds `position_state=OPEN_POSITION`, `paper_only=true` and `places_real_order=false`.

`validate_paper_position_reconstruction` verifies the hash, clock awareness/order, positive quantity/price, unique fill IDs, exact accounting version and for both fee/slippage:

```text
incurred_usd = remaining_usd + allocated_to_closes_usd
```

Reconstruction time must also be no later than the lifecycle's current reconciliation observation. `_restore_hashed_prior_position` seeds a valid snapshot before fill replay and demands that reserialization reproduce the same hash. Legacy partial rows, tampering, future clocks, incomplete cost basis and mixed complete/incomplete same-side ledgers quarantine/fail closed; economics are never inferred to make a row pass. A fallback entry rate is materialized once and then conserved across restarts.

Generation suppression requires both explicit final-close state and quantity conservation: pre-close equals closed quantity or remaining is exactly zero. Each historical netting fill requires a versioned canonical receipt binding close ID, position generation ID, fill ID, side and `input_quantity = consumed_quantity + residual_quantity`; an invalid/legacy receipt blocks replay. Accepted-fill disk compaction retains both reconstruction and netting evidence.

Source validation passed the full paper-management plus new CLI persistence lane (509), focused adversarial/persistence cases (16) and existing CLI compaction/rehydration selector (4, with 534 deselected). No deployed position migration or controlled paper restart has proved current stored history.

`cli/v2_portfolio_state_publisher.py` rebuilds open positions/equity/PnL from paper state/current prices, filters invalid admission and writes `v2:portfolio:state` with TTL plus public artifact. It can fall back to nominal capital and uses fixed UTC−4 “EST.” Duplicate publishers were active.

`cli/v2_portfolio_cascade_guard_loop.py` produces close/tighten intents from cascade/liquidation state; Redis failures can be swallowed. `services/continuous_edge_guardian/guardian.py` aggregates disk/Redis evidence into readiness/A-grade gates and can disagree when artifacts are stale.

## 19. Live execution

Real transport: `services/live_gate/binance_live_order_transport.py`.

It validates release/live/armed state, symbols, decision/risk lineage and action, notional/order/filter constraints, position state, dedupe/write guards, then can send signed Binance WebSocket `order.place` and persist execution state.

At audit time effective release mode was absent/non-live, gate disarmed and no active unit executed real submit. Dormant callers remain; `cli/v2_trader_runtime_loop.py` calls the evaluator whose `dry_run` defaults false. Any caller/unit/environment change requires a fresh audit.

Live source/callers cannot be edited without explicit operator approval. This reference contains no activation procedure.

## 20. FastAPI application

Factory: `app/main.py::create_app`.

It registers middleware, V1 routers, auth/RBAC, V2 router, market-stream router, health aliases and SPA/static serving. Effective deployment has four workers, so globals/locks/caches/history are process-local.

Current OpenAPI observation:

- 189 paths;
- 193 HTTP operations: 158 GET, 27 POST, 4 PUT, 4 DELETE;
- zero OpenAPI operations declare security;
- seven mounted WebSocket paths beyond OpenAPI.

Static AST sees more decorators/references because it includes OPTIONS/aliases/clients/unmounted/static source.

The API is not read-only. Mutations include auth/user/account, admin/live-gate control, paper reset/order CRUD/fill, alert CRUD, backtest/subprocess launch, push tokens, cache and pipeline requests.

`/health` and `/api/health` are unconditional liveness; `/api/v2/system/health` pings Redis.

## 21. Middleware and authentication

Eleven registered middleware layers include request ID, IP/rate/MFA/RBAC/idempotency/lineage/approval/live-block/DB/CORS concerns. Nine are essentially pass-through scaffolds; material middleware enforcement is CORS and a narrow live-block guard. Route dependencies provide some real auth/role protection.

Auth modules:

- `auth/security.py`: custom HS256 token, process-secret, cookies/session, revocation, MFA helpers;
- `auth/users.py`: local JSON and optional SQL user stores;
- `api/auth_rbac.py`: login/logout/register/admin/account routes.

Current health reported local-file/non-production users/revocations, issuer/audience and MFA not production-ready. Login returns access token in JSON plus HttpOnly cookie. Four workers have only process-local file locks, so atomic replace prevents torn files but not lost updates. Import can create a process-secret file if env is missing.

Sensitive local files had mode 0664; the tunnel service exposes a credential in command arguments. Values are intentionally not recorded.

## 22. Web and mobile clients

### React/Vite

`src/main.tsx` mounts StrictMode/App/AuthProvider/RealtimeProvider/RouterProvider. Router/pages and clients consume REST, WebSocket/SSE and public runtime artifacts. Vite disables ordinary public directory copying and performs curated copy/prune, so `public/operator_runtime` is not automatically deployed.

Effective process only previews existing `dist`; restart does not build. Dependency tree is incomplete and no frontend-local lockfile provides a clean reproducible install.

### Swift

Swift package provides iOS app, watch app and `aibot` CLI. API endpoint/client/model definitions are duplicated between app/core targets, creating contract drift. Any API or field change must inspect both Swift and TypeScript atlases.

## 23. Persistence and storage

### Redis

At snapshot: roughly 1.11 million keys, 31 GiB/32 GiB, `allkeys-lru`, AOF disabled, RDB enabled and no discovered replica/backup/restore proof. Redis holds critical coordination, paper and lineage state but can evict any key and lose post-snapshot changes.

### Relational/SQLite

`v2/backend/v2_paper_trading.db` is empty and central application metadata/Alembic have no initialized schema or versions. Optional user, revocation, alert and trader-account SQL repositories are implemented and can create their own tables outside Alembic, but the observed auth/state selection used local JSON. Closed-loop automation separately uses one SQLite WAL database; its rollback helper copies only the main DB and can omit WAL changes.

### Files/models/archive

Runtime, replay, model, public JSON, JSONL/logs and worklog evidence occupy hundreds of GiB. Archive records have content hashes but ordinary publisher writes skip checksum-manifest update; rollover can remove blobs/index without durable tombstones. Logs are decentralized and very large.

Two retention policies conflict: 100 GiB FIFO rollover versus 300 GiB/five-day janitor. The former is failed because of an invalid path; repairing it without approval can delete a large dataset.

## 24. Observability and automation

`app/logging.py` is a placeholder. User journals returned no entries; services write journal/files/runtime artifacts inconsistently. Prometheus rules exist without installed Prometheus/Grafana/Alertmanager. Webhook/Telegram sending was not active. Four API workers fragment in-memory metrics history.

The microstructure monitor demonstrates why stdout is not an authority plane: full Redis/status rows were redundantly serialized into a multi-gigabyte two-second loop log. Its installed service now selects bounded compact telemetry and the ten-minute logrotate timer caps four high-rate service families, while authoritative rows remain elsewhere. Monitor both sinks, writer continuity and archive integrity. Changing `--loop-log-mode`, loop cadence, log redirection, schema `v2_microstructure_feed_quality_monitor_loop_log_v1`, Redis/status publication or `copytruncate` rotation has a coupled observability/resource blast radius. IDE watcher exclusions reduce extension load but do not remove the operator's obligation to inspect excluded evidence explicitly.

Self-healing supervises dozens of non-ingestor components and can restart services; its rate ledger is Redis and can be evicted. Autonomous Claude/Codex workers can edit and commit the mutable worktree from which services restart. Git HEAD and dirty state are operational inputs.

## 25. Tests, dependencies and build

Runtime-oriented count: 1,446 backend test files (1,307 unit, 137 integration, 2 contract). A conftest documents previous destruction of real paper history; global isolation is incomplete, so full suite was not run.

No active root-enforced backend/frontend GitHub Actions workflow was found. A tracked dormant definition exists at `v2/.github/workflows/ci.yml`; its own header says it must be installed under the repository-root `.github/workflows/` before GitHub will enforce it. `v2/pyproject.toml` omits actual runtime packages such as Torch/NumPy/Gymnasium/psutil; the ad-hoc venv has many more. Frontend `npm ls` fails, Docker compose is empty, gitleaks is absent and its wrapper exits success when absent.

The 2026-07-16 baseline scoped results were: atlas Python/Node checks passed and atlas pytest passed 4; frontend typecheck passed; Swift Core passed 32 with iOS/watch application targets excluded; middleware order passed 1/failed 2 because expectations were stale; and the canonical-candle/pipeline-trust group passed 66/failed 6. All six latter failures occurred before intended publisher assertions because the synthetic tensor fixture lacked `missing_mask`, which production `_trusted_replay_snapshot` read (`publisher.py:562`; `test_pipeline_trust_runtime_enforcement.py:653-670`). That historical fixture result is not the 2026-07-17 trainer/PIT reconciliation, which later passed 374 tests at its recorded source cut.

## 26. Change-impact method

For a function:

1. find `symbol_id` in `CHANGE_IMPACT_INDEX.json`;
2. read exact source and every return/exception/fallback;
3. traverse direct callers/importers upward and callees downward;
4. inspect unresolved/dynamic calls;
5. join Redis/env/data/API/exchange registries;
6. inspect effective installed units/drop-ins/import roots;
7. trace TypeScript/Swift/public artifact consumers;
8. classify temporal/training/risk/position/live/destructive implications;
9. write isolated negative tests and rollback;
10. regenerate atlas and docs.

For high-blast-radius surfaces:

| Change | Affected system |
|---|---|
| Symbol universe | subscriptions, feature coverage, trainer/publish/UI universe |
| Candle/finality | all decisions, replay/labels/evaluation |
| Feature spec/order | tensor/model/checkpoint/prediction and clients |
| Temporal fields | trust, archive/replay, risk/paper/live validity |
| Publisher schema | prediction, orchestrator, risk, paper, UI/feedback |
| Risk action | paper and live control authority |
| Paper condition | lifecycle/accounting/portfolio/outcome/training |
| Cost model | gates, rewards, labels, sizing and promotion |
| Model/checkpoint ID | exact policy provenance and every future decision |
| Redis key/TTL | nearly every service and recovery |
| Worker/import config | locks/singletons/auth/metrics |
| Frontend/API fields | React and duplicated Swift decoders |
| Retention | irreversible replay/evidence deletion |

## 27. Rebuild requirements

A clean copy requires pinned dependencies/hardware, immutable releases, canonical import root, complete unit installer, secret-name/rotation manifest, exported tunnel routing, versioned Redis/key/TTL contracts, PIT envelopes, a reproducible generation-bound tensor (446/1,784 current source; 477/1,908 historical only), exact ordered feature digest and weight identity, clean split manifests, one risk/paper authority, one fill state-machine boundary, durable publication receipts, isolated tests, centralized observability and tested backup/restore/rollback.

The ordered reconstruction stages and acceptance tests are in `docs/system_audit_2026_master/REBUILD_BLUEPRINT.md`.

## 28. Current blocking defects

The detailed register is `docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md`. Highest priority:

1. deployed proof that every new paper row traverses final-admission v3 and no legacy/pre-repair row enters clean evidence;
2. cross-process fencing/durable reservation and crash-safe persistence for snapshot → commit → append/publish;
3. authenticated account-specific bracket binding (`CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC` is currently blocking);
4. deployed canonical adaptive-tuning semantic-receipt propagation and exclusive-writer/ACL proof;
5. incomplete per-source feature PIT lineage, advanced-indicator receipt coverage and final-holdout isolation;
6. publisher/archive/replay/checkpoint identity and deployment-generation compatibility, including a controlled compatible two-action-confidence checkpoint/calibration round-trip;
7. legacy/unsealed open-position exit/closure and fresh source-fill/current-mark evidence;
8. disabled/scanning-prone paper supply bridge and lack of attributable A+ supply;
9. four held trainer services/two stopped timers with exact on-policy runtime still 0/0, sole/latest PPO split starvation, no deployed cold-start/candidate/reject/promote/restore/crash or durable unique-consumption proof, no runtime nonzero V2 confidence-target/calibration evidence, process-local lane state and the old deployed cost schema; source now mitigates the former cold-start, unfitted-promotion, terminal/clock/cache and lifecycle-integration defects;
10. unbounded TTL −1 Redis evidence; corrected archive/hot-cache/consumer source passes 87/18 but has no controlled runtime migration, trim, reload or burn-in; undeployed supervisor-log repair, Redis durability/recovery and process ownership;
11. security, retention, CI/test isolation, negative performance and G11/G12 certification failures.

These conclusions do not authorize fixes to strategy, PPO, MASA, risk or live-execution code. Each requires a separately scoped approved change with tests.

## 29. Definition of safe system understanding

The system is “understood” only when a proposed change can identify:

- exact source symbol and semantic invariant;
- every direct/static and dynamic caller/consumer;
- environment/default/effective deployment value;
- Redis/file/API/client contracts and temporal fields;
- model/replay/checkpoint consequences;
- risk/position/paper/live consequences;
- tests and state isolation;
- deployment/restart/rollback;
- evidence preservation and atlas diff.

The atlas supplies the exhaustive static lower bound. This reference supplies subsystem semantics. The operator manual supplies safe actions. Runtime evidence must be refreshed because resident automation continuously changes the source and deployed state.
