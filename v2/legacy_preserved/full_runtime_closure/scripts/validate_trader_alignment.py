#!/usr/bin/env python3
"""
Validate that `trading/trader.py` and `trading/trader-asjad.py` stay aligned on
critical execution safety logic added in Audit-Jan5-Fixes.

This is a static (text-based) check:
- Does NOT import trader modules (avoids exchange/network side-effects).
- Does NOT start/stop any services.

Run:
    python3 scripts/validate_trader_alignment.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "trading" / "trader.py"
ASJAD = ROOT / "trading" / "trader-asjad.py"


def _is_wrapper(text: str) -> bool:
    """
    Detect a thin wrapper module that delegates to another implementation.
    (e.g. trader-asjad.py importing trading.trader and calling main()).
    """
    t = (text or "").lower()
    return ("from trading.trader import" in t) or ("import trading.trader" in t)


@dataclass(frozen=True)
class Check:
    name: str
    needles: Tuple[str, ...]
    description: str


CHECKS: List[Check] = [
    Check(
        name="Free-margin precheck (avoid -2019 spam)",
        needles=(
            "ADAPTIVE-HEDGE",
            "Insufficient free margin for hedge",
            "Shrinking hedge qty due to free margin",
        ),
        description="Hedge opens must downsize/skip when available margin is insufficient.",
    ),
    Check(
        name="Hedge gross exposure cap: downsize instead of deadlock",
        needles=(
            "allowed_additional_margin_equiv",
            "hedge_gross_cap_max_notional",
            "capped_notional",
        ),
        description="When MAX_HEDGE_GROSS_EXPOSURE_PCT is hit, new hedge legs should be capped not hard-rejected.",
    ),
    Check(
        name="Action/category normalization present",
        needles=(
            "normalize_action_name",
            "get_action_category",
            "action_category",
        ),
        description="Signals must be normalized and categorized consistently (OPEN_RISK/HEDGE/PROTECTIVE/RECOVERY).",
    ),
]


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _check_file(label: str, text: str) -> List[str]:
    issues: List[str] = []
    for c in CHECKS:
        missing = [n for n in c.needles if n not in text]
        if missing:
            issues.append(f"{label}: missing for [{c.name}]: {missing}")
    return issues


def main() -> int:
    primary = _read(PRIMARY)
    asjad = _read(ASJAD)

    issues = []

    # If trader-asjad.py is a thin wrapper, validate only the shared implementation (trader.py)
    # plus minimal wrapper sanity. Otherwise validate both full implementations.
    if _is_wrapper(asjad):
        issues.extend(_check_file("trader.py", primary))
        # Wrapper must clearly reference the asjad account and configure a log file override.
        if "asjad" not in asjad.lower():
            issues.append("trader-asjad.py(wrapper): expected to contain 'asjad' identifier but did not find it")
        if "trader_log_file" not in asjad.lower():
            issues.append("trader-asjad.py(wrapper): expected to set TRADER_LOG_FILE override but did not find it")
    else:
        issues.extend(_check_file("trader.py", primary))
        issues.extend(_check_file("trader-asjad.py", asjad))

    # Basic sanity: account-specific file should mention asjad somewhere (helps prevent mis-wiring)
    if "asjad" not in asjad.lower():
        issues.append("trader-asjad.py: expected to contain 'asjad' identifier but did not find it")

    if issues:
        print("❌ FAIL: trader alignment checks failed")
        for it in issues:
            print(f"- {it}")
        return 1

    print("✅ PASS: trader alignment checks OK")
    for c in CHECKS:
        print(f"- {c.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


