import json

from v2.backend.app.services.paper_trade_management.policy_funding_repair import (
    V2_PAPER_CLOSED_TRADES_KEY,
    V2_PAPER_LEDGER_KEY,
    V2_PAPER_OUTCOME_LABELS_KEY,
    build_policy_funding_repair_report,
    repair_policy_funding_rows,
)


class FakeRedis:
    def __init__(self, store: dict[str, object]):
        self.store = {key: json.dumps(value) for key, value in store.items()}
        self.set_calls: list[tuple[str, object, int | None]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value
        self.set_calls.append((key, json.loads(value), ex))
        return True


def _accepted(**overrides):
    row = {
        "fill_id": "fill-1",
        "intent_id": "fill-1",
        "signal_id": "fill-1",
        "prediction_id": "pred-1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "short",
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "generated_utc": "2026-06-20T00:00:05Z",
        "fill_price_utc": "2026-06-20T00:00:05Z",
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "policy_activated_at": "2026-06-20T00:00:05Z",
        "expected_funding_bps": 8.0,
        "funding_interval_seconds": 28800.0,
    }
    row.update(overrides)
    return row


def _closed(**overrides):
    row = {
        "close_id": "close-1",
        "outcome_label_id": "outcome-1",
        "trainer_feedback_id": "feedback-1",
        "position_id": "position-1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "short",
        "paper_only": True,
        "places_real_order": False,
        "paper_exit_policy_version": "P0_DIRECTIONAL_EXIT_POLICY_V1",
        "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
        "source_fill_ids": ["fill-1"],
        "entry_signal_id": "fill-1",
        "entry_prediction_id": "pred-1",
        "entry_price": 100.0,
        "closed_quantity": 10.0,
        "exit_price": 99.0,
        "exit_time": "2026-06-20T04:00:05Z",
        "hold_time_seconds": 14400.0,
        "realized_pnl_usd": 10.0,
        "realized_pnl_usdt": 10.0,
        "realized_pnl": 10.0,
        "winner": True,
        "policy_activated_at": None,
        "funding_pnl_usd": None,
        "funding_pnl_source": None,
    }
    row.update(overrides)
    return row


def test_repairs_policy_activation_and_funding_from_safe_accepted_fill():
    rows, report, repaired_by_token = repair_policy_funding_rows(
        [_closed()],
        accepted_rows=[_accepted()],
        generated_at="2026-06-21T00:00:00Z",
    )

    repaired = rows[0]
    assert report["status_counts"] == {"repaired": 1}
    assert repaired["policy_activated_at"] == "2026-06-20T00:00:05Z"
    assert repaired["policy_activated_at_source"] == (
        "PAPER_POLICY_FUNDING_REPAIR:EARLIEST_SAFE_ACCEPTED_FILL_TIME"
    )
    assert repaired["funding_pnl_accounting_version"] == "PAPER_FUNDING_ACCRUAL_V1"
    assert repaired["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert repaired["funding_pnl_source"] == "EXPECTED_FUNDING_BPS"
    assert repaired["funding_bps"] == 8.0
    assert repaired["funding_rate"] == 0.0008
    assert round(repaired["funding_pnl_usd"], 8) == 0.4
    assert round(repaired["realized_pnl_usd"], 8) == 10.4
    assert repaired["paper_policy_funding_repair_realized_pnl_delta_usd"] == repaired["funding_pnl_usd"]
    assert "close-1" in repaired_by_token


def test_missing_funding_rate_is_left_unaccounted_but_timestamp_can_be_repaired():
    rows, report, _repaired_by_token = repair_policy_funding_rows(
        [_closed(source_fill_ids=["missing-fill"], entry_signal_id="missing-fill")],
        accepted_rows=[],
        generated_at="2026-06-21T00:00:00Z",
    )

    repaired = rows[0]
    assert report["status_counts"] == {"partially_repaired": 1}
    assert report["missing_reason_counts"] == {"MISSING_FUNDING_RATE_OR_BPS": 1}
    assert repaired["policy_activated_at"] == "2026-06-20T00:00:05Z"
    assert repaired["policy_activated_at_source"] == (
        "PAPER_POLICY_FUNDING_REPAIR:EXIT_TIME_MINUS_HOLD_TIME_SECONDS"
    )
    assert repaired["funding_pnl_usd"] is None
    assert repaired["funding_pnl_source"] is None
    assert repaired["paper_policy_funding_repair_status"] == (
        "PARTIAL_POLICY_ACTIVATION_REPAIRED_FUNDING_UNREPAIRABLE"
    )
    assert repaired["paper_policy_funding_unrepairable_reasons"] == ["MISSING_FUNDING_RATE_OR_BPS"]


def test_allocation_policy_timestamp_is_persisted_to_top_level_trade_row():
    row = _closed(
        policy_activated_at=None,
        funding_rate=0.0,
        expected_funding_bps=0.0,
        adaptive_allocation={
            "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
            "policy_activated_at": "2026-06-20T00:00:05Z",
            "model_inputs": {
                "funding_rate": 0.0,
                "expected_funding_bps": 0.0,
                "funding_interval_seconds": 28800.0,
            },
        },
    )

    rows, report, _repaired_by_token = repair_policy_funding_rows(
        [row],
        accepted_rows=[],
        generated_at="2026-06-21T00:00:00Z",
    )

    assert report["status_counts"] == {"repaired": 1}
    assert rows[0]["policy_activated_at"] == "2026-06-20T00:00:05Z"
    assert "policy_activated_at" in rows[0]["paper_policy_funding_repaired_fields"]
    assert rows[0]["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"


def test_report_write_updates_only_v2_paper_ledger_closed_and_outcome_keys():
    closed = _closed()
    outcome = dict(closed)
    outcome["close_id"] = None
    redis = FakeRedis(
        {
            V2_PAPER_LEDGER_KEY: {
                "accepted": [_accepted()],
                "closed_trades": [closed],
                "outcome_labels": [outcome],
            },
            V2_PAPER_CLOSED_TRADES_KEY: [closed],
            V2_PAPER_OUTCOME_LABELS_KEY: [outcome],
        }
    )

    report = build_policy_funding_repair_report(
        redis,
        write=True,
        generated_at="2026-06-21T00:00:00Z",
    )

    assert report["writes_redis"] is True
    assert report["places_real_order"] is False
    assert report["keys_written"] == [
        V2_PAPER_CLOSED_TRADES_KEY,
        V2_PAPER_OUTCOME_LABELS_KEY,
        V2_PAPER_LEDGER_KEY,
    ]
    assert [key for key, _value, _ex in redis.set_calls] == report["keys_written"]
    assert report["ledger_rows_updated"] == {"closed_trades": 1, "outcome_labels": 1}


def test_report_repairs_from_richer_ledger_context_when_closed_trade_key_is_sparse():
    sparse_closed = _closed(policy_activated_at=None)
    ledger_closed = _closed(
        policy_activated_at=None,
        adaptive_allocation={
            "adaptive_capital_policy_version": "ADAPTIVE_CAPITAL_ALLOCATOR_V1",
            "policy_activated_at": "2026-06-20T00:00:05Z",
            "model_inputs": {
                "funding_rate": 0.0,
                "expected_funding_bps": 0.0,
                "funding_interval_seconds": 28800.0,
            },
        },
    )
    redis = FakeRedis(
        {
            V2_PAPER_LEDGER_KEY: {
                "accepted": [
                    _accepted(
                        fill_id="fill-1",
                        intent_id="fill-1",
                        signal_id="fill-1",
                        prediction_id="conflicting-prediction",
                        expected_funding_bps=2.5,
                        funding_rate=0.00025,
                    ),
                    _accepted(
                        fill_id="pred-1",
                        intent_id="pred-1",
                        signal_id="pred-1",
                        prediction_id="pred-1",
                        expected_funding_bps=0.0,
                        funding_rate=0.0,
                    ),
                ],
                "closed_trades": [ledger_closed],
            },
            V2_PAPER_CLOSED_TRADES_KEY: [sparse_closed],
        }
    )

    report = build_policy_funding_repair_report(
        redis,
        write=True,
        generated_at="2026-06-21T00:00:00Z",
    )

    repaired_rows = json.loads(redis.get(V2_PAPER_CLOSED_TRADES_KEY))
    repaired = repaired_rows[0]
    assert report["closed_trade_repair"]["status_counts"] == {"repaired": 1}
    assert repaired["policy_activated_at"] == "2026-06-20T00:00:05Z"
    assert repaired["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert repaired["funding_pnl_source"] == "FUNDING_RATE"
    assert repaired["funding_rate"] == 0.0
    assert repaired["funding_bps"] == 0.0
    assert repaired["funding_pnl_usd"] == 0.0
