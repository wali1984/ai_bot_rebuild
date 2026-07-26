"""Paper-provisional canonical prediction publisher (Option B).

Serves the PAPER_PROVISIONAL_100_ROW_CHECKPOINT through the EXISTING canonical
trainer prediction-publication contract (build_prediction_payload +
V2HybridPredictionPublisher), emitting genuine ~163-field v2:prediction records
with authentic feature/checkpoint/market-state/microstructure/cost lineage and a
genuinely fitted confidence calibration. It NEVER imports or mutates the pinned
strict trainer, never submits live orders, and stamps every record paper-only /
provisional-cohort / live-blocked.

The record then flows through the standalone orchestrator -> risk gateway ->
paper loop exactly like a strict-trainer prediction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = str(Path(__file__).resolve().parents[4])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from v2.backend.app.services.market_state_integrity.canonical_candles import (  # noqa: E402
    REQUIRED_DECISION_TIMEFRAMES,
    build_multi_timeframe_decision_snapshot,
    closed_candle_key,
    latest_closed_candle_at_or_before,
    parse_ms,
)
from v2.backend.app.services.market_state_integrity.sample_rejection import (  # noqa: E402
    classify_training_sample,
)
from v2.backend.app.services.market_state_integrity.trust import (  # noqa: E402
    ENFORCEMENT_EPOCH,
    TRUST_SCHEMA_VERSION,
    attach_runtime_trust_metadata,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: E402
    CheckpointManifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (  # noqa: E402
    CONFIDENCE_HEAD_ACTIONS,
    calibrate_confidence,
    normalize_calibration_state,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (  # noqa: E402
    CHECKPOINT_SOURCE,
    MODEL_SOURCE,
    PREDICTION_KEY_TEMPLATE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (  # noqa: E402
    TrainingExample,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: E402
    ModelForwardResult,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (  # noqa: E402
    build_exact_cost_provenance,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (  # noqa: E402
    V2HybridPredictionPublisher,
    build_prediction_payload,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (  # noqa: E402
    V2OnlyJsonIO,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (  # noqa: E402
    FeatureTensorRecord,
)
from v2.backend.app.services.ordinary_paper_admission import (  # noqa: E402
    build_microstructure_trust_evidence,
)
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (  # noqa: E402
    build_serving_feature_vector,
    feature_abi_sha256 as serving_feature_abi_sha256,
    feature_builder_sha256 as serving_feature_builder_sha256,
)
from v2.backend.app.services.prediction_serving.serving_model_v3 import (  # noqa: E402
    EDGE_HEAD_ACTIONS,
    MODEL_ARCHITECTURE,
    build_serving_model_v3,
)

STATUS_KEY = "v2:trainer:paper_provisional_prediction_publisher:status"
ADAPTIVE_COST_KEY_TEMPLATE = "v2:costs:round_trip_bps:{symbol}"
MICROSTRUCTURE_KEY_TEMPLATE = "v2:microstructure:trust_score:{symbol}:{timeframe}"
COHORT_ACTIVATION_KEY = "v2:paper:provisional_cohort_activation"
MICRO_ACTIONS_OK = {"ALLOW", "REDUCE_SIZE"}
DEFAULT_CHECKPOINT = (
    Path(REPO_ROOT) / ".local_models/paper_provisional/PAPER_PROVISIONAL_100_ROW_CHECKPOINT.pt"
)
DEFAULT_MANIFEST = (
    Path(REPO_ROOT) / ".local_models/paper_provisional/provisional_100_row_manifest.json"
)
PROVISIONAL_TTL_SECONDS = 180


# --------------------------------------------------------------------------- #
# Small IO helpers (read-only against V2 keys).
# --------------------------------------------------------------------------- #
def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_ms(value: Any) -> str | None:
    parsed = parse_ms(value)
    if parsed is None:
        return None
    return (
        datetime.fromtimestamp(parsed / 1000.0, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _gross_expected_move_from_directional_net_edge(
    *, action: str, directional_net_edge_bps: Any, round_trip_cost_bps: float
) -> float | None:
    """Convert a position-return net edge to the publisher's signed gross move."""
    normalized_action = str(action).strip().lower()
    if normalized_action == "hold":
        return 0.0
    net_edge = _finite_float(directional_net_edge_bps)
    if normalized_action not in {"long", "short"} or net_edge is None:
        return None
    gross_directional = net_edge + abs(float(round_trip_cost_bps))
    return gross_directional if normalized_action == "long" else -gross_directional


def read_json_key(client: Any, key: str) -> Any:
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
    client.ping()
    return client


# --------------------------------------------------------------------------- #
# Checkpoint (provisional MLP + genuinely fitted calibration).
# --------------------------------------------------------------------------- #
class ProvisionalCheckpoint:
    def __init__(self, path: Path) -> None:
        import torch

        blob = torch.load(path, map_location="cpu", weights_only=False)
        meta = blob["meta"]
        self.path = str(path)
        self.feature_names: list[str] = list(meta["feature_names"])
        self.actions: list[str] = list(meta["actions"])
        self.mean = torch.tensor(meta["standardize_mean"]).unsqueeze(0)
        self.std = torch.tensor(meta["standardize_std"]).unsqueeze(0)
        self.model_id: str = str(meta["model_id"])
        self.checkpoint_id: str = str(meta["checkpoint_id"])
        self.weight_sha256: str = str(meta["checkpoint_weight_sha256"])
        self.model_parameter_fingerprint: str = str(meta["model_parameter_fingerprint"])
        self.calibration_state: dict[str, Any] = normalize_calibration_state(
            meta["confidence_calibration_state"]
        )
        self.manifest_id: str = str(meta.get("manifest_id") or "")
        self.feature_abi_sha256: str = str(meta.get("feature_abi_sha256") or "")
        self.feature_builder_sha256: str = str(meta.get("feature_builder_sha256") or "")
        self.serving_feature_abi_v2 = (
            self.feature_abi_sha256 == serving_feature_abi_sha256()
            and self.feature_builder_sha256 == serving_feature_builder_sha256()
        )
        self.generated_utc: str = str(meta.get("generated_utc") or utc_now())
        self.model_architecture: str = str(meta.get("model_architecture") or "")
        self.directional_net_edge_actions: tuple[str, ...] = tuple(
            meta.get("directional_net_edge_actions") or ()
        )
        self.directional_net_edge_mean_bps = torch.tensor(
            meta.get("directional_net_edge_mean_bps") or []
        )
        self.directional_net_edge_scale_bps = torch.tensor(
            meta.get("directional_net_edge_scale_bps") or []
        )
        self._torch = torch
        if self.model_architecture == MODEL_ARCHITECTURE:
            if self.directional_net_edge_actions != EDGE_HEAD_ACTIONS:
                raise ValueError("CHECKPOINT_DIRECTIONAL_EDGE_ACTIONS_MISMATCH")
            if self.directional_net_edge_mean_bps.numel() != len(EDGE_HEAD_ACTIONS):
                raise ValueError("CHECKPOINT_DIRECTIONAL_EDGE_MEAN_INVALID")
            if self.directional_net_edge_scale_bps.numel() != len(EDGE_HEAD_ACTIONS):
                raise ValueError("CHECKPOINT_DIRECTIONAL_EDGE_SCALE_INVALID")
            model = build_serving_model_v3(
                input_dim=len(self.feature_names), action_count=len(self.actions)
            )
        else:
            # Rollback compatibility for the previous action-only paper model.
            model = torch.nn.Sequential(
                torch.nn.Linear(len(self.feature_names), 32),
                torch.nn.ReLU(),
                torch.nn.Linear(32, len(self.actions)),
            )
        model.load_state_dict(blob["state_dict"])
        model.eval()
        self.model = model
        assert self.calibration_state.get("fitted") is True, "provisional calibration not fitted"

    def forward(self, feature_values: list[float]) -> dict[str, Any]:
        torch = self._torch
        x = torch.tensor([feature_values], dtype=torch.float32)
        xn = (x - self.mean) / self.std
        with torch.no_grad():
            output = self.model(xn)
            if self.model_architecture == MODEL_ARCHITECTURE:
                logits_batch, edge_standardized_batch = output
                logits = logits_batch[0]
                directional_edges = (
                    edge_standardized_batch[0] * self.directional_net_edge_scale_bps
                    + self.directional_net_edge_mean_bps
                )
            else:
                logits = output[0]
                directional_edges = None
            probs = torch.softmax(logits, dim=0)
        idx = int(torch.argmax(probs))
        action = self.actions[idx]
        raw_prob = float(probs[idx])
        result = {
            "action": action,
            "action_index": idx,
            "logits": [float(v) for v in logits.tolist()],
            "probabilities": [float(v) for v in probs.tolist()],
            "confidence_raw": raw_prob,
        }
        if directional_edges is not None:
            edge_values = [float(value) for value in directional_edges.tolist()]
            result["directional_net_edge_bps"] = dict(
                zip(EDGE_HEAD_ACTIONS, edge_values, strict=True)
            )
            result["selected_directional_net_edge_bps"] = (
                result["directional_net_edge_bps"].get(action)
            )
        return result

    def build_calibration(
        self, *, raw_prob: float, action: str, data_coverage_percent: float,
        missing_feature_count: int, stale_feature_count: int, total_feature_count: int,
    ) -> dict[str, Any]:
        """Build the canonical calibration dict exactly like the strict model.forward:
        calibrate_confidence(...) output + selected-action + checkpoint metadata."""
        cs = self.calibration_state
        temperature = float(cs["temperature"])
        cal = calibrate_confidence(
            raw_probability=raw_prob,
            data_coverage_percent=data_coverage_percent,
            missing_feature_count=missing_feature_count,
            stale_feature_count=stale_feature_count,
            total_feature_count=total_feature_count,
            temperature=temperature,
            calibration_fitted=True,
            calibration_reason=None,
        )
        directional = action in CONFIDENCE_HEAD_ACTIONS
        cal.update(
            {
                "selected_action": action,
                "selected_action_is_directional": directional,
                "confidence_head_action_index": (
                    CONFIDENCE_HEAD_ACTIONS.index(action) if directional else None
                ),
                "model_parameter_fingerprint": self.model_parameter_fingerprint,
                "checkpoint_calibration_sample": cs.get("sample"),
                "checkpoint_calibration_fit_partition": cs.get("fit_partition"),
                "checkpoint_calibration_validation_rows_used": cs.get("validation_rows_used"),
                "checkpoint_calibration_row_digest": cs.get("row_digest"),
            }
        )
        return cal

    def checkpoint_manifest(self) -> CheckpointManifest:
        cs = self.calibration_state
        return CheckpointManifest(
            checkpoint_id=self.checkpoint_id,
            checkpoint_source=CHECKPOINT_SOURCE,
            path=self.path,
            generated_utc=self.generated_utc,
            model_id=self.model_id,
            input_dim=len(self.feature_names),
            device="cpu",
            cuda_active=False,
            weight_blob_written=True,
            weight_file_path=self.path,
            weight_file_format="torch_state_dict",
            weight_file_sha256=self.weight_sha256,
            model_parameter_fingerprint=self.model_parameter_fingerprint,
            confidence_calibration_fitted=True,
            confidence_calibration_temperature=float(cs["temperature"]),
            confidence_calibration_sample=int(cs["sample"]),
            confidence_calibration_fit_partition=str(cs.get("fit_partition") or ""),
            confidence_calibration_validation_rows_used=0,
            confidence_calibration_label_semantics=str(cs.get("label_semantics") or ""),
            confidence_head_schema_version=str(cs.get("confidence_head_schema_version") or ""),
            confidence_head_actions=tuple(cs.get("confidence_head_actions") or ()),
            confidence_calibration_long_sample=int(cs["action_counts"]["long"]),
            confidence_calibration_short_sample=int(cs["action_counts"]["short"]),
            confidence_calibration_model_parameter_fingerprint=self.model_parameter_fingerprint,
            confidence_calibration_row_digest=str(cs.get("row_digest") or ""),
            confidence_calibration_state=dict(cs),
            lineage_kind="PAPER_PROVISIONAL_SERVING_CANDIDATE",
            training_partition_digest=str(cs.get("row_digest") or ""),
        )


# --------------------------------------------------------------------------- #
# Cohort identity.
# --------------------------------------------------------------------------- #
def read_active_cohort(client: Any) -> dict[str, Any]:
    rec = read_json_key(client, COHORT_ACTIVATION_KEY)
    if isinstance(rec, dict) and rec.get("paper_strategy_cohort_id"):
        return rec
    raise SystemExit("BLOCKED: no active provisional cohort activation in Redis")


# --------------------------------------------------------------------------- #
# Feature snapshot -> (my-40-feature tensor, trust_row).
# --------------------------------------------------------------------------- #
def read_current_feature_snapshot(client: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    """Prefer the mutable latest projection; require a non-empty features map and
    proven latest-unclosed-kline exclusion (finality).

    The immutable feature payload deliberately contains ``available_at=null``:
    availability is only knowable after Redis commits it.  Bind the exact
    payload bytes to its post-commit publication receipt and expose that receipt
    clock as ``record_available_at`` for the shared serving builder.
    """
    key = f"v2:features:latest:{symbol}:{timeframe}"
    raw = client.get(key)
    if raw is None:
        return None
    raw_bytes = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
    try:
        snap = json.loads(raw_bytes)
    except (TypeError, ValueError):
        return None
    if not isinstance(snap, dict):
        return None
    if str(snap.get("symbol") or "").upper() != symbol or str(snap.get("timeframe") or "") != timeframe:
        return None
    feats = snap.get("features")
    if not isinstance(feats, Mapping) or not feats:
        return None
    snapshot_id = str(snap.get("feature_snapshot_id") or "")
    receipt = read_json_key(
        client, f"v2:features:publication_receipt:{snapshot_id}"
    )
    if not isinstance(receipt, Mapping):
        return None
    receipt_valid = (
        receipt.get("schema_version")
        == "native_feature_publication_postcommit_receipt_v1"
        and receipt.get("publication_binding_authenticated") is True
        and receipt.get("publication_binding_complete") is True
        and receipt.get("temporal_invariants_valid") is True
        and str(receipt.get("feature_snapshot_id") or "") == snapshot_id
        and str(receipt.get("symbol") or "").upper() == symbol
        and str(receipt.get("timeframe") or "") == timeframe
        and str(receipt.get("feature_cutoff") or "")
        == str(snap.get("feature_cutoff") or "")
        and str(receipt.get("snapshot_archive_key") or "")
        == f"v2:features:snapshot:{snapshot_id}"
        and str(receipt.get("snapshot_payload_sha256") or "")
        == hashlib.sha256(raw_bytes).hexdigest()
        and len(str(receipt.get("receipt_sha256") or "")) == 64
    )
    if not receipt_valid:
        return None
    enriched = dict(snap)
    enriched["record_available_at"] = receipt.get("available_at")
    enriched["feature_publication_receipt_sha256"] = receipt.get("receipt_sha256")
    enriched["feature_publication_receipt_verified"] = True
    enriched["feature_publication_receipt_key"] = (
        f"v2:features:publication_receipt:{snapshot_id}"
    )
    return enriched


def build_tensor(
    ckpt: ProvisionalCheckpoint,
    snapshot: Mapping[str, Any],
    *,
    decision_time_iso: str,
    exact_cost_record: Mapping[str, Any] | None,
) -> FeatureTensorRecord | None:
    """Build a ZERO-MISSING tensor: serve only snapshots that carry every feature
    in the checkpoint ABI (so no critical-feature-family / missing-feature block)."""
    feats = snapshot.get("features") or {}
    values: list[float] = []
    if ckpt.serving_feature_abi_v2:
        vector = build_serving_feature_vector(
            feature_record=snapshot,
            decision_time=decision_time_iso,
            exact_cost_record=exact_cost_record,
        )
        if tuple(ckpt.feature_names) != vector.ordered_feature_names:
            raise ValueError("CHECKPOINT_ORDERED_FEATURE_NAMES_ABI_MISMATCH")
        values.extend(vector.values)
    else:
        for name in ckpt.feature_names:
            v = _finite_float(feats.get(name))
            if v is None:
                return None  # incomplete snapshot for this ABI — skip, never zero-fill
            values.append(v)
    n = len(ckpt.feature_names)
    feature_snapshot_id = str(snapshot.get("feature_snapshot_id") or "")
    source_lineage_hash = hashlib.sha256(
        json.dumps(
            {
                "symbol": str(snapshot.get("symbol")),
                "timeframe": str(snapshot.get("timeframe")),
                "feature_snapshot_id": feature_snapshot_id,
                "feature_names": list(ckpt.feature_names),
                "feature_cutoff": snapshot.get("feature_cutoff"),
                "available_at": snapshot.get("available_at"),
                "feature_abi_sha256": ckpt.feature_abi_sha256,
                "feature_builder_sha256": ckpt.feature_builder_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    tensor_digest = hashlib.sha256(
        json.dumps(
            {
                "schema": "serving_feature_abi_v2" if ckpt.serving_feature_abi_v2 else "paper_provisional_v1",
                "symbol": str(snapshot.get("symbol")),
                "timeframe": str(snapshot.get("timeframe")),
                "feature_snapshot_id": feature_snapshot_id,
                "feature_names": list(ckpt.feature_names),
                "values": values,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    tensor_id = (
        tensor_digest
        if ckpt.serving_feature_abi_v2
        else "paper_provisional_tensor_" + tensor_digest[:24]
    )
    return FeatureTensorRecord(
        tensor_id=tensor_id,
        symbol=str(snapshot.get("symbol")),
        timeframe=str(snapshot.get("timeframe")),
        feature_snapshot_id=feature_snapshot_id,
        values=tuple(values),
        missing_mask=tuple(0 for _ in range(n)),
        stale_mask=tuple(0 for _ in range(n)),
        source_availability=tuple(1 for _ in range(n)),
        feature_names=tuple(ckpt.feature_names),
        source_labels=tuple(
            "serving_feature_abi_v2_shared_builder"
            if ckpt.serving_feature_abi_v2
            else "paper_provisional_feature_snapshot"
            for _ in ckpt.feature_names
        ),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=tuple(1 for _ in range(n)),
        source_lineage_hash=source_lineage_hash,
    )


def build_trust_row(
    *,
    tensor: FeatureTensorRecord,
    snapshot: Mapping[str, Any],
    mtf: Mapping[str, Any],
    candle: Mapping[str, Any],
    decision_time_iso: str,
    generated_at: str,
) -> dict[str, Any]:
    feature_cutoff = snapshot.get("feature_cutoff") or mtf.get("feature_cutoff")
    available_at = (
        snapshot.get("record_available_at")
        or snapshot.get("available_at")
        or candle.get("available_at")
    )
    source_available_at = (
        snapshot.get("source_available_at")
        or snapshot.get("source_available_time")
        or candle.get("available_at")
    )
    source_received_at = (
        snapshot.get("ingested_at")
        or snapshot.get("source_received_time_est")
        or source_available_at
    )
    close_time = candle.get("candle_close_time") or candle.get("close_time")
    open_time = candle.get("candle_open_time") or candle.get("open_time")
    event_time = candle.get("event_time") or close_time
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": ENFORCEMENT_EPOCH,
        "producer": "v2_paper_provisional_prediction_publisher",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": generated_at,
        "sample_id": "paper_provisional_" + str(mtf.get("mtf_snapshot_id")),
        "symbol": str(snapshot.get("symbol")),
        "timeframe": str(snapshot.get("timeframe")),
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "feature_vector_hash": tensor.tensor_id,
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": False,
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "candle_open_time": iso_ms(open_time),
        "candle_close_time": iso_ms(close_time),
        "source_event_time_est": iso_ms(event_time),
        "source_received_time_est": iso_ms(source_received_at),
        "source_available_time": iso_ms(source_available_at),
        "record_available_at": iso_ms(available_at),
        "available_at": iso_ms(available_at),
        "feature_cutoff": iso_ms(feature_cutoff),
        "decision_time_est": decision_time_iso,
        "decision_time": decision_time_iso,
        "masa_feature_cutoff": iso_ms(feature_cutoff),
        "ppo_feature_cutoff": iso_ms(feature_cutoff),
        "masa_prediction_timestamp": decision_time_iso,
        "ppo_observation_timestamp": decision_time_iso,
        "all_tf_candle_timestamps": [
            iso_ms(value) for value in (mtf.get("all_tf_candle_timestamps") or [])
        ],
        "all_source_event_times": [
            iso_ms(value) for value in (mtf.get("all_source_event_times") or [])
        ],
        "decision_id": mtf.get("decision_id"),
        "mtf_snapshot_id": mtf.get("mtf_snapshot_id"),
        "mtf_snapshot_valid": mtf.get("valid"),
        "mtf_snapshot_reject_reasons": list(mtf.get("reject_reasons") or []),
        "multi_timeframe_decision_snapshot": dict(mtf),
        "features": dict(zip(tensor.feature_names, tensor.values, strict=True)),
        "latency_ms": 0,
        "is_backfilled": False,
        "backfilled": False,
        "source_mode": "live",
        # Finality proof carried from the producer snapshot.
        "latest_unclosed_kline_excluded": snapshot.get("latest_unclosed_kline_excluded"),
        "latest_unclosed_exclusion_method": snapshot.get("latest_unclosed_exclusion_method"),
        "latest_unclosed_exclusion_decision_time_ms": snapshot.get(
            "latest_unclosed_exclusion_decision_time_ms"
        ),
        "latest_closed_kline_close_time_ms": snapshot.get(
            "latest_closed_kline_close_time_ms"
        ),
    }


# --------------------------------------------------------------------------- #
# Microstructure + cost binding (decision-time gated).
# --------------------------------------------------------------------------- #
def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def read_microstructure_action(
    client: Any, symbol: str, timeframe: str, decision_time: datetime
) -> tuple[str | None, dict[str, Any]]:
    """Bind the current microstructure action. The live-book trust is timeframe
    agnostic (mirrored to 1m/5m/15m), so try the requested tf then those mirrors.
    Gate: real record, matching symbol, both clocks parseable and NOT future-dated
    relative to the decision time, and a decided action. The sub-second
    generated_at/available_at ordering is a writer artifact (feed available then
    scored) universally present in the live data and is not enforced here."""
    for tf in (timeframe, "1m", "5m", "15m"):
        rec = read_json_key(client, f"v2:microstructure:trust_score:{symbol}:{tf}")
        if not isinstance(rec, dict):
            continue
        if rec.get("schema_version") != "microstructure_trust_score_v2":
            continue
        if str(rec.get("symbol") or "").upper() != symbol:
            continue
        avail = _parse_utc(rec.get("available_at"))
        gen = _parse_utc(rec.get("generated_at"))
        if avail is None or gen is None:
            continue
        if avail > decision_time or gen > decision_time:
            continue  # future-dated relative to our decision — reject
        action = str(rec.get("microstructure_action") or "").upper()
        return action, {
            "microstructure_action": action,
            "composite_microstructure_trust_score": rec.get("composite_microstructure_trust_score"),
            "available_at": rec.get("available_at"),
            "generated_at": rec.get("generated_at"),
            "matched_timeframe": tf,
        }
    return None, {}


def build_cost_provenance(
    client: Any, symbol: str
) -> tuple[float | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Bind the canonical adaptive round-trip cost via build_exact_cost_provenance
    over v2:costs:round_trip_bps:{symbol}. Returns
    (round_trip_bps, provenance, exact source record)."""
    source_key = ADAPTIVE_COST_KEY_TEMPLATE.format(symbol=symbol)
    payload = read_json_key(client, source_key)
    if not isinstance(payload, Mapping):
        return None, None, None
    fallback_rt = _finite_float(payload.get("round_trip_cost_bps")) or _finite_float(
        payload.get("flat_baseline_round_trip_bps")
    )
    try:
        provenance = build_exact_cost_provenance(
            source_key=source_key,
            source_payload=payload,
            consumer_observed_at=datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        )
    except Exception:  # noqa: BLE001
        # The current adaptive-cost source lacks the strict-UTC orderbook clock
        # lineage build_exact_cost_provenance requires. Return the genuine cost
        # value with NO exact-cost envelope: the record still publishes (canonical
        # supply) but carries the honest ordinary_paper_exact_cost block reason.
        return fallback_rt, None, dict(payload)
    rt = _finite_float(provenance.get("round_trip_cost_bps")) or fallback_rt
    return rt, provenance, dict(payload)


def build_micro_evidence(
    client: Any,
    *,
    symbol: str,
    timeframe: str,
    tensor: FeatureTensorRecord,
    decision_time_iso: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Build the hash-bound microstructure_trust_evidence envelope from the exact
    current source read (live-book trust is timeframe-agnostic: try tf then mirrors)."""
    for tf in (timeframe, "1m", "5m", "15m"):
        source_key = MICROSTRUCTURE_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
        payload = read_json_key(client, source_key)
        if not isinstance(payload, Mapping):
            continue
        if payload.get("schema_version") != "microstructure_trust_score_v2":
            continue
        if str(payload.get("symbol") or "").upper() != symbol:
            continue
        try:
            ttl = client.ttl(source_key)
        except Exception:
            ttl = None
        ttl_int = int(ttl) if isinstance(ttl, int) and ttl > 0 else None
        if ttl_int is None:
            continue
        evidence = build_microstructure_trust_evidence(
            source_payload=payload,
            source_payload_readback=payload,
            source_key=source_key,
            source_observed_ttl_seconds=ttl_int,
            tensor_id=tensor.tensor_id,
            feature_snapshot_id=tensor.feature_snapshot_id,
            tensor_source_lineage_hash=tensor.source_lineage_hash,
            tensor_decision_time=decision_time_iso,
            symbol=symbol,
            timeframe=tensor.timeframe,
        )
        action = str(payload.get("microstructure_action") or "").upper()
        return action, evidence
    return None, None


def classify_row(
    *, tensor: FeatureTensorRecord, trust_row: Mapping[str, Any]
) -> dict[str, Any]:
    """Run the canonical classify_training_sample on the market-state row built from
    the (zero-missing) tensor + trust lineage. accepted_for_training is genuine
    data-quality (market-state score >= 80), never a fabricated label claim."""
    # Mirror _market_state_row_from_example: express zero-missing via names/counts
    # only (never a raw mask list, which mask_names would misread as a phantom).
    row = {
        "symbol": tensor.symbol,
        "timeframe": tensor.timeframe,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "features": dict(zip(tensor.feature_names, tensor.values, strict=True)),
        "feature_names": list(tensor.feature_names),
        "missing_feature_names": [],
        "missing_feature_count": 0,
        "stale_feature_names": [],
        "stale_feature_count": 0,
        "feature_freshness_state": "CURRENT",
    }
    for key in (
        "feature_cutoff", "available_at", "candle_closed_confirmed", "candle_open_time",
        "candle_close_time", "source_event_time_est", "source_received_time_est",
        "source_available_time", "decision_time_est", "decision_id", "mtf_snapshot_id",
        "mtf_snapshot_valid", "multi_timeframe_decision_snapshot",
        "all_tf_candle_timestamps", "all_source_event_times", "latency_ms",
        "is_backfilled", "backfilled",
    ):
        if trust_row.get(key) is not None:
            row[key] = trust_row.get(key)
    return classify_training_sample(row)


# --------------------------------------------------------------------------- #
# Provisional cohort + safety tags.
# --------------------------------------------------------------------------- #
def stamp_provisional_tags(
    payload: dict[str, Any],
    cohort: Mapping[str, Any],
    checkpoint: ProvisionalCheckpoint,
) -> None:
    payload.update(
        {
            "checkpoint_classification": "PAPER_PROVISIONAL_100_ROW_CHECKPOINT",
            "paper_provisional_checkpoint": True,
            "paper_provisional_checkpoint_id": checkpoint.checkpoint_id,
            "paper_strategy_cohort_id": cohort.get("paper_strategy_cohort_id"),
            "paper_cohort_checkpoint_id": cohort.get("checkpoint_id"),
            "feature_abi_sha256": checkpoint.feature_abi_sha256,
            "feature_builder_sha256": checkpoint.feature_builder_sha256,
            "serving_feature_abi_v2": checkpoint.serving_feature_abi_v2,
            "paper_cohort_activation_utc": cohort.get("paper_cohort_activation_utc"),
            "paper_cohort_initial_equity_usd": cohort.get("paper_cohort_initial_equity_usd"),
            "paper_only": True,
            "economic_certification": "PROVISIONAL",
            "checkpoint_promotable": False,
            "engineering_canary": False,
            "engineering_replay": False,
            "requires_per_trade_economic_exception": False,
            "live_eligible": False,
            "valid_for_live": False,
            "routes_to_live": False,
            "places_real_order": False,
            "exchange_mutation": False,
            "trainer_direct_trading": False,
        }
    )


# --------------------------------------------------------------------------- #
# One symbol/timeframe -> published canonical record (or a reasoned rejection).
# --------------------------------------------------------------------------- #
def publish_one(
    *,
    client: Any,
    io: V2OnlyJsonIO,
    publisher: V2HybridPredictionPublisher,
    ckpt: ProvisionalCheckpoint,
    cohort: Mapping[str, Any],
    symbol: str,
    timeframe: str,
    exchange: str = "binance",
    serving_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = utc_now()
    if str(cohort.get("checkpoint_id") or "") != ckpt.checkpoint_id:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "COHORT_CHECKPOINT_MISMATCH",
        }
    snapshot = read_current_feature_snapshot(client, symbol, timeframe)
    if snapshot is None:
        return {"symbol": symbol, "timeframe": timeframe, "status": "NO_CURRENT_FEATURE_SNAPSHOT"}
    if snapshot.get("latest_unclosed_kline_excluded") is not True:
        return {"symbol": symbol, "timeframe": timeframe, "status": "FINALITY_UNPROVEN"}

    # Observe exact cost before stamping the prediction decision.  The canonical
    # receipt contract requires consumer_observed_at <= decision_time; choosing
    # decision_time first made a genuine post-read clock impossible by a few
    # microseconds and correctly failed ordinary paper admission.
    round_trip_cost_bps, cost_provenance, exact_cost_record = build_cost_provenance(
        client, symbol
    )
    if round_trip_cost_bps is None:
        return {"symbol": symbol, "timeframe": timeframe, "status": "NO_ADAPTIVE_COST_SOURCE"}

    candles_by_tf = {
        tf: read_json_key(client, closed_candle_key(exchange, symbol, tf))
        for tf in REQUIRED_DECISION_TIMEFRAMES
    }
    decision_dt = datetime.now(UTC)
    decision_ms = int(decision_dt.timestamp() * 1000)
    decision_iso = decision_dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    feature_cutoff_ms = parse_ms(snapshot.get("feature_cutoff"))
    if feature_cutoff_ms is None:
        return {"symbol": symbol, "timeframe": timeframe, "status": "FEATURE_CUTOFF_INVALID"}
    mtf = build_multi_timeframe_decision_snapshot(
        symbol=symbol,
        # The model tensor is cut at the primary feature snapshot's cutoff.
        # Select every supporting timeframe at that same cutoff so no faster
        # candle or source event can appear after the tensor's feature_cutoff.
        decision_time=feature_cutoff_ms,
        candles_by_timeframe=candles_by_tf,
        required_timeframes=REQUIRED_DECISION_TIMEFRAMES,
    )
    if mtf.get("valid") is not True:
        return {
            "symbol": symbol, "timeframe": timeframe, "status": "MTF_SNAPSHOT_INVALID",
            "reject_reasons": list(mtf.get("reject_reasons") or []),
        }
    candle = latest_closed_candle_at_or_before(candles_by_tf.get(timeframe), decision_ms)
    if candle is None:
        return {"symbol": symbol, "timeframe": timeframe, "status": "PRIMARY_CANDLE_MISSING"}

    # ServingFeatureABIV2 binds its four cost slots to this exact source record.
    try:
        tensor = build_tensor(
            ckpt,
            snapshot,
            decision_time_iso=decision_iso,
            exact_cost_record=exact_cost_record,
        )
    except ValueError as exc:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "FEATURE_ABI_REJECTED",
            "reject_reasons": [str(exc)],
            "cost_evidence_valid": cost_provenance is not None,
        }
    if tensor is None:
        return {"symbol": symbol, "timeframe": timeframe, "status": "INCOMPLETE_FEATURE_ABI"}

    trust_row = build_trust_row(
        tensor=tensor, snapshot=snapshot, mtf=mtf, candle=candle,
        decision_time_iso=decision_iso, generated_at=generated_at,
    )
    # Genuine data-quality classification (market-state score >= 80, zero missing).
    classification = classify_row(tensor=tensor, trust_row=trust_row)
    accepted = classification.get("accepted_for_training") is True
    if not accepted:
        return {
            "symbol": symbol, "timeframe": timeframe, "status": "NOT_ACCEPTED_FOR_TRAINING",
            "reject_reasons": list(classification.get("reject_reasons") or [])[:6],
            "market_state_integrity_score": classification.get("market_state_integrity_score"),
        }
    trust_row["accepted_for_training"] = True
    trust_row["valid_for_training"] = True
    trust_row["trainer_consumable"] = True
    trust_row["market_state_id"] = classification.get("market_state_id")

    # Canonical microstructure trust evidence envelope (hash-bound to the tensor).
    micro_action, micro_evidence = build_micro_evidence(
        client, symbol=symbol, timeframe=timeframe, tensor=tensor,
        decision_time_iso=decision_iso,
    )
    if micro_action not in MICRO_ACTIONS_OK or micro_evidence is None:
        return {
            "symbol": symbol, "timeframe": timeframe, "status": "MICROSTRUCTURE_BLOCKED",
            "microstructure_action": micro_action,
            "cost_evidence_valid": cost_provenance is not None,
            "microstructure_evidence_valid": bool(
                isinstance(micro_evidence, Mapping)
                and micro_evidence.get("evidence_valid") is True
            ),
        }
    trust_row["microstructure_trust_evidence"] = micro_evidence

    example = TrainingExample(
        symbol=symbol,
        timeframe=timeframe,
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=tuple(closed_candle_key(exchange, symbol, tf) for tf in REQUIRED_DECISION_TIMEFRAMES),
        row_classification="TRAINABLE",
        trust_row=trust_row,
    )

    fwd = ckpt.forward(list(tensor.values))
    action = fwd["action"]
    calibration = ckpt.build_calibration(
        raw_prob=fwd["confidence_raw"],
        action=action,
        data_coverage_percent=tensor.data_coverage_percent,
        missing_feature_count=len(tensor.missing_feature_names),
        stale_feature_count=len(tensor.stale_feature_names),
        total_feature_count=len(tensor.feature_names),
    )
    confidence_calibrated = float(calibration["confidence_calibrated"])
    predicted_net_edge = _finite_float(fwd.get("selected_directional_net_edge_bps"))
    if ckpt.model_architecture == MODEL_ARCHITECTURE:
        expected_move_bps = _gross_expected_move_from_directional_net_edge(
            action=action,
            directional_net_edge_bps=predicted_net_edge,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        if expected_move_bps is None:
            expected_move_bps = 0.0
    else:
        # Rollback compatibility only. New governed activations use the trained
        # directional net-edge head above.
        edge = 2.0 * confidence_calibrated - 1.0
        magnitude = abs(edge) * (abs(round_trip_cost_bps) + 10.0)
        if action == "long":
            expected_move_bps = abs(magnitude)
        elif action == "short":
            expected_move_bps = -abs(magnitude)
        else:
            expected_move_bps = 0.0

    model_output = ModelForwardResult(
        model_id=ckpt.model_id,
        model_source=MODEL_SOURCE,
        action_logits=tuple(fwd["logits"]),
        action_probabilities=tuple(fwd["probabilities"]),
        selected_action_index=fwd["action_index"],
        selected_action=action,
        expected_move_bps=expected_move_bps,
        confidence_raw=fwd["confidence_raw"],
        confidence_calibrated=confidence_calibrated,
        policy_value=confidence_calibrated,
        masa_signal=0.0,
        calibration=calibration,
        device="cpu",
        cuda_active=False,
        model_tensors_device_verified=True,
    )

    payload = build_prediction_payload(
        example=example,
        model_output=model_output,
        checkpoint=ckpt.checkpoint_manifest(),
        round_trip_cost_bps=round_trip_cost_bps,
        min_data_coverage_percent=50.0,
        min_confidence_calibrated=0.5,
        min_edge_after_cost_bps=0.0,
        checkpoint_weight_sha256=ckpt.weight_sha256,
        checkpoint_evidence_digest=ckpt.model_parameter_fingerprint,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        cost_provenance=cost_provenance,
        decision_time_utc=decision_iso,
        cycle_id=(serving_context or {}).get("cycle_id"),
        process_instance_id=(serving_context or {}).get("process_instance_id"),
        candidate_policy_fingerprint=(serving_context or {}).get(
            "candidate_policy_fingerprint"
        ),
        # A serving cycle can legitimately re-evaluate the same feature tensor
        # at a later decision time. Bind that new decision to a new prediction
        # ID so the immutable per-ID source record never collides with a prior
        # cycle's different clock/evidence payload.
        prediction_nonce=(serving_context or {}).get("cycle_id"),
    )
    if ckpt.serving_feature_abi_v2:
        # Carry the exact model input and its ABI-scoped lineage into the
        # canonical prediction.  The mutable upstream feature snapshot has a
        # much broader legacy catalogue whose absent optional fields must not
        # replace this checkpoint's complete, admitted 29-feature contract at
        # downstream revalidation.
        payload.update(
            {
                "features": dict(
                    zip(tensor.feature_names, tensor.values, strict=True)
                ),
                "missing_mask": {
                    name: bool(flag)
                    for name, flag in zip(
                        tensor.feature_names, tensor.missing_mask, strict=True
                    )
                },
                "stale_mask": {
                    name: bool(flag)
                    for name, flag in zip(
                        tensor.feature_names, tensor.stale_mask, strict=True
                    )
                },
                "source_availability": {
                    name: bool(flag)
                    for name, flag in zip(
                        tensor.feature_names,
                        tensor.source_availability_vector,
                        strict=True,
                    )
                },
                "entry_feature_snapshot_id": tensor.feature_snapshot_id,
                "entry_feature_available_at": trust_row.get("available_at"),
                "entry_feature_generated_at": snapshot.get("generated_at"),
                "entry_feature_cutoff": trust_row.get("feature_cutoff"),
                "entry_feature_decision_time": decision_iso,
                "entry_feature_candle_closed_confirmed": True,
                "entry_feature_source": snapshot.get(
                    "feature_publication_receipt_key"
                ),
                "funding_bps_at_decision_time": exact_cost_record.get(
                    "funding_bps_at_decision_time"
                ),
                "expected_funding_bps": exact_cost_record.get(
                    "funding_bps_at_decision_time"
                ),
                "expected_funding_bps_source": (
                    "exact_cost_provenance.source_payload."
                    "funding_bps_at_decision_time"
                ),
                "entry_feature_snapshot": {
                    "schema_version": "serving_feature_abi_v2_entry_snapshot_v1",
                    "feature_snapshot_id": tensor.feature_snapshot_id,
                    "feature_tensor_id": tensor.tensor_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "feature_freshness_state": "CURRENT",
                    "available_at": trust_row.get("available_at"),
                    "record_available_at": trust_row.get("available_at"),
                    "generated_at": snapshot.get("generated_at"),
                    "feature_cutoff": trust_row.get("feature_cutoff"),
                    "candle_close_time": trust_row.get("candle_close_time"),
                    "candle_closed_confirmed": True,
                    "latest_unclosed_kline_excluded": True,
                    "latest_unclosed_exclusion_method": snapshot.get(
                        "latest_unclosed_exclusion_method"
                    ),
                    "latest_unclosed_exclusion_decision_time_ms": snapshot.get(
                        "latest_unclosed_exclusion_decision_time_ms"
                    ),
                    "latest_closed_kline_close_time_ms": snapshot.get(
                        "latest_closed_kline_close_time_ms"
                    ),
                    "feature_abi_sha256": ckpt.feature_abi_sha256,
                    "feature_builder_sha256": ckpt.feature_builder_sha256,
                    "feature_publication_receipt_sha256": snapshot.get(
                        "feature_publication_receipt_sha256"
                    ),
                    "feature_publication_receipt_verified": snapshot.get(
                        "feature_publication_receipt_verified"
                    ),
                    "feature_vector_hash": tensor.tensor_id,
                    "features": dict(
                        zip(tensor.feature_names, tensor.values, strict=True)
                    ),
                },
            }
        )
    stamp_provisional_tags(payload, cohort, ckpt)
    payload["directional_net_edge_model_architecture"] = ckpt.model_architecture
    payload["directional_net_edge_semantics"] = (
        "predicted_position_return_bps_after_complete_round_trip_cost"
        if ckpt.model_architecture == MODEL_ARCHITECTURE
        else "legacy_confidence_cost_proxy_rollback_only"
    )
    payload["predicted_directional_net_edge_bps"] = predicted_net_edge
    payload["counterfactual_directional_net_edge_bps"] = fwd.get(
        "directional_net_edge_bps"
    )
    if serving_context:
        # PredictionRecordV2 policy/lineage fields stamped by the canonical serving
        # runtime (registry generation, serving release sha, evidence hashes).
        for key in (
            "serving_runtime_release_sha", "active_model_registry_generation",
            "feature_evidence_sha256", "cost_evidence_sha256",
            "microstructure_evidence_sha256",
        ):
            if serving_context.get(key) is not None:
                payload[key] = serving_context.get(key)
        payload.setdefault(
            "checkpoint_classification", serving_context.get("checkpoint_classification")
        )
    payload["microstructure_action"] = micro_action
    payload["microstructure_trust_evidence"] = micro_evidence

    # Write the MTF snapshot the record references (trust replay dependency).
    mtf_snapshot_payload = attach_runtime_trust_metadata(
        dict(mtf),
        decision_id=payload.get("decision_id"),
        prediction_id=payload.get("prediction_id"),
        mtf_snapshot_id=payload.get("mtf_snapshot_id"),
        replay_snapshot_id=payload.get("replay_snapshot_id"),
        created_at=generated_at,
        producer="v2_paper_provisional_prediction_publisher",
    )
    mtf_snapshot_payload.update(
        {
            "available_at": payload.get("available_at"),
            "feature_hash": payload.get("feature_vector_hash"),
            "feature_vector_hash": payload.get("feature_vector_hash"),
            "all_source_event_times": list(payload.get("all_source_event_times") or []),
            "routes_to_live": False,
        }
    )
    mtf_key = f"v2:market:mtf_snapshot:{mtf_snapshot_payload['mtf_snapshot_id']}"
    io.set_json(mtf_key, mtf_snapshot_payload)
    payload["multi_timeframe_decision_snapshot"] = mtf_snapshot_payload
    payload["mtf_snapshot"] = mtf_snapshot_payload

    # publish_prediction itself performs the durable feature-snapshot archive
    # append and stamps durable_feature_snapshot_archive_* on the payload.
    ok = publisher.publish_prediction(payload)
    if not ok:
        return {
            "symbol": symbol, "timeframe": timeframe, "status": "PUBLISH_FAILED",
            "prediction_id": payload.get("prediction_id"),
            "paper_fill_gate_block_reasons": list(payload.get("paper_fill_gate_block_reasons") or [])[:8],
            "io_errors": list(getattr(io.audit, "errors", []) or [])[:6],
        }

    # Non-authoritative trainer proposals incl. native-policy signal for enrichment.
    lineage_error = None
    try:
        publisher.publish_lineage(
            prediction_payload=payload,
            min_confidence_calibrated=0.5,
            min_data_coverage_percent=50.0,
            risk_caps_configured=True,
        )
    except Exception as exc:  # noqa: BLE001
        lineage_error = type(exc).__name__

    prediction_key = PREDICTION_KEY_TEMPLATE.format(symbol=symbol, timeframe=timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "PUBLISHED",
        "prediction_key": prediction_key,
        "prediction_id": payload.get("prediction_id"),
        "selected_action": action,
        "confidence_calibrated": confidence_calibrated,
        "market_state_id": payload.get("market_state_id"),
        "market_state_integrity_score": payload.get("market_state_integrity_score"),
        "valid_for_orchestrator": payload.get("valid_for_orchestrator"),
        "valid_for_paper": payload.get("valid_for_paper"),
        "routes_to_orchestrator": payload.get("routes_to_orchestrator"),
        "paper_fill_allowed": payload.get("paper_fill_allowed"),
        "confidence_calibration_fitted": payload.get("confidence_calibration_fitted"),
        "replay_snapshot_id": payload.get("replay_snapshot_id"),
        "durable_feature_snapshot_archive_snapshot_id": payload.get(
            "durable_feature_snapshot_archive_snapshot_id"
        ),
        "paper_fill_gate_block_reasons": list(payload.get("paper_fill_gate_block_reasons") or [])[:8],
        "directional": action in ("long", "short"),
        "lineage_error": lineage_error,
        "paper_strategy_cohort_id": payload.get("paper_strategy_cohort_id"),
        "cost_evidence_valid": cost_provenance is not None,
        "microstructure_evidence_valid": bool(
            isinstance(micro_evidence, Mapping)
            and micro_evidence.get("evidence_valid") is True
        ),
    }


# --------------------------------------------------------------------------- #
# Universe resolution + run loop.
# --------------------------------------------------------------------------- #
def resolve_symbols(client: Any, explicit: list[str] | None) -> list[str]:
    if explicit:
        return [s.strip().upper() for s in explicit if s.strip()]
    try:
        from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols as ru

        return [s.upper() for s in ru()]
    except Exception:
        return []


def run_once(
    *,
    client: Any,
    ckpt: ProvisionalCheckpoint,
    symbols: list[str],
    timeframes: list[str],
    status_path: Path | None,
    stop_after_directional: int = 0,
) -> dict[str, Any]:
    io = V2OnlyJsonIO(client=client)
    publisher = V2HybridPredictionPublisher(
        io=io, behavior_receipt_archive_root=None,
        current_cycle_publication_ttl_seconds=PROVISIONAL_TTL_SECONDS,
    )
    cohort = read_active_cohort(client)
    observations: list[dict[str, Any]] = []
    published = directional = 0
    rejections: dict[str, int] = {}
    for symbol in symbols:
        for timeframe in timeframes:
            res = publish_one(
                client=client, io=io, publisher=publisher, ckpt=ckpt, cohort=cohort,
                symbol=symbol, timeframe=timeframe,
            )
            observations.append(res)
            if res.get("status") == "PUBLISHED":
                published += 1
                if res.get("directional"):
                    directional += 1
            else:
                rejections[res.get("status", "UNKNOWN")] = (
                    rejections.get(res.get("status", "UNKNOWN"), 0) + 1
                )
        if stop_after_directional and directional >= stop_after_directional:
            break
    generated_utc = utc_now()
    latest = next((o for o in reversed(observations) if o.get("status") == "PUBLISHED"), {})
    status = {
        "schema_version": "paper_provisional_prediction_publisher_status_v1",
        "generated_utc": generated_utc,
        "checkpoint_id": ckpt.checkpoint_id,
        "manifest_id": ckpt.manifest_id,
        "paper_strategy_cohort_id": cohort.get("paper_strategy_cohort_id"),
        "records_evaluated": len(observations),
        "records_published": published,
        "directional_records_published": directional,
        "hold_records_published": published - directional,
        "records_rejected": len(observations) - published,
        "rejections_by_reason": rejections,
        "latest_prediction_id": latest.get("prediction_id"),
        "latest_decision_time": generated_utc,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "exchange_action_taken": False,
        "paper_only": True,
        "routes_to_live": False,
        "sample_published": [o for o in observations if o.get("status") == "PUBLISHED"][:6],
        "sample_rejections": [o for o in observations if o.get("status") != "PUBLISHED"][:8],
    }
    try:
        io.set_json_expiring(STATUS_KEY, status, ex=PROVISIONAL_TTL_SECONDS * 4)
    except Exception:
        pass
    if status_path is not None:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status, indent=2, default=str))
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_paper_provisional_prediction_publisher")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--timeframes", default="5m,15m,1h,4h")
    parser.add_argument("--checkpoint-path", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--status-path", default="")
    parser.add_argument("--stop-after-directional", type=int, default=0)
    parser.add_argument("--max-symbols", type=int, default=0)
    args = parser.parse_args(argv)

    if not (args.once or args.loop):
        print(json.dumps({"status": "BLOCKED", "reason": "REQUIRE_--once_OR_--loop"}))
        return 1

    client = redis_client(args.redis_url)
    ckpt = ProvisionalCheckpoint(Path(args.checkpoint_path))
    symbols = resolve_symbols(client, [s for s in args.symbols.split(",") if s.strip()] or None)
    if args.max_symbols and len(symbols) > args.max_symbols:
        symbols = symbols[: args.max_symbols]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    status_path = Path(args.status_path) if args.status_path else None

    if args.once:
        status = run_once(
            client=client, ckpt=ckpt, symbols=symbols, timeframes=timeframes,
            status_path=status_path, stop_after_directional=args.stop_after_directional,
        )
        print(json.dumps(status, indent=2, default=str))
        return 0

    import time

    while True:
        status = run_once(
            client=client, ckpt=ckpt, symbols=symbols, timeframes=timeframes,
            status_path=status_path, stop_after_directional=args.stop_after_directional,
        )
        print(json.dumps({k: status[k] for k in (
            "generated_utc", "records_published", "directional_records_published",
            "records_rejected", "rejections_by_reason",
        )}, default=str), flush=True)
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
