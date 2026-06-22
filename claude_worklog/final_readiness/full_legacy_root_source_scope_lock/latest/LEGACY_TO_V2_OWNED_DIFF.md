# Phase B — Legacy-to-V2-Owned Diff

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Summary

For each of the 210 audit-mentioned candidate paths, the diff classifies
the V2-owned-runtime state into one of:

| Classification | Count |
|---------------|-------|
| ALREADY_PRESENT | 156 |
| COPIED_NOW (round 3) | 10 (first round) + 9 (helpers/aliases) = 19 effective |
| BLOCKED_LEGACY_FILE_NOT_FOUND_OR_DENIED | 44 |
| SAFE_SOURCE_MISSING_BLOCKER | 0 |
| UNSAFE_SECRET_EXCLUDED | 0 |
| BINARY_MODEL_INVENTORIED_ONLY | 0 |
| LOG_OR_RUNTIME_ARTIFACT_EXCLUDED | 0 |
| TEST_DEBUG_NON_RUNTIME_EXCLUDED | 0 |
| DUPLICATE_OR_BACKUP_EXCLUDED | 0 |
| OPERATOR_DECISION_REQUIRED | 0 |

The 44 BLOCKED entries are audit-mentioned paths the probe could not
read. Two causes:

1. Path appears in an audit prose reference but is not actually a file
   at the legacy bot path (e.g., audit listed a dependency by module
   name; the file lives somewhere the audit did not separately
   enumerate).
2. The file exists but was not located at the probed relative path.

Because directory listing is denied, the 44 entries cannot be
re-classified without operator action. They are treated as
`BLOCKED_LEGACY_FILE_NOT_FOUND_OR_DENIED` rather than fabricated.

## Important: this diff is bounded by Phase A's enumeration method

The diff covers exactly the candidate paths Phase A built from the audit
docs. It does NOT cover the entire legacy bot filesystem. A
filesystem-exhaustive diff requires operator action to grant directory
listing (see LEGACY_ROOT_ACCESS_PROOF.md).
