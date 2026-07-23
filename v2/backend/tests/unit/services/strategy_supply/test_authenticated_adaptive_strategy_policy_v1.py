from __future__ import annotations

import hashlib
import inspect
import math
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import redis

from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.strategy_supply import (
    authenticated_adaptive_strategy_policy_v1 as policy_module,
)
from v2.backend.app.services.strategy_supply.authenticated_adaptive_strategy_policy_v1 import (
    AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION,
    AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION,
    EXPLICITLY_EXCLUDED_ECONOMIC_INPUTS,
    EXPLICITLY_EXCLUDED_MUTABLE_INPUTS,
    ORDERED_EXPERT_NAMES,
    AuthenticatedAdaptiveStrategyPolicyV1IntegrityError,
    AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
    build_authenticated_adaptive_strategy_policy_v1,
)
from v2.backend.tests.unit.services.strategy_supply import (
    test_authenticated_strategy_output_publication_v1 as publication_test,
)
from v2.backend.tests.unit.services.strategy_supply import (
    test_authenticated_strategy_ta_transform_v1 as ta_test,
)

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _clock(value: str) -> datetime:
    return datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)


def _after(value: str, *, milliseconds: int) -> datetime:
    return _clock(value) + timedelta(milliseconds=milliseconds)


def _clock_to_ms(value: datetime) -> int:
    return int((value - _EPOCH).total_seconds() * 1_000)


@pytest.fixture(scope="module")
def redis_socket(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for authenticated policy tests")
    root = tmp_path_factory.mktemp("authenticated-adaptive-policy-redis")
    socket_path = str(root / "redis.sock")
    process = subprocess.Popen(  # noqa: S603 - fixed local executable and arguments
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
            client = redis.Redis(unix_socket_path=socket_path, decode_responses=False)
            if client.ping():
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


@pytest.fixture(scope="module")
def genuine_publication(
    redis_socket: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    client = redis.Redis(unix_socket_path=redis_socket, decode_responses=False)
    client.flushdb()
    ta_test._publish(
        client,
        rows=ta_test._rows(source="wss"),
        producer_role=ta_test.BINANCE_WSS_WRITER_ROLE,
        producer_code_sha256=ta_test.WSS_CODE_SHA256,
    )
    root = tmp_path_factory.mktemp("authenticated-adaptive-policy-upstream")
    capture, _source_store = ta_test._capture(client, root / "source")
    transform, _transform_store = ta_test._transform(capture, root / "transform")
    return publication_test.publish_and_verify_authenticated_strategy_output_v1(
        client,
        transform,
        archive_ttl_seconds=publication_test._ARCHIVE_TTL_SECONDS,
        receipt_ttl_seconds=publication_test._RECEIPT_TTL_SECONDS,
        publication_clock=lambda: publication_test._publication_clock(transform),
    )


def _policy_clock(publication: Any, *, first_ms: int = 1, second_ms: int = 2) -> Any:
    observations = iter(
        (
            _after(publication.consumer_reopened_at, milliseconds=first_ms),
            _after(publication.consumer_reopened_at, milliseconds=second_ms),
        )
    )
    return lambda: next(observations)


def _build(publication: Any, root: Path) -> Any:
    store = ImmutableSourcePayloadStore(root)
    result = build_authenticated_adaptive_strategy_policy_v1(
        publication,
        store,
        policy_clock=_policy_clock(publication),
    )
    return result, store


def _rows_from_closes(closes: list[float]) -> tuple[SimpleNamespace, ...]:
    return tuple(SimpleNamespace(close=value) for value in closes)


def test_exact_adaptive_proposal_is_authenticated_but_all_trade_authority_is_held(
    genuine_publication: Any,
    redis_socket: str,
    tmp_path: Path,
) -> None:
    result, store = _build(genuine_publication, tmp_path / "policy")
    semantic = result.semantic_content
    audit = result.audit_manifest
    adaptive = semantic["adaptive_policy"]
    inputs = semantic["input_policy"]
    candidate = semantic["candidate_fields"]
    authorization = semantic["authorization"]

    assert result.schema_version == AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION
    assert audit["schema_version"] == (
        AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION
    )
    assert result.source_publication is genuine_publication
    assert genuine_publication.upstream_transform is genuine_publication._upstream_transform
    assert result.calculation_row_count == ta_test.CALCULATION_ROW_COUNT == 89
    assert result.walk_forward_evaluation_count == 87
    assert result.forecast_horizon_ms == ta_test.TIMEFRAME_DURATION_MS[ta_test.TIMEFRAME]
    assert result.raw_directional_proposal in {"UP", "DOWN", "NEUTRAL"}
    assert math.isfinite(result.expected_log_return)
    assert math.isfinite(result.expected_move_bps)
    assert result.predictive_uncertainty_log_return >= 0.0
    assert 0.0 <= result.directional_signal_strength <= 1.0
    assert result.non_executable_target_price > 0.0
    assert 0.0 < result.non_executable_uncertainty_lower_price <= result.reference_price
    assert result.non_executable_uncertainty_upper_price >= result.reference_price
    assert result.predictive_uncertainty_up_bps == pytest.approx(
        (result.non_executable_uncertainty_upper_price / result.reference_price - 1.0) * 10_000.0
    )
    assert result.predictive_uncertainty_down_bps == pytest.approx(
        (1.0 - result.non_executable_uncertainty_lower_price / result.reference_price) * 10_000.0
    )
    assert adaptive["directional_signal_strength_semantics"] == (
        "BOUNDED_UNCALIBRATED_RATIO_NOT_A_PROBABILITY"
    )
    assert tuple(name for name, _value in result.ordered_adaptive_weights) == (ORDERED_EXPERT_NAMES)
    assert abs(math.fsum(value for _name, value in result.ordered_adaptive_weights) - 1.0) <= (
        math.ulp(1.0) * len(ORDERED_EXPERT_NAMES)
    )
    assert adaptive["future_rows_used"] is False
    assert adaptive["zero_fill_used"] is False
    assert inputs["market_performance_thresholds"] == []
    assert inputs["fixed_expert_weights"] == []
    assert inputs["score_cutoffs"] == []
    assert inputs["unreceipted_external_economics_consumed"] == []
    assert inputs["explicitly_excluded_economic_inputs"] == list(
        EXPLICITLY_EXCLUDED_ECONOMIC_INPUTS
    )
    assert inputs["explicitly_excluded_mutable_inputs"] == list(EXPLICITLY_EXCLUDED_MUTABLE_INPUTS)
    assert inputs["optional_provider_inputs_consumed"] == []
    assert set(candidate.values()) == {None}
    assert authorization["raw_directional_proposal_authenticated"] is True
    assert all(
        authorization[name] is False
        for name in (
            "strategy_candidate_attached",
            "strategy_output_authorized",
            "prediction_authorized",
            "paper_trading_authorized",
            "live_execution_authorized",
            "order_submission_authorized",
            "runtime_wired",
        )
    )
    assert result.available_at is None
    assert result.execution_time is None
    assert result.strategy_candidate_attached is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.order_submission_authorized is False
    clocks = (
        result.feature_cutoff,
        result.max_source_available_at,
        genuine_publication.upstream_transform.writer_publication_available_at,
        genuine_publication.upstream_transform.capture_generated_at,
        genuine_publication.upstream_transform.transform_generated_at,
        result.output_generated_at,
        result.output_available_at,
        result.output_receipt_postcommit_observed_at,
        result.output_consumer_reopened_at,
        result.decision_time,
        result.generated_at,
    )
    assert all(
        _clock(left) <= _clock(right) for left, right in zip(clocks, clocks[1:], strict=False)
    )
    assert store.get(
        result.semantic_content_sha256,
        expected_byte_count=result.semantic_content_byte_count,
    ) == result.semantic_content_json.encode("ascii")
    assert store.get(
        result.audit_manifest_sha256,
        expected_byte_count=result.audit_manifest_byte_count,
    ) == result.audit_manifest_json.encode("ascii")
    redis_client = redis.Redis(unix_socket_path=redis_socket, decode_responses=False)
    assert redis_client.get(genuine_publication.archive_key) == (
        genuine_publication._envelope_json.encode("ascii")
    )
    assert redis_client.get(genuine_publication.latest_projection_key) == (
        genuine_publication._envelope_json.encode("ascii")
    )
    assert redis_client.get(genuine_publication.receipt_key) == (
        genuine_publication._receipt_json.encode("ascii")
    )
    assert redis_client.get(genuine_publication.latest_receipt_pointer_key) == (
        genuine_publication.output_id.encode("ascii")
    )


def test_same_source_has_stable_semantics_but_distinct_clock_audits(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    first_store = ImmutableSourcePayloadStore(tmp_path / "first")
    first = build_authenticated_adaptive_strategy_policy_v1(
        genuine_publication,
        first_store,
        policy_clock=_policy_clock(genuine_publication, first_ms=1, second_ms=2),
    )
    second_store = ImmutableSourcePayloadStore(tmp_path / "second")
    second = build_authenticated_adaptive_strategy_policy_v1(
        genuine_publication,
        second_store,
        policy_clock=_policy_clock(genuine_publication, first_ms=3, second_ms=4),
    )

    assert first.semantic_content_sha256 == second.semantic_content_sha256
    assert first.semantic_content_json == second.semantic_content_json
    assert first.ordered_adaptive_weights == second.ordered_adaptive_weights
    assert first.decision_time != second.decision_time
    assert first.audit_manifest_sha256 != second.audit_manifest_sha256


def test_walk_forward_calls_only_expanding_prefixes(
    genuine_publication: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transform = genuine_publication.upstream_transform
    _window, rows = policy_module._validated_exact_window(transform)
    expected_log_prices = tuple(math.log(float(row.close)) for row in rows)
    observed_histories: list[tuple[float, ...]] = []
    original = policy_module._expert_forecasts

    def recording(history: tuple[float, ...]) -> tuple[tuple[str, float], ...]:
        observed_histories.append(history)
        return original(history)

    monkeypatch.setattr(policy_module, "_expert_forecasts", recording)
    policy_module._compute_policy(rows)

    assert observed_histories == [
        *(expected_log_prices[:target_index] for target_index in range(2, 89)),
        expected_log_prices,
    ]


def test_weights_change_with_observed_return_regime() -> None:
    trending = _rows_from_closes(
        [100.0 * math.exp(0.001 * index + 0.00002 * index * index) for index in range(89)]
    )
    alternating = _rows_from_closes(
        [100.0 * math.exp(0.006 if index % 2 else -0.006) for index in range(89)]
    )

    trend_policy = policy_module._compute_policy(trending)
    alternating_policy = policy_module._compute_policy(alternating)

    assert trend_policy.ordered_adaptive_weights != alternating_policy.ordered_adaptive_weights
    assert all(value >= 0.0 for _name, value in trend_policy.ordered_adaptive_weights)
    assert all(value >= 0.0 for _name, value in alternating_policy.ordered_adaptive_weights)


def test_arbitrarily_small_nonzero_forecasts_have_no_magnitude_cutoff() -> None:
    step = math.ulp(1.0) * 32
    upward = policy_module._compute_policy(
        _rows_from_closes([100.0 * math.exp(step * index) for index in range(89)])
    )
    downward = policy_module._compute_policy(
        _rows_from_closes([100.0 * math.exp(-step * index) for index in range(89)])
    )

    assert upward.expected_log_return > 0.0
    assert upward.raw_directional_proposal == "UP"
    assert downward.expected_log_return < 0.0
    assert downward.raw_directional_proposal == "DOWN"


def test_exact_zero_forecast_is_structural_neutrality() -> None:
    computation = policy_module._compute_policy(_rows_from_closes([100.0] * 89))

    assert computation.expected_log_return == 0.0
    assert computation.raw_directional_proposal == "NEUTRAL"
    assert computation.directional_signal_strength == 0.0
    assert computation.non_executable_target_price == 100.0
    assert computation.non_executable_uncertainty_lower_price == 100.0
    assert computation.non_executable_uncertainty_upper_price == 100.0
    assert set(value for _name, value in computation.ordered_expert_mse) == {0.0}
    assert set(value for _name, value in computation.ordered_adaptive_weights) == {0.25}


@pytest.mark.parametrize("invalid_close", [0.0, -1.0, math.inf, math.nan])
def test_invalid_close_price_fails_closed(invalid_close: float) -> None:
    closes = [100.0] * 89
    closes[-1] = invalid_close
    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
        match="adaptive_strategy_policy_close_price_invalid",
    ):
        policy_module._compute_policy(_rows_from_closes(closes))


def test_stale_source_at_proposal_decision_fails_before_cas(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    duration = ta_test.TIMEFRAME_DURATION_MS[ta_test.TIMEFRAME]
    reopened = _clock(genuine_publication.consumer_reopened_at)
    stale_ms = ((_clock_to_ms(reopened) // duration) + 1) * duration
    stale = _EPOCH + timedelta(milliseconds=stale_ms)
    observations = iter((stale, stale + timedelta(milliseconds=1)))
    store = ImmutableSourcePayloadStore(tmp_path / "stale")

    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
        match="adaptive_strategy_policy_source_stale_at_decision",
    ):
        build_authenticated_adaptive_strategy_policy_v1(
            genuine_publication,
            store,
            policy_clock=lambda: next(observations),
        )


def test_decision_before_output_reopen_fails_closed(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    early = _clock(genuine_publication.available_at)
    observations = iter((early, early + timedelta(milliseconds=1)))
    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
        match="adaptive_strategy_policy_clock_order_invalid",
    ):
        build_authenticated_adaptive_strategy_policy_v1(
            genuine_publication,
            ImmutableSourcePayloadStore(tmp_path / "early"),
            policy_clock=lambda: next(observations),
        )


def test_regressing_generation_clock_fails_closed(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    observations = iter(
        (
            _after(genuine_publication.consumer_reopened_at, milliseconds=2),
            _after(genuine_publication.consumer_reopened_at, milliseconds=1),
        )
    )
    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
        match="adaptive_strategy_policy_clock_order_invalid",
    ):
        build_authenticated_adaptive_strategy_policy_v1(
            genuine_publication,
            ImmutableSourcePayloadStore(tmp_path / "regressing"),
            policy_clock=lambda: next(observations),
        )


def test_factory_publication_and_authentic_store_are_required(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
        match="adaptive_strategy_policy_verified_output_publication_required",
    ):
        build_authenticated_adaptive_strategy_policy_v1(  # type: ignore[arg-type]
            object(),
            ImmutableSourcePayloadStore(tmp_path / "invalid-publication"),
        )
    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1ValidationError,
        match="adaptive_strategy_policy_authentic_store_required",
    ):
        build_authenticated_adaptive_strategy_policy_v1(  # type: ignore[arg-type]
            genuine_publication,
            object(),
        )


def test_result_replacement_and_address_tamper_fail_closed(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    result, _store = _build(genuine_publication, tmp_path / "policy")
    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1IntegrityError,
        match="adaptive_strategy_policy_result_binding_invalid",
    ):
        replace(result, expected_move_bps=result.expected_move_bps + 1.0)
    with pytest.raises(AuthenticatedAdaptiveStrategyPolicyV1IntegrityError):
        replace(
            result,
            semantic_content_address=SourcePayloadAddress(
                schema_version=result.semantic_content_address.schema_version,
                payload_sha256="f" * 64,
                payload_byte_count=result.semantic_content_byte_count,
                relative_path=f"sha256/ff/{'f' * 64}",
            ),
        )


@pytest.mark.parametrize(
    ("artifact_name", "mutation"),
    [
        ("semantic", "corrupt"),
        ("semantic", "delete"),
        ("audit", "corrupt"),
        ("audit", "delete"),
    ],
)
def test_postconstruction_cas_corruption_and_deletion_fail_closed(
    genuine_publication: Any,
    tmp_path: Path,
    artifact_name: str,
    mutation: str,
) -> None:
    result, store = _build(
        genuine_publication,
        tmp_path / f"policy-{artifact_name}-{mutation}",
    )
    address = (
        result.semantic_content_address
        if artifact_name == "semantic"
        else result.audit_manifest_address
    )
    path = store.root_path / address.relative_path
    if mutation == "delete":
        path.unlink()
    else:
        retained = path.read_bytes()
        path.chmod(0o600)
        path.write_bytes(bytes((retained[0] ^ 1,)) + retained[1:])
        path.chmod(0o400)

    with pytest.raises(
        AuthenticatedAdaptiveStrategyPolicyV1IntegrityError,
        match=f"adaptive_strategy_policy_{artifact_name}_cas_readback_failed",
    ):
        _ = result.semantic_content


def test_public_api_cannot_accept_economics_position_or_execution_inputs() -> None:
    signature = inspect.signature(build_authenticated_adaptive_strategy_policy_v1)
    source = inspect.getsource(policy_module)

    assert tuple(signature.parameters) == (
        "publication",
        "source_payload_store",
        "policy_clock",
    )
    assert not {
        "cost_evidence",
        "notional_usd",
        "quantity",
        "account",
        "position_state",
        "risk_envelope",
        "leverage",
        "margin",
        "live_gate_state",
        "optional_providers",
    }.intersection(signature.parameters)
    assert 'market_performance_thresholds": []' in source
    assert 'fixed_expert_weights": []' in source
    assert 'score_cutoffs": []' in source


def test_module_code_identity_binds_exact_source_file(
    genuine_publication: Any,
    tmp_path: Path,
) -> None:
    result, _store = _build(genuine_publication, tmp_path / "policy")
    expected_modules = {
        "authenticated_adaptive_strategy_policy_v1": policy_module,
        "authenticated_strategy_output_publication_v1": (publication_test.publication_module),
        "authenticated_strategy_ta_transform_v1": policy_module.strategy_ta_module,
        "ohlcv_closed_window_schema": policy_module.ohlcv_schema_module,
        "immutable_source_payload_store": policy_module.source_payload_store_module,
    }
    dependency_digests = dict(result.dependency_code_sha256s)

    assert tuple(dependency_digests) == tuple(expected_modules)
    assert (
        result.module_code_sha256 == dependency_digests["authenticated_adaptive_strategy_policy_v1"]
    )
    for dependency_name, dependency_module in expected_modules.items():
        assert (
            dependency_digests[dependency_name]
            == hashlib.sha256(Path(dependency_module.__file__).read_bytes()).hexdigest()
        )
