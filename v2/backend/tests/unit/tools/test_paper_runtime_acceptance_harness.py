from __future__ import annotations

import json

from tools import paper_runtime_acceptance_harness as harness


class FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in values.items()
        }

    def get(self, key: str):
        return self.values.get(key)

    def scan_iter(self, _pattern: str, *, count: int):
        assert count == 8000
        return iter(())


def base_values() -> dict[str, object]:
    return {
        "v2:paper:account_epoch:current": {
            "paper_session_id": "paper-session-1",
            "paper_account_epoch": 1,
            "paper_only": True,
            "live_gate": "blocked_human_only",
            "routes_to_live": False,
            "places_real_order": False,
        },
        "v2:paper:session": {
            "paper_session_id": "paper-session-1",
            "paper_account_epoch": 1,
            "exchange_action_taken": False,
        },
        "v2:paper:epoch:1:positions": [
            {"position_id": "position-1", "accepted_fill_id": "fill-1"}
        ],
        "v2:paper:epoch:1:accepted_fills": [{"fill_id": "fill-1"}],
        "v2:paper:epoch:1:closed_trades": [],
        "v2:paper:epoch:1:reservations": [],
        "v2:paper:open_position_fill_proofs": {
            "proofs": [{"fill_id": "fill-1", "position_id": "position-1"}]
        },
        "v2:paper:open_position_fill_proofs:manifest": {
            "initialization_state": "INITIALIZED_WITH_PROOFS",
            "completed": True,
        },
        "v2:paper:accepted_fills:quarantine": [],
        "v2:portfolio:state": {
            "paper_session_id": "paper-session-1",
            "paper_account_epoch": 1,
            "wallet_balance": 3000.0,
            "equity": 3000.0,
            "reserved_margin_usd": 0.0,
        },
        "v2:paper:trade_management:status": {
            "generated_utc": "2026-07-28T19:00:00.000Z",
            "paper_margin_reservation_status": {
                "used_margin_usd": 100.0,
                "free_margin_usd": 2900.0,
                "margin_base_usd": 3000.0,
                "candidate_count": 1,
                "pre_lifecycle_snapshot_sha256": "a" * 64,
                "reservation_rows": [],
                "post_lifecycle_accounting_invariant_holds": True,
                "post_lifecycle_reconciled": True,
            },
        },
    }


def test_snapshot_uses_current_epoch_and_proves_accounting_contract() -> None:
    snapshot = harness.snapshot(FakeRedis(base_values()))

    assert snapshot["paper_session_id"] == "paper-session-1"
    assert snapshot["paper_account_epoch"] == 1
    assert snapshot["accepted_fills_count"] == 1
    assert snapshot["open_positions_count"] == 1
    assert snapshot["proof_backed_positions"] == 1
    assert snapshot["unproved_positions"] == 0
    assert snapshot["proof_store_initialized"] is True
    assert snapshot["proof_store_backfill_complete"] is True
    assert snapshot["reservation_snapshot_present"] is True
    assert snapshot["reservation_leak_count"] == 0
    assert snapshot["duplicate_fill_count"] == 0
    assert snapshot["duplicate_close_count"] == 0
    assert snapshot["wallet_equity_margin_conserved"] is True
    assert all(snapshot["safety"].values())


def test_snapshot_reports_duplicates_and_reservation_leaks() -> None:
    values = base_values()
    values["v2:paper:epoch:1:accepted_fills"] = [
        {"fill_id": "fill-1"},
        {"fill_id": "fill-1"},
    ]
    values["v2:paper:epoch:1:closed_trades"] = [
        {"close_id": "close-1"},
        {"close_id": "close-1"},
    ]
    values["v2:paper:epoch:1:reservations"] = [{"reservation_id": "leak-1"}]

    snapshot = harness.snapshot(FakeRedis(values))

    assert snapshot["duplicate_fill_count"] == 1
    assert snapshot["duplicate_close_count"] == 1
    assert snapshot["reservation_leak_count"] == 1


def test_cycle_observation_timeout_covers_long_production_cycles() -> None:
    assert harness._cycle_observation_timeout(3.0) == 900.0
    assert harness._cycle_observation_timeout(65.0) == 900.0
    assert harness._cycle_observation_timeout(180.0) == 1080.0


def test_observer_anchors_to_the_cycle_visible_at_invocation() -> None:
    redis_client = FakeRedis(base_values())

    assert harness._initial_cycle_id(redis_client) == "2026-07-28T19:00:00.000Z"
