from __future__ import annotations

import json

import pytest

from tools import first_paper_lifecycle_acceptance as acceptance


class FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = {key: json.dumps(value) for key, value in values.items()}

    def get(self, key: str):
        return self.values.get(key)


def _values() -> dict[str, object]:
    session = "paper-session-1"
    return {
        acceptance.POINTER_KEY: {
            "schema_version": "PaperAccountEpochV1",
            "paper_session_id": session,
            "paper_account_epoch": 1,
            "starting_equity_usd": 3000.0,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
        },
        acceptance.LEGACY_SESSION_KEY: {"exchange_action_taken": False},
        acceptance.PAPER_STATUS_KEY: {
            "paper_session_id": session,
            "paper_account_epoch": 1,
            "cycle_state": "COMPLETED_CYCLE",
            "generated_utc": "2026-07-28T20:00:00.000Z",
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_action_taken": False,
        },
        acceptance.PROOF_MANIFEST_KEY: {
            "completed": True,
            "initialization_state": "EMPTY_INITIALIZED_PROOF_SET",
            "proof_count": 0,
        },
        acceptance.PROOFS_KEY: [],
        "v2:paper:epoch:1:positions": [],
        "v2:paper:epoch:1:accepted_fills": [],
        "v2:paper:epoch:1:closed_trades": [],
        "v2:paper:epoch:1:reservations": [],
        acceptance.PORTFOLIO_KEY: {
            "paper_session_id": session,
            "paper_account_epoch": 1,
            "wallet_balance_usd": 3000.0,
            "equity_usd": 3000.0,
            "free_margin_usd": 3000.0,
            "used_margin_usd": 0.0,
            "reserved_margin_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
        },
    }


def test_safe_context_is_current_epoch_and_paper_only() -> None:
    context = acceptance._safe_context(FakeRedis(_values()))

    assert context["session_id"] == "paper-session-1"
    assert context["epoch"] == 1
    assert context["positions"] == []
    assert context["fills"] == []
    assert all(context["safety"].values())


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("paper_only", False),
        ("live_gate", "open"),
        ("routes_to_live", True),
        ("places_real_order", True),
    ],
)
def test_safe_context_rejects_unsafe_epoch_authority(field: str, unsafe: object) -> None:
    values = _values()
    values[acceptance.POINTER_KEY][field] = unsafe

    with pytest.raises(acceptance.AcceptanceBoundary, match="paper_safety_boundary"):
        acceptance._safe_context(FakeRedis(values))


def test_reconstruction_requires_exact_identity_and_zero_duplicates(monkeypatch) -> None:
    context = acceptance._safe_context(FakeRedis(_values()))
    position = {
        "position_id": "position-1",
        "position_generation_id": "generation-1",
        "prediction_id": "prediction-1",
        "entry_fill_id": "fill-1",
        "source_fill_ids": ["fill-1"],
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "net_quantity": 0.001,
        "avg_entry_price": 100000.0,
        "gross_notional_usd": 100.0,
        "effective_leverage": 1.0,
        "allocated_margin_usd": 100.0,
    }
    fill = {
        "fill_id": "fill-1",
        "paper_session_id": "paper-session-1",
        "paper_account_epoch": 1,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    proof = {"position_id": "position-1", "fill_id": "fill-1"}
    context.update({"positions": [position], "fills": [fill], "proofs": [proof]})
    monkeypatch.setattr(acceptance.paper_loop, "_paper_open_position_fill_proof_reasons", lambda _row: [])
    monkeypatch.setattr(acceptance.paper_loop, "_paper_position_proof_binding_reasons", lambda _p, _r: [])
    frozen = {
        "position": acceptance._position_projection(position),
        "position_sha256": acceptance._sha256(acceptance._position_projection(position)),
        "fill_sha256": acceptance._sha256(fill),
        "proof_sha256": acceptance._sha256(proof),
        "accepted_fills_sha256": acceptance._sha256([fill]),
        "proofs_sha256": acceptance._sha256([proof]),
        "accounting": acceptance._accounting_projection(context),
    }

    checks = acceptance._reconstruction_checks(frozen, context)

    assert checks["restart_reconstruction_match"] is True
    assert checks["duplicate_fill_count"] == 0
    assert checks["duplicate_close_count"] == 0
    assert checks["reservation_leak_count"] == 0
