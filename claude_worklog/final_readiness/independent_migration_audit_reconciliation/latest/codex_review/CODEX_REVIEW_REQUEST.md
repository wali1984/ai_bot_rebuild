# Codex Review Request — Independent Migration Audit Reconciliation

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-15

## Scope

Adversarial review of the audit reconciliation. Verify that:

1. Every row in `independent_audit_reconciliation_matrix.json` cites raw
   evidence from the audit (`migration-audit.md`) and from the V2 source tree.
2. No component is misclassified as `MIGRATED_CODEX_PASS`.
3. Newly classified `MISSING_IN_V2` components really are missing (cross-check
   with `v2/backend/app/` and `v2/legacy_preserved/`).
4. `live_gate` remains `blocked_human_only`, `live_symbols` remains `[]`,
   `approves_live` / `approves_canary` / `approves_legacy_shutdown` /
   `approves_redis_trim` are all `false`.
5. Frontend truth payload's `migration_truth.headline` reads
   "V2 is not fully migrated yet." and the Migration Progress card is red.

## Codex blocking conditions

Block if any of:

- A component is labeled `MIGRATED_CODEX_PASS` without satisfying clauses 1-13
  of the migration completion contract.
- A bridge-only worker is described as "complete" or "ready" anywhere in the
  artifacts.
- Any approval token (live, canary, legacy shutdown, Redis trim) appears.
- Old Redis writes appear in the new code paths.
- Exchange mutation appears in the new code paths.
- Any audit downgrade lacks a corresponding `next_claude_task` and
  `next_codex_review`.

## Expected outcome

A `CODEX_REVIEW.md` written into this directory with the top line:

GO/NO-GO: `CODEX_REVIEW_INDEPENDENT_MIGRATION_AUDIT_RECONCILIATION_PASS`
or `FAIL`, plus any findings.

This review does not authorize live, canary, legacy shutdown, or Redis trim.
