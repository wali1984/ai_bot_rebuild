# Phase 1 External Position Quarantine Plan V2

## 1. Corrected Failure Model
- In the retained execution window, `RAVEUSDT` exposure was **manual-origin**.
- The bot did **not** originate `RAVEUSDT` exposure in that retained window.
- The bot **adopted** and then **managed** this manual-origin inventory.
- The failure to fix is **unsafe external/manual position management**, not model entry logic.
- Therefore Phase 1 is a control-plane safety retrofit focused on provenance, quarantine, and fail-closed execution policy for non-system inventory.

## 2. Design Objective
Establish a fail-safe contract where external/manual/unknown inventory cannot receive risk-adding behavior. The bot may observe and de-risk such inventory, but may not expand risk, reshape leverage, or perform strategy-driven re-entry.

Safety principles:
1. Immutable provenance first.
2. Quarantine by default for non-system inventory.
3. Reduce-only policy for quarantined inventory.
4. Explicit lineage for every risk-affecting event.
5. Fail-closed under degraded state and orchestrator stall.

## 3. Hard-Ban Matrix

| Position Class | OPEN | INCREASE | ADD_HEDGE | DCA | SCALE | FLIP | ADJUST_LEVERAGE | ADJUST_LEVERAGE_AND_POSITION | Hedge Expansion | Manual Hedge Cap Override | Cross-Margin Rescue | Strategy Re-entry | Allowed by Policy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXTERNAL_MANUAL | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | observe, alert, mark provenance, reduce-only close, protective stop/TP, emergency flatten (strict account-protection rules) |
| UNKNOWN_EXTERNAL | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | BAN | observe, alert, mark provenance, reduce-only close, protective stop/TP, emergency flatten (strict account-protection rules) |

Policy notes:
- Emergency flatten is allowed only when account-protection rules trigger and must be reduce-only where exchange semantics permit.
- Any violation routes to skip/audit event with explicit reason code and lineage fields.

## 4. Position Provenance Schema
Add immutable provenance envelope per leg/position record:
- `position_id`
- `origin_kind` ∈ {`SYSTEM`, `EXTERNAL_MANUAL`, `UNKNOWN_EXTERNAL`}
- `origin_source` (module/process/source stream)
- `origin_first_seen_ts_ms` (immutable once set)
- `origin_version` (schema version)
- `origin_evidence` (hash or reference bundle)
- `adoption_id` (required for adopted manual/external inventory)
- `management_plan_id` (required once management policy attaches)
- `quarantine_state` ∈ {`QUARANTINED`, `RELEASED_BY_POLICY`}
- `quarantine_reason_code`

Immutability rules:
- `origin_first_seen_ts_ms`, `origin_kind`, and `origin_evidence` cannot be overwritten by normal execution paths.
- Any transition to `SYSTEM` must be explicit reconcile workflow with dedicated reason code and audit trail.

## 5. Provenance Detection Rules
Provenance resolution priority:
1. Matching system-origin execution lineage (valid parent decision + exchange order lineage in retained window) → `SYSTEM`.
2. Explicit manual/operator evidence (manual action metadata / adoption scan evidence) → `EXTERNAL_MANUAL`.
3. No provable bot-origin lineage in retained window + active inventory present → `UNKNOWN_EXTERNAL`.

Required explicit rule for RAVE:
- If `RAVEUSDT` has no retained-window bot-origin lineage and was adopted/managed post-discovery, classify as `EXTERNAL_MANUAL` or `UNKNOWN_EXTERNAL` (never `SYSTEM` by default).

## 6. Patch Order
Use exact safe order below.

### Patch 1 — Provenance schema + immutable first-seen evidence
- Files/functions:
  - `trading/trader.py`: `_position_origin_key()`, `_get_position_origin()`, `_set_position_origin()`, `_adopt_unmanaged_positions()`
  - `trading/base_executor.py`: attribution payload helper paths
  - `config.py`: schema/version and strict provenance flags
- Current behavior:
  - origin exists but mutable/partial; adopted path lacks strict immutable contract.
- Desired behavior:
  - immutable provenance envelope and required IDs (`position_id`, `adoption_id`, `management_plan_id`).
- Tests:
  - immutable fields cannot be overwritten on repeated sync/adoption.
  - RAVE classification reproducible from retained evidence.
- Rollback condition:
  - any incompatibility with existing position readers; rollback via provenance strict kill switch.

### Patch 2 — External/manual quarantine enforcement
- Files/functions:
  - `trading/trader.py`: pre-execution gate before `_execute_open/_execute_close/_execute_partial_close/_execute_adjust_lev_and_size`
  - `trading/stealth_stops.py`: ensure only protective reduce-only actions for quarantined legs
  - `trading/signal_router.py`: preserve provenance/quarantine tags
  - `config.py`: quarantine policy toggles
- Current behavior:
  - adopted inventory can receive normal strategy handling.
- Desired behavior:
  - apply hard-ban matrix for `EXTERNAL_MANUAL` and `UNKNOWN_EXTERNAL`.
- Tests:
  - risk-add blocked; reduce-only protective allowed by policy.
- Rollback condition:
  - protective exits blocked unexpectedly.

### Patch 3 — Disable/gate manual hedge override
- Files/functions:
  - `trading/trader.py` hedge pair cap block path
  - `rl/hedge_manager_v3.py` manual override block
  - `config.py` manual override quarantine bypass default OFF
- Current behavior:
  - manual override can expand cap.
- Desired behavior:
  - no manual hedge cap override for quarantined external/unknown inventory.
- Tests:
  - cap override not applied for manual/unknown legs.
- Rollback condition:
  - emergency de-risk cannot execute under legitimate account-protection path.

### Patch 4 — Risk assertion integration
- Files/functions:
  - `risk/assertions.py`: `is_risk_add_action()`, `assert_risk()`
  - `risk/halt_manager.py`: enforcement coupling and reason propagation
- Current behavior:
  - risk checks not fully quarantine-aware for all action families.
- Desired behavior:
  - quarantine-aware assertion codes; hard block risk-add on external/unknown.
- Tests:
  - no DCA/scale/flip/leverage adjustment for quarantined classes.
- Rollback condition:
  - false positives on protective-only exits.

### Patch 5 — Execution feedback attribution hardening
- Files/functions:
  - `trading/trader.py`: `_publish_execution_feedback()`, `_publish_execution_event()`, `_publish_exec_audit_event()`
  - `rl/trade_feedback.py`: consumer lineage validation
  - `rl/profit_bank.py`: maintain compatibility with enriched feedback
- Current behavior:
  - good telemetry, lineage incomplete for manual/external management.
- Desired behavior:
  - mandatory parent lineage and provenance fields for all risk-affecting events.
- Tests:
  - no null lineage on managed manual/external events.
- Rollback condition:
  - downstream parsers fail on new fields.

### Patch 6 — Duplicate accounting dedupe unification
- Files/functions:
  - `trading/trader.py` publish path
  - `rl/trade_feedback.py` dedupe path
  - audit/reporting readers of `executed_signals`
- Current behavior:
  - dedupe split between producer/consumer conventions.
- Desired behavior:
  - canonical `dedupe_key` and duplicate suppression on `exchange_order_id` lineage.
- Tests:
  - no duplicate `executed_signals` rows for same `exchange_order_id`.
- Rollback condition:
  - missed legitimate execution events due to over-dedupe.

### Patch 7 — Degraded-state fail-closed gates
- Files/functions:
  - `rl/orchestrator_worker.py`: gate synthesis + publish blocking
  - `risk/assertions.py`: fail-closed conditions
  - `risk/halt_manager.py`: unavailable-path behavior
  - `trading/trader.py`: trader-local enforcement fallback
  - `config.py`: thresholds/timeouts
- Current behavior:
  - degraded states not uniformly fail-closed for risk-add.
- Desired behavior:
  - risk-add blocked when any required degraded-state trigger is active.
- Tests:
  - DQ degraded and ORCH stalled both block risk-add.
- Rollback condition:
  - full signal freeze including protective actions.

### Patch 8 — Margin/leverage live blocks
- Files/functions:
  - `trading/base_executor.py`: leverage/margin guard rails
  - `trading/trader.py`: block `ADJUST_LEVERAGE*` on external/unknown
  - `config.py`: live hard limits
  - `rl/hybrid_trainer.py`: prevent strategy-origin leverage/margin directives for quarantined classes
- Current behavior:
  - leverage/margin operations can still be emitted/consumed in unsafe paths.
- Desired behavior:
  - no cross-margin/high-leverage behavior for external/unknown inventory.
- Tests:
  - leverage/margin hard blocks enforced with auditable reason codes.
- Rollback condition:
  - legitimate account safety flattening impaired.

## 7. File/Function Coverage

### `trading/trader.py`
- Why in scope: adoption, origin tagging, execution gates, execution feedback publication.
- Specific functions/classes: `_adopt_unmanaged_positions`, `_set_position_origin`, `_get_position_origin`, `_publish_execution_feedback`, `_publish_execution_event`, `_execute_adjust_lev_and_size`, pre-execution routing.
- Must change: provenance immutability, quarantine hard bans, lineage fields, dedupe key usage.
- Must not change: normal system-origin strategy semantics outside quarantine.

### `trading/base_executor.py`
- Why in scope: execution-layer margin/leverage controls and attribution recorder.
- Specific functions/classes: execution parameter validation, attribution update helpers, maker/taker execution wrapper.
- Must change: block margin/leverage risk-add for quarantined external/unknown classes.
- Must not change: exchange-safe order construction for reduce-only protective exits.

### `trading/stealth_stops.py`
- Why in scope: protective exit engine can unintentionally perform strategy-like behavior if not constrained.
- Specific functions/classes: stealth stop arming/trigger pathways.
- Must change: ensure quarantined inventory supports only protective reduce-only behavior.
- Must not change: protective stop logic for genuine system-origin positions.

### `trading/signal_router.py`
- Why in scope: source/provenance tag propagation across streams.
- Specific functions/classes: `should_route_signal`, `route_signal`.
- Must change: preserve and require provenance fields when routing managed inventory.
- Must not change: account enable/disable and confidence filtering baseline.

### `risk/assertions.py`
- Why in scope: central risk-add vs protective classification and hard blocks.
- Specific functions/classes: `is_risk_add_action`, `assert_risk`.
- Must change: quarantine-aware action blocking and degraded-state fail-closed checks.
- Must not change: existing protective pass-through for genuine emergency exits.

### `risk/halt_manager.py`
- Why in scope: halt/stress state authority; must fail-closed if unavailable.
- Specific functions/classes: halt state retrieval/enforcement interface.
- Must change: explicit handling when manager unavailable -> block risk-add.
- Must not change: existing halt-trigger semantics.

### `rl/orchestrator_worker.py`
- Why in scope: proposal arbitration, source normalization, degraded-state gate source.
- Specific functions/classes: proposal normalization, pre-publish blocking, fallback publication paths.
- Must change: quarantine-aware risk-add suppression and lineage propagation.
- Must not change: multi-proposal arbitration contract except safety gates.

### `rl/hybrid_trainer.py`
- Why in scope: upstream signal producer; must not emit unsafe directives for quarantined inventory.
- Specific functions/classes: signal payload builders and publish helpers.
- Must change: quarantine-aware emission constraints and confidence-not-applicable reason for blocked categories.
- Must not change: training/learning internals and model update loop behavior.

### `rl/hedge_manager_v3.py`
- Why in scope: manual hedge cap override and hedge add pathways.
- Specific functions/classes: pair cap and manual override decision branch.
- Must change: no override/no hedge expansion for quarantined classes.
- Must not change: protective trim/close behavior.

### `rl/trade_feedback.py`
- Why in scope: dedupe + lineage consumer integrity.
- Specific functions/classes: `ExecutionFeedbackConsumer._is_duplicate`, `_process_execution`.
- Must change: canonical dedupe key consumption and lineage validation.
- Must not change: historical calibration logic not related to execution lineage.

### `rl/profit_bank.py`
- Why in scope: consumes execution/profit feedback and can be impacted by schema changes.
- Specific functions/classes: `ingest_profit_exit_feedback`, executed signal ingestion.
- Must change: parse enriched lineage/provenance fields safely.
- Must not change: net-positive credit policy semantics.

### `config.py`
- Why in scope: all kill switches, thresholds, hard bans, and fail-closed defaults.
- Specific functions/classes: action/category gates, override flags, degraded-state thresholds.
- Must change: add explicit quarantine and degraded-state controls, default safe.
- Must not change: unrelated strategy tuning defaults.

### Audit/reporting scripts reading `executed_signals`
- Why in scope: must validate lineage completeness and manual-vs-bot PnL split.
- Specific targets (examples): audit scripts under `audit_*`, `scripts/signal_accuracy_*`, `rl/scripts/export_audit_pack.py`, and reporting readers that parse `executed_signals`.
- Must change: enforce schema checks for lineage/provenance/dedupe and separate manual-origin exposure from bot-management outcome.
- Must not change: historical report baseline math outside new split dimensions.

## 8. Degraded-State Fail-Closed Gates
Risk-add must be blocked when any of the following is true:
- `dq_source_ok=false`
- `trainer_stale=true`
- stale feature age beyond configured threshold
- stale orderbook/liquidation/volatility data
- `ORCH_STALLED`
- `ACCOUNT_PREFLIGHT_FAILED`
- HaltManager unavailable
- assert_governor unavailable

Policy:
- Risk-add: BLOCK (fail-closed).
- Protective reduce-only exits: ALLOW with explicit degraded-state reason code.

## 9. Risk Assertion Integration
Assertion outcomes to add:
- `QUARANTINE_RISK_ADD_BLOCK`
- `QUARANTINE_HEDGE_EXPANSION_BLOCK`
- `QUARANTINE_LEVERAGE_ADJUST_BLOCK`
- `DEGRADED_STATE_RISK_ADD_BLOCK`
- `ORCH_STALLED_RISK_ADD_BLOCK`
- `ACCOUNT_PREFLIGHT_RISK_ADD_BLOCK`

Assertion behavior:
- classify action by risk intent, not action text alone.
- for `EXTERNAL_MANUAL`/`UNKNOWN_EXTERNAL`, enforce hard-ban matrix first, then standard checks.

## 10. Execution Feedback and Parent Lineage
Every risk-affecting execution feedback event must include:
- `execution_id`
- `exchange_order_id`
- `position_id`
- `provenance`
- `parent_signal_id` or `parent_decision_id`
- `adoption_id` or `management_plan_id` (required for manual/external)
- `source_module`
- `reason_code`
- `dedupe_key`
- `confidence` or `confidence_not_applicable_reason`

Non-null lineage rule:
- Managed `EXTERNAL_MANUAL`/`UNKNOWN_EXTERNAL` executions cannot be emitted with null parent lineage.

## 11. Duplicate Accounting Dedupe
Canonical dedupe contract:
- Primary uniqueness: `exchange_order_id + account_id + symbol + side`
- Secondary fallback: `dedupe_key`
- Stream-level requirement: no duplicate `executed_signals` rows for same `exchange_order_id` lineage.

Audit requirement:
- duplicate detector report produced in paper mode and included in go/no-go evidence.

## 12. RAVEUSDT Regression Scenario
Scenario:
1. Create retained-window state where `RAVEUSDT` exists without bot-origin lineage.
2. Provenance classification sets `EXTERNAL_MANUAL` (or `UNKNOWN_EXTERNAL` if evidence incomplete).
3. Submit risk-add attempts (`OPEN`, `INCREASE`, `ADD_HEDGE`, `FLIP`, leverage adjust).
4. Verify all risk-add attempts blocked with quarantine codes.
5. Verify reduce-only protective actions allowed under policy.
6. Verify no manual hedge cap override/cross-margin rescue path is applied.
7. Verify execution feedback contains full lineage and dedupe fields.

Pass condition:
- no unsafe action executes; complete lineage present; no duplicate execution rows.

## 13. Tests
Required explicit tests:
1. RAVE manual long detected.
2. RAVE manual short detected.
3. RAVE classified as `EXTERNAL_MANUAL` when provenance proves manual origin.
4. Classified as `UNKNOWN_EXTERNAL` when provenance cannot be proven.
5. Risk-add blocked for manual/unknown.
6. Reduce-only allowed only by mode/policy.
7. No hedge cap override for manual/unknown.
8. No `ADJUST_LEVERAGE` for manual/unknown.
9. No `FLIP` for manual/unknown.
10. No cross-margin rescue for manual/unknown.
11. No duplicate `executed_signals` rows for same `exchange_order_id`.
12. Feedback includes provenance and parent decision ID.
13. PnL audit separates manual original exposure from bot management.
14. Risk-add blocked during DQ degraded state.
15. Risk-add blocked while `ORCH_STALLED`.

## 14. Paper-Mode Acceptance Criteria
Must all pass:
- 100% attribution on execution events.
- No duplicate execution rows.
- No risk-add on `EXTERNAL_MANUAL` or `UNKNOWN_EXTERNAL`.
- No risk-add during DQ degraded state.
- No risk-add while `ORCH_STALLED`.
- No cross-margin/high-leverage behavior for external/unknown paths.
- RAVE regression passes.
- PnL audit split passes (manual-origin exposure vs bot-management outcome).

## 15. Live-Mode Blockers
Do not proceed live if any is true:
- lineage completeness < 100% for risk-affecting events.
- any duplicate `exchange_order_id` execution rows.
- any observed risk-add on `EXTERNAL_MANUAL`/`UNKNOWN_EXTERNAL`.
- degraded-state fail-closed checks not proven.
- manual hedge cap override still reachable for quarantined classes.
- leverage adjustment paths not blocked for quarantined classes.

## 16. Rollback Plan
Rollback hierarchy:
1. Disable new quarantine enforcement flag (temporary containment) while keeping provenance writes ON.
2. If protective behavior impacted, switch to protective-only emergency mode.
3. Revert to previous commit/tag for Phase 1 planner-approved boundary.
4. Preserve all lineage logs for root-cause and replay.

Rollback trigger examples:
- protective exits blocked,
- false-positive quarantine on proven `SYSTEM` inventory,
- execution feedback consumer breakage,
- dedupe suppressing legitimate fills.

## 17. Implementation Readiness Checklist
Planning readiness is achieved only when all items are checked:
- [ ] Corrected failure model explicitly documented (RAVE manual-origin retained window).
- [ ] Hard-ban matrix complete for `EXTERNAL_MANUAL` and `UNKNOWN_EXTERNAL`.
- [ ] Patch order exactly matches required safe sequence (1..8).
- [ ] Required file/function coverage complete for all listed modules.
- [ ] Degraded-state fail-closed gates fully specified.
- [ ] Parent lineage schema mandatory and non-null for managed manual/external.
- [ ] Required tests fully enumerated.
- [ ] Paper-mode acceptance criteria include attribution, dedupe, degraded-state, ORCH-stall, RAVE, and PnL split.
- [ ] Live blockers explicitly defined.

Status target after follow-up review: `Verdict: PASS` and `Implementation readiness: READY_FOR_PATCH_1`.
