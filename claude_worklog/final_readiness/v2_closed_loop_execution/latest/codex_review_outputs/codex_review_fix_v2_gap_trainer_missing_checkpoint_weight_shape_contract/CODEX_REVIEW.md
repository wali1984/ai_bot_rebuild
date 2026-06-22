# Codex Review: codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract

GO/NO-GO: `CODEX_REVIEW_FIX_V2_GAP_TRAINER_MISSING_CHECKPOINT_WEIGHT_SHAPE_CONTRACT_CODEX_FAIL`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Blockers

- 1. Realized PnL credit (signed)
- 1. Realized PnL credit (signed)
- 1. Realized PnL credit (signed)
- 1. Realized PnL credit (signed)
- 1. Realized PnL credit (signed)
- 1. Provide an operator-approved checkpoint blob under
- 1. The CLAUDE.md protected runtime policy forbids mutating or
- 1. The CLAUDE.md protected runtime policy forbids mutating or
- 1. The blob:
- Blocking finding:
- Blocking finding:
- Blocking findings:
- 1. [P1] `v2/backend/app/services/rl_core/checkpoint_promotion.py` declares promoted checkpoint tensor shapes as `w1=[26,16]` and `w2=[16,5]`, but a torch `Linear(in_features, out_features).weight` sidecar is output-first (`[16,26]` and `[5,16]`). A compatible operator-provided torch checkpoint sidecar would be rejected as `CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH`, so the checkpoint weight-shape contract gap remains unresolved.
- 1. [P1] `v2/backend/app/services/rl_core/checkpoint_promotion.py` declares promoted checkpoint tensor shapes as `w1=[26,16]` and `w2=[16,5]`, but a torch `Linear(in_features, out_features).weight` sidecar is output-first (`[16,26]` and `[5,16]`). A compatible operator-provided torch checkpoint sidecar would be rejected as `CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH`, so the checkpoint weight-shape contract gap remains unresolved.
- 1. **Protocol document** ([CHECKPOINT_PROMOTION_PROTOCOL.md](claude_worklog/final_readiness/v2_checkpoint_promotion/latest/CHECKPOINT_PROMOTION_PROTOCOL.md))
- 1. The blob:

## Raw Output (tail)

```text
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

exec
/bin/bash -lc "sed -n '1,260p' v2/backend/app/services/rl_core/policy_architecture_compatibility.py" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
"""Read-only policy-architecture compatibility analysis.

Compares V2's current paper policy (26-dim observation, 16-dim hidden,
5-action MLP) against the legacy production architecture
(LSTM + multi-head attention + MoE + CNN, 1911-dim observation, 3^10
joint action space). Static analysis only — no torch import, no pickle
load.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.legacy_observation_contract import (
    build_legacy_observation_contract,
    gap_vs_v2_compact,
)

V2_POLICY_FACTS: dict[str, Any] = {
    "module": "v2.backend.app.services.rl_core.policy",
    "obs_dim": 26,
    "hidden_dim": 16,
    "action_count": 5,
    "action_labels": ["hold", "long", "short", "close", "hedge"],
    "has_lstm": False,
    "has_attention": False,
    "has_regime_head": False,
    "has_moe": False,
    "has_cnn": False,
    "value_head": True,
    "expected_move_head": True,
    "deterministic_init": True,
    "torch_loaded_in_v2_process": False,
}

CLASSIFICATION_COMPATIBLE = "COMPATIBLE_WITH_CURRENT_V2_POLICY"
CLASSIFICATION_REQUIRES_POLICY_PORT = "REQUIRES_V2_POLICY_ARCHITECTURE_PORT"
CLASSIFICATION_REQUIRES_OBS_EXPANSION = "REQUIRES_OBSERVATION_VECTOR_EXPANSION"
CLASSIFICATION_UNKNOWN_METADATA = "UNKNOWN_METADATA_REQUIRED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def analyze_compatibility() -> dict[str, Any]:
    contract = build_legacy_observation_contract()
    gap = gap_vs_v2_compact(contract)
    legacy_arch = contract.get("legacy_architecture") or {}
    legacy_action_size = (contract.get("legacy_action_space") or {}).get(
        "action_space_size_resolved"
    )
    legacy_largest = contract.get("legacy_observation_largest_dim")
    classifications: list[str] = []
    if legacy_largest and legacy_largest > V2_POLICY_FACTS["obs_dim"]:
        classifications.append(CLASSIFICATION_REQUIRES_OBS_EXPANSION)
    if (
        legacy_arch.get("has_lstm")
        or legacy_arch.get("has_attention")
        or legacy_arch.get("has_moe")
        or legacy_arch.get("has_cnn")
    ):
        classifications.append(CLASSIFICATION_REQUIRES_POLICY_PORT)
    if (
        legacy_action_size is not None
        and legacy_action_size != V2_POLICY_FACTS["action_count"]
    ):
        classifications.append(CLASSIFICATION_REQUIRES_POLICY_PORT)
    if not classifications:
        classifications.append(CLASSIFICATION_UNKNOWN_METADATA)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for c in classifications:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    overall = (
        CLASSIFICATION_REQUIRES_POLICY_PORT
        if CLASSIFICATION_REQUIRES_POLICY_PORT in deduped
        else (
            CLASSIFICATION_REQUIRES_OBS_EXPANSION
            if CLASSIFICATION_REQUIRES_OBS_EXPANSION in deduped
            else CLASSIFICATION_UNKNOWN_METADATA
        )
    )
    return {
        "schema_version": "v2_policy_architecture_compatibility_v1",
        "generated_utc": _utc_iso(),
        "v2_policy_facts": V2_POLICY_FACTS,
        "legacy_architecture_facts": legacy_arch,
        "legacy_action_space_size_resolved": legacy_action_size,
        "legacy_largest_observation_dim": legacy_largest,
        "observation_dim_gap_legacy_minus_v2": gap.get(
            "observation_dim_gap_legacy_minus_v2"
        ),
        "classifications": deduped,
        "overall_classification": overall,
        "narrow_remediation_tasks_required": [
            "claude_fix_v2_gap_policy_architecture_shape_contract",
            "claude_fix_v2_gap_full_observation_vector_builder",
        ]
        if overall != CLASSIFICATION_COMPATIBLE
        else [],
        "paired_codex_review_task_ids_required": [
            "codex_review_fix_v2_gap_policy_architecture_shape_contract",
            "codex_review_fix_v2_gap_full_observation_vector_builder",
        ]
        if overall != CLASSIFICATION_COMPATIBLE
        else [],
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_compatibility_status(
    worklog_path: Path, public_path: Path
) -> dict[str, Any]:
    payload = analyze_compatibility()
    worklog_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog_path.write_text(body, encoding="utf-8")
    public_path.write_text(body, encoding="utf-8")
    return payload

exec
/bin/bash -lc "rg \"w1\\\": \\[26, 16\\]|w2\\\": \\[16, 5\\]|\\\"w_exp\\\": \\[16\\]\" -n v2/backend | head -n 50" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py:22:            "w1": [26, 16],
v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py:24:            "w2": [16, 5],
v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py:26:            "w_exp": [16],
v2/backend/app/services/rl_core/checkpoint_promotion.py:42:        "w1": [26, 16],
v2/backend/app/services/rl_core/checkpoint_promotion.py:44:        "w2": [16, 5],
v2/backend/app/services/rl_core/checkpoint_promotion.py:46:        "w_exp": [16],

exec
/bin/bash -lc ".venv/bin/python - <<'PY'
from pathlib import Path
import json, tempfile
from v2.backend.app.services.rl_core import checkpoint_promotion as cp

import tempfile
with tempfile.TemporaryDirectory() as d:
    p=Path(d)
    (p/'x.pt').write_bytes(b'1')
    md={\"checkpoint_id\":\"x\",\"source_legacy_path\":\"x\",\"source_legacy_sha256\":\"a\"*64,\"training_window_utc\":\"x\",\"obs_dim\":26,\"action_count\":5,\"action_labels\":[\"hold\",\"long\",\"short\",\"close\",\"hedge\"],\"tensor_shapes_per_layer\":{\"w1\":[16,26],\"b1\":[16],\"w2\":[5,16],\"b2\":[5],\"w_exp\":[1,16],\"b_exp\":[1]},\"operator_signature_id\":\"o\",\"paper_only\":True,\"approves_live\":False,\"approves_canary\":False,\"approves_legacy_shutdown\":False}
    (p/'x_metadata.json').write_text(json.dumps(md))
    out=cp.scan_local_models(p)
    print(out['overall_state'], out['candidates'][0]['shape_mismatch_fields'])
PY" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH ['tensor_shapes_per_layer.w1', 'tensor_shapes_per_layer.w2', 'tensor_shapes_per_layer.w_exp']

exec
/bin/bash -lc "cat > claude_worklog/final_readiness/v2_closed_loop_execution/latest/codex_review_outputs/codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract/CODEX_GO_NO_GO.md <<'EOF'
CODEX_REVIEW_FIX_V2_GAP_TRAINER_MISSING_CHECKPOINT_WEIGHT_SHAPE_CONTRACT_CODEX_FAIL
EOF" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
exec
/bin/bash -lc 'cat claude_worklog/final_readiness/v2_closed_loop_execution/latest/codex_review_outputs/codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract/CODEX_GO_NO_GO.md' in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
CODEX_REVIEW_FIX_V2_GAP_TRAINER_MISSING_CHECKPOINT_WEIGHT_SHAPE_CONTRACT_CODEX_FAIL

codex
The V2-side review should fail because the promoted checkpoint shape contract is still using an input-first tensor layout that mismatches torch-native `nn.Linear` weight layout, so the checkpoint-shape remediation gap is not actually fixed. The existing tests also encode the same mismatch, allowing the defect to be masked.

Full review comments:

- [P1] Align checkpoint shape contract with torch linear layout — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/rl_core/checkpoint_promotion.py:42-44
  `V2_POLICY_SHAPE_CONTRACT` in `checkpoint_promotion.py` still defines `w1` and `w2` as input-first shapes (`[26,16]`, `[16,5]`), but the live V2 policy consumes flattened weights in output-first order (`w[j * in_dim + i]`) and torch `nn.Linear` serializes weight as `[out_features, in_features]`. In the same environment, a valid operator-sidecar emitted from torch with `w1=[16,26]`, `w2=[5,16]` (and typically `w_exp=[1,16]`) will be rejected with `CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH`, so the task’s weight-shape blocker remains unresolved for real checkpoints.

- [P2] Update checkpoint promotion fixture to torch-compatible shapes — /home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py:22-24
  `_good_metadata()` in `test_v2_checkpoint_promotion_status.py` encodes the same incorrect shape layout as production code (`[26,16]`/`[16,5]`), so the integration test passes with an inverted contract and provides no protection against the real-world torch sidecar shape orientation. This makes the regression suite blind to the exact issue this task is meant to resolve, so a broken scanner can continue to ship if code changes elsewhere keep returning false-ready states.
The V2-side review should fail because the promoted checkpoint shape contract is still using an input-first tensor layout that mismatches torch-native `nn.Linear` weight layout, so the checkpoint-shape remediation gap is not actually fixed. The existing tests also encode the same mismatch, allowing the defect to be masked.

Full review comments:

- [P1] Align checkpoint shape contract with torch linear layout — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/rl_core/checkpoint_promotion.py:42-44
  `V2_POLICY_SHAPE_CONTRACT` in `checkpoint_promotion.py` still defines `w1` and `w2` as input-first shapes (`[26,16]`, `[16,5]`), but the live V2 policy consumes flattened weights in output-first order (`w[j * in_dim + i]`) and torch `nn.Linear` serializes weight as `[out_features, in_features]`. In the same environment, a valid operator-sidecar emitted from torch with `w1=[16,26]`, `w2=[5,16]` (and typically `w_exp=[1,16]`) will be rejected with `CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH`, so the task’s weight-shape blocker remains unresolved for real checkpoints.

- [P2] Update checkpoint promotion fixture to torch-compatible shapes — /home/wali/Desktop/AI BOT REBUILD/v2/backend/tests/integration/cli/test_v2_checkpoint_promotion_status.py:22-24
  `_good_metadata()` in `test_v2_checkpoint_promotion_status.py` encodes the same incorrect shape layout as production code (`[26,16]`/`[16,5]`), so the integration test passes with an inverted contract and provides no protection against the real-world torch sidecar shape orientation. This makes the regression suite blind to the exact issue this task is meant to resolve, so a broken scanner can continue to ship if code changes elsewhere keep returning false-ready states.
```
