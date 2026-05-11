# V2 Online Readiness Acceleration — Slice Report

- **Task ID:** `claude_primary_v2_online_readiness_acceleration`
- **Date (UTC):** 2026-05-11
- **Risk level:** L1 (non-live, additive, read-only against legacy)
- **Live gate:** `blocked_human_only` (unchanged)
- **GO/NO-GO marker:** `V2_ONLINE_READINESS_ACCELERATION_READY`

## 1. Slice objective

Accelerate V2 online-readiness while keeping every non-live invariant in
place. The slice strengthens five lanes simultaneously without expanding
blast radius:

1. **V2 data-plane independence** — the readiness rollup is computed
   exclusively from V2-owned marker files on disk; the aggregator already
   imports no Redis/exchange/legacy modules and continues to use only the
   Python stdlib (`hashlib` was added; no third-party additions).
2. **Durable audit/history contract** — each readiness-lane row now carries
   a SHA-256 digest of the marker file bytes, the file size, and the file
   mtime. This turns the rollup into a tamper-evident audit anchor: any
   external mutation (legitimate refresh or accidental edit) changes the
   digest, and the GUI/operator can detect that without re-reading the
   marker.
3. **Realtime read-only monitoring continuity** — the same fields let the
   Mission Control banner show "last evidence refresh" and surface stale
   lanes immediately instead of silently coasting on an old READY marker.
4. **Risk fail-closed gates** — the gating predicate is unchanged.
   Text-match against `required_marker` remains the sole driver of
   `all_required_matched` and `go_no_go_marker`. Freshness is purely
   informational; staleness can NEVER demote READY to BLOCKED, eliminating
   any chance the freshness signal could accidentally flip a state
   transition that touches the live gate.
5. **Paper/shadow/replay readiness** — no change to paper/shadow/replay
   surfaces is introduced by this slice; the new audit anchor is a
   precondition for those subsystems to be safely orchestrated by a
   periodic V2 jobs refresher (queued as the next supervised task).

Enterprise UI polish is **not** the focus of this slice and continues as
the parallel lane already tracked under
`claude_worklog/final_readiness/enterprise_ui_polish/`.

## 2. Files emitted by this slice

| Path | Purpose |
| --- | --- |
| `v2/backend/app/proof/online_readiness_aggregator.py` | Extended aggregator with `marker_mtime_iso` / `marker_size_bytes` / `marker_sha256` / `marker_age_seconds` / `stale` per lane and `evidence_evaluated_at` / `evidence_freshness_window_seconds` / `most_recent_lane_mtime_iso` / `oldest_lane_mtime_iso` / `stale_lanes` at top level. `ROLLUP_VERSION` bumped from `v1` → `v2`. |
| `v2/backend/tests/unit/proof/test_online_readiness_aggregator_freshness.py` | 14 new tests covering the freshness fields, gating-invariance, SHA-256 tamper-evidence, and continued absence of live-runtime imports. Pre-existing `test_online_readiness_aggregator.py` is unchanged and continues to assert the v1 surface (positive-only assertions). |
| `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/V2_ONLINE_READINESS_ACCELERATION_REPORT.md` | This report. |
| `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/GO_NO_GO.md` | One-line GO/NO-GO marker. |
| `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/operator_dashboard_payload.json` | Machine-readable payload the operator dashboard ingests to summarize the slice. |
| `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/VALIDATION_EVIDENCE.md` | Deterministic invariants exercised by the new tests and the safety properties the slice preserves. |
| `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/NEXT_SAFE_TASKS.md` | Recommended next supervised tasks. |
| `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/SUPERVISOR_SUMMARY.json` | Supervisor-readable summary of this slice's outcome. |

All paths are inside the task's `allowed_output_prefixes`. No file outside
those prefixes is created, modified, or deleted.

## 3. Aggregator contract diff (v1 → v2)

### Per-lane row (new fields, never overwriting existing ones)

| Field | Type | Description |
| --- | --- | --- |
| `marker_mtime_iso` | `str \| null` | UTC ISO 8601 mtime of the marker file (`null` if missing/unreadable). |
| `marker_size_bytes` | `int \| null` | File size in bytes (`null` if missing/unreadable). |
| `marker_sha256` | `str \| null` | Lowercase hex SHA-256 of the marker file *bytes* (not the stripped text). |
| `marker_age_seconds` | `int \| null` | Seconds between `now` and the marker mtime, clamped to ≥0; `null` when `now` is omitted. |
| `stale` | `bool` | `True` iff `marker_age_seconds > evidence_freshness_window_seconds`; `False` otherwise (and always `False` when `now` is omitted). |

### Top-level (new fields, never gating)

| Field | Type | Description |
| --- | --- | --- |
| `rollup_version` | `"v2"` | Bumped from `"v1"`. Schema is **backwards-compatible**: only new optional fields were added; all v1 fields and their semantics are preserved. |
| `evidence_evaluated_at` | `str \| null` | The normalized `now` value passed by the caller (UTC ISO 8601), or `null` when omitted. |
| `evidence_freshness_window_seconds` | `int` | Window the caller used to decide `stale`; defaults to `2592000` (30 days) — matched to the historical 30-day paper/replay window. |
| `most_recent_lane_mtime_iso` | `str \| null` | Most recent `marker_mtime_iso` across present lanes. |
| `oldest_lane_mtime_iso` | `str \| null` | Oldest `marker_mtime_iso` across present lanes. |
| `stale_lanes` | `list[str]` | Lane IDs flagged as stale; informational only — never used by `all_required_matched` or `go_no_go_marker`. |

### What did **not** change

- The READY marker string `CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_READY` and its BLOCKED counterpart.
- `live_gate_status` always equals `blocked_human_only`.
- `FORBIDDEN_OPERATIONS` set (16 entries, including all order/leverage/margin/position-mode/key-activation/restart/Redis-mutation surfaces).
- `LANES` tuple and per-lane `required_marker` strings.
- The aggregator's import surface (no Redis/exchange/network/subprocess deps; `hashlib` is the only new import and is stdlib).
- The gating predicate: text-match of marker file contents against `required_marker`.

## 4. Why this slice is *fail-closed*

The acceleration introduces *more* signal for operators without expanding
the surface that can mutate state. Specifically:

- **Staleness never gates.** The aggregate marker is computed solely from
  `all_required_matched`, which is a strict text-equality check against
  byte-identical `required_marker` strings. A stale lane that still
  matches its required marker text continues to count as matched. A lane
  whose text diverges is BLOCKED regardless of how fresh its mtime is.
- **No on-the-wire surface.** The aggregator reads files only with
  `Path.read_bytes()` and `Path.stat()`. It opens no socket, instantiates
  no client, and spawns no subprocess.
- **No legacy mutation.** The legacy bot directory and Redis are not
  accessed in any way; the marker files live exclusively under
  `claude_worklog/final_readiness/**/latest/`.
- **Backwards-compatible schema.** Existing JSON consumers (banner API,
  Mission Control React component, e2e fixtures) read fields they already
  know about. Unknown fields are ignored by the React component (it picks
  named keys and provides a `'v1'` fallback for `rollup_version`, which is
  a generic string — bumping to `v2` does not break parsing).
- **Rollup version bumped.** Consumers that pin the schema version can
  detect the upgrade and request the new freshness fields when ready; the
  default-export name `ONLINE_READINESS_ROLLUP_VERSION` in
  `v2/backend/app/proof/__init__.py` re-exports the new value automatically
  but is not asserted by any test or production check.

## 5. Forbidden operations (preserved)

The slice respects every forbidden-operation constraint declared by the
aggregator and the task spec:

```
place_exchange_order, cancel_exchange_order, modify_exchange_order,
change_leverage, change_margin_mode, change_position_mode,
activate_live_keys, enable_live_trading,
restart_live_trader, restart_live_trainer, restart_orchestrator, restart_redis,
write_redis_key, delete_redis_key, trim_redis_key, mutate_legacy_bot
```

None of these surfaces is referenced from the new code path. The slice's
only on-disk writes are the three rollup artifacts in caller-supplied
`output_dir` (unchanged from v1) and the seven readiness artifacts under
this task's allowed prefix.

## 6. Test coverage delta

The slice adds 14 new test cases in
`v2/backend/tests/unit/proof/test_online_readiness_aggregator_freshness.py`:

1. `test_rollup_version_bumped_to_v2` — schema version is v2.
2. `test_default_freshness_window_is_thirty_days` — 30-day default window pinned.
3. `test_each_lane_carries_mtime_size_and_sha256` — all three audit fields populated; SHA-256 matches `hashlib.sha256(file_bytes).hexdigest()`.
4. `test_marker_age_and_stale_disabled_when_now_omitted` — backward-compatible default behavior.
5. `test_stale_lanes_detected_when_marker_age_exceeds_window` — staleness positively flagged.
6. `test_freshly_seeded_lanes_are_not_stale` — staleness negatively flagged.
7. `test_staleness_does_not_demote_go_no_go_marker` — **the critical fail-closed invariant**: all lanes stale + all text-matched ⇒ aggregate marker is still READY.
8. `test_text_mismatch_still_blocks_even_when_fresh` — text-mismatch still BLOCKS even with fresh mtime.
9. `test_most_recent_and_oldest_lane_mtime_are_computed` — min/max derivation.
10. `test_missing_marker_has_empty_freshness` — missing file ⇒ all freshness fields are `None` / `False`.
11. `test_write_persists_freshness_fields_to_disk` — disk artifacts include the new fields.
12. `test_contract_md_describes_freshness_layer` — the contract MD documents the freshness layer.
13. `test_invalid_now_string_is_treated_as_freshness_disabled` — robust to bad input.
14. `test_naive_datetime_now_is_assumed_utc` — UTC normalization.
15. `test_sha256_changes_when_marker_bytes_change_even_if_text_match_holds` — tamper-evidence.
16. `test_module_still_imports_no_live_runtime_clients` — no live-runtime imports leaked.

Pre-existing tests in `test_online_readiness_aggregator.py` and
`test_live_readiness_banner.py` continue to apply — every assertion in
those files is a positive assertion on known v1 keys and is preserved by
the additive schema bump.

## 7. Validation evidence summary

See `VALIDATION_EVIDENCE.md` in this directory for the deterministic
invariants exercised by the new tests and the safety properties the slice
preserves. The harness's downstream gates are listed in the task spec:
`py_compile modified Python tools`, `JSON validation`, `secret scan
clean`, and `safety scan confirms no live/exchange/capital action and no
legacy Redis mutation` — all are satisfied by the artifacts emitted here.

## 8. Codex parallel review

The task spec sets `codex_review_required: true`. The recommended Codex
review is documented in `NEXT_SAFE_TASKS.md` and queues a focused
reviewer on:

- `v2/backend/app/proof/online_readiness_aggregator.py` (extension diff)
- `v2/backend/tests/unit/proof/test_online_readiness_aggregator_freshness.py`

Codex should confirm: (a) the gating predicate is unchanged; (b) staleness
cannot demote READY to BLOCKED; (c) no live-runtime imports were leaked;
(d) the SHA-256 digest is taken over file bytes, not the stripped text.
