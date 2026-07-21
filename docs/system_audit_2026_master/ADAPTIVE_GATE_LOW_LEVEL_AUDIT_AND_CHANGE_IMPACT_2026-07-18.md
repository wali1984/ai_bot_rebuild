# Adaptive gate low-level audit and change-impact map

- **Snapshot date:** 2026-07-18
- **Working-tree base commit:** `e7bc73099977d0472def86b72b88bf6b23eaac67`
- **Branch:** `codex/pipeline-trust-refresh`
- **Scope:** current PAPER admission, orchestration, risk, allocation, leverage, margin, and outcome-feedback controls
- **Live behavior:** not changed by this document

All source locations are repository-relative and refer to the inspected working-tree snapshot, including relevant uncommitted handoff work. Line references are evidence anchors, not stable API identifiers; after any edit, relocate by the named function or field and re-run the cited contract tests.

## Executive finding

The current system is not threshold-free. It contains a mixture of:

- immutable structural, temporal, economic-sign, and loss-authority invariants that must remain hard;
- fixed market-magnitude and sample-count cliffs that can abruptly stop PAPER evidence flow;
- continuous adaptive controls whose outputs are still bounded by fixed audited safety authority;
- alternate or shadow implementations that are present in the repository but do not control the canonical PAPER path.

The highest-impact market cliffs are the canonical strategy-router ladder, the entry/side/outcome gates, the final A+ conjunction, preemptive decision ladders, the strict performance circuit, the duplicated fee-ratio gate, and the canonical adaptive tuner's fixed bins and rule ladder. The PAPER router is also currently starved of its intended MASA/timeframe index even though it consumes that empty index later. A derived-signal fallback retains a fixed 4 bps cost re-gate. A candidate can pass the native publisher and still be stopped by several independent downstream discontinuities or evaluated with incomplete routing context. Calling each component “adaptive” does not make the end-to-end composition adaptive.

The authorized leverage and margin envelope is a constraint to preserve. PAPER leverage is not globally stuck at 1x: candidate evidence interpolates from 1x toward the smaller of the dynamic risk envelope, the authorized symbol ceiling, the standalone recommendation, the call-site permitted leverage set, and liquidation safety. The canonical PAPER call site currently permits `1/2/3/5/10/20x`, so its effective maximum is 20x even where the wider operator ceiling is 50x or 75x. That is the inspected authorized implementation, not permission for this audit to expand it. Margin is simulated as isolated. Live leverage and margin mutation remain operator-gated and unchanged.

The 1000x-in-90-days objective is aspirational, not a result this code audit can guarantee. It implies approximately 7.98% compounded growth every day for 90 days. Leverage increases both gains and losses; it cannot manufacture positive after-cost edge. An A+ label is valid only when supported by point-in-time, forward outcome evidence. “All A+ grades flowing” must never be implemented by forcing every candidate to pass or by lowering evidence requirements.

### Handoff evidence of the binding freeze

The operator-supplied handoff transcript captured one 60-intent snapshot with zero accepted fills: 32 `P0_ENTRY_GATE_BLOCKED`, 21 `PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED`, three `BLOCK_NO_EDGE`, two strategy-router blocks, and one non-executable tier. Of the sampled P0 reasons, 26 were outcome-memory win-rate cliffs at 33.33% or 30.43% versus the fixed 35% floor. This is historical handoff evidence, not a current health assertion, but it demonstrates that the P0 outcome/performance gates can dominate the entire evidence loop exactly as the source-level graph predicts.

## Classification rules used in this audit

| Class | Meaning | Required treatment |
|---|---|---|
| `HARD-INVARIANT` | Identity, type/range, temporal ordering, candle finality, lineage, economic sign, position transition, exchange filter, margin, liquidation, drawdown/loss authority, or explicit operator scope. | Preserve as fail-closed. A hard zero/sign boundary is not a market threshold. |
| `AUTHORIZED-ENVELOPE` | Explicitly operator-authorized PAPER leverage/margin ceiling or live mutation boundary. | Preserve exactly unless the operator separately changes authorization. |
| `P0-MARKET-CLIFF` | A fixed market magnitude, grade, sample, or performance cutoff that directly blocks or permits the canonical PAPER path. | Characterize, shadow, then replace with continuous uncertainty-aware control. |
| `P1-CONTROL-KNOT` | Active or conditional fixed knot that ranks, sizes, ages, deduplicates, or concentrates candidates but is not the first dominant blocker. | Convert after P0 and retain monotonic safety bounds. |
| `CONDITIONAL-LANE` | Controls only an environment-selected, alternate, or candidate-specific lane. | Do not count as globally binding; test the activation predicate. |
| `INACTIVE/SHADOW` | No canonical consumer call, diagnostic-only writer, remediation script, or a threshold set so it cannot bind. | Do not tune as if it controls production. Remove ambiguity or keep clearly non-authoritative. |

“Adaptive” means the decision magnitude is derived from current, point-in-time market/performance evidence and changes continuously with uncertainty. Selecting among fixed thresholds, adding a regime offset, or tightening a static ceiling is still a fixed rule ladder.

## Canonical binding PAPER data flow

```text
native trainer / feature snapshots
        |
        v
native trainer prediction publisher (authoritative prediction-key writer)
  v2:prediction:{symbol}:{timeframe}
        | \
        |  `--> all-timeframe derived-signal publisher
        |         v2:signals:paper:{symbol}:{timeframe}
        |         (legacy/observation input; not decision authority by itself)
        v
orchestrator arbitration
  v2:decision:orchestrator:{orchestrator_decision_id}  (immutable per ID)
  v2:orchestrator:decisions                         (preview/aggregate)
  v2:signals:paper                                  (risk pending)
        |
        v
risk gateway
  v2:decision:risk:{risk_decision_id}               (immutable per ID)
  v2:risk:gateway:decisions / latest                 (preview/aggregate)
        |
        v
canonical paper loop
  aggregate and per-symbol signal observations
  -> exact decision-ID dereference -> entry/performance/preemptive/A+ gates
  -> AllocationInput -> dynamic envelope -> adaptive allocator
  -> write-invariant validation -> accepted PAPER fill / ledger
```

### Key ownership and authority

| Key or in-memory contract | Sole/primary writer | Consumers | Authority rule |
|---|---|---|---|
| `v2:prediction:{symbol}:{timeframe}` | Native `PredictionPublisher.publish_prediction` in `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:2586-2838` | Orchestrator scan; all-timeframe derived-signal publisher | Authoritative current prediction evidence, still subject to independent downstream validation. |
| `v2:signals:paper:{symbol}:{timeframe}` and `v2:signals:latest:{symbol}` | All-timeframe `publish_v2_keys` in `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:5942-6020` | Canonical paper signal reader/monitoring | Candidate observation only; cannot replace immutable orchestrator/risk authority. |
| `v2:decision:orchestrator:{orchestrator_decision_id}` | `_write_per_id_orchestrator_decision_record` in `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:117-203` | Risk gateway and canonical paper dereference | Immutable per-ID orchestrator authority; producer, ID, hash, time, and expiry must match. |
| `v2:orchestrator:decisions` | Orchestrator `run_once` in `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1199-1258` | Risk gateway; paper observation/recovery | Aggregate preview. It selects work but cannot substitute for the per-ID record. |
| `v2:signals:paper` | Orchestrator `run_once` in `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1260-1354` | Canonical paper signal reader | Risk-pending aggregate candidate view; exact decision dereference remains mandatory. |
| `v2:decision:risk:{risk_decision_id}` | `_write_per_id_risk_decision_record` in `v2/backend/app/cli/v2_risk_gateway_live_loop.py:658-818` | Canonical paper dereference/replay | Immutable per-ID risk authority; no preview or embedded allow bit can replace it. |
| `v2:risk:gateway:decisions` and latest previews | Risk gateway `run_once` in `v2/backend/app/cli/v2_risk_gateway_live_loop.py:892-949` | Monitoring and paper recovery/observation | Last-write-wins previews only; not fill authority. |
| `AllocationInput` | Canonical paper `_build_allocation_input` in `v2/backend/app/cli/v2_trade_management_paper_loop.py:40051-40984` | `allocate_paper_candidate` | Complete in-memory economic contract. Any post-allocation risk/quality mutation requires full reallocation. |
| `v2:paper:intents` / `v2:paper:closed_trades` | Canonical paper `run_once` writes at `v2/backend/app/cli/v2_trade_management_paper_loop.py:48741-49129` | Monitoring, outcome memory, tuner, trainer feedback | Outcome evidence, not retroactive admission authority; rows retain original immutable IDs/hashes and session/time classification. |

### Current P0 end-to-end validation blocker

The paper-boundary implementation is staged but not yet evidence-complete. `_paper_exact_json_with_ttl` performs each source-payload/TTL observation through one transactional Redis pipeline at `v2/backend/app/cli/v2_trade_management_paper_loop.py:40987-41023`; `_paper_ordinary_transport_assessment` uses it for both the replay snapshot and source prediction before calling the shared validator at `v2/backend/app/cli/v2_trade_management_paper_loop.py:41026-41055`. `_paper_signal_integrity_gate` bypasses the legacy score-70/`valid_for_paper` booleans only for a successfully revalidated ordinary claim at `v2/backend/app/cli/v2_trade_management_paper_loop.py:41058-41116`. `_build_allocation_input` validates the resulting `(0,1]` weight and evidence hash, places the hash in allocation lineage, and passes the weight into `AllocationInput` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:40845-40975`; `run_once` invokes the boundary and forwards its exact weight at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42238-42252,43331-43346`.

The staged final-append contract performs another ordinary transport re-read at `v2/backend/app/cli/v2_trade_management_paper_loop.py:34856-34889`, compares the revalidated weight and evidence hash to allocator input and lineage at `v2/backend/app/cli/v2_trade_management_paper_loop.py:37335-37357`, and is invoked immediately before list materialization at `v2/backend/app/cli/v2_trade_management_paper_loop.py:26367-26445`. The focused paper-boundary suite currently proves the first-boundary transactional reads, expiry/persistence refusal, transport tamper rejection, legacy behavior, and allocator input binding. It does not yet prove the final-append reread and final allocator weight/hash mismatch cases.

Status: `P0-VALIDATION-BLOCKED`. The system must not claim end-to-end adaptive ordinary PAPER admission until tests prove both boundaries, source/replay tamper and wrong identity, stale/expired/persistent keys, legacy downgrade, hash-bound allocator contraction, and unchanged hard/live gates. The risk record alone is not permission to trust an embedded weight. Independent strategy-router and later P0 market cliffs documented below also remain unresolved even after this boundary passes.

### Prediction and derived-signal publishers

- `PREDICTION_KEY_TEMPLATE` defines `v2:prediction:{symbol}:{timeframe}` at `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/config.py:47`; `PredictionPublisher.publish_prediction` writes the current-cycle native payload at `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:2586-2838`. Repository search found no write to this namespace in the all-timeframe publisher.
- The ordinary native publisher computes a scale-free PAPER quality weight, binds calibration/cost/PIT/replay/trust evidence, and leaves legacy static edge/confidence/coverage results as telemetry in `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:735-1065,1932-2355`.
- The all-timeframe publisher's key constructors for reading the prediction and writing derived signal views are `prediction_key`, `signal_paper_key`, and `signal_latest_key` in `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:1051-1064`.
- `build_prediction_row` assembles a derived prediction, feature, cost, confidence, market-integrity, and routing view at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:1905-2332`; signed direction is enforced at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:2093-2106`, while the legacy derived route still uses fixed `valid_for_*` booleans at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:2128-2177`.
- `build_signal_from_row` transports the derived lineage and gate result at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:3060-3338`. `publish_v2_keys` writes market-integrity and per-symbol/timeframe PAPER signal views at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:5942-6020`; it retires stale prediction keys but does not publish a new current prediction payload.
- The derived signal is not sufficient authority for a fill. The canonical PAPER loop must still dereference matching immutable orchestrator and risk records before allocation or acceptance.

### Orchestrator

- `v2_orchestrator_arbitration_loop._scan_predictions` scans `v2:prediction:*`, filters explicit non-routing rows, and rejects age over 300 seconds at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:244-284`.
- Exact feature snapshot/hash identity and `available_at`/`feature_cutoff <= decision_time` are rechecked at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:285-373`.
- Candle finality, PPO/MASA ordering, and feature-snapshot identity are rechecked at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:395-441`.
- `_prediction_to_proposal_and_signal` converts signed market-return edge to position-return edge without promoting HOLD at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:479-569`.
- `run_once` scores market state and applies the ordinary-lane independent assessment before arbitration at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:883-930`.
- Arbitration uses `OrchestratorArbitrationService(max_age_seconds=300)` at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1120-1121`.
- Per-ID orchestrator records are written by the sole producer at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:117-203` and called at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1199-1254`.
- Aggregate decisions and risk-pending PAPER signals are written at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1255-1258` and `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1260-1354`.

### Risk gateway

- The gateway reads `v2:orchestrator:decisions` and iterates bucket winners in `v2/backend/app/cli/v2_risk_gateway_live_loop.py:820-839`.
- It validates the exact orchestrator per-ID record and producer at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:235-310`.
- `_winner_to_decision` creates the typed decision record at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:486-531`.
- `run_once` revalidates ordinary-lane evidence, constructs trust rejection evidence, and invokes the canonical risk evaluator at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:839-889`.
- Immutable risk records are written under `v2:decision:risk:{risk_decision_id}` by `_write_per_id_risk_decision_record` at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:658-818`, then aggregate previews are written at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:892-949`.
- The generic risk service preserves invalid same-side position transitions and snapshot/trust fail-closed checks at `v2/backend/app/services/risk_gateway/service.py:181-245`.

### Canonical PAPER loop and allocator

- `_read_paper_signals` reads the aggregate `v2:signals:paper` key and a bounded deterministic set of per-symbol keys at `v2/backend/app/cli/v2_trade_management_paper_loop.py:5020-5256`.
- `_paper_policy_intent_decision_dereference` accepts authority only from exact per-ID records, validates producer/identity/hash/time/expiry, and treats previews as observations at `v2/backend/app/cli/v2_trade_management_paper_loop.py:25816-26083`.
- `run_once` calls that dereference at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42833-42850`.
- `_build_allocation_input` binds price, confidence, signed edge, market score, exchange filters, market context, reservations, ordinary quality, and lineage at `v2/backend/app/cli/v2_trade_management_paper_loop.py:40051-40984`.
- The paper allocator is imported inside `run_once` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:41164`; normal sizing is invoked at `v2/backend/app/cli/v2_trade_management_paper_loop.py:43441-43505`, and reduced-risk sizing fully reallocates at `v2/backend/app/cli/v2_trade_management_paper_loop.py:44613-44770`.
- A fill cannot enter accepted state until adaptive sizing (`v2/backend/app/cli/v2_trade_management_paper_loop.py:43441-43556`), entry/A+ and local admission (`v2/backend/app/cli/v2_trade_management_paper_loop.py:43695-44033`), preemptive admission (`v2/backend/app/cli/v2_trade_management_paper_loop.py:45215-45242`), and `validate_paper_fill_write_invariant` (`v2/backend/app/cli/v2_trade_management_paper_loop.py:45275-45310`) pass; every append path calls the final contract through `_paper_append_accepted_with_halted_probe_finalization` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:26274-26538`.
- The canonical owner contract requires exactly one `v2_trade_management_paper_loop`, forbids `paper_online_runtime`, and fails closed on ambiguity at `v2/backend/app/cli/v2_trade_management_paper_loop.py:3564-3823`.

## Protected hard invariants

These checks are intentionally static because they define truth or authority, not a market opportunity magnitude.

| Invariant | Exact implementation | Failure impact |
|---|---|---|
| Final candles only | Orchestrator rejects unconfirmed/future candle closes in `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:395-425`; market scoring validates completion in `v2/backend/app/services/market_state_integrity/scoring.py:194-210`. | Prevents look-ahead and partially formed higher-timeframe inputs. |
| Feature availability ordering | `available_at <= decision_time` and `feature_cutoff <= decision_time` in `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:324-337,395-417`. | Prevents unavailable features from entering a decision. |
| Cross-model ordering | `MASA feature_cutoff <= PPO decision_time` at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:427-435`. | Prevents cross-model future leakage. |
| Dirty training rows rejected | Critical candle/timing reasons and training rejection state in `v2/backend/app/services/market_state_integrity/scoring.py:278-309`; canonical tuner admits only clean current-session outcomes in `v2/backend/app/cli/v2_adaptive_gate_tuner.py:400-441`. | Prevents corrupt adaptation and false A+ evidence. |
| Finite/range-safe allocator input | `_paper_input_rejection_reasons` checks every economic input and `(0,1]` paper multipliers in `v2/backend/app/services/adaptive_capital_allocator/allocator.py:94-163`. | Prevents NaN/Inf or malformed evidence from becoming a pass. |
| Signed after-cost direction | Publisher at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:2093-2106`; entry gate at `v2/backend/app/services/paper_trade_management/entry_gate.py:184-218,407-414`. | A LONG requires positive signed edge; a SHORT requires negative market-return edge. |
| Exact microstructure source envelope | Monitor writes the canonical expiring `v2:microstructure:trust_score:{symbol}:{timeframe}` payload at `v2/backend/app/cli/v2_microstructure_feed_quality_monitor.py:726-767`; trainer data loading performs a transactional uncached `GET+TTL` and binds payload/hash/key/symbol/timeframe/tensor lineage in `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py:1032-1075,1662-1728`; shared construction and validation are in `v2/backend/app/services/ordinary_paper_admission.py:194-452`. | Prevents a fresh downstream book read, cached tensor value, changed key, persistent key, expired key, or unrelated symbol/timeframe from masquerading as the exact PIT source used by the trainer. |
| Exact ordinary source/replay transport | Shared revalidation compares current source prediction/replay contents, remaining positive TTL, prior TTL upper bounds, transported hash/weight, and expected identity in `v2/backend/app/services/ordinary_paper_admission.py:632-767,1207-1252`; PAPER obtains each payload/TTL pair transactionally in `v2/backend/app/cli/v2_trade_management_paper_loop.py:40987-41055`. | Prevents an embedded allow bit, refreshed TTL, overwritten current key, or changed replay generation from becoming PAPER authority. This is structural transport truth, not a market threshold. |
| Exact per-ID decision authority | Orchestrator record `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:117-203`; risk record `v2/backend/app/cli/v2_risk_gateway_live_loop.py:658-818`; paper dereference `v2/backend/app/cli/v2_trade_management_paper_loop.py:25816-26083`. | Prevents preview races, ID substitution, producer spoofing, and stale authority. |
| Invalid position transitions fail closed | `v2/backend/app/services/risk_gateway/service.py:190-203`. | Prevents same-side reopen or invalid transition from reaching order logic. |
| Exchange filters and quantization | PAPER rounds down and rechecks min/max quantity/notional in `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1367-1455`. | Prevents invented size and invalid venue quantity. |
| Loss/margin/liquidation authority | Margin selection, liquidation buffer, and free-margin block in `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1538-1580`. | Prevents size/leverage from exceeding supplied risk and free-margin authority. |
| Operator symbol/timeframe scope | Operator exclusions/timeframes in `v2/backend/app/services/paper_trade_management/entry_gate.py:76-100,302-321`. | Maintains explicit operational, listing, or regulatory scope. |
| PAPER/live separation | Allocator returns 1x for non-PAPER dynamic leverage in `v2/backend/app/services/adaptive_capital_allocator/allocator.py:447-452`; leverage recommendations are PAPER-only/non-mutating in `v2/backend/app/services/paper_trade_management/leverage_recommendation.py:1-21,268-289`. | Prevents this audit or PAPER evidence from changing exchange state. |

The following numerical boundaries are also structural: probability values in `[0,1]`, positive finite price/equity/quantity, timestamps not in the future, exact hash equality, minimum venue order rules, and authorized risk/leverage maxima. They are not candidates for market adaptation.

## P0 active static-gate inventory

### P0.1 Entry gate: fixed cascade and symbol cliffs

`PaperEntryGateConfig` contains a 0.30 SHORT trend cascade floor and a literal `SYNUSDT/RAVEUSDT/LITUSDT/CAPUSDT/EPICUSDT` trend-mode denylist at `v2/backend/app/services/paper_trade_management/entry_gate.py:101-135`. `evaluate_entry_gate` enforces them at `v2/backend/app/services/paper_trade_management/entry_gate.py:323-371`. It also consumes the canonical tuner's LONG/SHORT confidence floors and applies them as a binary entry cutoff at `v2/backend/app/services/paper_trade_management/entry_gate.py:373-405`; calling the source adaptive does not remove the final floor discontinuity. The canonical paper loop calls this evaluator and converts rejection to `P0_ENTRY_GATE_BLOCKED` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:43695-43804`.

Impact: changing 0.30 changes only SHORT trend supply at the cascade boundary; changing the literal set changes every trend candidate for that symbol regardless of current depth, gap probability, or liquidity; changing either tuned confidence floor moves the direct entry boundary for that side. Replace the market magnitude, symbol list, and confidence cliff with continuous current gap/liquidity/cascade/calibration risk, but preserve missing/stale evidence fail-closed.

### P0.2 Side-performance gate

`SideGateConfig` fixes minimum evidence at 8 trades, LONG/SHORT confidence floors at 0.55, Brier penalty start at 0.25, penalty scale 0.5, and maximum floor 0.80 in `v2/backend/app/services/paper_trade_management/side_performance.py:30-41`. `evaluate_side_gate` blocks non-positive expectancy at the evidence count and confidence below the derived floor at `v2/backend/app/services/paper_trade_management/side_performance.py:190-255`. It is consumed by `v2/backend/app/services/paper_trade_management/entry_gate.py:446-474` and again by the A+ side check in `v2/backend/app/services/a_plus_trade_gate/service.py:258-294`.

Impact: an eighth close can switch a whole side from allowed to blocked, and an epsilon around the confidence floor changes admission without changing uncertainty materially. Replace the count/floor ladder with a posterior expectancy/calibration uncertainty weight. Retain the hard rule that no risk growth is earned from a non-positive conservative after-cost expectation.

### P0.3 Outcome-memory gate

`OutcomeMemoryThresholds` fixes minimum evidence 20, win rate 0.35, rolling EV -5 bps, slippage failure 0.40, reversal 0.50, and missed-stop 0.40 at `v2/backend/app/services/paper_trade_management/outcome_memory.py:218-240`. `evaluate_outcome_memory_bucket` applies the ladder at `v2/backend/app/services/paper_trade_management/outcome_memory.py:265-403`. `load_outcome_memory_bucket` uses a 5,400-second stale-evidence valve at `v2/backend/app/services/paper_trade_management/outcome_memory.py:422-518`; the static soak fallback is advisory only at `v2/backend/app/services/paper_trade_management/outcome_memory.py:520-543`. The entry gate consumes it at `v2/backend/app/services/paper_trade_management/entry_gate.py:416-445`.

Impact: one sample or a small metric movement can quarantine a symbol/timeframe. The fixed stale valve can also abruptly convert a block to advisory. Replace market magnitudes with time-decayed posterior loss/EV/cost distributions and make staleness cadence-relative. Keep model-lineage trust, finite outcomes, and PIT ordering hard.

### P0.4 Final A+ conjunction

`APlusGateConfig` fixes HTF alignment at 0.25, composite trust at 0.60, context age at 1,800 seconds, high-confidence loss at 0.70 over 24 hours, and side evidence at 3 trades in `v2/backend/app/services/a_plus_trade_gate/service.py:58-99`. It also requires every listed microstructure confirmation field at `v2/backend/app/services/a_plus_trade_gate/service.py:74-83,365-402`, demands no missing/stale feature at `v2/backend/app/services/a_plus_trade_gate/service.py:545-557`, and blocks on any matching recent high-confidence loss at `v2/backend/app/services/a_plus_trade_gate/service.py:564-605`. `evaluate_a_plus_candidate` is an all-check conjunction at `v2/backend/app/services/a_plus_trade_gate/service.py:608-710`; the canonical paper loop calls and records it at `v2/backend/app/cli/v2_trade_management_paper_loop.py:43933-44018`.

The composite trust producer fixes feed/tape/cross-venue/sweep/spread/depth/impact confirmation magnitudes at `v2/backend/app/services/microstructure_trust/trust_score.py:117-190`, soft confirmation fraction 0.60 at `v2/backend/app/services/microstructure_trust/trust_score.py:193-231`, trust tiers at `v2/backend/app/services/microstructure_trust/trust_score.py:234-246`, and weighted score coefficients at `v2/backend/app/services/microstructure_trust/trust_score.py:253-365`. Trade tape requires 20 trades, defines a large trade as 4x mean notional, and uses 0.55/0.45 direction thresholds in `v2/backend/app/services/trade_tape/service.py:46-47,477-490,530-546`.

Impact: A+ is currently a strict evidence label and a PAPER admission input. Any single missing context or epsilon miss makes the entire grade false. Preserve required provenance/finality/risk/allocator/exit-plan truths. Convert market confirmation magnitudes and recency to an uncertainty-calibrated composite grade; do not make public order-book evidence sufficient by itself.

### P0.5 Preemptive edge-control ladders

The canonical decision fixes probation loss/exit bounds at 0.65/0.55, exploration bounds at 0.72/0.50, and a conservative loss bound at 0.80 in `v2/backend/app/services/preemptive_edge_control/decision.py:41-60`. It builds bucket, cost, confidence, regime, exit, and candidate-loss evidence at `v2/backend/app/services/preemptive_edge_control/decision.py:655-698`, applies fixed alternative-data scores at `v2/backend/app/services/preemptive_edge_control/decision.py:735-776`, and chooses actions through fixed loss/confidence/exit/ATR ladders at `v2/backend/app/services/preemptive_edge_control/decision.py:779-867`.

Supporting cliffs include candidate bucket minimum evidence 3 and PF/expectancy sign rules in `v2/backend/app/services/preemptive_edge_control/bucket_health.py:156-220`; edge 5 bps, loss-rate 0.40, ATR rate 0.40, confidence 0.75/0.50, regime 0.50, exit 0.35/0.55, and trust floors in `v2/backend/app/services/preemptive_edge_control/candidate_loss_risk.py:56-123`; and fixed stop/ATR, edge/cost, edge/stop, and 3x depth/notional tests in `v2/backend/app/services/preemptive_edge_control/exit_feasibility.py:17-64`. The canonical paper loop builds/attaches this decision before entry gates at `v2/backend/app/cli/v2_trade_management_paper_loop.py:43629-43668` and enforces preemptive admission at `v2/backend/app/cli/v2_trade_management_paper_loop.py:45215-45242`.

Impact: several discontinuities map continuous evidence to `ALLOW`, `REDUCE_SIZE`, exploration, or `NO_TRADE`. Replace the market ladders with one calibrated loss/exit distribution and a continuous risk-budget multiplier; preserve positive after-cost direction, exact cost provenance, and non-overridable safety vetoes.

### P0.6 Strict performance circuit and quarantine

Environment-default cliffs are defined in `v2/backend/app/cli/v2_trade_management_paper_loop.py:336-372`: loss-rate 0.40, high-confidence score 0.55, recovery confidence 0.70, cluster count 2, dimension count 3, ATR cluster count 2, negative bucket count 2, global-halt bucket rows 4, and distinct losses 3.

The circuit correctly excludes non-strict exploration/bootstrap/reconstructed rows from governing evidence at `v2/backend/app/cli/v2_trade_management_paper_loop.py:23473-23563`. However, `_paper_bucket_quarantine_status` applies the fixed loss-rate/sample/PF/EV/ATR ladder and global escalation at `v2/backend/app/cli/v2_trade_management_paper_loop.py:24505-24872`; first-bootstrap-loss blocking is at `v2/backend/app/cli/v2_trade_management_paper_loop.py:24873-24903`, and the rolling high-confidence recovery-loss cluster is at `v2/backend/app/cli/v2_trade_management_paper_loop.py:24904-25082`. `_paper_performance_circuit_breaker_status` uses rolling 25/50 views but begins hard PF/EV blocks at 5 and 10 rows, plus quarantine/bootstrap/cluster blocks, at `v2/backend/app/cli/v2_trade_management_paper_loop.py:25083-25325`.

Impact: this is capable of globally freezing evidence after very small samples. PF below 1 and conservative EV at or below zero are valid economic warning signs; sample counts, confidence labels, loss rates, cluster breadth, and global escalation must be uncertainty- and opportunity-supply-aware. A global halt must never depend on multiple projections of the same losing row as independent evidence.

### P0.7 Duplicated fee/edge gate

`evaluate_fee_ratio_gate` defaults to `fee_bps / abs(after_cost_edge_bps) <= 0.5` in `v2/backend/app/services/trade_management_paper/service.py:275-306`. `TradeManagementPaperService.evaluate_pre_trade` invokes it at `v2/backend/app/services/trade_management_paper/service.py:329-377`. The canonical paper loop immediately invokes the service and then calls the same gate again with `max_ratio=0.5` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42347-42356`; it supplies literal 3,600/300-second churn values at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42347-42389`.

Impact: one edge/cost ratio is evaluated twice and can generate divergent diagnostics later. Consolidate to one after-cost economic calculation. Preserve the hard requirement that directional after-cost edge is positive and that fee/cost provenance is current; use residual-edge uncertainty continuously for size instead of a 0.5 cliff.

### P0.8 Canonical “adaptive” tuner still uses fixed bins and grades

The authoritative tuner reads current-session outcomes and closed candles from the canonical keys in `v2/backend/app/cli/v2_adaptive_gate_tuner.py:32-71`. Its evidence-integrity floors are 20 clean outcomes and 20 final candles; those are estimator/data sufficiency requirements, not permission to fabricate missing data. It nevertheless bins the latest 100 outcomes at 0.75/0.50 in `v2/backend/app/cli/v2_adaptive_gate_tuner.py:418-435`, selects confidence 0.65/0.80/0.70 from win-rate rules, adds fixed regime offsets, and clamps 0.50-0.90 at `v2/backend/app/cli/v2_adaptive_gate_tuner.py:792-822`. B-grade and A-grade use fixed WR/count/PnL rules at `v2/backend/app/cli/v2_adaptive_gate_tuner.py:825-854`.

At publication it selects loss probability 0.85/0.80, clamps confidence floors to 0.40-0.70, and forces 0.80 fail-closed floors when evidence is insufficient or non-positive at `v2/backend/app/cli/v2_adaptive_gate_tuner.py:1554-1617`. The consumer validates canonical producer, hashes, session identity, source manifest, authority, PIT evidence, and restrictive fallback at `v2/backend/app/cli/v2_adaptive_gate_tuner.py:1010-1152`; the paper loop independently builds a semantic receipt at `v2/backend/app/cli/v2_trade_management_paper_loop.py:4660-4692` and uses the tuner state only on a passing receipt at `v2/backend/app/cli/v2_trade_management_paper_loop.py:41367-41449`.

Impact: the provenance contract is strong and must remain. The policy math is a static rule ladder. Replace bins and grade toggles with continuous calibration/posterior functions while preserving current-session isolation, finalized evidence, canonical hashes, and restrictive behavior when evidence is absent or non-positive.

### P0.9 Legacy market-integrity and microstructure magnitude booleans

`IntegrityThresholds` fixes training/prediction/risk/paper/live scores at 80/70/80/70/90 in `v2/backend/app/services/market_state_integrity/contracts.py:7-13`; `score_market_state` turns the composite into `valid_for_*` booleans at `v2/backend/app/services/market_state_integrity/scoring.py:290-309`. That score includes fixed freshness 120/900 seconds, disagreement 25 bps, and latency 5,000 ms at `v2/backend/app/services/market_state_integrity/scoring.py:184-192,243-255`.

Legacy orchestrator microstructure blocking uses trust 0.45, A-grade trust 0.65, and sweep risk 0.75 at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:582-584,787-832`; the risk loop has the same 0.45/0.75 pattern at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:53-54,447-463`. These remain active for non-ordinary candidates. The ordinary PAPER transport is intended to preserve hard reject reasons and convert valid market magnitudes to continuous size, but every consumer must independently verify the evidence hash before this legacy cliff is bypassed.

Impact: changing a score threshold affects publisher routing, orchestrator eligibility, risk trust, PAPER integrity, and allocator market-state size simultaneously. Never remove critical reject reasons with the composite threshold. Split structural reasons from continuous market quality explicitly.

### P0.10 Derived-signal 4 bps cost re-gate

The all-timeframe derived-signal publisher retains `ADAPTIVE_COST_MIN_EDGE_AFTER_COST_BPS=4.0` for legacy rows. `adaptive_after_cost_recompute` now treats that floor as already met for a claimed ordinary row while still requiring directionally aligned after-cost edge at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:1792-1902`. `build_prediction_row` separates structural market-state reasons from latency/disagreement magnitudes, copies the ordinary provenance, and uses structural validity for the ordinary branch at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:1905-2225`. `build_signal_from_row` requires an accepted shared assessment and an allowed risk action before an ordinary derived signal can claim fill permission at `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:3060-3122`.

Classification: `CONDITIONAL/LEGACY P0`; the ordinary branch is source-validated. The native publisher writes `v2:prediction:*`, and the orchestrator scans that namespace directly; the all-timeframe publisher emits a derived per-symbol fallback. The canonical paper reader applies its enriched ordinary-discovery predicate at `v2/backend/app/cli/v2_trade_management_paper_loop.py:5122-5152`, loads a bounded deterministic fallback key set at `v2/backend/app/cli/v2_trade_management_paper_loop.py:5176-5215`, then de-duplicates by prediction identity in favor of the richer lineage/gate record at `v2/backend/app/cli/v2_trade_management_paper_loop.py:5217-5254`. The 4 bps cliff remains binding only for legacy rows. It must never be described as globally removed, and no ordinary fallback can independently replace exact orchestrator/risk decision authority.

Regression anchors are `v2/backend/tests/unit/services/test_all_timeframe_prediction_signal_price_target_publisher.py:183-324` and `v2/backend/tests/integration/cli/test_v2_all_timeframe_prediction_signal_price_target_publisher.py`. The focused all-timeframe suite passed 58 tests, and the combined native/ordinary/orchestrator/risk/all-timeframe suite passed 90 tests, including current derived-key TTL, tamper/expiry/PIT failure, structural-versus-magnitude separation, and monotonic sizing.

### P0.11 Canonical strategy-router ladder

`DEFAULT_ROUTER_CONFIG` fixes data quality 80; MASA/PPO confidence 0.55/0.52; execution success 0.45; drawdown reduce/block at 125/250 bps; breakout/scalp move at 18/10 bps; volatility 0.02; spread 12 bps; liquidity 0.35; trust reduce/block at 0.65/0.45; sweep reduce/block at 0.55/0.75; major-move evidence/edge at 0.60/10 bps; several 0.5-0.7 size multipliers; and hard HTF/mid conflict booleans in `v2/backend/app/services/strategy_router/service.py:66-93`. `route_strategy` turns these into fixed reduction, mode, and direct `block_reason` transitions at `v2/backend/app/services/strategy_router/service.py:798-1060`. It also contains a literal momentum-ride override at continuation probability 0.65, reversal probability 0.40, and a 0.5 size multiplier at `v2/backend/app/services/strategy_router/service.py:916-950`; this can convert a configured sweep block into a reduced breakout. The canonical paper loop calls the router before entry admission and requires no block, a non-`no_trade_mode`, and the requested side in `allowed_actions` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42219-42271`.

Impact: this ladder can stop an ordinary candidate even after the upstream scale-free market-integrity and microstructure path passes. The handoff's 60-intent snapshot included two strategy-router blocks. Preserve future-cutoff rejection, valid action/position transition, and authoritative drawdown/loss limits as hard truths. Move model disagreement, confidence, execution uncertainty, volatility, spread, liquidity, trust, sweep, and regime magnitudes to continuous mode probability/risk weight; eliminate duplicate drawdown authority and fixed multipliers. Paper must independently verify the ordinary evidence before bypassing any legacy router magnitude block.

A new isolated remediation candidate classifies legacy soft-versus-hard router reasons and derives a geometric-mean continuous PAPER weight in `v2/backend/app/services/strategy_router/ordinary_paper_interpretation.py:27-93,192-489`. Its 50-test router suite is green, including epsilon continuity, monotonicity, unknown-reason failure, and preserved PIT/transition/quarantine blocks. At this snapshot, repository consumer search finds only its definition and export, not a canonical PAPER call. Therefore it is `STAGED/INACTIVE`, does not change the binding classification above, and must not be credited as a runtime repair until PAPER independently supplies accepted ordinary evidence, seals its contracted weight into `AllocationInput`, and revalidates it at final append.

### P0.12 Canonical PAPER router input starvation

After loading the already-bounded signal set, `run_once` builds only a prediction-ID index, then explicitly sets `prediction_rows = []` and `predictions_by_symbol = {}` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:41321-41355`. No later assignment populates the symbol index. The same loop later reads `symbol_predictions = predictions_by_symbol.get(symbol, [])`, applies `_point_in_time_timeframe_rows`, and passes the result as `masa_predictions` to `route_strategy` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42209-42222`. It also supplies the empty index to cross-asset strategy context at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42178-42181`.

Impact: canonical PAPER routing normally lacks higher/mid/lower MASA direction and confidence rows plus cross-asset prediction context. Existing fixed conflict/confidence rules can silently become non-binding because evidence is absent, while the staged continuous interpreter correctly treats the same missing evidence as fail-closed and would therefore reject every ordinary candidate. This is a P0 dataflow blocker, not a threshold-tuning problem. Build a bounded symbol/timeframe index from the signals already read, deduplicate by current prediction identity, and pass only finalized rows whose `feature_cutoff` and `available_at` are not after the router decision. Tests must use the actual `run_once` data shape and prove no Redis-wide SCAN, no cross-symbol leakage, no unfinished timeframe, and nonempty real-factor interpretation.

## P1 active and conditional control inventory

| Control | Current fixed knot | Active consumer and effect | Classification/remediation |
|---|---|---|---|
| Prediction/proposal freshness | Orchestrator max 300 s; paper policy decision record 900 s. | `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:40,244-284`; `v2/backend/app/cli/v2_trade_management_paper_loop.py:25813,25949-25965`. | P1. Identity/expiry stay hard; market freshness should be candle cadence and source-latency-distribution relative. |
| Paper signal freshness | Base 900 s, operator minimum 120 s, 3x candle cadence. | `v2/backend/app/cli/v2_trade_management_paper_loop.py:283-286,4948-4979`. | Partly adaptive already. Keep finality hard and eliminate the independent absolute 900 s where it can bind inconsistently. |
| Microstructure source lifetime | Monitor Redis TTL defaults to 60 s. | `v2/backend/app/cli/v2_microstructure_feed_quality_monitor.py:53,726-767,789-810`; exact ordinary evidence requires an observed positive integer TTL at `v2/backend/app/services/ordinary_paper_admission.py:352-354`. | Positive non-persistent source lifetime at the exact read is a hard provenance fact. The chosen 60 s publication lifetime is a P1 operational knot and should follow monitor cadence/feed-latency evidence without ever refreshing old decision evidence. |
| Orchestrator ranking | Weights 1.5 confidence, 0.8 edge, -0.4 freshness; edge normalized by 200 bps. | `v2/backend/app/services/orchestrator_arbitration/proposal.py:25-30,98-133`; service called at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1120-1121`. | P1 ranking knot. Normalize from current distributions and calibrate utility after cost. |
| Major-symbol processing priority | Literal `BTCUSDT/ETHUSDT/SOLUSDT` group first, then descending confidence inside each group. | Constant `v2/backend/app/cli/v2_trade_management_paper_loop.py:30272`; active stable sort before per-cycle exposure/reservation consumption at `v2/backend/app/cli/v2_trade_management_paper_loop.py:41303-41315`. | P1 operator-scope ordering. It does not bypass gates, but under finite cycle, margin, exposure, or attempt capacity it can change which symbols consume resources first and therefore reshape outcome/trainer evidence. Preserve unless authorization changes; report starvation by symbol. |
| Directional collapse | Minimum 50 total, 50 minority, majority share 0.90; adaptive path only tightens. | Constants `v2/backend/app/cli/v2_trade_management_paper_loop.py:292-297`; guard `v2/backend/app/cli/v2_trade_management_paper_loop.py:28734-28843`; called `v2/backend/app/cli/v2_trade_management_paper_loop.py:43672-43674`. | P1 diversity control. Compare closes with PIT opportunity supply and posterior concentration, not fixed close shares alone. |
| Strategy-mode collapse | Minimum 50 and top share 0.80, with opportunity-supply posterior when valid. | Constants `v2/backend/app/cli/v2_trade_management_paper_loop.py:298-316`; guard `v2/backend/app/cli/v2_trade_management_paper_loop.py:29556-29779`; called `v2/backend/app/cli/v2_trade_management_paper_loop.py:43675-43691`. | P1, partially repaired. Remove static fallback only after PIT supply evidence is reliably available. |
| Re-entry/dedup | Looks back 1,500 rows; default cooldown 300 s. | Constant `v2/backend/app/cli/v2_trade_management_paper_loop.py:392-393`; material-change/cooldown `v2/backend/app/cli/v2_trade_management_paper_loop.py:14000-14038`; gate `v2/backend/app/cli/v2_trade_management_paper_loop.py:14097-14189`; called `v2/backend/app/cli/v2_trade_management_paper_loop.py:43012-43031`. | Identity duplicates and same finalized candle remain hard; cooldown should follow thesis cadence, new independent evidence, and hazard. |
| Standalone 1m eligibility | Requires explicit/named dedicated bucket or PAPER-only label-collection priority. | Gate `v2/backend/app/cli/v2_trade_management_paper_loop.py:13731-13853`; actively called at `v2/backend/app/cli/v2_trade_management_paper_loop.py:42992-43011`. | `CONDITIONAL-LANE`, not inactive. It binds only standalone 1m theses and is operator/strategy-scope policy rather than a market magnitude. |
| Allocator confidence/edge/vol/regime transforms | Live confidence subtracts 0.50/0.25; edge `/80`; volatility `80/max(20,vol)` clamped 0.20-1.25; regime 0.2-1.25. | `v2/backend/app/services/adaptive_capital_allocator/sizing_model.py:10-41,68-94`; consumed by `_allocate` at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1245-1282`. | P1 sizing knots. PAPER already uses continuous confidence from zero; learn scales from PIT distributions while keeping monotonic caps. |
| High-precision orchestrator mode | 0.60 confidence, 5 bps, 80% coverage. | Config/gate `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:576-584,835-866`; conditional on `V2_HIGH_PRECISION_PAPER_MODE` at `v2/backend/app/cli/v2_orchestrator_arbitration_loop.py:1057-1065`. | `CONDITIONAL-LANE`; ordinary accepted candidates bypass it. Do not mistake it for canonical global policy. |
| Alternate `paper_online_runtime` high-precision gate | 0.75 confidence, 15 bps, 85% coverage, integrity 70, 12 feature families, two TFs, positive order-book alignment. | `v2/backend/app/services/paper_trade_management/high_precision_gate.py:47-87,122-245`; called at `v2/backend/app/cli/paper_online_runtime.py:1648-1666`. | `CONDITIONAL/ALTERNATE`; canonical owner validation requires this runtime disabled. |

## Inactive, shadow, or non-canonical lanes

| Component | Evidence it is not canonical admission authority | Consequence |
|---|---|---|
| Generic risk toxicity 0.85 | Defined in `v2/backend/app/services/risk_gateway/evaluators.py:323-340` and called only if `risk_context` includes `toxicity_score` in `v2/backend/app/services/risk_gateway/service.py:127-176`. The canonical risk loop invokes the evaluator with only `decision` and `trust_gate_result` at `v2/backend/app/cli/v2_risk_gateway_live_loop.py:852-857`. | Do not count the generic 0.85 as a current binding risk gate. Wiring it later would create a new P0 cliff. |
| Alpha/liquidity risk evaluator | `evaluate_alpha_liquidity_risk` is defined in `v2/backend/app/services/risk_gateway/alpha_liquidity.py:29-98`; repository consumers are the remediation CLI and tests, not the canonical risk loop. | Diagnostic/remediation only. Integrating it requires explicit call-chain and contract tests. |
| Generic orchestrator low-confidence service | The service supports a threshold in `v2/backend/app/services/orchestrator_decision/service.py:37-92`, but the native trainer publisher passes `low_confidence_threshold=0.0` at `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:3079`. | Threshold is present but non-binding in that producer lane. |
| Standalone preemptive `v2/backend/app/services/preemptive_edge_control/loss_probability.py` | The file reads tuner state internally, but canonical `v2/backend/app/services/preemptive_edge_control/decision.py` imports `candidate_loss_risk`, not this module. | Do not tune it expecting canonical PAPER behavior. It should remain clearly deprecated or be removed after dependency proof. |
| Runtime tuner shadow | Writes only `v2:diagnostic:adaptive_gate_tuning:runtime_tuner_shadow`, marks itself non-authoritative, and reads only exact fresh canonical state in `v2/backend/app/services/adaptive_gate_tuning/runtime_tuner.py:14-24,113-184,193-212`. | Its many fixed diagnostic thresholds do not control admission. Preserve namespace separation. |
| Static soak lists | `v2/backend/app/services/paper_trade_management/outcome_memory.py:34-35,520-543` identifies them as advisory only. | They are historical metadata, not current deny authority. |

## Authorized leverage and margin envelope to preserve

The leverage envelope is explicitly authorized by the operator and is not part of the remediation target. Its fixed ceilings are authority boundaries, not grants.

### Leverage authority chain

1. `symbol_leverage_ceiling` returns operator-configurable ceilings of 75x for BTC/ETH, 50x for SOL/LTC/XRP, and 20x for other symbols at `v2/backend/app/services/paper_trade_management/leverage_recommendation.py:55-74`.
2. `_liquidation_safe_max_leverage` enforces approximately `leverage <= 10000 / (safety_atr_multiple * ATR_bps + fee_buffer_bps)` at `v2/backend/app/services/paper_trade_management/leverage_recommendation.py:77-90`.
3. `recommend_leverage_for_signal` fixes weak/non-positive/flat/high-volatility cases to 1x, then interpolates continuously through confidence, after-cost edge, and volatility within the ceiling at `v2/backend/app/services/paper_trade_management/leverage_recommendation.py:161-242`. These fixed branch values are an explicitly preserved exception to the no-static-market-threshold objective because the operator directed this envelope to remain as implemented.
4. The recommendation always returns isolated PAPER margin, no exchange mutation, and no all-symbol aggregate authority at `v2/backend/app/services/paper_trade_management/leverage_recommendation.py:268-315`.
5. `calculate_dynamic_risk_envelope` returns the supplied base unchanged for live, applies the authorized symbol/global ceiling for PAPER, weights realized evidence continuously as `n/(n+25)`, requires positive PIT-safe edge/liquidity/regime evidence for growth, contracts risk under losses/drawdown, and interpolates leverage toward the ceiling only on favorable evidence at `v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py:128-193,227-356`.
6. `_adaptive_leverage_target_selection` calls the recommendation, caps by the risk envelope and symbol authority, computes continuous candidate quality, and selects `min(recommendation, 1 + (envelope_cap - 1) * quality)` at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:420-546`.
7. The canonical PAPER input explicitly supplies permitted values `(1, 2, 3, 5, 10, 20)` at `v2/backend/app/cli/v2_trade_management_paper_loop.py:40939-40945`. This discrete set is an additional binding ceiling: BTC/ETH 75x and SOL/LTC/XRP 50x are authority ceilings, but this call site cannot select above 20x. Preserve this exact effective envelope under the operator's “keep as is” direction.
8. `_select_margin_configuration` then searches only safe permitted leverage values at or below the continuous evidence target; PAPER cannot raise leverage to compensate for scarce margin, and free-margin/liquidation checks remain binding at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1098-1147,1538-1580`.

### Margin contract

- PAPER margin mode is isolated. Cross margin is not recommended because the current model has no account-wide cross-collateral liquidation proof: `v2/backend/app/services/paper_trade_management/leverage_recommendation.py:14,278,311-312`.
- `_adaptive_margin_mode_selection` computes continuous diagnostics but returns isolated for live and PAPER under the current authority at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:549-660`.
- `maintenance_margin_rate` must come from symbol/tier evidence for PAPER; the contract explicitly forbids a generic fabricated rate at `v2/backend/app/services/adaptive_capital_allocator/contracts.py:58-64`.
- Allocation uses post-quantization notional for margin, liquidation, and accounting at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1494-1531,1538-1588`.

### Required leverage regressions

- Strong positive after-cost evidence must demonstrate selected PAPER leverage above 1x when the dynamic envelope, liquidation distance, permitted values, margin, and symbol ceiling all allow it.
- Non-positive after-cost edge must remain 1x or be blocked; confidence alone cannot raise leverage.
- Selected leverage must never exceed recommendation, dynamic envelope, symbol ceiling, permitted values, or liquidation-safe capacity.
- Every PAPER result must remain `paper_only=True`, isolated, and non-mutating.
- Live output must be byte-for-byte/equality unchanged for PAPER-only quality/envelope inputs.

Existing source-level regression anchors prove the intended behavior: above-1x PAPER selection, adverse-evidence contraction, margin derivation, and no live mutation in `v2/backend/tests/unit/services/adaptive_capital_allocator/test_adaptive_leverage_margin_ramp.py:46-195`; continuous target response and a concrete 2x selected/effective result in `v2/backend/tests/unit/services/adaptive_capital_allocator/test_allocator.py:640-725`; and favorable PIT evidence, 75x/50x/20x ceiling enforcement, and no growth from summary metrics alone in `v2/backend/tests/unit/services/adaptive_capital_allocator/test_dynamic_envelope.py:78-140`. These tests establish contract behavior, not current market profitability or runtime evidence quality.

## Minimum-order risk breach and repaired contract

### Historical breach shape

The pre-repair ordinary PAPER path could calculate a tiny risk-limited target and then raise it to the venue minimum whenever the gross ceiling could hold that minimum. A handoff reproduction used equity 10,000, confidence 0.001, after-cost edge 0.001 bps, 100 bps stop, and a 5 USD minimum. The adaptive risk budget was approximately `0.00000148 USD`, while the 5 USD uplift implied approximately `0.052 USD` modeled loss, roughly 35,135 times the budget. The observation describes the removed behavior; current source blocks the case, so rerunning it now must not reproduce the breach.

The root error was treating a venue minimum as permission to increase risk. A venue minimum is only an executability constraint. If the risk-authorized target is below it, there is no valid order.

### Current repaired formula and sequence

`AllocationInput` now carries both `paper_risk_budget_fraction` and `paper_quality_sizing_weight` as independent `(0,1]` upper bounds at `v2/backend/app/services/adaptive_capital_allocator/contracts.py:90-100`. They are validated at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:94-152` and hash-bound to every PAPER allocation at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:291-335`.

For PAPER:

```text
risk_budget = equity
            * adaptive_budget_pct
            * paper_risk_budget_fraction
            * paper_quality_sizing_weight

gross_ceiling = envelope_gross_ceiling
              * paper_risk_budget_fraction
              * paper_quality_sizing_weight

modeled_loss_bps = stop_distance_bps
                 + max(fee_bps, 0)
                 + max(slippage_bps, 0)
                 + abs(expected_funding_bps)

target_notional = min(
    risk_budget / (modeled_loss_bps / 10000),
    gross_ceiling,
)
```

The implementation is `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1235-1317`. If `target_notional < venue_minimum`, every PAPER allocation blocks instead of rounding up at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1318-1362`. Quantity is then rounded down and min/max quantity/notional are rechecked at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1367-1455`. Margin/liquidation and result accounting use that exact post-quantization quantity/notional at `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1538-1632`.

Regression coverage is in `v2/backend/tests/unit/services/adaptive_capital_allocator/test_paper_quality_sizing_invariant.py:46-200`: `(0,1]` validation, monotonic contraction, modeled maximum loss never above quality-weighted budget, all loss components, no minimum-order uplift, hash binding, and unchanged live allocation.

## Field-level change-impact map

| Field or contract | Producer/source | Direct consumers | Small change can affect |
|---|---|---|---|
| `event_time`, `available_at`, `feature_cutoff`, `decision_time`, candle times | Feature/trainer prediction and publisher | Orchestrator temporal gate, risk trust, paper decision dereference, tuner evidence, replay | Route eligibility, leakage status, grade validity, risk authority, training admission, forensic replay. Never alias these clocks. |
| `prediction_id`, `signal_id`, `orchestrator_decision_id`, `risk_decision_id` | Publisher/orchestrator/risk | Per-ID stores, paper dereference, allocator lineage, fill write invariant, ledger/trainer feedback | Any formatting/derivation change can orphan downstream authority and turn every candidate into pending/blocked. |
| `feature_snapshot_id`, feature hash, source hashes | Feature/trainer/publisher | Orchestrator exact lookup, risk record, paper dereference, allocator receipt, trainer replay | Hash/identity mismatch blocks the entire route and can invalidate training evidence. |
| `selected_action` / `side` | Trainer/publisher | Signed-edge conversion, orchestrator proposal, risk transition, entry/A+/preemptive, allocator, leverage, exit | A side convention change reverses edge interpretation and can turn favorable SHORT evidence into adverse evidence. |
| `expected_move_after_cost_bps` | Trainer plus publisher cost recompute | Orchestrator ranking, entry direction, fee gate, A+/preemptive, allocator, leverage, performance feedback | Sign affects eligibility; magnitude affects rank, size, leverage, loss probability, fee ratio, and expected PnL. |
| `confidence_calibrated` and calibration proof | Trainer | Tuner bins/floors, proposal score, side/A+ gates, preemptive risk, allocator, leverage | A calibration change fans out to admission, rank, size, leverage, labels, and high-confidence loss circuits. Raw confidence must not substitute silently. |
| `market_state_integrity_score`, `valid_for_*`, reject reasons | Market-state scorer/publisher | Publisher route, orchestrator, risk trust, paper integrity, allocator, A+ | Composite threshold changes have five downstream admission effects. Critical reasons must remain separate and hard; magnitude should scale ordinary PAPER size. |
| `microstructure_trust_evidence`, `microstructure_trust_evidence_sha256`, `source_payload_sha256`, `source_observed_ttl_seconds` | Monitor payload plus trainer loader's exact transactional readback | Native publisher, ordinary evidence validator, orchestrator, risk, PAPER | Any payload/key/hash/TTL/symbol/timeframe/tensor mismatch invalidates the ordinary claim. A later fresh read is different evidence and must never repair the original decision retrospectively. |
| Microstructure trust/action, sweep, sequence, feed/latency flags | Trust publishers | Orchestrator, risk, A+, preemptive, allocator liquidity, ordinary quality | Changes route, grade, loss estimate, size, leverage quality, and exit feasibility. Missing hard feed/sequence truth cannot be replaced by a score. |
| Side/outcome closed rows | PAPER ledger/feedback | Side gate, outcome memory, A+, preemptive buckets, performance circuit, tuner, dynamic envelope, trainer | Row classification/session/time errors can globally halt entries or incorrectly grow leverage. One row projected into many buckets is still one observation. |
| `paper_quality_sizing_weight` | Ordinary admission evidence | Orchestrator/risk transport, paper revalidation, `AllocationInput`, allocator hash/risk/ceiling | Must change budget and gross ceiling monotonically, never grant admission, never alter live, and fail on evidence/hash mismatch. |
| `paper_risk_budget_fraction` | Reservation/recovery policy | `AllocationInput`, allocator budget/ceiling, quantization, margin/liquidation, lifecycle reservation | Any change requires complete reallocation; mutating an already completed allocation corrupts loss and margin accounting. |
| Dynamic envelope `max_effective_leverage` and risk fields | Performance + PIT market context | Allocator leverage/risk budget, lifecycle exposure caps, reservation evidence | More leverage/risk only on positive trusted evidence; stale/missing evidence must contract, never expand. |
| `permitted_leverage_values` | Canonical PAPER `AllocationInput` builder; allocator contract default for other callers | Margin configuration search, selected leverage, allocated margin, liquidation buffer | The canonical set `(1,2,3,5,10,20)` makes leverage selection stepwise and caps the runtime below wider 50x/75x symbol authority. Adding a value can reduce required margin but also reduce liquidation distance; removing one can force a lower safe choice or no allocation. |
| Exchange `min_qty`, `step_size`, `max_qty`, `min_notional` | Current symbol filter snapshot | Allocator quantization and fill write invariant | Can turn a valid theoretical target into no order. Never round risk upward to satisfy the venue. |
| `maintenance_margin_rate`, permitted leverage | Symbol/tier evidence and authority | Margin search, liquidation price/buffer, allocated margin | A small rate change shifts safe leverage and liquidation buffer; generic defaults make all downstream liquidation evidence fictitious. |
| Operator leverage environment variables | Operator-authorized config | Standalone recommendation, dynamic envelope, allocator | Changes absolute PAPER headroom across many candidates. It does not prove edge and must not mutate live exchange settings. |

## Function-level blast-radius map

| Function | Exact source | Immediate output | Downstream blast radius |
|---|---|---|---|
| `score_market_state` | `v2/backend/app/services/market_state_integrity/scoring.py:165-309` | Composite score, `valid_for_*`, reject reasons | Publisher routing, orchestrator hold, risk trust, PAPER integrity, allocation quality, training cleanliness. |
| `build_prediction_payload` / `PredictionPublisher.publish_prediction` | `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py:1584-2431,2586-2838` | Canonical native prediction/routing row and current-key write | Every orchestrator proposal and all downstream immutable authority; changing a field name, hash, clock, or current-key write contract can sever the entire route. |
| `build_prediction_row` / `build_signal_from_row` | `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py:1905-2332,3060-3338` | Derived prediction/signal view | Per-symbol signal visibility and legacy candidate observations. It does not own the authoritative current prediction write or grant decision authority by itself. |
| `assess_ordinary_paper_candidate` / `revalidate_ordinary_paper_transport` | `v2/backend/app/services/ordinary_paper_admission.py:564-767` | Hash-bound ordinary claim and continuous weight | Publisher/orchestrator/risk/paper transport and allocator binding are staged; the paper boundary remains validation-blocked until its exact-read/tamper/allocator tests pass. A bypass without independent consumer verification is unsafe. |
| `_paper_exact_json_with_ttl` / `_paper_ordinary_transport_assessment` | `v2/backend/app/cli/v2_trade_management_paper_loop.py:40987-41055` | Consumer-local exact replay/source observation and shared assessment | Controls whether the PAPER boundary may ignore legacy market-magnitude booleans. Any non-transactional read, key alias, missing TTL, or silent decode fallback can admit a changed generation or incorrectly reject every ordinary candidate. |
| `_paper_final_admission_point_in_time_contract` | `v2/backend/app/cli/v2_trade_management_paper_loop.py:34797-38280` | Final append PASS/BLOCK receipt | Rechecks current ordinary sources, allocation input, lineage, filters, margin, clocks, reservations, and revocable controls immediately before materialization. A small projection/hash change can block every fill; omitting a governing field can let post-allocation mutation escape detection. |
| `score_proposal` | `v2/backend/app/services/orchestrator_arbitration/proposal.py:98-133` | Per-bucket arbitration utility | Which candidate reaches risk; weights indirectly reshape symbol/side/timeframe opportunity supply and outcome feedback. |
| `assemble_risk_decision_record` | `v2/backend/app/services/risk_gateway/service.py:89-245` | Canonical allow/deny | Per-ID risk authority, PAPER dereference, fill eligibility, replay. |
| `route_strategy` | `v2/backend/app/services/strategy_router/service.py:682-1137` | Mode, labels, fixed size multiplier, block reason | Direct paper no-trade/mode/size decision before entry. It mixes hard temporal/transition truths with market/performance cliffs, so changing one config value or literal override reshapes both opportunity supply and the feedback used to tune later gates. |
| `interpret_ordinary_paper_router_result` | `v2/backend/app/services/strategy_router/ordinary_paper_interpretation.py:340-489` | PAPER-only hard/soft interpretation and absolute continuous weight | Currently inactive because no canonical consumer calls it. Once integrated, its hard-reason classification and factor completeness determine whether a legacy router block remains binding and how much allocator risk survives; any newly introduced router reason fails only if the integration preserves its fail-closed contract. |
| `evaluate_entry_gate` | `v2/backend/app/services/paper_trade_management/entry_gate.py:257-483` | P0 allow/reasons | Direct PAPER admission and source of `P0_ENTRY_GATE_BLOCKED`; also changes which outcomes can ever refresh its own evidence. |
| `evaluate_a_plus_candidate` | `v2/backend/app/services/a_plus_trade_gate/service.py:608-710` | A+ grade/all-check result | Strict grade, bootstrap/ordinary tiering, monitoring, live-candidate evidence; must not be forced true. |
| `evaluate_candidate` | `v2/backend/app/services/preemptive_edge_control/decision.py:498-1001` | Loss probability/action/reasons | PAPER tier, size reduction, no-trade, performance feedback, accepted-fill invariant. |
| `_paper_performance_circuit_breaker_status` | `v2/backend/app/cli/v2_trade_management_paper_loop.py:25083-25325` | Global/bucket halt state | New-entry freeze, recovery/exploration routing, evidence flow, operator status, tuner outcome availability. |
| `calculate_dynamic_risk_envelope` | `v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py:128-356` | Risk and leverage authority | Allocator risk budget, exposure caps, leverage, margin reservation, lifecycle accounting. |
| `_build_allocation_input` | `v2/backend/app/cli/v2_trade_management_paper_loop.py:40051-40984` | Complete economic contract | Every allocator result. Missing/aliased fields contaminate notional, leverage, margin, liquidation, and max-loss reporting together. |
| `_allocate` / `allocate_paper_candidate` | `v2/backend/app/services/adaptive_capital_allocator/allocator.py:1150-1640` | Quantity/notional/risk/leverage/margin/liquidation receipt | Accepted PAPER fill, open exposure, ledger, outcomes, trainer feedback, subsequent dynamic envelope. |

## Validation evidence at this snapshot

| Validation slice | Result | What it proves | What it does not prove |
|---|---:|---|---|
| Native trainer/helper/orchestrator/risk/microstructure focused suite | 96 passed | Exact trainer source evidence, native ordinary claim, orchestrator/risk revalidation, structural versus magnitude separation. | Canonical PAPER consumption or forward profitability. |
| All-timeframe derived-signal unit/integration suite | 58 passed | Ordinary derived branch, bounded current TTL, tamper/expiry/PIT refusal, and monotonic sizing. | Authority to fill without per-ID decisions and PAPER revalidation. |
| Combined native/ordinary/all-timeframe/orchestrator/risk regression | 90 passed | The selected upstream contract composes without an observed regression. This suite overlaps the two slices above and must not be added to them as independent coverage. | Final PAPER append, all repository tests, live runtime health, or A+ outcomes. |
| `v2/backend/tests/unit/cli/test_v2_trade_management_ordinary_paper_admission.py` | 11 passed | Transactional initial source/replay reads, TTL 0/-1/-2 refusal, transport tamper, unchanged legacy score gate, allocator weight/hash binding, missing-weight veto. | Final-append reread and final allocator weight/evidence-lineage mismatch; status remains P0 blocked. |
| Selected existing canonical PAPER admission regression (`-k 'paper_signal_integrity_gate or build_allocation_input or final_admission or persisted_admission'`) | 36 passed, 505 deselected | No observed regression in selected existing integrity, allocation-input, final-admission, and persisted-admission cases. | It does not add the missing ordinary final-append reread/mismatch cases or causal router-input tests; it is partial regression evidence only. |
| Complete strategy-router unit directory | 50 passed | Hard/soft classification, epsilon continuity, monotonic factors, missing/unknown failure, and unchanged legacy router tests for the isolated interpreter. | Canonical use: the interpreter has no PAPER consumer in this snapshot. |
| PAPER quality, adaptive leverage/margin ramp, and dynamic-envelope focused suites | 45 passed | No minimum-order risk uplift, monotonic quality contraction, above-1x PAPER behavior, authorized tier ceilings, adverse contraction, and unchanged live behavior. | Current Redis evidence quality, actual runtime leverage distribution, or 1000x feasibility. |

These are source-level contract results from the shared uncommitted handoff tree. They are not statistically independent sample evidence, do not certify the full repository, and must be rerun after the final integration diff.

## Phased remediation plan

### Phase 0 — freeze truth and authority

- Freeze live execution behavior, exchange mutation, authorized leverage ceilings, isolated margin, risk/loss caps, exact per-ID decision authority, temporal ordering, final candles, hashes, finite/range validation, exchange filters, and valid position transitions.
- Add a machine-readable allowlist distinguishing hard invariants/authorized envelope constants from market-magnitude constants. A raw numeric-literal scan without semantic classification is insufficient.
- Capture characterization tests for every P0 gate at `threshold-epsilon`, `threshold`, and `threshold+epsilon` before replacement.

### Phase 1 — complete one scale-free ordinary PAPER lane end to end

- Publisher: produce an ordinary PAPER claim only from immutable clean evidence, positive signed after-cost edge, exact cost provenance, and a continuous quality weight.
- Orchestrator: independently rebuild the evidence hash, recheck identity/PIT/finality/hard market-state reasons, and treat market score/trust/sweep magnitudes as size factors rather than boolean authority.
- Risk: independently revalidate the transported evidence and permit no ordinary claim to bypass hard trust, canonical orchestrator record, position, loss, or live gates.
- PAPER: independently revalidate exact risk/orchestrator records and ordinary evidence; pass the final continuous weight into `AllocationInput`.
- Allocator: apply the weight to both risk budget and gross ceiling before filters; block below venue minimum and re-derive all leverage/margin/liquidation fields.
- Require tamper, missing-field, stale-time, wrong-ID, wrong-producer, and legacy-claim downgrade tests at every boundary.

### Phase 2 — remove canonical P0 market cliffs

- Replace short cascade and symbol denylist with current continuous cascade, gap, depth, impact, and liquidity loss factors.
- Replace side/outcome fixed samples and rates with time-decayed posterior after-cost expectancy and calibration uncertainty.
- Convert A+ market confirmations into a calibrated grade score with evidence intervals; keep required provenance/risk/exit truths conjunctive.
- Replace preemptive decision ladders with a calibrated loss/exit distribution whose output is a continuous risk multiplier plus hard invariant vetoes.
- Consolidate fee/edge evaluation into one residual-edge distribution and remove duplicate evaluation.
- Replace performance-circuit sample/count/rate cliffs with sequential posterior evidence, unique-row accounting, opportunity-supply normalization, and bucket-scoped contraction before global halt.
- Replace tuner bins, fixed grade toggles, and regime offsets with online calibration/posterior updates. Preserve canonical session/PIT/hash authority and restrictive no-evidence behavior.

### Phase 3 — remove P1 knots without weakening caps

- Derive freshness from timeframe close cadence, observed publisher latency, and source-specific delay distributions.
- Calibrate orchestrator utility weights on forward after-cost utility and normalize by current regime distributions.
- Make re-entry timing depend on new finalized thesis evidence and empirical re-entry hazard, while exact duplicate IDs/candles remain hard.
- Learn allocator edge/volatility/regime scales from PIT distributions and assert monotonicity, boundedness, and loss-budget dominance.
- Keep the authorized leverage/margin envelope unchanged; validate that profitable, low-risk evidence can actually earn above 1x within it.

### Phase 4 — shadow comparison and controlled PAPER promotion

- Run old and new market policies side by side from identical immutable snapshots; only the existing canonical path may write accepted fills during shadow.
- Record per-candidate old decision, new continuous weight, hard-invariant result, allocation, counterfactual fill, and eventual after-cost outcome.
- Promote one component at a time only after no invariant regression, no discontinuity at the retired threshold, calibrated forward outcomes, and no live diff.
- Do not use reconstructed, future, mixed-session, alternate-runtime, or non-strict exploration rows as A+ promotion evidence.

## Regression and A+ evidence criteria

### Mandatory code/contract regressions

- Every producer-to-consumer ID/hash/time field round-trips exactly through publisher, orchestrator, risk, PAPER, allocation, accepted fill, close, and trainer feedback.
- The trainer's exact microstructure source payload, canonical key, remaining positive TTL, payload hash, tensor/snapshot/lineage identity, and decision clocks round-trip unchanged; mutation, expiry, persistence, cache substitution, or a later fresh read always blocks the original candidate.
- PAPER observes the exact source prediction and replay payload plus TTL transactionally at both initial integrity admission and final append. Missing, changed, expired, persistent, wrong-key, wrong-ID, wrong-symbol/timeframe, or larger-than-prior TTL evidence blocks; the final revalidated weight/hash must equal the sealed allocator input and lineage.
- Future `available_at`, future `feature_cutoff`, unclosed candle, MASA/PPO inversion, stale/expired per-ID record, wrong producer, wrong side, wrong snapshot, dirty required feature, NaN/Inf, or invalid position transition always blocks.
- For retired market thresholds, epsilon changes in valid market evidence produce continuous size/grade changes, not binary admission jumps.
- Continuous quality/risk weights are monotone, bounded in `(0,1]` when admitted, hash-bound, and can only contract budget/ceiling.
- `max_loss_if_stop_hit <= risk_budget_usd` for every allowed PAPER allocation, including fees, slippage, funding, overshoot, quantization, and reduced-risk paths.
- A target below venue minimum blocks; quantization always rounds down and rechecks every exchange filter.
- Strong trusted evidence can earn PAPER leverage above 1x; weak/non-positive edge cannot. All leverage/margin/liquidation caps remain binding.
- PAPER-only fields and policy changes produce no live-allocation, live-gate, exchange SDK, order-submit, cancel, or modification diff.
- Only one canonical PAPER writer is active; `paper_online_runtime` and toy/duplicate writers remain disabled.

### Runtime end-to-end evidence

- Fresh `v2:prediction:{symbol}:{timeframe}` rows contain exact final-candle/PIT/feature/checkpoint/cost/calibration lineage.
- Every routed candidate has dereferenceable, unexpired `v2:decision:orchestrator:{id}` and `v2:decision:risk:{id}` records owned by the exact producers.
- Ordinary continuous quality is identical after independent recomputation in orchestrator, risk, PAPER, and allocation material.
- Allocator receipts expose input hash, modeled-loss components, pre/post weight budgets and ceilings, post-quantization quantity/notional, leverage caps, isolated margin, maintenance evidence, and liquidation buffer.
- Accepted fills pass the write invariant and later close with realized after-cost PnL, MFE/MAE, costs, exit reason, policy version, and the original immutable lineage.
- Monitoring distinguishes no candidate, invariant block, market-quality contraction, exchange-minimum block, risk/margin block, and runtime failure. Zero fills is not automatically a runtime failure; missing heartbeats or broken lineage is.

### Evidence-based A+ definition

An A+ implementation grade requires all mandatory tests and exact runtime evidence to pass. An A+ candidate grade requires clean PIT evidence, calibrated forward probability, positive conservative after-cost edge, valid risk/allocation/exit plans, and no hard invariant failure. It does not require every candidate to trade, and it cannot be awarded from code coverage, backfilled outcomes, a single successful fill, or a target return assertion.

No code audit can certify that the system will reach 1000x. The defensible milestone is a fully functioning trainer-to-close feedback loop, adaptive PAPER admission without market cliffs, correct leverage/margin use within authorization, and statistically credible forward after-cost evidence with controlled drawdown. Only that evidence can justify later operator decisions.
