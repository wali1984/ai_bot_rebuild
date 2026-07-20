from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.canonical_feature_value_resolver_v4 import (
    RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED,
    RESOLUTION_MISSING_NULL,
    RESOLUTION_MISSING_SOURCE_RECORD,
    RESOLUTION_PLAN_UNRESOLVED,
    RESOLUTION_RESOLVED_MEASURED,
    RESOLUTION_SOURCE_RECORD_REJECTED,
    RESOLUTION_TYPED_NEGATIVE_RECEIPT_REQUIRED,
    RESOLUTION_VALUE_REJECTED,
    CanonicalFeatureValueResolverV4Error,
    canonical_source_payload_sha256_v4,
    canonical_source_record_id_v4,
    canonical_source_record_sha256_v4,
    resolve_canonical_feature_value_v4,
    resolve_canonical_feature_values_v4,
)
from v2.backend.app.services.native_trainer.feature_resolution_plan_v4 import (
    CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION,
    FEATURE_RESOLUTION_PLAN_V4,
    FEATURE_RESOLUTION_PLAN_V4_SHA256,
    FeatureResolutionPlanV4ValidationError,
    FeatureSlotResolutionPlanV4,
    materialize_feature_source_key_v4,
    materialize_feature_source_timeframe_v4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)

DECISION = "2026-07-20T12:01:00.000000Z"


def _slot(name: str) -> FeatureSlotResolutionPlanV4:
    return next(slot for slot in FEATURE_RESOLUTION_PLAN_V4.slots if slot.feature_name == name)


def _record(
    slot: FeatureSlotResolutionPlanV4,
    payload: object,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    event_time: str = "2026-07-20T12:00:00.100000Z",
    ingested_at: str = "2026-07-20T12:00:00.200000Z",
    source_available_at: str = "2026-07-20T12:00:00.300000Z",
    feature_cutoff: str = "2026-07-20T12:00:00.100000Z",
    generated_at: str = "2026-07-20T12:00:00.400000Z",
    publication_available_at: str = "2026-07-20T12:00:00.500000Z",
    candle_close_time: str | None = None,
    candle_final: bool | None = None,
    absence_receipt: object = None,
) -> tuple[str, dict[str, object]]:
    key = materialize_feature_source_key_v4(slot, symbol=symbol, timeframe=timeframe)
    source_timeframe = materialize_feature_source_timeframe_v4(
        slot,
        request_timeframe=timeframe,
    )
    record_id = canonical_source_record_id_v4(
        source_label=slot.configured_source_label,
        source_key=key,
        symbol=symbol,
        request_timeframe=timeframe,
        source_timeframe=source_timeframe,
    )
    record: dict[str, object] = {
        "schema_version": CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION,
        "payload_schema_version": slot.source_payload_schema_version,
        "source_label": slot.configured_source_label,
        "source_key": key,
        "source_record_id": record_id,
        "symbol": symbol,
        "request_timeframe": timeframe,
        "source_timeframe": source_timeframe,
        "payload": payload,
        "payload_sha256": canonical_source_payload_sha256_v4(payload),
        "event_time": event_time,
        "ingested_at": ingested_at,
        "source_available_at": source_available_at,
        "feature_cutoff": feature_cutoff,
        "generated_at": generated_at,
        "publication_available_at": publication_available_at,
        "candle_close_time": candle_close_time,
        "candle_final": candle_final,
        "absence_receipt": absence_receipt,
    }
    record["source_record_sha256"] = canonical_source_record_sha256_v4(record)
    return record_id, record


def _resolve(
    slot: FeatureSlotResolutionPlanV4,
    records: dict[str, dict[str, object]],
) -> dict[str, Any]:
    return resolve_canonical_feature_value_v4(
        ordinal=slot.ordinal,
        symbol="BTCUSDT",
        request_timeframe="5m",
        decision_time=DECISION,
        source_records=records,
    ).result


def test_measured_zero_is_resolved_and_never_confused_with_absence() -> None:
    slot = _slot("funding_rate")
    key, record = _record(slot, {"funding_rate": 0.0})
    result = _resolve(slot, {key: record})

    assert result["resolution_status"] == RESOLUTION_RESOLVED_MEASURED
    assert result["resolved_value"] == 0.0
    assert result["resolved_value_float32_be_hex"] == "00000000"
    assert result["selected_source_label"] == "v2:market:funding"
    assert result["selected_source_key"] == "v2:market:funding:BTCUSDT"
    assert result["selected_path"] == ["funding_rate"]
    assert result["selected_alias"] == "funding_rate"
    assert result["rejection_reasons"] == []


def test_explicit_null_stops_alias_search_and_remains_none() -> None:
    slot = _slot("mark_price")
    key, record = _record(
        slot,
        {
            "funding": {"markPrice": None},
            "mark_price": 123.0,
        },
    )
    result = _resolve(slot, {key: record})

    assert result["resolution_status"] == RESOLUTION_MISSING_NULL
    assert result["resolved_value"] is None
    assert result["selected_alias"] == "funding.markPrice"
    assert result["selected_path"] == ["funding", "markPrice"]
    assert result["rejection_reasons"] == ["SELECTED_EXACT_VALUE_IS_NULL"]


def test_wrong_key_and_arbitrary_provider_record_are_not_fallbacks() -> None:
    slot = _slot("funding_rate")
    expected_record_id, record = _record(slot, {"funding_rate": 0.0001})
    assert record["source_key"] == "v2:market:funding:BTCUSDT"
    record["source_key"] = "provider_feature_bridge:BTCUSDT"
    provider_record_id = canonical_source_record_id_v4(
        source_label="provider_feature_bridge",
        source_key="provider_feature_bridge:BTCUSDT",
        symbol="BTCUSDT",
        request_timeframe="5m",
        source_timeframe=None,
    )
    result = _resolve(slot, {provider_record_id: record})

    assert expected_record_id != provider_record_id
    assert result["resolution_status"] == RESOLUTION_MISSING_SOURCE_RECORD
    assert result["resolved_value"] is None
    assert result["selected_source_key"] is None
    assert result["caller_supplied_source_record_inspected"] is False


def test_wrong_schema_and_payload_digest_fail_closed() -> None:
    slot = _slot("funding_rate")
    key, record = _record(slot, {"funding_rate": 0.0001})
    wrong_schema = deepcopy(record)
    wrong_schema["payload_schema_version"] = "some_other_provider_schema"
    schema_result = _resolve(slot, {key: wrong_schema})
    assert schema_result["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert "SOURCE_RECORD_PAYLOAD_SCHEMA_MISMATCH" in schema_result["rejection_reasons"]

    wrong_digest = deepcopy(record)
    wrong_digest["payload_sha256"] = "0" * 64
    digest_result = _resolve(slot, {key: wrong_digest})
    assert digest_result["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert "SOURCE_RECORD_PAYLOAD_SHA256_MISMATCH" in digest_result["rejection_reasons"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "ingested_at",
            "2026-07-20T12:00:00.000000Z",
            "SOURCE_RECORD_EVENT_TIME_AFTER_INGESTED_AT",
        ),
        (
            "source_available_at",
            "2026-07-20T12:00:00.150000Z",
            "SOURCE_RECORD_INGESTED_AT_AFTER_SOURCE_AVAILABLE_AT",
        ),
        (
            "generated_at",
            "2026-07-20T12:00:00.250000Z",
            "SOURCE_RECORD_SOURCE_AVAILABLE_AT_AFTER_GENERATED_AT",
        ),
        (
            "feature_cutoff",
            "2026-07-20T12:00:00.450000Z",
            "SOURCE_RECORD_FEATURE_CUTOFF_AFTER_GENERATED_AT",
        ),
        (
            "publication_available_at",
            "2026-07-20T12:02:00.000000Z",
            "SOURCE_RECORD_PUBLICATION_AVAILABLE_AT_AFTER_DECISION_TIME",
        ),
    ],
)
def test_event_ingest_source_availability_feature_publication_and_decision_order(
    field: str,
    value: str,
    reason: str,
) -> None:
    slot = _slot("funding_rate")
    key, record = _record(slot, {"funding_rate": 0.0001})
    record[field] = value
    result = _resolve(slot, {key: record})

    assert result["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert reason in result["rejection_reasons"]
    assert result["resolved_value"] is None


def test_closed_ohlcv_derived_value_is_dependency_digest_bound() -> None:
    slot = _slot("taker_sell_base_vol")
    key, record = _record(
        slot,
        {"volume": 100.0, "taker_buy_base_vol": 40.0},
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    result = _resolve(slot, {key: record})

    assert result["resolution_status"] == RESOLUTION_RESOLVED_MEASURED
    assert result["resolved_value"] == 60.0
    assert result["dependency_paths"] == [["volume"], ["taker_buy_base_vol"]]
    assert len(result["dependency_leaf_sha256s"]) == 2
    assert result["dependency_root_sha256"]

    changed_key, changed = _record(
        slot,
        {"volume": 100.0, "taker_buy_base_vol": 41.0},
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    changed_result = _resolve(slot, {changed_key: changed})
    assert changed_result["resolved_value"] == 59.0
    assert changed_result["dependency_root_sha256"] != result["dependency_root_sha256"]


def test_unfinished_or_not_yet_available_candle_cannot_resolve() -> None:
    slot = _slot("close")
    key, unfinished = _record(
        slot,
        {"close": 100.0},
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=False,
    )
    unfinished_result = _resolve(slot, {key: unfinished})
    assert unfinished_result["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert "SOURCE_RECORD_UNFINISHED_CANDLE" in unfinished_result["rejection_reasons"]

    key, late = _record(
        slot,
        {"close": 100.0},
        source_available_at="2026-07-20T12:00:00.000000Z",
        feature_cutoff="2026-07-20T12:00:00.100000Z",
        generated_at="2026-07-20T12:00:00.400000Z",
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    late_result = _resolve(slot, {key: late})
    assert late_result["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert (
        "SOURCE_RECORD_CANDLE_CLOSE_NOT_BEFORE_SOURCE_AVAILABLE_AT"
        in late_result["rejection_reasons"]
    )


def test_candle_derived_ta_and_higher_timeframe_features_require_finality() -> None:
    rsi = _slot("RSI")
    key, no_finality = _record(rsi, {"indicators": {"RSI": 52.0}})
    rejected = _resolve(rsi, {key: no_finality})
    assert rejected["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert "SOURCE_RECORD_CANDLE_CLOSE_TIME_REQUIRED" in rejected["rejection_reasons"]

    key, finalized = _record(
        rsi,
        {"indicators": {"RSI": 52.0}},
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    resolved = _resolve(rsi, {key: finalized})
    assert resolved["resolution_status"] == RESOLUTION_RESOLVED_MEASURED
    assert resolved["resolved_value"] == 52.0

    htf = _slot("htf1h_taf_rsi")
    assert htf.requires_closed_candle is True


def test_empty_collection_and_typed_negative_never_fabricate_zero() -> None:
    funding = _slot("funding_rate")
    key, empty = _record(funding, [])
    empty_result = _resolve(funding, {key: empty})
    assert empty_result["resolution_status"] == RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED
    assert empty_result["resolved_value"] is None
    assert empty_result["selected_source_key"] is None

    key, claimed = _record(
        funding,
        [],
        absence_receipt={"authentication_verified": True, "event_count": 0},
    )
    claimed_result = _resolve(funding, {key: claimed})
    assert claimed_result["resolution_status"] == RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED
    assert claimed_result["rejection_reasons"] == [
        "AUTHENTICATED_EMPTY_WINDOW_RECEIPT_VERIFIER_UNWIRED"
    ]
    assert claimed_result["resolved_value"] is None

    key, empty_object = _record(funding, {})
    empty_object_result = _resolve(funding, {key: empty_object})
    assert empty_object_result["resolution_status"] == RESOLUTION_EMPTY_COLLECTION_RECEIPT_REQUIRED
    assert empty_object_result["resolved_value"] is None

    moralis = _slot("moralis_exchange_inflow_usd")
    key, negative = _record(
        moralis,
        {"typed_negative": {"reason": "NO_EVENT_IN_EXACT_WINDOW"}},
    )
    negative_result = _resolve(moralis, {key: negative})
    assert negative_result["resolution_status"] == RESOLUTION_TYPED_NEGATIVE_RECEIPT_REQUIRED
    assert negative_result["resolved_value"] is None


def test_invalid_derived_ohlcv_domain_is_rejected_not_clamped() -> None:
    slot = _slot("taker_sell_base_vol")
    key, record = _record(
        slot,
        {"volume": 10.0, "taker_buy_base_vol": 11.0},
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    result = _resolve(slot, {key: record})
    assert result["resolution_status"] == RESOLUTION_VALUE_REJECTED
    assert result["resolved_value"] is None
    assert result["rejection_reasons"] == ["DEPENDENCY_DOMAIN_INVALID"]


def test_legacy_future_liquidation_name_cannot_select_observed_alias() -> None:
    slot = FEATURE_RESOLUTION_PLAN_V4.slots[68]
    key, record = _record(
        slot,
        {
            "liquidation_long_level": 100.0,
            "long_level": 100.0,
            "future_liquidation_long_level": 100.0,
        },
    )
    result = _resolve(slot, {key: record})

    assert result["resolution_status"] == RESOLUTION_PLAN_UNRESOLVED
    assert (
        "RETROSPECTIVE_LIQUIDATION_DATA_CANNOT_PROVE_FUTURE_SEMANTICS"
        in result["rejection_reasons"][0]
    )
    assert result["caller_supplied_source_record_inspected"] is False
    assert result["selected_alias"] is None
    assert result["resolved_value"] is None


def test_full_shadow_output_is_ordered_446_and_cannot_authorize_any_consumer() -> None:
    funding = _slot("funding_rate")
    key, record = _record(funding, {"funding_rate": 0.0})
    audit = resolve_canonical_feature_values_v4(
        symbol="BTCUSDT",
        request_timeframe="5m",
        decision_time=DECISION,
        source_records={key: record},
    ).audit

    assert audit["slot_count"] == 446
    assert audit["resolved_measured_slot_count"] == 1
    assert [slot["ordinal"] for slot in audit["slot_results"]] == list(range(446))
    assert audit["feature_resolution_plan_sha256"] == FEATURE_RESOLUTION_PLAN_V4_SHA256
    assert audit["feature_source_registry_sha256"] == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert audit["audit_only"] is True
    assert audit["runtime_wired"] is False
    assert audit["runtime_source_reads_performed"] is False
    for field in (
        "tensor_eligible",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    ):
        assert audit[field] is False
        assert all(slot[field] is False for slot in audit["slot_results"])


def test_source_identity_separates_colliding_physical_key_semantics() -> None:
    ordinary = _slot("taf_rsi_14")
    higher_timeframe = _slot("htf1h_taf_rsi")
    ordinary_id, ordinary_record = _record(
        ordinary,
        {"indicators": {"rsi_14": 51.0}},
        timeframe="1h",
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    higher_id, higher_record = _record(
        higher_timeframe,
        {"indicators": {"rsi_14": 49.0}},
        timeframe="1h",
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    assert ordinary_record["source_key"] == higher_record["source_key"]
    assert ordinary_id != higher_id

    records = {ordinary_id: ordinary_record, higher_id: higher_record}
    ordinary_result = resolve_canonical_feature_value_v4(
        ordinal=ordinary.ordinal,
        symbol="BTCUSDT",
        request_timeframe="1h",
        decision_time=DECISION,
        source_records=records,
    ).result
    higher_result = resolve_canonical_feature_value_v4(
        ordinal=higher_timeframe.ordinal,
        symbol="BTCUSDT",
        request_timeframe="1h",
        decision_time=DECISION,
        source_records=records,
    ).result
    assert ordinary_result["resolved_value"] == 51.0
    assert higher_result["resolved_value"] == 49.0
    assert ordinary_result["selected_source_record_id"] == ordinary_id
    assert higher_result["selected_source_record_id"] == higher_id


def test_fixed_physical_source_timeframe_cannot_inherit_request_timeframe() -> None:
    slot = _slot("oi_change_pct")
    record_id, record = _record(slot, {"change_pct": 2.5}, timeframe="4h")
    assert record["request_timeframe"] == "4h"
    assert record["source_timeframe"] == "5m"
    resolved = resolve_canonical_feature_value_v4(
        ordinal=slot.ordinal,
        symbol="BTCUSDT",
        request_timeframe="4h",
        decision_time=DECISION,
        source_records={record_id: record},
    ).result
    assert resolved["resolution_status"] == RESOLUTION_RESOLVED_MEASURED
    assert resolved["source_timeframe"] == "5m"

    forged = deepcopy(record)
    forged["source_timeframe"] = "4h"
    forged["source_record_sha256"] = canonical_source_record_sha256_v4(forged)
    rejected = resolve_canonical_feature_value_v4(
        ordinal=slot.ordinal,
        symbol="BTCUSDT",
        request_timeframe="4h",
        decision_time=DECISION,
        source_records={record_id: forged},
    ).result
    assert rejected["resolution_status"] == RESOLUTION_SOURCE_RECORD_REJECTED
    assert "SOURCE_RECORD_SOURCE_TIMEFRAME_MISMATCH" in rejected["rejection_reasons"]


def test_shared_unkeyed_liquidity_zone_source_is_unresolved_across_timeframes() -> None:
    slot = _slot("liquidity_zone_above")
    record_id, record = _record(
        slot,
        {"liquidity_zone_above": 123.0, "timeframe": "1m"},
        timeframe="4h",
        candle_close_time="2026-07-20T12:00:00.000000Z",
        candle_final=True,
    )
    result = resolve_canonical_feature_value_v4(
        ordinal=slot.ordinal,
        symbol="BTCUSDT",
        request_timeframe="4h",
        decision_time=DECISION,
        source_records={record_id: record},
    ).result
    assert result["resolution_status"] == RESOLUTION_PLAN_UNRESOLVED
    assert result["caller_supplied_source_record_inspected"] is False
    assert result["resolved_value"] is None
    assert result["source_timeframe"] == "4h"
    assert result["rejection_reasons"] == [
        "UNRESOLVED_REQUEST_TIMEFRAME_OVERWRITES_SHARED_PHYSICAL_SOURCE_KEY"
    ]


def test_record_identity_binds_symbol_and_request_context_even_for_shared_key() -> None:
    slot = _slot("funding_rate")
    one_minute_id, one_minute = _record(slot, {"funding_rate": 0.0}, timeframe="1m")
    four_hour_id, four_hour = _record(slot, {"funding_rate": 0.0}, timeframe="4h")
    other_symbol_id, other_symbol = _record(
        slot,
        {"funding_rate": 0.0},
        symbol="ETHUSDT",
        timeframe="1m",
    )
    assert one_minute["source_key"] == four_hour["source_key"]
    assert one_minute_id != four_hour_id
    assert one_minute_id != other_symbol_id
    assert other_symbol["source_key"] != one_minute["source_key"]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest_without(value: dict[str, Any], digest_field: str) -> str:
    material = {key: item for key, item in value.items() if key != digest_field}
    return hashlib.sha256(_canonical_json(material).encode("ascii")).hexdigest()


def test_rehashed_result_cannot_forge_authority_or_embedded_digest() -> None:
    slot = _slot("funding_rate")
    record_id, record = _record(slot, {"funding_rate": 0.0})
    artifact = resolve_canonical_feature_value_v4(
        ordinal=slot.ordinal,
        symbol="BTCUSDT",
        request_timeframe="5m",
        decision_time=DECISION,
        source_records={record_id: record},
    )
    with pytest.raises(AttributeError):
        object.__setattr__(artifact, "trainer_admission_authorized", True)
    assert artifact.trainer_admission_authorized is False
    forged = artifact.result
    forged["trainer_admission_authorized"] = True
    forged_digest = _digest_without(forged, "result_sha256")
    forged["result_sha256"] = forged_digest
    object.__setattr__(artifact, "result_sha256", forged_digest)
    object.__setattr__(artifact, "result_json", _canonical_json(forged))
    with pytest.raises(
        CanonicalFeatureValueResolverV4Error,
        match="CANONICAL_FEATURE_RESOLVER_V4_AUTHORITY_INVALID",
    ):
        _ = artifact.result

    clean = resolve_canonical_feature_value_v4(
        ordinal=slot.ordinal,
        symbol="BTCUSDT",
        request_timeframe="5m",
        decision_time=DECISION,
        source_records={record_id: record},
    )
    mismatched = clean.result
    mismatched["result_sha256"] = "0" * 64
    object.__setattr__(clean, "result_json", _canonical_json(mismatched))
    with pytest.raises(
        CanonicalFeatureValueResolverV4Error,
        match="CANONICAL_FEATURE_RESOLVER_V4_RESULT_BINDING_INVALID",
    ):
        _ = clean.result


def test_rehashed_full_audit_cannot_forge_live_authority() -> None:
    artifact = resolve_canonical_feature_values_v4(
        symbol="BTCUSDT",
        request_timeframe="5m",
        decision_time=DECISION,
        source_records={},
    )
    with pytest.raises(AttributeError):
        object.__setattr__(artifact, "live_execution_authorized", True)
    assert artifact.live_execution_authorized is False
    pristine = artifact.audit
    forged = deepcopy(pristine)
    forged["live_execution_authorized"] = True
    forged_digest = _digest_without(forged, "audit_sha256")
    forged["audit_sha256"] = forged_digest
    object.__setattr__(artifact, "audit_sha256", forged_digest)
    object.__setattr__(artifact, "audit_json", _canonical_json(forged))
    with pytest.raises(
        CanonicalFeatureValueResolverV4Error,
        match="CANONICAL_FEATURE_RESOLVER_V4_AUTHORITY_INVALID",
    ):
        _ = artifact.audit

    invalid_summaries = []
    bool_count = deepcopy(pristine)
    bool_count["resolved_measured_slot_count"] = False
    invalid_summaries.append(bool_count)
    float_slot_count = deepcopy(pristine)
    float_slot_count["slot_count"] = 446.0
    invalid_summaries.append(float_slot_count)
    float_status_count = deepcopy(pristine)
    first_status = next(iter(float_status_count["resolution_status_counts"]))
    float_status_count["resolution_status_counts"][first_status] = float(
        float_status_count["resolution_status_counts"][first_status]
    )
    invalid_summaries.append(float_status_count)
    for invalid in invalid_summaries:
        invalid_digest = _digest_without(invalid, "audit_sha256")
        invalid["audit_sha256"] = invalid_digest
        object.__setattr__(artifact, "audit_sha256", invalid_digest)
        object.__setattr__(artifact, "audit_json", _canonical_json(invalid))
        with pytest.raises(
            CanonicalFeatureValueResolverV4Error,
            match="CANONICAL_FEATURE_RESOLVER_V4_AUDIT_SUMMARY_TYPE_INVALID",
        ):
            _ = artifact.audit


def test_global_plan_object_setattr_tamper_is_rejected_before_resolution() -> None:
    slot = FEATURE_RESOLUTION_PLAN_V4.slots[0]
    original_name = slot.feature_name
    try:
        object.__setattr__(slot, "feature_name", "forged_feature_name")
        with pytest.raises(
            FeatureResolutionPlanV4ValidationError,
            match="FEATURE_RESOLUTION_PLAN_V4_(REGISTRY_BINDING_MISMATCH|SHA256_INVALID)",
        ):
            resolve_canonical_feature_value_v4(
                ordinal=0,
                symbol="BTCUSDT",
                request_timeframe="5m",
                decision_time=DECISION,
                source_records={},
            )
    finally:
        object.__setattr__(slot, "feature_name", original_name)
