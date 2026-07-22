from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import zlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from v2.backend.app.services import binance_usdm_leverage_bracket_evidence as bracket_mod
from v2.backend.app.services.liquidation_surface.publication import (
    SurfacePublicationValidationError,
    build_surface_publication_security_context,
    derive_publication_scope_sha256,
    publish_liquidation_surface,
)
from v2.backend.app.services.liquidation_surface.source_adapters import RawRedisEvidence
from v2.backend.app.services.liquidation_surface.trainer_admission import (
    SOURCE_FAMILY_ORDER,
    TrainerAdmissionIntegrityError,
    TrainerAdmissionValidationError,
    build_trainer_admission_security_context,
    build_trainer_decision_context,
    evaluate_liquidation_surface_trainer_admission,
    prepare_liquidation_surface_candidate,
    publication_mapping_with_prepared_source_bundle,
    reopen_prepared_source_bundle_from_publication,
)
from v2.backend.tests.unit.services.liquidation_surface.test_publication import FakeRedis

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
BASE_MS = 1_800_000_000_000
DURATION_MS = 300_000
AS_OF_MS = BASE_MS + 902_000
GENERATED_AT_MS = AS_OF_MS + 100
FEATURE_ABI_SHA256 = "f" * 64
ADMISSION_HMAC_KEY = b"trainer-admission-test-key-material-0001"
PUBLICATION_HMAC_KEY = b"surface-publication-admission-test-key-01"
BRACKET_HMAC_KEY = b"bracket-reader-test-key-material-000001"


def _dt(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1_000, tz=UTC)


BRACKET_SECURITY = bracket_mod.build_evidence_security_context(
    trader_id="trainer-test",
    credential_ref="TRAINER_BINANCE_READONLY",
    base_url=bracket_mod.MAINNET_BASE_URL,
    credential_account_specific=True,
    hmac_key=BRACKET_HMAC_KEY,
    auth_key_id="trainer-bracket-evidence-v1",
)


class BracketRedis:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get(self, _key: str) -> str | None:
        return self.value


def _bracket_payload() -> dict[str, Any]:
    return bracket_mod.build_symbol_evidence(
        {
            "symbol": SYMBOL,
            "brackets": [
                {
                    "bracket": 1,
                    "initialLeverage": 20,
                    "notionalFloor": 0,
                    "notionalCap": 1_000_000_000,
                    "maintMarginRatio": 0.004,
                    "cum": 0,
                }
            ],
        },
        security_context=BRACKET_SECURITY,
        fetched_at=_dt(AS_OF_MS - 2_000),
        generated_at=_dt(AS_OF_MS - 1_990),
        ingested_at=_dt(AS_OF_MS - 1_980),
        available_at=_dt(AS_OF_MS - 1_970),
        freshness_seconds=600,
        cache_ttl_seconds=900,
    )


def _bracket_redis(*, present: bool = True, payload: dict[str, Any] | None = None) -> BracketRedis:
    value = payload if payload is not None else _bracket_payload()
    return BracketRedis(json.dumps(value, sort_keys=True) if present else None)


def _raw(value: object, *, whitespace: bool = False) -> bytes:
    return json.dumps(
        value,
        sort_keys=not whitespace,
        indent=1 if whitespace else None,
        separators=None if whitespace else (",", ":"),
    ).encode("utf-8")


def _evidence(
    key: str,
    value: object,
    *,
    observed_at_ms: int,
    whitespace: bool = False,
) -> RawRedisEvidence:
    return RawRedisEvidence.from_value(
        key=key,
        value=_raw(value, whitespace=whitespace),
        consumer_observed_at_ms=observed_at_ms,
    )


def _candle_payload() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(3):
        open_time = BASE_MS + index * DURATION_MS
        close_time = open_time + DURATION_MS - 1
        rows.append(
            {
                "symbol": SYMBOL,
                "exchange": "binance",
                "venue": "binance_usdm",
                "product_type": "USD-M",
                "timeframe": TIMEFRAME,
                "candle_open_time": open_time,
                "candle_close_time": close_time,
                "event_time": close_time,
                "ingested_at": close_time + 10,
                "available_at": close_time + 20,
                "is_closed": True,
                "closed_candle": True,
                "candle_closed_confirmed": True,
                "feature_eligible": True,
                "source": "binance_wss",
                "raw_payload_hash": f"{index + 1:064x}",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100",
                "quote_volume": "10000",
                "taker_buy_quote_vol": "6000",
            }
        )
    return rows


def _candle_evidence(*, whitespace: bool = False) -> RawRedisEvidence:
    return _evidence(
        f"v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}",
        _candle_payload(),
        observed_at_ms=BASE_MS + 900_500,
        whitespace=whitespace,
    )


def _mark_evidence(
    *,
    bad_symbol: bool = False,
    event_times: tuple[int, int] | None = None,
) -> tuple[RawRedisEvidence, ...]:
    observations = []
    for event_time in event_times or (AS_OF_MS - 1_000, AS_OF_MS - 100):
        observations.append(
            _evidence(
                f"v2:market:mark_price:{SYMBOL}",
                {
                    "schema_version": "binance_usdm_mark_price_wss_v1",
                    "symbol": "ETHUSDT" if bad_symbol else SYMBOL,
                    "venue": "binance_usdm",
                    "product_type": "USD-M",
                    "source": "binance_usdm_wss_mark_price_all_symbols",
                    "transport": "websocket_primary",
                    "event_time": event_time,
                    "available_at": event_time + 10,
                    "markPrice": "100",
                },
                observed_at_ms=event_time + 20,
            )
        )
    return tuple(observations)


def _oi_evidence(
    *,
    wrong_endpoint: bool = False,
    source_timeframe: str = TIMEFRAME,
) -> RawRedisEvidence:
    request_started = BASE_MS + 900_500
    source_duration_ms = {
        "5m": 300_000,
        "15m": 900_000,
    }[source_timeframe]
    latest_aligned_begin = BASE_MS + 900_000
    payload = {
        "ts_ms": request_started + 100,
        "request_started_at_ms": request_started,
        "symbol": SYMBOL,
        "exchange": "Binance",
        "family": "open_interest",
        "endpoint": "liquidationHeatmap" if wrong_endpoint else "openInterest_kline",
        "interval": source_timeframe,
        "request_parameters": {
            "exchange": "Binance",
            "symbol": SYMBOL,
            "interval": source_timeframe,
            "productType": "SWAP",
            "size": 15,
        },
        "data": {
            "success": True,
            "code": "1",
            "data": [
                {
                    "begin": latest_aligned_begin - 2 * source_duration_ms,
                    "close": "100",
                },
                {
                    "begin": latest_aligned_begin - source_duration_ms,
                    "close": "120",
                },
                {"begin": latest_aligned_begin, "close": "140"},
            ],
        },
    }
    return _evidence(
        f"latest:coinank:open_interest:{SYMBOL}:{source_timeframe}",
        payload,
        observed_at_ms=BASE_MS + 900_700,
    )


def _prepared(
    *,
    candle: RawRedisEvidence | None = None,
    marks: tuple[RawRedisEvidence, ...] | None = None,
    oi: RawRedisEvidence | None = None,
    bracket_present: bool = True,
    candle_whitespace: bool = False,
):
    return prepare_liquidation_surface_candidate(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        as_of_time_ms=AS_OF_MS,
        generated_at_ms=GENERATED_AT_MS,
        candle_evidence=(
            _candle_evidence(whitespace=candle_whitespace) if candle is None else candle
        ),
        mark_price_evidence=_mark_evidence() if marks is None else marks,
        open_interest_evidence=_oi_evidence() if oi is None else oi,
        bracket_redis_client=_bracket_redis(present=bracket_present),
        bracket_security_context=BRACKET_SECURITY,
        bracket_now_fn=lambda: _dt(AS_OF_MS - 50),
    )


def _publication_context(prepared, *, metadata: dict[str, Any] | None = None):
    return build_surface_publication_security_context(
        scope_metadata=(
            dict(prepared.publication_scope_metadata) if metadata is None else metadata
        ),
        hmac_key=PUBLICATION_HMAC_KEY,
        auth_key_id="surface-publication-admission-v1",
    )


def _publish(prepared, *, metadata: dict[str, Any] | None = None):
    client = FakeRedis(now_ms=GENERATED_AT_MS + 200)
    publication = publish_liquidation_surface(
        client,
        publication_mapping_with_prepared_source_bundle(prepared),
        security_context=_publication_context(prepared, metadata=metadata),
    )
    return client, publication


def _security():
    return build_trainer_admission_security_context(
        auth_key_id="trainer-admission-test-v1",
        hmac_key=ADMISSION_HMAC_KEY,
    )


def _decision(
    publication,
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    abi: str = FEATURE_ABI_SHA256,
):
    return build_trainer_decision_context(
        decision_id="decision-1",
        decision_time_ms=publication.consumer_reopened_at_ms + 10,
        symbol=symbol,
        timeframe=timeframe,
        feature_abi_sha256=abi,
    )


def _admit(publication, prepared, *, decision=None):
    context = _decision(publication) if decision is None else decision
    return evaluate_liquidation_surface_trainer_admission(
        publication,
        prepared,
        decision_context=context,
        admission_security_context=_security(),
        now_ms_fn=lambda: publication.consumer_reopened_at_ms + 1,
    )


def test_preparation_derives_all_sources_scope_and_fixed_manifest_from_factories() -> None:
    prepared = _prepared()

    assert prepared.feature_ready is True
    assert prepared.required_mask == (True, True, True, True, False)
    assert prepared.available_mask == (True, True, True, True, False)
    assert prepared.missing_mask == (False, False, False, False, False)
    assert prepared.authenticated_mask == (True, True, True, True, False)
    assert prepared.degraded_mask == (False, False, False, False, False)
    assert prepared.publication_scope_sha256 == derive_publication_scope_sha256(
        prepared.publication_scope_metadata
    )
    assert prepared.request.candles[0].source_sha256 == hashlib.sha256(
        _candle_evidence().raw
    ).hexdigest()
    assert prepared.request.leverage_brackets[0].source_key.startswith(
        bracket_mod.REDIS_KEY_PREFIX
    )


def test_preparation_api_has_no_caller_request_authentication_or_scope_assertions() -> None:
    parameters = inspect.signature(prepare_liquidation_surface_candidate).parameters

    assert "request" not in parameters
    assert "source_authentication" not in parameters
    assert "bracket_safe_metadata_sha256" not in parameters
    assert "publication_scope_sha256" not in parameters


def test_happy_admission_is_exact_identity_scoped_and_never_trade_authority() -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)

    assert publication.trainer_authority is False
    assert admitted.feature_available is True
    assert admitted.trainer_authority is True
    assert admitted.symbol == SYMBOL
    assert admitted.timeframe == TIMEFRAME
    assert admitted.feature_abi_sha256 == FEATURE_ABI_SHA256
    assert admitted.is_authorized_for(
        decision_id="decision-1",
        decision_time_ms=admitted.decision_time_ms,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        feature_abi_sha256=FEATURE_ABI_SHA256,
    )
    assert admitted.prediction_authority is False
    assert admitted.paper_trading_authority is False
    assert admitted.live_execution_authority is False


def test_verified_publication_reopens_exact_prepared_source_bytes() -> None:
    prepared = _prepared()
    publication_payload = publication_mapping_with_prepared_source_bundle(prepared)
    candle_bundle = publication_payload["trainer_source_bundle"]["snapshot"][
        "candle_evidence"
    ]
    assert candle_bundle["encoding"] == "zlib_base64_v1"
    assert candle_bundle["compressed_byte_count"] < candle_bundle["raw_byte_count"]
    assert "raw_base64" not in candle_bundle
    _client, publication = _publish(prepared)

    reopened = reopen_prepared_source_bundle_from_publication(publication)

    assert reopened.manifest_sha256 == prepared.manifest_sha256
    assert reopened.candidate_archive_payload_sha256 == (
        prepared.candidate_archive_payload_sha256
    )
    assert reopened.request == prepared.request
    assert _admit(publication, reopened).feature_available is True


def test_verified_publication_rejects_rehashed_but_wrong_compressed_source_bytes() -> None:
    prepared = _prepared()
    payload = publication_mapping_with_prepared_source_bundle(prepared)
    bundle = payload["trainer_source_bundle"]
    candle_bundle = bundle["snapshot"]["candle_evidence"]
    wrong = zlib.compress(b"{}", level=9)
    candle_bundle["compressed_base64"] = base64.b64encode(wrong).decode("ascii")
    candle_bundle["compressed_byte_count"] = len(wrong)
    unsigned = dict(bundle)
    unsigned.pop("bundle_sha256")
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    publication = publish_liquidation_surface(
        FakeRedis(now_ms=GENERATED_AT_MS + 200),
        payload,
        security_context=_publication_context(prepared),
    )

    with pytest.raises(
        TrainerAdmissionValidationError,
        match="CANDLE_SOURCE_BUNDLE_EVIDENCE_HASH_INVALID",
    ):
        reopen_prepared_source_bundle_from_publication(publication)


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("decision_id", "another-decision"),
        ("decision_time_ms", GENERATED_AT_MS + 999),
        ("symbol", "ETHUSDT"),
        ("timeframe", "15m"),
        ("feature_abi_sha256", "e" * 64),
    ],
)
def test_authorization_helper_rejects_every_identity_or_abi_mismatch(
    changed: str,
    value: object,
) -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)
    arguments: dict[str, object] = {
        "decision_id": admitted.decision_id,
        "decision_time_ms": admitted.decision_time_ms,
        "symbol": admitted.symbol,
        "timeframe": admitted.timeframe,
        "feature_abi_sha256": admitted.feature_abi_sha256,
    }
    arguments[changed] = value

    assert admitted.is_authorized_for(**arguments) is False  # type: ignore[arg-type]


def test_admission_receipt_sha_and_hmac_bind_all_exposed_authority_fields() -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)
    receipt = dict(admitted.admission_receipt)
    observed_hmac = receipt.pop("admission_receipt_hmac_sha256")
    observed_sha = receipt.pop("admission_receipt_sha256")

    assert receipt["symbol"] == admitted.symbol
    assert receipt["timeframe"] == admitted.timeframe
    assert receipt["feature_abi_sha256"] == admitted.feature_abi_sha256
    assert tuple(receipt["required_mask"]) == admitted.required_mask
    assert tuple(receipt["degraded_mask"]) == admitted.degraded_mask
    assert observed_sha == hashlib.sha256(
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    receipt["admission_receipt_sha256"] = observed_sha
    assert observed_hmac == hmac.new(
        ADMISSION_HMAC_KEY,
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifest_sha256", "e" * 64),
        ("feature_ready", False),
        ("available_mask", (False, True, True, True, False)),
        ("candidate_archive_payload_sha256", "d" * 64),
    ],
)
def test_dataclasses_replace_cannot_modify_prepared_candidate(field: str, value: object) -> None:
    prepared = _prepared()

    with pytest.raises(
        TrainerAdmissionValidationError,
        match="PREPARED_SURFACE_CANONICAL_INTEGRITY_INVALID",
    ):
        replace(prepared, **{field: value})


def test_dataclasses_replace_cannot_modify_manifest_leaf() -> None:
    leaf = _prepared().source_manifest[0]

    with pytest.raises(
        TrainerAdmissionValidationError,
        match="SOURCE_MANIFEST_LEAF_FACTORY_OR_HASH_INVALID",
    ):
        replace(leaf, row_count=leaf.row_count + 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_id", "forged-decision"),
        ("feature_abi_sha256", "e" * 64),
        ("trainer_authority_reason", "FORGED"),
        ("degraded_mask", (True, False, False, False, False)),
        ("surface_publication_receipt_sha256", "d" * 64),
    ],
)
def test_dataclasses_replace_cannot_modify_admission_result(field: str, value: object) -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)

    with pytest.raises(
        TrainerAdmissionValidationError,
        match="TRAINER_ADMISSION_RESULT_CANONICAL_INTEGRITY_INVALID",
    ):
        replace(admitted, **{field: value})


def test_changed_raw_leaf_rederivation_cannot_bind_an_existing_publication() -> None:
    original = _prepared()
    _client, publication = _publish(original)
    changed = _prepared(candle_whitespace=True)

    with pytest.raises(
        TrainerAdmissionIntegrityError,
        match="PUBLICATION_PREPARED_MODEL_HASH_BINDING_MISMATCH",
    ):
        _admit(publication, changed)


def test_wrong_publication_scope_cannot_override_reader_derived_scope() -> None:
    prepared = _prepared()
    metadata = {
        **dict(prepared.publication_scope_metadata),
        "credential_binding_id": "mainnet:trainer-test:OTHER_BINANCE_READONLY",
    }
    with pytest.raises(
        SurfacePublicationValidationError,
        match="SURFACE_PREPARED_SOURCE_BUNDLE_SCOPE_MISMATCH",
    ):
        _publish(prepared, metadata=metadata)


def test_decision_symbol_or_timeframe_mismatch_fails_before_authority() -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)
    wrong = _decision(publication, symbol="ETHUSDT")

    with pytest.raises(
        TrainerAdmissionValidationError,
        match="ADMISSION_DECISION_IDENTITY_MISMATCH",
    ):
        _admit(publication, prepared, decision=wrong)


def test_missing_authenticated_brackets_produce_fixed_mask_and_no_feature_payload() -> None:
    prepared = _prepared(bracket_present=False)
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)
    index = SOURCE_FAMILY_ORDER.index("leverage_brackets")

    assert prepared.available_mask[index] is False
    assert prepared.missing_mask[index] is True
    assert prepared.authenticated_mask[index] is False
    assert admitted.feature_available is False
    assert admitted.trainer_authority is False
    assert admitted.surface_payload is None
    assert "SOURCE_MISSING:leverage_brackets" in admitted.rejection_reasons


def test_invalid_mark_bytes_are_degraded_and_never_zero_filled() -> None:
    prepared = _prepared(marks=_mark_evidence(bad_symbol=True))
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)
    index = SOURCE_FAMILY_ORDER.index("mark_price")

    assert prepared.request.mark_prices == ()
    assert prepared.available_mask[index] is False
    assert prepared.missing_mask[index] is True
    assert prepared.degraded_mask[index] is True
    assert admitted.surface_payload is None
    assert any(
        reason.startswith("SOURCE_DEGRADED:mark_price:SOURCE_ADAPTER_REJECTED")
        for reason in admitted.rejection_reasons
    )


def test_adaptively_stale_mark_evidence_is_masked_without_static_threshold() -> None:
    marks = _mark_evidence(
        event_times=(AS_OF_MS - 20_000, AS_OF_MS - 19_000),
    )
    prepared = _prepared(marks=marks)
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)
    index = SOURCE_FAMILY_ORDER.index("mark_price")

    assert prepared.available_mask[index] is True
    assert prepared.authenticated_mask[index] is True
    assert prepared.degraded_mask[index] is True
    assert prepared.source_manifest[index].degradation_reason == (
        "ADAPTIVE_SOURCE_FRESHNESS_REJECTED"
    )
    assert prepared.candidate_payload["adaptive_freshness_evidence"][  # type: ignore[index]
        "static_market_threshold_used"
    ] is False
    assert admitted.feature_available is False
    assert admitted.surface_payload is None


def test_unsupported_coinank_heatmap_endpoint_is_rejected_by_strict_oi_adapter() -> None:
    prepared = _prepared(oi=_oi_evidence(wrong_endpoint=True))
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)
    index = SOURCE_FAMILY_ORDER.index("open_interest")

    assert prepared.request.open_interest == ()
    assert prepared.missing_mask[index] is True
    assert prepared.degraded_mask[index] is True
    assert admitted.surface_payload is None


def test_oi_source_timeframe_is_derived_from_exact_key_not_surface_lane() -> None:
    prepared = _prepared(oi=_oi_evidence(source_timeframe="15m"))

    assert prepared.request.timeframe == "5m"
    assert {row.timeframe for row in prepared.request.open_interest} == {"15m"}
    assert prepared.candidate_payload is not None
    assert prepared.candidate_payload["open_interest_source_timeframe"] == "15m"


def test_verified_publication_exposed_field_replacement_is_rejected_before_admission() -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)

    with pytest.raises(
        SurfacePublicationValidationError,
        match="VERIFIED_SURFACE_AUTHORITY_OR_CLOCK_INVALID",
    ):
        replace(publication, surface_id=f"v2_lsurf_{'e' * 64}")


def test_prepared_and_admitted_json_trees_are_deeply_immutable() -> None:
    prepared = _prepared()
    _client, publication = _publish(prepared)
    admitted = _admit(publication, prepared)

    with pytest.raises(TypeError):
        prepared.candidate_payload["current_price"] = 1.0  # type: ignore[index]
    with pytest.raises(AttributeError):
        prepared.candidate_payload["long_levels"].append({"price": 1.0})  # type: ignore[union-attr]
    with pytest.raises(TypeError):
        admitted.admission_receipt["trainer_authority"] = False  # type: ignore[index]
    with pytest.raises(TypeError):
        admitted.surface_payload["current_price"] = 1.0  # type: ignore[index,union-attr]
