# V2 Online Readiness Acceleration — Validation Evidence

This document captures the deterministic invariants exercised by the new
test suite and the safety properties the slice preserves. Every claim
below is backed by a specific test case or a specific code-path inspection
of the artifacts emitted by this slice.

## A. Gating-invariance invariants (FAIL-CLOSED)

### A1. Staleness never demotes READY to BLOCKED

- **Test:** `test_staleness_does_not_demote_go_no_go_marker`
- **Setup:** All five required lane markers are seeded with the correct
  `required_marker` text but each file's mtime is backdated by 365 days.
  `now` is `datetime.now(tz=timezone.utc)`. `freshness_window_seconds = 30 *
  24 * 60 * 60`.
- **Expected:** `len(stale_lanes) == len(LANES)`, AND
  `all_required_matched is True`, AND
  `go_no_go_marker == GO_NO_GO_MARKER_READY`, AND
  `blocking_lanes == []`, AND
  `live_gate_status == "blocked_human_only"`.
- **Why this matters:** the slice cannot accidentally promote or demote
  the live gate; staleness is informational only.

### A2. Text mismatch still BLOCKS regardless of freshness

- **Test:** `test_text_mismatch_still_blocks_even_when_fresh`
- **Setup:** All five lanes seeded fresh. The last lane's marker is
  rewritten with `"DIVERGED_MARKER"`, so its text no longer matches
  `required_marker`. `now` is `datetime.now(tz=timezone.utc)`.
- **Expected:** `all_required_matched is False`, AND
  `go_no_go_marker == GO_NO_GO_MARKER_BLOCKED`, AND
  the diverged lane's `lane_id` appears in `blocking_lanes`.

### A3. Missing marker still BLOCKS

- **Test:** `test_missing_marker_has_empty_freshness`
- **Setup:** All five lanes seeded fresh, then the first lane's marker is
  unlinked. `now` is supplied.
- **Expected:** Missing lane's freshness fields are all `None` / `False`,
  AND `go_no_go_marker == GO_NO_GO_MARKER_BLOCKED`.

## B. Audit-history invariants (TAMPER-EVIDENCE)

### B1. SHA-256 is taken over file bytes

- **Test:** `test_each_lane_carries_mtime_size_and_sha256`
- **Setup:** All five lanes seeded fresh.
- **Expected:** for every lane, `marker_sha256 ==
  hashlib.sha256(marker_path.read_bytes()).hexdigest()` — i.e., the digest
  is over the raw file bytes, not the stripped text. This is what makes
  it a true tamper-evident anchor (newline/EOL changes detectable).

### B2. SHA-256 changes when bytes change even if text-match holds

- **Test:** `test_sha256_changes_when_marker_bytes_change_even_if_text_match_holds`
- **Setup:** Lane seeded with `MARKER\n`. SHA captured. Lane rewritten with
  `MARKER\n\n` (same `strip()` value, different bytes).
- **Expected:** new SHA differs from the original; `matched` is still
  `True` (text-match uses stripped text).

### B3. Empty freshness for missing/unreadable markers

- **Test:** `test_missing_marker_has_empty_freshness`
- **Expected:** No partial fields; if the file is missing, all five
  freshness fields are emitted as `None` / `False` rather than absent or
  partially populated.

## C. Schema-compatibility invariants

### C1. Backwards compatibility with v1 callers

- **Inspection target:** `v2/backend/tests/unit/proof/test_online_readiness_aggregator.py`
  (pre-existing, untouched). All five test cases call
  `build_online_readiness_rollup(repo_root, ...)` or
  `write_online_readiness_rollup(repo_root, output_dir, ...)` with
  positional/keyword args supported in both v1 and v2 signatures. Every
  assertion is a positive assertion on a key that still exists in v2.
- **Expected:** no pre-existing test is broken by the v1 → v2 schema bump.

### C2. Banner handler is compatible

- **Inspection target:** `v2/backend/app/api/v1/live_readiness.py`. Handler
  calls `build_online_readiness_rollup(_resolve_repo_root())` with no
  extra kwargs. The v2 signature defaults `now=None` and
  `freshness_window_seconds=DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS`.
- **Result:** the handler returns a v2 rollup with empty `stale_lanes`,
  freshness fields populated where files exist, and the same shape v1
  consumers already expect.

### C3. Frontend default fallback is non-breaking

- **Inspection target:** `v2/frontend/src/components/banners/MissionControlReadinessBanner.tsx`
  line 35: `rollup_version: typeof raw.rollup_version === 'string' ?
  raw.rollup_version : 'v1'` — the value is treated as an opaque string
  with a `'v1'` fallback; the bump to `'v2'` is benign.

### C4. e2e fixture remains acceptable

- **Inspection target:** `v2/frontend/tests/e2e/mission_control_readiness_banner.spec.ts`
  uses `rollup_version: 'v1'` in its mock fixture. The e2e test asserts
  on chip text, lane IDs, marker paths, and `live_gate_status` — not on
  `rollup_version` itself.

## D. Non-live-import invariants

### D1. No live-runtime imports leaked

- **Test:** `test_module_still_imports_no_live_runtime_clients`
- **Banned needles:** `import redis`, `from redis`, `import ccxt`,
  `from ccxt`, `import websockets`, `from websockets`, `import requests`,
  `from requests`, `subprocess`.
- **Expected:** every needle is absent from the aggregator source.

### D2. Only stdlib added

- **Inspection:** the aggregator's imports are now `hashlib`, `json`,
  `dataclasses.dataclass`, `datetime.datetime/timezone`, `pathlib.Path`,
  `typing.Any/Mapping`. All stdlib. `hashlib` is the only new addition
  versus v1.

## E. Determinism invariants

### E1. Identical inputs → identical outputs

- For fixed `generated_at`, `now`, `freshness_window_seconds`, and a fixed
  marker filesystem (bytes + mtimes), `build_online_readiness_rollup`
  emits an identical dict. The aggregator uses no random sources, reads no
  environment variables (except via the API handler's repo-root override),
  and performs no clock reads when `generated_at` and `now` are supplied.

### E2. Lane order is fixed

- The `LANES` tuple is iterated in declaration order; `lanes_status` is
  built deterministically with the same ordering.

### E3. Invalid `now` is robust

- **Test:** `test_invalid_now_string_is_treated_as_freshness_disabled`
- An unparseable `now` string yields the freshness-disabled behavior
  rather than raising — guarantees the aggregator stays callable in
  diagnostic / failure modes.

## F. Forbidden-operation invariants (CLAUDE.md compliance)

The slice does NOT invoke any of the following:

| Operation | Status in this slice |
| --- | --- |
| `place_exchange_order` | not invoked |
| `cancel_exchange_order` | not invoked |
| `modify_exchange_order` | not invoked |
| `change_leverage` | not invoked |
| `change_margin_mode` | not invoked |
| `change_position_mode` | not invoked |
| `activate_live_keys` | not invoked |
| `enable_live_trading` | not invoked |
| `restart_live_trader` | not invoked |
| `restart_live_trainer` | not invoked |
| `restart_orchestrator` | not invoked |
| `restart_redis` | not invoked |
| `write_redis_key` | not invoked |
| `delete_redis_key` | not invoked |
| `trim_redis_key` | not invoked |
| `mutate_legacy_bot` | not invoked |

All on-disk writes performed by the slice are confined to the task's
`allowed_output_prefixes` (`v2/` and the four
`claude_worklog/final_readiness/.../latest/` directories explicitly listed
in the task spec).

## G. Harness-level downstream validations (deferred to supervisor)

The task spec declares these supervisor-side validations:

- `py_compile modified Python tools if any` — the emitted aggregator is
  Python 3.11+ compatible (targets `requires-python = ">=3.11"` per
  `v2/pyproject.toml` while using only syntax available in 3.11; uses
  `dict | None` PEP-604 unions and `tuple[...]` builtin generics, both
  3.10+).
- `JSON validation for generated JSON artifacts` — `operator_dashboard_payload.json`
  and `SUPERVISOR_SUMMARY.json` are emitted as valid JSON.
- `npm run sync:proof-artifacts if dashboard payload changed` — the
  dashboard payload is a new file under
  `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/`;
  the sync target should regenerate the frontend's proof-artifact index.
- `npm run typecheck if frontend changed` — **not applicable** to this
  slice (no frontend files changed).
- `npm run build if frontend changed` — **not applicable** (no frontend
  files changed).
- `high-confidence secret scan clean` — no API keys, tokens, or
  passwords were emitted; no `.env`, `secrets`, or credential files were
  touched.
- `safety scan confirms no live/exchange/capital action and no legacy
  Redis mutation` — confirmed by inspection above.
