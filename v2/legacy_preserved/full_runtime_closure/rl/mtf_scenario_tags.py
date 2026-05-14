"""
Multi-TF scenario tags for proposals and signals (audit / operator policy).

Adds stable, human-readable tags derived from existing tf_bias_dir / tf_votes /
action direction. Gated by ENABLE_MTF_SCENARIO_TAGS (default on).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from rl.tf_aggregator import _vote_dir


def _dir_from_action(action: Any) -> int:
    return _vote_dir(action, None)


def compute_mtf_scenario_tags(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return tags to merge into payload (does not mutate).
    """
    try:
        import config as _cfg

        if not bool(getattr(_cfg, "ENABLE_MTF_SCENARIO_TAGS", True)):
            return {}
    except Exception:
        pass

    action = (
        payload.get("action")
        or payload.get("action_name")
        or payload.get("final_action")
        or payload.get("predicted_action")
        or ""
    )
    act_dir = _dir_from_action(action)
    bias_dir = int(payload.get("tf_bias_dir") if payload.get("tf_bias_dir") is not None else payload.get("bias_dir") or 0)
    timing_dir = int(payload.get("tf_timing_dir") if payload.get("tf_timing_dir") is not None else payload.get("timing_dir") or 0)
    conflict = float(payload.get("tf_conflict_score") if payload.get("tf_conflict_score") is not None else payload.get("conflict_score") or 0.0)

    primary_tf = str(
        payload.get("source_tf")
        or payload.get("timeframe")
        or payload.get("tf")
        or "multi"
    ).strip() or "multi"

    contrary_htf_bias = False
    if act_dir != 0 and bias_dir != 0 and act_dir != bias_dir:
        contrary_htf_bias = True

    if act_dir == 0:
        scenario = "NO_DIRECTION"
    elif bias_dir == 0:
        scenario = "NEUTRAL_HTF"
    elif act_dir == bias_dir:
        scenario = "ALIGNED_HTF"
    elif act_dir == timing_dir and timing_dir != bias_dir:
        scenario = "LTF_VS_HTF"
    elif contrary_htf_bias:
        scenario = "COUNTER_HTF"
    else:
        scenario = "MIXED"

    mtf_scenario_id = f"{scenario}|act={act_dir}|bias={bias_dir}|timing={timing_dir}|cf={conflict:.2f}"

    return {
        "mtf_scenario_id": mtf_scenario_id,
        "primary_tf": primary_tf,
        "contrary_htf_bias": contrary_htf_bias,
        "mtf_structural_bias_dir": bias_dir,
        "mtf_timing_dir": timing_dir,
        "mtf_action_dir": act_dir,
    }


def enrich_payload_mtf_scenario_tags(payload: Optional[Dict[str, Any]]) -> None:
    """In-place merge of scenario tags."""
    if not isinstance(payload, dict):
        return
    tags = compute_mtf_scenario_tags(payload)
    for k, v in tags.items():
        if v is not None and payload.get(k) is None:
            payload[k] = v
