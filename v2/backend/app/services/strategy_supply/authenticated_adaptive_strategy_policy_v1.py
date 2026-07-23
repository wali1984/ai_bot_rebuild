"""Authenticated adaptive TA-only strategy proposal.

This boundary consumes only a post-commit-reopened held strategy-output
publication.  It independently revalidates the exact writer-authenticated
closed-OHLCV suffix and derives a one-timeframe directional proposal from a
walk-forward ensemble whose weights come only from the observed pre-decision
forecast errors in that suffix.

The artifact deliberately does not accept fees, spread, slippage, funding,
notional, account, position, margin, leverage, optional-provider, or mutable
live-gate inputs.  It therefore cannot create a strategy candidate or grant
prediction, PAPER, live, or order authority.  A later receipt family must
authenticate those missing economic and state inputs before admission.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer import (
    immutable_source_payload_store as source_payload_store_module,
)
from v2.backend.app.services.native_trainer import (
    ohlcv_closed_window_schema as ohlcv_schema_module,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)
from v2.backend.app.services.strategy_supply import (
    authenticated_strategy_output_publication_v1 as output_publication_module,
)
from v2.backend.app.services.strategy_supply import (
    authenticated_strategy_ta_transform_v1 as strategy_ta_module,
)
from v2.backend.app.services.strategy_supply.authenticated_strategy_output_publication_v1 import (
    StrategyOutputPublicationV1Error,
    VerifiedStrategyOutputPublicationV1,
)
from v2.backend.app.services.strategy_supply.authenticated_strategy_ta_transform_v1 import (
    AuthenticatedStrategyTaTransformV1,
    AuthenticatedStrategyTaTransformV1Error,
)

AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION: Final = (
    "authenticated_adaptive_strategy_policy_v1"
)
AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION: Final = (
    "authenticated_adaptive_strategy_policy_audit_v1"
)
AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_EVIDENCE_CLASSIFICATION: Final = (
    "WRITER_AUTHENTICATED_PIT_TA_ONLY_WALK_FORWARD_ADAPTIVE_PROPOSAL"
)
AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_DOWNSTREAM_STATUS: Final = (
    "RAW_DIRECTIONAL_PROPOSAL_ONLY_COST_NOTIONAL_STATE_CANDIDATE_AND_EXECUTION_AUTHORITY_HELD"
)

ORDERED_EXPERT_NAMES: Final = (
    "expanding_mean_log_return",
    "last_log_return_momentum",
    "last_log_return_reversion",
    "least_squares_log_price_trend",
)
EXPLICITLY_EXCLUDED_ECONOMIC_INPUTS: Final = (
    "fee_bps",
    "spread_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
    "reference_notional",
    "account_equity",
    "available_margin",
    "position_state",
    "risk_envelope",
    "leverage_envelope",
)
EXPLICITLY_EXCLUDED_MUTABLE_INPUTS: Final = (
    "v2:live_gate:state",
    "v2:strategy_supply:hypotheses:*",
    "v2:strategy_supply:positive_hypotheses:*",
    "v2:strategy_supply:gate_clean_positive_hypotheses:*",
)

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_CONSTRUCTION_TOKEN = object()

_AUTHORITY_FIELDS = (
    "strategy_candidate_attached",
    "strategy_output_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
)

_IMPLEMENTATION_MANIFEST = {
    "schema_version": "authenticated_adaptive_strategy_policy_implementation_v1",
    "input": "EXACT_WRITER_AUTHENTICATED_CLOSED_OHLCV_SUFFIX_BOUND_TO_OUTPUT_RECEIPT",
    "return_domain": "NATURAL_LOG_CLOSE_TO_CLOSE",
    "ordered_experts": list(ORDERED_EXPERT_NAMES),
    "evaluation": "EXPANDING_ONE_STEP_WALK_FORWARD_WITHOUT_FUTURE_ROWS",
    "weighting": "NORMALIZED_INVERSE_WALK_FORWARD_MSE_WITH_EXACT_ZERO_TIE",
    "uncertainty": "WEIGHTED_RESIDUAL_MSE_PLUS_CURRENT_EXPERT_DISAGREEMENT",
    "direction": "EXACT_SIGN_OF_ENSEMBLE_EXPECTED_LOG_RETURN",
    "signal_strength": "ABS_EXPECTED_RETURN_DIVIDED_BY_ABS_EXPECTED_RETURN_PLUS_UNCERTAINTY",
    "signal_strength_semantics": "BOUNDED_UNCALIBRATED_RATIO_NOT_A_PROBABILITY",
    "forecast_horizon": "ONE_SOURCE_TIMEFRAME",
    "market_selection_threshold": "NONE",
}
_CONFIGURATION_CONTRACT = {
    "schema_version": "authenticated_adaptive_strategy_policy_configuration_v1",
    "source_row_count": "UPSTREAM_AUTHENTICATED_TA_CALCULATION_ROW_COUNT",
    "expert_weights": "DERIVED_PER_ARTIFACT_FROM_WALK_FORWARD_ERROR",
    "fixed_expert_weights": [],
    "market_performance_thresholds": [],
    "score_cutoffs": [],
    "zero_fill": "FORBIDDEN",
    "missing_economics": "EXPLICIT_NULL_AND_AUTHORITY_HELD",
    "missing_position_state": "EXPLICIT_NULL_AND_AUTHORITY_HELD",
    "optional_provider_policy": "NOT_CONSUMED",
}


def _static_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_IMPLEMENTATION_SHA256: Final = _static_sha256(
    _IMPLEMENTATION_MANIFEST
)
AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_CONFIGURATION_SHA256: Final = _static_sha256(
    _CONFIGURATION_CONTRACT
)


class AuthenticatedAdaptiveStrategyPolicyV1Error(RuntimeError):
    """Base fail-closed adaptive proposal error."""


class AuthenticatedAdaptiveStrategyPolicyV1ValidationError(
    AuthenticatedAdaptiveStrategyPolicyV1Error
):
    """A caller, clock, source, or numerical input violates the contract."""


class AuthenticatedAdaptiveStrategyPolicyV1IntegrityError(
    AuthenticatedAdaptiveStrategyPolicyV1Error
):
    """An authenticated identity, artifact, or factory binding does not hold."""


@dataclass(frozen=True, slots=True)
class _PolicyComputation:
    raw_directional_proposal: str
    expected_log_return: float
    expected_move_bps: float
    predictive_uncertainty_log_return: float
    predictive_uncertainty_up_bps: float
    predictive_uncertainty_down_bps: float
    directional_signal_strength: float
    reference_price: float
    non_executable_target_price: float
    non_executable_uncertainty_lower_price: float
    non_executable_uncertainty_upper_price: float
    walk_forward_evaluation_count: int
    ordered_expert_forecasts: tuple[tuple[str, float], ...]
    ordered_expert_mse: tuple[tuple[str, float], ...]
    ordered_adaptive_weights: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class AuthenticatedAdaptiveStrategyPolicyV1:
    """Factory-authenticated TA-only proposal with all trade authority held."""

    schema_version: str
    audit_schema_version: str
    evidence_classification: str
    downstream_status: str
    symbol: str
    timeframe: str
    output_id: str
    output_payload_sha256: str
    output_receipt_sha256: str
    upstream_ta_semantic_sha256: str
    upstream_ta_audit_sha256: str
    upstream_exact_payload_sha256: str
    calculation_row_count: int
    calculation_window_candle_ids_sha256: str
    latest_candle_id: str
    latest_candle_raw_payload_hash: str
    forecast_horizon_ms: int
    raw_directional_proposal: str
    expected_log_return: float
    expected_move_bps: float
    predictive_uncertainty_log_return: float
    predictive_uncertainty_up_bps: float
    predictive_uncertainty_down_bps: float
    directional_signal_strength: float
    reference_price: float
    non_executable_target_price: float
    non_executable_uncertainty_lower_price: float
    non_executable_uncertainty_upper_price: float
    walk_forward_evaluation_count: int
    ordered_expert_forecasts: tuple[tuple[str, float], ...]
    ordered_expert_mse: tuple[tuple[str, float], ...]
    ordered_adaptive_weights: tuple[tuple[str, float], ...]
    implementation_sha256: str
    configuration_sha256: str
    module_code_sha256: str
    dependency_code_root_sha256: str
    dependency_code_sha256s: tuple[tuple[str, str], ...]
    feature_cutoff: str
    max_source_available_at: str
    output_generated_at: str
    output_available_at: str
    output_receipt_postcommit_observed_at: str
    output_consumer_reopened_at: str
    decision_time: str
    generated_at: str
    available_at: None
    execution_time: None
    semantic_content_sha256: str
    semantic_content_byte_count: int
    semantic_content_json: str = field(repr=False)
    semantic_content_address: SourcePayloadAddress
    audit_manifest_sha256: str
    audit_manifest_byte_count: int
    audit_manifest_json: str = field(repr=False)
    audit_manifest_address: SourcePayloadAddress
    _publication: VerifiedStrategyOutputPublicationV1 = field(repr=False, compare=False)
    _source_payload_store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)
    publication_receipt_authenticated: bool = field(default=True, init=False)
    upstream_transform_authenticated: bool = field(default=True, init=False)
    exact_closed_window_revalidated: bool = field(default=True, init=False)
    adaptive_weights_rederived: bool = field(default=True, init=False)
    semantic_and_audit_cas_reopened: bool = field(default=True, init=False)
    raw_directional_proposal_authenticated: bool = field(default=True, init=False)
    market_performance_thresholds_applied: bool = field(default=False, init=False)
    unreceipted_external_economics_consumed: bool = field(default=False, init=False)
    cost_evidence_receipt_sha256: None = field(default=None, init=False)
    expected_notional_receipt_sha256: None = field(default=None, init=False)
    position_state_receipt_sha256: None = field(default=None, init=False)
    leverage_envelope_receipt_sha256: None = field(default=None, init=False)
    strategy_candidate_attached: bool = field(default=False, init=False)
    strategy_output_authorized: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)
    runtime_wired: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_result(self)

    @property
    def semantic_content(self) -> dict[str, Any]:
        _validate_result(self)
        return cast(dict[str, Any], json.loads(self.semantic_content_json))

    @property
    def audit_manifest(self) -> dict[str, Any]:
        _validate_result(self)
        return cast(dict[str, Any], json.loads(self.audit_manifest_json))

    @property
    def source_publication(self) -> VerifiedStrategyOutputPublicationV1:
        _validate_result(self)
        return self._publication


def _validation_error(reason: str) -> NoReturn:
    raise AuthenticatedAdaptiveStrategyPolicyV1ValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise AuthenticatedAdaptiveStrategyPolicyV1IntegrityError(reason) from None


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _integrity_error("adaptive_strategy_policy_json_encoding_invalid")
    if not encoded or len(encoded) > _MAX_ARTIFACT_BYTES:
        _integrity_error("adaptive_strategy_policy_artifact_size_invalid")
    return encoded


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _validation_error(reason)
    try:
        parsed = datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _validation_error(reason)
    if parsed.strftime(_CLOCK_FORMAT) != value:
        _validation_error(reason)
    return parsed


def _clock_to_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000) + delta.microseconds // 1_000


def _ms_to_clock(value: int) -> str:
    if type(value) is not int or value < 0:
        _integrity_error("adaptive_strategy_policy_source_clock_invalid")
    try:
        parsed = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _integrity_error("adaptive_strategy_policy_source_clock_invalid")
    return parsed.strftime(_CLOCK_FORMAT)


def _sample_clock(clock: Callable[[], datetime], *, reason: str) -> tuple[str, datetime]:
    if not callable(clock):
        _validation_error(reason)
    try:
        observed = clock()
    except Exception:  # noqa: BLE001 - hostile clock detail must not escape
        _validation_error(reason)
    if type(observed) is not datetime or observed.tzinfo is None:
        _validation_error(reason)
    normalized = observed.astimezone(UTC)
    text = normalized.strftime(_CLOCK_FORMAT)
    return text, _parse_clock(text, reason=reason)


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _validate_address(
    address: object,
    *,
    expected_sha256: str,
    expected_byte_count: int,
    reason: str,
) -> SourcePayloadAddress:
    if type(address) is not SourcePayloadAddress:
        _integrity_error(reason)
    typed = cast(SourcePayloadAddress, address)
    if (
        typed.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or typed.payload_sha256 != expected_sha256
        or typed.payload_byte_count != expected_byte_count
        or typed.relative_path != f"sha256/{expected_sha256[:2]}/{expected_sha256}"
    ):
        _integrity_error(reason)
    return typed


def _fresh_readback(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    expected: bytes,
    *,
    reason: str,
) -> None:
    try:
        reopened = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise AuthenticatedAdaptiveStrategyPolicyV1IntegrityError(reason) from exc
    if not hmac.compare_digest(reopened, expected):
        _integrity_error(reason)


def _put_immutable(
    store: ImmutableSourcePayloadStore,
    payload: bytes,
    *,
    reason: str,
) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        address = store.put(
            payload,
            expected_sha256=digest,
            expected_byte_count=len(payload),
        )
    except SourcePayloadStoreError as exc:
        raise AuthenticatedAdaptiveStrategyPolicyV1IntegrityError(reason) from exc
    _fresh_readback(store, address, payload, reason=reason)
    return address


def _read_module_sha256(module: ModuleType, *, expected_name: str, reason: str) -> str:
    path_value = getattr(module, "__file__", None)
    if type(path_value) is not str:
        _integrity_error(reason)
    path = Path(path_value)
    if path.name != expected_name or path.suffix != ".py":
        _integrity_error(reason)
    try:
        source = path.read_bytes()
    except OSError:
        _integrity_error(reason)
    if not source:
        _integrity_error(reason)
    return hashlib.sha256(source).hexdigest()


def _self_code_sha256() -> str:
    try:
        source = Path(__file__).read_bytes()
    except OSError:
        _integrity_error("adaptive_strategy_policy_code_unavailable")
    if not source:
        _integrity_error("adaptive_strategy_policy_code_unavailable")
    return hashlib.sha256(source).hexdigest()


def _dependency_code_material() -> tuple[tuple[tuple[str, str], ...], str]:
    dependencies = (
        ("authenticated_adaptive_strategy_policy_v1", _self_code_sha256()),
        (
            "authenticated_strategy_output_publication_v1",
            _read_module_sha256(
                output_publication_module,
                expected_name="authenticated_strategy_output_publication_v1.py",
                reason="adaptive_strategy_policy_output_contract_code_unavailable",
            ),
        ),
        (
            "authenticated_strategy_ta_transform_v1",
            _read_module_sha256(
                strategy_ta_module,
                expected_name="authenticated_strategy_ta_transform_v1.py",
                reason="adaptive_strategy_policy_ta_contract_code_unavailable",
            ),
        ),
        (
            "ohlcv_closed_window_schema",
            _read_module_sha256(
                ohlcv_schema_module,
                expected_name="ohlcv_closed_window_schema.py",
                reason="adaptive_strategy_policy_ohlcv_schema_code_unavailable",
            ),
        ),
        (
            "immutable_source_payload_store",
            _read_module_sha256(
                source_payload_store_module,
                expected_name="immutable_source_payload_store.py",
                reason="adaptive_strategy_policy_cas_code_unavailable",
            ),
        ),
    )
    if any(_SHA256_RE.fullmatch(digest) is None for _name, digest in dependencies):
        _integrity_error("adaptive_strategy_policy_dependency_hash_invalid")
    root = _static_sha256(
        {
            "schema_version": "authenticated_adaptive_strategy_policy_dependencies_v1",
            "ordered_dependencies": [
                {"dependency_id": name, "code_sha256": digest} for name, digest in dependencies
            ],
        }
    )
    return dependencies, root


def _validated_publication(
    value: object,
) -> tuple[VerifiedStrategyOutputPublicationV1, AuthenticatedStrategyTaTransformV1]:
    if type(value) is not VerifiedStrategyOutputPublicationV1:
        _validation_error("adaptive_strategy_policy_verified_output_publication_required")
    publication = cast(VerifiedStrategyOutputPublicationV1, value)
    try:
        envelope = publication.envelope
        receipt = publication.receipt
        transform = publication.upstream_transform
        _ = transform.semantic_content
        _ = transform.audit_manifest
    except (StrategyOutputPublicationV1Error, AuthenticatedStrategyTaTransformV1Error) as exc:
        raise AuthenticatedAdaptiveStrategyPolicyV1IntegrityError(
            "adaptive_strategy_policy_upstream_revalidation_failed"
        ) from exc
    if (
        type(transform) is not AuthenticatedStrategyTaTransformV1
        or publication.publication_binding_authenticated is not True
        or publication.upstream_transform_authenticated is not True
        or publication.authenticated_adaptive_policy_attached is not False
        or publication.strategy_candidate_count != 0
        or any(getattr(publication, name) is not False for name in _AUTHORITY_FIELDS[1:])
        or envelope.get("strategy_candidates") != []
        or envelope.get("authenticated_adaptive_policy_receipt_sha256") is not None
        or envelope.get("market_performance_thresholds_applied") != []
        or envelope.get("unreceipted_external_economics_consumed") != []
        or receipt.get("authenticated_adaptive_policy_attached") is not False
        or receipt.get("strategy_candidate_count") != 0
        or publication.output_id != envelope.get("output_id")
        or publication.receipt_sha256 != receipt.get("receipt_sha256")
    ):
        _integrity_error("adaptive_strategy_policy_upstream_authority_invalid")
    return publication, transform


def _validated_exact_window(
    transform: AuthenticatedStrategyTaTransformV1,
) -> tuple[ValidatedOHLCVClosedWindow, tuple[Any, ...]]:
    try:
        capture = transform.source_capture
        exact_payload = capture.exact_canonical_payload_bytes
    except Exception as exc:  # noqa: BLE001 - upstream factory detail is contained
        raise AuthenticatedAdaptiveStrategyPolicyV1IntegrityError(
            "adaptive_strategy_policy_source_capture_revalidation_failed"
        ) from exc
    try:
        window = validate_ohlcv_closed_window(
            exact_payload,
            symbol=transform.symbol,
            timeframe=transform.timeframe,
            required_contiguous_lookback=transform.calculation_row_count,
        )
    except OHLCVClosedWindowValidationError as exc:
        raise AuthenticatedAdaptiveStrategyPolicyV1ValidationError(
            "adaptive_strategy_policy_exact_window_unavailable"
        ) from exc
    calculation_rows = window.rows[-transform.calculation_row_count :]
    semantic = transform.semantic_content
    strategy_ta = semantic.get("strategy_ta")
    if not isinstance(strategy_ta, Mapping):
        _integrity_error("adaptive_strategy_policy_ta_semantic_invalid")
    if (
        window.exact_payload_sha256 != transform.exact_payload_sha256
        or window.exact_payload_byte_count != transform.exact_payload_byte_count
        or window.symbol != transform.symbol
        or window.timeframe != transform.timeframe
        or window.source_key != transform.source_key
        or window.contiguous_suffix_count < transform.calculation_row_count
        or len(calculation_rows) != transform.calculation_row_count
        or calculation_rows[-1].candle_id != transform.latest_candle_id
        or calculation_rows[-1].raw_payload_hash != transform.latest_candle_raw_payload_hash
        or float(calculation_rows[-1].close) != transform.reference_price
        or strategy_ta.get("calculation_window_first_candle_id") != calculation_rows[0].candle_id
        or strategy_ta.get("calculation_window_latest_candle_id") != calculation_rows[-1].candle_id
        or strategy_ta.get("calculation_window_candle_ids_sha256")
        != transform.calculation_window_candle_ids_sha256
        or transform.feature_cutoff != _ms_to_clock(calculation_rows[-1].candle_close_time)
        or transform.max_source_available_at != _ms_to_clock(window.max_available_at)
    ):
        _integrity_error("adaptive_strategy_policy_exact_window_binding_invalid")
    return window, calculation_rows


def _least_squares_next_log_return(log_prices: tuple[float, ...]) -> float:
    count = len(log_prices)
    mean_x = (count - 1) / 2.0
    mean_y = math.fsum(log_prices) / count
    denominator = math.fsum((index - mean_x) ** 2 for index in range(count))
    if denominator <= 0.0 or not math.isfinite(denominator):
        _integrity_error("adaptive_strategy_policy_least_squares_denominator_invalid")
    slope = (
        math.fsum((index - mean_x) * (value - mean_y) for index, value in enumerate(log_prices))
        / denominator
    )
    forecast_log_price = mean_y + slope * (count - mean_x)
    forecast_return = forecast_log_price - log_prices[-1]
    if not math.isfinite(forecast_return):
        _validation_error("adaptive_strategy_policy_expert_forecast_nonfinite")
    return forecast_return


def _expert_forecasts(log_prices: tuple[float, ...]) -> tuple[tuple[str, float], ...]:
    if len(log_prices) < 2:
        _integrity_error("adaptive_strategy_policy_expert_history_insufficient")
    returns = tuple(
        later - earlier for earlier, later in zip(log_prices, log_prices[1:], strict=False)
    )
    forecasts = (
        math.fsum(returns) / len(returns),
        returns[-1],
        -returns[-1],
        _least_squares_next_log_return(log_prices),
    )
    if any(not math.isfinite(value) for value in forecasts):
        _validation_error("adaptive_strategy_policy_expert_forecast_nonfinite")
    return tuple(zip(ORDERED_EXPERT_NAMES, forecasts, strict=True))


def _compute_policy(calculation_rows: tuple[Any, ...]) -> _PolicyComputation:
    if len(calculation_rows) < 3:
        _integrity_error("adaptive_strategy_policy_walk_forward_history_insufficient")
    closes: list[float] = []
    for row in calculation_rows:
        close = float(row.close)
        if not math.isfinite(close) or close <= 0.0:
            _validation_error("adaptive_strategy_policy_close_price_invalid")
        closes.append(close)
    log_prices = tuple(math.log(value) for value in closes)
    errors: dict[str, list[float]] = {name: [] for name in ORDERED_EXPERT_NAMES}
    for target_index in range(2, len(log_prices)):
        history = log_prices[:target_index]
        actual = log_prices[target_index] - log_prices[target_index - 1]
        for name, forecast in _expert_forecasts(history):
            error = actual - forecast
            if not math.isfinite(error):
                _validation_error("adaptive_strategy_policy_walk_forward_error_nonfinite")
            errors[name].append(error)
    evaluation_count = len(log_prices) - 2
    if evaluation_count <= 0 or any(len(values) != evaluation_count for values in errors.values()):
        _integrity_error("adaptive_strategy_policy_walk_forward_count_invalid")
    mse = {
        name: math.fsum(error * error for error in errors[name]) / evaluation_count
        for name in ORDERED_EXPERT_NAMES
    }
    if any(not math.isfinite(value) or value < 0.0 for value in mse.values()):
        _validation_error("adaptive_strategy_policy_walk_forward_mse_invalid")
    zero_error_names = tuple(name for name in ORDERED_EXPERT_NAMES if mse[name] == 0.0)
    if zero_error_names:
        perfect_weight = 1.0 / len(zero_error_names)
        weights = {
            name: perfect_weight if name in zero_error_names else 0.0
            for name in ORDERED_EXPERT_NAMES
        }
    else:
        minimum_mse = min(mse.values())
        relative_precision = {name: minimum_mse / mse[name] for name in ORDERED_EXPERT_NAMES}
        total_precision = math.fsum(relative_precision.values())
        if not math.isfinite(total_precision) or total_precision <= 0.0:
            _validation_error("adaptive_strategy_policy_adaptive_weight_invalid")
        weights = {
            name: relative_precision[name] / total_precision for name in ORDERED_EXPERT_NAMES
        }
    current = dict(_expert_forecasts(log_prices))
    expected = math.fsum(weights[name] * current[name] for name in ORDERED_EXPERT_NAMES)
    variance = math.fsum(
        weights[name] * (mse[name] + (current[name] - expected) ** 2)
        for name in ORDERED_EXPERT_NAMES
    )
    if variance < 0.0 and math.isclose(variance, 0.0, rel_tol=0.0, abs_tol=math.ulp(1.0)):
        variance = 0.0
    if not math.isfinite(expected) or not math.isfinite(variance) or variance < 0.0:
        _validation_error("adaptive_strategy_policy_ensemble_result_invalid")
    uncertainty = math.sqrt(variance)
    try:
        expected_move_bps = math.expm1(expected) * 10_000.0
        uncertainty_up_bps = math.expm1(uncertainty) * 10_000.0
        uncertainty_down_bps = -math.expm1(-uncertainty) * 10_000.0
        target = closes[-1] * math.exp(expected)
        uncertainty_lower_price = closes[-1] * math.exp(-uncertainty)
        uncertainty_upper_price = closes[-1] * math.exp(uncertainty)
        if expected > 0.0:
            direction = "UP"
        elif expected < 0.0:
            direction = "DOWN"
        else:
            direction = "NEUTRAL"
    except OverflowError:
        _validation_error("adaptive_strategy_policy_price_projection_nonfinite")
    strength_denominator = abs(expected) + uncertainty
    signal_strength = abs(expected) / strength_denominator if strength_denominator > 0.0 else 0.0
    numerical_values = (
        expected_move_bps,
        uncertainty_up_bps,
        uncertainty_down_bps,
        target,
        uncertainty_lower_price,
        uncertainty_upper_price,
        signal_strength,
        *weights.values(),
    )
    if (
        any(not math.isfinite(value) for value in numerical_values)
        or target <= 0.0
        or uncertainty_lower_price <= 0.0
        or uncertainty_upper_price <= 0.0
        or uncertainty_lower_price > closes[-1]
        or uncertainty_upper_price < closes[-1]
        or not 0.0 <= signal_strength <= 1.0
        or abs(math.fsum(weights.values()) - 1.0) > math.ulp(1.0) * len(ORDERED_EXPERT_NAMES)
    ):
        _validation_error("adaptive_strategy_policy_numerical_contract_invalid")
    return _PolicyComputation(
        raw_directional_proposal=direction,
        expected_log_return=expected,
        expected_move_bps=expected_move_bps,
        predictive_uncertainty_log_return=uncertainty,
        predictive_uncertainty_up_bps=uncertainty_up_bps,
        predictive_uncertainty_down_bps=uncertainty_down_bps,
        directional_signal_strength=signal_strength,
        reference_price=closes[-1],
        non_executable_target_price=target,
        non_executable_uncertainty_lower_price=uncertainty_lower_price,
        non_executable_uncertainty_upper_price=uncertainty_upper_price,
        walk_forward_evaluation_count=evaluation_count,
        ordered_expert_forecasts=tuple((name, current[name]) for name in ORDERED_EXPERT_NAMES),
        ordered_expert_mse=tuple((name, mse[name]) for name in ORDERED_EXPERT_NAMES),
        ordered_adaptive_weights=tuple((name, weights[name]) for name in ORDERED_EXPERT_NAMES),
    )


def _computation_material(computation: _PolicyComputation) -> dict[str, Any]:
    return {
        "policy_family": "ONLINE_WALK_FORWARD_INVERSE_ERROR_ENSEMBLE",
        "return_domain": "NATURAL_LOG_CLOSE_TO_CLOSE",
        "raw_directional_proposal": computation.raw_directional_proposal,
        "expected_log_return": computation.expected_log_return,
        "expected_move_bps": computation.expected_move_bps,
        "predictive_uncertainty_log_return": computation.predictive_uncertainty_log_return,
        "predictive_uncertainty_up_bps": computation.predictive_uncertainty_up_bps,
        "predictive_uncertainty_down_bps": computation.predictive_uncertainty_down_bps,
        "directional_signal_strength": computation.directional_signal_strength,
        "directional_signal_strength_semantics": "BOUNDED_UNCALIBRATED_RATIO_NOT_A_PROBABILITY",
        "reference_price": computation.reference_price,
        "non_executable_target_price": computation.non_executable_target_price,
        "non_executable_uncertainty_lower_price": (
            computation.non_executable_uncertainty_lower_price
        ),
        "non_executable_uncertainty_upper_price": (
            computation.non_executable_uncertainty_upper_price
        ),
        "walk_forward_evaluation_count": computation.walk_forward_evaluation_count,
        "ordered_expert_forecasts": [
            {"expert": name, "forecast_log_return": value}
            for name, value in computation.ordered_expert_forecasts
        ],
        "ordered_expert_mse": [
            {"expert": name, "walk_forward_mse": value}
            for name, value in computation.ordered_expert_mse
        ],
        "ordered_adaptive_weights": [
            {"expert": name, "weight": value}
            for name, value in computation.ordered_adaptive_weights
        ],
    }


def _semantic_material(
    *,
    publication: VerifiedStrategyOutputPublicationV1,
    transform: AuthenticatedStrategyTaTransformV1,
    calculation_rows: tuple[Any, ...],
    computation: _PolicyComputation,
    forecast_horizon_ms: int,
    dependencies: tuple[tuple[str, str], ...],
    dependency_root: str,
) -> dict[str, Any]:
    return {
        "schema_version": AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION,
        "evidence_classification": (
            AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_EVIDENCE_CLASSIFICATION
        ),
        "source_binding": {
            "symbol": publication.symbol,
            "timeframe": publication.timeframe,
            "output_id": publication.output_id,
            "output_payload_sha256": publication.output_payload_sha256,
            "output_receipt_sha256": publication.receipt_sha256,
            "upstream_ta_semantic_sha256": transform.semantic_content_sha256,
            "upstream_ta_audit_sha256": transform.audit_manifest_sha256,
            "upstream_exact_payload_sha256": transform.exact_payload_sha256,
            "calculation_row_count": len(calculation_rows),
            "calculation_window_candle_ids_sha256": (
                transform.calculation_window_candle_ids_sha256
            ),
            "calculation_window_first_candle_id": calculation_rows[0].candle_id,
            "latest_candle_id": calculation_rows[-1].candle_id,
            "latest_candle_raw_payload_hash": calculation_rows[-1].raw_payload_hash,
            "feature_cutoff": transform.feature_cutoff,
        },
        "adaptive_policy": {
            **_computation_material(computation),
            "feature_row_count": len(calculation_rows),
            "forecast_horizon_ms": forecast_horizon_ms,
            "expert_weights_source": "SAME_WINDOW_PRIOR_ONLY_WALK_FORWARD_ERROR",
            "future_rows_used": False,
            "zero_fill_used": False,
        },
        "implementation": {
            "implementation_sha256": (
                AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_IMPLEMENTATION_SHA256
            ),
            "configuration_sha256": (
                AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_CONFIGURATION_SHA256
            ),
            "module_code_sha256": dict(dependencies)["authenticated_adaptive_strategy_policy_v1"],
            "dependency_code_root_sha256": dependency_root,
        },
        "input_policy": {
            "market_performance_thresholds": [],
            "fixed_expert_weights": [],
            "score_cutoffs": [],
            "unreceipted_external_economics_consumed": [],
            "explicitly_excluded_economic_inputs": list(EXPLICITLY_EXCLUDED_ECONOMIC_INPUTS),
            "explicitly_excluded_mutable_inputs": list(EXPLICITLY_EXCLUDED_MUTABLE_INPUTS),
            "optional_provider_inputs_consumed": [],
        },
        "candidate_fields": {
            "cost_evidence_receipt_sha256": None,
            "expected_notional_receipt_sha256": None,
            "position_state_receipt_sha256": None,
            "leverage_envelope_receipt_sha256": None,
            "strategy_candidate": None,
        },
        "authorization": {
            "raw_directional_proposal_authenticated": True,
            **{name: False for name in _AUTHORITY_FIELDS},
            "runtime_wired": False,
        },
    }


def _audit_material(
    *,
    publication: VerifiedStrategyOutputPublicationV1,
    transform: AuthenticatedStrategyTaTransformV1,
    semantic_sha256: str,
    semantic_byte_count: int,
    semantic_address: SourcePayloadAddress,
    decision_time: str,
    generated_at: str,
    dependencies: tuple[tuple[str, str], ...],
    dependency_root: str,
) -> dict[str, Any]:
    return {
        "schema_version": AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION,
        "evidence_classification": (
            AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_DOWNSTREAM_STATUS,
        "semantic_content": {
            "payload_sha256": semantic_sha256,
            "payload_byte_count": semantic_byte_count,
            "address": _address_material(semantic_address),
        },
        "publication_receipt_binding": {
            "output_id": publication.output_id,
            "output_payload_sha256": publication.output_payload_sha256,
            "output_receipt_sha256": publication.receipt_sha256,
            "upstream_ta_semantic_sha256": transform.semantic_content_sha256,
            "upstream_ta_audit_sha256": transform.audit_manifest_sha256,
        },
        "point_in_time_clocks": {
            "feature_cutoff": transform.feature_cutoff,
            "max_source_available_at": transform.max_source_available_at,
            "writer_publication_available_at": transform.writer_publication_available_at,
            "capture_generated_at": transform.capture_generated_at,
            "transform_generated_at": transform.transform_generated_at,
            "output_generated_at": publication.generated_at,
            "output_available_at": publication.available_at,
            "output_receipt_postcommit_observed_at": (publication.receipt_postcommit_observed_at),
            "output_consumer_reopened_at": publication.consumer_reopened_at,
            "decision_time": decision_time,
            "generated_at": generated_at,
            "available_at": None,
            "execution_time": None,
        },
        "implementation": {
            "implementation_sha256": (
                AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_IMPLEMENTATION_SHA256
            ),
            "configuration_sha256": (
                AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_CONFIGURATION_SHA256
            ),
            "module_code_sha256": dict(dependencies)["authenticated_adaptive_strategy_policy_v1"],
            "dependency_code_root_sha256": dependency_root,
            "ordered_dependency_code_sha256s": [
                {"dependency_id": name, "code_sha256": digest} for name, digest in dependencies
            ],
        },
        "market_performance_thresholds": [],
        "unreceipted_external_economics_consumed": False,
        "runtime_wired": False,
        "authorization": {
            "raw_directional_proposal_authenticated": True,
            **{name: False for name in _AUTHORITY_FIELDS},
        },
    }


def _validate_clock_and_freshness(
    *,
    publication: VerifiedStrategyOutputPublicationV1,
    transform: AuthenticatedStrategyTaTransformV1,
    window: ValidatedOHLCVClosedWindow,
    decision_time: str,
    generated_at: str,
) -> None:
    clocks = tuple(
        _parse_clock(value, reason="adaptive_strategy_policy_clock_order_invalid")
        for value in (
            transform.feature_cutoff,
            transform.max_source_available_at,
            transform.writer_publication_available_at,
            transform.capture_generated_at,
            transform.transform_generated_at,
            publication.generated_at,
            publication.available_at,
            publication.receipt_postcommit_observed_at,
            publication.consumer_reopened_at,
            decision_time,
            generated_at,
        )
    )
    if any(left > right for left, right in zip(clocks, clocks[1:], strict=False)):
        _validation_error("adaptive_strategy_policy_clock_order_invalid")
    duration_ms = TIMEFRAME_DURATION_MS.get(publication.timeframe)
    if type(duration_ms) is not int or duration_ms <= 0:
        _integrity_error("adaptive_strategy_policy_timeframe_duration_invalid")
    expected_latest_close = (_clock_to_ms(clocks[-2]) // duration_ms) * duration_ms - 1
    if window.latest_economic_close_time != expected_latest_close:
        _validation_error("adaptive_strategy_policy_source_stale_at_decision")
    if window.max_available_at > _clock_to_ms(clocks[-2]):
        _validation_error("adaptive_strategy_policy_source_unavailable_at_decision")


def _validate_result(result: object) -> None:
    if type(result) is not AuthenticatedAdaptiveStrategyPolicyV1:
        _integrity_error("adaptive_strategy_policy_exact_result_type_required")
    policy = cast(AuthenticatedAdaptiveStrategyPolicyV1, result)
    if policy._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("adaptive_strategy_policy_factory_construction_required")
    publication, transform = _validated_publication(policy._publication)
    window, calculation_rows = _validated_exact_window(transform)
    computation = _compute_policy(calculation_rows)
    dependencies, dependency_root = _dependency_code_material()
    forecast_horizon_ms = TIMEFRAME_DURATION_MS[publication.timeframe]
    _validate_clock_and_freshness(
        publication=publication,
        transform=transform,
        window=window,
        decision_time=policy.decision_time,
        generated_at=policy.generated_at,
    )
    expected_semantic = _semantic_material(
        publication=publication,
        transform=transform,
        calculation_rows=calculation_rows,
        computation=computation,
        forecast_horizon_ms=forecast_horizon_ms,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    semantic_bytes = _canonical_json_bytes(expected_semantic)
    try:
        retained_semantic = policy.semantic_content_json.encode("ascii")
        retained_audit = policy.audit_manifest_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("adaptive_strategy_policy_retained_json_invalid")
    if not hmac.compare_digest(retained_semantic, semantic_bytes):
        _integrity_error("adaptive_strategy_policy_semantic_binding_invalid")
    expected_audit = _audit_material(
        publication=publication,
        transform=transform,
        semantic_sha256=hashlib.sha256(semantic_bytes).hexdigest(),
        semantic_byte_count=len(semantic_bytes),
        semantic_address=policy.semantic_content_address,
        decision_time=policy.decision_time,
        generated_at=policy.generated_at,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    audit_bytes = _canonical_json_bytes(expected_audit)
    expected_scalars = (
        policy.raw_directional_proposal == computation.raw_directional_proposal
        and policy.expected_log_return == computation.expected_log_return
        and policy.expected_move_bps == computation.expected_move_bps
        and policy.predictive_uncertainty_log_return
        == computation.predictive_uncertainty_log_return
        and policy.predictive_uncertainty_up_bps == computation.predictive_uncertainty_up_bps
        and policy.predictive_uncertainty_down_bps == computation.predictive_uncertainty_down_bps
        and policy.directional_signal_strength == computation.directional_signal_strength
        and policy.reference_price == computation.reference_price
        and policy.non_executable_target_price == computation.non_executable_target_price
        and policy.non_executable_uncertainty_lower_price
        == computation.non_executable_uncertainty_lower_price
        and policy.non_executable_uncertainty_upper_price
        == computation.non_executable_uncertainty_upper_price
        and policy.walk_forward_evaluation_count == computation.walk_forward_evaluation_count
        and policy.ordered_expert_forecasts == computation.ordered_expert_forecasts
        and policy.ordered_expert_mse == computation.ordered_expert_mse
        and policy.ordered_adaptive_weights == computation.ordered_adaptive_weights
    )
    if (
        policy.schema_version != AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION
        or policy.audit_schema_version
        != AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION
        or policy.evidence_classification
        != AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_EVIDENCE_CLASSIFICATION
        or policy.downstream_status != AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_DOWNSTREAM_STATUS
        or policy.symbol != publication.symbol
        or policy.timeframe != publication.timeframe
        or policy.output_id != publication.output_id
        or policy.output_payload_sha256 != publication.output_payload_sha256
        or policy.output_receipt_sha256 != publication.receipt_sha256
        or policy.upstream_ta_semantic_sha256 != transform.semantic_content_sha256
        or policy.upstream_ta_audit_sha256 != transform.audit_manifest_sha256
        or policy.upstream_exact_payload_sha256 != transform.exact_payload_sha256
        or policy.calculation_row_count != len(calculation_rows)
        or policy.calculation_window_candle_ids_sha256
        != transform.calculation_window_candle_ids_sha256
        or policy.latest_candle_id != transform.latest_candle_id
        or policy.latest_candle_raw_payload_hash != transform.latest_candle_raw_payload_hash
        or policy.forecast_horizon_ms != forecast_horizon_ms
        or not expected_scalars
        or policy.implementation_sha256
        != AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_IMPLEMENTATION_SHA256
        or policy.configuration_sha256
        != AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_CONFIGURATION_SHA256
        or policy.module_code_sha256
        != dict(dependencies)["authenticated_adaptive_strategy_policy_v1"]
        or policy.dependency_code_root_sha256 != dependency_root
        or policy.dependency_code_sha256s != dependencies
        or policy.feature_cutoff != transform.feature_cutoff
        or policy.max_source_available_at != transform.max_source_available_at
        or policy.output_generated_at != publication.generated_at
        or policy.output_available_at != publication.available_at
        or policy.output_receipt_postcommit_observed_at
        != publication.receipt_postcommit_observed_at
        or policy.output_consumer_reopened_at != publication.consumer_reopened_at
        or policy.available_at is not None
        or policy.execution_time is not None
        or policy.semantic_content_sha256 != hashlib.sha256(semantic_bytes).hexdigest()
        or policy.semantic_content_byte_count != len(semantic_bytes)
        or policy.audit_manifest_sha256 != hashlib.sha256(audit_bytes).hexdigest()
        or policy.audit_manifest_byte_count != len(audit_bytes)
        or not hmac.compare_digest(retained_audit, audit_bytes)
        or any(getattr(policy, name) is not False for name in _AUTHORITY_FIELDS)
        or policy.publication_receipt_authenticated is not True
        or policy.upstream_transform_authenticated is not True
        or policy.exact_closed_window_revalidated is not True
        or policy.adaptive_weights_rederived is not True
        or policy.semantic_and_audit_cas_reopened is not True
        or policy.raw_directional_proposal_authenticated is not True
        or policy.market_performance_thresholds_applied is not False
        or policy.unreceipted_external_economics_consumed is not False
        or any(
            value is not None
            for value in (
                policy.cost_evidence_receipt_sha256,
                policy.expected_notional_receipt_sha256,
                policy.position_state_receipt_sha256,
                policy.leverage_envelope_receipt_sha256,
            )
        )
        or policy.runtime_wired is not False
        or type(policy._source_payload_store) is not ImmutableSourcePayloadStore
    ):
        _integrity_error("adaptive_strategy_policy_result_binding_invalid")
    _validate_address(
        policy.semantic_content_address,
        expected_sha256=policy.semantic_content_sha256,
        expected_byte_count=policy.semantic_content_byte_count,
        reason="adaptive_strategy_policy_semantic_address_invalid",
    )
    _validate_address(
        policy.audit_manifest_address,
        expected_sha256=policy.audit_manifest_sha256,
        expected_byte_count=policy.audit_manifest_byte_count,
        reason="adaptive_strategy_policy_audit_address_invalid",
    )
    _fresh_readback(
        policy._source_payload_store,
        policy.semantic_content_address,
        retained_semantic,
        reason="adaptive_strategy_policy_semantic_cas_readback_failed",
    )
    _fresh_readback(
        policy._source_payload_store,
        policy.audit_manifest_address,
        retained_audit,
        reason="adaptive_strategy_policy_audit_cas_readback_failed",
    )


def build_authenticated_adaptive_strategy_policy_v1(
    publication: VerifiedStrategyOutputPublicationV1,
    source_payload_store: ImmutableSourcePayloadStore,
    *,
    policy_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AuthenticatedAdaptiveStrategyPolicyV1:
    """Build and immutably capture one PIT-safe, TA-only adaptive proposal."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("adaptive_strategy_policy_authentic_store_required")
    publication, transform = _validated_publication(publication)
    window, calculation_rows = _validated_exact_window(transform)
    decision_time, _decision = _sample_clock(
        policy_clock,
        reason="adaptive_strategy_policy_decision_clock_invalid",
    )
    computation = _compute_policy(calculation_rows)
    generated_at, _generated = _sample_clock(
        policy_clock,
        reason="adaptive_strategy_policy_generation_clock_invalid",
    )
    _validate_clock_and_freshness(
        publication=publication,
        transform=transform,
        window=window,
        decision_time=decision_time,
        generated_at=generated_at,
    )
    dependencies, dependency_root = _dependency_code_material()
    forecast_horizon_ms = TIMEFRAME_DURATION_MS[publication.timeframe]
    semantic = _semantic_material(
        publication=publication,
        transform=transform,
        calculation_rows=calculation_rows,
        computation=computation,
        forecast_horizon_ms=forecast_horizon_ms,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    semantic_bytes = _canonical_json_bytes(semantic)
    semantic_sha256 = hashlib.sha256(semantic_bytes).hexdigest()
    semantic_address = _put_immutable(
        source_payload_store,
        semantic_bytes,
        reason="adaptive_strategy_policy_semantic_cas_capture_failed",
    )
    audit = _audit_material(
        publication=publication,
        transform=transform,
        semantic_sha256=semantic_sha256,
        semantic_byte_count=len(semantic_bytes),
        semantic_address=semantic_address,
        decision_time=decision_time,
        generated_at=generated_at,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    audit_bytes = _canonical_json_bytes(audit)
    audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
    audit_address = _put_immutable(
        source_payload_store,
        audit_bytes,
        reason="adaptive_strategy_policy_audit_cas_capture_failed",
    )
    return AuthenticatedAdaptiveStrategyPolicyV1(
        schema_version=AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION,
        audit_schema_version=AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION,
        evidence_classification=(AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_EVIDENCE_CLASSIFICATION),
        downstream_status=AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_DOWNSTREAM_STATUS,
        symbol=publication.symbol,
        timeframe=publication.timeframe,
        output_id=publication.output_id,
        output_payload_sha256=publication.output_payload_sha256,
        output_receipt_sha256=publication.receipt_sha256,
        upstream_ta_semantic_sha256=transform.semantic_content_sha256,
        upstream_ta_audit_sha256=transform.audit_manifest_sha256,
        upstream_exact_payload_sha256=transform.exact_payload_sha256,
        calculation_row_count=len(calculation_rows),
        calculation_window_candle_ids_sha256=transform.calculation_window_candle_ids_sha256,
        latest_candle_id=transform.latest_candle_id,
        latest_candle_raw_payload_hash=transform.latest_candle_raw_payload_hash,
        forecast_horizon_ms=forecast_horizon_ms,
        raw_directional_proposal=computation.raw_directional_proposal,
        expected_log_return=computation.expected_log_return,
        expected_move_bps=computation.expected_move_bps,
        predictive_uncertainty_log_return=(computation.predictive_uncertainty_log_return),
        predictive_uncertainty_up_bps=computation.predictive_uncertainty_up_bps,
        predictive_uncertainty_down_bps=computation.predictive_uncertainty_down_bps,
        directional_signal_strength=computation.directional_signal_strength,
        reference_price=computation.reference_price,
        non_executable_target_price=computation.non_executable_target_price,
        non_executable_uncertainty_lower_price=(computation.non_executable_uncertainty_lower_price),
        non_executable_uncertainty_upper_price=(computation.non_executable_uncertainty_upper_price),
        walk_forward_evaluation_count=computation.walk_forward_evaluation_count,
        ordered_expert_forecasts=computation.ordered_expert_forecasts,
        ordered_expert_mse=computation.ordered_expert_mse,
        ordered_adaptive_weights=computation.ordered_adaptive_weights,
        implementation_sha256=(AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_IMPLEMENTATION_SHA256),
        configuration_sha256=(AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_CONFIGURATION_SHA256),
        module_code_sha256=dict(dependencies)["authenticated_adaptive_strategy_policy_v1"],
        dependency_code_root_sha256=dependency_root,
        dependency_code_sha256s=dependencies,
        feature_cutoff=transform.feature_cutoff,
        max_source_available_at=transform.max_source_available_at,
        output_generated_at=publication.generated_at,
        output_available_at=publication.available_at,
        output_receipt_postcommit_observed_at=publication.receipt_postcommit_observed_at,
        output_consumer_reopened_at=publication.consumer_reopened_at,
        decision_time=decision_time,
        generated_at=generated_at,
        available_at=None,
        execution_time=None,
        semantic_content_sha256=semantic_sha256,
        semantic_content_byte_count=len(semantic_bytes),
        semantic_content_json=semantic_bytes.decode("ascii"),
        semantic_content_address=semantic_address,
        audit_manifest_sha256=audit_sha256,
        audit_manifest_byte_count=len(audit_bytes),
        audit_manifest_json=audit_bytes.decode("ascii"),
        audit_manifest_address=audit_address,
        _publication=publication,
        _source_payload_store=source_payload_store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_AUDIT_SCHEMA_VERSION",
    "AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_CONFIGURATION_SHA256",
    "AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_DOWNSTREAM_STATUS",
    "AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_EVIDENCE_CLASSIFICATION",
    "AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_IMPLEMENTATION_SHA256",
    "AUTHENTICATED_ADAPTIVE_STRATEGY_POLICY_V1_SCHEMA_VERSION",
    "EXPLICITLY_EXCLUDED_ECONOMIC_INPUTS",
    "EXPLICITLY_EXCLUDED_MUTABLE_INPUTS",
    "ORDERED_EXPERT_NAMES",
    "AuthenticatedAdaptiveStrategyPolicyV1",
    "AuthenticatedAdaptiveStrategyPolicyV1Error",
    "AuthenticatedAdaptiveStrategyPolicyV1IntegrityError",
    "AuthenticatedAdaptiveStrategyPolicyV1ValidationError",
    "build_authenticated_adaptive_strategy_policy_v1",
]
