"""Immutable, audit-only OHLCV feature-selection profile v1.

This module freezes one prospective selection over the deployed 446-slot ABI.
It is a declaration, not a resolver, transform implementation, source receipt,
feature snapshot, or trainer admission gate.  In particular, importing or
validating this profile does not establish that any selected source or
transform exists and grants no prediction, paper, live, or execution authority.

The profile preserves the full base ABI order.  A slot marked
``PROFILE_DISABLED`` may only be represented by the separately declared
disabled encoding in a future, profile-aware consumer; it is not a missing
observation or a typed negative.  No such consumer is wired by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn

from v2.backend.app.services.native_trainer.canonical_ohlcv_hermetic_replay_policy_v4 import (
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
    CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
    REQUIREMENT_REQUIRED,
    FeatureSourceRegistryV4,
    feature_source_registry_v4_contract,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    CURRENT_TIMEFRAME_NATIVE_CORE_FIELDS,
    EXISTING_CORE_CONTRACT_VERSION,
    EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
    MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
    TRUE_1H_TA_FIELDS,
    TRUE_1H_TA_MINIMUM_ROWS,
)
from v2.backend.app.services.native_trainer.source_evidence_profile_attestation_v4 import (
    CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4,
    CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
    SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION,
)

ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION: Final = (
    "adaptive_ohlcv_feature_selection_profile_v1"
)
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID: Final = "OHLCV_BOOTSTRAP_5M_1H_V1"
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_CLASSIFICATION: Final = (
    "PROSPECTIVE_AUDIT_ONLY_DECLARATION_UNAUTHENTICATED_UNWIRED"
)
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DOWNSTREAM_STATUS: Final = (
    "NON_CONSUMABLE_NO_TRANSFORM_OR_PER_SAMPLE_RECEIPT_PROOF_NO_ELIGIBILITY_OR_AUTHORITY"
)

PROFILE_DISABLED: Final = "PROFILE_DISABLED"
ENABLED_REQUIRED: Final = "ENABLED_REQUIRED"
ENABLED_OPTIONAL_EVENT_DEPENDENT: Final = "ENABLED_OPTIONAL_EVENT_DEPENDENT"

RAW_CLOSED_5M_FAMILY_ID: Final = "CLOSED_5M_OHLCV_RAW_OR_EXACT_DERIVATION"
PLANNED_5M_TRANSFORM_FAMILY_ID: Final = "PLANNED_RECEIPT_BOUND_CLOSED_5M_TRANSFORMS"
TRUE_1H_TA_FAMILY_ID: Final = "PLANNED_RECEIPT_BOUND_TRUE_CLOSED_1H_TA"

ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SLOT_COUNT: Final = 446
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_SLOT_COUNT: Final = 35
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_REQUIRED_SLOT_COUNT: Final = 35
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_OPTIONAL_SLOT_COUNT: Final = 0
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DISABLED_SLOT_COUNT: Final = 411
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DISABLED_REQUIRED_SLOT_COUNT: Final = 348
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DISABLED_OPTIONAL_SLOT_COUNT: Final = 63

ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS: Final = (
    10,
    11,
    *range(14, 25),
    159,
    160,
    *range(166, 178),
    *range(434, 442),
)

ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ORDERED_DISPOSITION_SHA256: Final = (
    "44a8b2227a9777f66c3769d82d6a76a43220e60ecf538a3799da0952a2f02afb"
)
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256: Final = (
    "8536827ed61dd1a11106359b20f39a749812f75b4aa10f9eda5f4a87a8c62e76"
)
ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256: Final = (
    "dae4bbab9da91ddee03da05313a73d5604d8ba878f802155e8fcaa2c7a5e8a88"
)

CANONICAL_OHLCV_REQUIRED_PRODUCER_POLICY_ID: Final = "canonical-binance-ohlcv-hermetic-replay"
SELECTION_CUTOFF_RULE_ID: Final = "PROSPECTIVE_SELECTION_CUTOFF_V1"
DISABLED_ENCODING_ID: Final = "PROFILE_DISABLED_ZERO_WITH_SEPARATE_SELECTION_MASK_V1"
TYPED_NEGATIVE_POLICY_ID: Final = "PROFILE_TYPED_NEGATIVE_DISPOSITION_POLICY_V1"

_DISPOSITIONS = frozenset({PROFILE_DISABLED, ENABLED_REQUIRED, ENABLED_OPTIONAL_EVENT_DEPENDENT})
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@{}+-]{0,255}$", re.ASCII)
_CLOCK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", re.ASCII)
_CONSTRUCTION_TOKEN = object()


class AdaptiveOhlcvFeatureSelectionProfileV1ValidationError(ValueError):
    """The declaration does not reproduce the single pinned v1 profile."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AdaptiveOhlcvFeatureSelectionProfileV1ValidationError(*reasons) from None


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_CANONICAL_ENCODING_FAILED")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OhlcvFeatureTransformContractV1:
    """One selected ABI leaf and its required, but not asserted, derivation."""

    ordinal: int
    feature_name: str
    transform_id: str
    input_fields: tuple[str, ...]
    minimum_closed_source_rows: int
    implementation_present: bool
    per_sample_receipt_bound: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        if type(self.ordinal) is not int or not 0 <= self.ordinal < 446:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_ORDINAL_INVALID")
        if not _valid_label(self.feature_name) or not _valid_label(self.transform_id):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_LABEL_INVALID")
        if type(self.input_fields) is not tuple or not self.input_fields:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_INPUTS_INVALID")
        if any(not _valid_label(value) for value in self.input_fields):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_INPUTS_INVALID")
        if len(set(self.input_fields)) != len(self.input_fields):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_INPUT_DUPLICATE")
        if type(self.minimum_closed_source_rows) is not int or self.minimum_closed_source_rows <= 0:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_MINIMUM_ROWS_INVALID")
        if self.implementation_present is not False or self.per_sample_receipt_bound is not False:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRANSFORM_OR_RECEIPT_CLAIM_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class OhlcvTimeframeFinalityTransformContractV1:
    """Physical timeframe, finality, provenance, and transform prerequisites."""

    family_id: str
    physical_timeframe: str
    configured_source_label: str
    output_source_key_template: str
    canonical_ohlcv_source_key_template: str
    enabled_ordinals: tuple[int, ...]
    enabled_feature_names: tuple[str, ...]
    transforms: tuple[OhlcvFeatureTransformContractV1, ...]
    family_minimum_closed_source_rows: int
    finality_rule: str
    availability_rule: str
    feature_cutoff_rule: str
    transform_available_at_rule: str
    historical_lookback_policy: str
    latest_decision_bound_row_policy: str
    unfinished_candles_allowed: bool
    proxy_higher_timeframe_allowed: bool
    transform_implementation_present: bool
    per_sample_receipts_bound: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        labels = (
            self.family_id,
            self.physical_timeframe,
            self.configured_source_label,
            self.output_source_key_template,
            self.canonical_ohlcv_source_key_template,
            self.finality_rule,
            self.availability_rule,
            self.feature_cutoff_rule,
            self.transform_available_at_rule,
            self.historical_lookback_policy,
            self.latest_decision_bound_row_policy,
        )
        if any(not _valid_label(value) for value in labels):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_LABEL_INVALID")
        if (
            type(self.enabled_ordinals) is not tuple
            or type(self.enabled_feature_names) is not tuple
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_INVENTORY_INVALID")
        if not self.enabled_ordinals or any(
            type(value) is not int or not 0 <= value < 446 for value in self.enabled_ordinals
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_ORDINALS_INVALID")
        if tuple(sorted(set(self.enabled_ordinals))) != self.enabled_ordinals:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_ORDINALS_INVALID")
        if len(self.enabled_ordinals) != len(self.enabled_feature_names):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_DIMENSION_INVALID")
        if any(not _valid_label(value) for value in self.enabled_feature_names):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_FEATURE_INVALID")
        if len(set(self.enabled_feature_names)) != len(self.enabled_feature_names):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_FEATURE_DUPLICATE")
        if type(self.transforms) is not tuple or len(self.transforms) != len(self.enabled_ordinals):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_TRANSFORMS_INVALID")
        if any(type(item) is not OhlcvFeatureTransformContractV1 for item in self.transforms):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_CONTRACT_TRANSFORMS_INVALID")
        if (
            tuple(item.ordinal for item in self.transforms) != self.enabled_ordinals
            or tuple(item.feature_name for item in self.transforms) != self.enabled_feature_names
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_TRANSFORM_ORDER_INVALID")
        if (
            type(self.family_minimum_closed_source_rows) is not int
            or self.family_minimum_closed_source_rows <= 0
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_MINIMUM_ROWS_INVALID")
        false_claims = (
            self.unfinished_candles_allowed,
            self.proxy_higher_timeframe_allowed,
            self.transform_implementation_present,
            self.per_sample_receipts_bound,
        )
        if any(value is not False for value in false_claims):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_FALSE_CLAIM_REQUIRED")


@dataclass(frozen=True, slots=True)
class OhlcvProducerDependencyContractV1:
    """Required producer contracts, with satisfaction deliberately unclaimed."""

    source_evidence_profile_schema_version: str
    source_evidence_profile_id: str
    source_adapter_id: str
    hermetic_replay_policy_schema_version: str
    hermetic_replay_policy_contract_version: str
    hermetic_replay_policy_id: str
    hermetic_replay_protocol_sha256: str
    policy_document_sha256_binding_rule: str
    exact_policy_document_sha256_embedded: bool
    producer_dependency_satisfied: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        values = (
            self.source_evidence_profile_schema_version,
            self.source_evidence_profile_id,
            self.source_adapter_id,
            self.hermetic_replay_policy_schema_version,
            self.hermetic_replay_policy_contract_version,
            self.hermetic_replay_policy_id,
            self.policy_document_sha256_binding_rule,
        )
        if any(not _valid_label(value) for value in values):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_PRODUCER_DEPENDENCY_LABEL_INVALID")
        if (
            type(self.hermetic_replay_protocol_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.hermetic_replay_protocol_sha256) is None
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_PRODUCER_PROTOCOL_SHA256_INVALID")
        if (
            self.exact_policy_document_sha256_embedded is not False
            or self.producer_dependency_satisfied is not False
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_PRODUCER_DEPENDENCY_CLAIM_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class ProspectiveSelectionCutoffRuleV1:
    rule_id: str
    clock_format: str
    clauses: tuple[str, ...]
    activation_timestamp_embedded: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        if not _valid_label(self.rule_id) or not _valid_label(self.clock_format):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_CUTOFF_RULE_LABEL_INVALID")
        if type(self.clauses) is not tuple or not self.clauses:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_CUTOFF_RULE_CLAUSES_INVALID")
        if any(not _valid_label(value) for value in self.clauses):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_CUTOFF_RULE_CLAUSES_INVALID")
        if len(set(self.clauses)) != len(self.clauses):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_CUTOFF_RULE_CLAUSE_DUPLICATE")
        if self.activation_timestamp_embedded is not False:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_MUTABLE_ACTIVATION_TIMESTAMP_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class DisabledFeatureEncodingContractV1:
    encoding_id: str
    numeric_value_hex: str
    profile_selection_mask: int
    missing_mask_reused: bool
    stale_mask_reused: bool
    source_availability_claimed: bool
    typed_negative_encoding_reused: bool
    runtime_materializer_implemented: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        if not _valid_label(self.encoding_id) or self.numeric_value_hex != "0x0.0p+0":
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISABLED_ENCODING_INVALID")
        if type(self.profile_selection_mask) is not int or self.profile_selection_mask != 0:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISABLED_SELECTION_MASK_INVALID")
        flags = (
            self.missing_mask_reused,
            self.stale_mask_reused,
            self.source_availability_claimed,
            self.typed_negative_encoding_reused,
            self.runtime_materializer_implemented,
        )
        if any(value is not False for value in flags):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISABLED_ENCODING_FALSE_CLAIM_REQUIRED")


@dataclass(frozen=True, slots=True)
class TypedNegativeDispositionPolicyV1:
    policy_id: str
    permitted_dispositions: tuple[str, ...]
    forbidden_dispositions: tuple[str, ...]
    authentication_required: bool
    exact_slot_and_source_binding_required: bool
    may_enable_profile_disabled_slot: bool
    may_satisfy_enabled_required_slot: bool
    v1_permitted_slot_count: int
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        if not _valid_label(self.policy_id):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_POLICY_INVALID")
        if self.permitted_dispositions != (ENABLED_OPTIONAL_EVENT_DEPENDENT,):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_PERMISSION_INVALID")
        if self.forbidden_dispositions != (PROFILE_DISABLED, ENABLED_REQUIRED):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_FORBIDDEN_SET_INVALID")
        if (
            self.authentication_required is not True
            or self.exact_slot_and_source_binding_required is not True
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_AUTHENTICATION_REQUIRED")
        if (
            self.may_enable_profile_disabled_slot is not False
            or self.may_satisfy_enabled_required_slot is not False
        ):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_ESCALATION_FORBIDDEN")
        if type(self.v1_permitted_slot_count) is not int or self.v1_permitted_slot_count != 0:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_COUNT_INVALID")


@dataclass(frozen=True, slots=True)
class AdaptiveOhlcvFeatureSelectionProfileV1:
    """Factory-only representation of the complete immutable profile."""

    schema_version: str
    profile_id: str
    classification: str
    downstream_status: str
    base_abi_schema_version: str
    base_abi_sha256: str
    base_registry_schema_version: str
    base_registry_sha256: str
    base_requirement_policy_id: str
    base_slot_count: int
    model_ta_dependency_contract_version: str
    model_ta_dependency_contract_sha256: str
    ordered_slot_dispositions: tuple[str, ...]
    ordered_disposition_sha256: str
    enabled_slot_ordinals: tuple[int, ...]
    enabled_feature_names: tuple[str, ...]
    enabled_feature_list_sha256: str
    enabled_required_slot_count: int
    enabled_optional_event_dependent_slot_count: int
    disabled_slot_count: int
    disabled_required_slot_count: int
    disabled_optional_event_dependent_slot_count: int
    timeframe_finality_transform_contracts: tuple[OhlcvTimeframeFinalityTransformContractV1, ...]
    producer_dependency_contract: OhlcvProducerDependencyContractV1
    selection_cutoff_rule: ProspectiveSelectionCutoffRuleV1
    disabled_encoding_contract: DisabledFeatureEncodingContractV1
    typed_negative_policy: TypedNegativeDispositionPolicyV1
    audit_only: bool
    transforms_implemented: bool
    per_sample_receipts_bound: bool
    feature_snapshot_published: bool
    consumer_eligible: bool
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    profile_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_profile(self)


def _transform(
    ordinal: int,
    feature_name: str,
    transform_id: str,
    input_fields: tuple[str, ...],
    minimum_closed_source_rows: int,
) -> OhlcvFeatureTransformContractV1:
    return OhlcvFeatureTransformContractV1(
        ordinal=ordinal,
        feature_name=feature_name,
        transform_id=transform_id,
        input_fields=input_fields,
        minimum_closed_source_rows=minimum_closed_source_rows,
        implementation_present=False,
        per_sample_receipt_bound=False,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


_RAW_5M_TRANSFORMS = (
    _transform(10, "quote_volume", "SOURCE_FIELD_IDENTITY_V1", ("quote_volume",), 1),
    _transform(11, "volume", "SOURCE_FIELD_IDENTITY_V1", ("volume",), 1),
    _transform(14, "open", "SOURCE_FIELD_IDENTITY_V1", ("open",), 1),
    _transform(15, "high", "SOURCE_FIELD_IDENTITY_V1", ("high",), 1),
    _transform(16, "low", "SOURCE_FIELD_IDENTITY_V1", ("low",), 1),
    _transform(17, "close", "SOURCE_FIELD_IDENTITY_V1", ("close",), 1),
    _transform(18, "num_trades", "SOURCE_FIELD_IDENTITY_V1", ("num_trades",), 1),
    _transform(
        19,
        "taker_buy_base_vol",
        "SOURCE_FIELD_IDENTITY_V1",
        ("taker_buy_base_vol",),
        1,
    ),
    _transform(
        20,
        "taker_buy_quote_vol",
        "SOURCE_FIELD_IDENTITY_V1",
        ("taker_buy_quote_vol",),
        1,
    ),
    _transform(
        21,
        "taker_sell_base_vol",
        "NONNEGATIVE_VOLUME_MINUS_TAKER_BUY_BASE_V1",
        ("volume", "taker_buy_base_vol"),
        1,
    ),
    _transform(
        22,
        "taker_sell_quote_vol",
        "NONNEGATIVE_QUOTE_VOLUME_MINUS_TAKER_BUY_QUOTE_V1",
        ("quote_volume", "taker_buy_quote_vol"),
        1,
    ),
    _transform(
        23,
        "taker_buy_ratio",
        "TAKER_BUY_BASE_OVER_VOLUME_V1",
        ("taker_buy_base_vol", "volume"),
        1,
    ),
    _transform(
        24,
        "taker_sell_ratio",
        "ONE_MINUS_TAKER_BUY_BASE_OVER_VOLUME_V1",
        ("taker_buy_base_vol", "volume"),
        1,
    ),
    _transform(159, "ohlcv_close", "IDENTITY_ALIAS_CLOSE_V1", ("close",), 1),
    _transform(160, "ohlcv_volume", "IDENTITY_ALIAS_VOLUME_V1", ("volume",), 1),
)

_PLANNED_5M_TRANSFORMS = (
    _transform(166, "ret_pct", "SIMPLE_CLOSE_RETURN_V1", ("close",), 2),
    _transform(167, "log_return", "NATURAL_LOG_CLOSE_RETURN_V1", ("close",), 2),
    _transform(168, "range_pct", "HIGH_MINUS_LOW_OVER_CLOSE_V1", ("high", "low", "close"), 1),
    _transform(169, "body_pct", "CLOSE_MINUS_OPEN_OVER_CLOSE_V1", ("open", "close"), 1),
    _transform(
        170,
        "true_range_pct",
        "WILDER_ATR_14_OVER_CLOSE_V1",
        ("high", "low", "close"),
        15,
    ),
    _transform(171, "ema_12", "SMA_SEEDED_EMA_12_V1", ("close",), 12),
    _transform(172, "ema_26", "SMA_SEEDED_EMA_26_V1", ("close",), 26),
    _transform(173, "rsi_14", "WILDER_RSI_14_V1", ("close",), 15),
    _transform(174, "macd", "SMA_SEEDED_MACD_12_26_9_LINE_V1", ("close",), 35),
    _transform(
        175,
        "macd_signal",
        "SMA_SEEDED_MACD_12_26_9_SIGNAL_V1",
        ("close",),
        35,
    ),
    _transform(
        176,
        "macd_hist",
        "SMA_SEEDED_MACD_12_26_9_HISTOGRAM_V1",
        ("close",),
        35,
    ),
    _transform(
        177,
        "bb_width_pct",
        "BOLLINGER_POPULATION_WIDTH_20_2_OVER_MEAN_V1",
        ("close",),
        20,
    ),
)

_TRUE_1H_TRANSFORMS = (
    _transform(434, "htf1h_taf_rsi", "TALIB_RSI_14_REAL_V1", ("close",), 15),
    _transform(435, "htf1h_taf_adx", "TALIB_ADX_14_REAL_V1", ("high", "low", "close"), 28),
    _transform(
        436,
        "htf1h_taf_macd_hist",
        "TALIB_MACD_12_26_9_MACDHIST_V1",
        ("close",),
        34,
    ),
    _transform(437, "htf1h_taf_atr", "TALIB_ATR_14_REAL_V1", ("high", "low", "close"), 15),
    _transform(
        438,
        "htf1h_taf_mfi",
        "TALIB_MFI_14_REAL_V1",
        ("high", "low", "close", "volume"),
        15,
    ),
    _transform(
        439,
        "htf1h_taf_willr",
        "TALIB_WILLR_14_REAL_V1",
        ("high", "low", "close"),
        14,
    ),
    _transform(
        440,
        "htf1h_taf_natr",
        "TALIB_NATR_14_REAL_V1",
        ("high", "low", "close"),
        15,
    ),
    _transform(
        441,
        "htf1h_taf_cci",
        "TALIB_CCI_14_REAL_V1",
        ("high", "low", "close"),
        14,
    ),
)


def _timeframe_contract(
    *,
    family_id: str,
    physical_timeframe: str,
    configured_source_label: str,
    output_source_key_template: str,
    transforms: tuple[OhlcvFeatureTransformContractV1, ...],
    minimum_rows: int,
) -> OhlcvTimeframeFinalityTransformContractV1:
    return OhlcvTimeframeFinalityTransformContractV1(
        family_id=family_id,
        physical_timeframe=physical_timeframe,
        configured_source_label=configured_source_label,
        output_source_key_template=output_source_key_template,
        canonical_ohlcv_source_key_template=(
            f"v2:market:ohlcv_closed:binance:{{symbol}}:{physical_timeframe}"
        ),
        enabled_ordinals=tuple(item.ordinal for item in transforms),
        enabled_feature_names=tuple(item.feature_name for item in transforms),
        transforms=transforms,
        family_minimum_closed_source_rows=minimum_rows,
        finality_rule="EVERY_INPUT_CANDLE_CLOSE_TIME_STRICTLY_LT_DECISION_TIME",
        availability_rule="EVERY_SOURCE_AND_OUTPUT_AVAILABLE_AT_LE_DECISION_TIME",
        feature_cutoff_rule="LATEST_INCLUDED_CLOSED_CANDLE_CLOSE_TIME_STRICTLY_LT_DECISION_TIME",
        transform_available_at_rule="MAX_INPUT_AVAILABLE_AT_AND_TRANSFORM_GENERATED_AT",
        historical_lookback_policy=(
            "AUTHENTICATED_CANONICAL_BINANCE_REST_ALLOWED_FOR_CAUSAL_HISTORY_ONLY_WITH_"
            "IMMUTABLE_SCHEMA_RECEIPT_CAS_AND_AVAILABLE_AT_LE_DECISION_TIME"
        ),
        latest_decision_bound_row_policy="FINALIZED_LIVE_BINANCE_WSS_ROW_REQUIRED",
        unfinished_candles_allowed=False,
        proxy_higher_timeframe_allowed=False,
        transform_implementation_present=False,
        per_sample_receipts_bound=False,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


_TIMEFRAME_CONTRACTS = (
    _timeframe_contract(
        family_id=RAW_CLOSED_5M_FAMILY_ID,
        physical_timeframe="5m",
        configured_source_label="v2:market:ohlcv",
        output_source_key_template="v2:market:ohlcv_closed:binance:{symbol}:5m",
        transforms=_RAW_5M_TRANSFORMS,
        minimum_rows=1,
    ),
    _timeframe_contract(
        family_id=PLANNED_5M_TRANSFORM_FAMILY_ID,
        physical_timeframe="5m",
        configured_source_label="v2:features:latest",
        output_source_key_template="v2:features:latest:{symbol}:5m",
        transforms=_PLANNED_5M_TRANSFORMS,
        minimum_rows=EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    ),
    _timeframe_contract(
        family_id=TRUE_1H_TA_FAMILY_ID,
        physical_timeframe="1h",
        configured_source_label="v2:features:ta_full:1h",
        output_source_key_template="v2:features:ta_full:{symbol}:1h",
        transforms=_TRUE_1H_TRANSFORMS,
        minimum_rows=TRUE_1H_TA_MINIMUM_ROWS,
    ),
)

_PRODUCER_DEPENDENCY = OhlcvProducerDependencyContractV1(
    source_evidence_profile_schema_version=SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION,
    source_evidence_profile_id=CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
    source_adapter_id=CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4,
    hermetic_replay_policy_schema_version=CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_SCHEMA_VERSION,
    hermetic_replay_policy_contract_version=(
        CANONICAL_OHLCV_HERMETIC_REPLAY_POLICY_V4_CONTRACT_VERSION
    ),
    hermetic_replay_policy_id=CANONICAL_OHLCV_REQUIRED_PRODUCER_POLICY_ID,
    hermetic_replay_protocol_sha256=CANONICAL_OHLCV_HERMETIC_REPLAY_PROTOCOL_V4_SHA256,
    policy_document_sha256_binding_rule=(
        "EACH_SAMPLE_RECEIPT_MUST_BIND_ONE_EXACT_VALIDATED_POLICY_DOCUMENT_SHA256"
    ),
    exact_policy_document_sha256_embedded=False,
    producer_dependency_satisfied=False,
    _construction_token=_CONSTRUCTION_TOKEN,
)

_SELECTION_CUTOFF_RULE = ProspectiveSelectionCutoffRuleV1(
    rule_id=SELECTION_CUTOFF_RULE_ID,
    clock_format="UTC_MICROSECOND_Z",
    clauses=(
        "SELECTION_OBSERVATION_EVENT_TIME_LE_SELECTION_DATA_CUTOFF",
        "SELECTION_OBSERVATION_AVAILABLE_AT_LE_SELECTION_DATA_CUTOFF",
        "SELECTION_DATA_CUTOFF_STRICTLY_LT_PROFILE_PUBLISHED_AVAILABLE_AT",
        "PROFILE_PUBLISHED_AVAILABLE_AT_LE_SAMPLE_DECISION_TIME",
        "EACH_ENABLED_FEATURE_AVAILABLE_AT_LE_SAMPLE_DECISION_TIME",
        "FINAL_FEATURE_CUTOFF_STRICTLY_LT_SAMPLE_DECISION_TIME",
        "MASA_FEATURE_CUTOFF_LE_PPO_FEATURE_CUTOFF",
        "PPO_FEATURE_CUTOFF_STRICTLY_LT_PPO_DECISION_TIME",
    ),
    activation_timestamp_embedded=False,
    _construction_token=_CONSTRUCTION_TOKEN,
)

_DISABLED_ENCODING = DisabledFeatureEncodingContractV1(
    encoding_id=DISABLED_ENCODING_ID,
    numeric_value_hex="0x0.0p+0",
    profile_selection_mask=0,
    missing_mask_reused=False,
    stale_mask_reused=False,
    source_availability_claimed=False,
    typed_negative_encoding_reused=False,
    runtime_materializer_implemented=False,
    _construction_token=_CONSTRUCTION_TOKEN,
)

_TYPED_NEGATIVE_POLICY = TypedNegativeDispositionPolicyV1(
    policy_id=TYPED_NEGATIVE_POLICY_ID,
    permitted_dispositions=(ENABLED_OPTIONAL_EVENT_DEPENDENT,),
    forbidden_dispositions=(PROFILE_DISABLED, ENABLED_REQUIRED),
    authentication_required=True,
    exact_slot_and_source_binding_required=True,
    may_enable_profile_disabled_slot=False,
    may_satisfy_enabled_required_slot=False,
    v1_permitted_slot_count=0,
    _construction_token=_CONSTRUCTION_TOKEN,
)


def _transform_material(item: OhlcvFeatureTransformContractV1) -> dict[str, object]:
    return {
        "ordinal": item.ordinal,
        "feature_name": item.feature_name,
        "transform_id": item.transform_id,
        "input_fields": list(item.input_fields),
        "minimum_closed_source_rows": item.minimum_closed_source_rows,
        "implementation_present": item.implementation_present,
        "per_sample_receipt_bound": item.per_sample_receipt_bound,
    }


def _timeframe_material(item: OhlcvTimeframeFinalityTransformContractV1) -> dict[str, object]:
    return {
        "family_id": item.family_id,
        "physical_timeframe": item.physical_timeframe,
        "configured_source_label": item.configured_source_label,
        "output_source_key_template": item.output_source_key_template,
        "canonical_ohlcv_source_key_template": item.canonical_ohlcv_source_key_template,
        "enabled_ordinals": list(item.enabled_ordinals),
        "enabled_feature_names": list(item.enabled_feature_names),
        "transforms": [_transform_material(value) for value in item.transforms],
        "family_minimum_closed_source_rows": item.family_minimum_closed_source_rows,
        "finality_rule": item.finality_rule,
        "availability_rule": item.availability_rule,
        "feature_cutoff_rule": item.feature_cutoff_rule,
        "transform_available_at_rule": item.transform_available_at_rule,
        "historical_lookback_policy": item.historical_lookback_policy,
        "latest_decision_bound_row_policy": item.latest_decision_bound_row_policy,
        "unfinished_candles_allowed": item.unfinished_candles_allowed,
        "proxy_higher_timeframe_allowed": item.proxy_higher_timeframe_allowed,
        "transform_implementation_present": item.transform_implementation_present,
        "per_sample_receipts_bound": item.per_sample_receipts_bound,
    }


def _producer_material(item: OhlcvProducerDependencyContractV1) -> dict[str, object]:
    return {
        "source_evidence_profile_schema_version": item.source_evidence_profile_schema_version,
        "source_evidence_profile_id": item.source_evidence_profile_id,
        "source_adapter_id": item.source_adapter_id,
        "hermetic_replay_policy_schema_version": item.hermetic_replay_policy_schema_version,
        "hermetic_replay_policy_contract_version": item.hermetic_replay_policy_contract_version,
        "hermetic_replay_policy_id": item.hermetic_replay_policy_id,
        "hermetic_replay_protocol_sha256": item.hermetic_replay_protocol_sha256,
        "policy_document_sha256_binding_rule": item.policy_document_sha256_binding_rule,
        "exact_policy_document_sha256_embedded": item.exact_policy_document_sha256_embedded,
        "producer_dependency_satisfied": item.producer_dependency_satisfied,
    }


def _cutoff_material(item: ProspectiveSelectionCutoffRuleV1) -> dict[str, object]:
    return {
        "rule_id": item.rule_id,
        "clock_format": item.clock_format,
        "clauses": list(item.clauses),
        "activation_timestamp_embedded": item.activation_timestamp_embedded,
    }


def _disabled_material(item: DisabledFeatureEncodingContractV1) -> dict[str, object]:
    return {
        "encoding_id": item.encoding_id,
        "numeric_value_hex": item.numeric_value_hex,
        "profile_selection_mask": item.profile_selection_mask,
        "missing_mask_reused": item.missing_mask_reused,
        "stale_mask_reused": item.stale_mask_reused,
        "source_availability_claimed": item.source_availability_claimed,
        "typed_negative_encoding_reused": item.typed_negative_encoding_reused,
        "runtime_materializer_implemented": item.runtime_materializer_implemented,
    }


def _typed_negative_material(item: TypedNegativeDispositionPolicyV1) -> dict[str, object]:
    return {
        "policy_id": item.policy_id,
        "permitted_dispositions": list(item.permitted_dispositions),
        "forbidden_dispositions": list(item.forbidden_dispositions),
        "authentication_required": item.authentication_required,
        "exact_slot_and_source_binding_required": item.exact_slot_and_source_binding_required,
        "may_enable_profile_disabled_slot": item.may_enable_profile_disabled_slot,
        "may_satisfy_enabled_required_slot": item.may_satisfy_enabled_required_slot,
        "v1_permitted_slot_count": item.v1_permitted_slot_count,
    }


def _family_by_ordinal(
    contracts: tuple[OhlcvTimeframeFinalityTransformContractV1, ...],
) -> dict[int, OhlcvTimeframeFinalityTransformContractV1]:
    return {ordinal: contract for contract in contracts for ordinal in contract.enabled_ordinals}


def _transform_by_ordinal(
    contracts: tuple[OhlcvTimeframeFinalityTransformContractV1, ...],
) -> dict[int, OhlcvFeatureTransformContractV1]:
    return {item.ordinal: item for contract in contracts for item in contract.transforms}


def _enabled_feature_material(
    profile: AdaptiveOhlcvFeatureSelectionProfileV1,
) -> list[dict[str, object]]:
    families = _family_by_ordinal(profile.timeframe_finality_transform_contracts)
    transforms = _transform_by_ordinal(profile.timeframe_finality_transform_contracts)
    return [
        {
            "ordinal": ordinal,
            "feature_name": FEATURE_SOURCE_REGISTRY_V4.slots[ordinal].feature_name,
            "configured_source_label": (
                FEATURE_SOURCE_REGISTRY_V4.slots[ordinal].configured_source_label
            ),
            "base_requirement_class": FEATURE_SOURCE_REGISTRY_V4.slots[ordinal].requirement_class,
            "profile_disposition": profile.ordered_slot_dispositions[ordinal],
            "family_id": families[ordinal].family_id,
            "physical_timeframe": families[ordinal].physical_timeframe,
            "transform_id": transforms[ordinal].transform_id,
        }
        for ordinal in profile.enabled_slot_ordinals
    ]


def _profile_material(profile: AdaptiveOhlcvFeatureSelectionProfileV1) -> dict[str, object]:
    return {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "classification": profile.classification,
        "downstream_status": profile.downstream_status,
        "base_contract": {
            "abi_schema_version": profile.base_abi_schema_version,
            "abi_sha256": profile.base_abi_sha256,
            "feature_source_registry_schema_version": profile.base_registry_schema_version,
            "feature_source_registry_sha256": profile.base_registry_sha256,
            "feature_requirement_policy_id": profile.base_requirement_policy_id,
            "slot_count": profile.base_slot_count,
            "model_ta_dependency_contract_version": profile.model_ta_dependency_contract_version,
            "model_ta_dependency_contract_sha256": profile.model_ta_dependency_contract_sha256,
            "native_core_transform_contract_version": EXISTING_CORE_CONTRACT_VERSION,
            "native_core_minimum_closed_source_rows": EXISTING_CORE_MINIMUM_SOURCE_ROWS,
            "true_1h_minimum_closed_source_rows": TRUE_1H_TA_MINIMUM_ROWS,
        },
        "selection": {
            "ordered_slot_dispositions": list(profile.ordered_slot_dispositions),
            "ordered_disposition_sha256": profile.ordered_disposition_sha256,
            "enabled_slot_ordinals": list(profile.enabled_slot_ordinals),
            "enabled_feature_names": list(profile.enabled_feature_names),
            "enabled_features": _enabled_feature_material(profile),
            "enabled_feature_list_sha256": profile.enabled_feature_list_sha256,
            "counts": {
                "enabled": len(profile.enabled_slot_ordinals),
                "enabled_required": profile.enabled_required_slot_count,
                "enabled_optional_event_dependent": (
                    profile.enabled_optional_event_dependent_slot_count
                ),
                "disabled": profile.disabled_slot_count,
                "disabled_required": profile.disabled_required_slot_count,
                "disabled_optional_event_dependent": (
                    profile.disabled_optional_event_dependent_slot_count
                ),
            },
        },
        "timeframe_finality_transform_contracts": [
            _timeframe_material(item) for item in profile.timeframe_finality_transform_contracts
        ],
        "required_producer_dependency": _producer_material(profile.producer_dependency_contract),
        "selection_cutoff_rule": _cutoff_material(profile.selection_cutoff_rule),
        "disabled_encoding": _disabled_material(profile.disabled_encoding_contract),
        "typed_negative_policy": _typed_negative_material(profile.typed_negative_policy),
        "authorization": {
            "audit_only": profile.audit_only,
            "transforms_implemented": profile.transforms_implemented,
            "per_sample_receipts_bound": profile.per_sample_receipts_bound,
            "feature_snapshot_published": profile.feature_snapshot_published,
            "consumer_eligible": profile.consumer_eligible,
            "trainer_admission_authorized": profile.trainer_admission_authorized,
            "prediction_authorized": profile.prediction_authorized,
            "paper_trading_authorized": profile.paper_trading_authorized,
            "live_execution_authorized": profile.live_execution_authorized,
            "runtime_wired": profile.runtime_wired,
        },
    }


def _validate_profile(profile: AdaptiveOhlcvFeatureSelectionProfileV1) -> None:
    exact_metadata = (
        (profile.schema_version, ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION),
        (profile.profile_id, ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID),
        (profile.classification, ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_CLASSIFICATION),
        (profile.downstream_status, ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DOWNSTREAM_STATUS),
        (profile.base_abi_schema_version, FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION),
        (profile.base_abi_sha256, FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256),
        (profile.base_registry_schema_version, FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION),
        (profile.base_registry_sha256, FEATURE_SOURCE_REGISTRY_V4_SHA256),
        (profile.base_requirement_policy_id, FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID),
        (
            profile.model_ta_dependency_contract_version,
            MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
        ),
        (
            profile.model_ta_dependency_contract_sha256,
            MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
        ),
    )
    if any(type(actual) is not str or actual != expected for actual, expected in exact_metadata):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_BASE_BINDING_DRIFT")
    if type(profile.base_slot_count) is not int or profile.base_slot_count != 446:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_BASE_SLOT_COUNT_DRIFT")
    if type(profile.ordered_slot_dispositions) is not tuple:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_NOT_EXACT_TUPLE")
    if len(profile.ordered_slot_dispositions) != 446:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_COUNT_INVALID")
    if any(
        type(value) is not str or value not in _DISPOSITIONS
        for value in profile.ordered_slot_dispositions
    ):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_INVALID")
    if type(profile.enabled_slot_ordinals) is not tuple:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINALS_NOT_EXACT_TUPLE")
    if any(
        type(value) is not int or not 0 <= value < 446 for value in profile.enabled_slot_ordinals
    ):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_INVALID")
    if len(set(profile.enabled_slot_ordinals)) != len(profile.enabled_slot_ordinals):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_DUPLICATE")
    if tuple(sorted(profile.enabled_slot_ordinals)) != profile.enabled_slot_ordinals:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_ORDER_INVALID")
    if (
        profile.enabled_slot_ordinals
        != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS
    ):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_INVENTORY_DRIFT")
    expected_names = tuple(
        FEATURE_SOURCE_REGISTRY_V4.slots[index].feature_name
        for index in profile.enabled_slot_ordinals
    )
    if (
        type(profile.enabled_feature_names) is not tuple
        or profile.enabled_feature_names != expected_names
    ):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_NAME_ORDER_DRIFT")
    if len(set(profile.enabled_feature_names)) != len(profile.enabled_feature_names):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_NAME_DUPLICATE")
    enabled = frozenset(profile.enabled_slot_ordinals)
    expected_dispositions = tuple(
        (
            PROFILE_DISABLED
            if slot.ordinal not in enabled
            else (
                ENABLED_REQUIRED
                if slot.requirement_class == REQUIREMENT_REQUIRED
                else ENABLED_OPTIONAL_EVENT_DEPENDENT
            )
        )
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
    )
    if profile.ordered_slot_dispositions != expected_dispositions:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_DRIFT")
    counts = (
        profile.enabled_required_slot_count,
        profile.enabled_optional_event_dependent_slot_count,
        profile.disabled_slot_count,
        profile.disabled_required_slot_count,
        profile.disabled_optional_event_dependent_slot_count,
    )
    expected_counts = (35, 0, 411, 348, 63)
    if any(type(value) is not int for value in counts) or counts != expected_counts:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_COUNT_DRIFT")
    if profile.timeframe_finality_transform_contracts != _TIMEFRAME_CONTRACTS:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_TRANSFORM_CONTRACT_DRIFT")
    family_ordinals = tuple(
        ordinal
        for contract in profile.timeframe_finality_transform_contracts
        for ordinal in contract.enabled_ordinals
    )
    if len(set(family_ordinals)) != len(family_ordinals):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_FAMILY_ORDINAL_DUPLICATE")
    if tuple(sorted(family_ordinals)) != profile.enabled_slot_ordinals:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_FAMILY_INVENTORY_DRIFT")
    for contract in profile.timeframe_finality_transform_contracts:
        for ordinal, name in zip(
            contract.enabled_ordinals, contract.enabled_feature_names, strict=True
        ):
            slot = FEATURE_SOURCE_REGISTRY_V4.slots[ordinal]
            if (
                slot.feature_name != name
                or slot.configured_source_label != contract.configured_source_label
            ):
                _fail("ADAPTIVE_OHLCV_PROFILE_V1_REGISTRY_FAMILY_BINDING_DRIFT")
    if profile.producer_dependency_contract != _PRODUCER_DEPENDENCY:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_PRODUCER_DEPENDENCY_DRIFT")
    if profile.selection_cutoff_rule != _SELECTION_CUTOFF_RULE:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_CUTOFF_RULE_DRIFT")
    if profile.disabled_encoding_contract != _DISABLED_ENCODING:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISABLED_ENCODING_DRIFT")
    if profile.typed_negative_policy != _TYPED_NEGATIVE_POLICY:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_POLICY_DRIFT")
    authority_values = (
        profile.transforms_implemented,
        profile.per_sample_receipts_bound,
        profile.feature_snapshot_published,
        profile.consumer_eligible,
        profile.trainer_admission_authorized,
        profile.prediction_authorized,
        profile.paper_trading_authorized,
        profile.live_execution_authorized,
        profile.runtime_wired,
    )
    if profile.audit_only is not True or any(value is not False for value in authority_values):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_AUTHORITY_MUST_REMAIN_FALSE")
    ordered_sha256 = _canonical_sha256(list(profile.ordered_slot_dispositions))
    if profile.ordered_disposition_sha256 != ordered_sha256:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_SHA256_INVALID")
    if (
        profile.ordered_disposition_sha256
        != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ORDERED_DISPOSITION_SHA256
    ):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_SHA256_DRIFT")
    enabled_sha256 = _canonical_sha256(_enabled_feature_material(profile))
    if profile.enabled_feature_list_sha256 != enabled_sha256:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_LIST_SHA256_INVALID")
    if (
        profile.enabled_feature_list_sha256
        != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256
    ):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_LIST_SHA256_DRIFT")
    profile_sha256 = _canonical_sha256(_profile_material(profile))
    if profile.profile_sha256 != profile_sha256:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_PROFILE_SHA256_INVALID")
    if profile.profile_sha256 != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_PROFILE_SHA256_DRIFT")


def build_adaptive_ohlcv_feature_selection_profile_v1(
    registry: object,
    enabled_slot_ordinals: object,
    ordered_slot_dispositions: object,
) -> AdaptiveOhlcvFeatureSelectionProfileV1:
    """Build only the exact pinned declaration from the exact v4 registry."""

    if type(registry) is not FeatureSourceRegistryV4:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_BASE_REGISTRY_NOT_EXACT_TYPE")
    feature_source_registry_v4_contract(registry)
    if registry != FEATURE_SOURCE_REGISTRY_V4:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_BASE_REGISTRY_DRIFT")
    if type(enabled_slot_ordinals) is not tuple:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINALS_NOT_EXACT_TUPLE")
    if any(type(value) is not int or not 0 <= value < 446 for value in enabled_slot_ordinals):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_INVALID")
    if len(set(enabled_slot_ordinals)) != len(enabled_slot_ordinals):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_DUPLICATE")
    if tuple(sorted(enabled_slot_ordinals)) != enabled_slot_ordinals:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_ORDER_INVALID")
    if enabled_slot_ordinals != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_INVENTORY_DRIFT")
    if type(ordered_slot_dispositions) is not tuple:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_NOT_EXACT_TUPLE")
    enabled_names = tuple(registry.slots[index].feature_name for index in enabled_slot_ordinals)
    ordered_sha256 = _canonical_sha256(list(ordered_slot_dispositions))
    skeleton = AdaptiveOhlcvFeatureSelectionProfileV1(
        schema_version=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION,
        profile_id=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        classification=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_CLASSIFICATION,
        downstream_status=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DOWNSTREAM_STATUS,
        base_abi_schema_version=FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
        base_abi_sha256=FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        base_registry_schema_version=FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION,
        base_registry_sha256=FEATURE_SOURCE_REGISTRY_V4_SHA256,
        base_requirement_policy_id=FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
        base_slot_count=FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        model_ta_dependency_contract_version=MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_VERSION,
        model_ta_dependency_contract_sha256=MODEL_TA_TECHNICAL_DEPENDENCY_CONTRACT_SHA256,
        ordered_slot_dispositions=ordered_slot_dispositions,
        ordered_disposition_sha256=ordered_sha256,
        enabled_slot_ordinals=enabled_slot_ordinals,
        enabled_feature_names=enabled_names,
        enabled_feature_list_sha256=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256,
        enabled_required_slot_count=35,
        enabled_optional_event_dependent_slot_count=0,
        disabled_slot_count=411,
        disabled_required_slot_count=348,
        disabled_optional_event_dependent_slot_count=63,
        timeframe_finality_transform_contracts=_TIMEFRAME_CONTRACTS,
        producer_dependency_contract=_PRODUCER_DEPENDENCY,
        selection_cutoff_rule=_SELECTION_CUTOFF_RULE,
        disabled_encoding_contract=_DISABLED_ENCODING,
        typed_negative_policy=_TYPED_NEGATIVE_POLICY,
        audit_only=True,
        transforms_implemented=False,
        per_sample_receipts_bound=False,
        feature_snapshot_published=False,
        consumer_eligible=False,
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        profile_sha256=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    return skeleton


def adaptive_ohlcv_feature_selection_profile_v1_contract(
    profile: AdaptiveOhlcvFeatureSelectionProfileV1,
) -> dict[str, Any]:
    """Return a detached canonical dictionary including the profile digest."""

    if type(profile) is not AdaptiveOhlcvFeatureSelectionProfileV1:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_NOT_EXACT_PROFILE")
    _validate_profile(profile)
    material = _profile_material(profile)
    material["profile_sha256"] = profile.profile_sha256
    return material


def canonical_adaptive_ohlcv_feature_selection_profile_v1_json(
    profile: AdaptiveOhlcvFeatureSelectionProfileV1,
) -> str:
    """Serialize a validated profile with deterministic canonical JSON."""

    contract = adaptive_ohlcv_feature_selection_profile_v1_contract(profile)
    try:
        return json.dumps(
            contract,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_CANONICAL_ENCODING_FAILED")


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _fail(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
        _fail(reason)
    return parsed


def validate_adaptive_ohlcv_profile_prospective_cutoff_v1(
    profile: AdaptiveOhlcvFeatureSelectionProfileV1,
    *,
    selection_observation_clocks: object,
    selection_data_cutoff: object,
    profile_published_available_at: object,
    sample_decision_time: object,
    enabled_feature_available_at: object,
    final_feature_cutoff: object,
    masa_feature_cutoff: object,
    ppo_feature_cutoff: object,
    ppo_decision_time: object,
) -> None:
    """Validate clock ordering only; success does not authorize consumption."""

    if type(profile) is not AdaptiveOhlcvFeatureSelectionProfileV1:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_NOT_EXACT_PROFILE")
    _validate_profile(profile)
    cutoff = _parse_clock(
        selection_data_cutoff,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_DATA_CUTOFF_INVALID",
    )
    published = _parse_clock(
        profile_published_available_at,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_PROFILE_PUBLISHED_AVAILABLE_AT_INVALID",
    )
    decision = _parse_clock(
        sample_decision_time,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_SAMPLE_DECISION_TIME_INVALID",
    )
    feature_cutoff = _parse_clock(
        final_feature_cutoff,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_FINAL_FEATURE_CUTOFF_INVALID",
    )
    masa_cutoff = _parse_clock(
        masa_feature_cutoff,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_MASA_FEATURE_CUTOFF_INVALID",
    )
    ppo_cutoff = _parse_clock(
        ppo_feature_cutoff,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_PPO_FEATURE_CUTOFF_INVALID",
    )
    ppo_decision = _parse_clock(
        ppo_decision_time,
        reason="ADAPTIVE_OHLCV_PROFILE_V1_PPO_DECISION_TIME_INVALID",
    )
    if type(selection_observation_clocks) is not tuple or not selection_observation_clocks:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATIONS_INVALID")
    observation_ids: list[str] = []
    for item in selection_observation_clocks:
        if type(item) is not tuple or len(item) != 3:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATION_INVALID")
        observation_id, event_time, available_at = item
        if not _valid_label(observation_id):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATION_ID_INVALID")
        observation_ids.append(observation_id)
        event = _parse_clock(
            event_time,
            reason="ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATION_EVENT_TIME_INVALID",
        )
        available = _parse_clock(
            available_at,
            reason="ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATION_AVAILABLE_AT_INVALID",
        )
        if event > available:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATION_CAUSAL_ORDER_INVALID")
        if event > cutoff:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_EVENT_AFTER_DATA_CUTOFF")
        if available > cutoff:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_AVAILABLE_AFTER_DATA_CUTOFF")
    if len(set(observation_ids)) != len(observation_ids):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_OBSERVATION_DUPLICATE")
    if not cutoff < published:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_CUTOFF_NOT_BEFORE_PUBLICATION")
    if published > decision:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_PROFILE_PUBLISHED_AFTER_SAMPLE_DECISION")
    if type(enabled_feature_available_at) is not tuple:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABILITY_NOT_EXACT_TUPLE")
    if len(enabled_feature_available_at) != len(profile.enabled_feature_names):
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABILITY_COUNT_INVALID")
    available_names: list[str] = []
    for item in enabled_feature_available_at:
        if type(item) is not tuple or len(item) != 2:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABILITY_ITEM_INVALID")
        feature_name, available_at = item
        if not _valid_label(feature_name):
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABILITY_NAME_INVALID")
        available_names.append(feature_name)
        available = _parse_clock(
            available_at,
            reason="ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABLE_AT_INVALID",
        )
        if available > decision:
            _fail("ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABLE_AFTER_SAMPLE_DECISION")
    if tuple(available_names) != profile.enabled_feature_names:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABILITY_ORDER_DRIFT")
    if not feature_cutoff < decision:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_FINAL_FEATURE_CUTOFF_NOT_BEFORE_DECISION")
    if masa_cutoff > ppo_cutoff:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_MASA_CUTOFF_AFTER_PPO_CUTOFF")
    if not ppo_cutoff < ppo_decision:
        _fail("ADAPTIVE_OHLCV_PROFILE_V1_PPO_CUTOFF_NOT_BEFORE_PPO_DECISION")


_EXPECTED_DISPOSITIONS = tuple(
    (
        PROFILE_DISABLED
        if slot.ordinal
        not in frozenset(ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS)
        else (
            ENABLED_REQUIRED
            if slot.requirement_class == REQUIREMENT_REQUIRED
            else ENABLED_OPTIONAL_EVENT_DEPENDENT
        )
    )
    for slot in FEATURE_SOURCE_REGISTRY_V4.slots
)

if tuple(CURRENT_TIMEFRAME_NATIVE_CORE_FIELDS[:12]) != tuple(
    FEATURE_SOURCE_REGISTRY_V4.slots[index].feature_name for index in range(166, 178)
) or tuple(CURRENT_TIMEFRAME_NATIVE_CORE_FIELDS[12:]) != ("htf_ret_pct", "htf_rsi_14"):
    _fail("ADAPTIVE_OHLCV_PROFILE_V1_NATIVE_CORE_DEPENDENCY_DRIFT")
if tuple(TRUE_1H_TA_FIELDS) != tuple(
    FEATURE_SOURCE_REGISTRY_V4.slots[index].feature_name for index in range(434, 442)
):
    _fail("ADAPTIVE_OHLCV_PROFILE_V1_TRUE_1H_DEPENDENCY_DRIFT")

ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1 = build_adaptive_ohlcv_feature_selection_profile_v1(
    FEATURE_SOURCE_REGISTRY_V4,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS,
    _EXPECTED_DISPOSITIONS,
)


__all__ = [
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DISABLED_SLOT_COUNT",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_REQUIRED_SLOT_COUNT",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_SLOT_COUNT",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ORDERED_DISPOSITION_SHA256",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256",
    "ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SLOT_COUNT",
    "AdaptiveOhlcvFeatureSelectionProfileV1",
    "AdaptiveOhlcvFeatureSelectionProfileV1ValidationError",
    "DisabledFeatureEncodingContractV1",
    "ENABLED_OPTIONAL_EVENT_DEPENDENT",
    "ENABLED_REQUIRED",
    "OhlcvFeatureTransformContractV1",
    "OhlcvProducerDependencyContractV1",
    "OhlcvTimeframeFinalityTransformContractV1",
    "PROFILE_DISABLED",
    "ProspectiveSelectionCutoffRuleV1",
    "TypedNegativeDispositionPolicyV1",
    "adaptive_ohlcv_feature_selection_profile_v1_contract",
    "build_adaptive_ohlcv_feature_selection_profile_v1",
    "canonical_adaptive_ohlcv_feature_selection_profile_v1_json",
    "validate_adaptive_ohlcv_profile_prospective_cutoff_v1",
]
