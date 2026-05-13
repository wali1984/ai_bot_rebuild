# LEGACY_BASELINE_ANALYSIS — `<worker_id>`

> Copy this file to `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/<worker_id>_LEGACY_BASELINE_ANALYSIS.md` before implementing any V2 worker. Codex review will FAIL if this file is missing, vague, or silently drops legacy behavior.

## 1. legacy_source_paths

Concrete file paths under `legacy_reference/` that own the responsibility this worker is taking over. **Required — at least one. If none exist, justify the greenfield decision in section 11 with citations.**

```text
legacy_reference/<some_dir>/<some_file>.py
legacy_reference/<another>/<file>.py
```

## 2. legacy_functions_preserved

Specific functions, classes, methods, or top-level scripts from the legacy code whose behavior the V2 worker must preserve.

| legacy symbol | legacy file | what it does | V2 location |
|---|---|---|---|
| `_funcName` | `legacy_reference/.../x.py` | one-sentence description | `v2/backend/app/.../foo.py` |

## 3. legacy_inputs

What the legacy code reads (Redis streams, files, exchange APIs, env vars, CLI args, signals). Each row must say whether the V2 worker preserves, drops, or replaces the input.

| legacy input | source | freshness contract | V2 mapping | preserved? |
|---|---|---|---|---|
| | | | | yes / no (with reason) |

## 4. legacy_outputs

What the legacy code writes (Redis keys, log lines, files, public payloads, exchange order envelopes). **Note: this column is purely descriptive of legacy behavior — the V2 worker MUST NOT replicate legacy Redis writes against the old Redis namespace. V2 workers write only V2-namespaced data.**

| legacy output | sink | format | V2 mapping | preserved? |
|---|---|---|---|---|

## 5. legacy_redis_keys (read-only references only)

Keys/streams the legacy code reads or writes. V2 workers may only **read** legacy keys (as historical reference). They may not write old Redis under any circumstance.

| key/stream | direction in legacy | V2 stance |
|---|---|---|
| `legacy:foo:bar` | read | read-only reference only |
| `legacy:baz` | write | NOT to be written by V2 |

## 6. legacy_config_dependencies

Env vars, config files, secrets, hard-coded constants that the legacy code requires. Each row must explain how the V2 worker resolves the same dependency (or why it doesn't need it).

| legacy config key | type | V2 resolution |
|---|---|---|

## 7. legacy_edge_cases

Edge cases the legacy code handles (empty inputs, rate limits, retries, fallbacks, idempotency, partial fills, etc.). Each must be addressed by the V2 worker or explicitly listed in section 12 as removed-with-reason.

| edge case | legacy handling | V2 handling |
|---|---|---|

## 8. legacy_failure_modes

Known failure modes of the legacy code — crashes, hangs, silent corruption, race conditions, accounting drift. The V2 worker must either prevent each failure mode or explicitly accept it.

| failure mode | legacy behavior | V2 mitigation |
|---|---|---|

## 9. legacy_tests_or_expected_behavior

Cite any legacy unit tests, integration tests, replay fixtures, or operator runbooks that pin the expected behavior. The V2 worker's tests must cover at least the legacy-equivalent behavior.

| legacy test / runbook | what it pins | V2 test that covers it |
|---|---|---|

## 10. V2_mapping (one row per legacy responsibility)

Every legacy responsibility from sections 1–9 must appear here with a concrete V2 implementation pointer.

| legacy responsibility | V2 file/function | notes |
|---|---|---|

## 11. intentional_changes

Behavior the V2 worker deliberately changes vs legacy. Each row must carry a written reason — never silent.

| change | rationale |
|---|---|

## 12. removed_or_deprecated_behavior

Legacy behavior the V2 worker deliberately omits. Each row must carry a written reason.

| removed behavior | reason | risk if user expected it |
|---|---|---|

## 13. V2 safety upgrades (optional but encouraged)

How the V2 implementation improves on legacy: fail-closed gates, deterministic IDs, durable ledgers, freshness labels, MISSING_EVIDENCE classifications, no real-exchange codepath, etc.

## 14. Open questions for operator

Any decision the worker needs the operator to confirm before completion (e.g., "legacy hard-coded leverage 5x; V2 should require operator approval to set leverage at all — confirm").

---

**Codex pre-check:** sections 1, 2, 3, 4, 5, 6, 7, 10, 11, and 12 must each contain at least one substantive entry, OR the worker must justify the absence in writing. An empty table or a "TBD" placeholder is treated as a FAIL.
