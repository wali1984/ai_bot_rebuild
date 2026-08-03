from __future__ import annotations

import json

import pytest

from v2.backend.app.cli import v2_portfolio_cascade_guard_loop as guard


class FakeRedis:
    def __init__(self, values: dict[str, object]):
        self.values = dict(values)
        self.writes: list[tuple[str, str, int | None]] = []

    def get(self, key: str):
        value = self.values.get(key)
        return json.dumps(value) if value is not None else None

    def set(self, key: str, value: str, ex: int | None = None):
        self.writes.append((key, value, ex))
        return True


def _position() -> dict[str, object]:
    return {
        "symbol": "MANAUSDT",
        "side": "long",
        "net_quantity": 1000.0,
        "avg_entry_price": 0.07,
        "mark_price": 0.072,
        "effective_leverage": 2.0,
        "unrealized_pnl": 2.0,
        "unrealized_pnl_bps": 285.0,
    }


def _ledger(
    *,
    maintenance_valid: bool = True,
    margin_base: object = 3000.0,
    maintenance_rate: object = 0.005,
) -> dict[str, object]:
    return {
        "paper_account_margin_status": {
            "status": "PASS",
            "accounting_complete": True,
            "margin_base_usd": margin_base,
            "used_margin_usd": 35.0,
            "free_margin_usd": 2965.0,
            "position_margin_rows": [
                {
                    "row_id": "margin-row-mana",
                    "symbol": "MANAUSDT",
                    "valid": True,
                    "maintenance_margin_evidence_valid": maintenance_valid,
                    "canonical_notional_usd": 70.0,
                    "effective_leverage": 2.0,
                    "maintenance_margin_rate": maintenance_rate,
                    "maintenance_margin_rate_source": (
                        "ALLOCATION_MODEL_INPUT_MAINTENANCE_MARGIN_RATE"
                    ),
                }
            ],
        }
    }


def test_run_once_joins_canonical_margin_and_leverage_evidence() -> None:
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [_position()],
            "v2:paper:ledger": _ledger(),
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["open_position_count"] == 1
    assert payload["portfolio_position_count_computed"] == 1
    assert payload["portfolio_level_computed"] is True
    assert payload["portfolio_risk_result_authoritative"] is True
    assert payload["portfolio_position_count_expected"] == 1
    assert payload["portfolio_margin_evidence"]["status"] == "PASS"
    assert payload["portfolio_margin_evidence"]["joined_position_count"] == 1
    assert payload["maintenance_margin_evidence_complete"] is True
    assert payload["leverage_evidence_complete"] is True
    assert payload["portfolio_position_count_matches"] is True
    assert payload["portfolio_risk_block_reasons"] == []
    assert payload["worst_case_liquidation_breached"] is False
    assert payload["places_real_order"] is False
    assert len(redis_client.writes) == 1


@pytest.mark.parametrize(
    ("field", "value", "expected_drop_reason"),
    [
        ("net_quantity", "bad", "POSITION_QUANTITY_INVALID"),
        ("net_quantity", None, "POSITION_QUANTITY_MISSING"),
        ("mark_price", 0.0, "POSITION_MARK_NON_POSITIVE"),
        ("mark_price", None, "POSITION_MARK_MISSING"),
    ],
)
def test_run_once_dropped_open_position_blocks_breach_conclusion(
    field: str,
    value: object,
    expected_drop_reason: str,
) -> None:
    position = _position()
    position[field] = value
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [position],
            "v2:paper:ledger": _ledger(),
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["portfolio_position_count_expected"] == 1
    assert payload["portfolio_position_count_computed"] == 0
    assert payload["portfolio_position_count_matches"] is False
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["portfolio_level_computed"] is False
    assert payload["worst_case_liquidation_breached"] is None
    assert "POSITION_ROWS_DROPPED" in payload["portfolio_risk_block_reasons"]
    assert "POSITION_COUNT_MISMATCH" in payload["portfolio_risk_block_reasons"]
    stored = json.loads(redis_client.writes[0][1])
    assert stored["worst_case_liquidation_breached"] is None
    assert expected_drop_reason in str(stored)


def test_run_once_unrecognized_side_blocks_breach_conclusion() -> None:
    position = _position()
    position["side"] = "sideways"
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [position],
            "v2:paper:ledger": _ledger(),
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["portfolio_position_count_computed"] == 1
    assert payload["portfolio_position_count_matches"] is True
    assert payload["position_direction_evidence_complete"] is False
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["worst_case_liquidation_breached"] is None
    assert (
        "POSITION_DIRECTION_EVIDENCE_UNRECOGNIZED"
        in payload["portfolio_risk_block_reasons"]
    )


@pytest.mark.parametrize("margin_base", ["bad", True, float("nan")])
def test_run_once_invalid_account_input_preserves_unknown_conclusion(
    margin_base: object,
) -> None:
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [_position()],
            "v2:paper:ledger": _ledger(margin_base=margin_base),
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["portfolio_margin_evidence"]["status"] == "BLOCKED"
    assert "PAPER_MARGIN_BASE_INVALID" in payload["portfolio_risk_block_reasons"]
    assert payload["portfolio_position_count_computed"] is None
    assert payload["portfolio_position_count_matches"] is None
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["worst_case_liquidation_breached"] is None


@pytest.mark.parametrize(
    "ledger",
    [
        _ledger(maintenance_valid=False),
        _ledger(maintenance_rate=None),
    ],
)
def test_run_once_incomplete_maintenance_evidence_preserves_unknown_conclusion(
    ledger: dict[str, object],
) -> None:
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [_position()],
            "v2:paper:ledger": ledger,
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["portfolio_margin_evidence"]["status"] == "BLOCKED"
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["portfolio_risk_computation_blocked"] is True
    assert payload["worst_case_liquidation_breached"] is None


def test_run_once_non_mapping_open_row_preserves_expected_count_and_blocks() -> None:
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [_position(), "malformed-row"],
            "v2:paper:ledger": _ledger(),
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["open_position_count"] == 2
    assert payload["portfolio_position_count_expected"] == 2
    assert payload["portfolio_position_count_mappable"] == 1
    assert payload["portfolio_position_count_computed"] is None
    assert payload["portfolio_margin_evidence"]["joined_position_count"] == 1
    assert "POSITION_ROW_NOT_MAPPING:1" in payload["portfolio_risk_block_reasons"]
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["worst_case_liquidation_breached"] is None
    assert len(redis_client.writes) == 1


def test_run_once_no_open_positions_preserves_not_applicable_unknown() -> None:
    redis_client = FakeRedis({"v2:paper:positions": []})

    payload = guard.run_once(redis_client)

    assert payload["open_position_count"] == 0
    assert payload["portfolio_position_count_computed"] is None
    assert payload["portfolio_position_count_matches"] is None
    assert payload["portfolio_risk_status"] == "NOT_APPLICABLE_NO_OPEN_POSITIONS"
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["portfolio_risk_computation_blocked"] is False
    assert payload["portfolio_risk_block_reasons"] == []
    assert payload["worst_case_liquidation_breached"] is None


def test_missing_margin_evidence_cannot_claim_portfolio_computation() -> None:
    redis_client = FakeRedis(
        {
            "v2:paper:positions": [_position()],
            "v2:paper:ledger": _ledger(maintenance_valid=False),
        }
    )

    payload = guard.run_once(redis_client)

    assert payload["open_position_count"] == 1
    assert payload["portfolio_position_count_computed"] is None
    assert payload["portfolio_level_computed"] is False
    assert payload["portfolio_margin_evidence"]["status"] == "BLOCKED"
    assert (
        "MAINTENANCE_MARGIN_EVIDENCE_INVALID:MANAUSDT"
        in payload["portfolio_margin_evidence"]["rejection_reasons"]
    )
    assert payload["worst_case_liquidation_breached"] is None
    assert payload["portfolio_risk_result_authoritative"] is False
    assert payload["portfolio_risk_computation_blocked"] is True
    assert payload["places_real_order"] is False
