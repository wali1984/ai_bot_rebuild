from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import time


def _now_ms() -> int:
    return int(time.time() * 1000)


def read_equity_usd(r, account_id: str) -> Optional[float]:
    keys = [
        f"portfolio:equity:{account_id}",
        f"portfolio:{account_id}:equity",
        "portfolio:primary:equity",
        "portfolio:equity:primary",
    ]
    for k in keys:
        try:
            v = r.get(k)
            if v is not None:
                return float(v)
        except Exception:
            continue
    return None


def phase_cap_margin(equity: float, phase: Dict[str, Any]) -> float:
    pct = float(phase.get("per_pos_margin_pct", 0.0) or 0.0)
    return max(0.0, equity * pct)


def preflight_invariants(
    *,
    r,
    account_id: str,
    phases: list,
    min_open_notional_usd: float,
    min_open_margin_usd: float,
    resolve_phase_fn,
) -> Tuple[bool, str]:
    eq = read_equity_usd(r, account_id)
    if eq is None:
        return True, "WARN:NO_EQUITY_YET"

    phase = resolve_phase_fn(eq, phases)
    cap = phase_cap_margin(eq, phase)

    if min_open_margin_usd > 0 and cap > 0 and min_open_margin_usd > cap:
        return False, (
            "FATAL:MIN_OPEN_MARGIN_GT_CAP "
            f"min_open_margin={min_open_margin_usd} cap={cap:.2f} equity={eq:.2f} phase={phase.get('name')}"
        )
    if min_open_notional_usd > 0 and cap > 0 and min_open_notional_usd > (cap * 50):
        return False, (
            "FATAL:MIN_OPEN_NOTIONAL_IMPLIES_MARGIN_GT_CAP "
            f"min_open_notional={min_open_notional_usd} cap_margin={cap:.2f}"
        )

    return True, "OK"
