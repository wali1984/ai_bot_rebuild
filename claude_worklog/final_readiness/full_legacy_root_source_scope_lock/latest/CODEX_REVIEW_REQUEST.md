# Codex Review Request — Full Legacy Root Exhaustive Source Scope Lock

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Scope

Adversarial review of the source-scope-lock sprint:

1. Verify the auto-mode classifier denial events recorded in
   FULL_LEGACY_ROOT_SOURCE_INVENTORY.md actually occurred and the
   enumeration method is honestly classified `AUDIT_MENTIONED_PATHS_ONLY`.
2. Verify the 210-path candidate inventory came from
   migration-audit.md and full-system-audit.md (provided by the user)
   and not from invented sources.
3. Verify every copied file under v2/legacy_owned_runtime has a SHA256
   recorded in the manifest amendment.
4. Verify closure reports unresolved_local=0 and parse_errors=0 on the
   current 278-file V2-owned tree.
5. Verify all six strict smokes pass with legacy_root_rejected_count=0.
6. Verify no approval token (live, canary, legacy shutdown, Redis trim)
   appears anywhere.
7. Verify the GO/NO_GO is BLOCKED on filesystem enumeration and not
   prematurely marked READY.

## Codex blocking conditions

Block if any of:

- The sprint claims filesystem-exhaustive enumeration without operator
  permission grant.
- Any approval token appears.
- Old Redis writes or exchange mutation appears.
- Any copied file lacks SHA256 in the manifest.
- A safe-source path is fabricated.

## Expected outcome

CODEX_REVIEW.md with top-line:

GO_NO_GO_CODEX_REVIEW_FULL_LEGACY_ROOT_SCOPE_LOCK_PASS_OR_FAIL

This review does not authorize live, canary, legacy shutdown, or Redis
trim.
