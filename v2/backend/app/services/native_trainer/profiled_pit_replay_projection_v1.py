"""PIT-safe projection of authenticated profiled samples into replay records.

The source sample is admitted by ``profiled_training_ledger_loader_v1`` and
its forward outcome comes only from the canonical 5m label binding.  This
module never reads a current market value, writes a model, or grants serving
authority.  It produces a deterministic durable-snapshot-archive record that
the challenger can consume after the importer commits it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    build_archive_record,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    PHYSICAL_MODEL_FEATURE_COUNT,
    PHYSICAL_ORDERED_FEATURE_NAMES,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT,
    ProfiledTrainingLedgerSampleV1,
)

PROFILED_PIT_REPLAY_PROJECTION_V1_SCHEMA_VERSION: Final = (
    "profiled_pit_replay_projection_v1"
)
PROFILED_PIT_REPLAY_PROJECTION_V1_SOURCE: Final = (
    "PROFILED_TRAINING_LEDGER_LOADER_V1_PLUS_CANONICAL_5M_LABEL_BINDING"
)

_SHA256_LENGTH: Final = 64


class ProfiledPitReplayProjectionV1Error(ValueError):
    """A purported replay projection failed its source/PIT contract."""


def _fail(reason: str) -> NoReturn:
    raise ProfiledPitReplayProjectionV1Error(reason) from None


def _sha256(value: object) -> str:
    if (
        type(value) is not str
        or len(cast(str, value)) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in cast(str, value))
    ):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_SHA256_INVALID")
    return cast(str, value)


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(cast(str, value).replace("Z", "+00:00"))
    except ValueError:
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    if normalized.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail(reason)
    return normalized


def _finite(value: object, *, reason: str, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _fail(reason)
    numeric = float(value)
    if not math.isfinite(numeric) or (nonnegative and numeric < 0.0):
        _fail(reason)
    return numeric


def _label_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_LABEL_BINDING_INVALID")
    label = cast(Mapping[str, Any], value)
    if label.get("schema_version") != "profiled_training_finalized_label_binding_v1":
        _fail("PROFILED_PIT_REPLAY_PROJECTION_LABEL_BINDING_INVALID")
    if label.get("future_labels_not_in_feature_tensor") is not True:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_LABEL_LEAKAGE_GUARD_INVALID")
    if label.get("auxiliary_cost_values_excluded_from_model_vector") is not True:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_COST_VECTOR_GUARD_INVALID")
    if label.get("static_action_threshold_used") is not False:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_STATIC_THRESHOLD_FORBIDDEN")
    _sha256(label.get("label_binding_sha256"))
    _sha256(label.get("directional_cost_evidence_sha256"))
    _sha256(label.get("label_path_sha256"))
    _sha256(label.get("label_range_sha256"))
    return label


def project_profiled_training_sample_to_replay_snapshot_v1(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    label_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one deterministic challenger replay snapshot.

    ``sample`` must already be fully admitted by the bounded profiled ledger
    loader.  The forward-looking label is deliberately stored outside
    ``features`` and becomes usable only after its canonical availability
    timestamp.
    """

    if type(sample) is not ProfiledTrainingLedgerSampleV1:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_SAMPLE_EXACT_TYPE_REQUIRED")
    label = _label_mapping(label_binding)
    if len(sample.physical_feature_values) != PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_PHYSICAL_VECTOR_LENGTH_INVALID")
    if len(PHYSICAL_ORDERED_FEATURE_NAMES) != PHYSICAL_MODEL_FEATURE_COUNT:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_PHYSICAL_SCHEMA_INVALID")
    feature_cutoff = _clock(
        sample.feature_cutoff,
        reason="PROFILED_PIT_REPLAY_PROJECTION_FEATURE_CUTOFF_INVALID",
    )
    generated_at = _clock(
        sample.generated_at,
        reason="PROFILED_PIT_REPLAY_PROJECTION_GENERATED_AT_INVALID",
    )
    decision_time = _clock(
        sample.decision_time,
        reason="PROFILED_PIT_REPLAY_PROJECTION_DECISION_TIME_INVALID",
    )
    cost_available_at = _clock(
        sample.cost_evidence_available_at,
        reason="PROFILED_PIT_REPLAY_PROJECTION_COST_AVAILABLE_AT_INVALID",
    )
    reference_available_at = _clock(
        sample.decision_reference_price_available_at,
        reason="PROFILED_PIT_REPLAY_PROJECTION_REFERENCE_AVAILABLE_AT_INVALID",
    )
    label_available_at = _clock(
        label.get("label_available_at"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_LABEL_AVAILABLE_AT_INVALID",
    )
    if not (
        feature_cutoff <= generated_at <= decision_time < label_available_at
        and cost_available_at <= generated_at
        and reference_available_at <= decision_time
    ):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_CLOCK_ORDER_INVALID")
    if label.get("decision_time") != sample.decision_time:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_LABEL_DECISION_BINDING_INVALID")
    if type(sample.sequence) is not int or sample.sequence <= 0:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_SEQUENCE_INVALID")
    if sample.trainer_admission_authorized is not True or any(
        value is not False
        for value in (
            sample.prediction_authorized,
            sample.paper_trading_authorized,
            sample.live_execution_authorized,
            sample.runtime_wired,
        )
    ):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_SAMPLE_AUTHORITY_INVALID")
    if not sample.symbol or not sample.timeframe:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_SYMBOL_OR_TIMEFRAME_INVALID")

    features = {
        name: _finite(value, reason="PROFILED_PIT_REPLAY_PROJECTION_FEATURE_INVALID")
        for name, value in zip(
            PHYSICAL_ORDERED_FEATURE_NAMES,
            sample.physical_feature_values[:PHYSICAL_MODEL_FEATURE_COUNT],
            strict=True,
        )
    }
    if any(name.startswith("future_") for name in features):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_FUTURE_FEATURE_FORBIDDEN")
    directional_cost = label.get("directional_cost_evidence")
    if not isinstance(directional_cost, Mapping):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_DIRECTIONAL_COST_INVALID")
    fee_bps_per_side = _finite(
        directional_cost.get("fee_bps_per_side"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_FEE_INVALID",
        nonnegative=True,
    )
    full_spread_bps = _finite(
        directional_cost.get("full_spread_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_SPREAD_INVALID",
        nonnegative=True,
    )
    slippage_bps_per_side = _finite(
        directional_cost.get("expected_slippage_bps_per_side"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_SLIPPAGE_INVALID",
        nonnegative=True,
    )
    funding_bps = _finite(
        directional_cost.get("signed_expected_funding_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_FUNDING_INVALID",
    )
    base_cost = 2.0 * fee_bps_per_side + full_spread_bps + 2.0 * slippage_bps_per_side
    long_cost = _finite(
        directional_cost.get("long_round_trip_cost_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_LONG_COST_INVALID",
        nonnegative=True,
    )
    short_cost = _finite(
        directional_cost.get("short_round_trip_cost_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_SHORT_COST_INVALID",
        nonnegative=True,
    )
    raw_return = _finite(
        directional_cost.get("raw_return_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_RAW_RETURN_INVALID",
    )
    long_net = _finite(
        directional_cost.get("long_net_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_LONG_NET_INVALID",
    )
    short_net = _finite(
        directional_cost.get("short_net_bps"),
        reason="PROFILED_PIT_REPLAY_PROJECTION_SHORT_NET_INVALID",
    )
    tolerance = 1e-8
    if not (
        math.isclose(long_cost, base_cost + funding_bps, rel_tol=0.0, abs_tol=tolerance)
        and math.isclose(short_cost, base_cost - funding_bps, rel_tol=0.0, abs_tol=tolerance)
        and math.isclose(long_net, raw_return - long_cost, rel_tol=0.0, abs_tol=tolerance)
        and math.isclose(short_net, -raw_return - short_cost, rel_tol=0.0, abs_tol=tolerance)
    ):
        _fail("PROFILED_PIT_REPLAY_PROJECTION_DIRECTIONAL_COST_ECONOMICS_INVALID")
    if label.get("label_target_action") not in {"hold", "long", "short"}:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_LABEL_ACTION_INVALID")
    label_horizon = label.get("label_horizon_seconds")
    if type(label_horizon) is not int or label_horizon <= 0:
        _fail("PROFILED_PIT_REPLAY_PROJECTION_LABEL_HORIZON_INVALID")

    source_hashes = {
        "profiled_child_record_sha256": _sha256(sample.record_sha256),
        "profiled_parent_record_sha256": _sha256(sample.parent_record_sha256),
        "profiled_parent_lineage_binding_sha256": _sha256(sample.parent_lineage_binding_sha256),
        "cost_capture_binding_sha256": _sha256(sample.cost_capture_binding_sha256),
        "cost_capture_artifact_sha256": _sha256(sample.cost_capture_artifact_sha256),
        "cost_capture_receipt_sha256": _sha256(sample.cost_capture_receipt_sha256),
        "cost_cas_object_inventory_sha256": _sha256(sample.cost_cas_object_inventory_sha256),
        "canonical_label_binding_sha256": _sha256(label.get("label_binding_sha256")),
        "canonical_label_path_sha256": _sha256(label.get("label_path_sha256")),
        "canonical_label_range_sha256": _sha256(label.get("label_range_sha256")),
        "directional_cost_evidence_sha256": _sha256(
            label.get("directional_cost_evidence_sha256")
        ),
    }
    snapshot_id = "profiled_pit_replay_v1_" + stable_sha256(
        {
            "profiled_child_record_sha256": sample.record_sha256,
            "label_binding_sha256": label["label_binding_sha256"],
        }
    )
    return build_archive_record(
        snapshot_id=snapshot_id,
        symbol=sample.symbol,
        timeframe=sample.timeframe,
        feature_cutoff=sample.feature_cutoff,
        decision_time=sample.decision_time,
        # This is the verified pre-decision feature materialization clock, not
        # the later ledger post-commit readback used to admit the training row.
        available_at=sample.generated_at,
        mtf_snapshot_id=sample.parent_durable_snapshot_id,
        features=features,
        missing_mask={name: False for name in features},
        stale_mask={name: False for name in features},
        source_availability={name: True for name in features},
        source_hashes=source_hashes,
        created_at=sample.postcommit_readback_at,
        extra={
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": True,
            "source": PROFILED_PIT_REPLAY_PROJECTION_V1_SOURCE,
            "pit_replay_projection": {
                "schema_version": PROFILED_PIT_REPLAY_PROJECTION_V1_SCHEMA_VERSION,
                "source_loader": "profiled_training_ledger_loader_v1",
                "ledger_sequence": sample.sequence,
                "profiled_durable_snapshot_id": sample.durable_snapshot_id,
                "profiled_feature_snapshot_id": sample.feature_snapshot_id,
                "parent_durable_snapshot_id": sample.parent_durable_snapshot_id,
                "mtf_snapshot_id_semantics": (
                    "AUTHENTICATED_PROFILED_PARENT_DURABLE_SNAPSHOT_ID"
                ),
                "trainer_admission_authorized": True,
                "prediction_authorized": False,
                "paper_trading_authorized": False,
                "live_execution_authorized": False,
                "runtime_wired": False,
                "label_binding": dict(label),
                "action_specific_cost_evidence": {
                    "fee_bps_per_side": fee_bps_per_side,
                    "full_spread_bps": full_spread_bps,
                    "expected_slippage_bps_per_side": slippage_bps_per_side,
                    "signed_expected_funding_bps": funding_bps,
                    "long_round_trip_cost_bps": long_cost,
                    "short_round_trip_cost_bps": short_cost,
                    "raw_future_return_bps": raw_return,
                    "long_net_bps": long_net,
                    "short_net_bps": short_net,
                    "label_available_at": label["label_available_at"],
                    "label_horizon_seconds": label_horizon,
                },
            },
        },
    )


__all__ = [
    "PROFILED_PIT_REPLAY_PROJECTION_V1_SCHEMA_VERSION",
    "PROFILED_PIT_REPLAY_PROJECTION_V1_SOURCE",
    "ProfiledPitReplayProjectionV1Error",
    "project_profiled_training_sample_to_replay_snapshot_v1",
]
