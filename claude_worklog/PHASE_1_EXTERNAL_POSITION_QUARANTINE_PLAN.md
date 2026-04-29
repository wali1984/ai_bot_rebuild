# PHASE 1 — External/Manual Position Quarantine + Provenance Hardening (Plan Only)

## Scope
This document is a **design-only** implementation plan. No source code changes are included here.

Goal: prevent repeat failures where external/manual inventory is treated as normal alpha inventory and then managed by risk-add or destructive unwind paths.

## Evidence Baseline (current behavior)
- Manual/external PnL can mask system losses (audit split): [April-20.md](April-20.md#L22-L43), [April-20.md](April-20.md#L64-L76).
- Known large loss event example: `RAVEUSDT CLOSE_LONG` via `hedge_intel_full_unwind`: [April-20.md](April-20.md#L353-L364).
- Trader already has adoption + origin plumbing:
  - `POSITION_ADOPTION_ENABLED`: [config.py](config.py#L1309-L1313)
  - `_set_position_origin()` / `_get_position_origin()`: [trading/trader.py](trading/trader.py#L4863-L4910)
  - `_adopt_unmanaged_positions()`: [trading/trader.py](trading/trader.py#L5116-L5241)
  - periodic adoption scan in main loop: [trading/trader.py](trading/trader.py#L23898-L23910)
- Manual hedge cap override exists and can expand risk budget:
  - config flags: [config.py](config.py#L348-L353)
  - trader enforcement path: [trading/trader.py](trading/trader.py#L10758-L10775)
  - hedge-manager path: [rl/hedge_manager_v3.py](rl/hedge_manager_v3.py#L1174-L1214)
- Execution attribution + feedback already exist:
  - trader execution feedback payload: [trading/trader.py](trading/trader.py#L19631-L20129)
  - exec event publishing to feedback stream: [trading/trader.py](trading/trader.py#L20238-L20312)
  - trainer feedback consumer dedupe: [rl/trade_feedback.py](rl/trade_feedback.py#L693-L814)
  - profit-bank ingestion from `PROFIT_EXIT`: [rl/profit_bank.py](rl/profit_bank.py#L187-L250)

---

## Current vs Desired Behavior

### A) Position provenance
- Current:
  - `origin` can be absent, `adopted`, `manual`, `system`.
  - adoption writes a separate key and may backfill `origin=adopted`.
- Desired:
  - immutable provenance envelope per leg:
    - `origin_kind` in {`SYSTEM`, `ADOPTED_EXTERNAL`, `ADOPTED_MANUAL`, `UNKNOWN_EXTERNAL`}.
    - `origin_source`, `origin_first_seen_ts_ms`, `origin_version`, `origin_evidence`.
  - once external/manual, cannot be silently promoted to system without explicit reconcile event.

### B) External/manual quarantine
- Current:
  - adopted legs become managed; no strict quarantine mode boundary.
- Desired:
  - all non-system inventory starts in `QUARANTINED` state.
  - quarantine policy:
    - allow `reduce_only` closes/partials/TP/SL.
    - disallow risk-add (`OPEN_*`, `ADD_*`, `INCREASE_*`, flips opening new exposure) unless explicit operator release.

### C) Hedge override on manual legs
- Current:
  - manual override can lift pair cap up to equity pct.
- Desired:
  - default OFF for quarantine legs.
  - controlled emergency bypass only with explicit reason code + TTL + audit event.

### D) Execution attribution
- Current:
  - rich feedback exists, but provenance+assertion linkage is not strict for all paths.
- Desired:
  - every execution/skip carries:
    - `signal_id`, `proposal_id` (if any), `origin_kind`, `quarantine_state`, `risk_assert_code`, `decision_path`, `dedupe_key`.
  - deterministic traceability from proposal → winner → trader decision → execution feedback.

### E) Duplicate execution defense
- Current:
  - dedupe in feedback consumer and ad-hoc dedupe in trader feedback publish.
- Desired:
  - single canonical idempotency key format used across trader + feedback consumer:
    - `exec_dedupe_key = account|symbol|side|action|signal_id|exchange_order_id|qty|price_bucket`.

---

## Files/Functions to Modify Later (implementation phase)

### 1) Provenance model + quarantine state
- [trading/trader.py](trading/trader.py)
  - `_position_origin_key()`
  - `_get_position_origin()`
  - `_set_position_origin()`
  - `_adopt_unmanaged_positions()`
  - signal execution gate path before `_execute_open()` / `_execute_close()` / `_execute_partial_close()`

### 2) Risk assertion + decision reason normalization
- [risk/assertions.py](risk/assertions.py)
  - `is_risk_add_action()`
  - `assert_risk()`
  - add quarantine-aware assertion codes

### 3) Hedge cap override hardening
- [trading/trader.py](trading/trader.py#L10680-L10810)
- [rl/hedge_manager_v3.py](rl/hedge_manager_v3.py#L1174-L1214)
- [config.py](config.py)
  - add kill switch + quarantine-aware override gates

### 4) Attribution schema + publish contracts
- [trading/trader.py](trading/trader.py#L19631-L20312)
  - `_publish_execution_feedback()`
  - `_publish_execution_event()`
  - `_publish_exec_audit_event()`
- [rl/trade_feedback.py](rl/trade_feedback.py#L633-L870)
  - `ExecutionFeedbackConsumer._is_duplicate()`
  - `ExecutionFeedbackConsumer._process_execution()`
- [rl/profit_bank.py](rl/profit_bank.py#L187-L250)
  - preserve compatibility with enriched `PROFIT_EXIT` payload

### 5) Router/orchestrator ingress quarantine tags
- [trading/signal_router.py](trading/signal_router.py)
  - `should_route_signal()` / `route_signal()` add provenance pass-through requirements
- [rl/orchestrator_worker.py](rl/orchestrator_worker.py)
  - proposal normalization path for source/provenance quarantine tags

---

## Patch Order (exact implementation order for later coding)
1. **Config + schema flags first**
   - Add quarantine/provenance flags with safe defaults.
   - Add backward-compatible payload fields (optional, nullable).
2. **Trader provenance core**
   - Harden origin read/write helpers and immutable first-seen semantics.
3. **Adoption-to-quarantine transition**
   - Change adoption to write `QUARANTINED` state and explicit `origin_kind`.
4. **Pre-execution quarantine gate**
   - Block risk-add on quarantined legs; allow reduce-only/protective.
5. **Risk assertion integration**
   - Add quarantine assertion codes and map to skip reasons.
6. **Hedge override hardening**
   - Disable manual override for quarantined legs by default.
7. **Attribution schema v2**
   - Enrich execution feedback/events with provenance + assertion fields.
8. **Unified dedupe key rollout**
   - trader publish + feedback consumer both adopt canonical key.
9. **Orchestrator/router propagation**
   - enforce source/provenance pass-through and default-safe fallback.
10. **Validation matrix + runbook updates**
   - finalize grep proofs, scenarios, and rollback/kill-switch steps.

---

## RAVEUSDT Regression Scenario (must pass)
- Setup:
  - external/manual `RAVEUSDT LONG` exists and is adopted.
  - leg is marked `origin_kind=ADOPTED_EXTERNAL`, `quarantine_state=QUARANTINED`.
- Expected:
  1. Any risk-add action on that quarantined leg is blocked with explicit quarantine code.
  2. Only reduce-only/protective actions can execute.
  3. Hedge-intel unwind cannot trigger destructive non-quarantine-close path.
  4. Execution feedback includes provenance + assertion codes.
  5. No duplicate execution feedback rows for same order.

---

## Validation Matrix (commands to include in RUNBOOK)

### Provenance and quarantine presence
- `redis-cli --scan --pattern 'wma:position_origin:*' | head -50`
- `redis-cli --scan --pattern 'wma:pos_adopted:*' | head -50`
- `redis-cli HGETALL 'portfolio:positions:primary' | head -40`

### Quarantine gating proofs
- `grep -E 'QUARANTINE|MANUAL_TEST_BLOCKED|TRADER_RISK_REJECT|RISK_ASSERT' logs/trader.log | tail -200`
- `grep -E 'HEDGE_PAIR_MARGIN_CAP_BLOCK|HEDGE_CAP_BYPASS' logs/trader.log | tail -200`

### Attribution and feedback proofs
- `redis-cli XRANGE executed_signals - + COUNT 10`
- `redis-cli XRANGE wma:trader:execution_feedback - + COUNT 20`
- `grep -E 'EXEC_FEEDBACK_PUBLISHED|EXEC_EVENT_PUBLISHED|PROFIT_EXIT' logs/trader.log | tail -200`

### Dedup proofs
- `grep -E 'duplicate|dedupe|Skipping duplicate execution' logs/hybrid_trainer.log | tail -200`
- `grep -E 'executed_signals_duplicate_publish_detected|EXEC-FEEDBACK-CONSUMER' logs/trader.log logs/hybrid_trainer.log | tail -200`

### RAVE regression proof
- `grep -E 'RAVEUSDT|hedge_intel_full_unwind|QUARANTINE|reduce_only' logs/trader.log | tail -300`

---

## Paper-Mode Acceptance Criteria
- No risk-add execution on quarantined external/manual legs.
- Reduce-only protective actions still execute under stress.
- Manual hedge cap override does not silently expand risk for quarantined legs.
- Every execution/skip has provenance and assertion metadata in feedback streams.
- Duplicate execution feedback rate is zero for replayed/retried messages.

## Live-Mode Blockers (must be cleared before rollout)
- Missing back-compat guards for old payload readers.
- Any path where quarantine blocks protective exits.
- Any path where `origin_kind` can be overwritten from external/manual to system without explicit reconcile.
- Any unexplained drop in feedback publish throughput.

---

## Kill Switches (required)
- `POSITION_ADOPTION_ENABLED` (existing) remains immediate rollback path.
- New `POSITION_QUARANTINE_ENABLED` (default ON in implementation phase).
- New `POSITION_PROVENANCE_STRICT_MODE` (default ON).
- New `MANUAL_HEDGE_OVERRIDE_QUARANTINE_BYPASS` (default OFF).

All new switches must fail-safe (block risk-add, allow protective reduce-only).
