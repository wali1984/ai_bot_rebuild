from __future__ import annotations

from dataclasses import replace

import pytest
from v2.backend.app.services.liquidation_surface.trainer_admission import (
    build_trainer_decision_context,
    evaluate_liquidation_surface_trainer_admission,
)
from v2.backend.app.services.liquidation_surface.trainer_projection import (
    PROJECTION_ABI_SHA256,
    PROJECTION_FEATURE_NAMES,
    PROJECTION_SOURCE_LABEL,
    LiquidationSurfaceTrainerProjectionError,
    build_liquidation_surface_trainer_projection,
)
from v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3 import (
    FEATURE_SPEC,
)
from v2.backend.tests.unit.services.liquidation_surface.test_trainer_admission import (
    AS_OF_MS,
    _admit,
    _decision,
    _mark_evidence,
    _prepared,
    _publish,
    _security,
)


def _projection(*, prepared=None):
    candidate = _prepared() if prepared is None else prepared
    _client, publication = _publish(candidate)
    decision = _decision(publication, abi=PROJECTION_ABI_SHA256)
    admission = _admit(publication, candidate, decision=decision)
    projected = build_liquidation_surface_trainer_projection(
        admission,
        decision_id=decision.decision_id,
        decision_time_ms=decision.decision_time_ms,
        symbol=decision.symbol,
        timeframe=decision.timeframe,
        feature_abi_sha256=decision.feature_abi_sha256,
    )
    return admission, projected


def test_projection_uses_existing_trainer_slot_names_but_truthful_new_source() -> None:
    _admission, projected = _projection()
    native_names = {name for name, _source in FEATURE_SPEC}

    assert len(PROJECTION_FEATURE_NAMES) == 12
    assert set(PROJECTION_FEATURE_NAMES).issubset(native_names)
    assert projected.ordered_feature_names == PROJECTION_FEATURE_NAMES
    assert set(projected.ordered_source_labels) == {PROJECTION_SOURCE_LABEL}
    assert PROJECTION_SOURCE_LABEL != "v2:market:liquidation_levels"


def test_authorized_surface_projects_direct_values_and_masks_unknown_cascade() -> None:
    admission, projected = _projection()
    payload = admission.surface_payload
    assert payload is not None
    values = projected.feature_mapping()
    nearest_long = payload["nearest_long_level"]
    nearest_short = payload["nearest_short_level"]

    assert projected.trainer_authority is True
    assert values["liquidation_long_level"] == nearest_long["price"]
    assert values["nearest_liquidation_level_below"] == nearest_long["price"]
    assert values["liquidation_short_level"] == nearest_short["price"]
    assert values["nearest_liquidation_level_above"] == nearest_short["price"]
    assert values["distance_to_long_liq_bps"] == nearest_long["distance_bps"]
    assert values["distance_to_short_liq_bps"] == nearest_short["distance_bps"]
    assert values["liquidation_cascade_risk"] is None
    assert values["liquidation_pressure_direction"] is None
    for feature_name in (
        "liquidation_cascade_risk",
        "liquidation_pressure_direction",
    ):
        ordinal = PROJECTION_FEATURE_NAMES.index(feature_name)
        assert projected.missing_mask[ordinal] is True
        assert projected.source_availability[ordinal] is False
    assert sum(projected.missing_mask) == 2
    assert sum(projected.source_availability) == 10
    assert projected.prediction_authority is False
    assert projected.paper_trading_authority is False
    assert projected.live_execution_authority is False


def test_side_normalized_clusters_do_not_fabricate_cross_side_pressure() -> None:
    admission, projected = _projection()
    assert admission.surface_payload is not None
    assert admission.surface_payload["nearest_long_level"]["normalized_strength"] > 0
    assert admission.surface_payload["nearest_short_level"]["normalized_strength"] > 0
    assert projected.feature_mapping()["liquidation_pressure_direction"] is None


def test_degraded_source_becomes_explicit_all_slot_mask_without_values() -> None:
    degraded = _prepared(
        marks=_mark_evidence(event_times=(AS_OF_MS - 20_000, AS_OF_MS - 19_000))
    )
    admission, projected = _projection(prepared=degraded)

    assert admission.trainer_authority is False
    assert projected.trainer_authority is False
    assert all(value is None for value in projected.ordered_feature_values)
    assert all(projected.missing_mask)
    assert all(projected.stale_mask)
    assert not any(projected.source_availability)
    assert projected.rejection_reasons


def test_late_publication_preserves_actual_clock_in_non_authoritative_mask() -> None:
    candidate = _prepared()
    _client, publication = _publish(candidate)
    decision = build_trainer_decision_context(
        decision_id="decision-before-publication",
        decision_time_ms=publication.consumer_reopened_at_ms - 1,
        symbol="BTCUSDT",
        timeframe="5m",
        feature_abi_sha256=PROJECTION_ABI_SHA256,
    )
    admission = evaluate_liquidation_surface_trainer_admission(
        publication,
        candidate,
        decision_context=decision,
        admission_security_context=_security(),
        now_ms_fn=lambda: publication.consumer_reopened_at_ms + 1,
    )
    projected = build_liquidation_surface_trainer_projection(
        admission,
        decision_id=decision.decision_id,
        decision_time_ms=decision.decision_time_ms,
        symbol=decision.symbol,
        timeframe=decision.timeframe,
        feature_abi_sha256=decision.feature_abi_sha256,
    )

    assert projected.trainer_authority is False
    assert projected.projection_available_at_ms > projected.decision_time_ms
    assert all(projected.missing_mask)
    assert "PUBLICATION_AVAILABLE_AFTER_DECISION_TIME" in projected.rejection_reasons


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_id", "wrong-decision"),
        ("decision_time_ms", 1),
        ("symbol", "ETHUSDT"),
        ("timeframe", "15m"),
        ("feature_abi_sha256", "0" * 64),
    ],
)
def test_projection_rejects_every_consumer_identity_mismatch(
    field: str,
    value: object,
) -> None:
    candidate = _prepared()
    _client, publication = _publish(candidate)
    decision = _decision(publication, abi=PROJECTION_ABI_SHA256)
    admission = _admit(publication, candidate, decision=decision)
    arguments: dict[str, object] = {
        "decision_id": decision.decision_id,
        "decision_time_ms": decision.decision_time_ms,
        "symbol": decision.symbol,
        "timeframe": decision.timeframe,
        "feature_abi_sha256": decision.feature_abi_sha256,
    }
    arguments[field] = value

    with pytest.raises(
        LiquidationSurfaceTrainerProjectionError,
        match="LIQUIDATION_TRAINER_PROJECTION_DECISION_IDENTITY_MISMATCH",
    ):
        build_liquidation_surface_trainer_projection(admission, **arguments)  # type: ignore[arg-type]


def test_projection_hash_and_decision_authorization_are_non_reusable() -> None:
    _admission, projected = _projection()

    assert projected.feature_cutoff_ms <= projected.projection_available_at_ms
    assert projected.projection_available_at_ms <= projected.decision_time_ms
    assert projected.is_authorized_for(
        decision_id=projected.decision_id,
        decision_time_ms=projected.decision_time_ms,
        symbol=projected.symbol,
        timeframe=projected.timeframe,
        feature_abi_sha256=projected.consumer_feature_abi_sha256,
    )
    assert not projected.is_authorized_for(
        decision_id=f"{projected.decision_id}-other",
        decision_time_ms=projected.decision_time_ms,
        symbol=projected.symbol,
        timeframe=projected.timeframe,
        feature_abi_sha256=projected.consumer_feature_abi_sha256,
    )
    with pytest.raises(
        LiquidationSurfaceTrainerProjectionError,
        match="LIQUIDATION_TRAINER_PROJECTION_FACTORY_OR_INTEGRITY_INVALID",
    ):
        replace(projected, trainer_authority_reason="FORGED")
    with pytest.raises(TypeError):
        projected.feature_mapping()["liquidation_long_level"] = 1.0  # type: ignore[index]
