"""V2-owned data loader for the hybrid trainer."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.durable_paper_evidence_archive import (
    COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    DurablePaperEvidenceArchive,
)
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
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mArchiveError,
    DurableCanonical5mLabelArchive,
    default_archive_path as default_canonical_5m_label_archive_path,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    default_archive_root,
    iter_snapshots_from_offset,
    load_snapshot as load_durable_feature_snapshot,
    verify_record as verify_durable_feature_snapshot,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    HORIZON_SECONDS,
    build_trusted_replay_row,
    target_action_index,
)
from v2.backend.app.services.ordinary_paper_admission import (
    build_microstructure_trust_evidence,
)

from .on_policy_behavior import BEHAVIOR_POLICY_LINEAGE_FIELDS
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
# (cost fields, cross-asset/regime families, orderbook features).
# For TRAINING the tensor carries an explicit missing_mask the model
# conditions on — absence is information, not corruption — and the label is
# PIT-protected by the replay builder independently of missing inputs.
# MISSING_MASKED replay rows are therefore accepted (and counted), while
# STALE_MASKED rows (wrong values, not absent ones) remain rejected. The
# global integrity optional-token list is intentionally NOT changed — live
# decision rows still require current-schema evidence.
TRAINER_FEEDBACK_OUTCOMES_KEY = "v2:trainer:feedback:outcomes"
TRAINER_FEEDBACK_COUNTERFACTUALS_KEY = "v2:trainer:feedback:counterfactuals"
TRAINER_FEEDBACK_PAPER_EXPLORATION_MATERIALIZATION_KEY = (
    "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
)
CANONICAL_REPO_ROOT = Path(__file__).resolve().parents[6]

# The trainer is re-executed as a fresh process every cycle, so an in-process
# integrity-proof cache is always cold and each cycle paid one full O(archive)
# verification of the ~1.3 GB label archive. The proof is durable evidence about
# an append-only archive, so it is persisted beside the archive and re-validated
# on load: `integrity_proof_is_current` when nothing was appended, otherwise
# `extend_integrity_proof`, which rebinds the immutable prefix and streams every
# new row/receipt. A rejected or unreadable proof falls back to the full proof,
# so this can only ever save work, never grant unverified trust.
_LABEL_ARCHIVE_PROOF_CACHE_SUFFIX = ".integrity_proof_cache.json"
# The archive's own directory is write-protected for some runtimes, so the proof
# cache falls back to a writable trainer-owned directory. The file name is keyed
# by the archive path, and the proof is re-validated against the archive on load
# either way, so location never affects trust.
_LABEL_ARCHIVE_PROOF_CACHE_FALLBACK_DIR = (
    CANONICAL_REPO_ROOT / "claude_worklog" / "trainer_atlas" / "integrity_proof_cache"
)


def _label_archive_proof_cache_paths(archive_path: Path) -> tuple[Path, ...]:
    digest = hashlib.sha256(str(archive_path).encode("utf-8")).hexdigest()[:32]
    return (
        Path(str(archive_path) + _LABEL_ARCHIVE_PROOF_CACHE_SUFFIX),
        _LABEL_ARCHIVE_PROOF_CACHE_FALLBACK_DIR / f"{digest}{_LABEL_ARCHIVE_PROOF_CACHE_SUFFIX}",
    )


def _load_persisted_label_archive_proof(archive_path: Path) -> dict[str, Any] | None:
    """Load a previously persisted full proof, or None when unusable."""
    for path in _label_archive_proof_cache_paths(archive_path):
        try:
            raw = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        # Bind the proof to this exact archive; a proof for another file is useless.
        if str(raw.get("archive_path") or "") != str(archive_path):
            continue
        if raw.get("archive_integrity_verified") is not True:
            continue
        return raw
    return None


def _persist_label_archive_proof(archive_path: Path, proof: Mapping[str, Any]) -> None:
    """Persist a verified proof atomically; failure is never fatal."""
    if proof.get("archive_integrity_verified") is not True:
        return
    payload = json.dumps(dict(proof), sort_keys=True, default=str)
    for path in _label_archive_proof_cache_paths(archive_path):
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(payload, "utf-8")
            os.replace(temporary, path)
            return
        except (OSError, TypeError, ValueError):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

DEFAULT_COUNTERFACTUAL_ARCHIVE_PATH = (
    CANONICAL_REPO_ROOT
    / ".local_data/v2_edge_replay_factory/counterfactual_evidence.sqlite3"
)
# Resource-control bound only.  This is not a market gate or training label
# threshold.  Redis JSON strings larger than this are never GET/parsing inputs;
# the verified durable archive must serve those rows instead.
TRAINER_FEEDBACK_REDIS_JSON_MAX_BYTES = 64 * 1024 * 1024
CLOSED_TRADE_DEFAULT_MAX_ROWS = TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE

# ── Closed-trade example memo cache ─────────────────────────────────────────
# The resident runtime rebuilds a fresh loader instance every cycle, and the
# fresh-training lane rebuilt ALL closed-trade feedback examples each cycle --
# ~12k counterfactual rows, each costing one Redis feature-snapshot GET plus a
# tensor build. That synchronous rebuild (data_loader_time_ms ~48s) starved the
# GPU (it idled while CPU/IO prepped the same immutable historical rows over and
# over). Closed-trade feedback rows + their feature snapshots are append-mostly
# and immutable-by-id only after the snapshot is verified against the durable
# archive. Memoize by feedback content, resolved archive root, and verified
# snapshot content identity across loader instances (module-level,
# lock-guarded).
# Warm cycles then rebuild only new/changed rows, collapsing the fresh load to
# well under a second. Successful examples only are cached; a row that yields no
# example (e.g. a snapshot not yet archived) is left uncached so a later-arriving
# snapshot is still picked up. Bounded LRU; kill-switch via env for safety.
_CLOSED_TRADE_EXAMPLE_CACHE: OrderedDict[str, Any] = OrderedDict()
_CLOSED_TRADE_EXAMPLE_CACHE_LOCK = threading.Lock()
_CLOSED_TRADE_EXAMPLE_CACHE_CAP = 65536
_CLOSED_TRADE_EXAMPLE_CACHE_STATS = {"hits": 0, "misses": 0}


def _closed_trade_example_cache_enabled() -> bool:
    return (
        os.getenv("V2_TRAINER_CLOSED_TRADE_EXAMPLE_CACHE", "1").strip().lower()
        not in {"0", "false", "no", "off"}
    )


def _closed_trade_example_cache_key(
    row: Mapping[str, Any],
    *,
    archive_root: Path,
    snapshot_content_sha256: str,
) -> str:
    """Bind memoized examples to the immutable snapshot namespace and bytes."""

    material = {
        "archive_root": str(Path(archive_root).resolve(strict=False)),
        "snapshot_content_sha256": str(snapshot_content_sha256),
        "feedback_row": dict(row),
    }
    try:
        blob = json.dumps(
            material,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        blob = repr(material)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _valid_sha256(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def _expected_feature_snapshot_content_sha256(
    row: Mapping[str, Any],
) -> str | None:
    """Return one immutable anchor, rejecting invalid or conflicting claims."""

    candidates: list[Any] = [
        row.get("durable_feature_snapshot_archive_content_sha256"),
        row.get("feature_snapshot_content_sha256"),
        row.get("entry_feature_snapshot_content_sha256"),
    ]
    source_hashes = row.get("source_hashes")
    if isinstance(source_hashes, Mapping):
        candidates.extend(
            (
                source_hashes.get("durable_feature_snapshot_archive_content_sha256"),
                source_hashes.get("feature_snapshot_content_sha256"),
            )
        )
    provided = [candidate for candidate in candidates if candidate not in (None, "")]
    normalized = {_valid_sha256(candidate) for candidate in provided}
    if not provided or None in normalized or len(normalized) != 1:
        return None
    return next(iter(normalized))


def _feature_snapshot_content_hash_claim_present(row: Mapping[str, Any]) -> bool:
    direct_claim = any(
        row.get(field_name) not in (None, "")
        for field_name in (
            "durable_feature_snapshot_archive_content_sha256",
            "feature_snapshot_content_sha256",
            "entry_feature_snapshot_content_sha256",
        )
    )
    source_hashes = row.get("source_hashes")
    source_claim = isinstance(source_hashes, Mapping) and any(
        source_hashes.get(field_name) not in (None, "")
        for field_name in (
            "durable_feature_snapshot_archive_content_sha256",
            "feature_snapshot_content_sha256",
        )
    )
    return direct_claim or source_claim


def _mutable_snapshot_matches_immutable_proof(
    *,
    row: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    feature_snapshot_id: Any,
) -> bool:
    """Allow a mutable copy only when a durable content identity anchors it."""

    expected_hash = _expected_feature_snapshot_content_sha256(row)
    observed_hash = _valid_sha256(snapshot.get("content_sha256"))
    if expected_hash is None or observed_hash != expected_hash:
        return False
    if verify_durable_feature_snapshot(snapshot):
        return False
    observed_id = snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id")
    return str(observed_id or "") == str(feature_snapshot_id)


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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _resolve_training_observed_at(value: datetime | str | None) -> datetime:
    """Resolve one aware cutoff for an entire loader invocation."""

    if value is None:
        return datetime.now(tz=timezone.utc)
    parsed = _parse_iso_utc(value)
    if parsed is None:
        raise ValueError("training_observed_at_must_be_aware_utc")
    return parsed


def _training_example_observed_by(
    example: "TrainingExample",
    *,
    training_observed_at: datetime,
) -> bool:
    """Reject labels whose availability lies beyond the consumer's cutoff."""

    if example.label_timing_valid is not True:
        return False
    label_available_at = _parse_iso_utc(example.label_available_at)
    if (
        label_available_at is not None
        and label_available_at > training_observed_at
    ):
        return False
    trust_row = example.trust_row if isinstance(example.trust_row, Mapping) else {}
    for field_name in ("label_available_at", "outcome_available_at"):
        raw_value = trust_row.get(field_name)
        if raw_value not in (None, "") and _parse_iso_utc(raw_value) is None:
            return False
    outcome_available_at_raw = trust_row.get("outcome_available_at")
    outcome_available_at = _parse_iso_utc(outcome_available_at_raw)
    return not (
        outcome_available_at_raw not in (None, "")
        and outcome_available_at is not None
        and outcome_available_at > training_observed_at
    )


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
    # Resolved once from the decision contract at construction time. Temporal
    # training must never infer chronology from loader/input order.
    decision_time: str | None = None
    # Time at which the realized/counterfactual label was fully knowable.  This
    # is resolved once, alongside decision_time, so a later mutation of the
    # source trust row cannot silently change a purged validation boundary.
    label_available_at: str | None = None
    label_timing_source: str | None = field(default=None, init=False)
    label_timing_valid: bool = field(default=False, init=False)
    label_timing_error: str | None = field(default=None, init=False)
    # Entry-time action sampled by the behavior policy. These are distinct from
    # hindsight/supervised labels and are frozen with the example so PPO cannot
    # silently follow a later-mutated trust row.
    behavior_action_index: int | None = None
    behavior_action: str | None = None

    def __post_init__(self) -> None:
        raw_decision_time: Any = self.decision_time
        if raw_decision_time in (None, "") and isinstance(self.trust_row, Mapping):
            for field in (
                "decision_time",
                "decision_time_est",
                "decision_cutoff_time_est",
                "decision_cutoff",
            ):
                candidate = self.trust_row.get(field)
                if candidate not in (None, ""):
                    raw_decision_time = candidate
                    break
        parsed = _parse_trust_time(raw_decision_time)
        canonical = (
            parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
            if parsed is not None
            else None
        )
        object.__setattr__(self, "decision_time", canonical)

        timing_candidates: list[tuple[datetime, str]] = []
        invalid_timing_sources: list[str] = []

        def add_timestamp(value: Any, source: str) -> None:
            if value in (None, ""):
                return
            parsed_timestamp = _parse_trust_time(value)
            if parsed_timestamp is None:
                invalid_timing_sources.append(source)
                return
            timing_candidates.append((parsed_timestamp, source))

        add_timestamp(self.label_available_at, "example.label_available_at")
        trust_targets: Mapping[str, Any] = {}
        if isinstance(self.trust_row, Mapping):
            for field_name in (
                "label_available_at",
                "outcome_available_at",
                "exit_time",
                "exit_price_utc",
                "closed_at",
            ):
                add_timestamp(
                    self.trust_row.get(field_name),
                    f"trust_row.{field_name}",
                )
            raw_targets = self.trust_row.get("outcome_targets")
            if isinstance(raw_targets, Mapping):
                trust_targets = raw_targets
                for field_name in (
                    "label_available_at",
                    "outcome_available_at",
                    "exit_time",
                    "exit_price_utc",
                    "closed_at",
                ):
                    add_timestamp(
                        raw_targets.get(field_name),
                        f"outcome_targets.{field_name}",
                    )

        duration_values: list[tuple[Any, str]] = []
        if isinstance(self.trust_row, Mapping):
            for field_name in (
                "label_horizon_seconds",
                "outcome_horizon_seconds",
                "holding_period",
                "holding_period_seconds",
                "hold_time_seconds",
            ):
                value = self.trust_row.get(field_name)
                if value not in (None, ""):
                    duration_values.append((value, f"trust_row.{field_name}"))
        for field_name in (
            "label_horizon_seconds",
            "outcome_horizon_seconds",
            "holding_period",
            "holding_period_seconds",
            "hold_time_seconds",
        ):
            value = trust_targets.get(field_name)
            if value not in (None, ""):
                duration_values.append((value, f"outcome_targets.{field_name}"))

        if parsed is not None:
            for raw_duration, source in duration_values:
                if isinstance(raw_duration, bool):
                    invalid_timing_sources.append(source)
                    continue
                try:
                    duration_seconds = float(raw_duration)
                except (TypeError, ValueError, OverflowError):
                    invalid_timing_sources.append(source)
                    continue
                if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
                    invalid_timing_sources.append(source)
                    continue
                timing_candidates.append(
                    (parsed + timedelta(seconds=duration_seconds), source)
                )

        label_timing_error: str | None = None
        label_available_at: str | None = None
        label_timing_source: str | None = None
        if parsed is None:
            label_timing_error = "DECISION_TIME_INVALID"
        elif invalid_timing_sources:
            label_timing_error = (
                "LABEL_TIMING_INVALID:" + ",".join(sorted(set(invalid_timing_sources)))
            )
        elif not timing_candidates:
            label_timing_error = "LABEL_TIMING_MISSING"
        else:
            label_time, label_timing_source = max(
                timing_candidates,
                key=lambda item: item[0],
            )
            if label_time <= parsed:
                label_timing_error = "LABEL_AVAILABLE_AT_NOT_AFTER_DECISION_TIME"
                label_timing_source = None
            else:
                label_available_at = label_time.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                )

        object.__setattr__(self, "label_available_at", label_available_at)
        object.__setattr__(self, "label_timing_source", label_timing_source)
        object.__setattr__(self, "label_timing_valid", label_timing_error is None)
        object.__setattr__(self, "label_timing_error", label_timing_error)

        raw_behavior_index: Any = self.behavior_action_index
        raw_behavior_action: Any = self.behavior_action
        if isinstance(self.trust_row, Mapping):
            if raw_behavior_index is None:
                raw_behavior_index = self.trust_row.get("behavior_action_index")
            if raw_behavior_index is None:
                # Backward-compatible source alias, but never a supervised
                # label_action_index fallback.
                raw_behavior_index = self.trust_row.get("selected_action_index")
            if raw_behavior_action in (None, ""):
                raw_behavior_action = self.trust_row.get("behavior_action")
            if raw_behavior_action in (None, ""):
                raw_behavior_action = self.trust_row.get("selected_action")

        parsed_behavior_index: int | None = None
        if not isinstance(raw_behavior_index, bool):
            try:
                candidate_index = int(raw_behavior_index)
            except (TypeError, ValueError, OverflowError):
                candidate_index = None
            if candidate_index is not None:
                try:
                    exactly_integral = float(raw_behavior_index) == float(candidate_index)
                except (TypeError, ValueError, OverflowError):
                    exactly_integral = False
                if exactly_integral:
                    parsed_behavior_index = candidate_index
        normalized_behavior_action = str(raw_behavior_action or "").strip().lower() or None
        object.__setattr__(self, "behavior_action_index", parsed_behavior_index)
        object.__setattr__(self, "behavior_action", normalized_behavior_action)


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

PRODUCER_TRAINER_CONSUMABLE_REJECTION_REASON = (
    "PRODUCER_TRAINER_CONSUMABLE_NOT_LITERAL_TRUE"
)


def _producer_trainer_consumable_evidence(
    snapshot: Any,
) -> dict[str, Any]:
    producer_snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    claim_present = "trainer_consumable" in producer_snapshot
    claim = producer_snapshot.get("trainer_consumable")
    literal_true = bool(
        claim_present and type(claim) is bool and claim is True
    )
    return {
        "producer_trainer_consumable_claim_present": claim_present,
        "producer_trainer_consumable_claim": claim,
        "producer_trainer_consumable_literal_true": literal_true,
    }


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


# A critical family counts as present at decision time when ANY of its
# representatives carried a value.  The representatives include both the full
# 446-slot training-ABI names AND the names the leaner serving ABI
# (SERVING_ABI_V2_PAPER_*) actually captures for the same family — e.g. the
# serving snapshot records the orderbook top-of-book as ``spread_bps`` and the
# funding regime as ``expected_funding_bps``.  These are genuine decision-time
# features from the same data sources (no lookahead), so a serving-ABI snapshot
# that carries them has the family present, not absent (operator directive
# 2026-08-01: a family whose signal is genuinely present must never block
# training as "critical family absent").
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
        "spread_bps",
    ),
    "funding_open_interest": (
        "funding_rate",
        "open_interest",
        "oi_change_pct",
        "basis_pct",
        "mark_price",
        "expected_funding_bps",
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
    vector_lengths = {
        len(tensor.values),
        len(tensor.missing_mask),
        len(tensor.stale_mask),
        len(tensor.source_availability),
        len(tensor.source_availability_vector),
        len(tensor.feature_names),
        len(tensor.source_labels),
    }
    if len(vector_lengths) != 1 or not tensor.values:
        return "NO_VERIFIABLE_OBSERVED_FEATURE_EVIDENCE"
    usable_observation = False
    for value, missing, stale, available in zip(
        tensor.values,
        tensor.missing_mask,
        tensor.stale_mask,
        tensor.source_availability,
    ):
        if isinstance(value, bool):
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            missing == 0
            and stale == 0
            and available == 1
            and math.isfinite(numeric_value)
        ):
            usable_observation = True
            break
    if not usable_observation and lineage is None:
        return "NO_VERIFIABLE_OBSERVED_FEATURE_EVIDENCE"
    if lineage is not None:
        # An archived snapshot cannot always re-derive live-only payloads into a
        # rebuilt tensor, so the tensor masks can read all-missing even when the
        # authenticated decision-time lineage recorded genuine observed features.
        # Per this function's own contract, integrity must reflect what was
        # observed AT DECISION TIME, not what can be re-derived from the archive.
        # When the lossy rebuild yields no usable slot, fall back to the
        # authenticated lineage: require a recorded source-availability vector
        # AND at least one feature that was NOT missing at decision time.  This
        # trusts the same authenticated producer record already relied on for
        # ``trainer_consumable`` — it does not manufacture evidence.
        if not usable_observation:
            source_availability = lineage.get("source_availability")
            source_recorded = (
                isinstance(source_availability, (Mapping, list, tuple))
                and len(source_availability) > 0
            )
            observed_present = (
                len(tensor.feature_names)
                - int(lineage.get("missing_feature_count") or 0)
            ) > 0
            if not (source_recorded and observed_present):
                return "NO_VERIFIABLE_OBSERVED_FEATURE_EVIDENCE"
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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
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
    for field_name in (
        "quarantine_reason",
        "invalid_admission_quarantine_reason",
        "paper_admission_quarantine_reason",
    ):
        value = row.get(field_name)
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


def _feedback_trust_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field_name in REQUIRED_TRUST_ENVELOPE_FIELDS:
        value = row.get(field_name)
        if value in (None, "") or (
            field_name == "source_hashes"
            and (not isinstance(value, Mapping) or not value)
        ):
            reasons.append(f"MISSING_TRUST_{field_name.upper()}")
    decision_time = _parse_trust_time(row.get("decision_time"))
    available_at = _parse_trust_time(row.get("available_at"))
    feature_cutoff = _parse_trust_time(row.get("feature_cutoff"))
    for field_name, parsed in (
        ("DECISION_TIME", decision_time),
        ("AVAILABLE_AT", available_at),
        ("FEATURE_CUTOFF", feature_cutoff),
    ):
        if row.get(field_name.lower()) not in (None, "") and parsed is None:
            reasons.append(f"{field_name}_UNPARSEABLE")
    for field_name in ("label_available_at", "outcome_available_at"):
        raw_value = row.get(field_name)
        if raw_value not in (None, "") and _parse_trust_time(raw_value) is None:
            reasons.append(f"{field_name.upper()}_UNPARSEABLE")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    return reasons


def _extra_contract_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("mtf_snapshot_id") is None:
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    if row.get("mtf_snapshot_valid") is not True:
        reasons.append("MTF_SNAPSHOT_INVALID")
    for reason in row.get("mtf_snapshot_reject_reasons") or []:
        reasons.append(f"MTF_SNAPSHOT:{reason}")
    clock_values = {
        "FEATURE_CUTOFF": row.get("feature_cutoff"),
        "AVAILABLE_AT": row.get("available_at"),
        "DECISION_TIME": row.get("decision_time"),
    }
    parsed_clocks = {
        field_name: _parse_trust_time(raw_value)
        for field_name, raw_value in clock_values.items()
    }
    for field_name, raw_value in clock_values.items():
        if raw_value in (None, ""):
            reasons.append(f"{field_name}_MISSING")
        elif parsed_clocks[field_name] is None:
            reasons.append(f"{field_name}_UNPARSEABLE")
    feature_cutoff = parsed_clocks["FEATURE_CUTOFF"]
    available_at = parsed_clocks["AVAILABLE_AT"]
    decision_time = parsed_clocks["DECISION_TIME"]
    if (
        feature_cutoff is not None
        and decision_time is not None
        and feature_cutoff > decision_time
    ):
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if (
        available_at is not None
        and decision_time is not None
        and available_at > decision_time
    ):
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")

    masa_cutoff_raw = row.get("masa_feature_cutoff")
    ppo_cutoff_raw = row.get("ppo_feature_cutoff")
    masa_cutoff = _parse_trust_time(masa_cutoff_raw)
    ppo_cutoff = _parse_trust_time(ppo_cutoff_raw)
    if masa_cutoff_raw not in (None, "") and masa_cutoff is None:
        reasons.append("MASA_FEATURE_CUTOFF_UNPARSEABLE")
    if ppo_cutoff_raw not in (None, "") and ppo_cutoff is None:
        reasons.append("PPO_FEATURE_CUTOFF_UNPARSEABLE")
    if (
        masa_cutoff is not None
        and decision_time is not None
        and masa_cutoff > decision_time
    ):
        reasons.append("MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME")
    if (
        ppo_cutoff is not None
        and decision_time is not None
        and ppo_cutoff > decision_time
    ):
        reasons.append("PPO_FEATURE_CUTOFF_AFTER_DECISION_TIME")
    for field_name in ("label_available_at", "outcome_available_at"):
        raw_value = row.get(field_name)
        if raw_value not in (None, "") and _parse_trust_time(raw_value) is None:
            reasons.append(f"{field_name.upper()}_UNPARSEABLE")
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
    if row.get("producer_trainer_consumable_literal_true") is not True:
        return False
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
        counterfactual_archive_path: Path | None = None,
        canonical_5m_label_archive_path: Path | None = None,
    ) -> None:
        self.io = io or V2OnlyJsonIO(client=None)
        self.tensor_builder = tensor_builder or V2UnifiedFeatureTensorBuilder()
        self.replay_bundle_paths = tuple(Path(p) for p in replay_bundle_paths)
        self.trusted_replay_archive_root = trusted_replay_archive_root or default_archive_root()
        self.counterfactual_archive_path = Path(
            counterfactual_archive_path or DEFAULT_COUNTERFACTUAL_ARCHIVE_PATH
        )
        self.canonical_5m_label_archive_path = Path(
            canonical_5m_label_archive_path
            or default_canonical_5m_label_archive_path()
        )
        self.last_trusted_replay_scan: dict[str, Any] = {}
        self.last_trusted_replay_backfill_scan: dict[str, Any] = {}
        self.last_prediction_grid_load: dict[str, Any] = {}
        self.last_closed_trade_load: dict[str, Any] = {}
        self._canonical_5m_label_archive_integrity_proof: (
            dict[str, Any] | None
        ) = None
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

    def _verified_counterfactual_archive_rows(
        self,
        *,
        limit: int,
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        """Read a bounded archive tail after the producer-owned full proof."""

        bounded_limit = max(0, int(limit))
        status: dict[str, Any] = {
            "source_key": TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
            "durable_archive_path": str(self.counterfactual_archive_path),
            "durable_archive_stream_id": COUNTERFACTUAL_ARCHIVE_STREAM_ID,
            "requested_rows": bounded_limit,
            "archive_rows_loaded": 0,
            "archive_integrity_verified": False,
            "archive_migration_complete": False,
            "archive_replacement_readiness_verified": False,
        }
        if bounded_limit == 0:
            status["status"] = "BOUNDED_ZERO_ROWS_REQUESTED"
            return [], status
        if not self.counterfactual_archive_path.is_file():
            status["status"] = "DURABLE_ARCHIVE_MISSING"
            return None, status
        try:
            archive = DurablePaperEvidenceArchive(
                self.counterfactual_archive_path,
                stream_id=COUNTERFACTUAL_ARCHIVE_STREAM_ID,
            )
            rows, readiness = archive.verified_latest_rows(
                source_key=TRAINER_FEEDBACK_COUNTERFACTUALS_KEY,
                limit=bounded_limit,
            )
            status.update(
                {
                    "archive_integrity_verified": readiness.get(
                        "archive_integrity_verified"
                    )
                    is True,
                    "archive_replacement_readiness_verified": readiness.get(
                        "readiness_verified"
                    )
                    is True,
                    "archive_migration_complete": readiness.get(
                        "readiness_verified"
                    )
                    is True,
                    "archive_migration_proof": (
                        "PRODUCER_VERIFIED_REPLACEMENT_READINESS_V1"
                        if readiness.get("readiness_verified") is True
                        else None
                    ),
                    "archive_total_unique_rows": readiness.get(
                        "archive_total_unique_rows"
                    ),
                    "archive_total_occurrences": readiness.get(
                        "archive_total_occurrences"
                    ),
                    "archive_chain_sha256": readiness.get(
                        "archive_chain_sha256"
                    ),
                    "archive_readiness_schema_version": readiness.get(
                        "schema_version"
                    ),
                    "archive_readiness_rejection_reasons": list(
                        readiness.get("rejection_reasons") or []
                    ),
                    "archive_verification_cost": readiness.get(
                        "verification_cost"
                    ),
                    "archive_verification_memory_bound": readiness.get(
                        "verification_memory_bound"
                    ),
                    "archive_bounded_rows_snapshot_compare_verified": (
                        readiness.get(
                            "bounded_rows_snapshot_compare_verified"
                        )
                        is True
                    ),
                }
            )
            if readiness.get("readiness_verified") is not True:
                status["status"] = (
                    "DURABLE_ARCHIVE_REPLACEMENT_READINESS_UNPROVEN"
                )
                return None, status
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            status["status"] = "DURABLE_ARCHIVE_VERIFICATION_FAILED"
            status["rejection_reason"] = type(exc).__name__
            status["rejection_detail"] = str(exc)[:240]
            return None, status
        status["status"] = "DURABLE_ARCHIVE_READY_BOUNDED_ROWS"
        status["archive_rows_loaded"] = len(rows)
        return rows, status

    def _bounded_redis_feedback_rows(
        self,
        *,
        source_key: str,
        limit: int,
    ) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
        """Read one Redis JSON working set only after an exact byte-size gate."""

        bounded_limit = max(0, int(limit))
        status: dict[str, Any] = {
            "source_key": source_key,
            "requested_rows": bounded_limit,
            "redis_json_max_bytes": TRAINER_FEEDBACK_REDIS_JSON_MAX_BYTES,
            "redis_payload_bytes": None,
            "rows_loaded": 0,
        }
        if bounded_limit == 0:
            status["status"] = "BOUNDED_ZERO_ROWS_REQUESTED"
            return [], status
        client = getattr(self.io, "client", None)
        if client is not None:
            strlen = getattr(client, "strlen", None)
            if not callable(strlen):
                status["status"] = "REDIS_STRING_LENGTH_CAPABILITY_MISSING"
                return [], status
            try:
                payload_bytes = int(strlen(source_key))
            except Exception as exc:  # noqa: BLE001
                status["status"] = "REDIS_STRING_LENGTH_READ_FAILED"
                status["rejection_reason"] = type(exc).__name__
                return [], status
            status["redis_payload_bytes"] = payload_bytes
            if payload_bytes > TRAINER_FEEDBACK_REDIS_JSON_MAX_BYTES:
                status["status"] = "REDIS_JSON_OVERSIZED_SKIPPED_FAIL_CLOSED"
                return [], status
        payload = self._get(source_key)
        rows: list[Mapping[str, Any]] = []
        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, Mapping)]
        elif isinstance(payload, Mapping):
            nested = (
                payload.get("rows")
                or payload.get("outcomes")
                or payload.get("outcome_labels")
            )
            if isinstance(nested, list):
                rows = [row for row in nested if isinstance(row, Mapping)]
        rows = rows[-bounded_limit:]
        status["status"] = "BOUNDED_REDIS_JSON_ROWS_LOADED"
        status["rows_loaded"] = len(rows)
        return rows, status

    def _bounded_feedback_rows(
        self,
        *,
        source_key: str,
        limit: int,
    ) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
        if source_key != TRAINER_FEEDBACK_COUNTERFACTUALS_KEY:
            return self._bounded_redis_feedback_rows(
                source_key=source_key,
                limit=limit,
            )
        archive_rows, archive_status = (
            self._verified_counterfactual_archive_rows(limit=limit)
        )
        if archive_rows is not None:
            return archive_rows, archive_status
        if archive_status.get("status") != "DURABLE_ARCHIVE_MISSING":
            return [], {
                "source_key": source_key,
                "status": (
                    "COUNTERFACTUAL_ARCHIVE_EXISTS_BUT_UNREADY_FAIL_CLOSED:"
                    f"{archive_status.get('status')}"
                ),
                "archive_status": archive_status,
                "archive_fallback_used": False,
                "redis_fallback_suppressed": True,
                "redis_read_attempted": False,
            }
        redis_rows, redis_status = self._bounded_redis_feedback_rows(
            source_key=source_key,
            limit=limit,
        )
        combined = {
            **redis_status,
            "archive_status": archive_status,
            "archive_fallback_used": bool(redis_rows),
            "redis_fallback_suppressed": False,
            "redis_read_attempted": True,
        }
        if not redis_rows:
            combined["status"] = (
                "COUNTERFACTUAL_SOURCE_UNAVAILABLE_FAIL_CLOSED:"
                f"{archive_status.get('status')}:{redis_status.get('status')}"
            )
        return redis_rows, combined

    def _get_exact_json_with_ttl(self, key: str) -> tuple[dict[str, Any] | None, int | None]:
        """Atomically re-read one expiring source and its remaining TTL.

        This bypasses the request cache deliberately: an ordinary PAPER source
        envelope is only valid when the exact bytes used by the tensor still
        exist under the canonical Redis key at evidence-construction time.
        """

        assert_v2_key(key)
        client = getattr(self.io, "client", None)
        audit = getattr(self.io, "audit", None)
        if audit is not None:
            audit.reads_attempted += 1
        if client is None:
            if audit is not None:
                audit.reads_missing += 1
            return None, None
        try:
            pipe = client.pipeline(transaction=True)
            pipe.get(key)
            pipe.ttl(key)
            raw, raw_ttl = pipe.execute()
        except Exception as exc:  # noqa: BLE001
            if audit is not None:
                audit.errors.append(
                    f"exact_get_ttl_failed:{key}:{type(exc).__name__}"
                )
            return None, None
        if raw is None:
            if audit is not None:
                audit.reads_missing += 1
            return None, int(raw_ttl) if isinstance(raw_ttl, int) else None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                if audit is not None:
                    audit.errors.append(f"json_decode_failed:{key}")
                return None, int(raw_ttl) if isinstance(raw_ttl, int) else None
        payload = dict(raw) if isinstance(raw, Mapping) else None
        ttl = int(raw_ttl) if isinstance(raw_ttl, int) and not isinstance(raw_ttl, bool) else None
        return payload, ttl

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
        """Read only the canonical finalized OHLCV surface.

        ``v2:market:ohlcv:binance:*`` is a legacy compatibility surface.  Its
        rows do not carry the exact canonical identity and availability
        contract required by trainer decisions.  It must therefore neither
        replace a canonical row on timestamp collision nor stand in for a
        missing canonical window.
        """

        closed_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
        closed_payload = self._get(closed_key)
        if isinstance(closed_payload, list) and closed_payload:
            closed_rows = self._closed_candle_series_from_raw(
                closed_payload,
                symbol=symbol,
                timeframe=timeframe,
            )
            return closed_rows, closed_key
        return closed_payload, closed_key

    def _read_trusted_replay_label_candles(
        self,
        *,
        symbol: str,
    ) -> tuple[Any, str]:
        """Read only the canonical finalized 5m label source.

        The legacy compatibility key can contain raw rows whose historical
        ingestion/availability clocks are not preserved.  It is suitable for
        compatibility features, not exact outcome labels, so replay never
        falls back to it.
        """

        key = f"v2:market:ohlcv_closed:binance:{str(symbol).upper()}:5m"
        return self._get(key), key

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
        public_intel, public_intel_key = self._get_first(
            f"v2:altdata:public_intel:symbol:{symbol}",
            f"v2:altdata:public_intel:{symbol}",
        )
        whale_walls, whale_walls_key = self._get_first(
            f"v2:altdata:whale_walls:symbol:{symbol}",
            f"v2:altdata:whale_walls:{symbol}",
        )
        payloads.update(
            {
                "public_intel": public_intel,
                "whale_walls": whale_walls,
            }
        )
        keys.update(
            {
                "public_intel": public_intel_key,
                "whale_walls": whale_walls_key,
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
            f"v2:altdata:whale_walls:symbol:{symbol}",
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
            f"v2:altdata:confluence:{symbol}:{timeframe}",
            f"v2:microstructure:feed_quality:binance:{symbol}",
            f"v2:microstructure:feed_quality:kucoin:{symbol}",
            f"v2:microstructure:adversarial_features:binance:{symbol}",
            f"v2:microstructure:adversarial_features:kucoin:{symbol}",
            f"v2:microstructure:trade_tape_confirmation:{symbol}",
            f"v2:microstructure:cross_venue_confirmation:{symbol}",
            f"v2:microstructure:sweep_risk:{symbol}:{timeframe}",
            f"v2:market:microstructure:{symbol}",
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
            "whale_walls": f"v2:altdata:whale_walls:symbol:{symbol}",
            "paper_positions": "v2:paper:positions",
            "risk_decisions": "v2:risk:decisions",
            "orchestrator_decisions": "v2:orchestrator:decisions",
            # Parity with the full payload map (build_example slow path) for
            # independently clocked, non-provider compatibility sources. Legacy
            # Moralis namespaces remain absent until an authenticated resolver
            # and postcommit receipt verifier exist at this consumer boundary.
            "microstructure_trust": f"v2:microstructure:trust_score:{symbol}:{timeframe}",
            "cascade_context": f"v2:microstructure:cascade_context:{symbol}:{timeframe}",
            "ta_full_htf_1h": f"v2:features:ta_full:{symbol}:1h",
            "altdata_confluence": f"v2:altdata:confluence:{symbol}:{timeframe}",
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
                        "behavior_action_sampling_mode",
                        "behavior_distribution_contract",
                        "strategy_supply_hypothesis",
                        *BEHAVIOR_POLICY_LINEAGE_FIELDS,
                    )
                    if outcome_row.get(field) not in (None, "")
                }
            )
        if _has_explicit_training_trust_evidence(trust_row):
            trust_result = classify_training_sample(trust_row)
            trust_row["market_state_integrity_score"] = trust_result["market_state_integrity_score"]
            extra_reasons = _extra_contract_rejection_reasons(trust_row)
            if trust_row.get("producer_trainer_consumable_literal_true") is not True:
                extra_reasons.append(
                    PRODUCER_TRAINER_CONSUMABLE_REJECTION_REASON
                )
            trust_row["reject_reasons"] = sorted(set(list(trust_result["reject_reasons"]) + extra_reasons))
            trust_row["source_lineage"] = trust_result["source_lineage"]
            final_accepted = bool(
                trust_result["accepted_for_training"] is True
                and trust_result["valid_for_training"] is True
                and not trust_row["reject_reasons"]
            )
            trust_row["accepted_for_training"] = final_accepted
            trust_row["valid_for_training"] = final_accepted
            if not final_accepted:
                classification = "MARKET_STATE_REJECTED"
                trust_row["trainer_consumable"] = False
                trust_row["row_classification"] = classification
        else:
            classification = "MARKET_STATE_REJECTED"
            trust_row["accepted_for_training"] = False
            trust_row["valid_for_training"] = False
            trust_row["trainer_consumable"] = False
            trust_row["row_classification"] = classification
            trust_row["market_state_integrity_score"] = None
            trust_row["reject_reasons"] = sorted(
                {
                    "MISSING_EXPLICIT_TRAINING_TRUST_EVIDENCE",
                    *(
                        [PRODUCER_TRAINER_CONSUMABLE_REJECTION_REASON]
                        if trust_row.get(
                            "producer_trainer_consumable_literal_true"
                        )
                        is not True
                        else []
                    ),
                }
            )

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
        decision_time = prediction.get("decision_time") or latest.get("decision_time")
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
        source_keys = payloads.get("_keys")
        source_keys = source_keys if isinstance(source_keys, Mapping) else {}
        microstructure_source_key = str(
            source_keys.get("microstructure_trust") or ""
        )
        canonical_microstructure_source_key = (
            f"v2:microstructure:trust_score:{symbol}:{timeframe}"
        )
        microstructure_readback: dict[str, Any] | None = None
        microstructure_ttl: int | None = None
        if microstructure_source_key == canonical_microstructure_source_key:
            microstructure_readback, microstructure_ttl = (
                self._get_exact_json_with_ttl(microstructure_source_key)
            )
        microstructure_evidence = build_microstructure_trust_evidence(
            source_payload=(
                payloads.get("microstructure_trust")
                if isinstance(payloads.get("microstructure_trust"), Mapping)
                else None
            ),
            source_payload_readback=microstructure_readback,
            source_key=microstructure_source_key,
            source_observed_ttl_seconds=microstructure_ttl,
            tensor_id=tensor.tensor_id,
            feature_snapshot_id=tensor.feature_snapshot_id,
            tensor_source_lineage_hash=tensor.source_lineage_hash,
            tensor_decision_time=tensor.decision_time,
            symbol=symbol.upper(),
            timeframe=timeframe,
            tensor_temporal_rejection_reasons=tensor.temporal_rejection_reasons,
        )
        producer_trainer_consumable_evidence = (
            _producer_trainer_consumable_evidence(latest)
        )
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
            "feature_cutoff": prediction.get("feature_cutoff")
            or latest.get("feature_cutoff")
            or snapshot_feature_cutoff,
            "decision_time": decision_time,
            "available_at": prediction.get("available_at")
            or latest.get("available_at"),
            "latency_ms": latest.get("latency_ms"),
            "generated_at": latest.get("generated_at") or latest.get("generated_utc"),
            "feature_freshness_state": latest.get("feature_freshness_state"),
            # The consumer may narrow a producer's admission, but it must never
            # upgrade a missing, false, or loosely truthy producer claim.  Keep
            # the original claim beside the derived flag so the veto remains
            # auditable after tensor reconstruction.
            **producer_trainer_consumable_evidence,
            "trainer_consumable": (
                classification == "TRAINABLE"
                and producer_trainer_consumable_evidence[
                    "producer_trainer_consumable_literal_true"
                ]
            ),
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
            "decision_time_est": latest.get("decision_time_est"),
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
            "microstructure_trust_evidence": microstructure_evidence,
            "microstructure_trust_evidence_sha256": microstructure_evidence.get(
                "evidence_sha256"
            ),
            "microstructure_trust_evidence_rejection_reasons": list(
                microstructure_evidence.get("producer_rejection_reasons") or []
            ),
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
        training_observed_at: datetime | str | None = None,
    ) -> list[TrainingExample]:
        observation_cutoff = _resolve_training_observed_at(training_observed_at)
        examples: list[TrainingExample] = []
        bounded_limit = None if limit is None else max(0, int(limit))
        if bounded_limit == 0:
            return examples
        if trusted_only:
            closed_trade_limit = (
                CLOSED_TRADE_DEFAULT_MAX_ROWS
                if bounded_limit is None
                else bounded_limit
            )
            examples.extend(
                self._closed_trade_snapshot_training_examples(
                    limit=closed_trade_limit,
                    training_observed_at=observation_cutoff,
                )
            )
            if bounded_limit is not None and len(examples) >= bounded_limit:
                return examples[:bounded_limit]
            if closed_trade_only:
                return examples
        for symbol in symbols:
            for timeframe in timeframes:
                example = self.build_example(
                    symbol=symbol,
                    timeframe=timeframe,
                    snapshot_fast_path=snapshot_fast_path,
                )
                if trusted_only:
                    if not _example_trusted_for_training(example):
                        continue
                    if not _training_example_observed_by(
                        example,
                        training_observed_at=observation_cutoff,
                    ):
                        continue
                examples.append(example)
                if bounded_limit is not None and len(examples) >= bounded_limit:
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
        training_observed_at: datetime | str | None = None,
    ) -> list[TrainingExample]:
        """Stream frontier-labelable snapshots from an oldest-first cursor.

        Frontier labels come from the canonical finalized 5m Redis working
        set.  Historical ``backfill=True`` labels come only from a complete,
        content-verified range in the durable time-indexed 5m archive.  Both
        paths are bounded by one explicit ``training_observed_at`` and process
        snapshots one at a time.  Mutable Redis history and same-timeframe
        feature snapshots are never historical-label fallbacks.
        """
        historical_label_archive: DurableCanonical5mLabelArchive | None = None
        historical_archive_integrity: dict[str, Any] | None = None
        if backfill:
            blocked_status = {
                "backfill_lane": True,
                "examples_built": 0,
                "snapshots_scanned": 0,
                "cursor_advanced": False,
                "durable_canonical_5m_label_archive_path": str(
                    self.canonical_5m_label_archive_path
                ),
                "durable_canonical_5m_label_archive_integrity_verified": False,
                "same_timeframe_label_fallback_used": False,
                "mutable_redis_history_used_for_historical_labels": False,
            }
            if not self.canonical_5m_label_archive_path.is_file():
                blocked_status.update(
                    {
                        "status": (
                            "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"
                        ),
                        "durable_canonical_5m_label_archive_availability": (
                            "MISSING"
                        ),
                        "rejection_reasons": {
                            "DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED": 1,
                        },
                    }
                )
                self.last_trusted_replay_backfill_scan = blocked_status
                return []
            historical_label_archive = DurableCanonical5mLabelArchive(
                self.canonical_5m_label_archive_path
            )
            try:
                cached_integrity = (
                    self._canonical_5m_label_archive_integrity_proof
                )
                if cached_integrity is None:
                    # The trainer is re-executed as a fresh process every cycle,
                    # so an in-process cache alone is always cold and every cycle
                    # paid one full O(archive) proof. The proof is durable
                    # evidence, so it is persisted and re-validated below rather
                    # than recomputed from scratch.
                    cached_integrity = _load_persisted_label_archive_proof(
                        self.canonical_5m_label_archive_path
                    )
                if (
                    cached_integrity is not None
                    and historical_label_archive.integrity_proof_is_current(
                        cached_integrity
                    )
                ):
                    historical_archive_integrity = cached_integrity
                else:
                    # The 5m label archive is appended continuously by the live
                    # candle feed, so a cached proof stops being "current" almost
                    # immediately -- which previously forced a full O(archive)
                    # re-verification of ~1.3 GB on nearly every cycle and kept
                    # the trainer pinned to the CPU instead of the GPU.
                    # extend_integrity_proof rebinds the immutable prefix and
                    # streams/validates only the new suffix rows and receipts, so
                    # it is the same guarantee at append-sized cost. Any prefix
                    # or suffix rejection falls through to the full proof below.
                    historical_archive_integrity = None
                    if cached_integrity is not None:
                        try:
                            extended = historical_label_archive.extend_integrity_proof(
                                cached_integrity
                            )
                        except (Canonical5mArchiveError, sqlite3.Error, TypeError, ValueError):
                            extended = None
                        if (
                            isinstance(extended, Mapping)
                            and extended.get("archive_integrity_verified") is True
                        ):
                            historical_archive_integrity = dict(extended)
                    if historical_archive_integrity is None:
                        historical_archive_integrity = (
                            historical_label_archive.verify_integrity()
                        )
                    if historical_archive_integrity.get(
                        "archive_integrity_verified"
                    ) is True:
                        _persist_label_archive_proof(
                            self.canonical_5m_label_archive_path,
                            historical_archive_integrity,
                        )
                        self._canonical_5m_label_archive_integrity_proof = (
                            historical_archive_integrity
                        )
            except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                blocked_status.update(
                    {
                        "status": (
                            "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_"
                            "INTEGRITY_CHECK_FAILED"
                        ),
                        "archive_integrity_error": type(exc).__name__,
                        "rejection_reasons": {
                            "DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_"
                            "CHECK_FAILED": 1,
                        },
                    }
                )
                self.last_trusted_replay_backfill_scan = blocked_status
                return []
            if (
                historical_archive_integrity.get(
                    "archive_integrity_verified"
                )
                is not True
            ):
                archive_reasons = list(
                    historical_archive_integrity.get("rejection_reasons") or []
                )
                blocked_status.update(
                    {
                        "status": (
                            "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_"
                            "INTEGRITY_UNVERIFIED"
                        ),
                        "durable_canonical_5m_label_archive_integrity": (
                            historical_archive_integrity
                        ),
                        "rejection_reasons": {
                            str(reason): 1
                            for reason in archive_reasons
                        }
                        or {
                            "DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_"
                            "UNVERIFIED": 1,
                        },
                    }
                )
                self.last_trusted_replay_backfill_scan = blocked_status
                return []
        observation_cutoff = _resolve_training_observed_at(training_observed_at)
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
        embargo_cutoff = observation_cutoff - timedelta(
            seconds=TRUSTED_REPLAY_LABEL_EMBARGO_SECONDS
        )
        backfill_stop_offset: int | None = None
        epoch_wrapped = False
        cursor = self._read_trusted_replay_cursor(backfill=backfill)
        if cursor < 0:
            cursor = 0
        if backfill:
            frontier_cursor = self._read_trusted_replay_cursor()
            backfill_stop_offset = max(0, frontier_cursor) or None
            if backfill_stop_offset and cursor >= backfill_stop_offset:
                cursor = 0
                epoch_wrapped = True
        rejections: dict[str, int] = {}
        scanned = 0
        frontier_reached = False
        consumed_offset = cursor
        candle_cache: dict[str, tuple[Any, str]] = {}
        durable_label_ranges_verified = 0
        archive_coverage_retry_pending = False

        def _stream_labelable_snapshots() -> Iterable[tuple[int, dict[str, Any]]]:
            nonlocal scanned, frontier_reached
            for next_offset, snapshot in iter_snapshots_from_offset(
                self.trusted_replay_archive_root,
                start_offset=cursor,
            ):
                if scanned >= scan_limit:
                    break
                if limit is not None and len(examples) >= int(limit):
                    break
                if (
                    backfill_stop_offset is not None
                    and next_offset > backfill_stop_offset
                ):
                    frontier_reached = True
                    break
                decision_time = _parse_iso_utc(snapshot.get("decision_time"))
                if decision_time is not None and decision_time > embargo_cutoff:
                    frontier_reached = True
                    break
                scanned += 1
                yield next_offset, snapshot

        # The cursor advances only past snapshots whose build was attempted.
        for next_offset, snapshot in _stream_labelable_snapshots():
            symbol = str(snapshot.get("symbol") or "").upper()
            timeframe = str(snapshot.get("timeframe") or "")
            if not symbol or not timeframe:
                rejections["symbol_or_timeframe_missing"] = rejections.get("symbol_or_timeframe_missing", 0) + 1
                consumed_offset = next_offset
                continue
            producer_trainer_consumable_evidence = (
                _producer_trainer_consumable_evidence(snapshot)
            )
            if (
                producer_trainer_consumable_evidence[
                    "producer_trainer_consumable_literal_true"
                ]
                is not True
            ):
                rejections[
                    PRODUCER_TRAINER_CONSUMABLE_REJECTION_REASON
                ] = (
                    rejections.get(
                        PRODUCER_TRAINER_CONSUMABLE_REJECTION_REASON,
                        0,
                    )
                    + 1
                )
                consumed_offset = next_offset
                continue
            durable_label_path_proof: dict[str, Any] | None = None
            if backfill:
                assert historical_label_archive is not None
                decision_time = _parse_iso_utc(snapshot.get("decision_time"))
                if decision_time is None:
                    rejections["DECISION_TIME_MISSING_OR_INVALID"] = (
                        rejections.get(
                            "DECISION_TIME_MISSING_OR_INVALID",
                            0,
                        )
                        + 1
                    )
                    consumed_offset = next_offset
                    continue
                try:
                    candle_rows, durable_label_path_proof = (
                        historical_label_archive.verified_label_path(
                            symbol=symbol,
                            decision_time=decision_time,
                            training_observed_at=observation_cutoff,
                            horizon_seconds=HORIZON_SECONDS["4h"],
                            archive_integrity_proof=(
                                historical_archive_integrity
                            ),
                        )
                    )
                except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
                    reason = (
                        "DURABLE_CANONICAL_5M_LABEL_RANGE_READ_FAILED:"
                        f"{type(exc).__name__}"
                    )
                    rejections[reason] = rejections.get(reason, 0) + 1
                    archive_coverage_retry_pending = True
                    break
                if candle_rows is None:
                    for reason in (
                        durable_label_path_proof.get("rejection_reasons")
                        or ["DURABLE_CANONICAL_5M_LABEL_RANGE_UNVERIFIED"]
                    ):
                        rejections[str(reason)] = (
                            rejections.get(str(reason), 0) + 1
                        )
                    # Distinguish a PERMANENT interior coverage hole from a
                    # TRANSIENT not-yet-written tail using the archive's own
                    # coverage frontier for this symbol.  If the frontier is at
                    # or past this snapshot's 4h label-window end, the archive
                    # has progressed beyond the range yet a candle is still
                    # absent — a permanent hole (e.g. a canonical-5m WSS gap);
                    # SKIP it and advance so one gapped symbol can never halt the
                    # whole offline scan.  Otherwise the tail is still being
                    # written: PRESERVE the cursor and wait for coverage to fill
                    # (retryable).  Skipping never accepts an unverified label —
                    # it only excludes a permanently unlabelable row.
                    frontier_close_ms = (
                        historical_label_archive.symbol_latest_close_ms(symbol)
                    )
                    label_window_end_ms = int(
                        decision_time.timestamp() * 1000
                    ) + HORIZON_SECONDS["4h"] * 1000
                    if (
                        frontier_close_ms is not None
                        and frontier_close_ms >= label_window_end_ms
                    ):
                        consumed_offset = next_offset
                        continue
                    archive_coverage_retry_pending = True
                    break
                durable_label_ranges_verified += 1
                range_sha256 = str(
                    durable_label_path_proof.get("label_path_sha256") or ""
                )
                candle_key = (
                    "durable_canonical_5m_label_archive:"
                    f"{self.canonical_5m_label_archive_path}:"
                    f"{range_sha256}"
                )
            else:
                if symbol not in candle_cache:
                    candle_cache[symbol] = (
                        self._read_trusted_replay_label_candles(symbol=symbol)
                    )
                candles, candle_key = candle_cache[symbol]
                candle_rows = candles if isinstance(candles, list) else []
            consumed_offset = next_offset
            replay_row, reasons = build_trusted_replay_row(
                snapshot,
                candles=candle_rows,
                training_observed_at=observation_cutoff,
                label_candle_source_key=candle_key,
            )
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
            snapshot_lineage = _snapshot_decision_time_lineage(snapshot)
            classification = _classification_from_lineage(tensor=tensor, lineage=snapshot_lineage)
            if classification == "NO_VERIFIABLE_OBSERVED_FEATURE_EVIDENCE":
                reason = "no_verifiable_observed_feature_evidence"
                rejections[reason] = rejections.get(reason, 0) + 1
                continue
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
            schema_introduction_attested = bool(
                snapshot.get("feature_family_introduced_after_snapshot_time") is True
            )
            missing_names_optional_or_event = (
                _missing_names_are_optional_or_event_dependent(missing_feature_names)
                and not any(
                    str(name).lower().startswith("critical_family_absent:")
                    for name in missing_feature_names
                )
            )
            safe_missing_mask_replay_candidate = (
                classification == "MISSING_MASKED"
                and not stale_feature_names
                and missing_names_optional_or_event
                and snapshot_lineage is not None
                and schema_introduction_attested
            )
            trust_row = dict(replay_row)
            trust_row.update(_lineage_trust_fields(tensor=tensor, lineage=snapshot_lineage))
            trust_row.update(producer_trainer_consumable_evidence)
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
                    "feature_family_introduced_after_snapshot_time": (
                        schema_introduction_attested
                    ),
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
                        "durable_canonical_5m_label_archive": bool(backfill),
                        "durable_canonical_5m_label_path_sha256": (
                            durable_label_path_proof.get("label_path_sha256")
                            if durable_label_path_proof is not None
                            else None
                        ),
                    },
                }
            )
            # Offline PIT-safety envelope for the historical trusted-replay
            # (COUNTERFACTUAL) lane.  This row pairs a PIT feature snapshot with
            # a durably-finalized canonical outcome and NO execution occurred, so
            # the offline PIT audit's evidence lane, source clocks, model
            # provenance and finality are populated ONLY from the producer's own
            # genuine decision-time source clocks — never forged or inferred
            # beyond the closed-candle identities the producer already recorded.
            # The audit's clock-order rules pin these mappings: rules
            # source_available_at<=generated_at<=available_at fix generated_at to
            # the source-availability instant; event_time is the closed-candle
            # market event; MASA/PPO cutoffs equal the feature cutoff by
            # counterfactual construction (features up to the cutoff, decided at
            # decision_time).  Missing genuine source clocks stay absent so the
            # audit fail-closes that row rather than admitting an invented time.
            _cf_source_available_at = (
                snapshot.get("source_available_at")
                or trust_row.get("available_at")
            )
            _cf_feature_cutoff = (
                trust_row.get("feature_cutoff") or snapshot.get("feature_cutoff")
            )
            _cf_decision_time = (
                trust_row.get("decision_time") or snapshot.get("decision_time")
            )
            _cf_candle_close = (
                trust_row.get("candle_close_time") or _cf_feature_cutoff
            )
            trust_row.update(
                {
                    "training_evidence_lane": "COUNTERFACTUAL",
                    "execution_occurred": False,
                    "event_time": _cf_candle_close,
                    # source_available_at is the canonical max(candle_close,
                    # event_time, ingested_at); a closed candle is ingested and
                    # available at the same source instant, so ingested_at ==
                    # source_available_at keeps that identity exact.
                    "ingested_at": _cf_source_available_at,
                    "source_available_at": _cf_source_available_at,
                    "generated_at": _cf_source_available_at,
                    "available_at": _cf_source_available_at,
                    # The archived snapshot is a genuine serving prediction
                    # payload (source=trainer_prediction_payload, real
                    # model_version/checkpoint_id): the MASA/PPO model DID decide
                    # at decision_time using features up to feature_cutoff, so its
                    # provenance is declared present and the cutoffs equal the
                    # feature cutoff by construction.
                    "masa_provenance_present": True,
                    "ppo_provenance_present": True,
                    "masa_feature_cutoff": _cf_feature_cutoff,
                    "ppo_feature_cutoff": _cf_feature_cutoff,
                    "ppo_decision_time": _cf_decision_time,
                    "outcome_finalized": bool(backfill),
                    "label_finalized": bool(backfill),
                }
            )
            replay_label_action_index = target_action_index(
                replay_row.get("target_action")
            )
            if replay_label_action_index is None:
                rejections["target_action_invalid"] = (
                    rejections.get("target_action_invalid", 0) + 1
                )
                continue
            example = TrainingExample(
                symbol=symbol,
                timeframe=timeframe,
                tensor=tensor,
                label_action_index=replay_label_action_index,
                label_expected_move_after_cost_bps=float(replay_row["future_return_after_cost_bps"]),
                payload_keys=tuple((payloads.get("_keys") or {}).values()),
                row_classification=classification,
                trust_row=trust_row,
                label_available_at=str(replay_row["label_available_at"]),
            )
            if not _training_example_observed_by(
                example,
                training_observed_at=observation_cutoff,
            ):
                rejections["label_available_after_training_observed_at"] = (
                    rejections.get(
                        "label_available_after_training_observed_at",
                        0,
                    )
                    + 1
                )
                continue
            if classification == "STALE_MASKED":
                rejections["stale_masked"] = rejections.get("stale_masked", 0) + 1
                continue
            if classification == "MISSING_MASKED":
                if not safe_missing_mask_replay_candidate:
                    reason = (
                        "missing_mask_schema_introduction_unproven"
                        if missing_names_optional_or_event
                        else "missing_critical_feature_family"
                    )
                    rejections[reason] = rejections.get(reason, 0) + 1
                    continue
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
                if not only_missing_family or not safe_missing_mask_replay_candidate:
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
            "status": (
                "WAITING_FOR_DURABLE_CANONICAL_5M_LABEL_COVERAGE_RETRY"
                if backfill and archive_coverage_retry_pending
                else "VERIFIED_DURABLE_CANONICAL_5M_HISTORICAL_LABELS_LOADED"
                if backfill and examples
                else "DURABLE_CANONICAL_5M_HISTORICAL_LABELS_VERIFIED_NO_ROWS"
                if backfill
                else "CANONICAL_5M_REDIS_FRONTIER_SCAN_COMPLETE"
            ),
            "cursor_offset": consumed_offset,
            "snapshots_scanned": scanned,
            "examples_built": len(examples),
            "frontier_reached": frontier_reached,
            "embargo_seconds": TRUSTED_REPLAY_LABEL_EMBARGO_SECONDS,
            "streaming_snapshot_processing": True,
            "maximum_resident_snapshot_rows": 1,
            "canonical_5m_label_symbols_cached": len(candle_cache),
            "durable_canonical_5m_label_archive_path": (
                str(self.canonical_5m_label_archive_path)
                if backfill
                else None
            ),
            "durable_canonical_5m_label_archive_integrity_verified": (
                historical_archive_integrity is not None
                and historical_archive_integrity.get(
                    "archive_integrity_verified"
                )
                is True
            ),
            "durable_canonical_5m_label_archive_chain_sha256": (
                historical_archive_integrity.get("archive_chain_sha256")
                if historical_archive_integrity is not None
                else None
            ),
            "durable_canonical_5m_label_ranges_verified": (
                durable_label_ranges_verified
            ),
            "archive_coverage_retry_pending": archive_coverage_retry_pending,
            "cursor_preserved_for_retryable_archive_coverage": (
                archive_coverage_retry_pending
            ),
            "same_timeframe_label_fallback_used": False,
            "mutable_redis_history_used_for_historical_labels": False,
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

    def _closed_trade_snapshot_training_examples(
        self,
        *,
        limit: int = CLOSED_TRADE_DEFAULT_MAX_ROWS,
        training_observed_at: datetime | str | None = None,
    ) -> list[TrainingExample]:
        observation_cutoff = _resolve_training_observed_at(training_observed_at)
        bounded_limit = max(0, int(limit))
        examples: list[TrainingExample] = []
        source_statuses: list[dict[str, Any]] = []
        rejected_after_observation_cutoff = 0
        for source_key, usable in (
            (TRAINER_FEEDBACK_OUTCOMES_KEY, _trainer_feedback_row_usable),
            (TRAINER_FEEDBACK_COUNTERFACTUALS_KEY, _counterfactual_trainer_feedback_row_usable),
            (
                TRAINER_FEEDBACK_PAPER_EXPLORATION_MATERIALIZATION_KEY,
                _paper_exploration_materialization_feedback_row_usable,
            ),
        ):
            remaining = bounded_limit - len(examples)
            if remaining <= 0:
                break
            payload, source_status = self._bounded_feedback_rows(
                source_key=source_key,
                limit=remaining,
            )
            source_statuses.append(source_status)
            if not payload:
                continue
            cache_enabled = _closed_trade_example_cache_enabled()
            for row in payload:
                if len(examples) >= bounded_limit:
                    break
                if not isinstance(row, Mapping) or not usable(row):
                    continue
                row_with_source = dict(row)
                row_with_source.setdefault("trainer_feedback_source_key", source_key)
                feature_snapshot_id = row_with_source.get(
                    "entry_feature_snapshot_id"
                ) or row_with_source.get("feature_snapshot_id")
                if feature_snapshot_id in (None, ""):
                    continue
                cache_key: str | None = None
                # An immutable content claim is sufficient to address an
                # already-validated cached example.  Consult that cache before
                # reading a mutable Redis copy; the cached entry was inserted
                # only after byte-identity verification against this same hash.
                expected_snapshot_hash = (
                    _expected_feature_snapshot_content_sha256(row_with_source)
                )
                if cache_enabled and expected_snapshot_hash is not None:
                    cache_key = _closed_trade_example_cache_key(
                        row_with_source,
                        archive_root=Path(self.trusted_replay_archive_root),
                        snapshot_content_sha256=expected_snapshot_hash,
                    )
                    with _CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
                        cached = _CLOSED_TRADE_EXAMPLE_CACHE.get(cache_key)
                        if cached is not None:
                            _CLOSED_TRADE_EXAMPLE_CACHE.move_to_end(cache_key)
                            _CLOSED_TRADE_EXAMPLE_CACHE_STATS["hits"] += 1
                    if cached is not None:
                        if not _example_trusted_for_training(cached):
                            continue
                        if _training_example_observed_by(
                            cached,
                            training_observed_at=observation_cutoff,
                        ):
                            examples.append(cached)
                        else:
                            rejected_after_observation_cutoff += 1
                        continue
                snapshot, snapshot_source = self._closed_trade_feature_snapshot(
                    row=row_with_source,
                    feature_snapshot_id=feature_snapshot_id,
                )
                if not isinstance(snapshot, Mapping):
                    continue
                snapshot_content_sha256 = _valid_sha256(
                    snapshot.get("content_sha256")
                )
                if snapshot_content_sha256 is None:
                    continue
                if cache_enabled and cache_key is None:
                    cache_key = _closed_trade_example_cache_key(
                        row_with_source,
                        archive_root=Path(self.trusted_replay_archive_root),
                        snapshot_content_sha256=snapshot_content_sha256,
                    )
                    with _CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
                        cached = _CLOSED_TRADE_EXAMPLE_CACHE.get(cache_key)
                        if cached is not None:
                            _CLOSED_TRADE_EXAMPLE_CACHE.move_to_end(cache_key)
                            _CLOSED_TRADE_EXAMPLE_CACHE_STATS["hits"] += 1
                    if cached is not None:
                        if not _example_trusted_for_training(cached):
                            continue
                        if _training_example_observed_by(
                            cached,
                            training_observed_at=observation_cutoff,
                        ):
                            examples.append(cached)
                        else:
                            rejected_after_observation_cutoff += 1
                        continue
                example = self._closed_trade_snapshot_training_example(
                    row_with_source,
                    resolved_snapshot=snapshot,
                    resolved_snapshot_source=snapshot_source,
                )
                if example is not None:
                    if not _example_trusted_for_training(example):
                        continue
                    if not _training_example_observed_by(
                        example,
                        training_observed_at=observation_cutoff,
                    ):
                        rejected_after_observation_cutoff += 1
                        continue
                    examples.append(example)
                    if cache_enabled:
                        assert cache_key is not None
                        with _CLOSED_TRADE_EXAMPLE_CACHE_LOCK:
                            _CLOSED_TRADE_EXAMPLE_CACHE[cache_key] = example
                            _CLOSED_TRADE_EXAMPLE_CACHE.move_to_end(cache_key)
                            _CLOSED_TRADE_EXAMPLE_CACHE_STATS["misses"] += 1
                            while len(_CLOSED_TRADE_EXAMPLE_CACHE) > _CLOSED_TRADE_EXAMPLE_CACHE_CAP:
                                _CLOSED_TRADE_EXAMPLE_CACHE.popitem(last=False)
        self.last_closed_trade_load = {
            "status": (
                "BOUNDED_CLOSED_TRADE_ROWS_LOADED"
                if examples
                else "NO_BOUNDED_CLOSED_TRADE_ROWS_AVAILABLE"
            ),
            "requested_max_rows": bounded_limit,
            "examples_built": len(examples),
            "hard_row_bound_respected": len(examples) <= bounded_limit,
            "training_observed_at": observation_cutoff.isoformat().replace(
                "+00:00",
                "Z",
            ),
            "rows_rejected_after_training_observation_cutoff": (
                rejected_after_observation_cutoff
            ),
            "source_statuses": source_statuses,
        }
        return examples

    def _closed_trade_feature_snapshot(
        self,
        *,
        row: Mapping[str, Any],
        feature_snapshot_id: Any,
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        # The disk archive is immutable-by-content and therefore authoritative
        # for training. Redis and embedded payloads are mutable caches and may
        # only recover availability when a durable SHA-256 recorded on the
        # feedback row proves byte-for-byte equivalence.
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
            expected_hash = _expected_feature_snapshot_content_sha256(row)
            observed_hash = _valid_sha256(archived.get("content_sha256"))
            content_claim_matches = (
                not _feature_snapshot_content_hash_claim_present(row)
                or (
                    expected_hash is not None
                    and observed_hash == expected_hash
                )
            )
            if (
                features
                and str(archived_id or feature_snapshot_id)
                == str(feature_snapshot_id)
                and content_claim_matches
            ):
                return archived, f"durable_feature_snapshot_archive:{feature_snapshot_id}"

        if _expected_feature_snapshot_content_sha256(row) is None:
            return None, None
        snapshot_key = f"v2:features:snapshot:{feature_snapshot_id}"
        mutable_candidates: list[tuple[Mapping[str, Any], str]] = []
        snapshot = self._get(snapshot_key)
        if isinstance(snapshot, Mapping):
            mutable_candidates.append((snapshot, snapshot_key))
        for field_name in ("entry_feature_snapshot", "feature_snapshot"):
            embedded = row.get(field_name)
            if isinstance(embedded, Mapping):
                mutable_candidates.append(
                    (embedded, f"trainer_feedback.{field_name}")
                )
        for candidate, source in mutable_candidates:
            if _mutable_snapshot_matches_immutable_proof(
                row=row,
                snapshot=candidate,
                feature_snapshot_id=feature_snapshot_id,
            ):
                return candidate, f"verified_mutable_equivalent:{source}"
        return None, None

    def _closed_trade_snapshot_training_example(
        self,
        row: Mapping[str, Any],
        *,
        resolved_snapshot: Mapping[str, Any] | None = None,
        resolved_snapshot_source: str | None = None,
    ) -> TrainingExample | None:
        feature_snapshot_id = row.get("entry_feature_snapshot_id") or row.get("feature_snapshot_id")
        if feature_snapshot_id in (None, ""):
            return None
        snapshot = resolved_snapshot
        snapshot_source = resolved_snapshot_source
        if not isinstance(snapshot, Mapping):
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
        snapshot_available_at = _parse_trust_time(snapshot.get("available_at"))
        snapshot_feature_cutoff = _parse_trust_time(snapshot.get("feature_cutoff"))
        if (
            decision_time is None
            or snapshot_available_at is None
            or snapshot_feature_cutoff is None
        ):
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
        targets = self._outcome_targets_from_row(row)
        directional_value = self._directional_label_bps_from_outcome(row)
        action = self._label_action(directional_value)
        snapshot_lineage = _reconcile_lineage_with_row(_snapshot_decision_time_lineage(snapshot), row)
        classification = _classification_from_lineage(tensor=tensor, lineage=snapshot_lineage)
        if classification == "NO_VERIFIABLE_OBSERVED_FEATURE_EVIDENCE":
            return None
        producer_trainer_consumable_evidence = (
            _producer_trainer_consumable_evidence(snapshot)
        )
        producer_trainer_consumable_literal_true = (
            producer_trainer_consumable_evidence[
                "producer_trainer_consumable_literal_true"
            ]
            is True
        )
        producer_tensor_row_classification = classification
        if not producer_trainer_consumable_literal_true:
            classification = "MARKET_STATE_REJECTED"
        lineage_fields = _lineage_trust_fields(tensor=tensor, lineage=snapshot_lineage)
        missing_feature_names = list(lineage_fields["missing_feature_names"])
        optional_missing_masked = producer_tensor_row_classification == "MISSING_MASKED" and _missing_names_are_optional_or_event_dependent(
            missing_feature_names
        )
        trainer_consumable = bool(
            producer_trainer_consumable_literal_true
            and (
                producer_tensor_row_classification == "TRAINABLE"
                or optional_missing_masked
            )
        )
        feature_cutoff = row.get("feature_cutoff") or snapshot.get("feature_cutoff")
        available_at = row.get("available_at") or snapshot.get("available_at")
        effective_feature_cutoff = _parse_trust_time(feature_cutoff)
        effective_available_at = _parse_trust_time(available_at)
        if (
            effective_feature_cutoff is None
            or effective_available_at is None
            or effective_feature_cutoff > decision_time
            or effective_available_at > decision_time
        ):
            return None
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
                "reject_reasons": (
                    []
                    if producer_trainer_consumable_literal_true
                    else [PRODUCER_TRAINER_CONSUMABLE_REJECTION_REASON]
                ),
                "row_classification": classification,
                "trainer_consumable": trainer_consumable,
                "producer_tensor_row_classification": (
                    producer_tensor_row_classification
                ),
                **producer_trainer_consumable_evidence,
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
            "whale_walls": dict(features),
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
        nested_targets = (
            row.get("outcome_targets")
            if isinstance(row.get("outcome_targets"), Mapping)
            else {}
        )
        value_raw = row.get("realized_net_pnl_bps")
        if value_raw in (None, ""):
            value_raw = nested_targets.get("realized_net_pnl_bps")
        if value_raw in (None, ""):
            value_raw = row.get("realized_pnl_bps")
        value = float(0.0 if value_raw in (None, "") else value_raw)
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
        nested_targets = (
            row.get("outcome_targets")
            if isinstance(row.get("outcome_targets"), Mapping)
            else {}
        )
        realized_bps_raw = row.get("realized_net_pnl_bps")
        if realized_bps_raw in (None, ""):
            realized_bps_raw = nested_targets.get("realized_net_pnl_bps")
        if realized_bps_raw in (None, ""):
            realized_bps_raw = row.get("realized_pnl_bps")
        realized_usd_raw = row.get("realized_net_pnl_usd")
        if realized_usd_raw in (None, ""):
            realized_usd_raw = nested_targets.get("realized_net_pnl_usd")
        if realized_usd_raw in (None, ""):
            realized_usd_raw = row.get("realized_pnl_usd")
        if realized_usd_raw in (None, ""):
            realized_usd_raw = row.get("realized_pnl")
        realized_bps = float(
            0.0 if realized_bps_raw in (None, "") else realized_bps_raw
        )
        realized_usd = float(
            0.0 if realized_usd_raw in (None, "") else realized_usd_raw
        )
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
            "realized_gross_pnl_usd": row.get("realized_gross_pnl_usd"),
            "closed_entry_notional_usd": row.get("closed_entry_notional_usd"),
            "closed_exit_notional_usd": row.get("closed_exit_notional_usd"),
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
            "fees_usd": row.get("fees_usd"),
            "entry_fee_usd": row.get("entry_fee_usd"),
            "entry_fee_bps_per_side": row.get("entry_fee_bps_per_side"),
            "entry_fee_source": row.get("entry_fee_source"),
            "entry_fee_fallback": row.get("entry_fee_fallback"),
            "exit_fee_usd": row.get("exit_fee_usd"),
            "exit_fee_bps_per_side": row.get("exit_fee_bps_per_side"),
            "exit_fee_source": row.get("exit_fee_source"),
            "exit_fee_fallback": row.get("exit_fee_fallback"),
            "exit_fee_rate_basis": row.get("exit_fee_rate_basis"),
            "total_fees_usd": row.get("total_fees_usd"),
            "slippage": row.get("slippage"),
            "slippage_usd": row.get("slippage_usd"),
            "entry_slippage_usd": row.get("entry_slippage_usd"),
            "entry_slippage_bps_per_side": row.get(
                "entry_slippage_bps_per_side"
            ),
            "entry_slippage_source": row.get("entry_slippage_source"),
            "entry_slippage_fallback": row.get("entry_slippage_fallback"),
            "exit_slippage_usd": row.get("exit_slippage_usd"),
            "exit_slippage_bps_per_side": row.get(
                "exit_slippage_bps_per_side"
            ),
            "exit_slippage_source": row.get("exit_slippage_source"),
            "exit_slippage_available_at": row.get(
                "exit_slippage_available_at"
            ),
            "exit_slippage_fallback": row.get("exit_slippage_fallback"),
            "exit_slippage_provenance_status": row.get(
                "exit_slippage_provenance_status"
            ),
            "total_slippage_usd": row.get("total_slippage_usd"),
            "total_execution_costs_usd": row.get("total_execution_costs_usd"),
            "paper_round_trip_cost_accounting_version": row.get(
                "paper_round_trip_cost_accounting_version"
            ),
            "paper_cost_rate_scope": row.get("paper_cost_rate_scope"),
            "paper_net_pnl_formula": row.get("paper_net_pnl_formula"),
            "outcome_cost_unit": row.get("outcome_cost_unit"),
            "round_trip_cost_fallback_used": row.get(
                "round_trip_cost_fallback_used"
            ),
            "round_trip_cost_provenance_status": row.get(
                "round_trip_cost_provenance_status"
            ),
            "funding": row.get("funding"),
            "funding_usd": row.get("funding_usd"),
            "funding_pnl_usd": row.get("funding_pnl_usd"),
            "MFE": row.get("MFE") if row.get("MFE") is not None else row.get("mfe_bps"),
            "MAE": row.get("MAE") if row.get("MAE") is not None else row.get("mae_bps"),
            "exit_reason": row.get("exit_reason") or row.get("close_reason"),
            "realized_after_cost_reward": realized_reward,
            "value_baseline": value_baseline,
            "advantage": realized_reward - value_baseline,
        }

    @staticmethod
    def _label_action(expected_move_after_cost_bps: float) -> int:
        """Map an already cost-adjusted outcome without a market-static band.

        Zero is the mathematical break-even invariant.  Cost, spread, impact,
        and funding adaptation must happen before this function; adding a fixed
        bps dead-zone here would silently turn small realized directions into
        HOLD labels under every market regime.
        """
        if expected_move_after_cost_bps > 0.0:
            return 1
        if expected_move_after_cost_bps < 0.0:
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
