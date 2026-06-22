# Codex 5.5 Review - V2 Checkpoint Promotion Shape Contract Torch-Native Remediation

Generated: 2026-05-26T14:08:07-0400 EDT

## Verdict

`V2_CHECKPOINT_PROMOTION_SHAPE_CONTRACT_TORCH_NATIVE_REMEDIATION_CODEX_PASS`

Codex verified the checkpoint-promotion shape-contract remediation. A torch
output-first sidecar is accepted, explicit input-first metadata is normalized,
flat-count invariants remain unchanged, and the scanner still avoids torch,
pickle/deserialization, legacy checkpoint reads, and live/canary/shutdown
approval.

## Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| New checkpoint-promotion task narrow/scoped | PASS | Remediation scope is limited to shape-contract orientation, metadata field handling, docs/status payloads, and tests. |
| Torch output-first sidecar shapes supported | PASS | Canonical contract is `w1=[16,26]`, `w2=[5,16]`, `w_exp=[1,16]`; tests accept torch-native metadata. |
| Input-first metadata normalized explicitly | PASS | `tensor_shape_layout=INPUT_FIRST` normalizes transposed weights and reports `METADATA_INPUT_FIRST_NORMALIZED`. |
| Missing layout defaults output-first | PASS | Missing `tensor_shape_layout` is treated as torch output-first; input-first shapes without the marker fail closed. |
| Flat count contract unchanged | PASS | `w1=416`, `b1=16`, `w2=80`, `b2=5`, `w_exp=16`, `b_exp=1`. |
| No torch import | PASS | Source scan found no `import torch` or `torch.load`; tests assert the module import does not load torch. |
| No pickle/deserialization | PASS | Source scan found no `import pickle`, `pickle.load`, `pickle.loads`, or checkpoint load path. |
| No legacy checkpoint path read | PASS | Scanner default root remains `.local_models`; code reads metadata/blobs only under the provided approved root. |
| `.local_models` root-only scanner remains | PASS | `APPROVED_ROOT = Path(".local_models")`; CLI/status tests cover absent-root and root-only behavior. |
| No live/canary/shutdown approval | PASS | Status payload keeps `approves_live=false`, `approves_canary=false`, `approves_legacy_shutdown=false`, `approves_redis_trim=false`. |
| No old Redis writes | PASS | Checkpoint scanner has no Redis client/write path; mutation key scans remain zero for protected live/order patterns. |
| `live_gate=blocked_human_only` | PASS | Promotion payload retains the blocked live gate. |
| `live_symbols=[]` | PASS | Promotion payload retains an empty live symbol list. |

This pass does not promote a real checkpoint and does not claim trained-model
compatibility beyond metadata shape inspection. Actual checkpoint blob approval
remains an operator-controlled paper-only promotion step.

## Verification

```text
python3 -m py_compile v2/backend/app/services/rl_core/checkpoint_promotion.py
```

Result: PASS

```text
PYTHONPATH=. .venv/bin/python -m pytest \
  v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py \
  v2/backend/tests/integration/cli/test_v2_rl_core_p0_2c_checkpoint.py -q
```

Result: `28 passed in 0.09s`

## Final Decision

`V2_CHECKPOINT_PROMOTION_SHAPE_CONTRACT_TORCH_NATIVE_REMEDIATION_CODEX_PASS`
