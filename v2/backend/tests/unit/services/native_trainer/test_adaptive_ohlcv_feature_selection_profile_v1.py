from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DISABLED_SLOT_COUNT,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_REQUIRED_SLOT_COUNT,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_SLOT_COUNT,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ORDERED_DISPOSITION_SHA256,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    ENABLED_OPTIONAL_EVENT_DEPENDENT,
    ENABLED_REQUIRED,
    PROFILE_DISABLED,
    AdaptiveOhlcvFeatureSelectionProfileV1ValidationError,
    adaptive_ohlcv_feature_selection_profile_v1_contract,
    build_adaptive_ohlcv_feature_selection_profile_v1,
    canonical_adaptive_ohlcv_feature_selection_profile_v1_json,
    validate_adaptive_ohlcv_profile_prospective_cutoff_v1,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    REQUIREMENT_OPTIONAL_EVENT_DEPENDENT,
)

_PROFILE = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1
_RAW_ORDINALS = (10, 11, *range(14, 25), 159, 160)
_TRANSFORM_ORDINALS = tuple(range(166, 178))
_TRUE_1H_ORDINALS = tuple(range(434, 442))
_EXPECTED_ENABLED = (*_RAW_ORDINALS, *_TRANSFORM_ORDINALS, *_TRUE_1H_ORDINALS)


def _assert_reason(
    exc_info: pytest.ExceptionInfo[AdaptiveOhlcvFeatureSelectionProfileV1ValidationError],
    reason: str,
) -> None:
    assert reason in exc_info.value.reasons


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _valid_cutoff_arguments() -> dict[str, object]:
    return {
        "selection_observation_clocks": (
            (
                "selection-audit-row-1",
                "2026-07-20T23:59:00.000000Z",
                "2026-07-21T00:01:00.000000Z",
            ),
            (
                "selection-audit-row-2",
                "2026-07-21T00:00:00.000000Z",
                "2026-07-21T00:02:00.000000Z",
            ),
        ),
        "selection_data_cutoff": "2026-07-21T00:02:00.000000Z",
        "profile_published_available_at": "2026-07-21T00:03:00.000000Z",
        "sample_decision_time": "2026-07-21T01:00:00.000000Z",
        "enabled_feature_available_at": tuple(
            (name, "2026-07-21T00:56:00.000000Z") for name in _PROFILE.enabled_feature_names
        ),
        "final_feature_cutoff": "2026-07-21T00:55:00.000000Z",
        "masa_feature_cutoff": "2026-07-21T00:54:00.000000Z",
        "ppo_feature_cutoff": "2026-07-21T00:55:00.000000Z",
        "ppo_decision_time": "2026-07-21T01:00:00.000000Z",
    }


def test_profile_pins_base_abi_registry_policy_counts_and_hashes() -> None:
    profile = _PROFILE

    assert profile.schema_version == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION
    assert profile.profile_id == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID
    assert profile.profile_id == "OHLCV_BOOTSTRAP_5M_1H_V1"
    assert profile.base_abi_sha256 == FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
    assert profile.base_registry_sha256 == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert profile.base_requirement_policy_id == FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID
    assert len(profile.ordered_slot_dispositions) == 446
    assert (
        len(profile.enabled_slot_ordinals)
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_SLOT_COUNT
        == 35
    )
    assert (
        profile.enabled_required_slot_count
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_REQUIRED_SLOT_COUNT
        == 35
    )
    assert profile.enabled_optional_event_dependent_slot_count == 0
    assert (
        profile.disabled_slot_count
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_DISABLED_SLOT_COUNT
        == 411
    )
    assert profile.disabled_required_slot_count == 348
    assert profile.disabled_optional_event_dependent_slot_count == 63
    assert (
        profile.ordered_disposition_sha256
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ORDERED_DISPOSITION_SHA256
    )
    assert (
        profile.enabled_feature_list_sha256
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256
    )
    assert profile.profile_sha256 == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256


def test_exact_enabled_order_and_all_other_slots_are_profile_disabled() -> None:
    assert ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_ORDINALS == _EXPECTED_ENABLED
    assert _PROFILE.enabled_slot_ordinals == _EXPECTED_ENABLED
    assert _PROFILE.enabled_feature_names == tuple(
        FEATURE_SOURCE_REGISTRY_V4.slots[index].feature_name for index in _EXPECTED_ENABLED
    )
    assert all(
        _PROFILE.ordered_slot_dispositions[index] == ENABLED_REQUIRED for index in _EXPECTED_ENABLED
    )
    assert sum(value == ENABLED_REQUIRED for value in _PROFILE.ordered_slot_dispositions) == 35
    assert (
        sum(
            value == ENABLED_OPTIONAL_EVENT_DEPENDENT
            for value in _PROFILE.ordered_slot_dispositions
        )
        == 0
    )
    assert sum(value == PROFILE_DISABLED for value in _PROFILE.ordered_slot_dispositions) == 411
    assert all(
        _PROFILE.ordered_slot_dispositions[index] == PROFILE_DISABLED
        for index in range(446)
        if index not in frozenset(_EXPECTED_ENABLED)
    )


def test_proxy_higher_timeframe_features_are_explicitly_disabled() -> None:
    assert FEATURE_SOURCE_REGISTRY_V4.slots[178].feature_name == "htf_ret_pct"
    assert FEATURE_SOURCE_REGISTRY_V4.slots[179].feature_name == "htf_rsi_14"
    assert _PROFILE.ordered_slot_dispositions[178:180] == (
        PROFILE_DISABLED,
        PROFILE_DISABLED,
    )
    assert all(
        contract.proxy_higher_timeframe_allowed is False
        for contract in _PROFILE.timeframe_finality_transform_contracts
    )


def test_timeframe_finality_transform_contracts_are_exact_and_non_claiming() -> None:
    raw, transforms_5m, true_1h = _PROFILE.timeframe_finality_transform_contracts

    assert raw.enabled_ordinals == _RAW_ORDINALS
    assert transforms_5m.enabled_ordinals == _TRANSFORM_ORDINALS
    assert true_1h.enabled_ordinals == _TRUE_1H_ORDINALS
    assert (
        raw.physical_timeframe,
        transforms_5m.physical_timeframe,
        true_1h.physical_timeframe,
    ) == (
        "5m",
        "5m",
        "1h",
    )
    assert true_1h.enabled_feature_names == (
        "htf1h_taf_rsi",
        "htf1h_taf_adx",
        "htf1h_taf_macd_hist",
        "htf1h_taf_atr",
        "htf1h_taf_mfi",
        "htf1h_taf_willr",
        "htf1h_taf_natr",
        "htf1h_taf_cci",
    )
    assert transforms_5m.family_minimum_closed_source_rows == 71
    assert true_1h.family_minimum_closed_source_rows == 34
    true_range = next(item for item in transforms_5m.transforms if item.ordinal == 170)
    assert true_range.feature_name == "true_range_pct"
    assert true_range.transform_id == "WILDER_ATR_14_OVER_CLOSE_V1"
    assert true_range.minimum_closed_source_rows == 15
    for contract in (raw, transforms_5m, true_1h):
        assert contract.unfinished_candles_allowed is False
        assert contract.transform_implementation_present is False
        assert contract.per_sample_receipts_bound is False
        assert contract.finality_rule == "EVERY_INPUT_CANDLE_CLOSE_TIME_STRICTLY_LT_DECISION_TIME"
        assert contract.availability_rule == "EVERY_SOURCE_AND_OUTPUT_AVAILABLE_AT_LE_DECISION_TIME"
        assert "REST_ALLOWED_FOR_CAUSAL_HISTORY_ONLY" in contract.historical_lookback_policy
        assert (
            contract.latest_decision_bound_row_policy == "FINALIZED_LIVE_BINANCE_WSS_ROW_REQUIRED"
        )
        assert all(item.implementation_present is False for item in contract.transforms)
        assert all(item.per_sample_receipt_bound is False for item in contract.transforms)


def test_required_producer_policy_is_a_dependency_not_sample_proof() -> None:
    dependency = _PROFILE.producer_dependency_contract

    assert dependency.source_evidence_profile_id == "canonical_binance_closed_ohlcv_profile_v4"
    assert dependency.hermetic_replay_policy_id == "canonical-binance-ohlcv-hermetic-replay"
    assert dependency.hermetic_replay_protocol_sha256 == (
        "055794d2fc9d1ce6c2c5383a6f73a24ca403abb47cbbcb14d252b62a108fdee9"
    )
    assert dependency.exact_policy_document_sha256_embedded is False
    assert dependency.producer_dependency_satisfied is False
    assert "EACH_SAMPLE_RECEIPT_MUST_BIND" in dependency.policy_document_sha256_binding_rule


def test_disabled_encoding_is_separate_from_missing_stale_and_typed_negative() -> None:
    encoding = _PROFILE.disabled_encoding_contract

    assert encoding.numeric_value_hex == "0x0.0p+0"
    assert encoding.profile_selection_mask == 0
    assert encoding.missing_mask_reused is False
    assert encoding.stale_mask_reused is False
    assert encoding.source_availability_claimed is False
    assert encoding.typed_negative_encoding_reused is False
    assert encoding.runtime_materializer_implemented is False


def test_typed_negatives_cannot_enable_disabled_or_satisfy_required_slots() -> None:
    policy = _PROFILE.typed_negative_policy
    base_optional_ordinals = tuple(
        slot.ordinal
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        if slot.requirement_class == REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
    )

    assert policy.permitted_dispositions == (ENABLED_OPTIONAL_EVENT_DEPENDENT,)
    assert policy.forbidden_dispositions == (PROFILE_DISABLED, ENABLED_REQUIRED)
    assert policy.authentication_required is True
    assert policy.exact_slot_and_source_binding_required is True
    assert policy.may_enable_profile_disabled_slot is False
    assert policy.may_satisfy_enabled_required_slot is False
    assert policy.v1_permitted_slot_count == 0
    assert len(base_optional_ordinals) == 63
    assert all(
        _PROFILE.ordered_slot_dispositions[index] == PROFILE_DISABLED
        for index in base_optional_ordinals
    )


def test_contract_is_canonical_detached_and_all_hashes_recompute() -> None:
    contract = adaptive_ohlcv_feature_selection_profile_v1_contract(_PROFILE)
    canonical = canonical_adaptive_ohlcv_feature_selection_profile_v1_json(_PROFILE)

    assert json.loads(canonical) == contract
    digest_material = dict(contract)
    assert (
        digest_material.pop("profile_sha256") == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
    )
    assert (
        hashlib.sha256(_canonical(digest_material)).hexdigest()
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
    )
    selection = contract["selection"]
    assert (
        hashlib.sha256(_canonical(selection["ordered_slot_dispositions"])).hexdigest()
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ORDERED_DISPOSITION_SHA256
    )
    assert (
        hashlib.sha256(_canonical(selection["enabled_features"])).hexdigest()
        == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ENABLED_LIST_SHA256
    )
    selection["ordered_slot_dispositions"][10] = PROFILE_DISABLED
    selection["enabled_features"][0]["feature_name"] = "caller-mutation"
    assert _PROFILE.ordered_slot_dispositions[10] == ENABLED_REQUIRED
    assert _PROFILE.enabled_feature_names[0] == "quote_volume"


def test_profile_and_nested_records_are_immutable_and_factory_only() -> None:
    with pytest.raises(FrozenInstanceError):
        _PROFILE.profile_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _PROFILE.timeframe_finality_transform_contracts[0].family_id = "changed"  # type: ignore[misc]
    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as exc_info:
        replace(_PROFILE, consumer_eligible=True)
    _assert_reason(exc_info, "ADAPTIVE_OHLCV_PROFILE_V1_AUTHORITY_MUST_REMAIN_FALSE")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        (
            "base_registry_sha256",
            "0" * 64,
            "ADAPTIVE_OHLCV_PROFILE_V1_BASE_BINDING_DRIFT",
        ),
        (
            "ordered_disposition_sha256",
            "0" * 64,
            "ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_SHA256_INVALID",
        ),
        (
            "enabled_feature_list_sha256",
            "0" * 64,
            "ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_LIST_SHA256_INVALID",
        ),
        (
            "profile_sha256",
            "0" * 64,
            "ADAPTIVE_OHLCV_PROFILE_V1_PROFILE_SHA256_INVALID",
        ),
    ),
)
def test_digest_and_base_binding_tampering_fails_closed(
    field: str,
    value: object,
    reason: str,
) -> None:
    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as exc_info:
        replace(_PROFILE, **{field: value})
    _assert_reason(exc_info, reason)


def test_transform_contract_tampering_fails_closed() -> None:
    family = _PROFILE.timeframe_finality_transform_contracts[1]
    changed_transform = replace(family.transforms[0], transform_id="FORGED_TRANSFORM_V1")
    changed_family = replace(
        family,
        transforms=(changed_transform, *family.transforms[1:]),
    )

    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as exc_info:
        replace(
            _PROFILE,
            timeframe_finality_transform_contracts=(
                _PROFILE.timeframe_finality_transform_contracts[0],
                changed_family,
                _PROFILE.timeframe_finality_transform_contracts[2],
            ),
        )
    _assert_reason(exc_info, "ADAPTIVE_OHLCV_PROFILE_V1_TIMEFRAME_TRANSFORM_CONTRACT_DRIFT")


@pytest.mark.parametrize(
    ("enabled", "dispositions", "reason"),
    (
        (
            list(_EXPECTED_ENABLED),
            _PROFILE.ordered_slot_dispositions,
            "ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINALS_NOT_EXACT_TUPLE",
        ),
        (
            (True, *_EXPECTED_ENABLED[1:]),
            _PROFILE.ordered_slot_dispositions,
            "ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_INVALID",
        ),
        (
            (_EXPECTED_ENABLED[0], *_EXPECTED_ENABLED),
            _PROFILE.ordered_slot_dispositions,
            "ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_DUPLICATE",
        ),
        (
            (_EXPECTED_ENABLED[1], _EXPECTED_ENABLED[0], *_EXPECTED_ENABLED[2:]),
            _PROFILE.ordered_slot_dispositions,
            "ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_ORDER_INVALID",
        ),
        (
            _EXPECTED_ENABLED[:-1],
            _PROFILE.ordered_slot_dispositions,
            "ADAPTIVE_OHLCV_PROFILE_V1_ENABLED_ORDINAL_INVENTORY_DRIFT",
        ),
        (
            _EXPECTED_ENABLED,
            list(_PROFILE.ordered_slot_dispositions),
            "ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_NOT_EXACT_TUPLE",
        ),
        (
            _EXPECTED_ENABLED,
            _PROFILE.ordered_slot_dispositions[:-1],
            "ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_COUNT_INVALID",
        ),
    ),
)
def test_builder_rejects_type_duplicate_order_count_and_inventory_drift(
    enabled: object,
    dispositions: object,
    reason: str,
) -> None:
    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as exc_info:
        build_adaptive_ohlcv_feature_selection_profile_v1(
            FEATURE_SOURCE_REGISTRY_V4,
            enabled,
            dispositions,
        )
    _assert_reason(exc_info, reason)


def test_required_slot_cannot_be_reclassified_optional_or_disabled() -> None:
    for forged in (ENABLED_OPTIONAL_EVENT_DEPENDENT, PROFILE_DISABLED):
        dispositions = list(_PROFILE.ordered_slot_dispositions)
        dispositions[10] = forged
        with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as exc_info:
            build_adaptive_ohlcv_feature_selection_profile_v1(
                FEATURE_SOURCE_REGISTRY_V4,
                _EXPECTED_ENABLED,
                tuple(dispositions),
            )
        _assert_reason(exc_info, "ADAPTIVE_OHLCV_PROFILE_V1_DISPOSITION_VECTOR_DRIFT")


def test_disabled_and_typed_negative_policy_escalation_fails_closed() -> None:
    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as disabled_exc:
        replace(_PROFILE.disabled_encoding_contract, typed_negative_encoding_reused=True)
    _assert_reason(
        disabled_exc,
        "ADAPTIVE_OHLCV_PROFILE_V1_DISABLED_ENCODING_FALSE_CLAIM_REQUIRED",
    )

    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as typed_exc:
        replace(_PROFILE.typed_negative_policy, may_enable_profile_disabled_slot=True)
    _assert_reason(typed_exc, "ADAPTIVE_OHLCV_PROFILE_V1_TYPED_NEGATIVE_ESCALATION_FORBIDDEN")


def test_prospective_cutoff_rule_accepts_only_causal_order() -> None:
    validate_adaptive_ohlcv_profile_prospective_cutoff_v1(
        _PROFILE,
        **_valid_cutoff_arguments(),
    )
    assert _PROFILE.selection_cutoff_rule.activation_timestamp_embedded is False
    assert _PROFILE.selection_cutoff_rule.clock_format == "UTC_MICROSECOND_Z"


def _future_feature_availability() -> tuple[tuple[str, str], ...]:
    values = list(_valid_cutoff_arguments()["enabled_feature_available_at"])
    values[-1] = (values[-1][0], "2026-07-21T01:00:00.000001Z")
    return tuple(values)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        (
            {
                "selection_observation_clocks": (
                    (
                        "future-event",
                        "2026-07-21T00:02:00.000001Z",
                        "2026-07-21T00:02:00.000001Z",
                    ),
                )
            },
            "ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_EVENT_AFTER_DATA_CUTOFF",
        ),
        (
            {
                "selection_observation_clocks": (
                    (
                        "late-availability",
                        "2026-07-21T00:01:00.000000Z",
                        "2026-07-21T00:02:00.000001Z",
                    ),
                )
            },
            "ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_AVAILABLE_AFTER_DATA_CUTOFF",
        ),
        (
            {"profile_published_available_at": "2026-07-21T00:02:00.000000Z"},
            "ADAPTIVE_OHLCV_PROFILE_V1_SELECTION_CUTOFF_NOT_BEFORE_PUBLICATION",
        ),
        (
            {"profile_published_available_at": "2026-07-21T01:00:00.000001Z"},
            "ADAPTIVE_OHLCV_PROFILE_V1_PROFILE_PUBLISHED_AFTER_SAMPLE_DECISION",
        ),
        (
            {"enabled_feature_available_at": _future_feature_availability()},
            "ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABLE_AFTER_SAMPLE_DECISION",
        ),
        (
            {"final_feature_cutoff": "2026-07-21T01:00:00.000000Z"},
            "ADAPTIVE_OHLCV_PROFILE_V1_FINAL_FEATURE_CUTOFF_NOT_BEFORE_DECISION",
        ),
        (
            {"masa_feature_cutoff": "2026-07-21T00:55:00.000001Z"},
            "ADAPTIVE_OHLCV_PROFILE_V1_MASA_CUTOFF_AFTER_PPO_CUTOFF",
        ),
        (
            {"ppo_feature_cutoff": "2026-07-21T01:00:00.000000Z"},
            "ADAPTIVE_OHLCV_PROFILE_V1_PPO_CUTOFF_NOT_BEFORE_PPO_DECISION",
        ),
    ),
)
def test_prospective_cutoff_adversarial_boundaries_fail_closed(
    overrides: dict[str, object],
    reason: str,
) -> None:
    arguments = _valid_cutoff_arguments()
    arguments.update(overrides)

    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as exc_info:
        validate_adaptive_ohlcv_profile_prospective_cutoff_v1(_PROFILE, **arguments)
    _assert_reason(exc_info, reason)


def test_feature_availability_order_and_clock_encoding_are_exact() -> None:
    arguments = _valid_cutoff_arguments()
    availability = list(arguments["enabled_feature_available_at"])
    availability[0], availability[1] = availability[1], availability[0]
    arguments["enabled_feature_available_at"] = tuple(availability)
    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as order_exc:
        validate_adaptive_ohlcv_profile_prospective_cutoff_v1(_PROFILE, **arguments)
    _assert_reason(order_exc, "ADAPTIVE_OHLCV_PROFILE_V1_FEATURE_AVAILABILITY_ORDER_DRIFT")

    arguments = _valid_cutoff_arguments()
    arguments["sample_decision_time"] = "2026-07-21T01:00:00Z"
    with pytest.raises(AdaptiveOhlcvFeatureSelectionProfileV1ValidationError) as clock_exc:
        validate_adaptive_ohlcv_profile_prospective_cutoff_v1(_PROFILE, **arguments)
    _assert_reason(clock_exc, "ADAPTIVE_OHLCV_PROFILE_V1_SAMPLE_DECISION_TIME_INVALID")


def test_profile_is_non_consumable_and_conveys_no_authority() -> None:
    assert _PROFILE.audit_only is True
    assert "UNAUTHENTICATED_UNWIRED" in _PROFILE.classification
    assert "NON_CONSUMABLE" in _PROFILE.downstream_status
    assert all(
        value is False
        for value in (
            _PROFILE.transforms_implemented,
            _PROFILE.per_sample_receipts_bound,
            _PROFILE.feature_snapshot_published,
            _PROFILE.consumer_eligible,
            _PROFILE.trainer_admission_authorized,
            _PROFILE.prediction_authorized,
            _PROFILE.paper_trading_authorized,
            _PROFILE.live_execution_authorized,
            _PROFILE.runtime_wired,
        )
    )
    contract = adaptive_ohlcv_feature_selection_profile_v1_contract(_PROFILE)
    assert all(
        value is False for name, value in contract["authorization"].items() if name != "audit_only"
    )
    assert not {
        "event_time",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
        "decision_time",
        "execution_time",
        "effective_from",
        "profile_published_available_at",
    } & set(contract)
