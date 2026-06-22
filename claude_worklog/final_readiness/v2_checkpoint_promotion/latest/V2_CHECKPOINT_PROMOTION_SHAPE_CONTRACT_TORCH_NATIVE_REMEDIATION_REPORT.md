# V2 Checkpoint Promotion Shape-Contract Torch-Native Remediation Report

- **Task ID**: `fix_v2_gap_checkpoint_promotion_shape_contract_torch_native`
- **Kind**: shape-contract orientation realignment (metadata-only, paper-only)
- **Generated**: 2026-05-26T17:53:40Z
- **Git HEAD**: 10513bbe0517fd81c9c87e4672bb15486a083c02
- **GO/NO-GO**: `V2_CHECKPOINT_PROMOTION_SHAPE_CONTRACT_TORCH_NATIVE_REMEDIATION_READY`

## Why this remediation existed

The completed task `claude_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract`
(state-of-truth completed 2026-05-24) added the shape-contract scaffold to
`v2/backend/app/services/rl_core/checkpoint_promotion.py`, but the
contract declared `tensor_shapes_per_layer` in legacy input-first
`[in, out]` form (`w1=[26,16]`, `w2=[16,5]`, `w_exp=[16]`).

The V2 native CPU forward in `v2/backend/app/services/rl_core/policy.py`
indexes the flat weight buffer as `w[j*in_dim + i]` with `j` iterating
the output dim — i.e. torch-native `[out, in]`. So any future operator
sidecar emitted from a real torch `nn.Linear(in, out).weight=[out, in]`
checkpoint would have been wrongly tagged
`CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH`, even though the underlying
weights are bit-for-bit compatible with V2's runtime layout.

That issue was Codex P1, but it lived outside the previous task's
`required_v2_files_to_modify=[checkpoints.py, policy.py]`, so it was
intentionally not patched inside that task scope. This narrow follow-up
task (allowed files: `checkpoint_promotion.py`,
`test_v2_checkpoint_promotion_status.py`,
`CHECKPOINT_PROMOTION_PROTOCOL.{md,json}`, and the
operator dashboard payload) closes the gap.

## What changed

### 1. `v2/backend/app/services/rl_core/checkpoint_promotion.py`

- `V2_POLICY_SHAPE_CONTRACT["tensor_shapes_per_layer"]` flipped to
  torch-native output-first:

  | layer  | before        | after         | flat count |
  |--------|---------------|---------------|------------|
  | w1     | `[26, 16]`    | `[16, 26]`    | 416        |
  | b1     | `[16]`        | `[16]`        |  16        |
  | w2     | `[16,  5]`    | `[ 5, 16]`    |  80        |
  | b2     | `[ 5]`        | `[ 5]`        |   5        |
  | w_exp  | `[16]`        | `[ 1, 16]`    |  16        |
  | b_exp  | `[ 1]`        | `[ 1]`        |   1        |

- New constants:
  - `TENSOR_SHAPE_LAYOUT_CONVENTION = "TORCH_NATIVE_OUTPUT_FIRST_OUT_IN"`
  - `TENSOR_SHAPE_LAYOUT_FIELD = "tensor_shape_layout"`
  - `TENSOR_SHAPE_LAYOUT_TORCH_OUTPUT_FIRST = "TORCH_OUTPUT_FIRST"`
  - `TENSOR_SHAPE_LAYOUT_INPUT_FIRST = "INPUT_FIRST"`
- New per-candidate orientation enum:
  - `ORIENTATION_TORCH_OUTPUT_FIRST`
  - `ORIENTATION_METADATA_INPUT_FIRST_NORMALIZED`
  - `ORIENTATION_SHAPE_MISMATCH`
  - `ORIENTATION_NOT_EVALUATED`
- `_validate_shape_contract()` now:
  1. Always validates flat counts (transpose invariant).
  2. Validates bias shapes (orientation-independent).
  3. If sidecar declares `tensor_shape_layout == "INPUT_FIRST"`,
     transposes each weight and compares against the torch-native
     contract; success → `METADATA_INPUT_FIRST_NORMALIZED`.
  4. Otherwise (absent or `TORCH_OUTPUT_FIRST`) compares directly →
     `TORCH_OUTPUT_FIRST` on match.
  5. Any other layout value → `SHAPE_MISMATCH` (fail closed).
- `CandidateResult` and the JSON payload gained two fields:
  `shape_contract_orientation`, `declared_tensor_shape_layout`.
- `scan_local_models()` payload bumped schema_version to
  `v2_checkpoint_promotion_status_v2_torch_native_shape_contract` and
  now reports per-orientation counts.
- Safety constants unchanged; added explicit `no_torch_imported: true`
  to the payload to make it queryable from operator UIs.

### 2. `v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py`

Rewritten to cover 21 cases:

| # | Test | What it proves |
|---|---|---|
| 1 | `test_scan_returns_operator_required_when_root_absent` | Missing root reports operator required |
| 2 | `test_scan_returns_operator_required_when_root_empty` | Empty root reports operator required |
| 3 | `test_blob_without_metadata_reports_metadata_missing` | Blob alone is insufficient |
| 4 | `test_metadata_without_blob_reports_blob_missing` | Sidecar alone is insufficient |
| 5 | `test_torch_output_first_metadata_promotes_with_orientation_marker` | Torch-native sidecar with explicit marker promotes |
| 6 | `test_torch_native_metadata_without_layout_marker_defaults_to_torch_output_first` | Default branch matches torch contract |
| 7 | `test_input_first_metadata_normalizes_when_layout_marker_explicit` | Input-first sidecar with `INPUT_FIRST` marker normalizes to TORCH_OUTPUT_FIRST contract |
| 8 | `test_input_first_metadata_fails_closed_without_layout_marker` | Regression guard: legacy `[in, out]` without marker is rejected |
| 9 | `test_shape_mismatch_is_reported_per_layer` | obs_dim mismatch + per-layer mismatch surfaced |
| 10 | `test_shape_mismatch_when_layer_dim_swapped_under_torch_layout` | `[26,16]` declared TORCH_OUTPUT_FIRST is rejected |
| 11 | `test_invalid_layout_value_fails_closed` | Unknown layout value rejected with error field |
| 12 | `test_metadata_with_live_approval_is_refused` | `approves_live=true` blocked |
| 13 | `test_paper_only_must_be_true` | `paper_only=false` blocked |
| 14 | `test_v2_policy_shape_contract_is_torch_native_output_first` | Asserts canonical contract values |
| 15 | `test_flat_counts_remain_unchanged` | Asserts flat-count invariants |
| 16 | `test_cli_emits_operator_required_when_root_absent` | CLI dual-mirror (worklog + public) JSON identical, GO/NO-GO and safety fields correct |
| 17 | `test_module_does_not_import_torch` | Importing the module does not pull in torch |
| 18 | `test_module_does_not_deserialize_pickle` | Module source contains no `pickle` / `torch.load` calls and scanning never imports torch |
| 19 | `test_scanner_only_reads_within_approved_root` | All result paths are rooted under the supplied directory |
| 20 | `test_scanner_does_not_touch_legacy_dir_path` | Source contains no legacy directory string literals |
| 21 | `test_default_approved_root_is_local_models` | Approved root constant is `.local_models` |

### 3. `claude_worklog/final_readiness/v2_checkpoint_promotion/latest/CHECKPOINT_PROMOTION_PROTOCOL.md`

Rewritten to document:

- the torch-native canonical sidecar (torch-output-first `[out, in]`);
- the optional `tensor_shape_layout` field, its default
  (`TORCH_OUTPUT_FIRST`) and the legacy `INPUT_FIRST` opt-in;
- the four `shape_contract_orientation` output values;
- the same safety rules as before, with explicit no-torch / no-pickle
  scanner constraint.

### 4. `claude_worklog/final_readiness/v2_checkpoint_promotion/latest/checkpoint_promotion_protocol.json`

Schema bumped to
`v2_checkpoint_promotion_protocol_v2_torch_native_shape_contract`.
Includes:

- updated `tensor_shapes_per_layer`,
- new `tensor_shape_layout_field_semantics` block,
- `tensor_shapes_per_layer_input_first_legacy_normalizable_form`,
- `shape_contract_orientation_values` enum.

### 5. `v2/frontend/public/v2_checkpoint_promotion/latest/operator_dashboard_payload.json` + dist mirror + worklog status

Regenerated via the CLI:

```
PYTHONPATH=. ./.venv/bin/python3 -m v2.backend.app.cli.v2_checkpoint_promotion_status --once
```

All three files share sha256
`59d777ff708dabb09cd64ae4120245997ff702485108909bdd9eb38604d2a7bb` and
now carry the torch-native contract plus
`orientation_counts={TORCH_OUTPUT_FIRST:0, METADATA_INPUT_FIRST_NORMALIZED:0, SHAPE_MISMATCH:0, NOT_EVALUATED:0}`.

## What did NOT change

- `v2/backend/app/services/rl_core/policy.py` — already torch-native; the
  flat-index forward at `policy.py:116` was the reason for the
  realignment.
- `v2/backend/app/services/rl_core/checkpoints.py` — unrelated lane (P0.2C
  inventory + safe_load_metadata_only).
- `v2/backend/app/cli/v2_checkpoint_promotion_status.py` — no code
  changes needed; CLI re-uses the scanner.
- Any legacy directory file — never touched, never read.
- `v2/frontend/public/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json`
  — owned by a separate stream and refreshed there.
- No Redis writes. No V2 service restart. No exchange call.

## Verification

```
PYTHONPATH=. ./.venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py \
  v2/backend/tests/integration/cli/test_v2_rl_core_p0_2c_checkpoint.py -v
```

Result: **28 passed, 0 failed**
(21 checkpoint-promotion tests + 7 rl_core P0.2C tests).

## Safety invariants

- `live_gate = "blocked_human_only"`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- scanner does not import torch
- scanner does not deserialize pickle
- scanner reads only `.local_models/` (or the test-supplied override
  root)
- legacy directory not modified, not started, not stopped
- no exchange-mutation call placed
- no Redis key written
- no V2 runtime service restarted by this remediation

## Operator next steps (out of scope for this remediation)

1. Drop a torch-emitted checkpoint into `.local_models/` along with its
   `_metadata.json` (torch-output-first or input-first + explicit
   `tensor_shape_layout`).
2. Run the CLI; result must be
   `CHECKPOINT_PROMOTION_READY_FOR_CODEX_SHAPE_REVIEW`.
3. Hand the candidate to Codex for a shape-only inspection before any
   weight-loading lane is opened (still gated behind a separate
   operator-approved task).
