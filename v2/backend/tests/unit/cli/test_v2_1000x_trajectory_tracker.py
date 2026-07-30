"""Session-anchored 1000x trajectory tracker (post-rotation repair).

Covers the 2026-07-29 repair: day-0 anchors on the PaperAccountEpochV1
pointer (hash-suffixed session ids carry no timestamp), accounting is
scoped to the current session (archived closed trades never blend into the
live face), and the per-outcome terminal-equity projection stamped by the
outcome pipeline is mirrored verbatim, never recomputed.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from v2.backend.app.cli import v2_1000x_trajectory_tracker as tracker
from v2.backend.app.services.paper_session.epoch import (
    EPOCH_POINTER_KEY,
    LEGACY_SESSION_KEY,
    PORTFOLIO_STATE_KEY,
)


class _FakeRedis:
    def __init__(self, store: dict[str, Any]):
        self._store = {key: json.dumps(value) for key, value in store.items()}
        self.written: dict[str, str] = {}

    @classmethod
    def from_url(cls, *_args: Any, **_kwargs: Any) -> "_FakeRedis":
        raise AssertionError("test must inject the instance explicitly")

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.written[key] = value


CURRENT_SESSION = "paper_session_140989e198032b94"
ARCHIVED_SESSION = "paper_3000_final_pre_live_20260713T190904Z"
STARTED_AT = "2026-07-28T19:23:37.482407Z"


def _base_store() -> dict[str, Any]:
    return {
        EPOCH_POINTER_KEY: {
            "schema_version": "PaperAccountEpochV1",
            "paper_session_id": CURRENT_SESSION,
            "paper_account_epoch": 1,
            "started_at": STARTED_AT,
            "starting_equity_usd": 3000.0,
        },
        "v2:paper:ledger": {
            "paper_session_id": ARCHIVED_SESSION,
            "starting_equity_usd": 2000.0,
        },
        "v2:paper:positions": [],
        "v2:paper:closed_trades": [
            {
                "paper_session_id": ARCHIVED_SESSION,
                "realized_net_pnl_usd": -1500.0,
                "exit_price_utc": "2026-07-20T00:00:00Z",
                "terminal_equity_after_completed_outcome": {
                    "schema_version": "terminal_paper_equity_after_outcome_v1",
                    "terminal_target_probability": 0.5,
                },
            },
            {
                "paper_session_id": CURRENT_SESSION,
                "trade_id": "t_current_1",
                "realized_net_pnl_usd": 25.0,
                "exit_price_utc": "2026-07-29T12:00:00Z",
                "terminal_equity_after_completed_outcome": {
                    "schema_version": "terminal_paper_equity_after_outcome_v1",
                    "terminal_target_probability": 0.001,
                },
                "terminal_target_probability": 0.001,
                "terminal_equity_distribution_usd": {
                    "p10": 900.0,
                    "p50": 3100.0,
                    "p90": 9000.0,
                },
            },
        ],
    }


def _run(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> dict[str, Any]:
    fake = _FakeRedis(store)
    monkeypatch.setattr(
        tracker.redis,
        "Redis",
        type("R", (), {"from_url": staticmethod(lambda *a, **k: fake)}),
    )
    payload = tracker.run_once()
    assert tracker.OUT_KEY in fake.written
    assert json.loads(fake.written[tracker.OUT_KEY]) == json.loads(
        json.dumps(payload, sort_keys=True)
    )
    return payload


def test_post_rotation_hash_session_id_anchors_on_epoch_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run(monkeypatch, _base_store())
    assert payload["paper_session_id"] == CURRENT_SESSION
    assert payload["paper_account_epoch"] == 1
    assert payload["session_started_utc"] == "2026-07-28T19:23:37Z"
    assert payload["days_elapsed"] is not None and payload["days_elapsed"] > 0
    assert payload["remaining_days_to_target"] is not None
    assert payload["session_anchor_source"] == f"redis:{EPOCH_POINTER_KEY}"


def test_archived_session_pnl_never_blends_into_current_equity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run(monkeypatch, _base_store())
    # Epoch pointer starting equity (3000) wins over stale ledger (2000);
    # only the +25 current-session close counts, never the archived -1500.
    assert payload["starting_equity_usd"] == 3000.0
    assert payload["equity_usd"] == pytest.approx(3025.0)
    assert payload["realized_pnl_usd"] == pytest.approx(25.0)
    assert payload["session_scope"] == "current_session"
    assert payload["closed_trade_count"] == 1
    assert payload["historical_closed_trade_count"] == 2
    assert payload["historical_rows_excluded_from_current_view"] == 1
    assert payload["target_equity_usd"] == pytest.approx(3_000_000.0)


def test_session_matched_portfolio_state_is_preferred_equity_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _base_store()
    store[PORTFOLIO_STATE_KEY] = {
        "paper_session_id": CURRENT_SESSION,
        "equity_usd": 3010.5,
    }
    payload = _run(monkeypatch, store)
    assert payload["equity_usd"] == pytest.approx(3010.5)
    assert payload["equity_source"] == f"redis:{PORTFOLIO_STATE_KEY}"
    # Foreign-session portfolio state must NOT be trusted.
    store[PORTFOLIO_STATE_KEY] = {
        "paper_session_id": ARCHIVED_SESSION,
        "equity_usd": 999999.0,
    }
    payload = _run(monkeypatch, store)
    assert payload["equity_usd"] == pytest.approx(3025.0)
    assert payload["equity_source"] == "session_scoped_recompute"


def test_terminal_projection_mirrors_newest_current_session_close_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run(monkeypatch, _base_store())
    latest = payload["latest_outcome_terminal_projection"]
    assert latest is not None
    assert latest["close_trade_id"] == "t_current_1"
    # Verbatim mirror of the outcome-pipeline record — the archived session's
    # projection (p=0.5) must never leak into the current session's view.
    assert (
        latest["terminal_equity_after_completed_outcome"][
            "terminal_target_probability"
        ]
        == 0.001
    )
    assert latest["terminal_equity_distribution_usd"]["p50"] == 3100.0
    assert payload["target_guaranteed"] is False
    assert payload["terminal_projection_note"] is None


def test_no_terminal_projection_yet_is_reported_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _base_store()
    store["v2:paper:closed_trades"] = []
    payload = _run(monkeypatch, store)
    assert payload["latest_outcome_terminal_projection"] is None
    assert payload["terminal_projection_note"] == (
        "NO_CURRENT_SESSION_CLOSE_CARRIES_TERMINAL_PROJECTION_YET"
    )
    assert payload["equity_usd"] == pytest.approx(3000.0)


def test_legacy_pre_rotation_environment_still_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _base_store()
    del store[EPOCH_POINTER_KEY]
    store[LEGACY_SESSION_KEY] = {
        "paper_session_id": ARCHIVED_SESSION,
        "initial_capital": 2000.0,
        "started_at": "2026-07-13T19:09:04Z",
    }
    payload = _run(monkeypatch, store)
    assert payload["paper_session_id"] == ARCHIVED_SESSION
    assert payload["session_started_utc"] == "2026-07-13T19:09:04Z"
    assert payload["starting_equity_usd"] == 2000.0
    # The archived-session row is the CURRENT session here.
    assert payload["closed_trade_count"] == 1
    assert payload["realized_pnl_usd"] == pytest.approx(-1500.0)


def test_paper_only_flags_and_no_guarantee_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _run(monkeypatch, _base_store())
    assert payload["paper_only"] is True
    assert payload["places_real_order"] is False
    assert payload["routes_to_live"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["target_guaranteed"] is False
    assert "research_objective_not_a_promise" in payload["objective"]
