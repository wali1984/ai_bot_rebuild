from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
import struct
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest
import talib

from v2.backend.app.services.feature_pipeline_native.service import (
    _bb_width_pct as deployed_bb_width_pct,
)
from v2.backend.app.services.feature_pipeline_native.service import _ema as deployed_ema
from v2.backend.app.services.feature_pipeline_native.service import _macd as deployed_macd
from v2.backend.app.services.feature_pipeline_native.service import _rsi as deployed_rsi
from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256,
    AuthenticatedOhlcvProfileTransformV1Error,
    transform_authenticated_ohlcv_profile_v1,
    validate_authenticated_ohlcv_capture_set_v1,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    canonical_ohlcv_multitimeframe_capture_set_v1_contract,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_multitimeframe_capture_set_v1 as capture_support,
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _float32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


def _rehash_contract(contract: dict[str, Any]) -> str:
    for timeframe in contract["timeframes"]:
        for row in timeframe["rows"]:
            identity = {
                key: value
                for key, value in row.items()
                if key not in {"source_read_receipt_v4", "row_identity_sha256"}
            }
            row["row_identity_sha256"] = _sha256(identity)
        timeframe["ordered_row_identity_sha256s"] = [
            row["row_identity_sha256"] for row in timeframe["rows"]
        ]
        timeframe["ordered_source_receipt_sha256s"] = [
            row["source_read_receipt_sha256"] for row in timeframe["rows"]
        ]
        timeframe_material = {
            key: value for key, value in timeframe.items() if key != "timeframe_capture_sha256"
        }
        timeframe["timeframe_capture_sha256"] = _sha256(timeframe_material)
    root_material = {
        key: value
        for key, value in contract.items()
        if key not in {"content_address", "capture_set_sha256", "capture_set_manifest_byte_count"}
    }
    root_bytes = _canonical_bytes(root_material)
    root = hashlib.sha256(root_bytes).hexdigest()
    contract["capture_set_sha256"] = root
    contract["capture_set_manifest_byte_count"] = len(root_bytes)
    contract["content_address"]["payload_sha256"] = root
    contract["content_address"]["payload_byte_count"] = len(root_bytes)
    return root


@pytest.fixture(scope="module")
def authenticated_contract(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("authenticated-ohlcv-transform")
    artifact, _store = capture_support._build(Path(root))
    contract = canonical_ohlcv_multitimeframe_capture_set_v1_contract(artifact)
    assert contract["capture_set_sha256"] == (
        "19cbf7c7118ce977a3b8a871f6da89deafb01a83fde3517f40517bf381890383"
    )
    return contract


@pytest.fixture(scope="module")
def transformed(authenticated_contract: dict[str, Any]):  # type: ignore[no-untyped-def]
    return transform_authenticated_ohlcv_profile_v1(
        authenticated_contract,
        expected_capture_set_sha256=authenticated_contract["capture_set_sha256"],
    )


def _features(result: Any) -> dict[str, dict[str, Any]]:
    return {item["feature_name"]: item for item in result.contract["ordered_features"]}


def test_exact_profile_inventory_float32_and_auxiliary_channel(
    transformed: Any,
) -> None:
    contract = transformed.contract
    expected_names = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_feature_names

    assert contract["feature_count"] == 35
    assert transformed.ordered_feature_names == expected_names
    assert tuple(item["ordinal"] for item in contract["ordered_features"]) == (
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS
    )
    assert len(transformed.ordered_feature_values) == 35
    for item in contract["ordered_features"]:
        packed = bytes.fromhex(item["value_float32_be_hex"])
        assert len(packed) == 4
        assert struct.unpack(">f", packed)[0] == item["value_float32"]
        assert math.isfinite(item["value_float32"])

    auxiliary = contract["auxiliary_label_evidence_requirements"]
    assert auxiliary["required_input_names"] == ["fee", "spread", "slippage", "funding"]
    assert auxiliary["excluded_from_model_feature_vector"] is True
    assert auxiliary["included_in_35_enabled_features"] is False
    assert auxiliary["supplied_by_this_transform"] is False
    assert all(item["model_feature"] is False for item in auxiliary["required_inputs"])
    assert not set(auxiliary["required_input_names"]) & set(transformed.ordered_feature_names)
    assert all(value is False for value in contract["authorization"].values())


def test_native_5m_formulas_match_deployed_contracts_and_wilder_talib(
    authenticated_contract: dict[str, Any],
    transformed: Any,
) -> None:
    rows = authenticated_contract["timeframes"][0]["rows"]
    closes = [float(row["ohlcv"]["close"]) for row in rows]
    highs = np.asarray([row["ohlcv"]["high"] for row in rows], dtype="float64")
    lows = np.asarray([row["ohlcv"]["low"] for row in rows], dtype="float64")
    close_array = np.asarray(closes, dtype="float64")
    latest = rows[-1]["ohlcv"]
    previous = rows[-2]["ohlcv"]
    features = _features(transformed)

    deployed_macd_values = deployed_macd(closes)
    expected = {
        "quote_volume": latest["quote_volume"],
        "volume": latest["volume"],
        "open": latest["open"],
        "high": latest["high"],
        "low": latest["low"],
        "close": latest["close"],
        "num_trades": latest["num_trades"],
        "taker_buy_base_vol": latest["taker_buy_base_vol"],
        "taker_buy_quote_vol": latest["taker_buy_quote_vol"],
        "taker_sell_base_vol": latest["volume"] - latest["taker_buy_base_vol"],
        "taker_sell_quote_vol": latest["quote_volume"] - latest["taker_buy_quote_vol"],
        "taker_buy_ratio": latest["taker_buy_base_vol"] / latest["volume"],
        "taker_sell_ratio": 1.0 - latest["taker_buy_base_vol"] / latest["volume"],
        "ohlcv_close": latest["close"],
        "ohlcv_volume": latest["volume"],
        "ret_pct": (latest["close"] - previous["close"]) / previous["close"],
        "log_return": math.log(latest["close"] / previous["close"]),
        "range_pct": (latest["high"] - latest["low"]) / latest["close"],
        "body_pct": (latest["close"] - latest["open"]) / latest["close"],
        "true_range_pct": float(talib.ATR(highs, lows, close_array, timeperiod=14)[-1])
        / latest["close"],
        "ema_12": deployed_ema(closes, 12),
        "ema_26": deployed_ema(closes, 26),
        "rsi_14": deployed_rsi(closes, 14),
        "macd": deployed_macd_values["macd"],
        "macd_signal": deployed_macd_values["signal"],
        "macd_hist": deployed_macd_values["hist"],
        "bb_width_pct": deployed_bb_width_pct(closes, period=20, k=2.0),
    }
    assert all(value is not None for value in expected.values())
    for name, value in expected.items():
        assert features[name]["value_float32"] == _float32(float(value))

    window = closes[-20:]
    population_width = 4.0 * statistics.pstdev(window) / (sum(window) / len(window))
    assert features["bb_width_pct"]["value_float32"] == _float32(population_width)


def test_true_1h_outputs_are_exact_talib_latest_float32(
    authenticated_contract: dict[str, Any],
    transformed: Any,
) -> None:
    rows = authenticated_contract["timeframes"][1]["rows"]
    highs = np.asarray([row["ohlcv"]["high"] for row in rows], dtype="float64")
    lows = np.asarray([row["ohlcv"]["low"] for row in rows], dtype="float64")
    closes = np.asarray([row["ohlcv"]["close"] for row in rows], dtype="float64")
    volumes = np.asarray([row["ohlcv"]["volume"] for row in rows], dtype="float64")
    _line, _signal, hist = talib.MACD(
        closes,
        fastperiod=12,
        slowperiod=26,
        signalperiod=9,
    )
    expected = {
        "htf1h_taf_rsi": talib.RSI(closes, timeperiod=14),
        "htf1h_taf_adx": talib.ADX(highs, lows, closes, timeperiod=14),
        "htf1h_taf_macd_hist": hist,
        "htf1h_taf_atr": talib.ATR(highs, lows, closes, timeperiod=14),
        "htf1h_taf_mfi": talib.MFI(highs, lows, closes, volumes, timeperiod=14),
        "htf1h_taf_willr": talib.WILLR(highs, lows, closes, timeperiod=14),
        "htf1h_taf_natr": talib.NATR(highs, lows, closes, timeperiod=14),
        "htf1h_taf_cci": talib.CCI(highs, lows, closes, timeperiod=14),
    }
    features = _features(transformed)
    for name, output in expected.items():
        assert len(output) == 34
        assert math.isfinite(float(output[-1]))
        assert features[name]["value_float32"] == _float32(float(output[-1]))


def test_talib_process_global_compatibility_drift_fails_closed(
    authenticated_contract: dict[str, Any],
) -> None:
    original = talib.get_compatibility()
    try:
        talib.set_compatibility(1)
        assert talib.get_compatibility() == 1
        with pytest.raises(
            AuthenticatedOhlcvProfileTransformV1Error,
            match="AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_ENVIRONMENT_MISMATCH",
        ):
            transform_authenticated_ohlcv_profile_v1(
                authenticated_contract,
                expected_capture_set_sha256=authenticated_contract["capture_set_sha256"],
            )
    finally:
        talib.set_compatibility(original)
    assert talib.get_compatibility() == original


def test_each_composite_material_binds_exact_rows_hashes_and_all_seven_clocks(
    authenticated_contract: dict[str, Any],
    transformed: Any,
) -> None:
    expected_roots = {
        timeframe["timeframe"]: timeframe["ordered_source_receipt_sha256s"]
        for timeframe in authenticated_contract["timeframes"]
    }
    for item in transformed.contract["ordered_features"]:
        material = item["composite_derivation_receipt_material"]
        timeframe = item["source_timeframe"]
        assert material["receipt_kind"] == "COMPOSITE_DERIVATION"
        assert [edge["receipt_sha256"] for edge in material["child_read_bindings"]] == (
            expected_roots[timeframe]
        )
        assert material["exact_bindings"]["timestamps"] == authenticated_contract["timestamps"]
        assert (
            material["exact_bindings"]["capture_set_sha256"]
            == (authenticated_contract["capture_set_sha256"])
        )
        assert material["exact_bindings"]["implementation_sha256"] == (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        )
        assert material["exact_bindings"]["global_configuration_sha256"] == (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        )
        assert _sha256(material) == item["composite_derivation_receipt_material_sha256"]
        assert material["payload_byte_count"] == 4
        assert (
            material["payload_sha256"]
            == hashlib.sha256(bytes.fromhex(material["value_float32_be_hex"])).hexdigest()
        )
        assert all(
            len(material["exact_bindings"][name]) == 64
            for name in (
                "implementation_sha256",
                "module_code_sha256",
                "global_configuration_sha256",
                "feature_configuration_sha256",
                "transform_sha256",
            )
        )


@pytest.mark.parametrize(
    ("timeframe_index", "expected_rows"),
    ((0, 71), (1, 34)),
)
def test_exact_minimum_rows_fail_closed(
    authenticated_contract: dict[str, Any],
    timeframe_index: int,
    expected_rows: int,
) -> None:
    candidate = copy.deepcopy(authenticated_contract)
    assert len(candidate["timeframes"][timeframe_index]["rows"]) == expected_rows
    candidate["timeframes"][timeframe_index]["rows"].pop(0)
    root = _rehash_contract(candidate)

    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_EXACT_LOOKBACK_REQUIRED",
    ):
        transform_authenticated_ohlcv_profile_v1(
            candidate,
            expected_capture_set_sha256=root,
        )


def test_value_tamper_and_rehashed_tamper_both_fail_external_root(
    authenticated_contract: dict[str, Any],
) -> None:
    original_root = authenticated_contract["capture_set_sha256"]
    stale = copy.deepcopy(authenticated_contract)
    stale["timeframes"][0]["rows"][-1]["ohlcv"]["close"] += 0.25
    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_CAPTURE_SHA256_MISMATCH",
    ):
        validate_authenticated_ohlcv_capture_set_v1(
            stale,
            expected_capture_set_sha256=original_root,
        )

    rehashed = copy.deepcopy(stale)
    forged_root = _rehash_contract(rehashed)
    assert forged_root != original_root
    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_EXPECTED_CAPTURE_SHA256_MISMATCH",
    ):
        validate_authenticated_ohlcv_capture_set_v1(
            rehashed,
            expected_capture_set_sha256=original_root,
        )


def test_receipt_tamper_fails_closed(
    authenticated_contract: dict[str, Any],
) -> None:
    candidate = copy.deepcopy(authenticated_contract)
    candidate["timeframes"][1]["rows"][0]["source_read_receipt_v4"]["receipt_sha256"] = "9" * 64
    root = _rehash_contract(candidate)
    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_RECEIPT_INVALID",
    ):
        validate_authenticated_ohlcv_capture_set_v1(
            candidate,
            expected_capture_set_sha256=root,
        )


def test_independent_transform_rejects_rehashed_required_window_rest_row(
    authenticated_contract: dict[str, Any],
) -> None:
    candidate = copy.deepcopy(authenticated_contract)
    row = candidate["timeframes"][1]["rows"][0]
    row["source_transport"] = "binance_rest"
    row["is_backfilled"] = True
    root = _rehash_contract(candidate)

    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_REQUIRED_WINDOW_REST_PROVENANCE_UNAVAILABLE",
    ):
        validate_authenticated_ohlcv_capture_set_v1(
            candidate,
            expected_capture_set_sha256=root,
        )


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_input_fails_before_transform(
    authenticated_contract: dict[str, Any],
    bad_value: float,
) -> None:
    candidate = copy.deepcopy(authenticated_contract)
    candidate["timeframes"][0]["rows"][-1]["ohlcv"]["open"] = bad_value
    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_NONFINITE_INPUT",
    ):
        transform_authenticated_ohlcv_profile_v1(
            candidate,
            expected_capture_set_sha256=authenticated_contract["capture_set_sha256"],
        )


def test_zero_ratio_denominator_fails_closed(
    authenticated_contract: dict[str, Any],
) -> None:
    candidate = copy.deepcopy(authenticated_contract)
    latest = candidate["timeframes"][0]["rows"][-1]["ohlcv"]
    latest["volume"] = 0.0
    latest["taker_buy_base_vol"] = 0.0
    root = _rehash_contract(candidate)

    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_LATEST_VOLUME_ZERO",
    ):
        transform_authenticated_ohlcv_profile_v1(
            candidate,
            expected_capture_set_sha256=root,
        )


def test_point_in_time_clock_violation_fails_closed(
    authenticated_contract: dict[str, Any],
) -> None:
    candidate = copy.deepcopy(authenticated_contract)
    candidate["timestamps"]["decision_time"] = "2026-07-21T12:00:00.015000Z"
    candidate["timestamps"]["generated_at"] = "2026-07-21T12:00:00.010000Z"
    root = _rehash_contract(candidate)

    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match=(
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_CAPTURE_CLOCK_ORDER_INVALID|"
            "AUTHENTICATED_OHLCV_TRANSFORM_V1_ROW_CAUSAL_ORDER_INVALID"
        ),
    ):
        transform_authenticated_ohlcv_profile_v1(
            candidate,
            expected_capture_set_sha256=root,
        )


def test_determinism_accepts_immutable_mapping_and_profile_hash_is_pinned(
    authenticated_contract: dict[str, Any],
    transformed: Any,
) -> None:
    immutable_top = MappingProxyType(copy.deepcopy(authenticated_contract))
    second = transform_authenticated_ohlcv_profile_v1(
        immutable_top,
        expected_capture_set_sha256=authenticated_contract["capture_set_sha256"],
    )
    assert second.artifact_json == transformed.artifact_json
    assert second.artifact_sha256 == transformed.artifact_sha256
    assert second.ordered_receipt_material_sha256s == (transformed.ordered_receipt_material_sha256s)

    with pytest.raises(
        AuthenticatedOhlcvProfileTransformV1Error,
        match="AUTHENTICATED_OHLCV_TRANSFORM_V1_EXPECTED_PROFILE_SHA256_MISMATCH",
    ):
        transform_authenticated_ohlcv_profile_v1(
            authenticated_contract,
            expected_capture_set_sha256=authenticated_contract["capture_set_sha256"],
            expected_profile_sha256="0" * 64,
        )
    assert transformed.profile_sha256 == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
