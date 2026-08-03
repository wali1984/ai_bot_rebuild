from __future__ import annotations

import json
import math

import app.services.altdata.coinank_hot_series as hot_series
import pytest
from app.services.altdata.coinank_hot_series import (
    MAX_HOT_SERIES_ENCODED_BYTES,
    MAX_HOT_SERIES_INPUT_MAPPING_FIELDS,
    MAX_HOT_SERIES_JSON_STRING_BYTES,
    MAX_HOT_SERIES_ROWS,
    MAX_HOT_SERIES_SOURCE_BYTES,
    CoinAnkHotSeriesValidationError,
    compact_coinank_hot_series,
    compact_coinank_hot_series_record,
    decode_coinank_hot_series_json,
)


def _record(index: int, *, pad_size: int = 0, raw_size: int = 1_000) -> dict[str, object]:
    return {
        "ts_epoch_ms": 1_800_000_000_000 + index,
        "source_ts_ms": 1_800_000_000_000 + index,
        "endpoint": "orderFlow_lists",
        "family": "advanced",
        "baseCoin": "BTCUSDT",
        "exchange": "Binance",
        "interval": "1h",
        "coinank_metric": float(index),
        "coinank_pad": "x" * pad_size,
        "raw_data": {"large": "x" * raw_size},
        "request_parameters": {"symbol": "BTC"},
    }


def test_record_projection_is_scalar_negative_authority_and_never_zero_fills() -> None:
    record = _record(1, raw_size=1_000_000)
    hostile_true_fields = (
        "publication_authority",
        "trainer_authority",
        "prediction_authority",
        "risk_authority",
        "orchestrator_authority",
        "allocator_authority",
        "paper_authority",
        "live_authority",
        "live_execution_authority",
        "actual_consumption",
        "trainer_consumption",
        "provider_tensor_consumption",
        "trainer_admission_granted",
        "consumer_receipts_bound",
        "publication_committed",
        "valid_for_trainer",
        "valid_for_live",
    )
    record.update({field: True for field in hostile_true_fields})
    forged_aliases = ("is_authoritative", "zero-fill-applied", "consumption granted")
    record.update({field: True for field in forged_aliases})
    record["admitted_feature_count"] = 99
    record["available_at"] = "2099-01-01T00:00:00Z"
    record["zero_filled_field_count"] = 42
    record["no_zero_fill_for_unknown_fields"] = False

    compact = compact_coinank_hot_series_record(record)

    assert compact is not None
    assert "raw_data" not in compact
    assert "request_parameters" not in compact
    assert compact["coinank_metric"] == 1.0
    assert all(compact[field] is False for field in hostile_true_fields)
    assert all(field not in compact for field in forged_aliases)
    assert compact["admitted_feature_count"] == 0
    assert compact["available_at"] is None
    assert compact["zero_filled_field_count"] == 0
    assert compact["no_zero_fill_for_unknown_fields"] is True
    assert all(
        value is None or type(value) in {bool, int, float, str} for value in compact.values()
    )


def test_invalid_scalars_identity_unicode_and_mapping_width_are_rejected() -> None:
    record = _record(2)
    record["nan"] = math.nan
    record["inf"] = math.inf
    record["nested"] = {"value": 2.0}
    record["huge_integer"] = 10**1_000

    compact = compact_coinank_hot_series_record(record)

    assert compact is not None
    assert all(field not in compact for field in ("nan", "inf", "nested", "huge_integer"))
    assert compact_coinank_hot_series_record({**_record(3), "endpoint": "bad\u202e"}) is None
    assert compact_coinank_hot_series_record({**_record(3), "bad\u0000key": 1}) is None
    assert compact_coinank_hot_series_record({**_record(3), "ts_epoch_ms": True}) is None
    wide: dict[str, object] = {
        f"field_{index}": index for index in range(MAX_HOT_SERIES_INPUT_MAPPING_FIELDS + 1)
    }
    wide.update({"ts_epoch_ms": 1, "endpoint": "e", "family": "f"})
    assert compact_coinank_hot_series_record(wide) is None


@pytest.mark.parametrize("token", ("NaN", "Infinity", "-Infinity"))
def test_safe_decoder_rejects_nonfinite_json_constants(token: str) -> None:
    with pytest.raises(CoinAnkHotSeriesValidationError, match="json_nonfinite"):
        decode_coinank_hot_series_json(f'{{"value":{token}}}')


def test_safe_decoder_rejects_duplicates_bidi_depth_width_strings_and_bytes() -> None:
    hostile_values = (
        ('{"value":1,"value":2}', "duplicate_key"),
        ('{"value":"bad\u202e"}', "string_invalid"),
        ('{"value":"bad\\u0000"}', "string_invalid"),
        ("[" * 34 + "0" + "]" * 34, "depth_exceeded"),
        (json.dumps([0] * 100_001), "array_too_wide"),
        (json.dumps("x" * (MAX_HOT_SERIES_JSON_STRING_BYTES + 1)), "string_invalid"),
    )
    for raw, reason in hostile_values:
        with pytest.raises(CoinAnkHotSeriesValidationError, match=reason):
            decode_coinank_hot_series_json(raw)
    with pytest.raises(CoinAnkHotSeriesValidationError, match="byte_count_invalid"):
        decode_coinank_hot_series_json(b" " * MAX_HOT_SERIES_SOURCE_BYTES + b"[]")


def test_history_retains_newest_rows_and_reports_all_evictions() -> None:
    existing = [_record(index) for index in range(MAX_HOT_SERIES_ROWS + 25)]

    result = compact_coinank_hot_series(existing, _record(999))

    assert result is not None
    assert result.source_record_count == MAX_HOT_SERIES_ROWS + 26
    assert result.retained_record_count == MAX_HOT_SERIES_ROWS
    assert result.evicted_record_count == 26
    assert result.records[-1]["coinank_metric"] == 999.0
    assert result.records[0]["coinank_metric"] == 26.0
    assert len(result.encoded_json.encode("ascii")) <= MAX_HOT_SERIES_ENCODED_BYTES
    decoded = json.loads(result.encoded_json)
    assert len(decoded) == MAX_HOT_SERIES_ROWS
    assert all("raw_data" not in row and "request_parameters" not in row for row in decoded)
    assert all(all(type(value) not in {dict, list} for value in row.values()) for row in decoded)


def test_byte_eviction_preserves_a_contiguous_newest_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oldest = _record(0)
    newer = _record(1, pad_size=2_000)
    current = _record(2)
    projected_oldest = compact_coinank_hot_series_record(oldest)
    projected_current = compact_coinank_hot_series_record(current)
    assert projected_oldest is not None and projected_current is not None
    old_bytes = len(json.dumps(projected_oldest, sort_keys=True, separators=(",", ":")))
    current_bytes = len(json.dumps(projected_current, sort_keys=True, separators=(",", ":")))
    reserve = int(hot_series._COMPACTION_METADATA_RESERVE_BYTES)
    monkeypatch.setattr(
        hot_series,
        "MAX_HOT_SERIES_ENCODED_BYTES",
        reserve + old_bytes + current_bytes + 3,
    )

    result = compact_coinank_hot_series([oldest, newer], current)

    assert result is not None
    assert [record["coinank_metric"] for record in result.records] == [2.0]


def test_oversized_legacy_cache_rebuild_is_flat_and_current_only() -> None:
    result = compact_coinank_hot_series(
        [_record(1), _record(2)],
        _record(3),
        reset_reason="OVERSIZED_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST",
        prior_series_bytes=300_000_000,
    )

    assert result is not None
    assert result.retained_record_count == 1
    assert result.records[0]["coinank_metric"] == 3.0
    assert result.records[0]["hot_series_reset_reason"] == (
        "OVERSIZED_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST"
    )
    assert result.records[0]["hot_series_prior_series_bytes"] == 300_000_000
    assert result.records[0]["hot_series_source_record_count"] == 1
    assert result.records[0]["hot_series_retained_record_count"] == 1
    assert result.records[0]["hot_series_evicted_record_count"] == 0
    assert result.records[0]["raw_provider_payload_not_deleted_by_hot_cache_compaction"] is True
    assert all(type(value) not in {dict, list} for value in result.records[0].values())


def test_humanized_nested_protected_claim_names_cannot_override_contract() -> None:
    record = _record(8)
    aliases = {
        "Publication Authority": True,
        "audit.publication committed": True,
        "Nested > Publish Committed": True,
        "Nested / Trainer Admission Granted": True,
        "HOT-SERIES ROLE": "AUTHORITATIVE",
        "Available At": "2099-01-01T00:00:00Z",
        "No Zero-Fill For Unknown Fields": False,
        "Request.Parameters": "forged",
        "audit": {"Publication Authority": True},
    }
    record.update(aliases)

    compact = compact_coinank_hot_series_record(record)

    assert compact is not None
    assert all(alias not in compact for alias in aliases)
    assert compact["publication_authority"] is False
    assert compact["trainer_admission_granted"] is False
    assert compact["hot_series_role"] == "EXPIRING_NON_AUTHORITATIVE_SCALAR_HISTORY"
    assert compact["available_at"] is None
    assert compact["no_zero_fill_for_unknown_fields"] is True
    assert "raw_data" not in compact
    assert "request_parameters" not in compact

    homoglyph = _record(9)
    homoglyph["Ｐｕｂｌｉｃａｔｉｏｎ　Ａｕｔｈｏｒｉｔｙ"] = True
    assert compact_coinank_hot_series_record(homoglyph) is None


def test_closed_scalar_abi_only_admits_core_and_safe_coinank_namespace() -> None:
    record = _record(10)
    record.update(
        {
            "arbitrary_scalar": 7,
            "ok_to_trade": True,
            "coinank_open_interest": 12.5,
            "coinank_ok_to_trade": True,
            "coinank_execution_enabled": True,
            "coinank_permission_to_trade": "yes",
            "coinank_valid_for_live": True,
            "coinank_provider_ready": True,
            "coinank_exchange_action_taken": True,
        }
    )

    compact = compact_coinank_hot_series_record(record)

    assert compact is not None
    assert compact["family"] == "advanced"
    assert compact["baseCoin"] == "BTCUSDT"
    assert compact["coinank_open_interest"] == 12.5
    for forbidden in (
        "arbitrary_scalar",
        "ok_to_trade",
        "coinank_ok_to_trade",
        "coinank_execution_enabled",
        "coinank_permission_to_trade",
        "coinank_valid_for_live",
        "coinank_provider_ready",
        "coinank_exchange_action_taken",
    ):
        assert forbidden not in compact
    assert compact["live_execution_authority"] is False
    assert compact["publication_authority"] is False


@pytest.mark.parametrize(
    "forged_field",
    (
        "coinank_should_trade",
        "coinank_SHOULD-TRADE",
        "coinank_should.trade",
        "coinank_should trade",
        "coinank_shouldTrade",
        "coinank_shouldtrade",
        "coinank_t-r-a-d-e_ok",
        "coinank_trade_ok",
        "coinank_tradeok",
        "coinank_safe_to_trade",
        "coinank_safetotrade",
        "coinank_order_allowed",
        "coinank_orderallowed",
        "coinank_o-r-d-e-r_allowed",
        "coinank_permit_trade",
        "coinank_execute_now",
        "coinank_actionable",
        "coinank_a-c-t-i-o-n",
        "coinank_takeAction",
        "coinank_use_for_training",
        "coinank_usefortraining",
        "coinank_t-r-a-i-n-i-n-g",
        "coinank_training_ready",
        "coinank_modelready",
        "coinank_admissionGranted",
        "coinank_eligibility.ready",
        "coinank_signalEnabled",
        "coinank_s-i-g-n-a-l",
        "coinank_approveOrder",
        "coinank_golive",
        "coinank_trustForLive",
        "coinank_recommend_leverage",
    ),
)
def test_semantic_authority_action_and_training_aliases_are_excluded(
    forged_field: str,
) -> None:
    record = _record(11)
    record[forged_field] = True

    compact = compact_coinank_hot_series_record(record)

    assert compact is not None
    assert forged_field not in compact
    assert compact["publication_authority"] is False
    assert compact["trainer_authority"] is False
    assert compact["live_execution_authority"] is False


@pytest.mark.parametrize(
    "forged_field",
    (
        "coinank_marketorder_operational",
        "coinank_marketorder_forbidden",
        "coinank_marketOrder_operational",
        "coinank_market-order-operational",
        "coinank_market.order.operational",
        "coinank_market order operational",
        "coinank_MARKETORDER_OPERATIONAL",
        "coinank_marketOrder_forbidden",
        "coinank_market-order-forbidden",
        "coinank_market.order.forbidden",
        "coinank_market order forbidden",
        "coinank_MARKETORDER_FORBIDDEN",
    ),
)
def test_telemetry_compounds_cannot_use_substring_metric_evidence(
    forged_field: str,
) -> None:
    compact = compact_coinank_hot_series_record({**_record(12), forged_field: True})

    assert compact is not None
    assert forged_field not in compact


@pytest.mark.parametrize(
    "forged_field",
    (
        "coinank_marketorder_operational_value",
        "coinank_marketorder_forbidden_value",
        "coinank_marketOrder_operational_value",
        "coinank_market-order-operational-value",
        "coinank_market.order.operational.value",
        "coinank_market order operational value",
        "coinank_MARKETORDER_OPERATIONAL_VALUE",
        "coinank_marketOrder_forbidden_value",
        "coinank_market-order-forbidden-value",
        "coinank_market.order.forbidden.value",
        "coinank_market order forbidden value",
        "coinank_MARKETORDER_FORBIDDEN_VALUE",
        "coinank_submitMarketOrder_value",
        "coinank_placeMarketOrder_value",
        "coinank_cancelMarketOrder_value",
        "coinank_marketOrderPlaced_value",
        "coinank_submit-market-order-value",
        "coinank_PLACE_MARKETORDER_VALUE",
        "coinank_market.order.cancelled.value",
    ),
)
def test_exact_metric_suffix_cannot_launder_unknown_or_action_tokens(
    forged_field: str,
) -> None:
    compact = compact_coinank_hot_series_record({**_record(12), forged_field: True})

    assert compact is not None
    assert forged_field not in compact


@pytest.mark.parametrize(
    "forged_field",
    (
        "coinank_marketorder_ope_ratio_nal",
        "coinank_marketorder_ope-ratio-nal",
        "coinank_marketorder_ope.ratio.nal",
        "coinank_marketorder_ope ratio nal",
        "coinank_marketorder_opeRatioNal",
        "coinank_MARKETORDER_OPE_RATIO_NAL",
        "coinank_marketorder_for_bid_den",
        "coinank_marketorder_for-bid-den",
        "coinank_marketorder_for.bid.den",
        "coinank_marketorder_for bid den",
        "coinank_marketorder_forBidDen",
        "coinank_MARKETORDER_FOR_BID_DEN",
        "coinank_market-order-for-bid-den",
    ),
)
def test_split_metric_tokens_cannot_reassemble_into_unrelated_words(
    forged_field: str,
) -> None:
    compact = compact_coinank_hot_series_record({**_record(12), forged_field: True})

    assert compact is not None
    assert forged_field not in compact


@pytest.mark.parametrize(
    "near_miss",
    (
        "accountable",
        "amounted",
        "masked",
        "forbidden",
        "disclosed",
        "discounted",
        "scvdx",
        "metadata",
        "depthless",
        "firstly",
        "imbalanced",
        "lasting",
        "blacklists",
        "belonging",
        "meaningful",
        "medianized",
        "opened",
        "opposition",
        "priceless",
        "qtyish",
        "quantityish",
        "separate",
        "operational",
        "shortcut",
        "assumption",
        "totalitarian",
        "turnoverish",
        "busdriver",
        "devalued",
        "involved",
        "volumetric",
    ),
)
def test_metric_evidence_near_misses_do_not_safelist_order_claims(near_miss: str) -> None:
    forged_field = f"coinank_marketorder_{near_miss}_value"

    compact = compact_coinank_hot_series_record({**_record(12), forged_field: True})

    assert compact is not None
    assert forged_field not in compact


@pytest.mark.parametrize(
    "telemetry_field",
    (
        "coinank_marketOrder_value",
        "coinank_market-order-value",
        "coinank_market.order.value",
        "coinank_market order value",
        "coinank_MARKETORDER_VALUE",
        "coinank_orderFlow_bids",
        "coinank_order-flow-asks",
        "coinank_order.book.depths",
        "coinank_bigOrder_imbalances",
        "coinank_topTrader_positions",
        "coinank_MARKETORDER_GETBUYSELLVALUE_DATA_COL1_LAST",
        "coinank_LS_TOPTRADER_ACCOUNTS_LONGSHORTRATIO_MEAN",
    ),
)
def test_exact_metric_tokens_preserve_closed_telemetry_compounds(
    telemetry_field: str,
) -> None:
    compact = compact_coinank_hot_series_record({**_record(12), telemetry_field: 1.25})

    assert compact is not None
    assert compact[telemetry_field] == 1.25


def test_observed_order_flow_and_top_trader_scalar_telemetry_remains_admitted() -> None:
    telemetry = {
        "coinank_marketOrder_getBuySellValue_data_col1_last": 101.0,
        "coinank_orderFlow_lists_data_0_asks_mean": 102.0,
        "coinank_bigorder_imbalance": 103.0,
        "coinank_orderbook_depth": 104.0,
        "coinank_ls_toptrader_accounts_longShortRatio_mean": 1.5,
        "coinank_open_interest": 1_000.0,
        "coinank_liquidation_history_data_0_longTurnover": 50.0,
    }

    compact = compact_coinank_hot_series_record({**_record(12), **telemetry})

    assert compact is not None
    assert {key: compact[key] for key in telemetry} == telemetry


def test_coinank_prefixed_homoglyph_semantic_alias_rejects_the_record() -> None:
    record = _record(13)
    record["coinank_shοuld_trade"] = True  # Greek omicron, not ASCII "o".

    assert compact_coinank_hot_series_record(record) is None


def test_non_monotonic_or_duplicate_source_timestamps_are_not_a_contiguous_suffix() -> None:
    assert compact_coinank_hot_series([_record(2), _record(1)], _record(3)) is None
    assert compact_coinank_hot_series([_record(1), _record(1)], _record(3)) is None
    assert compact_coinank_hot_series([_record(1), _record(3)], _record(2)) is None


def test_direct_string_byte_limit_is_checked_without_whole_value_encoding() -> None:
    with pytest.raises(CoinAnkHotSeriesValidationError, match="byte_count_invalid"):
        decode_coinank_hot_series_json("[]" * 9, max_bytes=16)
    with pytest.raises(CoinAnkHotSeriesValidationError, match="byte_count_invalid"):
        decode_coinank_hot_series_json('"' + "😀" * 5 + '"', max_bytes=16)
