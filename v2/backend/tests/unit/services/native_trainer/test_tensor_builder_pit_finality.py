from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    LEGACY_PROVIDER_FENCED_FEATURE_NAMES,
    V2UnifiedFeatureTensorBuilder,
)

DECISION_TIME = "2026-07-18T12:00:00Z"


def _fields(record):
    return dict(zip(record.feature_names, record.values, strict=True))


def _missing(record):
    return dict(zip(record.feature_names, record.missing_mask, strict=True))


def _stale(record):
    return dict(zip(record.feature_names, record.stale_mask, strict=True))


def _available(record):
    return dict(
        zip(record.feature_names, record.source_availability, strict=True)
    )


def test_future_confirmed_candle_is_masked_by_close_clock() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "ohlcv": {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "candle_closed_confirmed": True,
                "candle_close_time": "2026-07-18T12:01:00Z",
            }
        },
    )

    assert _missing(record)["close"] == 1
    assert _stale(record)["close"] == 1
    assert "OHLCV_CLOSE_TIME_AFTER_DECISION_TIME" in record.temporal_rejection_reasons


@pytest.mark.parametrize(
    ("candle", "expected_reason"),
    [
        (
            {
                "close": 100.0,
                "candle_close_time": "2026-07-18T11:59:00Z",
            },
            "OHLCV_FINALITY_NOT_CONFIRMED",
        ),
        (
            {"close": 100.0, "candle_closed_confirmed": True},
            "OHLCV_CLOSE_TIME_NOT_STRICT_UTC",
        ),
    ],
)
def test_unknown_candle_finality_cannot_be_enabled_by_environment(
    monkeypatch: pytest.MonkeyPatch,
    candle: dict[str, object],
    expected_reason: str,
) -> None:
    monkeypatch.setenv("PIPELINE_TRUST_ALLOW_UNKNOWN_KLINE_FINALITY", "true")

    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={"ohlcv": candle},
    )

    assert _missing(record)["close"] == 1
    assert expected_reason in record.temporal_rejection_reasons


def test_future_orderbook_is_masked_and_age_is_never_clamped_to_zero() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "orderbook": {
                "best_bid": 100.0,
                "best_ask": 100.1,
                "available_at": "2026-07-18T12:00:00.001Z",
                "update_age_ms": 0,
            }
        },
    )

    assert _missing(record)["ob_best_bid"] == 1
    assert _missing(record)["update_age_ms"] == 1
    assert _fields(record)["update_age_ms"] == 0.0
    assert "ORDERBOOK_AVAILABLE_AT_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )


def test_freshness_assertion_without_available_at_cannot_admit_orderbook() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "orderbook": {
                "best_bid": 100.0,
                "best_ask": 100.1,
                "freshness_state": "CURRENT",
            }
        },
    )

    assert _missing(record)["ob_best_bid"] == 1
    assert _stale(record)["ob_best_bid"] == 1
    assert "ORDERBOOK_AVAILABLE_AT_MISSING" in record.temporal_rejection_reasons
    assert "ORDERBOOK_AVAILABLE_AT_MISSING_FOR_FRESHNESS_FLAG" in (
        record.temporal_rejection_reasons
    )


def test_inverted_orderbook_clocks_fail_closed_with_explicit_reason() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "orderbook": {
                "best_bid": 100.0,
                "best_ask": 100.1,
                "event_time": "2026-07-18T11:59:59.900Z",
                "available_at": "2026-07-18T11:59:59.800Z",
            }
        },
    )

    assert _missing(record)["ob_best_bid"] == 1
    assert "ORDERBOOK_EVENT_TIME_AFTER_AVAILABLE_AT" in (
        record.temporal_rejection_reasons
    )


def test_future_feature_source_available_at_masks_its_features() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "features_latest": {
                "feature_snapshot_id": "same-snapshot",
                "available_at": "2026-07-18T12:00:00.001Z",
                "features": {"rsi_14": 55.0},
            }
        },
    )

    assert _missing(record)["rsi_14"] == 1
    assert "FEATURES_LATEST_AVAILABLE_AT_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )


@pytest.mark.parametrize(
    ("payload_name", "payload", "feature_name", "expected_reason"),
    [
        (
            "funding",
            {"funding_rate": 0.123456},
            "funding_rate",
            "FUNDING_AVAILABLE_AT_MISSING",
        ),
        (
            "features_latest",
            {"features": {"rsi_14": 55.0}},
            "rsi_14",
            "FEATURES_LATEST_AVAILABLE_AT_MISSING",
        ),
        (
            "microstructure",
            {"micro_price": 100.05},
            "micro_price",
            "MICROSTRUCTURE_AVAILABLE_AT_MISSING",
        ),
    ],
)
def test_populated_non_orderbook_source_without_available_at_is_masked(
    payload_name: str,
    payload: dict[str, object],
    feature_name: str,
    expected_reason: str,
) -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={payload_name: payload},
    )

    assert _missing(record)[feature_name] == 1
    assert _stale(record)[feature_name] == 1
    assert expected_reason in record.temporal_rejection_reasons


def test_non_orderbook_source_with_causal_available_at_is_admitted() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "funding": {
                "funding_rate": 0.123456,
                "event_time": "2026-07-18T11:59:58Z",
                "ingested_at": "2026-07-18T11:59:59Z",
                "available_at": "2026-07-18T11:59:59.500Z",
            }
        },
    )

    assert _fields(record)["funding_rate"] == pytest.approx(0.123456)
    assert _missing(record)["funding_rate"] == 0
    assert _stale(record)["funding_rate"] == 0
    assert record.temporal_rejection_reasons == ()


def test_exact_zero_from_primary_snapshot_is_not_replaced_by_fallbacks() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "features_latest": {
                "feature_snapshot_id": "zero-is-observed",
                "available_at": "2026-07-18T11:59:59Z",
                "features": {
                    "rsi_14": 0.0,
                    "bid_ask_spread_bps": 0.0,
                    "depth_imbalance": 0.0,
                },
                "rsi_14": 51.0,
            },
            "features_ta": {
                "available_at": "2026-07-18T11:59:59Z",
                "indicators": {"rsi_14": 61.0},
            },
            "orderbook": {
                "available_at": "2026-07-18T11:59:59Z",
                "best_bid": 100.0,
                "best_ask": 100.1,
                "best_bid_size": 9.0,
                "best_ask_size": 1.0,
            },
        },
    )

    fields = _fields(record)
    missing = _missing(record)
    assert fields["rsi_14"] == 0.0
    assert fields["bid_ask_spread_bps"] == 0.0
    assert fields["depth_imbalance"] == 0.0
    assert missing["rsi_14"] == 0
    assert missing["bid_ask_spread_bps"] == 0
    assert missing["depth_imbalance"] == 0


def test_paper_position_zero_unrealized_bps_is_not_replaced_or_fabricated() -> None:
    builder = V2UnifiedFeatureTensorBuilder()
    causal_position = {
        "symbol": "BTCUSDT",
        "unrealized_pnl_bps": 0.0,
        "unrealized_bps": 42.0,
        "available_at": "2026-07-18T11:59:59Z",
    }

    exact_zero = builder.build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={"paper_positions": [causal_position]},
    )
    missing_value = builder.build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "paper_positions": [
                {
                    "symbol": "BTCUSDT",
                    "available_at": "2026-07-18T11:59:59Z",
                }
            ]
        },
    )

    assert _fields(exact_zero)["paper_unrealized_bps"] == 0.0
    assert _missing(exact_zero)["paper_unrealized_bps"] == 0
    assert _fields(missing_value)["paper_unrealized_bps"] == 0.0
    assert _missing(missing_value)["paper_unrealized_bps"] == 1


def test_future_liquidity_zone_cannot_escape_through_sweep_risk_alias() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "liquidity_zones": {
                "liquidity_sweep_risk": 0.91,
                "sweep_risk_long_side": 0.87,
                "available_at": "2026-07-18T12:00:00.001Z",
            }
        },
    )

    assert _missing(record)["sweep_risk"] == 1
    assert _missing(record)["sweep_risk_long_side"] == 1
    assert _fields(record)["sweep_risk"] == 0.0
    assert "LIQUIDITY_ZONES_AVAILABLE_AT_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )


def test_causal_liquidity_zone_alias_is_admitted() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "liquidity_zones": {
                "liquidity_sweep_risk": 0.41,
                "sweep_risk_long_side": 0.37,
                "available_at": "2026-07-18T11:59:59Z",
            }
        },
    )

    assert _fields(record)["sweep_risk"] == pytest.approx(0.41)
    assert _fields(record)["sweep_risk_long_side"] == pytest.approx(0.37)
    assert _missing(record)["sweep_risk"] == 0
    assert _missing(record)["sweep_risk_long_side"] == 0


@pytest.mark.parametrize(
    ("available_at", "expected_reason"),
    [
        (None, "TRADE_TAPE_AVAILABLE_AT_MISSING"),
        (
            "2026-07-18T12:00:00.001Z",
            "TRADE_TAPE_AVAILABLE_AT_AFTER_DECISION_TIME",
        ),
    ],
)
def test_unclocked_or_future_trade_tape_is_masked(
    available_at: str | None,
    expected_reason: str,
) -> None:
    tape: dict[str, object] = {"trade_imbalance": 0.73}
    if available_at is not None:
        tape["available_at"] = available_at

    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={"trade_tape": tape},
    )

    assert _missing(record)["trade_imbalance"] == 1
    assert _stale(record)["trade_imbalance"] == 1
    assert expected_reason in record.temporal_rejection_reasons


def test_causal_trade_tape_is_admitted() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "trade_tape": {
                "trade_imbalance": 0.73,
                "event_time": "2026-07-18T11:59:58Z",
                "available_at": "2026-07-18T11:59:59Z",
            }
        },
    )

    assert _fields(record)["trade_imbalance"] == pytest.approx(0.73)
    assert _missing(record)["trade_imbalance"] == 0


def test_raw_provider_features_cannot_bypass_validated_context() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={"provider_features": {"rsi_14": 99.0}},
    )

    assert _missing(record)["rsi_14"] == 1
    assert _fields(record)["rsi_14"] == 0.0
    assert "PROVIDER_FEATURES_RAW_CONTEXT_REQUIRED" in (
        record.temporal_rejection_reasons
    )


def test_provider_features_in_causal_context_are_admitted() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "provider_feature_context": {
                "available_at": "2026-07-18T11:59:59Z",
                "provider_features": {"rsi_14": 57.0},
            }
        },
    )

    index = record.feature_names.index("rsi_14")
    assert record.values[index] == pytest.approx(57.0)
    assert record.missing_mask[index] == 0
    assert record.source_labels[index] == "provider_feature_bridge"


def test_legacy_provider_features_remain_typed_optional_missing_despite_claimed_contract(
) -> None:
    claimed_values = {
        name: float(index + 1)
        for index, name in enumerate(sorted(LEGACY_PROVIDER_FENCED_FEATURE_NAMES))
    }
    causal_contract = {
        "schema_version": "self_asserted_provider_contract_v1",
        "event_time": "2026-07-18T11:59:57Z",
        "ingested_at": "2026-07-18T11:59:58Z",
        "available_at": "2026-07-18T11:59:59Z",
        "feature_cutoff": "2026-07-18T11:59:57Z",
        "canonical_receipt_resolver_present": True,
        "postcommit_receipt_bound": True,
        "consumer_receipts_bound": True,
        "source_finality_contract_verified": True,
        "trainer_consumable": True,
    }
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "features_latest": {
                **causal_contract,
                "feature_snapshot_id": "self-asserted-provider-snapshot",
                "features": claimed_values,
            },
            "microstructure": {
                **causal_contract,
                "coinapi_wsds_tape_imbalance": 0.99,
            },
            "moralis_features": {
                **causal_contract,
                "features": claimed_values,
            },
            "smart_money_signals": {
                **causal_contract,
                "features": claimed_values,
            },
            "provider_feature_context": {
                **causal_contract,
                "provider_features": claimed_values,
            },
        },
    )

    values = _fields(record)
    missing = _missing(record)
    stale = _stale(record)
    available = _available(record)
    assert record.temporal_rejection_reasons == ()
    assert LEGACY_PROVIDER_FENCED_FEATURE_NAMES == {
        "coinapi_wsds_tape_imbalance",
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
        "moralis_onchain_risk_score",
        "moralis_smart_wallet_accumulation_score",
        "moralis_smart_wallet_distribution_score",
        "moralis_whale_net_flow_usd",
    }
    for name in LEGACY_PROVIDER_FENCED_FEATURE_NAMES:
        assert values[name] == 0.0
        assert missing[name] == 1
        assert stale[name] == 0
        assert available[name] == 0


def test_future_legacy_provider_clock_still_records_pit_rejection() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "microstructure": {
                "coinapi_wsds_tape_imbalance": 0.99,
                "event_time": "2026-07-18T12:00:00.001Z",
                "available_at": "2026-07-18T12:00:00.002Z",
                "source_finality_contract_verified": False,
            }
        },
    )

    assert _fields(record)["coinapi_wsds_tape_imbalance"] == 0.0
    assert _missing(record)["coinapi_wsds_tape_imbalance"] == 1
    assert _stale(record)["coinapi_wsds_tape_imbalance"] == 1
    assert "MICROSTRUCTURE_EVENT_TIME_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )
    assert "MICROSTRUCTURE_AVAILABLE_AT_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )


def test_future_nested_coinank_row_cannot_inherit_causal_wrapper_clock() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "coinank_open_interest": {
                "available_at": "2026-07-18T11:59:59Z",
                "data": {
                    "success": True,
                    "data": [
                        {
                            "coinValue": 1234.0,
                            "event_time": "2026-07-18T12:00:00.001Z",
                        }
                    ],
                },
            }
        },
    )

    assert _missing(record)["open_interest"] == 1
    assert _fields(record)["open_interest"] == 0.0
    assert "COINANK_OPEN_INTEREST_EVENT_TIME_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )


def test_causal_wrapper_conservatively_binds_unclocked_nested_coinank_row() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "coinank_open_interest": {
                "available_at": "2026-07-18T11:59:59Z",
                "data": {
                    "success": True,
                    "data": [{"coinValue": 1234.0}],
                },
            }
        },
    )

    index = record.feature_names.index("open_interest")
    assert record.values[index] == pytest.approx(1234.0)
    assert record.missing_mask[index] == 0
    assert record.source_labels[index] == "latest:coinank:open_interest"


def test_future_clock_in_row_source_masks_derived_aggregate() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "risk_decisions": [
                {
                    "action": "allow",
                    "decision_time": "2026-07-18T12:00:00.001Z",
                }
            ]
        },
    )

    assert _missing(record)["risk_recent_allow_rate"] == 1
    assert "RISK_DECISIONS_DECISION_TIME_AFTER_DECISION_TIME" in (
        record.temporal_rejection_reasons
    )


@pytest.mark.parametrize(
    ("payload_name", "feature_name", "expected_reason"),
    [
        (
            "paper_positions",
            "paper_position_present",
            "PAPER_POSITIONS_EMPTY_COLLECTION_RECEIPT_MISSING",
        ),
        (
            "risk_decisions",
            "risk_recent_allow_rate",
            "RISK_DECISIONS_EMPTY_COLLECTION_RECEIPT_MISSING",
        ),
        (
            "orchestrator_decisions",
            "orchestrator_recent_allow_rate",
            "ORCHESTRATOR_DECISIONS_EMPTY_COLLECTION_RECEIPT_MISSING",
        ),
    ],
)
def test_empty_row_source_without_availability_receipt_stays_missing(
    payload_name: str,
    feature_name: str,
    expected_reason: str,
) -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={payload_name: []},
    )

    assert _missing(record)[feature_name] == 1
    assert _stale(record)[feature_name] == 1
    assert expected_reason in record.temporal_rejection_reasons


def test_empty_nested_rows_cannot_inherit_only_wrapper_availability() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={
            "risk_decisions": {
                "available_at": "2026-07-18T11:59:59Z",
                "rows": [],
            }
        },
    )

    assert _missing(record)["risk_recent_allow_rate"] == 1
    assert "RISK_DECISIONS_EMPTY_COLLECTION_RECEIPT_MISSING" in (record.temporal_rejection_reasons)


def test_non_row_item_cannot_make_row_source_temporally_valid() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=DECISION_TIME,
        payloads={"paper_positions": [0]},
    )

    assert _missing(record)["paper_position_present"] == 1
    assert "PAPER_POSITIONS_ROW_TYPE_INVALID" in record.temporal_rejection_reasons


def test_tensor_identity_binds_equal_values_to_source_hash_lineage() -> None:
    def build(source_hash: str):
        return V2UnifiedFeatureTensorBuilder().build(
            symbol="BTCUSDT",
            timeframe="1m",
            decision_time=DECISION_TIME,
            payloads={
                "features_latest": {
                    "feature_snapshot_id": "same-snapshot",
                    "available_at": "2026-07-18T11:59:59Z",
                    "decision_time": DECISION_TIME,
                    "source_hashes": {"orderbook": source_hash},
                    "features": {"rsi_14": 55.0},
                }
            },
        )

    first = build("a" * 64)
    second = build("b" * 64)

    assert first.values == second.values
    assert first.missing_mask == second.missing_mask
    assert first.source_labels == second.source_labels
    assert first.source_lineage_hash != second.source_lineage_hash
    assert first.tensor_id != second.tensor_id


def test_naive_decision_clock_is_rejected_instead_of_assigned_utc() -> None:
    with pytest.raises(ValueError, match="argument.decision_time_not_strict_utc"):
        V2UnifiedFeatureTensorBuilder().build(
            symbol="BTCUSDT",
            timeframe="1m",
            decision_time="2026-07-18T12:00:00",
            payloads={},
        )
