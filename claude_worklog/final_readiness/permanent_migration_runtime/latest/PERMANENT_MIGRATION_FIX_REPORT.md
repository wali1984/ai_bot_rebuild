# Permanent Migration Fix Report

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.

## What changed

### Phase 1 — Migration completion contract
- New: [MIGRATION_COMPLETION_CONTRACT.md](MIGRATION_COMPLETION_CONTRACT.md)
- New: [migration_completion_contract.json](migration_completion_contract.json)

The contract defines the 13 prerequisites for `MIGRATED_CODEX_PASS` and the
permitted non-final classifications. Informal terms (`READY`, `COMPLETE`,
`DONE`, `GREEN`, `OK`, `PASS`) are no longer valid.

### Phase 2 — Permanent objective router
- New: [v2_permanent_objective_router.py](../../../tools/v2_permanent_objective_router.py)
- New: [ai-bot-v2-permanent-objective-router.service](../../../systemd/user/ai-bot-v2-permanent-objective-router.service)
- New: [ai-bot-v2-permanent-objective-router.timer](../../../systemd/user/ai-bot-v2-permanent-objective-router.timer)

The router reads the shutdown blocker matrix, observatory, paper edge,
expected-move review, parity gap matrix, worker porting state, and trainer
bridge status. It selects the highest-priority blocker, applies a safety guard
that rejects live/canary/Redis-trim authorization tasks, and writes
`router_status.json` + `ROUTER_STATUS.md`. UI-only routing is gated on P0
clearance. Live/canary routing is permanently disallowed.

Codex active-state verification on 2026-05-15 found the router service/timer
files on disk, but `systemctl --user` reports both units as `not-found`. The
router is therefore an on-disk/manual routing artifact right now, not an active
systemd controller. The active controller path remains the existing Codex
shutdown-readiness takeover and read-only observatory services until the
operator explicitly installs/enables the router service.

The current selected blocker is `PAPER_EDGE_UNPROVEN`; next task id is
`claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`.

### Phase 3 — Expected-move model review
- New: [v2_expected_move_model_review.py](../../../../v2/backend/app/cli/v2_expected_move_model_review.py)
- New: [services/expected_move_model_review/service.py](../../../../v2/backend/app/services/expected_move_model_review/service.py)
- New: [tests/integration/cli/test_v2_expected_move_model_review.py](../../../../v2/backend/tests/integration/cli/test_v2_expected_move_model_review.py)

The service is analysis-only. It loads the existing review payload,
threshold replay results, and false-block audit. Tests verify the safety
invariants: live_gate must remain blocked_human_only, live_symbols must remain
empty, approves_live/canary/legacy_shutdown must all be false, go_no_go must
be one of the four canonical values. 9/9 tests pass.

### Phase 4 — Trainer parity blocker packet
- New: [TRAINER_PARITY_BLOCKER_PACKET.md](TRAINER_PARITY_BLOCKER_PACKET.md)

Documents why the trainer bridge is `READONLY_BRIDGED` / `PAPER_ONLY` and not
`MIGRATED_CODEX_PASS`. Lists the required artifacts for full hybrid trainer
parity. Refuses to fabricate a synthetic full-parity claim.

### Phase 5 — Risk / trader parity blocker packet
- New: [RISK_TRADER_PARITY_BLOCKER_PACKET.md](RISK_TRADER_PARITY_BLOCKER_PACKET.md)

Captures the risk/trader action paths that need test coverage per
`next_remediation_tasks_for_claude.json` and the parity gap matrix. The router
emits `RISK_TRADER_ACTION_PARITY_INCOMPLETE` for these.

### Phase 6 — Professional frontend
- New: [permanent-migration/](../../../../v2/frontend/src/pages/permanent-migration/) page
- New: [data/runtimePayloads.ts](../../../../v2/frontend/src/data/runtimePayloads.ts)
- New: [components/status-simple/StatusBadge.tsx](../../../../v2/frontend/src/components/status-simple/StatusBadge.tsx)
- Wired into [pages/registry.ts](../../../../v2/frontend/src/pages/registry.ts)
- Added to [tests/e2e/_shared.ts](../../../../v2/frontend/tests/e2e/_shared.ts) for nav smoke and rbac visibility

The page consumes only the V2 frontend truth payload. It renders in plain
English: today's goal, live block, paper edge status, trainer parity, decision
quality, why shutdown is blocked, per-page cards with summary / why this
matters / what needs to happen next, and stale/missing evidence. No mock
current values. No legacy Redis. Live controls disabled.

### Phase 7 — Frontend truth payload builder
- New: [frontend_truth_payload_builder.py](../../../../v2/backend/app/cli/frontend_truth_payload_builder.py)
- Output: [frontend_truth_payload.json](../../../../v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json)

Aggregates 15 runtime payloads into a single source for the frontend. Stale
payloads are flagged with `STALE`; missing payloads with `MISSING_EVIDENCE`.
The builder never authorizes live, canary, legacy shutdown, or Redis trim.

### Phase 8 — Validation results
- py_compile: clean across all new Python.
- JSON validation: clean across all new payloads.
- pytest: 9/9 new tests pass.
- Frontend typecheck (`tsc -b --noEmit`): clean.
- Forbidden-mutation scan: clean. No exchange-mutation symbols, no leverage
  changes, no margin-mode changes, and no old-Redis writes appear in the new
  code paths.
- Final approval token: absent. Redis trim approval token: absent.

## What this objective does not do

- Does not authorize live trading.
- Does not authorize canary trading.
- Does not authorize legacy shutdown.
- Does not authorize Redis trim.
- Does not run the full hybrid trainer parity build (P0 dispatched as a separate
  blocker packet).
- Does not add full P0 risk action coverage tests (dispatched via the router).
- Does not add user pages for every CoinAnk-style derivatives view (one focused
  admin page is added; existing pages keep their structure).

## Next router-selected work

The router's current selected blocker is `PAPER_EDGE_UNPROVEN`, remediation
task id `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`. P0
blockers remaining: 8. This routing output is available for the active Codex
takeover loop to consume, but the standalone permanent-objective-router systemd
timer is not installed/active.

Live remains `blocked_human_only`.
