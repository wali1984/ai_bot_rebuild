from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.services.native_trainer.feature_resolution_plan_v4 import (
    EMPTY_COLLECTION_POLICY,
    FEATURE_RESOLUTION_PLAN_V4,
    FEATURE_RESOLUTION_PLAN_V4_SHA256,
    FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT,
    PLAN_RESOLVABLE,
    PLAN_UNRESOLVED_AUTHENTICATED_WINDOW,
    PLAN_UNRESOLVED_FUTURE_SEMANTICS,
    PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN,
    PLAN_UNRESOLVED_NO_PRODUCER,
    PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION,
    FeatureResolutionPlanV4ValidationError,
    FeatureSlotResolutionPlanV4,
    feature_resolution_plan_v4_contract,
    materialize_feature_source_key_v4,
    materialize_feature_source_timeframe_v4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)


def test_plan_covers_pinned_446_slot_registry_once_in_exact_order() -> None:
    plan = FEATURE_RESOLUTION_PLAN_V4
    assert len(plan.slots) == FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT == 446
    assert plan.plan_sha256 == FEATURE_RESOLUTION_PLAN_V4_SHA256
    assert plan.feature_source_registry_sha256 == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert tuple(slot.ordinal for slot in plan.slots) == tuple(range(446))
    assert len({slot.feature_name for slot in plan.slots}) == 446
    assert len({slot.configured_source_label for slot in plan.slots}) == 40
    status_counts: dict[str, int] = {}
    for slot in plan.slots:
        status_counts[slot.plan_status] = status_counts.get(slot.plan_status, 0) + 1
    assert status_counts == {
        PLAN_RESOLVABLE: 356,
        PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN: 57,
        PLAN_UNRESOLVED_FUTURE_SEMANTICS: 17,
        PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION: 8,
        PLAN_UNRESOLVED_AUTHENTICATED_WINDOW: 6,
        PLAN_UNRESOLVED_NO_PRODUCER: 2,
    }
    moralis = [slot for slot in plan.slots if slot.configured_source_label == "v2:features:moralis"]
    assert [slot.ordinal for slot in moralis] == list(range(259, 266))
    assert all(slot.requirement_class == "OPTIONAL_EVENT_DEPENDENT" for slot in moralis)
    assert [
        (
            slot.ordinal,
            slot.feature_name,
            slot.configured_source_label,
            slot.requirement_class,
        )
        for slot in plan.slots
    ] == [
        (
            slot.ordinal,
            slot.feature_name,
            slot.configured_source_label,
            slot.requirement_class,
        )
        for slot in FEATURE_SOURCE_REGISTRY_V4.slots
    ]


def test_every_branch_is_exact_and_no_generic_or_provider_fallback_exists() -> None:
    for slot in FEATURE_RESOLUTION_PLAN_V4.slots:
        assert slot.source_key_template is not None
        assert "*" not in slot.source_key_template
        assert "provider_feature_bridge" not in slot.source_key_template
        assert slot.empty_collection_policy == EMPTY_COLLECTION_POLICY
        for branch in slot.branches:
            assert branch.dependency_paths
            assert all(path for path in branch.dependency_paths)
            assert all("*" not in part for path in branch.dependency_paths for part in path)
            assert "provider_feature_bridge" not in branch.selected_alias

    # ret_pct is one of the 252 names previously populated only by the final
    # source-agnostic feature-name lookup.  The shadow plan preserves its ABI
    # slot but gives it no selector.
    ret_pct = next(
        slot for slot in FEATURE_RESOLUTION_PLAN_V4.slots if slot.feature_name == "ret_pct"
    )
    assert ret_pct.plan_status == PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN
    assert ret_pct.branches == ()


def test_future_liquidation_semantics_and_unproduced_slots_have_no_branch() -> None:
    future_ordinals = {*range(68, 78), *range(136, 142), 165}
    assert len(future_ordinals) == 17
    for ordinal in future_ordinals:
        slot = FEATURE_RESOLUTION_PLAN_V4.slots[ordinal]
        assert slot.plan_status == PLAN_UNRESOLVED_FUTURE_SEMANTICS
        assert slot.branches == ()

    for ordinal, name in ((131, "orderbook_wall_strength"), (133, "coinapi_wsds_tape_imbalance")):
        slot = FEATURE_RESOLUTION_PLAN_V4.slots[ordinal]
        assert slot.feature_name == name
        assert slot.plan_status == PLAN_UNRESOLVED_NO_PRODUCER
        assert slot.branches == ()

    collision_ordinals = {80, 81, 82, 106, 107, 108, 109, 110}
    for ordinal in collision_ordinals:
        slot = FEATURE_RESOLUTION_PLAN_V4.slots[ordinal]
        assert slot.configured_source_label == "v2:market:liquidity_zones"
        assert slot.plan_status == PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION
        assert slot.source_timeframe_template == "REQUEST_TIMEFRAME"
        assert slot.branches == ()


def test_feature_specific_maps_remain_source_scoped_and_exact() -> None:
    by_name = {slot.feature_name: slot for slot in FEATURE_RESOLUTION_PLAN_V4.slots}

    ta = by_name["MACD_signal"]
    assert ta.plan_status == PLAN_RESOLVABLE
    assert ta.configured_source_label == "v2:features:ta"
    assert [branch.dependency_paths for branch in ta.branches] == [
        (("indicators", "MACD_signal"),),
        (("indicators", "macd_signal"),),
        (("indicators", "ta_MACD_12_26_9_signal"),),
        (("indicators", "ta_MACD_macdsignal"),),
    ]

    ta_full = by_name["taf_ta_ht_trendmode_integer"]
    assert ta_full.configured_source_label == "v2:features:ta_full"
    assert ta_full.branches[0].dependency_paths == (("indicators", "ta_HT_TRENDMODE_integer"),)

    moralis = by_name["moralis_exchange_inflow_usd"]
    assert moralis.configured_source_label == "v2:features:moralis"
    assert moralis.branches[0].dependency_paths == (("features", "moralis_exchange_inflow_usd"),)


def test_key_materialization_is_exact_and_plan_is_non_authoritative_immutable() -> None:
    ohlcv = FEATURE_RESOLUTION_PLAN_V4.slots[10]
    assert (
        materialize_feature_source_key_v4(
            ohlcv,
            symbol="BTCUSDT",
            timeframe="5m",
        )
        == "v2:market:ohlcv_closed:binance:BTCUSDT:5m"
    )
    oi_history = next(
        slot
        for slot in FEATURE_RESOLUTION_PLAN_V4.slots
        if slot.configured_source_label == "v2:market:open_interest_hist"
    )
    htf_1h = next(
        slot
        for slot in FEATURE_RESOLUTION_PLAN_V4.slots
        if slot.configured_source_label == "v2:features:ta_full:1h"
    )
    assert (
        materialize_feature_source_timeframe_v4(
            oi_history,
            request_timeframe="4h",
        )
        == "5m"
    )
    assert (
        materialize_feature_source_timeframe_v4(
            htf_1h,
            request_timeframe="4h",
        )
        == "1h"
    )
    assert (
        materialize_feature_source_timeframe_v4(
            ohlcv,
            request_timeframe="4h",
        )
        == "4h"
    )

    contract = feature_resolution_plan_v4_contract(FEATURE_RESOLUTION_PLAN_V4)
    assert contract["plan_sha256"] == FEATURE_RESOLUTION_PLAN_V4_SHA256
    assert contract["authorization"] == {
        "audit_only": True,
        "runtime_wired": False,
        "source_reads_performed": False,
        "tensor_eligible": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    with pytest.raises(FrozenInstanceError):
        FEATURE_RESOLUTION_PLAN_V4.slots[0].feature_name = "forged"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        object.__setattr__(
            FEATURE_RESOLUTION_PLAN_V4,
            "trainer_admission_authorized",
            True,
        )
    assert FEATURE_RESOLUTION_PLAN_V4.trainer_admission_authorized is False


def test_plan_types_cannot_be_constructed_as_authority_by_callers() -> None:
    slot = FEATURE_RESOLUTION_PLAN_V4.slots[0]
    with pytest.raises(
        FeatureResolutionPlanV4ValidationError,
        match="FEATURE_RESOLUTION_PLAN_V4_FACTORY_CONSTRUCTION_REQUIRED",
    ):
        FeatureSlotResolutionPlanV4(
            ordinal=slot.ordinal,
            feature_name=slot.feature_name,
            configured_source_label=slot.configured_source_label,
            requirement_class=slot.requirement_class,
            source_key_template=slot.source_key_template,
            source_timeframe_template=slot.source_timeframe_template,
            source_payload_schema_version=slot.source_payload_schema_version,
            plan_status=slot.plan_status,
            unresolved_reason=slot.unresolved_reason,
            branches=slot.branches,
            requires_closed_candle=slot.requires_closed_candle,
            null_policy=slot.null_policy,
            empty_collection_policy=slot.empty_collection_policy,
            typed_negative_policy=slot.typed_negative_policy,
            _construction_token=object(),
        )


def test_object_setattr_branch_tamper_breaks_pinned_plan_before_materialization() -> None:
    slot = next(item for item in FEATURE_RESOLUTION_PLAN_V4.slots if item.branches)
    branch = slot.branches[0]
    original_alias = branch.selected_alias
    try:
        object.__setattr__(branch, "selected_alias", "forged_alias")
        with pytest.raises(
            FeatureResolutionPlanV4ValidationError,
            match="FEATURE_RESOLUTION_PLAN_V4_SHA256_INVALID",
        ):
            materialize_feature_source_key_v4(
                slot,
                symbol="BTCUSDT",
                timeframe="5m",
            )
    finally:
        object.__setattr__(branch, "selected_alias", original_alias)
