"""Read-only presentation helpers for paper probation gate status."""

from __future__ import annotations

from typing import Any


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def probation_gate_display_status(gate: dict[str, Any] | None) -> str:
    """Return operator-facing accumulation text without changing raw gate state."""

    payload = gate if isinstance(gate, dict) else {}
    raw_status = str(
        payload.get("status") or "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED"
    )
    closed = _int_or_none(payload.get("closed_count"))
    if closed is None:
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        closed = _int_or_none(checks.get("closed_probation_trades"))
    required = _int_or_none(payload.get("required_closed_count"))
    if required is None:
        required = _int_or_none(payload.get("window")) or 5

    if (
        raw_status == "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED"
        and closed is not None
        and required is not None
        and 0 <= closed < required
    ):
        return f"ACCUMULATING_{closed}_OF_{required}"
    return raw_status
