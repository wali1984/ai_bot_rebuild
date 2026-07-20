"""Immutable audit-only registry for the deployed 446-slot feature ABI.

The registry binds every model slot to its ordinal, feature name, configured
source label, and code-owned requirement class.  It does not read a provider,
capture a resolver branch, publish a feature snapshot, admit trainer data, or
authorize prediction or trading.  Its digest detects changes to configured
source labels that the existing name/requirement ABI digest intentionally does
not cover.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final, NoReturn

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_ABI_SCHEMA_VERSION,
    FEATURE_REQUIREMENT_POLICY_ID,
    FeatureSnapshotValidationError,
    feature_abi_contract,
    feature_requirement_classes_for_names,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3 import (
    FEATURE_SPEC,
)

FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION: Final = "trainer_feature_source_registry_v4"
FEATURE_SOURCE_REGISTRY_V4_EVIDENCE_CLASSIFICATION: Final = (
    "AUDIT_ONLY_CODE_DECLARATION_REGISTRY_UNAUTHENTICATED_UNWIRED"
)
FEATURE_SOURCE_REGISTRY_V4_DOWNSTREAM_STATUS: Final = (
    "NON_CONSUMABLE_NO_SOURCE_RECEIPT_FEATURE_PUBLICATION_TRAINER_PREDICTION_"
    "PAPER_OR_LIVE_AUTHORIZATION"
)
FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION: Final = "ordered_feature_tensor_abi_v3"
FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256: Final = (
    "e81b6dd95bfba930d67e694941f21a6d4ab5432142c25595848148c8bb42ddf9"
)
FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID: Final = "v2_hybrid_feature_requirements_v1"
FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT: Final = 446
FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT: Final = 384
FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT: Final = 62
FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT: Final = 40
FEATURE_SOURCE_REGISTRY_V4_SHA256: Final = (
    "556aa71f012a0649ee12992f07987f66a152620a7a98ea022fbfc575f96668a6"
)

REQUIREMENT_REQUIRED: Final = "REQUIRED"
REQUIREMENT_OPTIONAL_EVENT_DEPENDENT: Final = "OPTIONAL_EVENT_DEPENDENT"

MORALIS_OPTIONAL_GROUP_ID: Final = "MORALIS_OPTIONAL_EVENT_DEPENDENT"
MORALIS_CONFIGURED_SOURCE_LABEL: Final = "v2:features:moralis"
MORALIS_OPTIONAL_FEATURE_NAMES: Final = (
    "moralis_exchange_inflow_usd",
    "moralis_exchange_outflow_usd",
    "moralis_net_exchange_flow_usd",
    "moralis_whale_net_flow_usd",
    "moralis_smart_wallet_accumulation_score",
    "moralis_smart_wallet_distribution_score",
    "moralis_onchain_risk_score",
)

CONFLUENCE_OPTIONAL_GROUP_ID: Final = "ALTDATA_CONFLUENCE_OPTIONAL_EVENT_DEPENDENT"
CONFLUENCE_CONFIGURED_SOURCE_LABEL: Final = "v2:altdata:confluence"
CONFLUENCE_OPTIONAL_FEATURE_NAMES: Final = (
    "altdata_derivatives_pressure_score",
    "altdata_liquidation_sweep_risk_score",
    "altdata_social_attention_score",
    "altdata_social_euphoria_risk_score",
    "altdata_exchange_flow_pressure_usd",
    "altdata_wallet_accumulation_score",
    "altdata_wallet_distribution_score",
    "altdata_institutional_flow_score",
    "altdata_options_pin_risk_score",
    "altdata_market_regime_score",
    "altdata_confluence_long_score",
    "altdata_confluence_short_score",
    "altdata_trade_block_score",
    "altdata_reduce_size_score",
    "altdata_hedge_required_score",
)

FEATURE_SOURCE_REGISTRY_V4_EXPECTED_CONFIGURED_SOURCE_LABELS: Final = (
    "v2:altdata:confluence",
    "v2:altdata:public_intel",
    "v2:altdata:symbol_score",
    "v2:altdata:whale_walls",
    "v2:features:latest",
    "v2:features:moralis",
    "v2:features:ta",
    "v2:features:ta_full",
    "v2:features:ta_full:1h",
    "v2:liquidations:events",
    "v2:liquidations:levels",
    "v2:market:cvd",
    "v2:market:funding",
    "v2:market:fvg",
    "v2:market:liquidation_levels",
    "v2:market:liquidations:aggregate",
    "v2:market:liquidity_zones",
    "v2:market:long_short",
    "v2:market:microstructure",
    "v2:market:ohlcv",
    "v2:market:open_interest",
    "v2:market:open_interest_hist",
    "v2:market:orderbook",
    "v2:market:prices",
    "v2:market:structure",
    "v2:market:sweep_risk",
    "v2:market:trade_tape_features",
    "v2:market:volume_profile",
    "v2:market:vwap",
    "v2:microstructure:adversarial_features",
    "v2:microstructure:cascade_context",
    "v2:microstructure:cross_venue_confirmation",
    "v2:microstructure:feed_quality",
    "v2:microstructure:sweep_risk",
    "v2:microstructure:trade_tape_confirmation",
    "v2:microstructure:trust_score",
    "v2:orchestrator:decisions",
    "v2:orderbook:features",
    "v2:paper:positions",
    "v2:risk:decisions",
)

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$", re.ASCII)
_REQUIREMENT_CLASSES = frozenset({REQUIREMENT_REQUIRED, REQUIREMENT_OPTIONAL_EVENT_DEPENDENT})
_CONSTRUCTION_TOKEN = object()


class FeatureSourceRegistryV4ValidationError(ValueError):
    """The code declarations do not reproduce the pinned deployed registry."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise FeatureSourceRegistryV4ValidationError(*reasons) from None


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
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("FEATURE_SOURCE_REGISTRY_V4_CANONICAL_ENCODING_FAILED")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class FeatureSourceRegistrySlotV4:
    """One exact, ordinal model-slot declaration."""

    ordinal: int
    feature_name: str
    configured_source_label: str
    requirement_class: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_SOURCE_REGISTRY_V4_FACTORY_CONSTRUCTION_REQUIRED")
        if (
            type(self.ordinal) is not int
            or not 0 <= self.ordinal < FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
        ):
            _fail("FEATURE_SOURCE_REGISTRY_V4_SLOT_ORDINAL_INVALID")
        if not _valid_label(self.feature_name):
            _fail("FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_INVALID")
        if not _valid_label(self.configured_source_label):
            _fail("FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_INVALID")
        if (
            type(self.requirement_class) is not str
            or self.requirement_class not in _REQUIREMENT_CLASSES
        ):
            _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_CLASS_INVALID")


@dataclass(frozen=True, slots=True)
class FeatureSourceOptionalGroupV4:
    """A named optional group whose membership and source are pinned."""

    group_id: str
    configured_source_label: str
    slot_ordinals: tuple[int, ...]
    feature_names: tuple[str, ...]
    requirement_class: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_SOURCE_REGISTRY_V4_FACTORY_CONSTRUCTION_REQUIRED")
        if not _valid_label(self.group_id) or not _valid_label(self.configured_source_label):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_LABEL_INVALID")
        if type(self.slot_ordinals) is not tuple or type(self.feature_names) is not tuple:
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_TYPE_INVALID")
        if len(self.slot_ordinals) == 0 or len(self.slot_ordinals) != len(self.feature_names):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_DIMENSION_INVALID")
        if any(
            type(value) is not int or not 0 <= value < FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
            for value in self.slot_ordinals
        ):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_ORDINAL_INVALID")
        if tuple(sorted(set(self.slot_ordinals))) != self.slot_ordinals:
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_ORDINAL_INVALID")
        if any(not _valid_label(value) for value in self.feature_names):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_FEATURE_NAME_INVALID")
        if len(set(self.feature_names)) != len(self.feature_names):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_FEATURE_NAME_DUPLICATE")
        if (
            type(self.requirement_class) is not str
            or self.requirement_class != REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
        ):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_REQUIREMENT_INVALID")


@dataclass(frozen=True, slots=True)
class FeatureSourceRegistryV4:
    """Factory-only, immutable representation of the complete registry."""

    schema_version: str
    evidence_classification: str
    downstream_status: str
    abi_schema_version: str
    abi_sha256: str
    feature_requirement_policy_id: str
    slot_count: int
    required_slot_count: int
    optional_event_dependent_slot_count: int
    source_label_count: int
    configured_source_labels: tuple[str, ...]
    optional_source_groups: tuple[FeatureSourceOptionalGroupV4, ...]
    slots: tuple[FeatureSourceRegistrySlotV4, ...]
    audit_only: bool
    runtime_source_reads_performed: bool
    source_registry_authenticated: bool
    resolver_branch_capture_authenticated: bool
    source_receipts_authenticated: bool
    feature_snapshot_published: bool
    consumer_eligible: bool
    feature_publication_authorized: bool
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    registry_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_SOURCE_REGISTRY_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_registry(self)


def _slot_dict(slot: FeatureSourceRegistrySlotV4) -> dict[str, object]:
    return {
        "ordinal": slot.ordinal,
        "feature_name": slot.feature_name,
        "configured_source_label": slot.configured_source_label,
        "requirement_class": slot.requirement_class,
    }


def _group_dict(group: FeatureSourceOptionalGroupV4) -> dict[str, object]:
    return {
        "group_id": group.group_id,
        "configured_source_label": group.configured_source_label,
        "slot_ordinals": list(group.slot_ordinals),
        "feature_names": list(group.feature_names),
        "requirement_class": group.requirement_class,
    }


def _registry_material_from_parts(
    *,
    configured_source_labels: tuple[str, ...],
    optional_source_groups: tuple[FeatureSourceOptionalGroupV4, ...],
    slots: tuple[FeatureSourceRegistrySlotV4, ...],
) -> dict[str, object]:
    return {
        "schema_version": FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION,
        "evidence_classification": FEATURE_SOURCE_REGISTRY_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": FEATURE_SOURCE_REGISTRY_V4_DOWNSTREAM_STATUS,
        "feature_abi": {
            "schema_version": FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
            "sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
            "feature_requirement_policy_id": FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
            "slot_count": FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
            "required_slot_count": FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
            "optional_event_dependent_slot_count": FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
        },
        "configured_source_inventory": {
            "ordering": "LEXICOGRAPHIC_ASCII",
            "source_label_count": FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT,
            "configured_source_labels": list(configured_source_labels),
        },
        "optional_source_groups": [_group_dict(group) for group in optional_source_groups],
        "slots": [_slot_dict(slot) for slot in slots],
        "authorization": {
            "audit_only": True,
            "runtime_source_reads_performed": False,
            "source_registry_authenticated": False,
            "resolver_branch_capture_authenticated": False,
            "source_receipts_authenticated": False,
            "feature_snapshot_published": False,
            "consumer_eligible": False,
            "feature_publication_authorized": False,
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
        },
    }


def _registry_material(registry: FeatureSourceRegistryV4) -> dict[str, object]:
    return _registry_material_from_parts(
        configured_source_labels=registry.configured_source_labels,
        optional_source_groups=registry.optional_source_groups,
        slots=registry.slots,
    )


def _validate_registry(registry: FeatureSourceRegistryV4) -> None:
    metadata_values = (
        registry.schema_version,
        registry.evidence_classification,
        registry.downstream_status,
        registry.abi_schema_version,
        registry.abi_sha256,
        registry.feature_requirement_policy_id,
    )
    if any(type(value) is not str for value in metadata_values):
        _fail("FEATURE_SOURCE_REGISTRY_V4_METADATA_TYPE_INVALID")
    if registry.schema_version != FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION:
        _fail("FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION_MISMATCH")
    if registry.evidence_classification != FEATURE_SOURCE_REGISTRY_V4_EVIDENCE_CLASSIFICATION:
        _fail("FEATURE_SOURCE_REGISTRY_V4_EVIDENCE_CLASSIFICATION_MISMATCH")
    if registry.downstream_status != FEATURE_SOURCE_REGISTRY_V4_DOWNSTREAM_STATUS:
        _fail("FEATURE_SOURCE_REGISTRY_V4_DOWNSTREAM_STATUS_MISMATCH")
    if registry.abi_schema_version != FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION:
        _fail("FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION_MISMATCH")
    if registry.abi_sha256 != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256:
        _fail("FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256_MISMATCH")
    if registry.feature_requirement_policy_id != FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID_MISMATCH")
    expected_counts = (
        FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
        FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
        FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT,
    )
    actual_counts = (
        registry.slot_count,
        registry.required_slot_count,
        registry.optional_event_dependent_slot_count,
        registry.source_label_count,
    )
    if any(type(value) is not int for value in actual_counts) or actual_counts != expected_counts:
        _fail("FEATURE_SOURCE_REGISTRY_V4_COUNT_MISMATCH")
    if type(registry.optional_source_groups) is not tuple or type(registry.slots) is not tuple:
        _fail("FEATURE_SOURCE_REGISTRY_V4_COLLECTION_TYPE_INVALID")
    if type(registry.configured_source_labels) is not tuple or any(
        not _valid_label(value) for value in registry.configured_source_labels
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_SOURCE_INVENTORY_TYPE_INVALID")
    if (
        registry.configured_source_labels
        != FEATURE_SOURCE_REGISTRY_V4_EXPECTED_CONFIGURED_SOURCE_LABELS
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_SOURCE_INVENTORY_MISMATCH")
    if len(registry.slots) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT:
        _fail("FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT_MISMATCH")
    if any(type(slot) is not FeatureSourceRegistrySlotV4 for slot in registry.slots):
        _fail("FEATURE_SOURCE_REGISTRY_V4_SLOT_TYPE_INVALID")
    if any(
        type(group) is not FeatureSourceOptionalGroupV4 for group in registry.optional_source_groups
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_TYPE_INVALID")
    if tuple(slot.ordinal for slot in registry.slots) != tuple(range(len(registry.slots))):
        _fail("FEATURE_SOURCE_REGISTRY_V4_SLOT_ORDER_INVALID")
    if len({slot.feature_name for slot in registry.slots}) != len(registry.slots):
        _fail("FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_DUPLICATE")
    if (
        tuple(sorted({slot.configured_source_label for slot in registry.slots}))
        != registry.configured_source_labels
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_SOURCE_INVENTORY_MISMATCH")
    if (
        sum(slot.requirement_class == REQUIREMENT_REQUIRED for slot in registry.slots)
        != registry.required_slot_count
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT_MISMATCH")
    if (
        sum(
            slot.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
            for slot in registry.slots
        )
        != registry.optional_event_dependent_slot_count
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT_MISMATCH")
    expected_groups = (
        (
            MORALIS_OPTIONAL_GROUP_ID,
            MORALIS_CONFIGURED_SOURCE_LABEL,
            MORALIS_OPTIONAL_FEATURE_NAMES,
        ),
        (
            CONFLUENCE_OPTIONAL_GROUP_ID,
            CONFLUENCE_CONFIGURED_SOURCE_LABEL,
            CONFLUENCE_OPTIONAL_FEATURE_NAMES,
        ),
    )
    if len(registry.optional_source_groups) != len(expected_groups):
        _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUPS_MISMATCH")
    for group, (group_id, source_label, feature_names) in zip(
        registry.optional_source_groups, expected_groups, strict=True
    ):
        if (
            group.group_id != group_id
            or group.configured_source_label != source_label
            or group.feature_names != feature_names
        ):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUPS_MISMATCH")
        if any(not 0 <= index < len(registry.slots) for index in group.slot_ordinals):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_ORDINAL_INVALID")
        selected = tuple(registry.slots[index] for index in group.slot_ordinals)
        if tuple(slot.feature_name for slot in selected) != feature_names or any(
            slot.configured_source_label != source_label
            or slot.requirement_class != REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
            for slot in selected
        ):
            _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_BINDING_MISMATCH")
    if registry.audit_only is not True:
        _fail("FEATURE_SOURCE_REGISTRY_V4_AUDIT_ONLY_MUST_REMAIN_TRUE")
    authority_values = (
        registry.runtime_source_reads_performed,
        registry.source_registry_authenticated,
        registry.resolver_branch_capture_authenticated,
        registry.source_receipts_authenticated,
        registry.feature_snapshot_published,
        registry.consumer_eligible,
        registry.feature_publication_authorized,
        registry.trainer_admission_authorized,
        registry.prediction_authorized,
        registry.paper_trading_authorized,
        registry.live_execution_authorized,
    )
    if any(value is not False for value in authority_values):
        _fail("FEATURE_SOURCE_REGISTRY_V4_AUTHORITY_MUST_REMAIN_FALSE")
    calculated_sha256 = _canonical_sha256(_registry_material(registry))
    if type(registry.registry_sha256) is not str or registry.registry_sha256 != calculated_sha256:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REGISTRY_SHA256_INVALID")
    if calculated_sha256 != FEATURE_SOURCE_REGISTRY_V4_SHA256:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REGISTRY_SHA256_MISMATCH")


def _strict_feature_spec(feature_spec: object) -> tuple[tuple[str, str], ...]:
    if type(feature_spec) is not tuple:
        _fail("FEATURE_SOURCE_REGISTRY_V4_FEATURE_SPEC_NOT_EXACT_TUPLE")
    if len(feature_spec) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT:
        _fail("FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT_MISMATCH")
    parsed: list[tuple[str, str]] = []
    for item in feature_spec:
        if type(item) is not tuple or len(item) != 2:
            _fail("FEATURE_SOURCE_REGISTRY_V4_FEATURE_SPEC_ITEM_INVALID")
        feature_name, source_label = item
        if not _valid_label(feature_name):
            _fail("FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_INVALID")
        if not _valid_label(source_label):
            _fail("FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_INVALID")
        parsed.append((feature_name, source_label))
    names = tuple(feature_name for feature_name, _source_label in parsed)
    if len(set(names)) != len(names):
        _fail("FEATURE_SOURCE_REGISTRY_V4_FEATURE_NAME_DUPLICATE")
    return tuple(parsed)


def _strict_requirements(requirement_classes: object) -> tuple[str, ...]:
    if type(requirement_classes) is not tuple:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIREMENTS_NOT_EXACT_TUPLE")
    if len(requirement_classes) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_DIMENSION_MISMATCH")
    if any(
        type(value) is not str or value not in _REQUIREMENT_CLASSES for value in requirement_classes
    ):
        _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_CLASS_INVALID")
    return requirement_classes


def _optional_group(
    *,
    group_id: str,
    source_label: str,
    expected_feature_names: tuple[str, ...],
    slots: tuple[FeatureSourceRegistrySlotV4, ...],
) -> FeatureSourceOptionalGroupV4:
    selected = tuple(slot for slot in slots if slot.configured_source_label == source_label)
    if tuple(slot.feature_name for slot in selected) != expected_feature_names:
        _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUPS_MISMATCH")
    if any(slot.requirement_class != REQUIREMENT_OPTIONAL_EVENT_DEPENDENT for slot in selected):
        _fail("FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_GROUP_REQUIREMENT_INVALID")
    return FeatureSourceOptionalGroupV4(
        group_id=group_id,
        configured_source_label=source_label,
        slot_ordinals=tuple(slot.ordinal for slot in selected),
        feature_names=tuple(slot.feature_name for slot in selected),
        requirement_class=REQUIREMENT_OPTIONAL_EVENT_DEPENDENT,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def build_feature_source_registry_v4(
    feature_spec: object,
    ordered_requirement_classes: object,
) -> FeatureSourceRegistryV4:
    """Validate exact deployed declarations and return their immutable registry."""

    if FEATURE_ABI_SCHEMA_VERSION != FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION:
        _fail("FEATURE_SOURCE_REGISTRY_V4_UPSTREAM_ABI_SCHEMA_VERSION_MISMATCH")
    if FEATURE_REQUIREMENT_POLICY_ID != FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID:
        _fail("FEATURE_SOURCE_REGISTRY_V4_UPSTREAM_REQUIREMENT_POLICY_ID_MISMATCH")
    parsed_spec = _strict_feature_spec(feature_spec)
    requirements = _strict_requirements(ordered_requirement_classes)
    names = tuple(feature_name for feature_name, _source_label in parsed_spec)
    try:
        policy_requirements = feature_requirement_classes_for_names(names)
    except FeatureSnapshotValidationError as exc:
        raise FeatureSourceRegistryV4ValidationError(
            "FEATURE_SOURCE_REGISTRY_V4_UPSTREAM_REQUIREMENT_POLICY_INVALID"
        ) from exc
    if requirements != policy_requirements:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_MISMATCH")
    try:
        abi_sha256 = stable_sha256(
            feature_abi_contract(
                names,
                ordered_feature_requirement_classes=requirements,
            )
        )
    except FeatureSnapshotValidationError as exc:
        raise FeatureSourceRegistryV4ValidationError(
            "FEATURE_SOURCE_REGISTRY_V4_UPSTREAM_ABI_CONTRACT_INVALID"
        ) from exc
    if abi_sha256 != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256:
        _fail("FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256_MISMATCH")
    slots = tuple(
        FeatureSourceRegistrySlotV4(
            ordinal=ordinal,
            feature_name=feature_name,
            configured_source_label=source_label,
            requirement_class=requirements[ordinal],
            _construction_token=_CONSTRUCTION_TOKEN,
        )
        for ordinal, (feature_name, source_label) in enumerate(parsed_spec)
    )
    configured_source_labels = tuple(sorted({slot.configured_source_label for slot in slots}))
    if configured_source_labels != FEATURE_SOURCE_REGISTRY_V4_EXPECTED_CONFIGURED_SOURCE_LABELS:
        _fail("FEATURE_SOURCE_REGISTRY_V4_SOURCE_INVENTORY_MISMATCH")
    optional_source_groups = (
        _optional_group(
            group_id=MORALIS_OPTIONAL_GROUP_ID,
            source_label=MORALIS_CONFIGURED_SOURCE_LABEL,
            expected_feature_names=MORALIS_OPTIONAL_FEATURE_NAMES,
            slots=slots,
        ),
        _optional_group(
            group_id=CONFLUENCE_OPTIONAL_GROUP_ID,
            source_label=CONFLUENCE_CONFIGURED_SOURCE_LABEL,
            expected_feature_names=CONFLUENCE_OPTIONAL_FEATURE_NAMES,
            slots=slots,
        ),
    )
    material = _registry_material_from_parts(
        configured_source_labels=configured_source_labels,
        optional_source_groups=optional_source_groups,
        slots=slots,
    )
    registry_sha256 = _canonical_sha256(material)
    if registry_sha256 != FEATURE_SOURCE_REGISTRY_V4_SHA256:
        _fail("FEATURE_SOURCE_REGISTRY_V4_REGISTRY_SHA256_MISMATCH")
    return FeatureSourceRegistryV4(
        schema_version=FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION,
        evidence_classification=FEATURE_SOURCE_REGISTRY_V4_EVIDENCE_CLASSIFICATION,
        downstream_status=FEATURE_SOURCE_REGISTRY_V4_DOWNSTREAM_STATUS,
        abi_schema_version=FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
        abi_sha256=FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        feature_requirement_policy_id=FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
        slot_count=FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        required_slot_count=FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
        optional_event_dependent_slot_count=FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
        source_label_count=FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT,
        configured_source_labels=configured_source_labels,
        optional_source_groups=optional_source_groups,
        slots=slots,
        audit_only=True,
        runtime_source_reads_performed=False,
        source_registry_authenticated=False,
        resolver_branch_capture_authenticated=False,
        source_receipts_authenticated=False,
        feature_snapshot_published=False,
        consumer_eligible=False,
        feature_publication_authorized=False,
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        registry_sha256=registry_sha256,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def feature_source_registry_v4_contract(
    registry: FeatureSourceRegistryV4,
) -> dict[str, Any]:
    """Return a detached canonical dictionary including the registry digest."""

    if type(registry) is not FeatureSourceRegistryV4:
        _fail("FEATURE_SOURCE_REGISTRY_V4_NOT_EXACT_REGISTRY")
    _validate_registry(registry)
    contract = _registry_material(registry)
    contract["registry_sha256"] = registry.registry_sha256
    return contract


def canonical_feature_source_registry_v4_json(
    registry: FeatureSourceRegistryV4,
) -> str:
    """Serialize a validated registry with deterministic canonical JSON."""

    contract = feature_source_registry_v4_contract(registry)
    try:
        return json.dumps(
            contract,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("FEATURE_SOURCE_REGISTRY_V4_CANONICAL_ENCODING_FAILED")


_CURRENT_REQUIREMENTS = feature_requirement_classes_for_names(
    tuple(feature_name for feature_name, _source_label in FEATURE_SPEC)
)
FEATURE_SOURCE_REGISTRY_V4 = build_feature_source_registry_v4(
    FEATURE_SPEC,
    _CURRENT_REQUIREMENTS,
)


__all__ = [
    "CONFLUENCE_CONFIGURED_SOURCE_LABEL",
    "CONFLUENCE_OPTIONAL_FEATURE_NAMES",
    "CONFLUENCE_OPTIONAL_GROUP_ID",
    "FEATURE_SOURCE_REGISTRY_V4",
    "FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION",
    "FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256",
    "FEATURE_SOURCE_REGISTRY_V4_DOWNSTREAM_STATUS",
    "FEATURE_SOURCE_REGISTRY_V4_EVIDENCE_CLASSIFICATION",
    "FEATURE_SOURCE_REGISTRY_V4_EXPECTED_CONFIGURED_SOURCE_LABELS",
    "FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT",
    "FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT",
    "FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID",
    "FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION",
    "FEATURE_SOURCE_REGISTRY_V4_SHA256",
    "FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT",
    "FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT",
    "FeatureSourceOptionalGroupV4",
    "FeatureSourceRegistrySlotV4",
    "FeatureSourceRegistryV4",
    "FeatureSourceRegistryV4ValidationError",
    "MORALIS_CONFIGURED_SOURCE_LABEL",
    "MORALIS_OPTIONAL_FEATURE_NAMES",
    "MORALIS_OPTIONAL_GROUP_ID",
    "REQUIREMENT_OPTIONAL_EVENT_DEPENDENT",
    "REQUIREMENT_REQUIRED",
    "build_feature_source_registry_v4",
    "canonical_feature_source_registry_v4_json",
    "feature_source_registry_v4_contract",
]
