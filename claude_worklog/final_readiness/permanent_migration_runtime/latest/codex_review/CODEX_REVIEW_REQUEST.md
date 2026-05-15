# Codex Review Request — Permanent Migration Fix and Frontend Runtime Ready

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-15

## Scope

Adversarial review of the V2 permanent migration runtime objective. Verify the
following:

1. The migration completion contract in
   `claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md`
   refuses informal terms (`READY`, `COMPLETE`, `DONE`, `GREEN`, `OK`, `PASS`)
   and lists 13 verifiable prerequisites for `MIGRATED_CODEX_PASS`.
2. The permanent objective router at
   `claude_worklog/tools/v2_permanent_objective_router.py` reads only V2 public
   payloads + worklog readiness JSON, never authorizes live/canary/Redis-trim,
   and never routes to UI-only work while P0 blockers remain.
3. The expected-move review service is analysis-only, with safety invariants
   enforced by integration tests.
4. The frontend truth payload at
   `v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json`
   marks missing payloads `MISSING_EVIDENCE` and stale payloads `STALE`
   instead of inventing current values.
5. The new admin page at `/admin/permanent-migration` consumes only V2 payloads
   and exposes no live controls.

## Codex blocking conditions (uniform)

Block if any of:

- `worker_greenfield_without_justification`
- `copied_baseline_sha256_not_cited` where citation is structurally required
- `dependency_closure_missing` for a worker claimed `MIGRATED_CODEX_PASS`
- `legacy_features_silently_dropped`
- `tests_do_not_cover_legacy_equivalent_behavior` for a worker claimed
  `MIGRATED_CODEX_PASS`
- `worker_claims_migration_from_backlog_only`
- `old_redis_writes_appear`
- `exchange_mutation_appears`
- `live_approval_token_exists`
- `redis_trim_approval_token_exists`

## Expected outcome

A `CODEX_REVIEW.md` written into this directory with the top line
`GO/NO-GO: CODEX_REVIEW_PERMANENT_MIGRATION_FIX_AND_FRONTEND_RUNTIME_PASS`
or `FAIL`, followed by a short list of any findings.

This review request does not authorize live trading, canary trading, legacy
shutdown, or Redis trim.
