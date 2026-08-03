from __future__ import annotations

from typing import Any


def classify_masa_ppo_disagreement(row: dict[str, Any]) -> dict[str, Any]:
    masa_dir = str(row.get("masa_direction") or row.get("masa_selected_direction") or "").lower()
    ppo_action = str(row.get("ppo_selected_action") or row.get("selected_action") or "").lower()
    masa_move = row.get("masa_expected_move_bps") or row.get("expected_move_bps")
    masa_conf = row.get("masa_confidence") or row.get("confidence_calibrated")
    try:
        move = float(masa_move) if masa_move is not None else None
    except (TypeError, ValueError):
        move = None
    try:
        conf = float(masa_conf) if masa_conf is not None else None
    except (TypeError, ValueError):
        conf = None
    classes: list[str] = []
    if masa_dir and ppo_action in {"long", "short"} and masa_dir not in {ppo_action, "up" if ppo_action == "long" else "down"}:
        classes.append("DIRECTION_DISAGREEMENT")
    if conf is not None and conf < 0.55 and ppo_action in {"long", "short"}:
        classes.append("CONFIDENCE_DISAGREEMENT")
    if ppo_action == "hold" and move is not None and abs(move) >= 8.0:
        classes.append("PPO_HOLD_MASA_TRADE")
    if ppo_action in {"long", "short"} and (move is None or abs(move) < 1.0):
        classes.append("PPO_TRADE_MASA_NO_EDGE")
    if not classes:
        classes.append("AGREEMENT_OR_INSUFFICIENT_MASA_FIELDS")
    agreement_score = 100.0 if classes == ["AGREEMENT_OR_INSUFFICIENT_MASA_FIELDS"] else max(0.0, 100.0 - 25.0 * len(classes))
    return {
        "prediction_id": row.get("prediction_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "masa_direction_probability": row.get("masa_direction_probability"),
        "masa_expected_move_bps": move,
        "masa_confidence": conf,
        "ppo_action_probabilities": row.get("ppo_action_probabilities") or row.get("policy_action_probabilities"),
        "ppo_selected_action": ppo_action or None,
        "ppo_policy_value": row.get("ppo_policy_value"),
        "masa_ppo_agreement_score": agreement_score,
        "masa_ppo_disagreement_reason": classes[0],
        "disagreement_classes": classes,
        "actionability_adjustment": "DOWNRANK_OR_BLOCK" if classes != ["AGREEMENT_OR_INSUFFICIENT_MASA_FIELDS"] else "NONE",
    }
