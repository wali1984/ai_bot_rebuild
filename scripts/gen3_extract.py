#!/usr/bin/env python3
import json
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
rep = json.load(open(repo / "goal_state/PERMANENT_SYSTEM_RECOVERY/serving_checkpoint_training_report_v2.json"))
m = rep.get("metrics", {})


def slim(d):
    if not isinstance(d, dict):
        return d
    return {
        "rows": d.get("rows"),
        "accuracy": d.get("accuracy"),
        "directional_rate": d.get("directional_rate"),
        "prediction_distribution": d.get("prediction_distribution"),
        "selected_directional_positive_edge_rate": d.get("selected_directional_positive_edge_rate"),
        "directional_net_edge_mae_bps": d.get("directional_net_edge_mae_bps"),
    }


cal = m.get("calibration", {})
out = {
    "checkpoint_id": rep.get("checkpoint_id"),
    "checkpoint_file_sha256": rep.get("checkpoint_file_sha256"),
    "manifest_id": rep.get("manifest_id"),
    "feature_abi_sha256": rep.get("feature_abi_sha256"),
    "final_loss": m.get("final_loss"),
    "optimizer_steps": m.get("optimizer_steps"),
    "training": slim(m.get("training")),
    "validation": slim(m.get("validation")),
    "holdout": slim(m.get("holdout")),
    "calibration": {"fitted": cal.get("fitted"), "temperature": cal.get("temperature"), "reason": cal.get("reason"), "sample": cal.get("sample"), "win_rate": cal.get("win_rate")},
    "activation_eligible": rep.get("activation_eligible"),
    "activation_block_reason": rep.get("activation_block_reason"),
}
print(json.dumps(out, indent=2, sort_keys=True))
