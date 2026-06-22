# V2 Full-Observation Position-History Tracker-Only Consumption Remediation

Generated: `2026-05-21T17:30:00Z`

GO/NO-GO: `V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION_REMEDIATION_READY`

## Scope

Patch-only remediation of the Codex fail blocker
`POSITION_HISTORY_CONSUMPTION_STILL_USES_RAW_V2_PAPER_INPUTS` on the
V2 full-observation builder. The tracker-derived position-context
fields now consume ONLY the Codex-passed tracker-owned Redis keys
(`v2:paper:position_history:*` and `v2:paper:position_price_track:*`).
The remaining rate / granular block-reason fields still use raw V2
paper inputs but are clearly relabeled with
`V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY` so the operator cannot
confuse them with tracker evidence.

This packet:

- does NOT enable live or canary trading
- does NOT place / cancel / modify exchange orders
- does NOT change leverage or margin
- does NOT create approvals
- does NOT modify legacy code or runtime
- does NOT stop legacy
- does NOT stop V2 runtime
- does NOT write to any old Redis namespace
- does NOT start a policy architecture port
- does NOT claim checkpoint compatibility

`live_gate=blocked_human_only`, `live_symbols=[]`, and
`live_enabled=false` are unchanged.

## Codex Fail Blocker Addressed

Codex's exact bypass proof:

> - `position_history_consumption_allowed=True`
> - tracker `position_history={"position_state": "NO_OPEN_POSITION", "accepted_intent_count": 0}`
> - raw `paper_ledger={"accepted": [{"symbol": "BTCUSDT"}]}`
> - output `position_context.v2_intents_accepted_count = 1.0`
> - output source: `V2_POSITION_HISTORY_AGGREGATOR`

Under the patched builder this exact scenario now yields:

> - output `position_context.v2_intents_accepted_count = 0.0`
> - output source: `V2_POSITION_HISTORY_TRACKER`

Verified by
`test_tracker_no_open_position_overrides_raw_ledger_accepted_row`.

## Source Patch

File:
[v2/backend/app/services/rl_core/full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py)

### 1. Two distinct extractors

```python
def _extract_tracker_history_fields(
    *,
    symbol: str,
    position_history: Mapping[str, Any] | None,
    consumption_allowed: bool | None,
    consumption_blocked_reason: str | None,
) -> list[tuple[str, float | None, str]]:
    """Strict tracker-only. NEVER reads paper_positions / paper_ledger
    / paper_intents / paper_intents_held."""
    ...

def _extract_raw_paper_context_fields(
    *,
    symbol: str,
    paper_intents,
    paper_intents_held,
    paper_ledger,
) -> list[tuple[str, float | None, str]]:
    """Strict raw-paper-only. NEVER reads the tracker payload. Source
    label is V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY."""
    ...
```

### 2. Field split

| Field | Source path |
| ----- | ----------- |
| `v2_position_history_present` | tracker-only |
| `v2_hold_time_seconds_current` | tracker-only |
| `v2_intents_accepted_count` | tracker-only |
| `v2_intents_held_count` | tracker-only |
| `v2_intents_blocked_count` | tracker-only |
| `v2_mfe_bps` | tracker-only |
| `v2_mae_bps` | tracker-only |
| `v2_roe_bps` | tracker-only |
| `v2_position_age_seconds` | tracker-only |
| `v2_hold_time_proxy_seconds` | tracker-only |
| `v2_pre_trade_allowed_rate` | raw paper (relabeled) |
| `v2_fee_gate_allowed_rate` | raw paper (relabeled) |
| `v2_churn_blocked_rate` | raw paper (relabeled) |
| `v2_block_reason_negative_expected_move_count` | raw paper (relabeled) |
| `v2_block_reason_edge_below_threshold_count` | raw paper (relabeled) |
| `v2_block_reason_feature_freshness_count` | raw paper (relabeled) |
| `v2_block_reason_checkpoint_required_count` | raw paper (relabeled) |
| `v2_block_reason_trainer_malformed_count` | raw paper (relabeled) |
| `v2_block_reason_other_count` | raw paper (relabeled) |

### 3. Retired conflated source label

`V2_POSITION_HISTORY_AGGREGATOR` no longer appears on any
position-context field. The label was the exact one Codex flagged
as conflated. Verified by
`test_zero_fill_count_stays_zero_and_no_aggregator_source_on_status_payload`
which walks `sample_present_fields` for every per-symbol entry and
asserts the label is absent.

### 4. Source-attribution constants

```python
SOURCE_TRACKER_HISTORY                = "V2_POSITION_HISTORY_TRACKER"
SOURCE_TRACKER_NO_OPEN_POSITION       = "V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION"
SOURCE_TRACKER_PAYLOAD_MISSING        = "V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING"
SOURCE_TRACKER_PAYLOAD_FIELD_MISSING  = "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
SOURCE_RAW_PAPER_CONTEXT              = "V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY"
SOURCE_RAW_PAPER_CONTEXT_MISSING      = "MISSING_V2_RAW_PAPER_CONTEXT"
# (dynamic) "V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>"
```

### 5. Behaviour matrix

| Tracker payload state | Tracker counts | MFE/MAE/ROE source | Counts source |
| --------------------- | --- | --- | --- |
| Allowed + OPEN_TRACKING + values | from tracker | `V2_POSITION_HISTORY_TRACKER` | `V2_POSITION_HISTORY_TRACKER` |
| Allowed + OPEN_TRACKING + null in tracker payload | 0 (tracker said so) or null | `V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING` | tracker / payload-field-missing |
| Allowed + NO_OPEN_POSITION | from tracker (often 0) | `V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION` | `V2_POSITION_HISTORY_TRACKER` |
| Allowed + tracker payload missing or wrong symbol | null | `V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING` | `V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING` |
| Consumption blocked (any reason) | null | `V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>` | same |

## Regression Tests

File:
[v2/backend/tests/integration/cli/test_v2_full_observation_position_history_tracker_only_consumption.py](v2/backend/tests/integration/cli/test_v2_full_observation_position_history_tracker_only_consumption.py)

10 new tests, each designed to fail under the prior code shape and
pass under the patched code:

- `test_tracker_no_open_position_overrides_raw_ledger_accepted_row` — exact Codex bypass proof reversed.
- `test_tracker_counts_win_when_raw_ledger_is_empty` — inverse Codex proof: tracker numbers must reach the output.
- `test_stale_heartbeat_masks_tracker_fields_even_with_open_tracker_payload` — gate-blocked path emits masked source.
- `test_raw_held_and_shadow_intents_do_not_inflate_tracker_accepted_count` — held/shadow rows in the raw ledger cannot inflate tracker accepted count.
- `test_mfe_mae_roe_remain_null_when_tracker_has_no_open_position_evidence` — explicit no-fabrication test.
- `test_raw_paper_context_fields_are_explicitly_labeled_not_tracker_history` — labels are disjoint.
- `test_zero_fill_count_stays_zero_and_no_aggregator_source_on_status_payload` — zero-fill invariant + no leak of legacy label.
- `test_builder_does_not_import_torch_or_read_legacy_filesystem` — module-load safety check.
- `test_status_payload_pins_legacy_safety_invariants` — full safety-flag pin.
- `test_every_position_context_source_belongs_to_known_disjoint_set` — guards against any new conflated label.

Two existing tests were updated to reflect the new contract (they
were asserting that paper-positions-presence alone could drive
`v2_position_history_present` — a behaviour the user explicitly
forbade). They now pass a tracker payload and assert the tracker
drives the flag.

## Validation

| Check | Result |
| ----- | ------ |
| `py_compile` of patched builder | PASS |
| New tracker-only regression tests | PASS (10 of 10) |
| Updated prior consumption-gate test | PASS |
| Updated TA-burndown position-context tests | PASS (3 rebound) |
| Combined focused test sweep | PASS (104 of 104) |
| JSON validation of packet outputs | PASS |
| Old-Redis-write scan on builder | PASS (0 hits) |
| Exchange-mutation scan on builder | PASS (0 hits) |
| Approval-token scan on builder | PASS (0 hits) |
| Live status refresh via `v2_full_observation_builder_status --once` | PASS |
| Legacy `V2_POSITION_HISTORY_AGGREGATOR` source label leak | ABSENT |

## Live Status Evidence

After running
`python3 -m v2.backend.app.cli.v2_full_observation_builder_status --once`:

| Field | Value |
| ----- | ----- |
| `state` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` (unchanged) |
| `position_history_consumption_allowed` | True |
| `position_history_consumption_state` | `ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT` |
| `zero_filled_field_count` | 0 |
| `no_zero_fill_for_unknown_fields` | True |
| `checkpoint_compatibility_claimed` | False |
| `policy_architecture_parity_claimed` | False |
| `per_symbol[*].generated_full_observation_dim` | 157 / 157 / 151 (unchanged) |
| Legacy `V2_POSITION_HISTORY_AGGREGATOR` in samples | ABSENT |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |

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
- policy architecture port: not started

## Final Decision

`V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION_REMEDIATION_READY`
