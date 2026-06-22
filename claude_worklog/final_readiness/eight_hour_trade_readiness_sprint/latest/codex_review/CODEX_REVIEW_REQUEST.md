# Codex Review Request — 8-Hour Trade Readiness Implementation Sprint

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-15

## Scope

Adversarial review of the 8-hour sprint. Verify that each lane:

1. Produces honest evidence, not fabricated readiness.
2. Holds the migration completion contract invariants:
   live_gate=blocked_human_only, live_symbols=[], approves_live=false,
   approves_canary=false, approves_legacy_shutdown=false,
   approves_redis_trim=false.
3. Does not start legacy, mutate exchange, write old Redis, or change
   leverage/margin.
4. Cites raw evidence for every claim.

## Per-lane review prompts

### Lane A — Paper edge model repair
- Confirm: 0 safe threshold candidates, strict gate held.
- Confirm: no global or selective threshold change authorized.
- Block if: report claims paper edge is positive.

### Lane B — Trainer evidence
- Confirm: native fields enumerated honestly (raw expected_move_pct yes,
  expected_move_after_cost_bps no, feature_snapshot_id v2-form no,
  structured feature_attribution no).
- Confirm: bridge stays classified READONLY_BRIDGED/PAPER_ONLY.
- Block if: report claims full trainer parity without producing the required
  parity artifacts.

### Lane C — Risk/trader action parity deny tests
- Confirm: 22 passed, 3 skipped (documented gaps), 0 failed.
- Confirm: tests exercise actual exported risk_gateway evaluators.
- Confirm: no exchange client imported; no mutation paths reachable.
- Confirm: 3 skipped paths are documented parity gaps, not silently passing.
- Block if: any test reaches a mutating exchange path or uses a network client.

### Lane D — Signal/orchestrator freshness
- Confirm: stale payloads identified honestly (orchestrator_adapter,
  signal_publisher).
- Confirm: decision quality stays classified INSUFFICIENT_SAMPLE.
- Block if: report invents decision quality numbers for stale-source symbols.

### Lane E — Account permission
- Confirm: credentials_status=MISSING, fail_closed=true,
  exchange_mutation_performed=false.
- Confirm: classification is BLOCKED_BY_PERMISSION.
- Block if: any approval token is created.

### Lane F — Frontend truth
- Confirm: new page consumes only the frontend truth payload.
- Confirm: page exposes no live controls.
- Confirm: frontend typecheck clean; registry append-only.
- Block if: page imports legacy Redis client or fabricates current values.

## Uniform Codex blocking conditions

- `worker_greenfield_without_justification`
- `copied_baseline_sha256_not_cited` where citation is structurally required
- `dependency_closure_missing` for a worker claimed MIGRATED_CODEX_PASS
- `legacy_features_silently_dropped`
- `tests_do_not_cover_legacy_equivalent_behavior` for a claimed
  MIGRATED_CODEX_PASS worker
- `worker_claims_migration_from_backlog_only`
- `old_redis_writes_appear`
- `exchange_mutation_appears`
- `live_approval_token_exists`
- `redis_trim_approval_token_exists`

## Expected outcome

A `CODEX_REVIEW.md` written into this directory with the top line:

GO/NO-GO: `CODEX_REVIEW_EIGHT_HOUR_TRADE_READINESS_IMPLEMENTATION_SPRINT_PASS`
or `FAIL`, followed by a short list of any findings.

This review request does not authorize live trading, canary trading, legacy
shutdown, or Redis trim.
