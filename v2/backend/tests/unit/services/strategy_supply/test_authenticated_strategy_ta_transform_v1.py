from __future__ import annotations

import copy
import inspect
import json
import math
import os
import shutil
import subprocess
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import redis

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    atomic_merge_closed_window,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_bound_atomic_capture_v1 import (
    capture_canonical_ohlcv_writer_bound_atomic,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_receipt_consumer_v1 import (
    BINANCE_REST_WRITER_ROLE,
    BINANCE_WSS_WRITER_ROLE,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    ModelTATechnicalDependencyContract,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.strategy_supply import (
    authenticated_strategy_ta_transform_v1 as transform_module,
)
from v2.backend.app.services.strategy_supply.authenticated_strategy_ta_transform_v1 import (
    EXPLICITLY_EXCLUDED_MUTABLE_INPUTS,
    EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS,
    REQUIRED_STRATEGY_TA_INDICATORS,
    AuthenticatedStrategyTaTransformV1IntegrityError,
    AuthenticatedStrategyTaTransformV1ValidationError,
    transform_writer_bound_ohlcv_to_strategy_ta_v1,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "4h"
CANONICAL_KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:4h"
WSS_CODE_SHA256 = "1" * 64
REST_CODE_SHA256 = "2" * 64
CONFIG_A_SHA256 = "3" * 64
CONFIG_B_SHA256 = "4" * 64
MUTABLE_TTL_SECONDS = 86_400
RECEIPT_TTL_SECONDS = 43_200
ARCHIVE_TTL_SECONDS = 57_600
SOURCE_ROW_COUNT = 100
CALCULATION_ROW_COUNT = 89
EXPECTED_INDICATOR_COUNT = 219
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_AUTHORITY_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "strategy_output_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
)
_ORDERED_CLOCK_FIELDS = (
    "feature_cutoff",
    "max_producer_event_time",
    "max_ingested_at",
    "max_source_available_at",
    "writer_publication_available_at",
    "pre_writer_discovery_observed_at",
    "pre_writer_authoritative_observed_at",
    "pre_writer_consumer_observed_at",
    "atomic_server_observed_at",
    "atomic_consumer_observed_at",
    "post_writer_discovery_observed_at",
    "post_writer_authoritative_observed_at",
    "post_writer_consumer_observed_at",
    "capture_generated_at",
    "transform_generated_at",
)


@dataclass(frozen=True, slots=True)
class _UnitMaterial:
    capture: Any
    source_store: ImmutableSourcePayloadStore
    window: Any
    candidate: dict[str, Any]
    contract: ModelTATechnicalDependencyContract
    result: Any


def _allowlist() -> dict[str, tuple[str, ...]]:
    return {
        BINANCE_WSS_WRITER_ROLE: (WSS_CODE_SHA256,),
        BINANCE_REST_WRITER_ROLE: (REST_CODE_SHA256,),
    }


def _clock(value: str) -> datetime:
    return datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)


def _after_capture_clock(capture: Any, *, offset_ms: int = 1) -> Any:
    observed = _clock(capture.generated_at) + timedelta(milliseconds=offset_ms)
    return lambda: observed


def _rows(*, source: str) -> list[dict[str, Any]]:
    duration_ms = TIMEFRAME_DURATION_MS[TIMEFRAME]
    now_ms = int(time.time() * 1_000)
    latest_close = (now_ms // duration_ms) * duration_ms - 1
    first_open = latest_close + 1 - SOURCE_ROW_COUNT * duration_ms
    rows: list[dict[str, Any]] = []
    for index in range(SOURCE_ROW_COUNT):
        open_time = first_open + index * duration_ms
        close_time = open_time + duration_ms - 1
        base = 100.0 + index * 0.17 + ((index % 7) - 3) * 0.04
        opening = base
        closing = base + 0.22 + ((index % 5) - 2) * 0.03
        high = max(opening, closing) + 1.15 + (index % 3) * 0.02
        low = min(opening, closing) - 0.95 - (index % 4) * 0.02
        volume = 12.0 + (index % 11) * 0.4
        quote_volume = volume * closing
        if source == "wss":
            message = {
                "E": close_time,
                "s": SYMBOL,
                "k": {
                    "t": open_time,
                    "T": close_time,
                    "s": SYMBOL,
                    "i": TIMEFRAME,
                    "o": f"{opening:.8f}",
                    "h": f"{high:.8f}",
                    "l": f"{low:.8f}",
                    "c": f"{closing:.8f}",
                    "v": f"{volume:.8f}",
                    "q": f"{quote_volume:.8f}",
                    "n": 100 + index,
                    "V": f"{volume * 0.51:.8f}",
                    "Q": f"{quote_volume * 0.51:.8f}",
                    "x": True,
                },
            }
            row = canonical_from_binance_wss(
                message,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                ingested_at=close_time + 1,
            )
        elif source == "rest":
            raw = [
                open_time,
                f"{opening:.8f}",
                f"{high:.8f}",
                f"{low:.8f}",
                f"{closing:.8f}",
                f"{volume:.8f}",
                close_time,
                f"{quote_volume:.8f}",
                100 + index,
                f"{volume * 0.51:.8f}",
                f"{quote_volume * 0.51:.8f}",
                "0",
            ]
            row = canonical_from_binance_rest(
                raw,
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                ingested_at=close_time + 1,
            )
        else:  # pragma: no cover - test helper misuse
            raise AssertionError(f"unknown source: {source}")
        rows.append(row.to_dict())
    return rows


def _publish(
    client: redis.Redis,
    *,
    rows: list[dict[str, Any]],
    producer_role: str,
    producer_code_sha256: str,
    producer_config_sha256: str = CONFIG_A_SHA256,
) -> Any:
    return atomic_merge_closed_window(
        client,
        redis_key=CANONICAL_KEY,
        new_rows=tuple(rows),
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
        receipt_ttl_seconds=RECEIPT_TTL_SECONDS,
        archive_ttl_seconds=ARCHIVE_TTL_SECONDS,
        ttl_policy="set",
        ttl_seconds=MUTABLE_TTL_SECONDS,
    )


def _capture(
    client: redis.Redis,
    store_root: Path,
) -> tuple[Any, ImmutableSourcePayloadStore]:
    store = ImmutableSourcePayloadStore(store_root)
    capture = capture_canonical_ohlcv_writer_bound_atomic(
        client,
        store,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        trusted_writer_code_sha256_by_role=_allowlist(),
    )
    return capture, store


def _transform(
    capture: Any,
    store_root: Path,
    *,
    offset_ms: int = 1,
) -> tuple[Any, ImmutableSourcePayloadStore]:
    store = ImmutableSourcePayloadStore(store_root)
    result = transform_writer_bound_ohlcv_to_strategy_ta_v1(
        capture,
        store,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        consumer_clock=_after_capture_clock(capture, offset_ms=offset_ms),
    )
    return result, store


def _fast_transform(
    monkeypatch: pytest.MonkeyPatch,
    material: _UnitMaterial,
    store_root: Path,
    *,
    candidate: Mapping[str, Any] | None = None,
) -> tuple[Any, ImmutableSourcePayloadStore]:
    candidate_value = copy.deepcopy(material.candidate if candidate is None else dict(candidate))
    monkeypatch.setattr(
        transform_module,
        "_validated_technical_contract",
        lambda: material.contract,
    )
    monkeypatch.setattr(
        transform_module.full_talib_service,
        "build_full_talib_ta_closed_candidate",
        lambda *, validated_window: copy.deepcopy(candidate_value),
    )
    return _transform(material.capture, store_root)


def _corrupt(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
) -> None:
    payload = store.get(
        address.payload_sha256,
        expected_byte_count=address.payload_byte_count,
    )
    path = store.path_for(address.payload_sha256)
    os.chmod(path, 0o600)
    path.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
    os.chmod(path, 0o400)


def _mapping_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str):
                keys.add(key)
            keys.update(_mapping_keys(nested))
    elif isinstance(value, list | tuple):
        for nested in value:
            keys.update(_mapping_keys(nested))
    return keys


@pytest.fixture(scope="module")
def redis_socket(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for authenticated strategy TA tests")
    root = tmp_path_factory.mktemp("authenticated-strategy-ta-redis")
    socket_path = str(root / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local executable/arguments
        [
            executable,
            "--port",
            "0",
            "--save",
            "",
            "--appendonly",
            "no",
            "--unixsocket",
            socket_path,
            "--unixsocketperm",
            "700",
            "--dir",
            str(root),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            probe = redis.Redis(
                unix_socket_path=socket_path,
                decode_responses=False,
            )
            if probe.ping():
                break
        except (OSError, redis.RedisError):
            time.sleep(0.02)
    else:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("ephemeral redis-server did not become ready")
    try:
        yield socket_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture()
def raw_client(redis_socket: str) -> redis.Redis:
    client = redis.Redis(
        unix_socket_path=redis_socket,
        decode_responses=False,
    )
    client.flushdb()
    return client


@pytest.fixture(scope="module")
def unit_material(
    redis_socket: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> _UnitMaterial:
    client = redis.Redis(
        unix_socket_path=redis_socket,
        decode_responses=False,
    )
    client.flushdb()
    _publish(
        client,
        rows=_rows(source="wss"),
        producer_role=BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=WSS_CODE_SHA256,
    )
    root = tmp_path_factory.mktemp("authenticated-strategy-ta-unit")
    capture, source_store = _capture(client, root / "source")
    _, window = transform_module._validated_source_capture(capture)
    contract = transform_module._validated_technical_contract()
    candidate = transform_module.full_talib_service.build_full_talib_ta_closed_candidate(
        validated_window=window,
    )
    result, _ = _transform(capture, root / "output")
    return _UnitMaterial(
        capture=capture,
        source_store=source_store,
        window=window,
        candidate=candidate,
        contract=contract,
        result=result,
    )


# 19 focused unit cases. The authentic source fixture is created once; these
# cases do not repeat the already-proven writer/atomic race atlas.


def test_unit_exact_final_89_from_100_atomic_receipts(
    unit_material: _UnitMaterial,
) -> None:
    capture = unit_material.capture
    result = unit_material.result
    atomic = capture.atomic_capture
    semantic_source = result.semantic_content["source_semantics"]
    strategy_ta = result.semantic_content["strategy_ta"]

    assert capture.row_count == SOURCE_ROW_COUNT
    assert atomic.selected_row_count == SOURCE_ROW_COUNT
    assert len(atomic.source_read_receipts) == SOURCE_ROW_COUNT
    assert result.calculation_row_count == CALCULATION_ROW_COUNT
    assert semantic_source["calculation_row_count"] == CALCULATION_ROW_COUNT
    assert len(semantic_source["calculation_window_candle_ids"]) == (CALCULATION_ROW_COUNT)
    assert semantic_source["calculation_window_candle_ids"] == list(
        atomic.selected_candle_ids[-CALCULATION_ROW_COUNT:]
    )
    assert len(semantic_source["calculation_window_exact_payload_sha256s"]) == (
        CALCULATION_ROW_COUNT
    )
    assert (
        strategy_ta["calculation_window_first_candle_id"]
        == (atomic.selected_candle_ids[-CALCULATION_ROW_COUNT])
    )
    assert strategy_ta["calculation_window_latest_candle_id"] == (atomic.selected_candle_ids[-1])


def test_unit_required_indicators_and_same_candle_reference_price(
    unit_material: _UnitMaterial,
) -> None:
    result = unit_material.result
    indicators = result.indicators
    reference = result.semantic_content["strategy_ta"]["reference_price_input"]
    latest = unit_material.window.rows[-1]

    assert result.indicator_count == EXPECTED_INDICATOR_COUNT
    assert set(REQUIRED_STRATEGY_TA_INDICATORS).issubset(indicators)
    assert all(math.isfinite(indicators[name]) for name in REQUIRED_STRATEGY_TA_INDICATORS)
    assert result.reference_price == float(latest.close)
    assert reference["price"] == float(latest.close)
    assert reference["selected_candle_id"] == latest.candle_id
    assert reference["selected_candle_raw_payload_hash"] == latest.raw_payload_hash
    assert reference["source_exact_payload_sha256"] == result.exact_payload_sha256


def test_unit_audit_orders_fifteen_clocks_and_keeps_three_null(
    unit_material: _UnitMaterial,
) -> None:
    timestamps = unit_material.result.audit_manifest["timestamps"]
    chain = tuple(_clock(timestamps[name]) for name in _ORDERED_CLOCK_FIELDS)

    assert len(chain) == 15
    assert all(earlier <= later for earlier, later in pairwise(chain))
    assert timestamps["available_at"] is None
    assert timestamps["decision_time"] is None
    assert timestamps["execution_time"] is None
    assert unit_material.result.available_at is None
    assert unit_material.result.decision_time is None
    assert unit_material.result.execution_time is None


def test_unit_all_authority_and_external_economics_remain_false(
    unit_material: _UnitMaterial,
) -> None:
    result = unit_material.result
    semantic = result.semantic_content
    audit = result.audit_manifest

    assert all(getattr(result, name) is False for name in _AUTHORITY_FIELDS)
    assert all(semantic["authorization"][name] is False for name in _AUTHORITY_FIELDS)
    assert all(audit[name] is False for name in _AUTHORITY_FIELDS)
    assert result.runtime_wired is False
    assert result.unreceipted_external_economics_consumed is False
    assert result.market_performance_thresholds_applied is False
    assert semantic["external_input_policy"] == {
        "unreceipted_inputs_consumed": [],
        "explicitly_excluded_mutable_inputs": ["v2:live_gate:state"],
        "explicitly_excluded_optional_provider_groups": list(
            EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS
        ),
        "reference_notional_consumed": False,
        "paper_account_consumed": False,
        "zero_fill_used": False,
    }
    assert audit["market_performance_thresholds"] == []


def test_unit_public_signature_has_no_redis_or_mutable_economics_argument() -> None:
    signature = inspect.signature(transform_writer_bound_ohlcv_to_strategy_ta_v1)
    source = inspect.getsource(transform_writer_bound_ohlcv_to_strategy_ta_v1)

    assert tuple(signature.parameters) == (
        "source_capture",
        "source_payload_store",
        "expected_symbol",
        "expected_timeframe",
        "consumer_clock",
    )
    assert not {
        "client",
        "redis_client",
        "live_gate_state",
        "reference_notional",
        "risk_profile",
    }.intersection(signature.parameters)
    assert "v2:live_gate:state" not in source
    assert "client.get" not in source
    assert EXPLICITLY_EXCLUDED_MUTABLE_INPUTS == ("v2:live_gate:state",)


def test_unit_requires_factory_authenticated_capture(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        AuthenticatedStrategyTaTransformV1ValidationError,
        match="authenticated_strategy_ta_writer_bound_capture_required",
    ):
        transform_writer_bound_ohlcv_to_strategy_ta_v1(
            object(),  # type: ignore[arg-type]
            ImmutableSourcePayloadStore(tmp_path / "output"),
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
        )


def test_unit_requires_authentic_immutable_store(
    unit_material: _UnitMaterial,
) -> None:
    with pytest.raises(
        AuthenticatedStrategyTaTransformV1ValidationError,
        match="authenticated_strategy_ta_authentic_store_required",
    ):
        transform_writer_bound_ohlcv_to_strategy_ta_v1(
            unit_material.capture,
            object(),  # type: ignore[arg-type]
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
        )


def test_unit_rejects_requested_symbol_substitution(
    unit_material: _UnitMaterial,
    tmp_path: Path,
) -> None:
    with pytest.raises(
        AuthenticatedStrategyTaTransformV1ValidationError,
        match="authenticated_strategy_ta_requested_market_mismatch",
    ):
        transform_writer_bound_ohlcv_to_strategy_ta_v1(
            unit_material.capture,
            ImmutableSourcePayloadStore(tmp_path / "output"),
            expected_symbol="ETHUSDT",
            expected_timeframe=TIMEFRAME,
        )


def test_unit_rejects_requested_timeframe_substitution(
    unit_material: _UnitMaterial,
    tmp_path: Path,
) -> None:
    with pytest.raises(
        AuthenticatedStrategyTaTransformV1ValidationError,
        match="authenticated_strategy_ta_requested_market_mismatch",
    ):
        transform_writer_bound_ohlcv_to_strategy_ta_v1(
            unit_material.capture,
            ImmutableSourcePayloadStore(tmp_path / "output"),
            expected_symbol=SYMBOL,
            expected_timeframe="1h",
        )


def test_unit_rejects_missing_required_indicator(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = copy.deepcopy(unit_material.candidate)
    candidate["indicators"].pop(REQUIRED_STRATEGY_TA_INDICATORS[0])
    candidate["indicator_count"] -= 1
    candidate["field_count"] -= 1

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1ValidationError,
        match="authenticated_strategy_ta_required_indicators_missing",
    ):
        _fast_transform(monkeypatch, unit_material, tmp_path / "output", candidate=candidate)


def test_unit_rejects_nonfinite_indicator(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = copy.deepcopy(unit_material.candidate)
    candidate["indicators"][REQUIRED_STRATEGY_TA_INDICATORS[0]] = float("nan")

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1ValidationError,
        match="authenticated_strategy_ta_indicator_contract_invalid",
    ):
        _fast_transform(monkeypatch, unit_material, tmp_path / "output", candidate=candidate)


def test_unit_rejects_candidate_source_hash_substitution(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = copy.deepcopy(unit_material.candidate)
    candidate["source_exact_payload_sha256"] = "f" * 64

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1IntegrityError,
        match="authenticated_strategy_ta_candidate_source_identity_invalid",
    ):
        _fast_transform(monkeypatch, unit_material, tmp_path / "output", candidate=candidate)


def test_unit_rejects_candidate_selected_candle_substitution(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = copy.deepcopy(unit_material.candidate)
    candidate["latest_candle_raw_payload_hash"] = "e" * 64

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1IntegrityError,
        match="authenticated_strategy_ta_candidate_source_identity_invalid",
    ):
        _fast_transform(monkeypatch, unit_material, tmp_path / "output", candidate=candidate)


def test_unit_rejects_candidate_authority_escalation(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = copy.deepcopy(unit_material.candidate)
    candidate["trainer_admission_granted"] = True

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1IntegrityError,
        match="authenticated_strategy_ta_candidate_authority_invalid",
    ):
        _fast_transform(monkeypatch, unit_material, tmp_path / "output", candidate=candidate)


def test_unit_rejects_dependency_contract_hash_drift(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    drifted = replace(unit_material.contract, contract_sha256="f" * 64)
    monkeypatch.setattr(
        transform_module,
        "build_model_ta_technical_dependency_contract",
        lambda: drifted,
    )

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1IntegrityError,
        match="authenticated_strategy_ta_dependency_contract_binding_invalid",
    ):
        _transform(unit_material.capture, tmp_path / "output")


def test_unit_rejects_environment_change_during_computation(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    drifted_environment = replace(
        unit_material.contract.talib_environment,
        python_version="0.0.0-drift",
    )
    drifted_contract = replace(
        unit_material.contract,
        talib_environment=drifted_environment,
    )
    contracts = iter((unit_material.contract, drifted_contract))
    monkeypatch.setattr(
        transform_module,
        "_validated_technical_contract",
        lambda: next(contracts),
    )
    monkeypatch.setattr(
        transform_module.full_talib_service,
        "build_full_talib_ta_closed_candidate",
        lambda *, validated_window: copy.deepcopy(unit_material.candidate),
    )

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1IntegrityError,
        match="authenticated_strategy_ta_environment_changed_during_computation",
    ):
        _transform(unit_material.capture, tmp_path / "output")


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("semantic", "authenticated_strategy_ta_semantic_cas_readback_failed"),
        ("audit", "authenticated_strategy_ta_audit_cas_readback_failed"),
    ],
)
def test_unit_detects_output_cas_corruption(
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
    reason: str,
) -> None:
    result, output_store = _fast_transform(
        monkeypatch,
        unit_material,
        tmp_path / "output",
    )
    addresses = {
        "semantic": result.semantic_content_address,
        "audit": result.audit_manifest_address,
    }
    _corrupt(output_store, addresses[target])

    with pytest.raises(
        AuthenticatedStrategyTaTransformV1IntegrityError,
        match=reason,
    ):
        _ = result.audit_manifest


def test_unit_semantic_excludes_observation_and_publication_provenance(
    unit_material: _UnitMaterial,
) -> None:
    semantic = unit_material.result.semantic_content
    keys = set()
    for section in (
        "source_semantics",
        "transform_semantics",
        "strategy_ta",
        "external_input_policy",
        "authorization",
    ):
        keys.update(_mapping_keys(semantic[section]))

    forbidden = set(transform_module._OBSERVATION_ONLY_FIELDS) | set(
        transform_module._PROVENANCE_ONLY_FIELDS
    )
    assert not forbidden.intersection(keys)
    assert semantic["semantic_clock_policy"]["observation_and_generation_clocks_excluded"] == list(
        transform_module._OBSERVATION_ONLY_FIELDS
    )
    assert semantic["semantic_clock_policy"]["publication_provenance_fields_excluded"] == list(
        transform_module._PROVENANCE_ONLY_FIELDS
    )
    assert len(unit_material.result.dependency_code_sha256s) == 7


# Four real-Redis integration cases. They exercise genuine 100-row
# publications but do not replay the prior publication-race mutation matrix.


def test_real_redis_genuine_wss_100_row_publication_transforms(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(
        raw_client,
        rows=_rows(source="wss"),
        producer_role=BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=WSS_CODE_SHA256,
    )
    capture, _ = _capture(raw_client, tmp_path / "source")
    result, _ = _transform(capture, tmp_path / "output")
    source = result.semantic_content["source_semantics"]

    assert result.producer_role == BINANCE_WSS_WRITER_ROLE
    assert capture.atomic_capture.selected_row_count == SOURCE_ROW_COUNT
    assert len(capture.ordered_selected_candle_receipt_sha256s) == SOURCE_ROW_COUNT
    assert source["binance_wss_row_count"] == SOURCE_ROW_COUNT
    assert source["binance_rest_row_count"] == 0
    assert result.calculation_row_count == CALCULATION_ROW_COUNT
    assert result.indicator_count == EXPECTED_INDICATOR_COUNT


def test_real_redis_genuine_rest_100_row_publication_transforms(
    raw_client: redis.Redis,
    tmp_path: Path,
) -> None:
    _publish(
        raw_client,
        rows=_rows(source="rest"),
        producer_role=BINANCE_REST_WRITER_ROLE,
        producer_code_sha256=REST_CODE_SHA256,
    )
    capture, _ = _capture(raw_client, tmp_path / "source")
    result, _ = _transform(capture, tmp_path / "output")
    source = result.semantic_content["source_semantics"]

    assert result.producer_role == BINANCE_REST_WRITER_ROLE
    assert capture.atomic_capture.selected_row_count == SOURCE_ROW_COUNT
    assert len(capture.ordered_selected_candle_receipt_sha256s) == SOURCE_ROW_COUNT
    assert source["binance_rest_row_count"] == SOURCE_ROW_COUNT
    assert source["binance_wss_row_count"] == 0
    assert result.calculation_row_count == CALCULATION_ROW_COUNT
    assert result.indicator_count == EXPECTED_INDICATOR_COUNT


def test_real_redis_same_publication_new_observations_and_unrelated_mutations(
    raw_client: redis.Redis,
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rows = _rows(source="wss")
    _publish(
        raw_client,
        rows=rows,
        producer_role=BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=WSS_CODE_SHA256,
    )
    first_capture, _ = _capture(raw_client, tmp_path / "source-first")
    monkeypatch.setattr(
        transform_module,
        "_validated_technical_contract",
        lambda: unit_material.contract,
    )
    first_result, _ = _transform(first_capture, tmp_path / "output-first")

    sentinel = "MUTATION_SENTINEL_MUST_NOT_ENTER_STRATEGY_TA"
    assert raw_client.set(
        "v2:live_gate:state",
        json.dumps(
            {
                "risk_profile": {
                    "fields": {
                        "max_notional_per_trade": 999_999_999,
                        "sentinel": sentinel,
                    }
                }
            }
        ),
    )
    assert raw_client.set(
        f"v2:features:moralis:{SYMBOL}:1m",
        json.dumps({"smart_money": sentinel}),
    )
    assert raw_client.set(
        f"v2:market:coinank:liquidation_levels:{SYMBOL}:{TIMEFRAME}",
        json.dumps({"liquidation_levels": [sentinel]}),
    )

    second_capture, _ = _capture(raw_client, tmp_path / "source-second")
    second_result, _ = _transform(second_capture, tmp_path / "output-second")

    assert first_capture.revision_id == second_capture.revision_id
    assert first_capture.writer_receipt_sha256 == second_capture.writer_receipt_sha256
    assert first_capture.exact_payload_sha256 == second_capture.exact_payload_sha256
    assert first_capture.composite_manifest_sha256 != (second_capture.composite_manifest_sha256)
    assert first_result.semantic_content_json == second_result.semantic_content_json
    assert first_result.semantic_content_sha256 == second_result.semantic_content_sha256
    assert first_result.audit_manifest_sha256 != second_result.audit_manifest_sha256
    assert (
        first_result.audit_manifest["implementation"]
        == (second_result.audit_manifest["implementation"])
    )
    assert (
        first_result.audit_manifest["external_input_policy"]
        == (second_result.audit_manifest["external_input_policy"])
    )
    assert sentinel not in first_result.semantic_content_json
    assert sentinel not in second_result.semantic_content_json
    assert sentinel not in first_result.audit_manifest_json
    assert sentinel not in second_result.audit_manifest_json


def test_real_redis_identical_bytes_new_genuine_revision_changes_only_provenance(
    raw_client: redis.Redis,
    unit_material: _UnitMaterial,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rows = _rows(source="wss")
    first_publication = _publish(
        raw_client,
        rows=rows,
        producer_role=BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=WSS_CODE_SHA256,
        producer_config_sha256=CONFIG_A_SHA256,
    )
    first_capture, _ = _capture(raw_client, tmp_path / "source-first")
    monkeypatch.setattr(
        transform_module,
        "_validated_technical_contract",
        lambda: unit_material.contract,
    )
    first_result, _ = _transform(first_capture, tmp_path / "output-first")

    second_publication = _publish(
        raw_client,
        rows=rows,
        producer_role=BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=WSS_CODE_SHA256,
        producer_config_sha256=CONFIG_B_SHA256,
    )
    second_capture, _ = _capture(raw_client, tmp_path / "source-second")
    second_result, _ = _transform(second_capture, tmp_path / "output-second")

    assert first_publication.revision_id != second_publication.revision_id
    assert first_capture.revision_id != second_capture.revision_id
    assert first_capture.producer_config_sha256 == CONFIG_A_SHA256
    assert second_capture.producer_config_sha256 == CONFIG_B_SHA256
    assert first_capture.writer_receipt_sha256 != second_capture.writer_receipt_sha256
    assert first_capture.exact_payload_sha256 == second_capture.exact_payload_sha256
    assert first_capture.exact_canonical_payload_bytes == (
        second_capture.exact_canonical_payload_bytes
    )
    assert first_result.semantic_content_json == second_result.semantic_content_json
    assert first_result.semantic_content_sha256 == second_result.semantic_content_sha256
    assert first_result.audit_manifest_sha256 != second_result.audit_manifest_sha256
    assert (
        first_result.audit_manifest["upstream_proof"]["revision_id"]
        != (second_result.audit_manifest["upstream_proof"]["revision_id"])
    )
    assert (
        first_result.audit_manifest["upstream_proof"]["producer_config_sha256"]
        != (second_result.audit_manifest["upstream_proof"]["producer_config_sha256"])
    )
