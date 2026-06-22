# Subproject 4 — Orchestrator Arbitration — Report

**Subproject id:** `4_orchestrator_arbitration`
**Classification:** `PARTIALLY_MIGRATED_PAPER_ONLY`
**Generated UTC:** 2026-05-15
**Migration contract:** `claude_worklog/final_readiness/permanent_migration_runtime/latest/migration_completion_contract.json`
**Live gate:** `blocked_human_only`
**Live symbols:** `[]`
**Approves live:** `false`

## 1. Outcome summary

Subproject 4 delivers a V2-native, paper-only orchestrator arbitration
service replacing the smallest, safe-to-port subset of the legacy
`rl/orchestrator_worker.py` (10,523 lines), `rl/proposal_bus.py`,
`rl/tradeplan_orchestrator.py`, and `rl/intent_engine.py` runtimes.

The migration is intentionally **partial**: full legacy parity requires
real order routing and Redis proposal-bus integration, both of which
remain explicitly out of scope while the live gate is
`blocked_human_only`.

## 2. Components ported (paper-only)

1. **Proposal dataclass + deterministic scoring** —
   `v2/backend/app/services/orchestrator_arbitration/proposal.py`.
2. **V2 signal schema + validator** —
   `v2/backend/app/services/orchestrator_arbitration/signal_schema.py`.
3. **Deconflict signals** with explicit `MISSING_EVIDENCE_CANNOT_COMPARE`
   fail-closed result — `v2/backend/app/services/orchestrator_arbitration/deconflict.py`.
4. **Static stream routing** mapping symbol -> `primary` / `asjad` /
   `shadow` (informational only) —
   `v2/backend/app/services/orchestrator_arbitration/stream_routing.py`.
5. **Top-score-per-`(symbol, side)` arbitration loop** with stale-signal
   filtering — `v2/backend/app/services/orchestrator_arbitration/service.py`.
6. **Public operator-runtime status payload** with full safety invariants —
   `v2/backend/app/cli/v2_orchestrator_arbitration_worker.py`, emitting to
   `v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json`.

## 3. Components honestly marked MISSING_IN_V2

- Full 10,523-line `rl/orchestrator_worker.py` runtime.
- Real order routing.
- Redis `proposal_bus` integration (no `redis` import; no `xadd`).
- Hedge cage arbitration overlays.
- `asjad` account publish path.
- `IntentEngine` higher-timeframe PPO/MASA consensus full runtime.
- `tradeplan_orchestrator.py` protection-demand-score / `MarketContext`
  utility composition.
- `windows_arbitrated` telemetry counters and CRITICAL-flush flow.

## 4. Test result

Invocation (run from the repo root):

    .venv/bin/pytest \
        v2/backend/tests/integration/cli/test_v2_orchestrator_arbitration_worker.py \
        -q

Result: **21 passed in 0.11s** (zero failures, zero errors, zero skips).

All ten required test cases listed in the subproject specification are
present and passing:

- `test_signal_schema_rejects_missing_required_fields`
- `test_signal_schema_accepts_complete_signal`
- `test_score_proposal_returns_finite_for_fresh`
- `test_score_proposal_returns_minus_inf_for_stale`
- `test_arbitrate_picks_highest_score_per_symbol_side`
- `test_deconflict_picks_higher_confidence_when_opposite_sides`
- `test_deconflict_picks_more_after_cost_when_same_confidence`
- `test_deconflict_reports_MISSING_EVIDENCE_when_empty`
- `test_stream_router_defaults_to_shadow`
- `test_status_payload_carries_safety_invariants`

Eleven additional supporting tests cover unknown-side rejection,
out-of-range confidence rejection, stale-proposal exclusion, static
mapping honoring, invalid label rejection, end-to-end worker write,
worker handling of missing inputs, parser defaults, dry-run behavior,
forbidden-import absence, and the public payload path.

## 5. Safety invariants verified

- `live_gate == "blocked_human_only"` in status payload.
- `live_symbols == []`.
- `approves_live is False`.
- `cannot_bypass_risk_gateway is True`.
- `orchestrator_overrides_risk is False`.
- `redis` and `binance` substrings absent from worker source.
- Tests perform zero network IO.

## 6. GO/NO-GO

`SUBPROJECT_4_ORCHESTRATOR_ARBITRATION_PARTIALLY_MIGRATED_PAPER_ONLY`

The classification is intentionally **not** `MIGRATED` because real order
routing and Redis `proposal_bus` integration cannot be ported while the
live gate is `blocked_human_only`. Closing the remaining gaps requires
explicit human approval (live gate transition) and is deferred.
