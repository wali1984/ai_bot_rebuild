#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

g4dir = Path(__file__).resolve().parents[1] / ".local_models/paper_provisional/gen4"
rep = json.load(open(g4dir / "serving_checkpoint_training_report_v2.json"))
bun = json.load(open(g4dir / "serving_checkpoint_bundle_v2.json"))

out = {
    "report_top_keys": list(rep.keys()),
    "checkpoint_id": rep.get("checkpoint_id"),
    "checkpoint_path": rep.get("checkpoint_path"),
    "checkpoint_file_sha256_report": rep.get("checkpoint_file_sha256"),
    "feature_abi_sha256": rep.get("feature_abi_sha256"),
    "manifest_id": rep.get("manifest_id"),
    "manifest_sha256": rep.get("manifest_sha256"),
    "activation_eligible": rep.get("activation_eligible"),
    "activation_block_reason": rep.get("activation_block_reason"),
    "live_eligible": rep.get("live_eligible"),
    "paper_only": rep.get("paper_only"),
    "exchange_action_taken": rep.get("exchange_action_taken"),
    "model_parameter_fingerprint": rep.get("model_parameter_fingerprint"),
    "metrics_keys": list(rep.get("metrics", {}).keys()),
    "metrics": rep.get("metrics"),
}
cp = Path(rep.get("checkpoint_path") or "")
if cp.is_file():
    out["checkpoint_recomputed_sha256"] = hashlib.sha256(cp.read_bytes()).hexdigest()
    out["checkpoint_bytes"] = cp.stat().st_size

print(json.dumps(out, indent=2, sort_keys=True))
