from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.paper_trade_management.caps import PaperExposureCaps
from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig
from v2.backend.app.services.paper_trade_management.lifecycle import (
    PaperLifecycleConfig,
    reconcile_paper_lifecycle,
)
from v2.backend.app.services.paper_trade_management.market_price_evidence import (
    MARKET_PRICE_EVIDENCE_MISSING,
    read_market_price_evidence,
    verified_market_price_tuple,
    verify_market_price_evidence,
)

LOOKUP = "2026-07-21T10:00:30.000Z"


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads
        self.reads: list[str] = []

    def get(self, key: str) -> str | None:
        self.reads.append(key)
        value = self.payloads.get(key)
        return json.dumps(value) if value is not None else None


def _ticker(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "ticker_24hr": {
            "symbol": "BTCUSDT",
            "lastPrice": "102.0",
            "closeTime": "2026-07-21T10:00:29.000Z",
        },
        "fetched_utc": "2026-07-21T10:00:29.500Z",
        "source": "binance_public_websocket_cache_primary",
    }
    for key, value in overrides.items():
        if key.startswith("ticker__"):
            payload["ticker_24hr"][key.removeprefix("ticker__")] = value
        else:
            payload[key] = value
    return payload


def _feature(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_freshness_state": "CURRENT",
        "features": {"close_price": "102.0"},
        "candle_close_time": "2026-07-21T09:59:59.999Z",
        "feature_cutoff": "2026-07-21T09:59:59.999Z",
        "available_at": "2026-07-21T10:00:00.100Z",
        "generated_at": "2026-07-21T10:00:00.050Z",
        "candle_closed_confirmed": True,
        "latest_candle_temporally_valid": True,
    }
    payload.update(overrides)
    return payload


def _read(payloads: dict[str, Any]) -> dict[str, Any]:
    return read_market_price_evidence(
        FakeRedis(payloads),
        "BTCUSDT",
        timeframe="1m",
        clock=lambda: LOOKUP,
    )


def _paper_fill() -> dict[str, Any]:
    return {
        "fill_id": "fill-price-evidence",
        "ledger_row_id": "fill-price-evidence",
        "intent_id": "fill-price-evidence",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-07-21T10:00:00.000Z",
        "generated_utc": "2026-07-21T10:00:00.000Z",
        "signal_id": "sig-price-evidence",
        "prediction_id": "pred-price-evidence",
        "risk_decision_id": "risk-price-evidence",
        "orchestrator_decision_id": "orch-price-evidence",
        "decision_id": "orch-price-evidence",
        "market_state_id": "market-price-evidence",
        "feature_snapshot_id": "feature-price-evidence",
        "mtf_snapshot_id": "mtf-price-evidence",
        "feature_cutoff": "2026-07-21T09:59:59.999Z",
        "decision_time": "2026-07-21T10:00:00.000Z",
        "available_at": "2026-07-21T10:00:00.000Z",
        "selected_action": "long",
        "model_version": "unit-model",
        "checkpoint_id": "unit-checkpoint",
        "source_hashes": {"feature_vector_hash": "feature-hash"},
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "timeframe": "1m",
        "paper_fill_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "maintenance_margin_rate": 0.005,
    }


def test_valid_ticker_event_binds_key_symbol_timeframe_field_hash_and_clocks() -> None:
    evidence = _read({"v2:market:prices:BTCUSDT": _ticker()})

    assert evidence["evidence_status"] == "VALID"
    assert evidence["requested_redis_key"] == "v2:market:prices:BTCUSDT"
    assert evidence["requested_symbol"] == "BTCUSDT"
    assert evidence["requested_timeframe"] == "1m"
    assert evidence["selected_field"] == "ticker_24hr.lastPrice"
    assert len(evidence["source_hash_sha256"]) == 64
    assert (
        evidence["source_event_time"] <= evidence["available_at"] <= evidence["lookup_observed_at"]
    )
    assert verified_market_price_tuple(
        evidence,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    ) == (102.0, "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE", "2026-07-21T10:00:29.500Z")


def test_valid_final_closed_feature_candle_is_accepted_after_ticker_miss() -> None:
    evidence = _read({"v2:features:latest:BTCUSDT:1m": _feature()})

    assert evidence["evidence_status"] == "VALID"
    assert evidence["source_kind"] == "FINAL_CLOSED_CANDLE_FEATURE"
    assert evidence["candle_close_time"] == "2026-07-21T09:59:59.999Z"
    assert evidence["source_material"]["feature_cutoff"] == evidence["candle_close_time"]
    assert evidence["source_attempt_count"] == 2
    assert evidence["rejected_prior_sources"] == []


def test_lifecycle_mark_symbol_set_includes_existing_positions_without_new_fill() -> None:
    assert paper_loop._paper_lifecycle_mark_symbols(  # noqa: SLF001
        {
            "open_positions": [{"symbol": "ETHUSDT"}],
            "positions_by_symbol": {
                "SOLUSDT::HEDGE": {"symbol": "SOLUSDT"},
            },
        },
        [{"symbol": "BTCUSDT"}],
    ) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            _ticker(symbol="ETHUSDT", ticker__symbol="ETHUSDT"),
            "SOURCE_PAYLOAD_SYMBOL_BINDING_MISMATCH",
        ),
        (_ticker(timeframe="5m"), "SOURCE_PAYLOAD_TIMEFRAME_BINDING_MISMATCH"),
        (_ticker(ticker__closeTime=None), "SOURCE_EVENT_TIME_MISSING_OR_NOT_STRICT_UTC"),
        (
            _ticker(fetched_utc="2026-07-21T10:00:29"),
            "SOURCE_AVAILABLE_AT_MISSING_OR_NOT_STRICT_UTC",
        ),
        (
            _ticker(fetched_utc="2026-07-21T10:00:31.000Z"),
            "SOURCE_AVAILABLE_AT_AFTER_LOOKUP_OBSERVED_AT",
        ),
        (
            _ticker(
                ticker__closeTime="2026-07-21T10:00:29.900Z",
                fetched_utc="2026-07-21T10:00:29.100Z",
            ),
            "SOURCE_EVENT_TIME_AFTER_AVAILABLE_AT",
        ),
        (
            _ticker(ticker__closeTime="2026-07-21T09:58:00.000Z"),
            "SOURCE_EVENT_STALE_FOR_REQUESTED_TIMEFRAME",
        ),
    ],
)
def test_ticker_adversarial_bindings_and_clocks_fail_closed(
    payload: dict[str, Any],
    reason: str,
) -> None:
    evidence = _read({"v2:market:prices:BTCUSDT": payload})

    assert evidence["evidence_status"] == "REJECTED"
    assert reason in evidence["rejection_reasons"]
    assert verified_market_price_tuple(
        evidence,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    ) == (None, MARKET_PRICE_EVIDENCE_MISSING, None)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (_feature(symbol="ETHUSDT"), "SOURCE_PAYLOAD_SYMBOL_BINDING_MISMATCH"),
        (_feature(timeframe="5m"), "SOURCE_PAYLOAD_TIMEFRAME_BINDING_MISMATCH"),
        (_feature(candle_close_time=None), "SOURCE_EVENT_TIME_MISSING_OR_NOT_STRICT_UTC"),
        (
            _feature(available_at="2026-07-21T10:00:00"),
            "SOURCE_AVAILABLE_AT_MISSING_OR_NOT_STRICT_UTC",
        ),
        (
            _feature(available_at="2026-07-21T10:00:31.000Z"),
            "SOURCE_AVAILABLE_AT_AFTER_LOOKUP_OBSERVED_AT",
        ),
        (
            _feature(available_at="2026-07-21T09:59:59.000Z"),
            "SOURCE_EVENT_TIME_AFTER_AVAILABLE_AT",
        ),
        (_feature(candle_closed_confirmed=False), "FEATURE_CANDLE_NOT_CONFIRMED_FINAL"),
        (_feature(feature_freshness_state="STALE"), "FEATURE_FRESHNESS_NOT_CURRENT"),
        (
            _feature(features={"close_price": float("nan")}),
            "MARKET_PRICE_MISSING_OR_INVALID",
        ),
        (
            _feature(
                candle_close_time="2026-07-21T09:58:59.999Z",
                feature_cutoff="2026-07-21T09:58:59.999Z",
            ),
            "SOURCE_EVENT_STALE_FOR_REQUESTED_TIMEFRAME",
        ),
        (
            _feature(feature_cutoff="2026-07-21T09:59:58.999Z"),
            "FEATURE_CUTOFF_NOT_BOUND_TO_FINAL_CANDLE_CLOSE",
        ),
    ],
)
def test_feature_adversarial_bindings_finality_and_clocks_fail_closed(
    payload: dict[str, Any],
    reason: str,
) -> None:
    evidence = _read({"v2:features:latest:BTCUSDT:1m": payload})

    assert evidence["evidence_status"] == "REJECTED"
    assert reason in evidence["rejection_reasons"]


def test_tampered_evidence_hash_or_selected_value_fails_closed() -> None:
    evidence = _read({"v2:market:prices:BTCUSDT": _ticker()})
    tampered_price = copy.deepcopy(evidence)
    tampered_price["price"] = 999.0
    tampered_material = copy.deepcopy(evidence)
    tampered_material["source_material"]["payload_symbol"] = "ETHUSDT"
    tampered_lookup = copy.deepcopy(evidence)
    tampered_lookup["lookup_observed_at"] = "2026-07-21T10:00:29.750Z"

    price_result = verify_market_price_evidence(
        tampered_price,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )
    material_result = verify_market_price_evidence(
        tampered_material,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )
    lookup_result = verify_market_price_evidence(
        tampered_lookup,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )

    assert price_result["valid"] is False
    assert "SELECTED_PRICE_BINDING_MISMATCH" in price_result["reasons"]
    assert material_result["valid"] is False
    assert "SOURCE_HASH_MISMATCH" in material_result["reasons"]
    assert lookup_result["valid"] is False
    assert "MARKET_PRICE_EVIDENCE_HASH_MISMATCH" in lookup_result["reasons"]


def test_invalid_evidence_cannot_attach_entry_price_or_pass_prefill_evidence_gate() -> None:
    evidence = _read(
        {
            "v2:market:prices:BTCUSDT": _ticker(symbol="ETHUSDT"),
            "v2:features:latest:BTCUSDT:1m": _feature(candle_closed_confirmed=False),
        }
    )
    price, source, source_utc = verified_market_price_tuple(
        evidence,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )
    intent = {"symbol": "BTCUSDT"}

    paper_loop._attach_entry_price_provenance(  # noqa: SLF001
        intent,
        price,
        source,
        source_utc,
        market_price_evidence=evidence,
    )
    gate_reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(  # noqa: SLF001
        intent,
        require_fill_ledger=False,
    )

    assert intent["entry_price"] is None
    assert intent["fill_price"] is None
    assert intent["entry_price_provenance_present"] is False
    assert intent["entry_price_evidence_status"] == "REJECTED"
    assert MARKET_PRICE_EVIDENCE_MISSING in gate_reasons


def test_invalid_structured_mark_produces_no_close_outcome_or_trainer_row() -> None:
    evidence = _read({"v2:market:prices:BTCUSDT": _ticker()})
    evidence["source_material"]["payload_symbol"] = "ETHUSDT"
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_paper_fill()],
        mark_prices={
            "BTCUSDT": {
                "price": 102.0,
                "source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
                "market_price_evidence_required": True,
                "market_price_requested_timeframe": "1m",
                "market_price_evidence": evidence,
            }
        },
        generated_utc=LOOKUP,
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10_000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=100.0,
                stop_loss_bps=99_999.0,
            ),
        ),
    )
    trainer_rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=result["new_close_events"],
        outcome_labels=result["new_outcome_labels"],
    )

    assert len(result["open_positions"]) == 1
    assert result["new_close_events"] == []
    assert result["new_outcome_labels"] == []
    assert trainer_rows == []
    assert result["paper_exit_coordinator_status"]["evaluations"][0]["blocker"] == (
        "VERIFIED_MARKET_PRICE_EVIDENCE_REQUIRED"
    )


def test_valid_structured_mark_can_drive_same_sensitive_lifecycle_close() -> None:
    evidence = _read({"v2:market:prices:BTCUSDT": _ticker()})
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_paper_fill()],
        mark_prices={
            "BTCUSDT": {
                "price": 102.0,
                "source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE",
                "market_price_evidence_required": True,
                "market_price_requested_timeframe": "1m",
                "market_price_evidence": evidence,
            }
        },
        generated_utc=LOOKUP,
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10_000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                take_profit_bps=100.0,
                stop_loss_bps=99_999.0,
            ),
        ),
    )

    assert len(result["new_close_events"]) == 1
    assert len(result["new_outcome_labels"]) == 1
