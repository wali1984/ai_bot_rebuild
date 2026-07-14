"""V2-owned data loader for the hybrid trainer."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    build_multi_timeframe_decision_snapshot,
    canonical_from_binance_rest,
    now_ms,
    parse_ms,
)
from v2.backend.app.services.market_state_integrity.scoring import OPTIONAL_OR_EVENT_FEATURE_TOKENS
from v2.backend.app.services.market_state_integrity.sample_rejection import classify_training_sample
from v2.backend.app.services.market_state_integrity.trust import (
    ENFORCEMENT_EPOCH,
    TRUST_PRODUCER_VERSION,
    TRUST_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    REQUIRED_FEEDBACK_FIELDS,
    REQUIRED_TRUST_ENVELOPE_FIELDS,
    audit_quality_rejection_reasons,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    default_archive_root,
    iter_manifest_records_from_offset,
    iter_snapshots,
    iter_snapshots_from_offset,
    load_snapshot as load_durable_feature_snapshot,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    build_trusted_replay_row,
    snapshot_to_final_candle,
)

from .safety import V2OnlyJsonIO, assert_v2_key
from .tensor_builder import FeatureTensorRecord, V2UnifiedFeatureTensorBuilder

INVALID_PAPER_ADMISSION_REJECTION_REASON = (
    "P0_ENTRY_GATE_BLOCKED_NOT_EXPLORATION_RELAXABLE"
)
TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE = 16_384
TRUSTED_REPLAY_MIN_SCAN_PER_CYCLE = 512
TRUSTED_REPLAY_SCAN_MULTIPLIER = 4
# Outcome labels need finalized candles up to 4h after decision_time; the
# embargo keeps the replay cursor behind that horizon (plus finalization
# slack) so every consumed snapshot is labelable (F-0013).
TRUSTED_REPLAY_LABEL_EMBARGO_SECONDS = int(4.5 * 3600)
# Replay-lane mask policy: archived snapshots predate later schema additions
# (cost fields, santiment/cross-asset/regime families, orderbook features).
# For TRAINING the tensor carries an explicit missing_mask the model
# conditions on — absence is information, not corruption — and the label is
# PIT-protected by the replay builder independently of missing inputs.
# MISSING_MASKED replay rows are therefore accepted (and counted), while
# STALE_MASKED rows (wrong values, not absent ones) remain rejected. The
# global integrity optional-token list is intentionally NOT changed — live
# decision rows still require current-schema evidence.
# First-run cursor placement: closed-candle series from Redis cover ~25h at
# 15m granularity, so labeling starts inside that window.
TRUSTED_REPLAY_INITIAL_LOOKBACK_SECONDS = int(25 * 3600)
TRAINER_FEEDBACK_OUTCOMES_KEY = "v2:trainer:feedback:outcomes"
TRAINER_FEEDBACK_COUNTERFACTUALS_KEY = "v2:trainer:feedback:counterfactuals"
TRAINER_FEEDBACK_PAPER_EXPLORATION_MATERIALIZATION_KEY = (
    "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
)

# ── Closed-trade example memo cache ─────────────────────────────────────────
# The resident runtime rebuilds a fresh loader instance every cycle, and the
# fresh-training lane rebuilt ALL closed-trade feedback examples each cycle --
# ~12k counterfactual rows, each costing one Redis feature-snapshot GET plus a
# tensor build. That synchronous rebuild (data_loader_time_ms ~48s) starved the
# GPU (it idled while CPU/IO prepped the same immutable historical rows over and
# over). Closed-trade feedback rows + their feature snapshots are append-mostly
# and immutable-by-id, so the row->example build is deterministic: memoize it by
# a content hash of the row across loader instances (module-level, lock-guarded).
# Warm cycles then rebuild only new/changed rows, collapsing the fresh load to
# well under a second. Successful examples only are cached; a row that yields no
# example (e.g. a snapshot not yet archived) is left uncached so a later-arriving
# snapshot is still picked up. Bounded LRU; kill-switch via env for safety.
_CLOSED_TRADE_EXAMPLE_CACHE: OrderedDict[str, Any] = OrderedDict()
_CLOSED_TRADE_EXAMPLE_CACHE_LOCK = threading.Lock()
_CLOSED_TRADE_EXAMPLE_CACHE_CAP = 65536
_CLOSED_TRADE_EXAMPLE_CACHE_STATS = {"hits": 0, "misses": 0}


def _closed_trade_example_cache_enabled() -> bool:
    return (os.getenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "1").strip().lower()
            not in {"0", "false", "no", "off"})


def _closed_trade_example_cache_key(row: Mapping[str, Any]) -> str:
    """Stable content hash so an identical row maps to an identical example."""
    try:
        blob = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        blob = repr(sorted((str(k), str(v)) for k, v in row.items()))
    return hashlib.sha1(blob.encode("utf-8"), usedforsecurity=False).hexdigest()
COUNTERFACTUAL_TRAINER_FEEDBACK_SOURCES = {
    "V2_CONTINUOUS_EDGE_FACTORY_COUNTERFACTUAL_CLOSED_WINDOW",
    "V2_CONTINUOUS_EDGE_FACTORY_REPLAY_CLOSED_WINDOW",
}
PAPER_EXPLORATION_MATERIALIZATION_TRAINER_FEEDBACK_SOURCES = {
    "PAPER_EXPLORATION_MATERIALIZATION_CLOSED_WINDOW",
    "PAPER_RISK_CONTROLLER_EXPLORATION_CLOSED_WINDOW",
}
PAPER_EXPLORATION_MATERIALIZATION_CLOSED_FEEDBACK_TYPES = {
    "PAPER_EXPLORATION_MATERIALIZATION_COUNTERFACTUAL_CLOSED",
    "PAPER_EXPLORATION_MATERIALIZATION_CLOSED_OUTCOME",
}


def _parse_iso_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class TrainingExample:
    symbol: str
    timeframe: str
    tensor: FeatureTensorRecord
    label_action_index: int
    label_expected_move_after_cost_bps: float
    payload_keys: tuple[str, ...]
    row_classification: str
    trust_row: dict[str, Any] | None = None


EXPLICIT_TRAINING_TRUST_FIELDS = (
    "feature_cutoff",
    "decision_cutoff",
    "available_at",
    "source_available_time",
    "candle_closed_confirmed",
    "closed_candle",
    "candle_open_time",
    "candle_close_time",
    "source_event_time",
    "source_event_time_est",
    "source_received_time_est",
    "decision_time",
    "decision_time_est",
    "backfilled",
    "is_backfilled",
    "latency_ms",
    "price_disagreement_bps",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "decision_id",
    "mtf_snapshot_id",
    "mtf_snapshot_valid",
    "multi_timeframe_decision_snapshot",
)


def _has_explicit_training_trust_evidence(row: Mapping[str, Any]) -> bool:
    return any(row.get(field) is not None for field in EXPLICIT_TRAINING_TRUST_FIELDS)


def _snapshot_decision_time_lineage(snapshot: Any) -> dict[str, Any] | None:
    """Canonical decision-time feature lineage recorded by the feature pipeline.

    The pipeline writes explicit ``missing_feature_flags``/``stale_feature_flags``
    at snapshot capture time. Tensor rebuild gaps (live-only payloads that cannot
    be reconstructed later) must not be conflated with data that was actually
    missing when the decision was made. Returns ``None`` when the snapshot does
    not carry explicit lineage, in which case tensor masks remain the only
    available lineage source.
    """
    if not isinstance(snapshot, Mapping):
        return None

    def _names(value: Any) -> list[str]:
        if isinstance(value, Mapping):
            return [str(name) for name in value.keys() if str(name).strip()]
        if isinstance(value, (list, tuple)):
            return [str(name) for name in value if str(name).strip()]
        return []

    def _flagged_mask_names(value: Any) -> list[str]:
        if not isinstance(value, Mapping):
            return []
        return [str(name) for name, flagged in value.items() if flagged and str(name).strip()]

    def _source_availability(value: Any) -> Any:
        for key in ("source_availability", "source_availability_vector", "source_inputs"):
            source = value.get(key)
            if isinstance(source, Mapping):
                return {str(name): item for name, item in source.items()}
            if isinstance(source, (list, tuple)):
                return list(source)
        return {}

    if "missing_feature_flags" in snapshot or "missing_feature_count" in snapshot:
        missing_names = _names(snapshot.get("missing_feature_flags"))
        stale_names = _names(snapshot.get("stale_feature_flags"))
        raw_count = snapshot.get("missing_feature_count")
        try:
            missing_count = int(raw_count) if raw_count is not None else len(missing_names)
        except (TypeError, ValueError):
            missing_count = len(missing_names)
    elif isinstance(snapshot.get("missing_mask"), Mapping) or isinstance(snapshot.get("stale_mask"), Mapping):
        # Durable archive blobs persist the same decision-time lineage as full
        # boolean mask maps (missing_mask/stale_mask); a name was missing at
        # decision time only when its flag is truthy.
        missing_names = _flagged_mask_names(snapshot.get("missing_mask"))
        stale_names = _flagged_mask_names(snapshot.get("stale_mask"))
        missing_count = len(missing_names)
    else:
        return None
    missing_count = max(missing_count, len(missing_names))
    # Guard against snapshots whose flags claim completeness while a whole
    # critical feature family is absent from the captured features dict.
    features = snapshot.get("features")
    features = features if isinstance(features, Mapping) else {}
    for family_name, representatives in _CRITICAL_FAMILY_REPRESENTATIVES.items():
        if features and not any(features.get(name) is not None for name in representatives):
            synthetic = f"critical_family_absent:{family_name}"
            if synthetic not in missing_names:
                missing_names = [*missing_names, synthetic]
                missing_count += 1
    return {
        "missing_feature_names": missing_names,
        "missing_feature_count": missing_count,
        "stale_feature_names": stale_names,
        "stale_feature_count": len(stale_names),
        "source_availability": _source_availability(snapshot),
        "lineage_source": "feature_snapshot_decision_time_flags",
    }


_CRITICAL_FAMILY_REPRESENTATIVES: dict[str, tuple[str, ...]] = {
    "ohlcv_core": ("open", "high", "low", "close", "ohlcv_close", "last_price"),
    "orderbook_depth": (
        "bid_depth_usd",
        "ask_depth_usd",
        "depth_imbalance",
        "bid_ask_spread_bps",
        "ob_best_bid",
        "ob_best_ask",
        "orderbook_spread_bps",
    ),
    "funding_open_interest": (
        "funding_rate",
        "open_interest",
        "oi_change_pct",
        "basis_pct",
        "mark_price",
    ),
}


def _reconcile_lineage_with_row(
    lineage: dict[str, Any] | None,
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Drop snapshot-missing names whose values the runtime captured elsewhere.

    The paper runtime records decision-time cost evidence (fee schedule,
    expected slippage, funding) directly on the feedback row even when the
    feature snapshot itself lacked those fields. A value that was verifiably
    available at decision time is not missing evidence.
    """
    if lineage is None or not isinstance(row, Mapping):
        return lineage
    missing = list(lineage.get("missing_feature_names") or [])
    if not missing:
        return lineage
    reconciled: list[str] = []
    still_missing: list[str] = []
    for name in missing:
        value = row.get(name)
        if isinstance(value, bool):
            value = None
        try:
            numeric = float(value) if value is not None else None
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None and numeric == numeric:
            reconciled.append(name)
        else:
            still_missing.append(name)
    if not reconciled:
        return lineage
    updated = dict(lineage)
    updated["missing_feature_names"] = still_missing
    updated["missing_feature_count"] = len(still_missing)
    updated["missing_reconciled_from_feedback_row"] = reconciled
    return updated


def _classification_from_lineage(
    *,
    tensor: "FeatureTensorRecord",
    lineage: Mapping[str, Any] | None,
) -> str:
    """Row classification from canonical decision-time lineage when available.

    Tensor masks are preserved on the tensor itself (the model consumes them);
    integrity classification must reflect what was missing at decision time,
    not what cannot be re-derived from an archived snapshot.
    """
    if tensor.data_coverage_percent < 20.0:
        return "INSUFFICIENT_V2_DATA_COVERAGE"
    if lineage is not None:
        if int(lineage.get("stale_feature_count") or 0) > 0:
            return "STALE_MASKED"
        if int(lineage.get("missing_feature_count") or 0) > 0:
            return "MISSING_MASKED"
        return "TRAINABLE"
    if tensor.stale_feature_names:
        return "STALE_MASKED"
    if tensor.missing_feature_names:
        return "MISSING_MASKED"
    return "TRAINABLE"


def _lineage_trust_fields(
    *,
    tensor: "FeatureTensorRecord",
    lineage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Integrity-facing lineage fields for a trust row.

    ``missing_feature_names`` reflects the decision-time snapshot record;
    tensor rebuild gaps are preserved under explicit ``tensor_*`` keys so the
    masks stay auditable without triggering MISSING_CRITICAL_FEATURE_FAMILY
    false positives.
    """
    if lineage is not None:
        source_availability = lineage.get("source_availability")
        source_availability_recorded = isinstance(source_availability, (Mapping, list, tuple))
        return {
            "missing_feature_names": list(lineage.get("missing_feature_names") or []),
            "missing_feature_count": int(lineage.get("missing_feature_count") or 0),
            "stale_feature_names": list(lineage.get("stale_feature_names") or []),
            "stale_feature_count": int(lineage.get("stale_feature_count") or 0),
            "source_availability": source_availability if source_availability_recorded else {},
            "source_availability_recorded": source_availability_recorded,
            "missing_reconciled_from_feedback_row": list(
                lineage.get("missing_reconciled_from_feedback_row") or []
            ),
            "missing_feature_lineage_source": "feature_snapshot_decision_time_flags",
            "tensor_unreconstructed_feature_names": list(tensor.missing_feature_names),
            "tensor_unreconstructed_feature_count": len(tensor.missing_feature_names),
            "tensor_stale_feature_names": list(tensor.stale_feature_names),
            "tensor_missing_mask_preserved": True,
            "tensor_stale_mask_preserved": True,
            "source_availability_preserved": True,
            "lineage_mask_present": True,
        }
    return {
        "missing_feature_names": list(tensor.missing_feature_names),
        "missing_feature_count": len(tensor.missing_feature_names),
        "stale_feature_names": list(tensor.stale_feature_names),
        "stale_feature_count": len(tensor.stale_feature_names),
        "missing_feature_lineage_source": "tensor_reconstruction_masks",
        "tensor_missing_mask_preserved": True,
        "tensor_stale_mask_preserved": True,
        "source_availability_preserved": True,
        "source_availability_recorded": True,
        "lineage_mask_present": True,
    }


def _parse_trust_time(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed_epoch = float(value)
        except (TypeError, ValueError):
            return None
        if parsed_epoch <= 0 or parsed_epoch != parsed_epoch:
            return None
        if parsed_epoch > 10_000_000_000:
            parsed_epoch /= 1000.0
        try:
            return datetime.fromtimestamp(parsed_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_epoch = float(text)
        except (TypeError, ValueError):
            return None
        if parsed_epoch <= 0 or parsed_epoch != parsed_epoch:
            return None
        if parsed_epoch > 10_000_000_000:
            parsed_epoch /= 1000.0
        try:
            return datetime.fromtimestamp(parsed_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trainer_feedback_row_usable(row: Mapping[str, Any]) -> bool:
    if trainer_feedback_quarantine_rejection_reasons(row):
        return False
    if row.get("trainer_consumable") is False:
        return False
    missing = row.get("missing_feedback_fields")
    if isinstance(missing, list) and missing:
        return False
    if _feedback_trust_rejection_reasons(row):
        return False
    if row.get("feedback_schema_version") and any(
        row.get(field) in (None, "") for field in REQUIRED_FEEDBACK_FIELDS
    ):
        return False
    if row.get("trainer_feedback_source") == "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE":
        if audit_quality_rejection_reasons(dict(row)):
            return False
    return True


def _counterfactual_trainer_feedback_row_usable(row: Mapping[str, Any]) -> bool:
    if row.get("trainer_feedback_source") not in COUNTERFACTUAL_TRAINER_FEEDBACK_SOURCES:
        return False
    if row.get("counterfactual_label_pending") is True:
        return False
    if row.get("trainer_consumable") is not True:
        return False
    if row.get("counts_as_a_plus") is True or row.get("counts_as_final_a_plus") is True:
        return False
    if row.get("counts_as_live_ready") is True or row.get("routes_to_live") is True:
        return False
    return _trainer_feedback_row_usable(row)


def _paper_exploration_materialization_feedback_row_usable(row: Mapping[str, Any]) -> bool:
    feedback_source = row.get("trainer_feedback_source")
    feedback_type = row.get("feedback_type")
    if (
        feedback_source not in PAPER_EXPLORATION_MATERIALIZATION_TRAINER_FEEDBACK_SOURCES
        and feedback_type not in PAPER_EXPLORATION_MATERIALIZATION_CLOSED_FEEDBACK_TYPES
    ):
        return False
    if row.get("future_label_pending") is True or row.get("counterfactual_label_pending") is True:
        return False
    if row.get("trainer_consumable") is not True:
        return False
    if row.get("counts_as_a_plus") is True or row.get("counts_as_A_plus") is True:
        return False
    if row.get("counts_as_final_a_plus") is True or row.get("counts_as_final_A_plus") is True:
        return False
    if row.get("counts_as_live_ready") is True or row.get("routes_to_live") is True:
        return False
    if row.get("places_real_order") is True or row.get("order_submitted") is True:
        return False
    if row.get("test_order_submitted") is True:
        return False
    if (
        row.get("realized_net_pnl_usd") in (None, "")
        and row.get("realized_pnl_usd") in (None, "")
        and row.get("realized_net_pnl_bps") in (None, "")
        and row.get("realized_pnl_bps") in (None, "")
    ):
        return False
    return _trainer_feedback_row_usable(row)


def _paper_outcome_label_row_usable(row: Mapping[str, Any]) -> bool:
    """Return true only for closed-trade labels carrying trainer context.

    Bare realized-PnL labels are useful for reporting, but they do not tell the
    trainer which strategy, hedge state, regime, drawdown, liquidity, or
    microstructure context produced the outcome. Those rows must stay out of
    trainer labels now that strategy/hedge feedback is part of the contract.
    """
    if row.get("trainer_feedback_source") != "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE":
        return False
    if _feedback_trust_rejection_reasons(row):
        return False
    return all(row.get(field) not in (None, "") for field in REQUIRED_FEEDBACK_FIELDS) and not audit_quality_rejection_reasons(
        dict(row)
    )


def trainer_feedback_quarantine_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in (
        "quarantine_reason",
        "invalid_admission_quarantine_reason",
        "paper_admission_quarantine_reason",
    ):
        value = row.get(field)
        if value not in (None, "", "NONE"):
            reasons.append(str(value))
    values = row.get("quarantine_reasons")
    if isinstance(values, list):
        reasons.extend(str(value) for value in values if str(value).strip())
    elif values not in (None, "", [], {}):
        reasons.append(str(values))
    if row.get("entry_gate_block_reasons"):
        reasons.append(INVALID_PAPER_ADMISSION_REJECTION_REASON)
    return sorted(set(reasons))


def _high_confidence_loss_calibration_row(row: Mapping[str, Any]) -> bool:
    try:
        confidence = float(
            row.get("confidence_at_entry")
            or row.get("confidence_calibrated")
            or row.get("selected_action_probability")
            or 0.0
        )
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.70:
        return False
    if row.get("high_confidence_loss") is True:
        return True
    if str(row.get("outcome_label") or "").lower() == "loss":
        return True
    if row.get("action_was_profitable") is False:
        return True
    try:
        return float(row.get("realized_pnl_bps") or 0.0) < 0.0
    except (TypeError, ValueError):
        return False


def _feedback_trust_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in REQUIRED_TRUST_ENVELOPE_FIELDS:
        value = row.get(field)
        if value in (None, "") or (field == "source_hashes" and (not isinstance(value, Mapping) or not value)):
            reasons.append(f"MISSING_TRUST_{field.upper()}")
    decision_time = _parse_trust_time(row.get("decision_time"))
    available_at = _parse_trust_time(row.get("available_at"))
    feature_cutoff = _parse_trust_time(row.get("feature_cutoff"))
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if _high_confidence_loss_calibration_row(row):
        reasons = [
            reason for reason in reasons if not reason.startswith("MISSING_TRUST_")
        ]
    return reasons


def _extra_contract_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("mtf_snapshot_id") is None:
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    if row.get("mtf_snapshot_valid") is not True:
        reasons.append("MTF_SNAPSHOT_INVALID")
    for reason in row.get("mtf_snapshot_reject_reasons") or []:
        reasons.append(f"MTF_SNAPSHOT:{reason}")
    masa_cutoff = _parse_trust_time(row.get("masa_feature_cutoff"))
    ppo_cutoff = _parse_trust_time(row.get("ppo_feature_cutoff"))
    decision_time = _parse_trust_time(row.get("decision_time_est"))
    if masa_cutoff is not None and ppo_cutoff is not None and masa_cutoff != ppo_cutoff:
        reasons.append("MASA_PPO_CUTOFF_MISMATCH")
    if masa_cutoff is not None and decision_time is not None and masa_cutoff > decision_time:
        reasons.append("MASA_FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if row.get("backfilled") is True and str(row.get("source_mode") or "").lower() == "live":
        reasons.append("BACKFILLED_DATA_MARKED_LIVE")
    return reasons


def _missing_names_are_optional_or_event_dependent(value: Any) -> bool:
    if isinstance(value, Mapping):
        names = [str(name) for name in value.keys()]
    elif isinstance(value, (list, tuple)):
        names = [str(name) for name in value]
    else:
        return False
    names = [name for name in names if name.strip()]
    if not names:
        return False
    for name in names:
        lowered = name.lower()
        if not any(token in lowered for token in OPTIONAL_OR_EVENT_FEATURE_TOKENS):
            return False
    return True


def _example_trusted_for_training(example: TrainingExample) -> bool:
    row = example.trust_row or {}
    if row.get("accepted_for_training") is not True:
        return False
    if row.get("reject_reasons"):
        return False
    classification = str(example.row_classification).upper()
    if classification == "STALE_MASKED":
        return False
    if classification == "MISSING_MASKED":
        return True
    return classification == "TRAINABLE"


class V2HybridTrainerDataLoader:
    """Read V2 Redis/file payloads and build trainer examples."""

    def __init__(
        self,
        *,
        io: V2OnlyJsonIO | None = None,
        tensor_builder: V2UnifiedFeatureTensorBuilder | None = None,
        replay_bundle_paths: Iterable[Path] = (),
        trusted_replay_archive_root: Path | None = None,
    ) -> None:
        self.io = io or V2OnlyJsonIO(client=None)
        self.tensor_builder = tensor_builder or V2UnifiedFeatureTensorBuilder()
        self.replay_bundle_paths = tuple(Path(p) for p in replay_bundle_paths)
        self.trusted_replay_archive_root = trusted_replay_archive_root or default_archive_root()
        self.last_trusted_replay_scan: dict[str, Any] = {}
        self.last_trusted_replay_backfill_scan: dict[str, Any] = {}
        self.last_prediction_grid_load: dict[str, Any] = {}
        # Request-scoped batch cache: load_snapshot_payloads primes this with a
        # single pipelined round-trip so the ~57 per-pair reads stop paying
        # sequential Redis latency (the dominant prediction-grid cost).
        self._request_key_cache: dict[str, Any] | None = None

    def _get(self, key: str) -> Any:
        assert_v2_key(key)
        cache = self._request_key_cache
        if cache is not None and key in cache:
            return cache[key]
        return self.io.get_json(key)

    def _get_first(self, *keys: str) -> tuple[Any, str]:
        for key in keys:
            payload = self._get(key)
            if payload is not None:
                return payload, key
        return None, keys[0]

    def _get_current_coinank(self, key: str) -> Any:
        """Read the direct CoinAnk current-source key without permitting writes.

        The no-wrapper migration runs the legacy-owned CoinAnk ingestor as-is,
        and its current read contract is ``latest:coinank:*``. This method is
        deliberately read-only and only permits that narrow namespace so the
        trainer can consume current CoinAnk evidence without adding a bridge or
        writing old Redis keys.
        """
        if not key.startswith("latest:coinank:"):
            raise ValueError(f"non_current_coinank_key_rejected:{key}")
        self.io.audit.reads_attempted += 1
        client = self.io.client
        if client is None:
            self.io.audit.reads_missing += 1
            return None
        try:
            raw = client.get(key)
        except Exception as exc:  # noqa: BLE001
            self.io.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
            self.io.audit.reads_missing += 1
            return None
        if raw is None:
            self.io.audit.reads_missing += 1
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                self.io.audit.errors.append(f"json_decode_failed:{key}")
                return None
        return raw

    def _get_merged(self, *keys: str) -> tuple[Any, str]:
        merged: dict[str, Any] = {}
        used: list[str] = []
        for key in keys:
            payload = self._get(key)
            if not isinstance(payload, Mapping):
                continue
            merged.update(payload)
            features = payload.get("features")
            if isinstance(features, Mapping):
                merged.update(features)
            used.append(key)
        if merged:
            return merged, ",".join(used)
        return None, keys[0]

    @staticmethod
    def _closed_candle_series_from_raw(raw: Any, *, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        current_ms = now_ms()
        rows = raw if isinstance(raw, list) else [raw]
        closed_rows: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, Mapping):
                close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
                is_closed = (
                    row.get("is_closed") is True
                    or row.get("closed_candle") is True
                    or row.get("candle_closed_confirmed") is True
                )
                if close_ms is None or close_ms > current_ms or not is_closed:
                    continue
                closed_rows.append(dict(row))
                continue
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                continue
            close_ms = parse_ms(row[6])
            if close_ms is None or close_ms > current_ms:
                continue
            try:
                closed_rows.append(
                    canonical_from_binance_rest(
                        row,
                        symbol=symbol,
                        timeframe=timeframe,
                        ingested_at=close_ms,
                    ).to_dict()
                )
            except (TypeError, ValueError):
                continue
        closed_rows.sort(key=lambda item: int(parse_ms(item.get("candle_open_time") or item.get("open_time")) or 0))
        return closed_rows

    def _read_closed_candle_series(self, *, symbol: str, timeframe: str) -> tuple[Any, str]:
        closed_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
        closed_payload = self._get(closed_key)
        raw_key = f"v2:market:ohlcv:binance:{symbol}:{timeframe}"
        raw_payload = self._get(raw_key)
        closed_from_raw = self._closed_candle_series_from_raw(raw_payload, symbol=symbol, timeframe=timeframe)
        if isinstance(closed_payload, list) and closed_payload:
            merged: dict[int, dict[str, Any]] = {}
            for row in self._closed_candle_series_from_raw(closed_payload, symbol=symbol, timeframe=timeframe):
                close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
                if close_ms is not None:
                    merged[int(close_ms)] = dict(row)
            for row in closed_from_raw:
                close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
                if close_ms is not None:
                    merged[int(close_ms)] = dict(row)
            if merged:
                return [merged[key] for key in sorted(merged)], f"{closed_key},{raw_key}"
            return closed_payload, closed_key
        if closed_from_raw:
            return closed_from_raw, raw_key
        return closed_payload, closed_key

    def load_payloads(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        keys = {
            "prices": f"v2:market:prices:{symbol}",
            "ohlcv": f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}",
            "orderbook": f"v2:market:orderbook:{symbol}",
            "funding": f"v2:market:funding:{symbol}",
            "open_interest": f"v2:market:open_interest:{symbol}",
            "open_interest_hist": f"v2:market:open_interest_hist:{symbol}:5m",
            "long_short": f"v2:market:long_short:{symbol}",
            "coinank": f"v2:market:coinank:{symbol}",
            "kucoin": f"v2:market:kucoin:{symbol}",
            "coinapi": f"v2:market:coinapi:{symbol}",
            "microstructure": f"v2:market:microstructure:{symbol}",
            "trade_tape": f"v2:microstructure:trade_tape_confirmation:{symbol}",
            "microstructure_trust": f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            "cascade_context": f"v2:microstructure:cascade_context:{symbol}:{timeframe}",
            "ta_full_htf_1h": f"v2:features:ta_full:{symbol}:1h",
            "trade_tape_features": f"v2:market:trade_tape_features:{symbol}",
            "liquidations": "v2:liquidations:events",
            "liquidations_agg": f"v2:market:liquidations:aggregate:{symbol}",
            "liquidation_levels": f"v2:market:liquidation_levels:{symbol}",
            "liquidity_zones": f"v2:market:liquidity_zones:{symbol}",
            "fvg": f"v2:market:fvg:{symbol}:{timeframe}",
            "market_structure": f"v2:market:structure:{symbol}:{timeframe}",
            "sweep_risk": f"v2:market:sweep_risk:{symbol}:{timeframe}",
            "vwap_features": f"v2:market:vwap:{symbol}:{timeframe}",
            "volume_profile": f"v2:market:volume_profile:{symbol}:{timeframe}",
            "cvd_features": f"v2:market:cvd:{symbol}:{timeframe}",
            "advanced_trade_tape": f"v2:market:trade_tape_features:{symbol}",
            "technical_analysis": f"v2:technical_analysis:{symbol}:{timeframe}",
            "features_latest": f"v2:features:latest:{symbol}:{timeframe}",
            "features_ta": f"v2:features:ta:{symbol}:{timeframe}",
            "features_ta_full": f"v2:features:ta_full:{symbol}:{timeframe}",
            "unified_features": f"v2:unified_features:{symbol}:{timeframe}",
            "prediction": f"v2:prediction:{symbol}:{timeframe}",
            "symbol_score": f"v2:altdata:symbol_score:{symbol}",
            "moralis_features": f"v2:features:moralis:{symbol}:{timeframe}",
            "smart_money_signals": f"v2:smart_money:signals:{symbol}",
            "altdata_confluence": f"v2:altdata:confluence:{symbol}:{timeframe}",
            "risk_decisions": "v2:risk:decisions",
            "orchestrator_decisions": "v2:orchestrator:decisions",
            "paper_ledger": "v2:paper:ledger",
            "paper_positions": "v2:paper:positions",
            "paper_position_history": "v2:paper:position_history",
            "paper_outcome_labels": "v2:paper:outcome_labels",
            "trainer_feedback_outcomes": TRAINER_FEEDBACK_OUTCOMES_KEY,
            "trainer_feedback_counterfactuals": TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
            "trainer_feedback_paper_exploration_materialization": (
                TRAINER_FEEDBACK_PAPER_EXPLORATION_MATERIALIZATION_KEY
            ),
        }
        payloads = {name: self._get(key) for name, key in keys.items()}
        payloads["ohlcv"], keys["ohlcv"] = self._read_closed_candle_series(symbol=symbol, timeframe=timeframe)
        direct_orderbook, direct_orderbook_key = self._get_merged(
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:orderbook:depth:binance:{symbol}",
            f"v2:orderbook:top:binance:{symbol}",
            f"v2:orderbook:features:kucoin:{symbol}",
            f"v2:orderbook:depth:kucoin:{symbol}",
            f"v2:orderbook:top:kucoin:{symbol}",
            f"v2:market:orderbook:{symbol}",
            f"v2:market:orderbook:binance:{symbol}",
        )
        if direct_orderbook is not None:
            payloads["orderbook"] = direct_orderbook
            keys["orderbook"] = direct_orderbook_key
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            payloads[f"ohlcv_closed_{snapshot_timeframe}"], key = self._read_closed_candle_series(
                symbol=symbol,
                timeframe=snapshot_timeframe,
            )
            keys[f"ohlcv_closed_{snapshot_timeframe}"] = key
        microstructure, microstructure_key = self._get_merged(
            f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            f"v2:microstructure:feed_quality:binance:{symbol}",
            f"v2:microstructure:feed_quality:kucoin:{symbol}",
            f"v2:microstructure:adversarial_features:binance:{symbol}",
            f"v2:microstructure:adversarial_features:kucoin:{symbol}",
            f"v2:microstructure:trade_tape_confirmation:{symbol}",
            f"v2:microstructure:cross_venue_confirmation:{symbol}",
            f"v2:microstructure:sweep_risk:{symbol}:{timeframe}",
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:orderbook:features:kucoin:{symbol}",
            f"v2:market:microstructure:{symbol}",
            f"v2:market:coinapi:wsds:{symbol}",
            f"v2:features:microfeat:{symbol}:{timeframe}",
        )
        liquidation_levels, liquidation_levels_key = self._get_merged(
            f"v2:market:liquidation_levels:{symbol}",
            f"v2:liquidations:levels:{symbol}:{timeframe}",
            f"v2:unified_features:{symbol}:{timeframe}",
            f"v2:unified_features:{symbol}:{timeframe}:latest",
        )
        payloads["microstructure"] = microstructure
        payloads["liquidation_levels"] = liquidation_levels
        keys["microstructure"] = microstructure_key
        keys["liquidation_levels"] = liquidation_levels_key
        coinank_keys = {
            "coinank_open_interest": f"latest:coinank:open_interest:{symbol}:{timeframe}",
            "coinank_funding": f"latest:coinank:funding:{symbol}:{timeframe}",
            "coinank_long_short": f"latest:coinank:long_short:{symbol}:{timeframe}",
            "coinank_liquidations": f"latest:coinank:liquidations:{symbol}:{timeframe}",
            "coinank_market_order_flow": f"latest:coinank:market_order_flow:{symbol}:{timeframe}",
            "coinank_advanced": f"latest:coinank:advanced:{symbol}:{timeframe}",
        }
        for name, key in coinank_keys.items():
            payloads[name] = self._get_current_coinank(key)
            keys[name] = key
        nansen, nansen_key = self._get_first(
            f"v2:altdata:nansen:symbol:{symbol}",
            f"v2:altdata:nansen:{symbol}",
        )
        lunarcrush, lunarcrush_key = self._get_first(
            f"v2:altdata:lunarcrush:symbol:{symbol}",
            f"v2:altdata:lunarcrush:{symbol}",
        )
        public_intel, public_intel_key = self._get_first(
            f"v2:altdata:public_intel:symbol:{symbol}",
            f"v2:altdata:public_intel:{symbol}",
        )
        aicoin, aicoin_key = self._get_first(
            f"v2:altdata:aicoin:symbol:{symbol}",
            f"v2:altdata:aicoin:{symbol}",
        )
        whale_walls, whale_walls_key = self._get_first(
            f"v2:altdata:whale_walls:symbol:{symbol}",
            f"v2:altdata:whale_walls:{symbol}",
        )
        santiment, santiment_key = self._get_first(
            f"v2:altdata:santiment:symbol:{symbol}",
            f"v2:altdata:santiment:{symbol}",
        )
        payloads.update(
            {
                "nansen": nansen,
                "lunarcrush": lunarcrush,
                "public_intel": public_intel,
                "aicoin": aicoin,
                "whale_walls": whale_walls,
                "santiment": santiment,
            }
        )
        keys.update(
            {
                "nansen": nansen_key,
                "lunarcrush": lunarcrush_key,
                "public_intel": public_intel_key,
                "aicoin": aicoin_key,
                "whale_walls": whale_walls_key,
                "santiment": santiment_key,
            }
        )
        payloads["_keys"] = keys
        return payloads

    def load_snapshot_payloads(self, *, symbol: str, timeframe: str) -> dict[str, Any] | None:
        latest_key = f"v2:features:latest:{symbol}:{timeframe}"
        owns_cache = self._request_key_cache is None
        if owns_cache:
            self._prime_snapshot_request_cache(symbol=symbol, timeframe=timeframe, latest_key=latest_key)
        try:
            return self._load_snapshot_payloads_inner(
                symbol=symbol, timeframe=timeframe, latest_key=latest_key
            )
        finally:
            if owns_cache:
                self._request_key_cache = None

    def _snapshot_request_keys(self, *, symbol: str, timeframe: str, latest_key: str) -> list[str]:
        batch: list[str] = [latest_key]
        batch += [
            f"v2:market:funding:{symbol}",
            f"v2:market:open_interest:{symbol}",
            f"v2:market:open_interest_hist:{symbol}:5m",
            f"v2:market:long_short:{symbol}",
            f"v2:market:orderbook:{symbol}",
            f"v2:market:liquidations:aggregate:{symbol}",
            f"v2:market:liquidation_levels:{symbol}",
            f"v2:market:liquidity_zones:{symbol}",
            f"v2:market:fvg:{symbol}:{timeframe}",
            f"v2:market:structure:{symbol}:{timeframe}",
            f"v2:market:sweep_risk:{symbol}:{timeframe}",
            f"v2:market:vwap:{symbol}:{timeframe}",
            f"v2:market:volume_profile:{symbol}:{timeframe}",
            f"v2:market:cvd:{symbol}:{timeframe}",
            f"v2:market:trade_tape_features:{symbol}",
            f"v2:altdata:symbol_score:{symbol}",
            f"v2:altdata:public_intel:symbol:{symbol}",
            f"v2:altdata:aicoin:symbol:{symbol}",
            f"v2:altdata:whale_walls:symbol:{symbol}",
            f"v2:altdata:santiment:symbol:{symbol}",
            f"v2:altdata:lunarcrush:symbol:{symbol}",
            f"v2:altdata:nansen:symbol:{symbol}",
            "v2:paper:positions",
            "v2:risk:decisions",
            "v2:orchestrator:decisions",
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:orderbook:depth:binance:{symbol}",
            f"v2:orderbook:top:binance:{symbol}",
            f"v2:orderbook:features:kucoin:{symbol}",
            f"v2:orderbook:depth:kucoin:{symbol}",
            f"v2:orderbook:top:kucoin:{symbol}",
            f"v2:market:orderbook:binance:{symbol}",
            f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            f"v2:microstructure:cascade_context:{symbol}:{timeframe}",
            f"v2:features:ta_full:{symbol}:1h",
            f"v2:features:moralis:{symbol}:{timeframe}",
            f"v2:altdata:confluence:{symbol}:{timeframe}",
            f"v2:smart_money:signals:{symbol}",
            f"v2:microstructure:feed_quality:binance:{symbol}",
            f"v2:microstructure:feed_quality:kucoin:{symbol}",
            f"v2:microstructure:adversarial_features:binance:{symbol}",
            f"v2:microstructure:adversarial_features:kucoin:{symbol}",
            f"v2:microstructure:trade_tape_confirmation:{symbol}",
            f"v2:microstructure:cross_venue_confirmation:{symbol}",
            f"v2:microstructure:sweep_risk:{symbol}:{timeframe}",
            f"v2:market:microstructure:{symbol}",
            f"v2:market:coinapi:wsds:{symbol}",
            f"v2:features:microfeat:{symbol}:{timeframe}",
        ]
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            batch.append(f"v2:market:ohlcv_closed:binance:{symbol}:{snapshot_timeframe}")
            batch.append(f"v2:market:ohlcv:binance:{symbol}:{snapshot_timeframe}")
        return list(dict.fromkeys(batch))

    def _prime_snapshot_request_cache(self, *, symbol: str, timeframe: str, latest_key: str) -> None:
        """One pipelined round-trip for every key this snapshot build reads."""
        getter = getattr(self.io, "get_json_many", None)
        if getter is None:
            return
        batch = self._snapshot_request_keys(symbol=symbol, timeframe=timeframe, latest_key=latest_key)
        try:
            self._request_key_cache = dict(getter(batch))
        except Exception:
            self._request_key_cache = None

    def _prime_prediction_grid_request_cache(self, pairs: Iterable[tuple[str, str]]) -> int:
        getter = getattr(self.io, "get_json_many", None)
        if getter is None:
            return 0
        batch: list[str] = []
        for symbol, timeframe in pairs:
            latest_key = f"v2:features:latest:{symbol}:{timeframe}"
            batch.extend(
                self._snapshot_request_keys(symbol=symbol, timeframe=timeframe, latest_key=latest_key)
            )
        unique = list(dict.fromkeys(batch))
        if not unique:
            return 0
        try:
            self._request_key_cache = dict(getter(unique))
        except Exception:
            self._request_key_cache = None
            return 0
        return len(unique)

    def _load_snapshot_payloads_inner(
        self, *, symbol: str, timeframe: str, latest_key: str
    ) -> dict[str, Any] | None:
        latest = self._get(latest_key)
        if not isinstance(latest, Mapping):
            return None
        features = latest.get("features") if isinstance(latest.get("features"), Mapping) else None
        if not isinstance(features, Mapping) or not features:
            return None
        if str(latest.get("symbol") or "").upper() not in {"", symbol.upper()}:
            return None
        if str(latest.get("timeframe") or "") not in {"", timeframe}:
            return None
        payloads = self._payloads_from_feature_snapshot(snapshot=latest, features=features, feedback_row={})
        keys: dict[str, str] = {"features_latest": latest_key}
        supplemental_keys = {
            "funding": f"v2:market:funding:{symbol}",
            "open_interest": f"v2:market:open_interest:{symbol}",
            "open_interest_hist": f"v2:market:open_interest_hist:{symbol}:5m",
            "long_short": f"v2:market:long_short:{symbol}",
            "orderbook": f"v2:market:orderbook:{symbol}",
            "liquidations_agg": f"v2:market:liquidations:aggregate:{symbol}",
            "liquidation_levels": f"v2:market:liquidation_levels:{symbol}",
            "liquidity_zones": f"v2:market:liquidity_zones:{symbol}",
            "fvg": f"v2:market:fvg:{symbol}:{timeframe}",
            "market_structure": f"v2:market:structure:{symbol}:{timeframe}",
            "sweep_risk": f"v2:market:sweep_risk:{symbol}:{timeframe}",
            "vwap_features": f"v2:market:vwap:{symbol}:{timeframe}",
            "volume_profile": f"v2:market:volume_profile:{symbol}:{timeframe}",
            "cvd_features": f"v2:market:cvd:{symbol}:{timeframe}",
            "advanced_trade_tape": f"v2:market:trade_tape_features:{symbol}",
            "symbol_score": f"v2:altdata:symbol_score:{symbol}",
            "public_intel": f"v2:altdata:public_intel:symbol:{symbol}",
            "aicoin": f"v2:altdata:aicoin:symbol:{symbol}",
            "whale_walls": f"v2:altdata:whale_walls:symbol:{symbol}",
            "santiment": f"v2:altdata:santiment:symbol:{symbol}",
            "lunarcrush": f"v2:altdata:lunarcrush:symbol:{symbol}",
            "nansen": f"v2:altdata:nansen:symbol:{symbol}",
            "paper_positions": "v2:paper:positions",
            "risk_decisions": "v2:risk:decisions",
            "orchestrator_decisions": "v2:orchestrator:decisions",
            # Parity with the full payload map (build_example slow path): without
            # these the prediction fast path never resolves microstructure trust /
            # confluence / moralis features, so they stay missing on the live
            # tensor AND (post archive-fix) never reach the replay archive.
            "microstructure_trust": f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            "cascade_context": f"v2:microstructure:cascade_context:{symbol}:{timeframe}",
            "ta_full_htf_1h": f"v2:features:ta_full:{symbol}:1h",
            "moralis_features": f"v2:features:moralis:{symbol}:{timeframe}",
            "altdata_confluence": f"v2:altdata:confluence:{symbol}:{timeframe}",
            "smart_money_signals": f"v2:smart_money:signals:{symbol}",
        }
        for name, key in supplemental_keys.items():
            value = self._get(key)
            if value is not None:
                payloads[name] = value
            keys[name] = key
        direct_orderbook, direct_orderbook_key = self._get_merged(
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:orderbook:depth:binance:{symbol}",
            f"v2:orderbook:top:binance:{symbol}",
            f"v2:orderbook:features:kucoin:{symbol}",
            f"v2:orderbook:depth:kucoin:{symbol}",
            f"v2:orderbook:top:kucoin:{symbol}",
            f"v2:market:orderbook:{symbol}",
            f"v2:market:orderbook:binance:{symbol}",
        )
        if direct_orderbook is not None:
            payloads["orderbook"] = direct_orderbook
            keys["orderbook"] = direct_orderbook_key
        microstructure, microstructure_key = self._get_merged(
            f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            f"v2:microstructure:feed_quality:binance:{symbol}",
            f"v2:microstructure:feed_quality:kucoin:{symbol}",
            f"v2:microstructure:adversarial_features:binance:{symbol}",
            f"v2:microstructure:adversarial_features:kucoin:{symbol}",
            f"v2:microstructure:trade_tape_confirmation:{symbol}",
            f"v2:microstructure:cross_venue_confirmation:{symbol}",
            f"v2:microstructure:sweep_risk:{symbol}:{timeframe}",
            f"v2:orderbook:features:binance:{symbol}",
            f"v2:orderbook:features:kucoin:{symbol}",
            f"v2:market:microstructure:{symbol}",
            f"v2:market:coinapi:wsds:{symbol}",
            f"v2:features:microfeat:{symbol}:{timeframe}",
        )
        if microstructure is not None:
            payloads["microstructure"] = microstructure
        keys["microstructure"] = microstructure_key
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            payloads[f"ohlcv_closed_{snapshot_timeframe}"], key = self._read_closed_candle_series(
                symbol=symbol,
                timeframe=snapshot_timeframe,
            )
            keys[f"ohlcv_closed_{snapshot_timeframe}"] = key
        payloads["_keys"] = keys
        return payloads

    def build_example(self, *, symbol: str, timeframe: str, snapshot_fast_path: bool = False) -> TrainingExample:
        payloads = self.load_snapshot_payloads(symbol=symbol, timeframe=timeframe) if snapshot_fast_path else None
        if payloads is None:
            payloads = self.load_payloads(symbol=symbol, timeframe=timeframe)
        return self._build_example_from_payloads(symbol=symbol, timeframe=timeframe, payloads=payloads)

    def build_prediction_snapshot_example(self, *, symbol: str, timeframe: str) -> TrainingExample:
        """Build a current prediction row from the immutable feature snapshot.

        This path is intentionally prediction-only. Training rows continue to
        use the trusted replay/outcome loaders. The snapshot carries explicit
        missing/stale lineage; closed candles are still read so MTF temporal
        safety is validated without re-reading every supplemental source.
        """
        latest_key = f"v2:features:latest:{symbol}:{timeframe}"
        latest = self.io.get_json_many([latest_key]).get(latest_key)
        if not isinstance(latest, Mapping):
            latest = self.io.get_json(latest_key)
        if not isinstance(latest, Mapping):
            return self.build_example(symbol=symbol, timeframe=timeframe, snapshot_fast_path=True)
        features = latest.get("features") if isinstance(latest.get("features"), Mapping) else None
        if not isinstance(features, Mapping) or not features:
            return self.build_example(symbol=symbol, timeframe=timeframe, snapshot_fast_path=True)
        if str(latest.get("symbol") or "").upper() not in {"", symbol.upper()}:
            return self.build_example(symbol=symbol, timeframe=timeframe, snapshot_fast_path=True)
        if str(latest.get("timeframe") or "") not in {"", timeframe}:
            return self.build_example(symbol=symbol, timeframe=timeframe, snapshot_fast_path=True)

        payloads = self._payloads_from_feature_snapshot(snapshot=latest, features=features, feedback_row={})
        keys: dict[str, str] = {"features_latest": latest_key}
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            payloads[f"ohlcv_closed_{snapshot_timeframe}"], key = self._read_closed_candle_series(
                symbol=symbol,
                timeframe=snapshot_timeframe,
            )
            keys[f"ohlcv_closed_{snapshot_timeframe}"] = key
        payloads["_keys"] = keys
        return self._build_example_from_payloads(symbol=symbol, timeframe=timeframe, payloads=payloads)

    def _build_example_from_payloads(
        self,
        *,
        symbol: str,
        timeframe: str,
        payloads: Mapping[str, Any],
    ) -> TrainingExample:
        tensor = self.tensor_builder.build(
            symbol=symbol,
            timeframe=timeframe,
            payloads=payloads,
        )
        expected_move = self._label_expected_move_after_cost(
            payloads=payloads,
            tensor=tensor,
        )
        action = self._label_action(expected_move)
        snapshot_lineage = _snapshot_decision_time_lineage(payloads.get("features_latest"))
        classification = _classification_from_lineage(tensor=tensor, lineage=snapshot_lineage)
        trust_row = self._build_trust_row(
            symbol=symbol,
            timeframe=timeframe,
            payloads=payloads,
            tensor=tensor,
            classification=classification,
        )
        trust_row.update(_lineage_trust_fields(tensor=tensor, lineage=snapshot_lineage))
        outcome_row = self._matched_closed_trade_outcome(payloads=payloads, tensor=tensor)
        if outcome_row is not None:
            targets = self._outcome_targets_from_row(outcome_row)
            trust_row.update(
                {
                    "learning_mode": "outcome_supervised",
                    "update_lane": "OUTCOME_SUPERVISED_CLOSED_TRADE",
                    "outcome_targets": targets,
                    "realized_after_cost_reward": targets["realized_after_cost_reward"],
                    "value_baseline": targets["value_baseline"],
                    "advantage": targets["advantage"],
                    "advantage_source": "realized_after_cost_reward_minus_value_baseline",
                    "realized_reward_source": "realized_net_pnl_bps_after_cost",
                    "uses_expected_move_as_realized_reward": False,
                    "selected_action": targets["selected_action"],
                    "directional_outcome": targets["directional_outcome"],
                    "trade_outcome": targets["trade_outcome"],
                    "action_was_profitable": targets["action_was_profitable"],
                }
            )
            # PPO on-policy passthrough: entry-time policy fields captured on
            # the paper fill (never fabricated here). Rows carrying the full
            # contract are admitted by _has_on_policy_ppo_fields; incomplete
            # rows stay outcome-supervised.
            trust_row.update(
                {
                    field: outcome_row.get(field)
                    for field in (
                        "old_log_prob",
                        "old_value",
                        "reward",
                        "done",
                        "rollout_id",
                        "trajectory_index",
                        "action_probabilities",
                        "selected_action_log_prob",
                        "selected_action_probability",
                        "ppo_on_policy_entry_fields_present",
                        "ppo_on_policy_ineligible_reason",
                        "entry_policy_fields_source",
                    )
                    if outcome_row.get(field) not in (None, "")
                }
            )
        if _has_explicit_training_trust_evidence(trust_row):
            trust_result = classify_training_sample(trust_row)
            trust_row["accepted_for_training"] = trust_result["accepted_for_training"]
            trust_row["valid_for_training"] = trust_result["valid_for_training"]
            trust_row["market_state_integrity_score"] = trust_result["market_state_integrity_score"]
            extra_reasons = _extra_contract_rejection_reasons(trust_row)
            trust_row["reject_reasons"] = sorted(set(list(trust_result["reject_reasons"]) + extra_reasons))
            trust_row["source_lineage"] = trust_result["source_lineage"]
            if trust_result["accepted_for_training"] is not True or extra_reasons:
                classification = "MARKET_STATE_REJECTED"
                trust_row["trainer_consumable"] = False
                trust_row["row_classification"] = classification
        else:
            trust_row["accepted_for_training"] = classification != "STALE_MASKED"
            trust_row["valid_for_training"] = trust_row["accepted_for_training"]
            trust_row["market_state_integrity_score"] = None
            trust_row["reject_reasons"] = []

        return TrainingExample(
            symbol=symbol,
            timeframe=timeframe,
            tensor=tensor,
            label_action_index=action,
            label_expected_move_after_cost_bps=expected_move,
            payload_keys=tuple((payloads.get("_keys") or {}).values()),
            row_classification=classification,
            trust_row=trust_row,
        )

    def _build_trust_row(
        self,
        *,
        symbol: str,
        timeframe: str,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
        classification: str,
    ) -> dict[str, Any]:
        latest = payloads.get("features_latest")
        latest = latest if isinstance(latest, Mapping) else {}
        prediction = payloads.get("prediction")
        prediction = prediction if isinstance(prediction, Mapping) else {}
        features = latest.get("features") if isinstance(latest.get("features"), Mapping) else {}
        features_full = dict(features)
        ohlcv = payloads.get("ohlcv")
        ohlcv = ohlcv if isinstance(ohlcv, Mapping) else {}
        tensor_values = dict(zip(tensor.feature_names, tensor.values))
        tensor_missing = dict(zip(tensor.feature_names, tensor.missing_mask))
        for key in ("open", "high", "low", "close"):
            if features_full.get(key) is None:
                features_full[key] = latest.get(key, ohlcv.get(key))
            if features_full.get(key) is None and tensor_missing.get(key) == 0:
                features_full[key] = tensor_values.get(key)
        decision_time = latest.get("decision_time") or latest.get("decision_cutoff") or latest.get("generated_at")
        mtf_snapshot = build_multi_timeframe_decision_snapshot(
            symbol=symbol,
            decision_time=decision_time,
            candles_by_timeframe={
                snapshot_timeframe: payloads.get(f"ohlcv_closed_{snapshot_timeframe}")
                for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES
            },
        )
        snapshot_feature_cutoff = mtf_snapshot.get("feature_cutoff")
        snapshot_all_tf_candle_timestamps = mtf_snapshot.get("all_tf_candle_timestamps") or []
        snapshot_all_source_event_times = mtf_snapshot.get("all_source_event_times") or []
        return {
            "trust_schema_version": latest.get("trust_schema_version")
            or prediction.get("trust_schema_version")
            or TRUST_SCHEMA_VERSION,
            "enforcement_epoch": latest.get("enforcement_epoch")
            or prediction.get("enforcement_epoch")
            or ENFORCEMENT_EPOCH,
            "producer": latest.get("producer") or prediction.get("producer") or "v2_hybrid_cuda_trainer_data_loader",
            "producer_version": latest.get("producer_version")
            or prediction.get("producer_version")
            or TRUST_PRODUCER_VERSION,
            "created_at": latest.get("created_at") or prediction.get("created_at") or latest.get("generated_at"),
            "symbol": symbol,
            "timeframe": timeframe,
            "decision_id": mtf_snapshot.get("decision_id"),
            "prediction_id": prediction.get("prediction_id"),
            "mtf_snapshot_id": mtf_snapshot.get("mtf_snapshot_id"),
            "replay_snapshot_id": prediction.get("replay_snapshot_id") or latest.get("replay_snapshot_id"),
            "replay_snapshot_key": prediction.get("replay_snapshot_key") or latest.get("replay_snapshot_key"),
            "replay_snapshot_write_success": prediction.get("replay_snapshot_write_success"),
            "mtf_snapshot_valid": mtf_snapshot.get("valid"),
            "mtf_snapshot_reject_reasons": list(mtf_snapshot.get("reject_reasons") or []),
            "multi_timeframe_decision_snapshot": mtf_snapshot,
            "feature_snapshot_id": tensor.feature_snapshot_id,
            "feature_vector_hash": tensor.tensor_id,
            "feature_cutoff": latest.get("feature_cutoff")
            or latest.get("decision_cutoff")
            or snapshot_feature_cutoff
            or latest.get("generated_at"),
            "available_at": latest.get("available_at") or latest.get("source_available_time") or latest.get("generated_at"),
            "latency_ms": latest.get("latency_ms"),
            "generated_at": latest.get("generated_at") or latest.get("generated_utc"),
            "feature_freshness_state": latest.get("feature_freshness_state"),
            "trainer_consumable": classification == "TRAINABLE",
            "row_classification": classification,
            "missing_feature_count": len(tensor.missing_feature_names),
            "missing_feature_names": list(tensor.missing_feature_names),
            "stale_feature_count": len(tensor.stale_feature_names),
            "stale_feature_names": list(tensor.stale_feature_names),
            "candle_closed_confirmed": latest.get("candle_closed_confirmed")
            if "candle_closed_confirmed" in latest
            else latest.get("closed_candle"),
            "candle_open_time": latest.get("candle_open_time"),
            "candle_close_time": latest.get("candle_close_time"),
            "source_event_time_est": latest.get("source_event_time") or latest.get("source_event_time_est"),
            "source_received_time_est": latest.get("source_received_time_est")
            or latest.get("source_available_time")
            or latest.get("available_at"),
            "source_available_time": latest.get("source_available_time") or latest.get("available_at"),
            "decision_time_est": decision_time,
            "masa_feature_cutoff": prediction.get("masa_feature_cutoff") or latest.get("masa_feature_cutoff"),
            "ppo_feature_cutoff": prediction.get("ppo_feature_cutoff")
            or latest.get("ppo_feature_cutoff")
            or latest.get("feature_cutoff")
            or snapshot_feature_cutoff,
            "all_tf_candle_timestamps": snapshot_all_tf_candle_timestamps
            or latest.get("all_tf_candle_timestamps")
            or [],
            "all_source_event_times": snapshot_all_source_event_times
            or latest.get("all_source_event_times")
            or [],
            "source_lineage": latest.get("source_lineage") or {},
            "price_disagreement_bps": latest.get("price_disagreement_bps") or prediction.get("price_disagreement_bps"),
            "duplicate_event_count": latest.get("duplicate_event_count"),
            "out_of_order_event_count": latest.get("out_of_order_event_count"),
            "missing_candle_count": latest.get("missing_candle_count"),
            "backfilled": latest.get("backfilled") if "backfilled" in latest else latest.get("is_backfilled"),
            "is_backfilled": latest.get("is_backfilled") if "is_backfilled" in latest else latest.get("backfilled"),
            "source_mode": latest.get("source_mode") or prediction.get("source_mode"),
            "features": dict(features_full),
        }

    def load_training_examples(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        limit: int | None = None,
        trusted_only: bool = False,
        closed_trade_only: bool = False,
        snapshot_fast_path: bool = False,
    ) -> list[TrainingExample]:
        examples: list[TrainingExample] = []
        if trusted_only:
            for example in self._closed_trade_snapshot_training_examples():
                examples.append(example)
                if limit is not None and len(examples) >= int(limit):
                    return examples
            if closed_trade_only:
                return examples
        for symbol in symbols:
            for timeframe in timeframes:
                example = self.build_example(
                    symbol=symbol,
                    timeframe=timeframe,
                    snapshot_fast_path=snapshot_fast_path,
                )
                if trusted_only and not _example_trusted_for_training(example):
                    continue
                examples.append(example)
                if limit is not None and len(examples) >= int(limit):
                    return examples
        return examples

    def load_prediction_grid_examples(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        limit: int | None = None,
        snapshot_fast_path: bool = True,
        max_workers: int = 1,
    ) -> list[TrainingExample]:
        """Build current-grid prediction examples concurrently.

        This is a performance-only path for current prediction publication.
        Each worker uses the same ``build_example`` logic and read-only IO as
        the sequential loader, so feature_cutoff/available_at/decision_time
        checks and row classification are unchanged.
        """
        pairs: list[tuple[str, str]] = []
        max_count = int(limit) if limit is not None else None
        for symbol in symbols:
            for timeframe in timeframes:
                if max_count is not None and len(pairs) >= max_count:
                    break
                pairs.append((str(symbol), str(timeframe)))
            if max_count is not None and len(pairs) >= max_count:
                break
        if not pairs:
            self.last_prediction_grid_load = {
                "pair_count": 0,
                "parallel_workers": 0,
                "parallel_loader_used": False,
            }
            return []
        workers = max(1, min(int(max_workers or 1), len(pairs)))
        owns_cache = self._request_key_cache is None
        cache_key_count = self._prime_prediction_grid_request_cache(pairs) if owns_cache and snapshot_fast_path else 0
        if workers <= 1:
            try:
                examples = [
                    self.build_example(
                        symbol=symbol,
                        timeframe=timeframe,
                        snapshot_fast_path=snapshot_fast_path,
                    )
                    for symbol, timeframe in pairs
                ]
            finally:
                if owns_cache:
                    self._request_key_cache = None
            self.last_prediction_grid_load = {
                "pair_count": len(pairs),
                "parallel_workers": 1,
                "parallel_loader_used": False,
                "grid_request_cache_key_count": cache_key_count,
            }
            return examples

        def _build(pair: tuple[str, str]) -> TrainingExample:
            symbol, timeframe = pair
            return self.build_example(
                symbol=symbol,
                timeframe=timeframe,
                snapshot_fast_path=snapshot_fast_path,
            )

        examples: list[TrainingExample] = []
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                examples.extend(pool.map(_build, pairs))
        finally:
            if owns_cache:
                self._request_key_cache = None
        self.last_prediction_grid_load = {
            "pair_count": len(pairs),
            "parallel_workers": workers,
            "parallel_loader_used": True,
            "snapshot_fast_path": bool(snapshot_fast_path),
            "grid_request_cache_key_count": cache_key_count,
        }
        return examples

    def _trusted_replay_cursor_path(self, *, backfill: bool = False) -> Path:
        name = "trusted_replay_backfill_cursor.json" if backfill else "trusted_replay_cursor.json"
        return Path(self.trusted_replay_archive_root) / name

    def _read_trusted_replay_cursor(self, *, backfill: bool = False) -> int:
        try:
            payload = json.loads(
                self._trusted_replay_cursor_path(backfill=backfill).read_text(encoding="utf-8")
            )
            return max(0, int(payload.get("manifest_offset") or 0))
        except (OSError, ValueError, TypeError):
            return -1

    def _write_trusted_replay_cursor(
        self,
        offset: int,
        *,
        frontier_reached: bool,
        backfill: bool = False,
        epoch_wrapped: bool = False,
    ) -> None:
        try:
            self._trusted_replay_cursor_path(backfill=backfill).write_text(
                json.dumps(
                    {
                        "manifest_offset": int(offset),
                        "frontier_reached": bool(frontier_reached),
                        "backfill_lane": bool(backfill),
                        "epoch_wrapped": bool(epoch_wrapped),
                        "updated_utc": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def load_trusted_replay_examples(
        self,
        *,
        limit: int | None = None,
        backfill: bool = False,
    ) -> list[TrainingExample]:
        """Consume labelable snapshots from a persistent oldest-first cursor.

        F-0013: the previous newest-first bounded scan only ever inspected the
        most recent minutes of a ~13k-snapshots/hour archive, whose rows are
        younger than the outcome label horizon (max 4h) and therefore always
        rejected (NO_LATER_FINALIZED_CANDLES). The lane loaded 0 rows and the
        trainer stayed INFERENCE_ONLY. The cursor walks forward and stops at
        the embargo frontier (now - 4.5h); each cycle consumes snapshots that
        newly crossed the frontier, giving a continuous training stream.

        ``backfill=True`` runs the historical epoch lane: a second cursor
        re-consumes archive rows BEHIND the frontier cursor so a restarted
        replay buffer can refill from the full archive instead of waiting on
        live production rate. It stops at the frontier cursor (that region
        belongs to the primary lane) and wraps to offset 0 when it catches up,
        starting the next epoch over history. The frontier cursor is never
        touched by this lane.
        """
        examples: list[TrainingExample] = []
        requested_limit = TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE if limit is None else max(0, int(limit))
        scan_limit = min(
            max(
                requested_limit * TRUSTED_REPLAY_SCAN_MULTIPLIER,
                requested_limit,
                TRUSTED_REPLAY_MIN_SCAN_PER_CYCLE,
            ),
            TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE,
        )
        embargo_cutoff = datetime.now(tz=timezone.utc) - timedelta(
            seconds=TRUSTED_REPLAY_LABEL_EMBARGO_SECONDS
        )
        backfill_stop_offset: int | None = None
        epoch_wrapped = False
        cursor = self._read_trusted_replay_cursor(backfill=backfill)
        if cursor < 0:
            cursor = 0
        if backfill:
            frontier_cursor = self._read_trusted_replay_cursor()
            backfill_stop_offset = max(0, frontier_cursor)
            if backfill_stop_offset and cursor >= backfill_stop_offset:
                cursor = 0
                epoch_wrapped = True
        rejections: dict[str, int] = {}
        scanned = 0
        frontier_reached = False
        consumed_offset = cursor
        # Phase 1: collect the chunk so every snapshot can see the candles of
        # the snapshots that FOLLOW it inside the chunk (outcome labels need
        # future candles; incremental collection would starve the earliest
        # rows in every chunk).
        chunk: list[tuple[int, dict[str, Any]]] = []
        archive_candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
        candle_cache: dict[tuple[str, str], tuple[Any, str]] = {}
        for next_offset, snapshot in iter_snapshots_from_offset(
            self.trusted_replay_archive_root, start_offset=cursor
        ):
            if scanned >= scan_limit:
                break
            if backfill_stop_offset is not None and next_offset > backfill_stop_offset:
                # The region past the frontier cursor belongs to the primary lane.
                frontier_reached = True
                break
            decision_time = _parse_iso_utc(
                snapshot.get("decision_time") or snapshot.get("generated_utc")
            )
            if decision_time is not None and decision_time > embargo_cutoff:
                frontier_reached = True
                break
            scanned += 1
            chunk.append((next_offset, snapshot))
            candle, _candle_reasons = snapshot_to_final_candle(snapshot)
            if candle is not None:
                pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
                archive_candles.setdefault(pair, []).append(candle)
        for rows in archive_candles.values():
            rows.sort(key=lambda row: str(row.get("candle_close_time") or ""))
        # Phase 2: build examples; the cursor only advances past snapshots
        # whose build was attempted so an early example-limit stop does not
        # silently skip unprocessed rows.
        for next_offset, snapshot in chunk:
            if limit is not None and len(examples) >= int(limit):
                break
            consumed_offset = next_offset
            symbol = str(snapshot.get("symbol") or "").upper()
            timeframe = str(snapshot.get("timeframe") or "")
            if not symbol or not timeframe:
                rejections["symbol_or_timeframe_missing"] = rejections.get("symbol_or_timeframe_missing", 0) + 1
                continue
            cache_key = (symbol, timeframe)
            if cache_key not in candle_cache:
                candle_cache[cache_key] = self._read_closed_candle_series(symbol=symbol, timeframe=timeframe)
            candles, candle_key = candle_cache[cache_key]
            candle_rows = list(archive_candles.get(cache_key) or [])
            if isinstance(candles, list):
                candle_rows.extend(candles)
            replay_row, reasons = build_trusted_replay_row(snapshot, candles=candle_rows)
            if replay_row is None:
                for reason in reasons or ["trusted_replay_row_not_built"]:
                    rejections[str(reason)] = rejections.get(str(reason), 0) + 1
                continue
            features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
            if not features:
                rejections["features_empty"] = rejections.get("features_empty", 0) + 1
                continue
            payloads = self._payloads_from_feature_snapshot(
                snapshot=snapshot,
                features=features,
                feedback_row=replay_row,
            )
            payloads["_keys"] = {
                "features_latest": f"durable_feature_snapshot_archive:{snapshot.get('snapshot_id')}",
                "trainer_feedback_outcomes": replay_row["sample_id"],
                "ohlcv": candle_key,
            }
            tensor = self.tensor_builder.build(symbol=symbol, timeframe=timeframe, payloads=payloads)
            if tensor.data_coverage_percent < 20.0:
                rejections["data_coverage_below_20pct"] = rejections.get("data_coverage_below_20pct", 0) + 1
                continue
            snapshot_lineage = _snapshot_decision_time_lineage(snapshot)
            classification = _classification_from_lineage(tensor=tensor, lineage=snapshot_lineage)
            missing_feature_names = list(
                (
                    (snapshot_lineage or {}).get("missing_feature_names")
                    if snapshot_lineage is not None
                    else tensor.missing_feature_names
                )
                or []
            )
            stale_feature_names = list(
                (
                    (snapshot_lineage or {}).get("stale_feature_names")
                    if snapshot_lineage is not None
                    else tensor.stale_feature_names
                )
                or []
            )
            safe_missing_mask_replay_candidate = (
                classification == "MISSING_MASKED"
                and not stale_feature_names
                and "critical_family_absent:ohlcv_core" not in missing_feature_names
            )
            trust_row = dict(replay_row)
            trust_row.update(_lineage_trust_fields(tensor=tensor, lineage=snapshot_lineage))
            trust_row.update(
                {
                    "row_source": "trusted_replay_archive",
                    "trusted_replay_row": True,
                    "historical_replay_row": True,
                    "trusted_replay_backfill_lane": bool(backfill),
                    "row_classification": classification,
                    "classification_mask_present": True,
                    "feature_vector_hash": tensor.tensor_id,
                    "market_state_integrity_score": replay_row.get("market_state_integrity_score"),
                    "reject_reasons": list(reasons),
                    "safe_to_train_with_missing_mask": safe_missing_mask_replay_candidate,
                    "safe_missing_mask_training_scope": (
                        "HISTORICAL_REPLAY_ONLY"
                        if safe_missing_mask_replay_candidate
                        else None
                    ),
                    "feature_family_introduced_after_snapshot_time": safe_missing_mask_replay_candidate,
                    "critical_missing_vs_optional_missing": (
                        "HISTORICAL_SCHEMA_MISSING_MASKED"
                        if safe_missing_mask_replay_candidate
                        else "NONE"
                    ),
                    "safe_to_train_with_missing_mask_reason": (
                        "PIT_REPLAY_ROW_WITH_EXPLICIT_MISSING_MASK_AND_NO_STALE_OR_FUTURE_LEAK_FLAGS"
                        if safe_missing_mask_replay_candidate
                        else None
                    ),
                    "unsafe_to_train_reason": (
                        None
                        if classification != "STALE_MASKED"
                        else "STALE_FEATURE_FAMILY"
                    ),
                    "source_lineage": {
                        "durable_feature_snapshot_archive": True,
                        "feature_snapshot_id": snapshot.get("snapshot_id"),
                        "content_sha256": snapshot.get("content_sha256"),
                        "candle_source_key": candle_key,
                    },
                }
            )
            example = TrainingExample(
                symbol=symbol,
                timeframe=timeframe,
                tensor=tensor,
                label_action_index=self._label_action(float(replay_row["future_return_after_cost_bps"])),
                label_expected_move_after_cost_bps=float(replay_row["future_return_after_cost_bps"]),
                payload_keys=tuple((payloads.get("_keys") or {}).values()),
                row_classification=classification,
                trust_row=trust_row,
            )
            if classification == "STALE_MASKED":
                rejections["stale_masked"] = rejections.get("stale_masked", 0) + 1
                continue
            if classification == "MISSING_MASKED":
                rejections["missing_masked_accepted_for_replay"] = (
                    rejections.get("missing_masked_accepted_for_replay", 0) + 1
                )
            sample = classify_training_sample(trust_row)
            sample_reject_reasons = [str(x) for x in (sample.get("reject_reasons") or [])]
            # Replay-lane mask policy (see constant docstring above): a sample
            # rejected SOLELY for missing-schema families trains with its
            # missing_mask; any other rejection reason still stands.
            only_missing_family = bool(sample_reject_reasons) and all(
                reason == "MISSING_CRITICAL_FEATURE_FAMILY" for reason in sample_reject_reasons
            )
            if sample.get("accepted_for_training") is not True or sample_reject_reasons:
                if not only_missing_family:
                    for reason in sample_reject_reasons or ["sample_not_accepted"]:
                        rejections[f"sample:{reason}"] = rejections.get(f"sample:{reason}", 0) + 1
                    continue
                trust_row["safe_to_train_with_missing_mask"] = True
                trust_row["unsafe_to_train_reason"] = None
                trust_row["accepted_for_training"] = True
                trust_row["valid_for_training"] = True
                trust_row["reject_reasons"] = []
                rejections["sample_missing_family_accepted_for_replay"] = (
                    rejections.get("sample_missing_family_accepted_for_replay", 0) + 1
                )
            examples.append(example)
        self._write_trusted_replay_cursor(
            consumed_offset,
            frontier_reached=frontier_reached,
            backfill=backfill,
            epoch_wrapped=epoch_wrapped,
        )
        scan_status = {
            "cursor_offset": consumed_offset,
            "snapshots_scanned": scanned,
            "examples_built": len(examples),
            "frontier_reached": frontier_reached,
            "embargo_seconds": TRUSTED_REPLAY_LABEL_EMBARGO_SECONDS,
            "rejection_reasons": dict(sorted(rejections.items(), key=lambda kv: -kv[1])[:15]),
        }
        if backfill:
            scan_status["backfill_lane"] = True
            scan_status["backfill_stop_offset"] = backfill_stop_offset
            scan_status["epoch_wrapped"] = epoch_wrapped
            self.last_trusted_replay_backfill_scan = scan_status
        else:
            self.last_trusted_replay_scan = scan_status
        return examples

    def _closed_trade_snapshot_training_examples(self) -> list[TrainingExample]:
        examples: list[TrainingExample] = []
        for source_key, usable in (
            (TRAINER_FEEDBACK_OUTCOMES_KEY, _trainer_feedback_row_usable),
            (TRAINER_FEEDBACK_COUNTERFACTUALS_KEY, _counterfactual_trainer_feedback_row_usable),
            (
                TRAINER_FEEDBACK_PAPER_EXPLORATION_MATERIALIZATION_KEY,
                _paper_exploration_materialization_feedback_row_usable,
            ),
        ):
            payload = self._get(source_key)
            if not isinstance(payload, list):
                continue
            cache_enabled = _closed_trade_example_cache_enabled()
            for row in payload:
                if not isinstance(row, Mapping) or not usable(row):
                    continue
                row_with_source = dict(row)
                row_with_source.setdefault("trainer_feedback_source_key", source_key)
                if cache_enabled:
                    key = _closed_trade_example_cache_key(row_with_source)
                    with _CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
                        cached = _CLOSED_TRADE_EXAMPLE_CACHE.get(key)
                        if cached is not None:
                            _CLOSED_TRADE_EXAMPLE_CACHE.move_to_end(key)
                            _CLOSED_TRADE_EXAMPLE_CACHE_STATS["hits"] += 1
                    if cached is not None:
                        examples.append(cached)
                        continue
                example = self._closed_trade_snapshot_training_example(row_with_source)
                if example is not None:
                    examples.append(example)
                    if cache_enabled:
                        with _CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
                            _CLOSED_TRADE_EXAMPLE_CACHE[key] = example
                            _CLOSED_TRADE_EXAMPLE_CACHE.move_to_end(key)
                            _CLOSED_TRADE_EXAMPLE_CACHE_STATS["misses"] += 1
                            while len(_CLOSED_TRADE_EXAMPLE_CACHE) > _CLOSED_TRADE_EXAMPLE_CACHE_CAP:
                                _CLOSED_TRADE_EXAMPLE_CACHE.popitem(last=False)
        return examples

    def _closed_trade_feature_snapshot(
        self,
        *,
        row: Mapping[str, Any],
        feature_snapshot_id: Any,
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        snapshot_key = f"v2:features:snapshot:{feature_snapshot_id}"
        snapshot = self._get(snapshot_key)
        if isinstance(snapshot, Mapping):
            return snapshot, snapshot_key
        for field in ("entry_feature_snapshot", "feature_snapshot"):
            embedded = row.get(field)
            if not isinstance(embedded, Mapping):
                continue
            embedded_id = embedded.get("feature_snapshot_id") or embedded.get("snapshot_id")
            if embedded_id in (None, "") or str(embedded_id) != str(feature_snapshot_id):
                continue
            features = embedded.get("features") if isinstance(embedded.get("features"), Mapping) else {}
            if not features:
                continue
            return embedded, f"trainer_feedback.{field}"
        try:
            archived = load_durable_feature_snapshot(
                feature_snapshot_id,
                root=self.trusted_replay_archive_root,
            )
        except SnapshotArchiveError:
            archived = None
        if isinstance(archived, Mapping):
            features = archived.get("features") if isinstance(archived.get("features"), Mapping) else {}
            archived_id = archived.get("feature_snapshot_id") or archived.get("snapshot_id")
            if features and str(archived_id or feature_snapshot_id) == str(feature_snapshot_id):
                return archived, f"durable_feature_snapshot_archive:{feature_snapshot_id}"
        return None, None

    def _closed_trade_snapshot_training_example(self, row: Mapping[str, Any]) -> TrainingExample | None:
        feature_snapshot_id = row.get("entry_feature_snapshot_id") or row.get("feature_snapshot_id")
        if feature_snapshot_id in (None, ""):
            return None
        snapshot, snapshot_source = self._closed_trade_feature_snapshot(
            row=row,
            feature_snapshot_id=feature_snapshot_id,
        )
        if not isinstance(snapshot, Mapping):
            return None
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if not symbol or not timeframe:
            return None
        snapshot_payload_id = snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id")
        if snapshot_payload_id and str(snapshot_payload_id) != str(feature_snapshot_id):
            return None
        if str(snapshot.get("symbol") or "").upper() not in {"", symbol}:
            return None
        if str(snapshot.get("timeframe") or "") not in {"", timeframe}:
            return None
        decision_time = _parse_trust_time(row.get("decision_time"))
        snapshot_available_at = _parse_trust_time(snapshot.get("available_at") or snapshot.get("generated_utc") or snapshot.get("generated_at"))
        snapshot_feature_cutoff = _parse_trust_time(snapshot.get("feature_cutoff") or snapshot.get("source_available_time"))
        if decision_time is None:
            return None
        if snapshot_available_at is not None and snapshot_available_at > decision_time:
            return None
        if snapshot_feature_cutoff is not None and snapshot_feature_cutoff > decision_time:
            return None
        features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
        if not features:
            return None
        payloads = self._payloads_from_feature_snapshot(snapshot=snapshot, features=features, feedback_row=row)
        tensor = self.tensor_builder.build(symbol=symbol, timeframe=timeframe, payloads=payloads)
        if tensor.data_coverage_percent < 20.0:
            return None
        targets = self._outcome_targets_from_row(row)
        directional_value = self._directional_label_bps_from_outcome(row)
        action = self._label_action(directional_value)
        snapshot_lineage = _reconcile_lineage_with_row(_snapshot_decision_time_lineage(snapshot), row)
        classification = _classification_from_lineage(tensor=tensor, lineage=snapshot_lineage)
        lineage_fields = _lineage_trust_fields(tensor=tensor, lineage=snapshot_lineage)
        missing_feature_names = list(lineage_fields["missing_feature_names"])
        stale_feature_names = list(lineage_fields["stale_feature_names"])
        optional_missing_masked = classification == "MISSING_MASKED" and _missing_names_are_optional_or_event_dependent(
            missing_feature_names
        )
        trainer_consumable = classification == "TRAINABLE" or optional_missing_masked
        feature_cutoff = row.get("feature_cutoff") or snapshot.get("feature_cutoff") or snapshot.get("source_event_time_est")
        available_at = row.get("available_at") or snapshot.get("available_at") or snapshot.get("source_available_time")
        candle_close_time = row.get("candle_close_time") or snapshot.get("candle_close_time") or feature_cutoff
        candle_open_time = row.get("candle_open_time") or snapshot.get("candle_open_time")
        source_event_time = row.get("source_event_time") or row.get("source_event_time_est") or snapshot.get(
            "source_event_time_est"
        ) or feature_cutoff
        source_received_time = row.get("source_received_time_est") or snapshot.get("source_received_time_est") or available_at
        trust_row = dict(row)
        trust_row.update(
            {
                "trust_schema_version": row.get("trust_schema_version") or TRUST_SCHEMA_VERSION,
                "learning_mode": "outcome_supervised",
                "update_lane": "OUTCOME_SUPERVISED_CLOSED_TRADE",
                "outcome_targets": targets,
                "realized_after_cost_reward": targets["realized_after_cost_reward"],
                "value_baseline": targets["value_baseline"],
                "advantage": targets["advantage"],
                "advantage_source": "realized_after_cost_reward_minus_value_baseline",
                "realized_reward_source": "realized_net_pnl_bps_after_cost",
                "uses_expected_move_as_realized_reward": False,
                "selected_action": targets["selected_action"],
                "directional_outcome": targets["directional_outcome"],
                "trade_outcome": targets["trade_outcome"],
                "action_was_profitable": targets["action_was_profitable"],
                "accepted_for_training": trainer_consumable,
                "valid_for_training": trainer_consumable,
                "market_state_integrity_score": row.get("market_state_integrity_score"),
                "reject_reasons": [],
                "row_classification": classification,
                "trainer_consumable": trainer_consumable,
                **lineage_fields,
                "features": dict(features),
                "feature_cutoff": feature_cutoff,
                "decision_cutoff": row.get("decision_cutoff") or row.get("decision_time"),
                "decision_time_est": row.get("decision_time_est") or row.get("decision_time"),
                "decision_cutoff_time_est": row.get("decision_cutoff_time_est") or row.get("decision_time"),
                "available_at": available_at,
                "source_available_time": row.get("source_available_time") or available_at,
                "source_event_time": source_event_time,
                "source_event_time_est": source_event_time,
                "source_received_time_est": source_received_time,
                "generated_at": row.get("generated_at") or row.get("decision_time") or snapshot.get("generated_at"),
                "generated_utc": row.get("generated_utc") or row.get("decision_time") or snapshot.get("generated_utc"),
                "feature_freshness_state": row.get("feature_freshness_state")
                or snapshot.get("feature_freshness_state")
                or "CURRENT",
                "candle_closed_confirmed": row.get("candle_closed_confirmed")
                if row.get("candle_closed_confirmed") is not None
                else snapshot.get("candle_closed_confirmed"),
                "closed_candle": row.get("closed_candle")
                if row.get("closed_candle") is not None
                else snapshot.get("closed_candle") or snapshot.get("candle_closed_confirmed"),
                "candle_open_time": candle_open_time,
                "candle_close_time": candle_close_time,
                "latency_ms": snapshot.get("latency_ms")
                if snapshot.get("latency_ms") is not None
                else row.get("cost_evidence_freshness_ms"),
                "mtf_snapshot_valid": row.get("mtf_snapshot_valid")
                if row.get("mtf_snapshot_valid") is not None
                else bool(row.get("mtf_snapshot_id")),
                "mtf_snapshot_reject_reasons": row.get("mtf_snapshot_reject_reasons") or [],
                "replay_snapshot_id": row.get("replay_snapshot_id")
                or row.get("decision_id")
                or f"closed_trade:{feature_snapshot_id}",
                "replay_snapshot_key": row.get("replay_snapshot_key")
                or f"{row.get('trainer_feedback_source_key') or TRAINER_FEEDBACK_OUTCOMES_KEY}:{row.get('trainer_feedback_id')}",
                "masa_feature_cutoff": row.get("masa_feature_cutoff") or feature_cutoff,
                "ppo_feature_cutoff": row.get("ppo_feature_cutoff") or feature_cutoff,
                "source_lineage": {
                    "trainer_feedback_id": row.get("trainer_feedback_id"),
                    "entry_prediction_id": row.get("entry_prediction_id") or row.get("prediction_id"),
                    "entry_feature_snapshot_id": feature_snapshot_id,
                    "feature_snapshot_key": snapshot_source or f"v2:features:snapshot:{feature_snapshot_id}",
                    "snapshot_backed_closed_trade_feedback": True,
                },
                "snapshot_backed_closed_trade_feedback": True,
            }
        )
        return TrainingExample(
            symbol=symbol,
            timeframe=timeframe,
            tensor=tensor,
            label_action_index=action,
            label_expected_move_after_cost_bps=directional_value,
            payload_keys=(
                f"{row.get('trainer_feedback_source_key') or TRAINER_FEEDBACK_OUTCOMES_KEY}:{row.get('trainer_feedback_id')}",
                f"v2:features:snapshot:{feature_snapshot_id}",
            ),
            row_classification=classification,
            trust_row=trust_row,
        )

    @staticmethod
    def _payloads_from_feature_snapshot(
        *,
        snapshot: Mapping[str, Any],
        features: Mapping[str, Any],
        feedback_row: Mapping[str, Any],
    ) -> dict[str, Any]:
        price = next(
            (
                value
                for value in (
                    features.get("last_price"),
                    features.get("price_last"),
                    features.get("close"),
                    features.get("ohlcv_close"),
                )
                if value not in (None, "")
            ),
            None,
        )
        ohlcv_payload = {
            **dict(features),
            "closed_candle": snapshot.get("closed_candle") if "closed_candle" in snapshot else snapshot.get("candle_closed_confirmed"),
            "is_closed": snapshot.get("is_closed") if "is_closed" in snapshot else snapshot.get("candle_closed_confirmed"),
            "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
        }
        provider_feature_context = snapshot.get("provider_feature_context")
        if not isinstance(provider_feature_context, Mapping):
            provider_feature_context = features.get("provider_feature_context")
        provider_features = snapshot.get("provider_features")
        if not isinstance(provider_features, Mapping):
            provider_features = features.get("provider_features")
        return {
            "features_latest": snapshot,
            "ohlcv": ohlcv_payload,
            "features_ta": {"indicators": dict(features)},
            "features_ta_full": {"features": dict(features)},
            "technical_analysis": {"indicators": dict(features)},
            "prices": {
                "price": price,
                "last": price,
                "last_price": price,
                "ticker_24hr": {
                    "lastPrice": price,
                    "quoteVolume": features.get("quote_volume"),
                },
                "funding": {
                    "markPrice": features.get("mark_price"),
                    "indexPrice": features.get("index_price"),
                },
                "basis_pct": features.get("basis_pct"),
            },
            "funding": dict(features),
            "open_interest": dict(features),
            "open_interest_hist": dict(features),
            "long_short": dict(features),
            "orderbook": dict(features),
            "microstructure": dict(features),
            "liquidation_levels": dict(features),
            "liquidity_zones": dict(features),
            "fvg": dict(features),
            "market_structure": dict(features),
            "structure": dict(features),
            "sweep_risk": dict(features),
            "vwap_features": dict(features),
            "volume_profile": dict(features),
            "cvd_features": dict(features),
            "trade_tape": dict(features),
            "trade_tape_features": dict(features),
            "advanced_trade_tape": dict(features),
            "microstructure_trust": dict(features),
            "coinank_open_interest": dict(features),
            "coinank_funding": dict(features),
            "coinank_long_short": dict(features),
            "coinank_liquidations": dict(features),
            "coinank_market_order_flow": dict(features),
            "liquidations": dict(features),
            "liquidations_agg": dict(features),
            "symbol_score": dict(features),
            "public_intel": dict(features),
            "aicoin": dict(features),
            "whale_walls": dict(features),
            "santiment": dict(features),
            "lunarcrush": dict(features),
            "nansen": dict(features),
            "moralis_features": {"features": dict(features)},
            "smart_money_signals": {"features": dict(features)},
            "altdata_confluence": {"features": dict(features)},
            "paper_positions": {},
            "risk_decisions": {},
            "orchestrator_decisions": {},
            "prediction": dict(feedback_row),
            "trainer_feedback_outcomes": [dict(feedback_row)],
            "paper_outcome_labels": [],
            "provider_feature_context": provider_feature_context if isinstance(provider_feature_context, Mapping) else {},
            "provider_features": provider_features if isinstance(provider_features, Mapping) else {},
        }

    def _label_expected_move_after_cost(
        self,
        *,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
    ) -> float:
        outcome_move = self._label_from_closed_trade_outcome(payloads=payloads, tensor=tensor)
        if outcome_move is not None:
            return outcome_move
        latest = payloads.get("features_latest")
        existing_prediction = payloads.get("prediction")
        for payload in (existing_prediction, latest, payloads.get("unified_features")):
            if isinstance(payload, Mapping):
                val = payload.get("expected_move_after_cost_bps")
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
        values = dict(zip(tensor.feature_names, tensor.values))
        ema_12 = values.get("ema_12", 0.0)
        ema_26 = values.get("ema_26", 0.0)
        rsi = values.get("rsi_14", 50.0)
        macd = values.get("macd", 0.0)
        macd_signal = values.get("macd_signal", 0.0)
        spread_signal = (ema_12 - ema_26) * 0.35
        rsi_signal = (rsi - 50.0) * 0.18
        macd_signal_bps = (macd - macd_signal) * 4.0
        return float(max(-80.0, min(80.0, spread_signal + rsi_signal + macd_signal_bps)))

    def _label_from_closed_trade_outcome(
        self,
        *,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
    ) -> float | None:
        row = self._matched_closed_trade_outcome(payloads=payloads, tensor=tensor)
        if row is None:
            return None
        value = self._directional_label_bps_from_outcome(row)
        return float(max(-250.0, min(250.0, value)))

    def _matched_closed_trade_outcome(
        self,
        *,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
    ) -> Mapping[str, Any] | None:
        candidates: list[Mapping[str, Any]] = []
        for key in ("trainer_feedback_outcomes", "paper_outcome_labels"):
            payload = payloads.get(key)
            rows: list[Mapping[str, Any]] = []
            if isinstance(payload, list):
                rows.extend(row for row in payload if isinstance(row, Mapping))
            elif isinstance(payload, Mapping):
                payload_rows = payload.get("outcome_labels") or payload.get("rows")
                if isinstance(payload_rows, list):
                    rows.extend(row for row in payload_rows if isinstance(row, Mapping))
                else:
                    rows.append(payload)
            if key == "trainer_feedback_outcomes":
                rows = [row for row in rows if _trainer_feedback_row_usable(row)]
            if key == "paper_outcome_labels":
                rows = [row for row in rows if _paper_outcome_label_row_usable(row)]
            candidates.extend(rows)
        matched: list[Mapping[str, Any]] = []
        for row in candidates:
            if str(row.get("symbol") or "").upper() != tensor.symbol.upper():
                continue
            timeframe = row.get("timeframe")
            if timeframe and str(timeframe) != tensor.timeframe:
                continue
            if not row.get("entry_prediction_id") and not row.get("entry_feature_snapshot_id"):
                continue
            if not row.get("exit_time"):
                continue
            value = row.get("realized_pnl_bps")
            try:
                float(value)
            except (TypeError, ValueError):
                continue
            matched.append(row)
        if not matched:
            return None
        matched.sort(key=lambda row: str(row.get("exit_time") or ""))
        return matched[-1]

    @staticmethod
    def _directional_label_bps_from_outcome(row: Mapping[str, Any]) -> float:
        value = float(row.get("realized_net_pnl_bps") or row.get("realized_pnl_bps") or 0.0)
        directional = str(row.get("directional_outcome") or "").strip().upper()
        if directional == "UP":
            return abs(value)
        if directional == "DOWN":
            return -abs(value)
        if directional == "FLAT":
            return 0.0
        # realized_pnl_bps is position PnL, not price direction. For SHORT
        # trades, positive PnL means price moved down, so invert the sign.
        action = str(row.get("selected_action") or row.get("action") or row.get("side") or "").strip().lower()
        if action == "short":
            value = -value
        return float(value)

    @staticmethod
    def _outcome_targets_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
        realized_bps = float(row.get("realized_net_pnl_bps") or row.get("realized_pnl_bps") or 0.0)
        realized_usd = float(row.get("realized_net_pnl_usd") or row.get("realized_pnl_usd") or row.get("realized_pnl") or 0.0)
        selected_action = str(row.get("selected_action") or row.get("action") or row.get("side") or "").strip().lower()
        directional = str(row.get("directional_outcome") or "").strip().upper()
        if not directional:
            directional_value = V2HybridTrainerDataLoader._directional_label_bps_from_outcome(row)
            directional = "UP" if directional_value > 0.0 else "DOWN" if directional_value < 0.0 else "FLAT"
        trade_outcome = str(row.get("trade_outcome") or "").strip().upper()
        if trade_outcome not in {"WIN", "LOSS", "BREAKEVEN"}:
            trade_outcome = "WIN" if realized_usd > 0.0 else "LOSS" if realized_usd < 0.0 else "BREAKEVEN"
        value_baseline = float(row.get("value_baseline") or row.get("policy_value") or row.get("old_value") or 0.0)
        realized_reward = realized_bps / 100.0
        return {
            "realized_net_pnl_bps": realized_bps,
            "realized_net_pnl_usd": realized_usd,
            "directional_outcome": directional,
            "trade_outcome": trade_outcome,
            "selected_action": selected_action,
            "action_was_profitable": bool(
                row.get("action_was_profitable")
                if row.get("action_was_profitable") is not None
                else realized_usd > 0.0
            ),
            "holding_period": row.get("holding_period") or row.get("hold_time_seconds"),
            "fees": row.get("fees"),
            "slippage": row.get("slippage"),
            "funding": row.get("funding"),
            "MFE": row.get("MFE") if row.get("MFE") is not None else row.get("mfe_bps"),
            "MAE": row.get("MAE") if row.get("MAE") is not None else row.get("mae_bps"),
            "exit_reason": row.get("exit_reason") or row.get("close_reason"),
            "realized_after_cost_reward": realized_reward,
            "value_baseline": value_baseline,
            "advantage": realized_reward - value_baseline,
        }

    @staticmethod
    def _label_action(expected_move_after_cost_bps: float) -> int:
        if expected_move_after_cost_bps >= 4.0:
            return 1
        if expected_move_after_cost_bps <= -4.0:
            return 2
        return 0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows
