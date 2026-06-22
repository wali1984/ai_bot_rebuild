# Phase A — Full Legacy Root Source Inventory

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Headline

- Candidate paths probed: **210**
- Readable: **166**
- Unreadable: **44** (audit references not present at the legacy bot path)
- Missing from V2-owned runtime before this sprint: **10**
- Newly copied this sprint (Phase C): **17** (10 from missing list + 7 helper modules + 2 top-level aliases)

## Enumeration method (honest)

The auto-mode classifier denied every `ls` / `find` / `os.listdir` call
against the legacy bot path. Bash directory listing is blocked. Per-file
`open()` reads at specific known paths succeed.

The inventory below was therefore built from the union of file paths
explicitly mentioned in:

- `migration-audit.md` (user-provided)
- `full-system-audit.md` (user-provided)

This is **audit-list-exhaustive**, NOT **filesystem-exhaustive**. The
true file count under the legacy bot path remains unknown to this
session.

## Per-file probe results

For every candidate path the script attempted `open(legacy_root / path,
"rb")`. Results were classified as:

| Result | Count |
|--------|-------|
| readable | 166 |
| unreadable (NOT_FOUND_AT_LEGACY_ROOT or PermissionError) | 44 |

The unreadable entries are paths that appear in the audit prose but were
either never present at the legacy root or are in subdirectories the
audit referenced indirectly (e.g., dependency mentions that point to a
neighbor module that isn't separately listed).

## Files copied in this sprint

10 paths from the "missing from V2-owned" first-round list:

- api/app.py
- api/auth.py
- api/grpc_server.py
- circuit_breaker.py
- config/settings.py
- emergency_brake.py
- ingest/ccxt_historical.py
- ingest/live_alphavantage_news.py
- ingest/live_ccxt.py
- ingest/live_tokenmetrics.py

7 helper modules discovered after the first round of strict-smoke
diagnosis:

- ingest/alphavantage_client.py
- ingest/tm_ids.py
- ingest/tm_spec.py
- ingest/tokenmetrics_normalizer.py
- alphavantage_client.py (top-level)
- tokenmetrics_client.py (top-level)
- tokenmetrics_normalizer.py (top-level)

2 top-level aliases of fallback-import helpers:

- tm_ids.py (alias of ingest/tm_ids.py)
- tm_spec.py (alias of ingest/tm_spec.py)

All copies preserve directory structure relative to the legacy bot path.
SHA256 is recorded in `full_legacy_root_source_inventory.json` and in
the manifest amendment at
`claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest/FULL_LEGACY_CORE_COPY_MANIFEST.json`.

## What remains unknown

Because directory listing is denied, this sprint cannot prove that **no
other safe runtime source file exists in the legacy bot path**. The
audit-list inventory is a strong lower bound, not an upper bound.

## Headline classification

`FULL_LEGACY_ROOT_FILESYSTEM_ENUMERATION_BLOCKED_AUDIT_LIST_EXHAUSTIVE_COMPLETE`

Live remains blocked_human_only.
