# V2 Permanent Migration Fix and Frontend Runtime Readiness — GO/NO_GO

Generated: 2026-05-15

## GO_NO_GO

V2_PERMANENT_MIGRATION_FIX_AND_FRONTEND_RUNTIME_READY

## Rationale

Per the migration completion contract in
[MIGRATION_COMPLETION_CONTRACT.md](MIGRATION_COMPLETION_CONTRACT.md), this objective
is `READY` because:

1. The permanent migration contract exists and defines the 13-clause definition of
   `MIGRATED_CODEX_PASS` and the 11 permitted non-final classifications.
2. The permanent-objective router exists, runs against the live blocker matrix and
   parity gap matrix, and routes the highest-priority blocker on every invocation.
   Service + timer files are present on disk. Codex active-state verification on
   2026-05-15 found that the standalone systemd service/timer are not installed
   or active; the existing Codex takeover loop remains the active controller.
3. Remaining shutdown blockers are surfaced by the router and downgraded to
   non-final classifications. No artifact in this objective claims `READY` for a
   worker that has not satisfied the 13 clauses.
4. Paper edge and trainer parity tasks are explicitly captured as P0 blockers,
   with named remediation task ids the router emits on each tick. The existing
   `expected_move_model_review` artifacts are validated by the new service +
   CLI + integration tests.
5. The frontend truth payload builder exists and produces a single aggregated
   payload that the admin/user pages consume.
6. A new admin page (`/admin/permanent-migration`) is wired into the page registry
   and consumes only V2 public payloads. Stale and missing sources surface as
   `STALE` and `MISSING_EVIDENCE` rather than as invented values.
7. A Codex review hook is in place under
   `claude_worklog/final_readiness/permanent_migration_runtime/latest/codex_review/`
   for the next adversarial review pass.
8. Validation passes: py_compile clean across new Python; 9/9 new pytest tests
   green; frontend typecheck clean; JSON parses across all new payloads;
   forbidden-mutation scan clean.

## Live, canary, legacy shutdown, Redis trim status

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- approves_live: `false`
- approves_canary: `false`
- approves_legacy_shutdown: `false`
- approves_redis_trim: `false`
- final_approval_token: `absent`
- redis_trim_approval_token: `absent`

This `READY` token authorizes only the **permanent migration runtime and frontend
runtime** scope. It does not authorize live trading, canary trading, legacy
shutdown, or Redis trim. Those require explicit operator approval and remain
blocked by the contract.

## What still must happen before legacy shutdown can be reconsidered

- Native trainer evidence (or operator acceptance of derived evidence) must close
  the trainer parity gap captured in `TRAINER_PARITY_BLOCKER_PACKET.md`.
- Paper edge must be proven against fees through the expected-move model review
  threshold replay, or the operator must accept the strict-gate review outcome.
- The risk/trader action map must be fully covered by tests per
  `RISK_TRADER_PARITY_BLOCKER_PACKET.md`.
- Public payload freshness guard must clear stale latest JSONs.
- Account read-only permission evidence must close
  `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`.
