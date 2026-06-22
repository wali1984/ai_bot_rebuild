# Codex Review: Full Legacy Root Source Scope Lock

Generated: `2026-05-16T01:54:43Z`

GO/NO-GO: `FULL_LEGACY_ROOT_EXHAUSTIVE_SOURCE_SCOPE_LOCK_CODEX_FAIL`

## Decision

Codex fails `FULL_LEGACY_ROOT_EXHAUSTIVE_SOURCE_SCOPE_LOCK_READY`.

The packet is honest about its own blocker: it is audit-list-exhaustive, not filesystem-exhaustive. The user gate requires full legacy root enumeration and requires failure if missing files are hidden under preserved-closure-only or audit-mentioned-path wording.

This review does not approve live trading, canary trading, Redis trim, or legacy shutdown.

## Blocking Findings

1. Full legacy root was not enumerated by the packet.
   - Packet value: `enumeration_method=AUDIT_MENTIONED_PATHS_ONLY`.
   - Packet value: `filesystem_enumeration_status=BLOCKED_AUTO_MODE_CLASSIFIER_DENIES_LISTDIR`.
   - Packet candidate path count: `210`.
   - This violates the explicit review gate: full legacy root must be enumerated.

2. Codex independently verified the legacy root is much larger than the packet scope.
   - Codex read-only command counted `16,802` Python files under `/home/wali/Desktop/AI BOT`.
   - Packet only probed `210` audit-mentioned paths.
   - `v2/legacy_owned_runtime` currently has `278` Python files.
   - Therefore the packet cannot prove every safe runtime source is copied or classified.

3. Required subsystem source coverage is not filesystem-exhaustive.
   - Codex read-only counts from the legacy root:
     - `rl`: `121` Python files
     - `ingest`: `30` Python files
     - `trading`: `35` Python files
     - `risk`: `22` Python files
     - `services`: `8` Python files
     - `utils`: `21` Python files
     - `monitoring`: `8` Python files
     - `config`: `1` Python file
     - `api`: `13` Python files
   - The packet does not contain a filesystem-derived source inventory proving these trees were exhaustively copied or classified.

4. Missing safe sources remain possible by construction.
   - The packet states: “The true file count under the legacy bot path remains unknown to this session.”
   - That is exactly the condition this review must fail.

## Passing Checks

The lower-level V2-owned runtime checks are currently clean:

- Dependency closure rerun:
  - Command: `PYTHONPATH="$PWD" .venv/bin/python -m v2.backend.app.cli.zero_miss_dependency_closure`
  - Result: `py_files=278 unresolved_local=0 external=29 parse_errors=0`
- Full `v2/legacy_owned_runtime` py_compile: PASS.
- Focused zero-miss tests: `16 passed`.
- Strict smoke import proof:
  - all six wrappers pass
  - `any_legacy_root_resolved=false`
  - all `legacy_root_rejected_count=0`
- Old Redis scan:
  - only guarded V2 namespace-adapter write methods matched; tests enforce old-key rejection.
- Exchange mutation scan:
  - no direct mutation calls found in reviewed V2/backend scope.
- Frontend/public payload:
  - shows `FULL_LEGACY_ROOT_EXHAUSTIVE_SOURCE_SCOPE_LOCK_BLOCKED`
  - says old-system shutdown is “No”
  - does not claim live/shutdown readiness.
- Safety values:
  - `live_gate=blocked_human_only`
  - `live_symbols=[]`
  - all live/canary/shutdown/Redis-trim approvals are false.

## Required Next Fix

Build a true filesystem-derived inventory from `/home/wali/Desktop/AI BOT` without modifying that path:

1. Enumerate every file under the legacy root.
2. Classify source vs binary/model/log/runtime artifact/test/debug/secret.
3. Copy or explicitly classify every safe runtime source under `rl`, `ingest`, `trading`, `risk`, `services`, `utils`, `monitoring`, `config`, `api`, and root-level runtime files.
4. Inventory binaries/models/logs instead of copying them unsafely.
5. Rerun dependency closure, py_compile, strict smokes, old Redis scan, exchange mutation scan, and frontend truth sync.

Do not proceed to native algorithmic-core migration until this source-scope lock gets a Codex PASS.
