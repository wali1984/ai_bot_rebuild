from __future__ import annotations

from dataclasses import dataclass


_ACTION_ALIASES = {
    "open_long": "long",
    "open_short": "short",
    "close_long": "close",
    "close_short": "close",
    "abstain": "hold",
}


@dataclass(frozen=True)
class PositionTransitionResult:
    valid: bool
    position_before: str
    requested_action: str
    position_after: str
    reject_reason: str | None
    allowed_actions: dict[str, bool]


def normalize_position_state(value: str | None) -> str:
    text = str(value or "FLAT").strip().upper()
    if text in {"FLAT", "LONG", "SHORT", "LONG_HEDGE", "SHORT_HEDGE"}:
        return text
    return "FLAT"


def normalize_position_action(value: str | None) -> str:
    text = str(value or "hold").strip().lower()
    return _ACTION_ALIASES.get(text, text)


def build_position_action_mask(
    position_state: str | None,
    *,
    hedge_mode: bool = False,
) -> dict[str, bool]:
    state = normalize_position_state(position_state)
    if hedge_mode and state in {"LONG_HEDGE", "SHORT_HEDGE"}:
        return {
            "hold": True,
            "long": state != "LONG_HEDGE",
            "short": state != "SHORT_HEDGE",
            "close": True,
        }
    if state == "FLAT":
        return {"hold": True, "long": True, "short": True, "close": False}
    if state == "LONG":
        return {"hold": True, "long": False, "short": False, "close": True}
    if state == "SHORT":
        return {"hold": True, "long": False, "short": False, "close": True}
    return {"hold": True, "long": False, "short": False, "close": True}


def validate_position_transition(
    *,
    position_before: str | None,
    requested_action: str | None,
    position_after: str | None = None,
    hedge_mode: bool = False,
    allow_flip_via_close: bool = False,
) -> PositionTransitionResult:
    before = normalize_position_state(position_before)
    action = normalize_position_action(requested_action)
    allowed_actions = build_position_action_mask(before, hedge_mode=hedge_mode)
    if action not in allowed_actions:
        return PositionTransitionResult(
            valid=False,
            position_before=before,
            requested_action=action,
            position_after=normalize_position_state(position_after),
            reject_reason="unknown_action",
            allowed_actions=allowed_actions,
        )
    expected_after = before
    if action == "long":
        expected_after = "LONG_HEDGE" if hedge_mode and before == "FLAT" else "LONG"
    elif action == "short":
        expected_after = "SHORT_HEDGE" if hedge_mode and before == "FLAT" else "SHORT"
    elif action == "close":
        expected_after = "FLAT"
    after = normalize_position_state(position_after or expected_after)
    if not allowed_actions.get(action, False):
        reject_reason = "flip_requires_close_flow" if action in {"long", "short"} else "action_not_allowed"
        return PositionTransitionResult(
            valid=False,
            position_before=before,
            requested_action=action,
            position_after=after,
            reject_reason=reject_reason,
            allowed_actions=allowed_actions,
        )
    if before == "LONG" and action == "short" and not allow_flip_via_close:
        return PositionTransitionResult(
            valid=False,
            position_before=before,
            requested_action=action,
            position_after=after,
            reject_reason="flip_requires_close_flow",
            allowed_actions=allowed_actions,
        )
    if before == "SHORT" and action == "long" and not allow_flip_via_close:
        return PositionTransitionResult(
            valid=False,
            position_before=before,
            requested_action=action,
            position_after=after,
            reject_reason="flip_requires_close_flow",
            allowed_actions=allowed_actions,
        )
    if after != expected_after:
        return PositionTransitionResult(
            valid=False,
            position_before=before,
            requested_action=action,
            position_after=after,
            reject_reason="position_after_mismatch",
            allowed_actions=allowed_actions,
        )
    return PositionTransitionResult(
        valid=True,
        position_before=before,
        requested_action=action,
        position_after=after,
        reject_reason=None,
        allowed_actions=allowed_actions,
    )
