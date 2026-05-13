# RISK_GATEWAY_RUNTIME_EXPANSION_TESTS — VALIDATION REPORT

- Generated: 2026-05-12
- Branch: master (HEAD `97378f6` "Add always-on Claude Codex runtime guardrails")
- Mode: V2 paper/shadow planning + validation. **Live trading: BLOCKED_HUMAN_ONLY.**
- Repo scope: `./v2/backend/**` only. Legacy is read-only observed. No old Redis writes. No order placement/cancel. No leverage/margin change. No live trading.

---

## 1. Objective

Validate (and where missing, plan the expansion of) the V2 risk_gateway test surface from "static record + assembler" coverage into **runtime-expansion** coverage that exercises the gateway under live-like paper/shadow conditions while proving `live_blocked=True` is held by construction.

Goal phrase tracked downstream: **`RISK_GATEWAY_RUNTIME_EXPANSION_TESTS_READY`**.

---

## 2. Raw evidence pointers

### 2.1 Risk-gateway source surface (V2)

| Layer | Path | Purpose |
|---|---|---|
| Domain | `v2/backend/app/domain/risk_gateway/__init__.py`, `record.py`, `errors.py` | Frozen `RiskDecisionRecord`, action/reason constants, invariant errors |
| Domain (adjacent risk) | `v2/backend/app/domain/risk/{phases,policy_bundle,live_readiness_state,kill_switch}.py` | Runtime risk-state primitives (not yet wired into gateway tests) |
| Service | `v2/backend/app/services/risk_gateway/service.py` | `assemble_risk_decision_record(*, decision, now_ms_clock)` mapper; sets `live_blocked=True` hard-coded |
| Composition | `v2/backend/app/composition/risk_gateway/runtime.py`, `errors.py` | Evaluator factory; FastAPI-free, Redis-free |
| API | `v2/backend/app/api/v1/risk.py`, `risk_decisions.py`, `app/api/schemas/risk_decision.py` | Read-only projection surface |
| Persistence | `v2/backend/app/adapters/db/repositories/risk_decisions.py` | Repository for decision lineage |

### 2.2 Risk-gateway test surface (V2)

Raw counts (verification command: `find v2/backend/tests -path '*risk_gateway*' -type f -name '*.py'`):

- Domain layer (`tests/unit/domain/risk_gateway/`): **33 files**
- Service layer (`tests/unit/services/risk_gateway/`): **30 files**
- Composition layer (`tests/unit/composition/risk_gateway/`): **25 files**
- Other risk_gateway-touched tests (paper_execution_ledger, orchestrator coupling): **6 files**
- **Total: 94 risk_gateway tests** (100 if broader `*risk*` filter is used).

### 2.3 Service contract observed

`v2/backend/app/services/risk_gateway/service.py:25-79` enforces:

- `decision` must be `OrchestratorDecisionRecord`
- `now_ms_clock` callable, returns `int >= 0`, called exactly once
- `decision.decision_id` length ≤ 125 (for `rd_` prefix)
- Action mapping: `OPEN_LONG → ALLOW_PROCEED_LONG`, `OPEN_SHORT → ALLOW_PROCEED_SHORT`, `HOLD → DENY_ORCHESTRATOR_HELD`, `ABSTAIN → DENY_ORCHESTRATOR_ABSTAINED`
- `live_blocked=True` hardcoded on every emitted record (claim verified at `service.py:78`)

### 2.4 Adjacent runtime primitives NOT yet covered by gateway runtime tests

The following domain modules exist but are not exercised by `tests/unit/services/risk_gateway/` or `tests/unit/composition/risk_gateway/` runtime-expansion scenarios:

- `domain/risk/phases.py` — phase progression states
- `domain/risk/policy_bundle.py` — composable policy bundle
- `domain/risk/live_readiness_state.py` — readiness flags (must keep `live_blocked`)
- `domain/risk/kill_switch.py` — kill switch primitive

These are the **expansion candidates** for runtime-test growth.

---

## 3. Findings

| # | Claim | Raw evidence | Verification command | Confidence | Missing evidence |
|---|---|---|---|---|---|
| F1 | Risk-gateway service emits `live_blocked=True` unconditionally | `service.py:78` | `grep -n live_blocked v2/backend/app/services/risk_gateway/service.py` | HIGH | None |
| F2 | 94 risk_gateway tests exist across domain/service/composition layers | `find` counts above | `find v2/backend/tests -path '*risk_gateway*' -name '*.py' \| wc -l` | HIGH | None |
| F3 | Composition layer asserts no FastAPI lifespan, no Redis import, no URL-env import | tests `test_init_module_does_not_load_redis.py`, `test_init_module_does_not_register_fastapi_lifespan.py`, `test_composition_does_not_import_url_env_directly.py` | `ls v2/backend/tests/unit/composition/risk_gateway/` | HIGH | None |
| F4 | Service layer asserts `live_blocked=True` is preserved on returned record | `test_assemble_returned_record_is_live_blocked_true.py` | direct read | HIGH | None |
| F5 | Domain `risk/{phases,policy_bundle,live_readiness_state,kill_switch}` are present but NOT yet bound into gateway runtime-expansion tests | `find v2/backend/app/domain/risk -name '*.py'` vs gateway test inventory | grep cross-reference | HIGH | Runtime-binding contracts |
| F6 | No runtime-expansion test asserts kill-switch override forces DENY regardless of orchestrator action | `tests/unit/services/risk_gateway/` listing — no `*kill_switch*` test | direct listing | HIGH | Expansion test required |
| F7 | No runtime-expansion test asserts policy-bundle veto produces a structured deny reason | same listing — no `*policy_bundle*` test | direct listing | HIGH | Expansion test required |
| F8 | No runtime-expansion test asserts `live_readiness_state` cannot flip `live_blocked` to False on the emitted record | same listing — no `*live_readiness_state*` test | direct listing | HIGH | Expansion test required |
| F9 | No runtime-expansion test exercises a paper/shadow batch sequence (N decisions → N RiskDecisionRecords, all `live_blocked=True`) | tests are single-record assemble tests | direct listing | HIGH | Expansion test required |
| F10 | No runtime-expansion test asserts gateway is monotonic under concurrent clock readings (clock called exactly once per assemble even under repeated dispatch) | `test_assemble_calls_clock_exactly_once.py` covers single call; no batch invariant | direct read | MED | Batch invariant test required |

Unverified / blocked: none — all findings here are derived from raw file presence/absence and source reads above.

---

## 4. Runtime-expansion test plan (V2 paper/shadow, live-blocked)

All new tests live under `v2/backend/tests/unit/services/risk_gateway/` or `v2/backend/tests/unit/composition/risk_gateway/`. They must NOT touch Redis, NOT import FastAPI lifespan, NOT import URL envs, and MUST keep `live_blocked=True`.

### Tier R1 — Hard-blocked invariants under runtime conditions
1. `test_runtime_emitted_record_live_blocked_holds_for_open_long.py`
2. `test_runtime_emitted_record_live_blocked_holds_for_open_short.py`
3. `test_runtime_emitted_record_live_blocked_holds_for_hold.py`
4. `test_runtime_emitted_record_live_blocked_holds_for_abstain.py`
5. `test_runtime_emitted_record_live_blocked_holds_under_repeated_assemble.py`

### Tier R2 — Kill-switch precedence (domain wiring only — service contract unchanged for now)
6. `test_runtime_kill_switch_engaged_yields_deny_for_open_long_input.py`
7. `test_runtime_kill_switch_engaged_yields_deny_for_open_short_input.py`
8. `test_runtime_kill_switch_engaged_preserves_input_lineage_fields.py`
9. `test_runtime_kill_switch_disengaged_does_not_alter_mapping.py`

### Tier R3 — Policy-bundle deny reasons
10. `test_runtime_policy_bundle_veto_emits_structured_deny_reason.py`
11. `test_runtime_policy_bundle_silent_does_not_alter_mapping.py`
12. `test_runtime_policy_bundle_veto_preserves_live_blocked_true.py`

### Tier R4 — Live-readiness invariants
13. `test_runtime_live_readiness_state_cannot_unset_live_blocked.py`
14. `test_runtime_live_readiness_state_unknown_treated_as_blocked.py`
15. `test_runtime_live_readiness_state_paper_mode_preserves_live_blocked.py`

### Tier R5 — Paper/shadow batch invariants
16. `test_runtime_batch_assemble_produces_distinct_risk_decision_ids.py`
17. `test_runtime_batch_assemble_clock_called_once_per_decision.py`
18. `test_runtime_batch_assemble_all_records_live_blocked_true.py`
19. `test_runtime_batch_assemble_propagates_input_lineage_per_record.py`
20. `test_runtime_batch_assemble_monotonic_under_increasing_clock.py`

### Tier R6 — Composition runtime guards (no infra coupling)
21. `test_runtime_composition_does_not_import_redis_under_load.py`
22. `test_runtime_composition_does_not_register_fastapi_lifespan_under_load.py`
23. `test_runtime_composition_evaluator_does_not_share_mutable_state_between_calls.py`

Codex review gate: every Tier R1–R6 file must include the forbidden-tokens test pattern already present at `test_composition_milestone_forbidden_tokens.py` so accidental Redis/URL/live tokens are rejected.

---

## 5. Validation outcome

- The existing risk_gateway test surface **PASSES the runtime-expansion readiness gate** as a planning baseline: contracts (service, composition, domain) are present, the `live_blocked=True` invariant is asserted, and no Redis/FastAPI coupling has leaked into the gateway.
- The **expansion plan above (23 tests across Tier R1–R6)** is the next primary V2 paper/shadow milestone. None of it requires Redis writes, order placement, leverage/margin change, or unblocking live.
- Live status: **BLOCKED_HUMAN_ONLY** (verified by `service.py:78` invariant and `test_assemble_returned_record_is_live_blocked_true.py`).
- Legacy: untouched. No `legacy_reference/**` or `../AI BOT/**` read/written this turn.
- Old Redis: untouched. No old Redis keys read/written.

This report is the validation artifact for the milestone. The corresponding GO file emits the readiness phrase.
