"""Deterministic strategy TA derived from writer-authenticated OHLCV.

This boundary consumes only a factory-authenticated
``CanonicalOhlcvWriterBoundAtomicCapture``.  It never reads a mutable Redis
key and it deliberately has no parameter through which the unreceipted
``v2:live_gate:state`` document (or any other external economics document) can
enter the calculation.

The semantic artifact contains the exact stable source, calculation, and
implementation identities.  Redis observation clocks, local generation
clocks, and read-receipt identities remain in a separate immutable audit
manifest so repeated captures of one unchanged writer publication produce the
same semantic digest.  Neither artifact claims post-commit availability,
strategy admission, trainer admission, prediction, paper trading, or live
execution authority.
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
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.full_talib_ta import service as full_talib_service
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_atomic_receipt_adapter as atomic_adapter_module,
)
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_writer_bound_atomic_capture_v1 as writer_bound_module,
)
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_writer_receipt_consumer_v1 as writer_consumer_module,
)
from v2.backend.app.services.native_trainer import (
    model_ta_technical_dependency_contract as ta_dependency_module,
)
from v2.backend.app.services.native_trainer import (
    ohlcv_closed_window_schema as ohlcv_schema_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_bound_atomic_capture_v1 import (
    CanonicalOhlcvWriterBoundAtomicCapture,
    CanonicalOhlcvWriterBoundAtomicCaptureError,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
    CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256,
    CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256,
    DEPLOYED_TALIB_ENVIRONMENT_SHA256,
    LOOKBACK_MANIFEST_SHA256,
    MODEL_FEATURE_ABI_SHA256,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    STRICT_LATEST_OUTPUT_SEMANTICS,
    TA_OHLC_ABI_LEAVES_SHA256,
    ModelTATechnicalDependencyContract,
    ModelTATechnicalDependencyContractError,
    build_model_ta_technical_dependency_contract,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    require_contiguous_window,
    validate_ohlcv_closed_window,
)

AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION: Final = (
    "authenticated_strategy_ta_transform_v1"
)
AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_MANIFEST_SCHEMA_VERSION: Final = (
    "authenticated_strategy_ta_transform_audit_manifest_v1"
)
AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_EVIDENCE_CLASSIFICATION: Final = (
    "WRITER_AUTHENTICATED_EXACT_OHLCV_DETERMINISTIC_TA_TRANSFORM"
)
AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_DOWNSTREAM_STATUS: Final = (
    "TRANSFORM_PROOF_ONLY_NO_AVAILABILITY_ADMISSION_PREDICTION_OR_EXECUTION_AUTHORITY"
)
AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_ID: Final = (
    "strategy_full_talib_writer_bound_exact_suffix_v1"
)

# These are calculation dependencies, not market-selection thresholds.  A
# missing critical value is masked/fail-closed instead of being zero-filled.
REQUIRED_STRATEGY_TA_INDICATORS: Final = (
    "bb_width_pct",
    "ema_20",
    "ema_50",
    "rsi_14",
    "ta_ADX",
    "ta_ATR_14",
    "ta_NATR",
)
EXPLICITLY_EXCLUDED_MUTABLE_INPUTS: Final = ("v2:live_gate:state",)
EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS: Final = (
    "fvg",
    "liquidity_zones",
    "liquidation_levels",
    "sweep_risk",
    "microstructure",
    "microstructure_trust",
    "orderbook",
    "orderbook_top",
    "orderbook_rest",
    "trade_tape",
    "trade_tape_confirmation",
    "coinglass",
    "moralis",
    "altdata_confluence",
)

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\." r"[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()
_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024

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
_OBSERVATION_ONLY_FIELDS = (
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
    "available_at",
    "decision_time",
    "execution_time",
)
_PROVENANCE_ONLY_FIELDS = (
    "revision_id",
    "producer_role",
    "producer_code_sha256",
    "producer_config_sha256",
    "writer_receipt_sha256",
    "trusted_allowlist_sha256",
    "writer_publication_available_at",
    "composite_manifest_sha256",
    "composite_manifest_address",
    "pre_writer_tuple_manifest_sha256",
    "pre_writer_tuple_manifest_address",
    "atomic_batch_id",
    "atomic_batch_material_sha256",
    "atomic_suffix_digest_sha256",
    "atomic_suffix_manifest_sha256",
    "atomic_suffix_manifest_address",
    "ordered_selected_candle_receipt_sha256s",
    "post_writer_tuple_manifest_sha256",
    "post_writer_tuple_manifest_address",
)

_IMPLEMENTATION_MANIFEST = {
    "schema_version": "authenticated_strategy_ta_implementation_manifest_v1",
    "implementation_id": AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_ID,
    "source_factory": "capture_canonical_ohlcv_writer_bound_atomic",
    "calculation_function": "build_full_talib_ta_closed_candidate",
    "calculation_candidate_schema_version": (
        full_talib_service.FULL_TALIB_TA_CLOSED_CANDIDATE_SCHEMA_VERSION
    ),
    "calculation_window": "EXACT_FINAL_CONTIGUOUS_SUFFIX",
    "semantic_identity": (
        "SOURCE_AND_TRANSFORM_SEMANTICS_ONLY_EXCLUDES_OBSERVATION_AND_GENERATION_CLOCKS"
    ),
    "audit_identity": ("BINDS_COMPLETE_UPSTREAM_RECEIPT_CHAIN_OBSERVATION_CLOCKS_AND_GENERATED_AT"),
    "latest_output_semantics": STRICT_LATEST_OUTPUT_SEMANTICS,
    "reference_price": "LATEST_SELECTED_CLOSED_CANDLE_CLOSE",
    "optional_indicator_policy": "RETAIN_EXPLICIT_REJECTIONS_NEVER_FILL",
    "availability_policy": "NONE_UNTIL_LATER_POSTCOMMIT_RECEIPT",
    "canonical_json": {
        "sort_keys": True,
        "ensure_ascii": True,
        "allow_nan": False,
        "separators": [",", ":"],
    },
}
_CONFIGURATION_CONTRACT = {
    "schema_version": "authenticated_strategy_ta_configuration_v1",
    "required_contiguous_rows": CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
    "required_strategy_indicators": list(REQUIRED_STRATEGY_TA_INDICATORS),
    "explicitly_excluded_mutable_inputs": list(EXPLICITLY_EXCLUDED_MUTABLE_INPUTS),
    "explicitly_excluded_optional_provider_groups": list(
        EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS
    ),
    "source_transport": "WRITER_RECEIPT_SANDWICH_PLUS_ATOMIC_PER_CANDLE_RECEIPTS",
    "source_payload": "EXACT_BINARY_CANONICAL_CLOSED_OHLCV",
    "latest_interval_policy": "LATEST_COMPLETED_INTERVAL_AT_TRANSFORM_GENERATION",
    "optional_indicator_policy": "MISSING_WITH_EXPLICIT_REASON",
    "nonfinite_policy": "REJECT_CRITICAL_RETAIN_OPTIONAL_REJECTION",
    "zero_fill_policy": "FORBIDDEN",
    "market_performance_thresholds": [],
    "unreceipted_external_economics": "FORBIDDEN",
    "model_ta_dependency_contract_sha256": (MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256),
    "model_feature_abi_sha256": MODEL_FEATURE_ABI_SHA256,
    "ta_full_feature_map_sha256": CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256,
    "ta_full_fields_sha256": CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256,
    "ta_ohlcv_abi_leaves_sha256": TA_OHLC_ABI_LEAVES_SHA256,
    "lookback_manifest_sha256": LOOKBACK_MANIFEST_SHA256,
    "deployed_talib_environment_sha256": DEPLOYED_TALIB_ENVIRONMENT_SHA256,
}


class AuthenticatedStrategyTaTransformV1Error(RuntimeError):
    """Base fail-closed strategy-TA transform error."""


class AuthenticatedStrategyTaTransformV1ValidationError(AuthenticatedStrategyTaTransformV1Error):
    """The source, clock, environment, or calculation is not eligible."""


class AuthenticatedStrategyTaTransformV1IntegrityError(AuthenticatedStrategyTaTransformV1Error):
    """A proof, dependency, artifact, or immutable readback did not bind."""


@dataclass(frozen=True, slots=True)
class AuthenticatedStrategyTaTransformV1:
    """Factory-authenticated immutable strategy-TA transform result."""

    schema_version: str
    manifest_schema_version: str
    evidence_classification: str
    downstream_status: str
    symbol: str
    timeframe: str
    source_key: str
    revision_id: str
    producer_role: str
    producer_code_sha256: str
    producer_config_sha256: str
    writer_receipt_sha256: str
    trusted_allowlist_sha256: str
    exact_payload_sha256: str
    exact_payload_byte_count: int
    canonical_payload_address: SourcePayloadAddress
    upstream_composite_manifest_sha256: str
    upstream_composite_manifest_address: SourcePayloadAddress
    calculation_row_count: int
    calculation_window_candle_ids_sha256: str
    latest_candle_id: str
    latest_candle_raw_payload_hash: str
    indicator_count: int
    indicator_names_sha256: str
    reference_price: float
    implementation_sha256: str
    configuration_sha256: str
    module_code_sha256: str
    dependency_code_root_sha256: str
    dependency_code_sha256s: tuple[tuple[str, str], ...]
    model_ta_dependency_contract_sha256: str
    deployed_talib_environment_sha256: str
    feature_cutoff: str
    max_source_available_at: str
    writer_publication_available_at: str
    capture_generated_at: str
    transform_generated_at: str
    transform_generated_at_ms: int
    available_at: None
    decision_time: None
    execution_time: None
    semantic_content_sha256: str
    semantic_content_byte_count: int
    semantic_content_json: str = field(repr=False)
    semantic_content_address: SourcePayloadAddress
    audit_manifest_sha256: str
    audit_manifest_byte_count: int
    audit_manifest_json: str = field(repr=False)
    audit_manifest_address: SourcePayloadAddress
    _source_capture: CanonicalOhlcvWriterBoundAtomicCapture = field(
        repr=False,
        compare=False,
    )
    _source_payload_store: ImmutableSourcePayloadStore = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    writer_authenticated_source_verified: bool = field(default=True, init=False)
    deterministic_semantic_identity_verified: bool = field(default=True, init=False)
    transform_dependencies_verified: bool = field(default=True, init=False)
    semantic_and_audit_cas_reopened: bool = field(default=True, init=False)
    unreceipted_external_economics_consumed: bool = field(default=False, init=False)
    market_performance_thresholds_applied: bool = field(default=False, init=False)
    runtime_wired: bool = field(default=False, init=False)
    durable_ledger_appended: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    strategy_output_authorized: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    order_submission_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_result(self)

    @property
    def source_capture(self) -> CanonicalOhlcvWriterBoundAtomicCapture:
        _validate_result(self)
        return self._source_capture

    @property
    def semantic_content(self) -> dict[str, Any]:
        _validate_result(self)
        return cast(dict[str, Any], json.loads(self.semantic_content_json))

    @property
    def audit_manifest(self) -> dict[str, Any]:
        _validate_result(self)
        return cast(dict[str, Any], json.loads(self.audit_manifest_json))

    @property
    def indicators(self) -> dict[str, float]:
        semantic = self.semantic_content
        return cast(dict[str, float], semantic["strategy_ta"]["indicators"])


def _validation_error(reason: str) -> NoReturn:
    raise AuthenticatedStrategyTaTransformV1ValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise AuthenticatedStrategyTaTransformV1IntegrityError(reason) from None


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
        _integrity_error("authenticated_strategy_ta_json_encoding_invalid")
    if not encoded or len(encoded) > _MAX_ARTIFACT_BYTES:
        _integrity_error("authenticated_strategy_ta_artifact_size_invalid")
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_SHA256: Final = _sha256(
    _IMPLEMENTATION_MANIFEST
)
AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_CONFIGURATION_SHA256: Final = _sha256(
    _CONFIGURATION_CONTRACT
)


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
    return ((delta.days * 86_400 + delta.seconds) * 1_000) + (delta.microseconds // 1_000)


def _ms_to_clock(value: int) -> str:
    if type(value) is not int or value < 0:
        _integrity_error("authenticated_strategy_ta_source_clock_invalid")
    try:
        return (_EPOCH + timedelta(milliseconds=value)).strftime(_CLOCK_FORMAT)
    except (OverflowError, ValueError):
        _integrity_error("authenticated_strategy_ta_source_clock_invalid")


def _sample_clock(clock: Callable[[], datetime]) -> tuple[str, int]:
    if not callable(clock):
        _validation_error("authenticated_strategy_ta_clock_not_callable")
    try:
        observed = clock()
    except Exception:  # noqa: BLE001 - hostile clock detail must not escape
        _validation_error("authenticated_strategy_ta_clock_failed")
    if type(observed) is not datetime or observed.tzinfo is None:
        _validation_error("authenticated_strategy_ta_clock_invalid")
    normalized = observed.astimezone(UTC)
    text = normalized.strftime(_CLOCK_FORMAT)
    parsed = _parse_clock(text, reason="authenticated_strategy_ta_clock_invalid")
    return text, _clock_to_ms(parsed)


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _validated_address(
    value: object,
    *,
    expected_sha256: str,
    expected_byte_count: int,
    reason: str,
) -> SourcePayloadAddress:
    if type(value) is not SourcePayloadAddress:
        _integrity_error(reason)
    address = cast(SourcePayloadAddress, value)
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != expected_sha256
        or address.payload_byte_count != expected_byte_count
        or address.relative_path != f"sha256/{expected_sha256[:2]}/{expected_sha256}"
    ):
        _integrity_error(reason)
    return address


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
        raise AuthenticatedStrategyTaTransformV1IntegrityError(reason) from exc
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
        raise AuthenticatedStrategyTaTransformV1IntegrityError(reason) from exc
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
        _integrity_error("authenticated_strategy_ta_transform_code_unavailable")
    if not source:
        _integrity_error("authenticated_strategy_ta_transform_code_unavailable")
    return hashlib.sha256(source).hexdigest()


def _dependency_code_material() -> tuple[tuple[tuple[str, str], ...], str]:
    dependencies = (
        (
            "authenticated_strategy_ta_transform_v1",
            _self_code_sha256(),
        ),
        (
            "full_talib_ta_service",
            _read_module_sha256(
                full_talib_service,
                expected_name="service.py",
                reason="authenticated_strategy_ta_full_talib_code_unavailable",
            ),
        ),
        (
            "model_ta_technical_dependency_contract",
            _read_module_sha256(
                ta_dependency_module,
                expected_name="model_ta_technical_dependency_contract.py",
                reason="authenticated_strategy_ta_dependency_contract_code_unavailable",
            ),
        ),
        (
            "writer_bound_atomic_capture",
            _read_module_sha256(
                writer_bound_module,
                expected_name="canonical_ohlcv_writer_bound_atomic_capture_v1.py",
                reason="authenticated_strategy_ta_source_contract_code_unavailable",
            ),
        ),
        (
            "canonical_ohlcv_atomic_receipt_adapter",
            _read_module_sha256(
                atomic_adapter_module,
                expected_name="canonical_ohlcv_atomic_receipt_adapter.py",
                reason="authenticated_strategy_ta_atomic_adapter_code_unavailable",
            ),
        ),
        (
            "canonical_ohlcv_writer_receipt_consumer",
            _read_module_sha256(
                writer_consumer_module,
                expected_name="canonical_ohlcv_writer_receipt_consumer_v1.py",
                reason="authenticated_strategy_ta_writer_consumer_code_unavailable",
            ),
        ),
        (
            "ohlcv_closed_window_schema",
            _read_module_sha256(
                ohlcv_schema_module,
                expected_name="ohlcv_closed_window_schema.py",
                reason="authenticated_strategy_ta_ohlcv_schema_code_unavailable",
            ),
        ),
    )
    if any(_SHA256_RE.fullmatch(digest) is None for _name, digest in dependencies):
        _integrity_error("authenticated_strategy_ta_dependency_code_hash_invalid")
    root = _sha256(
        {
            "schema_version": "authenticated_strategy_ta_code_dependencies_v1",
            "ordered_dependencies": [
                {"dependency_id": name, "code_sha256": digest} for name, digest in dependencies
            ],
        }
    )
    return dependencies, root


def _validated_technical_contract() -> ModelTATechnicalDependencyContract:
    try:
        contract = build_model_ta_technical_dependency_contract()
    except ModelTATechnicalDependencyContractError as exc:
        raise AuthenticatedStrategyTaTransformV1ValidationError(
            "authenticated_strategy_ta_dependency_contract_rejected"
        ) from exc
    if (
        contract.contract_sha256 != MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256
        or contract.talib_environment_sha256 != DEPLOYED_TALIB_ENVIRONMENT_SHA256
        or contract.model_feature_abi_sha256 != MODEL_FEATURE_ABI_SHA256
        or contract.ta_full_feature_map_sha256 != CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256
        or contract.ta_full_fields_sha256 != CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256
        or contract.ta_ohlcv_abi_leaves_sha256 != TA_OHLC_ABI_LEAVES_SHA256
        or contract.lookback_manifest_sha256 != LOOKBACK_MANIFEST_SHA256
        or contract.current_timeframe_minimum_source_rows != CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        or contract.strict_latest_output_semantics != STRICT_LATEST_OUTPUT_SEMANTICS
        or contract.reads_mutable_ta_payload is not False
        or contract.grants_market_admission is not False
        or contract.grants_trainer_admission is not False
        or contract.grants_feature_publication is not False
        or contract.grants_live_execution is not False
        or contract.authorizes_order_submission is not False
    ):
        _integrity_error("authenticated_strategy_ta_dependency_contract_binding_invalid")
    return contract


def _validated_source_capture(
    capture: object,
) -> tuple[CanonicalOhlcvWriterBoundAtomicCapture, ValidatedOHLCVClosedWindow]:
    if type(capture) is not CanonicalOhlcvWriterBoundAtomicCapture:
        _validation_error("authenticated_strategy_ta_writer_bound_capture_required")
    typed = cast(CanonicalOhlcvWriterBoundAtomicCapture, capture)
    try:
        _ = typed.composite_manifest
        atomic = typed.atomic_capture
        exact_payload_bytes = typed.exact_canonical_payload_bytes
    except CanonicalOhlcvWriterBoundAtomicCaptureError as exc:
        raise AuthenticatedStrategyTaTransformV1IntegrityError(
            "authenticated_strategy_ta_source_capture_revalidation_failed"
        ) from exc
    try:
        window = validate_ohlcv_closed_window(
            exact_payload_bytes,
            symbol=typed.symbol,
            timeframe=typed.timeframe,
            required_contiguous_lookback=CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
        )
        expected_window = require_contiguous_window(
            atomic.validated_window,
            required_contiguous_lookback=CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
        )
    except OHLCVClosedWindowValidationError as exc:
        raise AuthenticatedStrategyTaTransformV1ValidationError(
            "authenticated_strategy_ta_exact_89_row_window_unavailable"
        ) from exc
    if (
        type(window) is not ValidatedOHLCVClosedWindow
        or window != expected_window
        or window.required_contiguous_lookback != CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        or window.required_contiguous_window_satisfied is not True
        or atomic.selected_row_count < CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        or atomic.selected_row_count != window.contiguous_suffix_count
        or atomic.selected_source_end_index_exclusive != window.row_count
        or atomic.selected_source_start_index != window.row_count - window.contiguous_suffix_count
        or len(atomic.selected_candle_ids) != atomic.selected_row_count
        or len(atomic.selected_exact_payload_sha256s) != atomic.selected_row_count
    ):
        _validation_error("authenticated_strategy_ta_exact_suffix_contract_invalid")
    return typed, window


def _validated_candidate(
    candidate: object,
    *,
    capture: CanonicalOhlcvWriterBoundAtomicCapture,
    window: ValidatedOHLCVClosedWindow,
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        _integrity_error("authenticated_strategy_ta_candidate_mapping_required")
    value = dict(candidate)
    indicators = value.get("indicators")
    if not isinstance(indicators, Mapping) or not indicators:
        _validation_error("authenticated_strategy_ta_indicators_unavailable")
    normalized_indicators: dict[str, float] = {}
    for name, raw in indicators.items():
        if (
            type(name) is not str
            or not name
            or type(raw) not in (int, float)
            or not math.isfinite(float(raw))
        ):
            _validation_error("authenticated_strategy_ta_indicator_contract_invalid")
        normalized_indicators[name] = float(raw)
    missing_required = tuple(
        name for name in REQUIRED_STRATEGY_TA_INDICATORS if name not in normalized_indicators
    )
    if missing_required:
        _validation_error(
            "authenticated_strategy_ta_required_indicators_missing:" + ",".join(missing_required)
        )
    try:
        atomic = capture.atomic_capture
    except CanonicalOhlcvWriterBoundAtomicCaptureError as exc:
        raise AuthenticatedStrategyTaTransformV1IntegrityError(
            "authenticated_strategy_ta_source_capture_revalidation_failed"
        ) from exc
    latest = window.rows[-1]
    expected_identity = (
        value.get("schema_version")
        == full_talib_service.FULL_TALIB_TA_CLOSED_CANDIDATE_SCHEMA_VERSION
        and value.get("symbol") == capture.symbol
        and value.get("timeframe") == capture.timeframe
        and value.get("source_ohlcv_key") == capture.source_key
        and value.get("source_exact_payload_sha256") == capture.exact_payload_sha256
        and value.get("source_exact_payload_byte_count") == capture.exact_payload_byte_count
        and value.get("source_row_count") == capture.row_count
        and value.get("source_contiguous_suffix_count") == window.contiguous_suffix_count
        and value.get("calculation_row_count") == CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        and value.get("calculation_normalized_row_count") == CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        and value.get("calculation_required_contiguous_rows")
        == CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        and value.get("calculation_window_first_candle_id")
        == atomic.selected_candle_ids[-CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS]
        and value.get("calculation_window_latest_candle_id") == atomic.selected_candle_ids[-1]
        and value.get("latest_candle_id") == latest.candle_id
        and value.get("latest_candle_raw_payload_hash") == latest.raw_payload_hash
        and value.get("latest_closed_candle_open_ts_ms") == latest.candle_open_time
        and value.get("latest_closed_candle_close_ts_ms") == window.latest_economic_close_time
        and value.get("source_producer_event_time_ms") == window.latest_producer_event_time
        and value.get("source_ingested_at_ms") == window.max_ingested_at
        and value.get("source_available_at_ms") == window.max_available_at
    )
    if not expected_identity:
        _integrity_error("authenticated_strategy_ta_candidate_source_identity_invalid")
    expected_false = (
        "redis_read_receipt_emitted",
        "immutable_cas_captured",
        "publication_committed",
        "consumer_eligible",
        "trainer_consumable",
        "trainer_admission_granted",
        "live_execution_authorized",
        "exchange_action_taken",
        "places_real_order",
    )
    if (
        any(value.get(name) is not False for name in expected_false)
        or value.get("available_at") is not None
        or value.get("publication_observed_at") is not None
        or value.get("closed_candles_only") is not True
        or value.get("candle_closed_confirmed") is not True
        or value.get("exact_source_schema_validated") is not True
        or value.get("producer_finality_contract_validated") is not True
        or value.get("calculation_normalized_exact_source_identity") is not True
        or value.get("no_zero_fill") is not True
        or value.get("live_symbols") != []
        or value.get("live_gate") != full_talib_service.LIVE_GATE_BLOCKED
    ):
        _integrity_error("authenticated_strategy_ta_candidate_authority_invalid")
    computed = value.get("computed_functions")
    skipped = value.get("skipped_functions")
    rejected = value.get("strict_latest_output_rejections")
    families = value.get("families_present")
    if (
        not isinstance(computed, list)
        or any(type(name) is not str or not name for name in computed)
        or len(computed) != len(set(computed))
        or not isinstance(skipped, Mapping)
        or any(type(key) is not str or type(reason) is not str for key, reason in skipped.items())
        or not isinstance(rejected, Mapping)
        or any(type(key) is not str or type(reason) is not str for key, reason in rejected.items())
        or not isinstance(families, list)
        or any(type(name) is not str or not name for name in families)
        or value.get("indicator_count") != len(normalized_indicators)
        or value.get("field_count") != len(normalized_indicators)
        or value.get("computed_function_count") != len(computed)
        or value.get("skipped_function_count") != len(skipped)
        or value.get("strict_latest_output_rejection_count") != len(rejected)
        or type(value.get("talib_function_count")) is not int
        or value["talib_function_count"] <= 0
        or str(value.get("computation_classification", "")).startswith("BLOCKED_")
    ):
        _validation_error("authenticated_strategy_ta_candidate_completeness_invalid")
    value["indicators"] = dict(sorted(normalized_indicators.items()))
    value["skipped_functions"] = dict(sorted(cast(Mapping[str, str], skipped).items()))
    value["strict_latest_output_rejections"] = dict(
        sorted(cast(Mapping[str, str], rejected).items())
    )
    return value


def _strategy_ta_semantics(candidate: Mapping[str, Any]) -> dict[str, Any]:
    retained = (
        "schema_version",
        "source_label",
        "library_used",
        "talib_function_count",
        "computed_function_count",
        "computed_functions",
        "skipped_function_count",
        "skipped_functions",
        "strict_latest_output_rejection_count",
        "strict_latest_output_rejections",
        "field_count",
        "indicator_count",
        "indicators",
        "families_present",
        "classification",
        "computation_classification",
        "source_schema_version",
        "source_row_count",
        "source_contiguous_suffix_count",
        "calculation_row_count",
        "calculation_normalized_row_count",
        "calculation_required_contiguous_rows",
        "calculation_normalized_exact_source_identity",
        "calculation_normalized_first_ts_ms",
        "calculation_normalized_last_ts_ms",
        "calculation_window_first_candle_id",
        "calculation_window_latest_candle_id",
        "calculation_window_candle_ids_sha256",
        "latest_candle_id",
        "latest_candle_raw_payload_hash",
        "latest_candle_source_sequence_id",
        "latest_closed_candle_open_ts_ms",
        "latest_closed_candle_close_ts_ms",
        "closed_candles_only",
        "candle_closed_confirmed",
        "exact_source_schema_validated",
        "producer_finality_contract_validated",
        "no_zero_fill",
    )
    missing = tuple(name for name in retained if name not in candidate)
    if missing:
        _integrity_error("authenticated_strategy_ta_candidate_fields_missing:" + ",".join(missing))
    return {name: candidate[name] for name in retained}


def _semantic_material(
    *,
    capture: CanonicalOhlcvWriterBoundAtomicCapture,
    window: ValidatedOHLCVClosedWindow,
    candidate: Mapping[str, Any],
    dependencies: tuple[tuple[str, str], ...],
    dependency_root: str,
) -> dict[str, Any]:
    try:
        atomic = capture.atomic_capture
    except CanonicalOhlcvWriterBoundAtomicCaptureError as exc:
        raise AuthenticatedStrategyTaTransformV1IntegrityError(
            "authenticated_strategy_ta_source_capture_revalidation_failed"
        ) from exc
    latest = window.rows[-1]
    indicator_names = sorted(cast(Mapping[str, float], candidate["indicators"]))
    latest_valid_before_ms = (
        window.latest_economic_close_time + (TIMEFRAME_DURATION_MS[capture.timeframe]) + 1
    )
    reference_price = float(latest.close)
    return {
        "schema_version": AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION,
        "evidence_classification": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_EVIDENCE_CLASSIFICATION),
        "source_semantics": {
            "symbol": capture.symbol,
            "timeframe": capture.timeframe,
            "source_key": capture.source_key,
            "exact_payload_sha256": capture.exact_payload_sha256,
            "exact_payload_byte_count": capture.exact_payload_byte_count,
            "canonical_payload_address": _address_material(capture.canonical_payload_address),
            "row_count": capture.row_count,
            "binance_wss_row_count": window.binance_wss_row_count,
            "binance_rest_row_count": window.binance_rest_row_count,
            "calculation_row_count": CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
            "atomic_receipted_contiguous_suffix_row_count": atomic.selected_row_count,
            "calculation_window_candle_ids": list(
                atomic.selected_candle_ids[-CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS:]
            ),
            "calculation_window_exact_payload_sha256s": list(
                atomic.selected_exact_payload_sha256s[-CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS:]
            ),
            "calculation_window_candle_ids_sha256": candidate[
                "calculation_window_candle_ids_sha256"
            ],
            "latest_candle_id": latest.candle_id,
            "latest_candle_raw_payload_hash": latest.raw_payload_hash,
            "latest_economic_close_time_ms": window.latest_economic_close_time,
            "max_producer_event_time_ms": window.latest_producer_event_time,
            "max_ingested_at_ms": window.max_ingested_at,
            "max_source_available_at_ms": window.max_available_at,
            "feature_cutoff": capture.feature_cutoff,
            "max_producer_event_time": capture.max_producer_event_time,
            "max_ingested_at": capture.max_ingested_at,
            "max_source_available_at": capture.max_source_available_at,
            "latest_completed_interval_valid_before": _ms_to_clock(latest_valid_before_ms),
        },
        "transform_semantics": {
            "implementation_id": AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_ID,
            "implementation_sha256": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_SHA256),
            "configuration_sha256": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_CONFIGURATION_SHA256),
            "module_code_sha256": dict(dependencies)["authenticated_strategy_ta_transform_v1"],
            "dependency_code_root_sha256": dependency_root,
            "ordered_dependency_code_sha256s": [
                {"dependency_id": name, "code_sha256": digest} for name, digest in dependencies
            ],
            "model_ta_dependency_contract_sha256": (MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256),
            "model_feature_abi_sha256": MODEL_FEATURE_ABI_SHA256,
            "ta_full_feature_map_sha256": (CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256),
            "ta_full_fields_sha256": CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256,
            "ta_ohlcv_abi_leaves_sha256": TA_OHLC_ABI_LEAVES_SHA256,
            "lookback_manifest_sha256": LOOKBACK_MANIFEST_SHA256,
            "deployed_talib_environment_sha256": (DEPLOYED_TALIB_ENVIRONMENT_SHA256),
            "strict_latest_output_semantics": STRICT_LATEST_OUTPUT_SEMANTICS,
            "required_strategy_ta_indicators": list(REQUIRED_STRATEGY_TA_INDICATORS),
        },
        "strategy_ta": {
            **_strategy_ta_semantics(candidate),
            "indicator_names_sha256": _sha256(
                {
                    "schema_version": "strategy_ta_indicator_names_v1",
                    "ordered_names": indicator_names,
                }
            ),
            "reference_price_input": {
                "schema_version": "strategy_closed_candle_reference_price_v1",
                "price": reference_price,
                "source": "writer_authenticated_latest_selected_closed_candle",
                "source_ohlcv_key": capture.source_key,
                "source_exact_payload_sha256": capture.exact_payload_sha256,
                "selected_candle_id": latest.candle_id,
                "selected_candle_raw_payload_hash": latest.raw_payload_hash,
                "selected_candle_open_ts_ms": latest.candle_open_time,
                "selected_candle_close_ts_ms": latest.candle_close_time,
                "selected_candle_event_time": _ms_to_clock(latest.event_time),
                "selected_candle_ingested_at": _ms_to_clock(latest.ingested_at),
                "selected_candle_available_at": _ms_to_clock(latest.available_at),
                "feature_cutoff": capture.feature_cutoff,
                "source_available_at": capture.max_source_available_at,
            },
        },
        "external_input_policy": {
            "unreceipted_inputs_consumed": [],
            "explicitly_excluded_mutable_inputs": list(EXPLICITLY_EXCLUDED_MUTABLE_INPUTS),
            "explicitly_excluded_optional_provider_groups": list(
                EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS
            ),
            "reference_notional_consumed": False,
            "paper_account_consumed": False,
            "zero_fill_used": False,
        },
        "semantic_clock_policy": {
            "observation_and_generation_clocks_excluded": list(_OBSERVATION_ONLY_FIELDS),
            "publication_provenance_fields_excluded": list(_PROVENANCE_ONLY_FIELDS),
            "source_row_economic_and_availability_clocks_retained": True,
        },
        "authorization": {
            **{name: False for name in _AUTHORITY_FIELDS},
            "runtime_wired": False,
        },
    }


def _audit_material(
    *,
    capture: CanonicalOhlcvWriterBoundAtomicCapture,
    semantic_sha256: str,
    semantic_byte_count: int,
    semantic_address: SourcePayloadAddress,
    transform_generated_at: str,
    transform_generated_at_ms: int,
    dependencies: tuple[tuple[str, str], ...],
    dependency_root: str,
) -> dict[str, Any]:
    return {
        "schema_version": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_MANIFEST_SCHEMA_VERSION),
        "evidence_classification": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_EVIDENCE_CLASSIFICATION),
        "downstream_status": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_DOWNSTREAM_STATUS),
        "semantic_content_sha256": semantic_sha256,
        "semantic_content_byte_count": semantic_byte_count,
        "semantic_content_address": _address_material(semantic_address),
        "upstream_proof": {
            "symbol": capture.symbol,
            "timeframe": capture.timeframe,
            "source_key": capture.source_key,
            "revision_id": capture.revision_id,
            "producer_role": capture.producer_role,
            "producer_code_sha256": capture.producer_code_sha256,
            "producer_config_sha256": capture.producer_config_sha256,
            "writer_receipt_sha256": capture.writer_receipt_sha256,
            "trusted_allowlist_sha256": capture.trusted_allowlist_sha256,
            "exact_payload_sha256": capture.exact_payload_sha256,
            "exact_payload_byte_count": capture.exact_payload_byte_count,
            "canonical_payload_address": _address_material(capture.canonical_payload_address),
            "composite_manifest_sha256": capture.composite_manifest_sha256,
            "composite_manifest_address": _address_material(capture.composite_manifest_address),
            "pre_writer_tuple_manifest_sha256": (capture.pre_writer_tuple_manifest_sha256),
            "pre_writer_tuple_manifest_address": _address_material(
                capture.pre_writer_tuple_manifest_address
            ),
            "atomic_batch_id": capture.atomic_batch_id,
            "atomic_batch_material_sha256": capture.atomic_batch_material_sha256,
            "atomic_suffix_digest_sha256": capture.atomic_suffix_digest_sha256,
            "atomic_suffix_manifest_sha256": capture.atomic_suffix_manifest_sha256,
            "atomic_suffix_manifest_address": _address_material(
                capture.atomic_suffix_manifest_address
            ),
            "ordered_selected_candle_receipt_sha256s": list(
                capture.ordered_selected_candle_receipt_sha256s
            ),
            "post_writer_tuple_manifest_sha256": (capture.post_writer_tuple_manifest_sha256),
            "post_writer_tuple_manifest_address": _address_material(
                capture.post_writer_tuple_manifest_address
            ),
        },
        "timestamps": {
            "feature_cutoff": capture.feature_cutoff,
            "max_producer_event_time": capture.max_producer_event_time,
            "max_ingested_at": capture.max_ingested_at,
            "max_source_available_at": capture.max_source_available_at,
            "writer_publication_available_at": (capture.writer_publication_available_at),
            "pre_writer_discovery_observed_at": (capture.pre_writer_discovery_observed_at),
            "pre_writer_authoritative_observed_at": (capture.pre_writer_authoritative_observed_at),
            "pre_writer_consumer_observed_at": (capture.pre_writer_consumer_observed_at),
            "atomic_server_observed_at": capture.atomic_server_observed_at,
            "atomic_consumer_observed_at": capture.atomic_consumer_observed_at,
            "post_writer_discovery_observed_at": (capture.post_writer_discovery_observed_at),
            "post_writer_authoritative_observed_at": (
                capture.post_writer_authoritative_observed_at
            ),
            "post_writer_consumer_observed_at": (capture.post_writer_consumer_observed_at),
            "capture_generated_at": capture.generated_at,
            "transform_generated_at": transform_generated_at,
            "transform_generated_at_ms": transform_generated_at_ms,
            "available_at": None,
            "decision_time": None,
            "execution_time": None,
        },
        "implementation": {
            "implementation_id": AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_ID,
            "implementation_sha256": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_SHA256),
            "configuration_sha256": (AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_CONFIGURATION_SHA256),
            "module_code_sha256": dict(dependencies)["authenticated_strategy_ta_transform_v1"],
            "dependency_code_root_sha256": dependency_root,
            "ordered_dependency_code_sha256s": [
                {"dependency_id": name, "code_sha256": digest} for name, digest in dependencies
            ],
            "model_ta_dependency_contract_sha256": (MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256),
            "model_feature_abi_sha256": MODEL_FEATURE_ABI_SHA256,
            "ta_full_feature_map_sha256": (CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256),
            "ta_full_fields_sha256": CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256,
            "ta_ohlcv_abi_leaves_sha256": TA_OHLC_ABI_LEAVES_SHA256,
            "lookback_manifest_sha256": LOOKBACK_MANIFEST_SHA256,
            "deployed_talib_environment_sha256": (DEPLOYED_TALIB_ENVIRONMENT_SHA256),
        },
        "semantic_exclusions": [
            *_OBSERVATION_ONLY_FIELDS,
            *_PROVENANCE_ONLY_FIELDS,
        ],
        "external_input_policy": {
            "unreceipted_inputs_consumed": [],
            "explicitly_excluded_mutable_inputs": list(EXPLICITLY_EXCLUDED_MUTABLE_INPUTS),
            "explicitly_excluded_optional_provider_groups": list(
                EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS
            ),
        },
        "market_performance_thresholds": [],
        "market_performance_thresholds_applied": False,
        "unreceipted_external_economics_consumed": False,
        "runtime_wired": False,
        **{name: False for name in _AUTHORITY_FIELDS},
    }


def _validated_clock_order(
    capture: CanonicalOhlcvWriterBoundAtomicCapture,
    *,
    transform_generated_at: str,
    transform_generated_at_ms: int,
) -> None:
    ordered = tuple(
        _parse_clock(value, reason="authenticated_strategy_ta_clock_order_invalid")
        for value in (
            capture.feature_cutoff,
            capture.max_producer_event_time,
            capture.max_ingested_at,
            capture.max_source_available_at,
            capture.writer_publication_available_at,
            capture.pre_writer_discovery_observed_at,
            capture.pre_writer_authoritative_observed_at,
            capture.pre_writer_consumer_observed_at,
            capture.atomic_server_observed_at,
            capture.atomic_consumer_observed_at,
            capture.post_writer_discovery_observed_at,
            capture.post_writer_authoritative_observed_at,
            capture.post_writer_consumer_observed_at,
            capture.generated_at,
            transform_generated_at,
        )
    )
    if any(later < earlier for earlier, later in pairwise(ordered)):
        _validation_error("authenticated_strategy_ta_clock_order_invalid")
    if _clock_to_ms(ordered[-1]) != transform_generated_at_ms:
        _integrity_error("authenticated_strategy_ta_generated_clock_binding_invalid")
    duration_ms = TIMEFRAME_DURATION_MS.get(capture.timeframe)
    if type(duration_ms) is not int or duration_ms <= 0:
        _integrity_error("authenticated_strategy_ta_timeframe_duration_invalid")
    expected_latest_close = (transform_generated_at_ms // duration_ms) * duration_ms - 1
    if capture.latest_economic_close_time_ms != expected_latest_close:
        _validation_error("authenticated_strategy_ta_stale_at_generation")


def _validate_semantic(
    semantic: object,
    *,
    result: AuthenticatedStrategyTaTransformV1,
) -> None:
    if not isinstance(semantic, Mapping) or set(semantic) != {
        "schema_version",
        "evidence_classification",
        "source_semantics",
        "transform_semantics",
        "strategy_ta",
        "external_input_policy",
        "semantic_clock_policy",
        "authorization",
    }:
        _integrity_error("authenticated_strategy_ta_semantic_shape_invalid")
    source = semantic.get("source_semantics")
    transform = semantic.get("transform_semantics")
    strategy_ta = semantic.get("strategy_ta")
    external = semantic.get("external_input_policy")
    clock_policy = semantic.get("semantic_clock_policy")
    authorization = semantic.get("authorization")
    if not all(
        isinstance(item, Mapping)
        for item in (source, transform, strategy_ta, external, clock_policy, authorization)
    ):
        _integrity_error("authenticated_strategy_ta_semantic_sections_invalid")
    source = cast(Mapping[str, Any], source)
    transform = cast(Mapping[str, Any], transform)
    strategy_ta = cast(Mapping[str, Any], strategy_ta)
    external = cast(Mapping[str, Any], external)
    clock_policy = cast(Mapping[str, Any], clock_policy)
    authorization = cast(Mapping[str, Any], authorization)
    if (
        semantic.get("schema_version") != result.schema_version
        or semantic.get("evidence_classification") != result.evidence_classification
        or source.get("symbol") != result.symbol
        or source.get("timeframe") != result.timeframe
        or source.get("source_key") != result.source_key
        or source.get("exact_payload_sha256") != result.exact_payload_sha256
        or source.get("exact_payload_byte_count") != result.exact_payload_byte_count
        or source.get("feature_cutoff") != result.feature_cutoff
        or source.get("max_source_available_at") != result.max_source_available_at
        or transform.get("implementation_sha256") != result.implementation_sha256
        or transform.get("configuration_sha256") != result.configuration_sha256
        or transform.get("module_code_sha256") != result.module_code_sha256
        or transform.get("dependency_code_root_sha256") != result.dependency_code_root_sha256
        or transform.get("model_ta_dependency_contract_sha256")
        != result.model_ta_dependency_contract_sha256
        or transform.get("model_feature_abi_sha256") != MODEL_FEATURE_ABI_SHA256
        or transform.get("ta_full_feature_map_sha256")
        != CURRENT_TIMEFRAME_TA_FULL_FEATURE_MAP_SHA256
        or transform.get("ta_full_fields_sha256") != CURRENT_TIMEFRAME_TA_FULL_FIELDS_SHA256
        or transform.get("ta_ohlcv_abi_leaves_sha256") != TA_OHLC_ABI_LEAVES_SHA256
        or transform.get("lookback_manifest_sha256") != LOOKBACK_MANIFEST_SHA256
        or transform.get("deployed_talib_environment_sha256")
        != result.deployed_talib_environment_sha256
        or strategy_ta.get("indicator_count") != result.indicator_count
        or strategy_ta.get("indicator_names_sha256") != result.indicator_names_sha256
        or external.get("unreceipted_inputs_consumed") != []
        or external.get("explicitly_excluded_mutable_inputs")
        != list(EXPLICITLY_EXCLUDED_MUTABLE_INPUTS)
        or external.get("explicitly_excluded_optional_provider_groups")
        != list(EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS)
        or external.get("reference_notional_consumed") is not False
        or external.get("paper_account_consumed") is not False
        or external.get("zero_fill_used") is not False
        or clock_policy.get("observation_and_generation_clocks_excluded")
        != list(_OBSERVATION_ONLY_FIELDS)
        or clock_policy.get("publication_provenance_fields_excluded")
        != list(_PROVENANCE_ONLY_FIELDS)
        or any(authorization.get(name) is not False for name in _AUTHORITY_FIELDS)
        or authorization.get("runtime_wired") is not False
    ):
        _integrity_error("authenticated_strategy_ta_semantic_binding_invalid")
    forbidden = set(_OBSERVATION_ONLY_FIELDS) | set(_PROVENANCE_ONLY_FIELDS)

    def walk(value: object) -> None:
        if isinstance(value, Mapping):
            if forbidden.intersection(value):
                _integrity_error("authenticated_strategy_ta_semantic_audit_clock_leak")
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list | tuple):
            for nested in value:
                walk(nested)

    # The policy names the exclusions; only the other semantic sections must
    # be free of those fields.
    for section_name in (
        "source_semantics",
        "transform_semantics",
        "strategy_ta",
        "external_input_policy",
        "authorization",
    ):
        walk(semantic[section_name])
    indicators = strategy_ta.get("indicators")
    if not isinstance(indicators, Mapping) or len(indicators) != result.indicator_count:
        _integrity_error("authenticated_strategy_ta_semantic_indicators_invalid")
    if any(
        name not in indicators
        or type(indicators[name]) not in (int, float)
        or not math.isfinite(float(indicators[name]))
        for name in REQUIRED_STRATEGY_TA_INDICATORS
    ):
        _integrity_error("authenticated_strategy_ta_semantic_required_indicators_invalid")
    names_hash = _sha256(
        {
            "schema_version": "strategy_ta_indicator_names_v1",
            "ordered_names": sorted(indicators),
        }
    )
    reference = strategy_ta.get("reference_price_input")
    if (
        names_hash != result.indicator_names_sha256
        or not isinstance(reference, Mapping)
        or type(reference.get("price")) not in (int, float)
        or not math.isfinite(float(reference["price"]))
        or float(reference["price"]) != result.reference_price
        or reference.get("selected_candle_id") != result.latest_candle_id
        or reference.get("selected_candle_raw_payload_hash")
        != result.latest_candle_raw_payload_hash
    ):
        _integrity_error("authenticated_strategy_ta_semantic_reference_price_invalid")


def _validate_result(result: AuthenticatedStrategyTaTransformV1) -> None:
    if result._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("authenticated_strategy_ta_factory_construction_required")
    if (
        result.schema_version != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION
        or result.manifest_schema_version
        != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_MANIFEST_SCHEMA_VERSION
        or result.evidence_classification
        != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_EVIDENCE_CLASSIFICATION
        or result.downstream_status != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_DOWNSTREAM_STATUS
        or result.available_at is not None
        or result.decision_time is not None
        or result.execution_time is not None
        or result.unreceipted_external_economics_consumed is not False
        or result.market_performance_thresholds_applied is not False
        or result.runtime_wired is not False
        or any(getattr(result, name) is not False for name in _AUTHORITY_FIELDS)
        or any(
            flag is not True
            for flag in (
                result.writer_authenticated_source_verified,
                result.deterministic_semantic_identity_verified,
                result.transform_dependencies_verified,
                result.semantic_and_audit_cas_reopened,
            )
        )
        or type(result._source_payload_store) is not ImmutableSourcePayloadStore
    ):
        _integrity_error("authenticated_strategy_ta_result_contract_invalid")
    capture, window = _validated_source_capture(result._source_capture)
    dependencies, dependency_root = _dependency_code_material()
    if (
        result.symbol != capture.symbol
        or result.timeframe != capture.timeframe
        or result.source_key != capture.source_key
        or result.revision_id != capture.revision_id
        or result.producer_role != capture.producer_role
        or result.producer_code_sha256 != capture.producer_code_sha256
        or result.producer_config_sha256 != capture.producer_config_sha256
        or result.writer_receipt_sha256 != capture.writer_receipt_sha256
        or result.trusted_allowlist_sha256 != capture.trusted_allowlist_sha256
        or result.exact_payload_sha256 != capture.exact_payload_sha256
        or result.exact_payload_byte_count != capture.exact_payload_byte_count
        or result.canonical_payload_address != capture.canonical_payload_address
        or result.upstream_composite_manifest_sha256 != capture.composite_manifest_sha256
        or result.upstream_composite_manifest_address != capture.composite_manifest_address
        or result.calculation_row_count != CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS
        or result.latest_candle_id != window.rows[-1].candle_id
        or result.latest_candle_raw_payload_hash != window.rows[-1].raw_payload_hash
        or result.implementation_sha256
        != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_SHA256
        or result.configuration_sha256
        != AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_CONFIGURATION_SHA256
        or result.dependency_code_sha256s != dependencies
        or result.module_code_sha256 != dict(dependencies)["authenticated_strategy_ta_transform_v1"]
        or result.dependency_code_root_sha256 != dependency_root
        or result.model_ta_dependency_contract_sha256
        != MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256
        or result.deployed_talib_environment_sha256 != DEPLOYED_TALIB_ENVIRONMENT_SHA256
        or result.feature_cutoff != capture.feature_cutoff
        or result.max_source_available_at != capture.max_source_available_at
        or result.writer_publication_available_at != capture.writer_publication_available_at
        or result.capture_generated_at != capture.generated_at
    ):
        _integrity_error("authenticated_strategy_ta_result_binding_invalid")
    _validated_clock_order(
        capture,
        transform_generated_at=result.transform_generated_at,
        transform_generated_at_ms=result.transform_generated_at_ms,
    )
    try:
        semantic_bytes = result.semantic_content_json.encode("ascii")
        audit_bytes = result.audit_manifest_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("authenticated_strategy_ta_artifact_json_invalid")
    if (
        hashlib.sha256(semantic_bytes).hexdigest() != result.semantic_content_sha256
        or len(semantic_bytes) != result.semantic_content_byte_count
        or hashlib.sha256(audit_bytes).hexdigest() != result.audit_manifest_sha256
        or len(audit_bytes) != result.audit_manifest_byte_count
    ):
        _integrity_error("authenticated_strategy_ta_artifact_hash_invalid")
    _validated_address(
        result.semantic_content_address,
        expected_sha256=result.semantic_content_sha256,
        expected_byte_count=result.semantic_content_byte_count,
        reason="authenticated_strategy_ta_semantic_address_invalid",
    )
    _validated_address(
        result.audit_manifest_address,
        expected_sha256=result.audit_manifest_sha256,
        expected_byte_count=result.audit_manifest_byte_count,
        reason="authenticated_strategy_ta_audit_address_invalid",
    )
    _fresh_readback(
        result._source_payload_store,
        result.semantic_content_address,
        semantic_bytes,
        reason="authenticated_strategy_ta_semantic_cas_readback_failed",
    )
    _fresh_readback(
        result._source_payload_store,
        result.audit_manifest_address,
        audit_bytes,
        reason="authenticated_strategy_ta_audit_cas_readback_failed",
    )
    try:
        semantic = json.loads(semantic_bytes)
        audit = json.loads(audit_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _integrity_error("authenticated_strategy_ta_artifact_json_invalid")
    if _canonical_json_bytes(semantic) != semantic_bytes:
        _integrity_error("authenticated_strategy_ta_semantic_not_canonical")
    _validate_semantic(semantic, result=result)
    expected_audit = _audit_material(
        capture=capture,
        semantic_sha256=result.semantic_content_sha256,
        semantic_byte_count=result.semantic_content_byte_count,
        semantic_address=result.semantic_content_address,
        transform_generated_at=result.transform_generated_at,
        transform_generated_at_ms=result.transform_generated_at_ms,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    if _canonical_json_bytes(expected_audit) != audit_bytes or audit != expected_audit:
        _integrity_error("authenticated_strategy_ta_audit_manifest_binding_invalid")


def transform_writer_bound_ohlcv_to_strategy_ta_v1(
    source_capture: CanonicalOhlcvWriterBoundAtomicCapture,
    source_payload_store: ImmutableSourcePayloadStore,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    consumer_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> AuthenticatedStrategyTaTransformV1:
    """Build one deterministic TA artifact and a separate immutable audit proof."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("authenticated_strategy_ta_authentic_store_required")
    capture, window = _validated_source_capture(source_capture)
    if capture.symbol != expected_symbol or capture.timeframe != expected_timeframe:
        _validation_error("authenticated_strategy_ta_requested_market_mismatch")
    dependencies, dependency_root = _dependency_code_material()
    before_contract = _validated_technical_contract()
    try:
        candidate_raw = full_talib_service.build_full_talib_ta_closed_candidate(
            validated_window=window,
        )
    except ValueError as exc:
        raise AuthenticatedStrategyTaTransformV1ValidationError(
            "authenticated_strategy_ta_computation_rejected"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - dependency detail is contained
        raise AuthenticatedStrategyTaTransformV1IntegrityError(
            "authenticated_strategy_ta_computation_failed"
        ) from exc
    after_contract = _validated_technical_contract()
    if (
        before_contract.contract_material_json != after_contract.contract_material_json
        or before_contract.talib_environment != after_contract.talib_environment
    ):
        _integrity_error("authenticated_strategy_ta_environment_changed_during_computation")
    candidate = _validated_candidate(candidate_raw, capture=capture, window=window)
    transform_generated_at, transform_generated_at_ms = _sample_clock(consumer_clock)
    _validated_clock_order(
        capture,
        transform_generated_at=transform_generated_at,
        transform_generated_at_ms=transform_generated_at_ms,
    )
    semantic = _semantic_material(
        capture=capture,
        window=window,
        candidate=candidate,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    semantic_bytes = _canonical_json_bytes(semantic)
    semantic_sha256 = hashlib.sha256(semantic_bytes).hexdigest()
    semantic_address = _put_immutable(
        source_payload_store,
        semantic_bytes,
        reason="authenticated_strategy_ta_semantic_cas_capture_failed",
    )
    audit = _audit_material(
        capture=capture,
        semantic_sha256=semantic_sha256,
        semantic_byte_count=len(semantic_bytes),
        semantic_address=semantic_address,
        transform_generated_at=transform_generated_at,
        transform_generated_at_ms=transform_generated_at_ms,
        dependencies=dependencies,
        dependency_root=dependency_root,
    )
    audit_bytes = _canonical_json_bytes(audit)
    audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
    audit_address = _put_immutable(
        source_payload_store,
        audit_bytes,
        reason="authenticated_strategy_ta_audit_cas_capture_failed",
    )
    strategy_ta = cast(Mapping[str, Any], semantic["strategy_ta"])
    reference = cast(Mapping[str, Any], strategy_ta["reference_price_input"])
    return AuthenticatedStrategyTaTransformV1(
        schema_version=AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION,
        manifest_schema_version=(AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_MANIFEST_SCHEMA_VERSION),
        evidence_classification=(AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_EVIDENCE_CLASSIFICATION),
        downstream_status=(AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_DOWNSTREAM_STATUS),
        symbol=capture.symbol,
        timeframe=capture.timeframe,
        source_key=capture.source_key,
        revision_id=capture.revision_id,
        producer_role=capture.producer_role,
        producer_code_sha256=capture.producer_code_sha256,
        producer_config_sha256=capture.producer_config_sha256,
        writer_receipt_sha256=capture.writer_receipt_sha256,
        trusted_allowlist_sha256=capture.trusted_allowlist_sha256,
        exact_payload_sha256=capture.exact_payload_sha256,
        exact_payload_byte_count=capture.exact_payload_byte_count,
        canonical_payload_address=capture.canonical_payload_address,
        upstream_composite_manifest_sha256=capture.composite_manifest_sha256,
        upstream_composite_manifest_address=capture.composite_manifest_address,
        calculation_row_count=CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
        calculation_window_candle_ids_sha256=cast(
            str,
            strategy_ta["calculation_window_candle_ids_sha256"],
        ),
        latest_candle_id=window.rows[-1].candle_id,
        latest_candle_raw_payload_hash=window.rows[-1].raw_payload_hash,
        indicator_count=cast(int, strategy_ta["indicator_count"]),
        indicator_names_sha256=cast(str, strategy_ta["indicator_names_sha256"]),
        reference_price=float(reference["price"]),
        implementation_sha256=(AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_SHA256),
        configuration_sha256=(AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_CONFIGURATION_SHA256),
        module_code_sha256=dict(dependencies)["authenticated_strategy_ta_transform_v1"],
        dependency_code_root_sha256=dependency_root,
        dependency_code_sha256s=dependencies,
        model_ta_dependency_contract_sha256=(MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256),
        deployed_talib_environment_sha256=DEPLOYED_TALIB_ENVIRONMENT_SHA256,
        feature_cutoff=capture.feature_cutoff,
        max_source_available_at=capture.max_source_available_at,
        writer_publication_available_at=capture.writer_publication_available_at,
        capture_generated_at=capture.generated_at,
        transform_generated_at=transform_generated_at,
        transform_generated_at_ms=transform_generated_at_ms,
        available_at=None,
        decision_time=None,
        execution_time=None,
        semantic_content_sha256=semantic_sha256,
        semantic_content_byte_count=len(semantic_bytes),
        semantic_content_json=semantic_bytes.decode("ascii"),
        semantic_content_address=semantic_address,
        audit_manifest_sha256=audit_sha256,
        audit_manifest_byte_count=len(audit_bytes),
        audit_manifest_json=audit_bytes.decode("ascii"),
        audit_manifest_address=audit_address,
        _source_capture=capture,
        _source_payload_store=source_payload_store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_CONFIGURATION_SHA256",
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_DOWNSTREAM_STATUS",
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_EVIDENCE_CLASSIFICATION",
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_ID",
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_IMPLEMENTATION_SHA256",
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_MANIFEST_SCHEMA_VERSION",
    "AUTHENTICATED_STRATEGY_TA_TRANSFORM_V1_SCHEMA_VERSION",
    "EXPLICITLY_EXCLUDED_MUTABLE_INPUTS",
    "EXPLICITLY_EXCLUDED_OPTIONAL_PROVIDER_GROUPS",
    "REQUIRED_STRATEGY_TA_INDICATORS",
    "AuthenticatedStrategyTaTransformV1",
    "AuthenticatedStrategyTaTransformV1Error",
    "AuthenticatedStrategyTaTransformV1IntegrityError",
    "AuthenticatedStrategyTaTransformV1ValidationError",
    "transform_writer_bound_ohlcv_to_strategy_ta_v1",
]
