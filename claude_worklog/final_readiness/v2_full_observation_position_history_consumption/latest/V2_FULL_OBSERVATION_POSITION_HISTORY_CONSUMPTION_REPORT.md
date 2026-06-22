# V2 Full-Observation Position-History Consumption (Partial Progress)

Generated: `2026-05-21T16:44:55Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_HISTORY_CONSUMPTION_READY_PARTIAL_PROGRESS`

## Scope

Codex passed the persistent position-history tracker daemon with
`V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS`. This
packet wires the V2 full-observation builder to consume the
tracker's Redis keys as V2-owned evidence, gated on the tracker
Codex PASS marker and on heartbeat freshness. The aggregator
math, source-attribution conventions, and explicit-missing-source
behaviour for NO_OPEN_POSITION are preserved.

This packet:

- adds a tracker-consumption gate to the full-observation builder
- masks the tracker-derived position-context fields when the gate
  is blocked (instead of zero-filling them)
- surfaces the gate decision in the full-observation status JSON
  and the operator-runtime mirrors
- keeps `zero_filled_field_count=0`,
  `no_zero_fill_for_unknown_fields=true`,
  `checkpoint_compatibility_claimed=false`,
  `policy_architecture_parity_claimed=false`,
  `live_gate=blocked_human_only`, `live_symbols=[]`

It does NOT modify legacy code or runtime, does NOT enable live or
canary trading, does NOT change leverage or margin, does NOT write
to any old Redis namespace, does NOT introduce an exchange
mutation surface, and does NOT create any approval.

The marker is `READY_PARTIAL_PROGRESS` rather than `READY` because
the full-observation builder remains in its existing
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` state: this
packet does not promise full-dimension parity, only that the
position-history slice is wired correctly and gated.

## Source Patch

File:
[v2/backend/app/services/rl_core/full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py)

### 1. Gate constants

```python
TRACKER_CODEX_PASS_MARKER_PATHS = (
    Path(".../v2_position_history_tracker_daemon_remediation/latest/codex_review/CODEX_GO_NO_GO.md"),
    Path(".../v2_position_history_persistent_tracker/latest/codex_review/CODEX_GO_NO_GO.md"),
)
ACCEPTED_TRACKER_CODEX_PASS_TOKENS = frozenset({
    "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS",
    "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS",
})
TRACKER_HEARTBEAT_KEY = "v2:paper:position_history:heartbeat"
TRACKER_HEARTBEAT_MAX_AGE_SECONDS_DEFAULT = 180
```

Acceptance is permissive across the two PASS shapes so that whichever
of the related packets next emits a fresh PASS unblocks the gate.
The current live state passes via the daemon-remediation PASS marker
even though the older persistent-tracker packet still carries a
stale `*_CODEX_FAIL` content; the gate accepts either as long as at
least one matches.

### 2. Gate function

`evaluate_position_history_consumption_gate(...)` returns a
structured decision:

- `consumption_allowed` (bool)
- `blocked_reason` (None when allowed)
- `consumption_state`: one of
  `ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT`,
  `BLOCKED_TRACKER_NOT_CODEX_PASSED`,
  `BLOCKED_HEARTBEAT_MISSING`,
  `BLOCKED_HEARTBEAT_TTL_NOT_POSITIVE`,
  `BLOCKED_HEARTBEAT_STALE`
- per-marker probe + per-heartbeat probe fields

### 3. Per-symbol masking

`_build_position_context_slice` now accepts
`position_history_consumption_allowed` and
`position_history_consumption_blocked_reason`. When the gate is
explicitly blocked, the existing aggregator call is skipped and the
19 tracker-derived position-context field names are emitted with
`value=None` and source
`V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>`. The
`zero_filled_field_count` is unaffected because masked values are
counted as missing, not as zero-fill.

### 4. Top-level status payload

The status JSON now exposes:

- `position_history_consumption` (full gate result dict)
- `position_history_consumption_allowed`
- `position_history_consumption_blocked_reason`
- `position_history_consumption_state`
- `position_history_consumption_unblocked_after`
- `position_history_tracker_heartbeat_present` / `_fresh` / `_ttl_seconds` /
  `_age_seconds` / `_generated_utc`
- `position_history_tracker_codex_pass_marker_paths_passed` / `_failed`

## Live Gate Evidence

Refreshed via
`python3 -m v2.backend.app.cli.v2_full_observation_builder_status --once`
at `2026-05-21T16:44:55Z`. Live mirrors now report:

| Field | Value |
| ----- | ----- |
| `position_history_consumption_allowed` | True |
| `position_history_consumption_blocked_reason` | None |
| `position_history_consumption_state` | `ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT` |
| `position_history_tracker_heartbeat_present` | True |
| `position_history_tracker_heartbeat_fresh` | True |
| `position_history_tracker_heartbeat_ttl_seconds` | 862 |
| `position_history_tracker_heartbeat_age_seconds` | 38 |
| `position_history_tracker_heartbeat_generated_utc` | `2026-05-21T16:44:17Z` |
| `position_history_tracker_codex_pass_marker_paths_passed` | daemon-remediation PASS path |
| `position_history_tracker_codex_pass_marker_paths_failed` | persistent-tracker stale-FAIL path |
| `state` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` (unchanged) |
| `checkpoint_compatibility_claimed` | False |
| `policy_architecture_parity_claimed` | False |
| `no_zero_fill_for_unknown_fields` | True |
| `zero_filled_field_count` | 0 |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |

## NO_OPEN_POSITION Behaviour Preserved

When the gate is allowed but a symbol has no V2-owned open-position
evidence:

- `position_state=NO_OPEN_POSITION` in the tracker payload
- `v2_mfe_bps`, `v2_mae_bps`, `v2_roe_bps` remain `null`
- the field source is `MISSING_V2_OWNED_POSITION_RECORD`, never
  `V2_POSITION_HISTORY_AGGREGATOR` claiming a real value
- no synthesis of accepted positions
- no fabrication of excursion metrics

Verified by
`test_no_open_position_does_not_fabricate_mfe_mae_roe_in_allowed_path`.

## Fields Filled When Consumption Is Allowed

Per the user contract, only these fields are filled from the tracker
when the gate allows consumption — and only when real V2-owned
evidence exists for them:

- position age (`v2_position_age_seconds`, `v2_hold_time_proxy_seconds`)
- hold time (`v2_hold_time_seconds_current`)
- max favorable bps (`v2_mfe_bps`)
- max adverse bps (`v2_mae_bps`)
- unrealized bps (`v2_roe_bps`)
- accepted intent count (`v2_intents_accepted_count`)
- held intent count (`v2_intents_held_count`)
- block reason count (multiple `v2_block_reason_*_count` fields)

## Regression Tests

File:
[v2/backend/tests/integration/cli/test_v2_full_observation_position_history_consumption.py](v2/backend/tests/integration/cli/test_v2_full_observation_position_history_consumption.py)

12 new tests:

- `test_gate_allowed_when_codex_pass_and_heartbeat_fresh`
- `test_gate_accepts_persistent_tracker_pass_token_too`
- `test_gate_blocks_when_codex_pass_marker_missing`
- `test_gate_blocks_when_heartbeat_missing`
- `test_gate_blocks_when_heartbeat_stale`
- `test_gate_blocks_when_heartbeat_ttl_not_positive`
- `test_blocked_consumption_masks_tracker_fields_with_explicit_source`
- `test_allowed_consumption_emits_aggregator_sourced_fields`
- `test_no_open_position_does_not_fabricate_mfe_mae_roe_in_allowed_path`
- `test_status_payload_surfaces_consumption_gate`
- `test_status_payload_zero_fill_count_stays_zero_when_consumption_blocked`
- `test_module_default_pass_marker_paths_pin_codex_review_files`

## Validation

| Check | Result |
| ----- | ------ |
| `py_compile` of full-observation builder | PASS |
| Focused full-observation + tracker + recorder test sweep | PASS (94 of 94) |
| New consumption-gate tests | PASS (12 of 12) |
| JSON validation of packet outputs | PASS |
| Live status refresh via CLI | PASS |
| Live gate evaluates to `ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT` | PASS |

## Safety Posture

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `places_real_order=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `no_zero_fill_for_unknown_fields=true`
- `zero_filled_field_count=0`
- legacy code: unmodified
- legacy runtime: not stopped, not touched
- old Redis namespaces: not written
- exchange mutation surface: none introduced
- approvals: none created

## Final Decision

`V2_FULL_OBSERVATION_POSITION_HISTORY_CONSUMPTION_READY_PARTIAL_PROGRESS`
