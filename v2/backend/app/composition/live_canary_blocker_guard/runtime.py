from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .errors import LiveCanaryBlockerGuardCompositionError


REQUIRED_CANARY_GATES = (
    "human_final_approval_token_present",
    "paper_runtime_current",
    "live_gate_still_blocked_until_activation",
    "read_only_account_verified",
    "trade_permission_known",
    "isolated_margin_verified",
    "leverage_cap_verified",
    "stop_policy_runtime_proven",
    "kill_switch_runtime_proven",
    "daily_loss_gate_runtime_proven",
    "weekly_loss_gate_runtime_proven",
    "old_redis_write_isolated",
    "exchange_action_absent",
)

RISK_ADD_ACTIONS = frozenset(
    {
        "OPEN",
        "INCREASE",
        "FLIP",
        "HEDGE",
        "DCA",
        "REBALANCE",
        "ADJUST_LEVERAGE",
        "ADJUST_LEVERAGE_AND_POSITION",
        "OPEN_LONG",
        "OPEN_SHORT",
    }
)
DEFAULT_BLOCKED_ACTIONS = frozenset(
    {
        "HEDGE",
        "DCA",
        "ADJUST_LEVERAGE",
        "ADJUST_LEVERAGE_AND_POSITION",
    }
)


class LiveCanaryBlockerGuardRuntime:
    __slots__ = ("evaluate_now",)

    def __init__(self, *, evaluate_now: Callable[..., dict[str, Any]]) -> None:
        self.evaluate_now = evaluate_now


def build_live_canary_blocker_guard_runtime(
    *,
    now_ms_clock: Callable[[], int],
    max_paper_runtime_age_seconds: int = 300,
) -> LiveCanaryBlockerGuardRuntime:
    if not callable(now_ms_clock):
        raise LiveCanaryBlockerGuardCompositionError("must_be_callable", field="now_ms_clock")
    if not isinstance(max_paper_runtime_age_seconds, int) or max_paper_runtime_age_seconds < 1:
        raise LiveCanaryBlockerGuardCompositionError("must_be_positive_int", field="max_paper_runtime_age_seconds")

    def _evaluate_now(
        *,
        paper_runtime_payload: Mapping[str, Any],
        exchange_account_payload: Mapping[str, Any] | None = None,
        risk_runtime_payload: Mapping[str, Any] | None = None,
        intent_payload: Mapping[str, Any] | None = None,
        approval_token_present: bool = False,
    ) -> dict[str, Any]:
        now_ms = _valid_now_ms(now_ms_clock())
        paper = _as_mapping(paper_runtime_payload, "paper_runtime_payload")
        account = _as_mapping(exchange_account_payload, "exchange_account_payload")
        risk = _as_mapping(risk_runtime_payload, "risk_runtime_payload")
        paper_age = _age_seconds(now_ms, paper.get("generated_at"))
        live_gate = str(paper.get("live_gate_status") or "blocked_human_only")
        required_blocks_checked = set(_as_list(_as_mapping(paper.get("current_risk_decision"), "current_risk_decision").get("required_blocks_checked")))
        gates = {
            "human_final_approval_token_present": bool(approval_token_present),
            "paper_runtime_current": paper.get("runtime_state") == "PAPER_RUNTIME_ONLINE_ACTIVE" and paper_age is not None and paper_age <= max_paper_runtime_age_seconds,
            "live_gate_still_blocked_until_activation": live_gate == "blocked_human_only",
            "read_only_account_verified": account.get("read_only_account_status") == "VERIFIED_READONLY",
            "trade_permission_known": account.get("trade_permission_status") in {"DISABLED", "ENABLED_REQUIRES_APPROVAL"},
            "isolated_margin_verified": account.get("margin_mode") == "isolated" or risk.get("required_margin_mode") == "isolated",
            "leverage_cap_verified": _numeric(account.get("leverage_cap") or risk.get("leverage_cap")) is not None and (_numeric(account.get("leverage_cap") or risk.get("leverage_cap")) or 0) <= 1,
            "stop_policy_runtime_proven": "missing_stop_policy" in required_blocks_checked or risk.get("stop_policy_required") is True,
            "kill_switch_runtime_proven": "disabled_kill_switch" in required_blocks_checked or risk.get("kill_switch_required") is True,
            "daily_loss_gate_runtime_proven": "daily_loss_breach" in required_blocks_checked or risk.get("daily_loss_gate_required") is True,
            "weekly_loss_gate_runtime_proven": risk.get("weekly_loss_gate_required") is True,
            "old_redis_write_isolated": paper.get("legacy_redis_writes") is False,
            "exchange_action_absent": paper.get("exchange_orders") is False,
        }
        blockers = [name for name, passed in gates.items() if not passed]
        intent = _as_mapping(intent_payload, "intent_payload")
        intent_blockers = _intent_blockers(
            intent=intent,
            now_ms=now_ms,
            risk=risk,
            account=account,
        )
        gate_rows = [
            {
                "gate": name,
                "status": "PASS" if passed else "BLOCKED",
                "human_approval_required": name == "human_final_approval_token_present",
            }
            for name, passed in gates.items()
        ]
        return {
            "classification": "LIVE_CANARY_BLOCKED" if blockers or intent_blockers else "LIVE_CANARY_CAN_BE_CONSIDERED_BY_HUMAN_ONLY",
            "source": "V2_LIVE_CANARY_BLOCKER_GUARD",
            "generated_at_ms": now_ms,
            "paper_runtime_age_seconds": paper_age,
            "live_gate_status": live_gate,
            "gate_rows": gate_rows,
            "blockers": blockers,
            "intent_blockers": intent_blockers,
            "intent_evaluation_status": "BLOCKED" if intent_blockers else "NO_INTENT_BLOCKERS",
            "approval_token_present": bool(approval_token_present),
            "safe_for_live": False,
            "automation_can_enable_live": False,
        }

    return LiveCanaryBlockerGuardRuntime(evaluate_now=_evaluate_now)


def _as_mapping(value: Mapping[str, Any] | None, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LiveCanaryBlockerGuardCompositionError("must_be_mapping", field=field)
    return value


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _intent_blockers(
    *,
    intent: Mapping[str, Any],
    now_ms: int,
    risk: Mapping[str, Any],
    account: Mapping[str, Any],
) -> list[str]:
    if not intent:
        return []
    blockers: list[str] = []
    action = str(intent.get("action") or intent.get("side") or "").strip().upper()
    risk_add = action in RISK_ADD_ACTIONS

    if action in DEFAULT_BLOCKED_ACTIONS:
        blockers.append(f"{action.lower()}_disabled_by_default")
    if action in {"HEDGE", "DCA"}:
        blockers.append("hedge_dca_disabled_initially")

    if risk_add:
        for field in ("signal_id", "prediction_id", "feature_snapshot_id", "confidence", "source_module"):
            if not intent.get(field):
                blockers.append(f"missing_{field}")

        signal_ts = _generated_at_ms(intent.get("signal_generated_at_ms") or intent.get("signal_generated_at"))
        if signal_ts is None:
            blockers.append("missing_signal_timestamp")
        elif int((now_ms - signal_ts) / 1000) > int(_numeric(risk.get("max_risk_add_signal_age_seconds")) or 10):
            blockers.append("stale_risk_add_signal")

    if intent.get("exchange_order_id") and intent.get("exchange_order_id") in set(_as_list(intent.get("seen_exchange_order_ids"))):
        blockers.append("duplicate_exchange_order_id")
    if intent.get("execution_intent_id") and intent.get("execution_intent_id") in set(_as_list(intent.get("seen_execution_intent_ids"))):
        blockers.append("duplicate_execution_intent_id")
    if intent.get("signal_id") and intent.get("signal_id") in set(_as_list(intent.get("seen_signal_ids"))):
        blockers.append("duplicate_signal_id")

    margin_mode = str(intent.get("margin_mode") or account.get("margin_mode") or risk.get("required_margin_mode") or "").strip().lower()
    if margin_mode == "cross":
        blockers.append("cross_margin_blocked_for_canary")
    elif risk_add and margin_mode != "isolated":
        blockers.append("isolated_margin_not_verified")

    leverage_cap = None if "leverage_cap" in intent and intent.get("leverage_cap") is None else _numeric(intent.get("leverage_cap") or account.get("leverage_cap") or risk.get("leverage_cap"))
    leverage = _numeric(intent.get("leverage"))
    if leverage_cap is None:
        blockers.append("leverage_cap_unknown")
    elif leverage is not None and leverage > leverage_cap:
        blockers.append("leverage_above_cap")

    if intent.get("stop_policy_present") is False:
        blockers.append("missing_stop_policy")
    if intent.get("kill_switch_healthy") is False:
        blockers.append("kill_switch_unhealthy")
    if intent.get("daily_loss_gate_present") is False:
        blockers.append("daily_loss_gate_missing")
    if intent.get("weekly_loss_gate_present") is False:
        blockers.append("weekly_loss_gate_missing")
    if intent.get("market_feed_current") is False:
        blockers.append("market_feed_stale_or_missing")
    if intent.get("feature_snapshot_current") is False:
        blockers.append("feature_snapshot_stale_or_missing")
    if risk_add and "risk_config_version" in intent and not intent.get("risk_config_version"):
        blockers.append("missing_risk_config_version")
    elif risk_add and not (intent.get("risk_config_version") or risk.get("risk_config_version")):
        blockers.append("missing_risk_config_version")

    return sorted(set(blockers))


def _age_seconds(now_ms: int, generated_at: Any) -> int | None:
    generated_ms = _generated_at_ms(generated_at)
    if generated_ms is None:
        return None
    return max(0, int((now_ms - generated_ms) / 1000))


def _generated_at_ms(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    return None


def _valid_now_ms(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LiveCanaryBlockerGuardCompositionError("must_be_non_negative_int", field="now_ms_clock")
    return value
