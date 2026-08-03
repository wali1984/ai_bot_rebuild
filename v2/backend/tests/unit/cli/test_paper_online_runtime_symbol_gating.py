"""Tests for Codex NO-GO fixes: paper symbol gating and position-derived clear flags."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.paper_online_runtime import (
    PAPER_POSITION_MIN_HOLD_SECONDS,
    _derive_intelligent_close_guard_clear,
    _derive_reduce_only_clear,
)


# ---------------------------------------------------------------------------
# _derive_reduce_only_clear
# ---------------------------------------------------------------------------

def test_reduce_only_clear_when_no_position():
    assert _derive_reduce_only_clear({"side": "long"}, None) is True


def test_reduce_only_clear_when_position_opposite_side():
    position = {"status": "OPEN", "side": "short"}
    assert _derive_reduce_only_clear({"side": "long"}, position) is True


def test_reduce_only_blocked_when_position_same_side():
    position = {"status": "OPEN", "side": "long"}
    assert _derive_reduce_only_clear({"side": "long"}, position) is False


def test_reduce_only_blocked_short_same_side():
    position = {"status": "OPEN", "side": "short"}
    assert _derive_reduce_only_clear({"side": "short"}, position) is False


def test_reduce_only_clear_when_intent_side_missing_and_no_position():
    assert _derive_reduce_only_clear({}, None) is True


def test_reduce_only_clear_when_position_side_missing():
    # Unknown position side: treating unknown as different side is safe (allow close)
    position = {"status": "OPEN", "side": None}
    assert _derive_reduce_only_clear({"side": "long"}, position) is True


# ---------------------------------------------------------------------------
# _derive_intelligent_close_guard_clear
# ---------------------------------------------------------------------------

def _ts(seconds_ago: float) -> str:
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)
    return ts.isoformat()


def test_close_guard_clear_when_no_position():
    assert _derive_intelligent_close_guard_clear(None, dt.datetime.now(dt.timezone.utc).isoformat()) is True


def test_close_guard_blocked_when_hold_time_not_met():
    too_young = PAPER_POSITION_MIN_HOLD_SECONDS - 10
    position = {"status": "OPEN", "opened_at": _ts(too_young)}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    assert _derive_intelligent_close_guard_clear(position, now) is False


def test_close_guard_clear_when_hold_time_met():
    old_enough = PAPER_POSITION_MIN_HOLD_SECONDS + 10
    position = {"status": "OPEN", "opened_at": _ts(old_enough)}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    assert _derive_intelligent_close_guard_clear(position, now) is True


def test_close_guard_blocked_when_opened_at_missing():
    position = {"status": "OPEN"}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    assert _derive_intelligent_close_guard_clear(position, now) is False


# ---------------------------------------------------------------------------
# Integration: apply_paper_tightening_gate rejects non-universe symbol
# ---------------------------------------------------------------------------

def _minimal_lineage(symbol: str = "BTCUSDT") -> dict:
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "signal": {"symbol": symbol, "side": "long", "generated_at": ts, "confidence": 0.9,
                   "confidence_calibrated": 0.9},
        "execution_intent": {"symbol": symbol, "side": "long"},
        "risk_decision": {
            "risk_action": "allow",
            "risk_result": "ALLOWED",
            "risk_reason_code": None,
            "required_blocks_checked": [],
        },
        "trainer_prediction": {
            "trainer_source": "v2_native",
            "confidence_calibrated": 0.9,
            "raw_output": {},
        },
        "feature_snapshot": {
            "freshness_state": "CURRENT",
            "generated_at": ts,
            "features": {},
        },
    }


def test_apply_tightening_gate_blocks_non_universe_symbol():
    from v2.backend.app.cli.paper_online_runtime import apply_paper_tightening_gate

    lineage = _minimal_lineage("NOTPAPERUSDT")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    result = apply_paper_tightening_gate(lineage, generated_at=now, recent_events=[])
    risk = result["risk_decision"]
    edge = risk.get("paper_edge_gate", {})
    assert edge.get("paper_symbol_allowed") is False, "non-universe symbol must be blocked"
    assert "SYMBOL_NOT_PAPER_ELIGIBLE_BLOCK" in (edge.get("blockers") or [])
    assert risk.get("risk_action") == "deny"


def test_apply_tightening_gate_reduce_only_derived_from_position():
    from v2.backend.app.cli.paper_online_runtime import apply_paper_tightening_gate

    lineage = _minimal_lineage("BTCUSDT")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    open_pos = {"status": "OPEN", "side": "long", "opened_at": now}
    result = apply_paper_tightening_gate(
        lineage, generated_at=now, recent_events=[], previous_position=open_pos
    )
    risk = result["risk_decision"]
    gate = risk.get("paper_protective_behavior_gate", {})
    # Same-side position → reduce_only NOT clear
    assert gate.get("reduce_only_protection_clear") is False


def test_apply_tightening_gate_reduce_only_clear_when_flat():
    from v2.backend.app.cli.paper_online_runtime import apply_paper_tightening_gate

    lineage = _minimal_lineage("BTCUSDT")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    result = apply_paper_tightening_gate(
        lineage, generated_at=now, recent_events=[], previous_position=None
    )
    risk = result["risk_decision"]
    gate = risk.get("paper_protective_behavior_gate", {})
    assert gate.get("reduce_only_protection_clear") is True
