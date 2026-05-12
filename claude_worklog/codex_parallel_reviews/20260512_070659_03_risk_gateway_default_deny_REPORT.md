# Codex Parallel Review - Risk Gateway Default Deny MVP

Review timestamp: 2026-05-12 07:06:59

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

## Validation Run

Command:

`PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`

Result:

`100 passed in 0.29s`

No Redis writes, Redis deletes, service restarts, order placement/cancelation, leverage/margin changes, live trading enablement, or deployment were performed.

## Findings

### BLOCKER 1 - Risk gateway still allows tradable opens without risk-side freshness/exposure/quarantine inputs

The implemented risk gateway assembler only accepts an already-built `OrchestratorDecisionRecord` and maps four orchestrator actions:

- `open_long` -> `allow` / `allow_proceed_long`
- `open_short` -> `allow` / `allow_proceed_short`
- `hold` -> `deny` / `deny_orchestrator_held`
- `abstain` -> `deny` / `deny_orchestrator_abstained`

Evidence:

- `v2/backend/app/services/risk_gateway/service.py:25` defines `assemble_risk_decision_record(decision, now_ms_clock)` with no feature freshness, exposure, hedge state, or quarantine input.
- `v2/backend/app/services/risk_gateway/service.py:49` through `v2/backend/app/services/risk_gateway/service.py:60` allow `open_long` and `open_short` solely from `decision.decision_action`.
- `v2/backend/app/domain/risk_gateway/record.py:56` through `v2/backend/app/domain/risk_gateway/record.py:68` define a record with no stale-data, residual-exposure, or quarantine fields.
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/00_PHASE_2G_SUB_PHASE_BREAKDOWN.md:21` through `claude_worklog/phase2_core_rebuild/risk_gateway_impl/00_PHASE_2G_SUB_PHASE_BREAKDOWN.md:27` explicitly scope 2G.B to this four-branch mapper and reserve `deny_default` for future enrichment.

Impact:

Default deny exists only for non-tradable/unknown orchestrator actions. A tradable orchestrator open is not independently denied by the risk gateway when risk context is absent, stale, quarantined, or exposure-unsafe.

### BLOCKER 2 - Stale data blocks are upstream orchestrator behavior, not risk-gateway default-deny behavior

The stale path is implemented in the orchestrator assembler: stale or missing prediction freshness becomes `abstain`, which the risk gateway then maps to `deny_orchestrator_abstained`.

Evidence:

- `v2/backend/app/services/orchestrator_decision/service.py:77` through `v2/backend/app/services/orchestrator_decision/service.py:82` convert missing/stale freshness to `DECISION_ACTION_ABSTAIN`.
- `v2/backend/app/services/risk_gateway/service.py:58` through `v2/backend/app/services/risk_gateway/service.py:60` only sees abstain and emits the generic `deny_orchestrator_abstained`.
- `v2/backend/app/domain/risk_gateway/record.py:40` through `v2/backend/app/domain/risk_gateway/record.py:51` allow stale input reason codes only as copied orchestrator reason strings; there is no risk reason such as `deny_stale_data`.

Impact:

If a stale tradable decision reaches the risk gateway due to an upstream bug or alternate caller, the risk gateway has no stale-context check of its own.

### BLOCKER 3 - Hedge unwind residual exposure is represented as deterministic proof data, not enforced by risk-gateway code

The LAB failure case requires V2 to evaluate net exposure after closing a protective hedge and either keep/reduce/close/block/mark unsafe. The current risk gateway has no position, hedge leg, net exposure, squeeze context, or residual-exposure input.

Evidence:

- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:25` through `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:56` require evaluation of net exposure, confidence, freshness, liquidity/OI/regime context, and a risk-gateway block state.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:124` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:136` include a deterministic LAB fixture with `decision="deny"` and reason `short_squeeze_and_hedge_unwind_residual_exposure`.
- `v2/backend/app/services/risk_gateway/service.py:25` through `v2/backend/app/services/risk_gateway/service.py:79` provide no comparable enforcement path.

Impact:

LAB-like coverage exists as non-live evidence/proof, but the Risk Gateway Default Deny MVP does not block hedge-unwind residual exposure in its production decision surface.

### BLOCKER 4 - Manual/external position quarantine is proof-only and not wired into risk-gateway decisions

The quarantine module correctly classifies manual, protective exchange-side, unknown, and duplicate positions as quarantined and monitor-only. However, this state is not an input to `assemble_risk_decision_record`, and no risk-gateway deny reason exists for quarantined symbol/account exposure.

Evidence:

- `v2/backend/app/proof/external_manual_position_quarantine.py:186` through `v2/backend/app/proof/external_manual_position_quarantine.py:256` classify ownership, quarantine manual/external/unknown/duplicate rows, and emit blocked actions.
- `v2/backend/app/proof/external_manual_position_quarantine.py:286` records policy text `block_risk_add_on_quarantined_symbol_account`.
- `v2/backend/app/proof/external_manual_position_quarantine.py:348` through `v2/backend/app/proof/external_manual_position_quarantine.py:368` writes proof artifacts, not runtime risk-gateway integration.
- `v2/backend/app/domain/risk_gateway/record.py:23` through `v2/backend/app/domain/risk_gateway/record.py:30` enumerate risk reasons and do not include quarantine-specific denial.

Impact:

The repo can prove a quarantine policy fixture, but the risk gateway cannot consume quarantine state and cannot deny a tradable open because a symbol/account is quarantined.

## What Is Working

- Risk gateway domain records are frozen and validate action/reason consistency.
- Service and composition layers are pure, deterministic, and avoid Redis/FastAPI/runtime side effects.
- Risk records always carry `live_blocked=True`.
- Unknown or invalid decision action cannot produce a risk record.
- Stale data is blocked when it is correctly represented upstream as an orchestrator abstain.
- LAB and quarantine failure cases have deterministic proof/test coverage outside the risk gateway decision surface.

## Proposed Non-Live Autofix Tasks

1. Add a non-live `RiskGatewayContext` value object under `v2/backend/app/domain/risk_gateway/` with explicit fields for freshness gate state, hedge unwind residual exposure state, and quarantine state. Keep it pure and fixture/test driven.

2. Extend the risk gateway service with a context-aware assembler, or replace the current assembler signature in a supervised milestone, so tradable `open_long`/`open_short` decisions are denied by default unless required risk context is present and clean.

3. Add risk denial taxonomy for:
   - stale or missing risk data
   - hedge unwind residual exposure
   - manual/external/quarantined symbol-account
   - missing risk context default deny

4. Add unit tests where a tradable orchestrator `open_long`/`open_short` is denied when:
   - freshness context is stale or missing
   - hedge unwind would leave unsafe residual net exposure
   - symbol/account is quarantined
   - risk context is absent or incomplete

5. Convert the deterministic LAB and quarantine proof rows into direct risk-gateway service tests that assert `RiskDecisionRecord.risk_action == "deny"` with the relevant deny reason, without touching live services or Redis.

6. Keep all fixes non-live: pure domain/service tests only, no Redis mutation, no exchange adapter calls, no service restarts, no order placement/cancelation, and no live-mode enablement.

