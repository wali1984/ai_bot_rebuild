"""Trusted replay bootstrap from V2 feature snapshot archives."""
from __future__ import annotations

import bisect
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    build_multi_timeframe_decision_snapshot,
    canonical_candle_id,
    parse_ms,
    stable_hash,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    default_archive_path as default_canonical_5m_label_archive_path,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record,
    build_archive_status,
    build_reference_retention_status,
    default_archive_root,
    publish_status_artifacts,
    rollover_archive,
    write_checksum_manifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    parse_utc,
    snapshot_to_final_candle,
)

GOAL_ID = "V2_TRUSTED_REPLAY_BOOTSTRAP_PAPER_EXPLORATION_AND_ONLINE_LEARNING_ACTIVATION"
ARTIFACT_REL = Path("operator_runtime/v2_native_trainer/latest")


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _scan_json(client: Any, pattern: str, *, limit: int) -> Iterable[tuple[str, dict[str, Any]]]:
    count = 0
    for key in client.scan_iter(pattern, count=1000):
        if limit and count >= int(limit):
            break
        try:
            raw = client.get(key)
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            count += 1
            yield str(key), payload


def _scan_keys(client: Any, pattern: str, *, limit: int) -> list[str]:
    keys: list[str] = []
    for key in client.scan_iter(pattern, count=5000):
        keys.append(str(key))
        if limit and len(keys) >= int(limit):
            break
    return keys


def _json_for_key(client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = client.get(key)
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _build_feature_snapshot_candle_index(
    client: Any,
    *,
    keys: Iterable[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    by_pair: dict[tuple[str, str], list[tuple[int, int, dict[str, Any]]]] = {}
    for key in keys:
        payload = _json_for_key(client, key)
        if not isinstance(payload, dict):
            continue
        candle, reasons = snapshot_to_final_candle(payload)
        if candle is None:
            continue
        close_ms = parse_ms(candle.get("candle_close_time"))
        available_ms = parse_ms(candle.get("available_at"))
        if close_ms is None or available_ms is None:
            continue
        pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
        by_pair.setdefault(pair, []).append((int(close_ms), int(available_ms), candle))
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for pair, rows in by_pair.items():
        rows.sort(key=lambda item: (item[0], item[1]))
        index[pair] = {
            "close_times": [item[0] for item in rows],
            "rows": rows,
        }
    return index


def _latest_indexed_candle_at_or_before(
    index: dict[tuple[str, str], dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    decision_ms: int,
) -> tuple[dict[str, Any] | None, str | None]:
    bucket = index.get((str(symbol).upper(), str(timeframe)))
    if not bucket:
        return None, "MISSING_CLOSED_CANDLE"
    close_times = bucket["close_times"]
    rows = bucket["rows"]
    pos = bisect.bisect_right(close_times, int(decision_ms)) - 1
    saw_future_available = False
    while pos >= 0:
        _close_ms, available_ms, candle = rows[pos]
        if available_ms <= decision_ms:
            return dict(candle), None
        saw_future_available = True
        pos -= 1
    return None, "AVAILABLE_AT_AFTER_DECISION" if saw_future_available else "MISSING_CLOSED_CANDLE"


def _mtf_snapshot_from_feature_index(
    *,
    symbol: str,
    decision_time: str,
    mtf_index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    decision_ms = parse_ms(decision_time)
    if decision_ms is None:
        return {
            "decision_id": "decision_missing",
            "mtf_snapshot_id": "mtf_missing",
            "valid": False,
            "reject_reasons": ["DECISION_TIME_MISSING"],
            "selected_candles": {},
            "all_tf_candle_timestamps": [],
            "all_source_event_times": [],
            "source_hashes": [],
        }
    selected: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    reject_reasons: list[str] = []
    for timeframe in REQUIRED_DECISION_TIMEFRAMES:
        candle, reason = _latest_indexed_candle_at_or_before(
            mtf_index,
            symbol=symbol,
            timeframe=timeframe,
            decision_ms=int(decision_ms),
        )
        if candle is None:
            missing.append(timeframe)
            if reason == "AVAILABLE_AT_AFTER_DECISION":
                reject_reasons.append(f"AVAILABLE_AT_AFTER_DECISION_{timeframe}")
            else:
                reject_reasons.append(f"MISSING_CLOSED_CANDLE_{timeframe}")
            continue
        selected[timeframe] = candle
    close_times = [parse_ms(row.get("candle_close_time") or row.get("close_time")) for row in selected.values()]
    feature_cutoff = min([value for value in close_times if value is not None], default=None)
    snapshot_body = {
        "symbol": str(symbol).upper(),
        "decision_time": int(decision_ms),
        "feature_cutoff": feature_cutoff,
        "selected_candles": {
            timeframe: {
                "candle_id": row.get("candle_id") or canonical_candle_id(row),
                "candle_open_time": row.get("candle_open_time") or row.get("open_time"),
                "candle_close_time": row.get("candle_close_time") or row.get("close_time"),
                "available_at": row.get("available_at"),
                "is_closed": row.get("is_closed") is True or row.get("closed_candle") is True,
                "event_time": row.get("event_time"),
                "source": row.get("source"),
                "raw_payload_hash": row.get("raw_payload_hash"),
                "source_snapshot_id": row.get("source_snapshot_id"),
            }
            for timeframe, row in selected.items()
        },
        "missing_timeframes": missing,
        "gap_flags": sorted(set(reject_reasons)),
    }
    snapshot_id = stable_hash(snapshot_body)[:24]
    return {
        "decision_id": f"decision_{snapshot_id}",
        "mtf_snapshot_id": f"mtf_{snapshot_id}",
        **snapshot_body,
        "valid": not reject_reasons,
        "reject_reasons": sorted(set(reject_reasons)),
        "all_tf_candle_timestamps": [
            row.get("candle_close_time") or row.get("close_time") for row in selected.values()
        ],
        "all_source_event_times": [row.get("event_time") for row in selected.values() if row.get("event_time") is not None],
        "source_hashes": [row.get("raw_payload_hash") for row in selected.values() if row.get("raw_payload_hash")],
        "source": "FEATURE_SNAPSHOT_ARCHIVE_MTF_INDEX",
    }


def build_temporal_split_manifest(decision_times: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Return non-authoritative bootstrap status, never a holdout manifest.

    Only the hybrid runtime knows the exact rows that actually entered a
    checkpoint optimizer. A bootstrap-time fractional split cannot bind that
    inventory and must not be published where the persistent verifier could
    mistake it for checkpoint-specific authority.
    """

    observed = sorted((str(ts), str(sample_id)) for ts, sample_id in decision_times)
    return {
        "schema_version": "trusted_replay_holdout_manifest_producer_status_v1",
        "generated_utc": utc_now(),
        "status": "BLOCKED_RUNTIME_CHECKPOINT_BINDING_REQUIRED",
        "observed_bootstrap_rows": len(observed),
        "observed_decision_time_sample_sha256": hashlib.sha256(
            json.dumps(
                observed,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
        "authoritative_manifest_published": False,
        "legacy_v1_manifest_published": False,
        "static_fractional_split_used": False,
        "equal_decision_timestamps_partitioned": False,
        "required_producer": "HYBRID_RUNTIME_POST_OPTIMIZER_CHECKPOINT_BINDING",
    }


def _quarantine_legacy_v1_manifest(output_dir: Path) -> str | None:
    manifest_path = output_dir / "trusted_replay_train_validation_holdout_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema_version") != (
        "trusted_replay_train_validation_holdout_manifest_v1"
    ):
        return None
    quarantine_path = output_dir / (
        "trusted_replay_train_validation_holdout_manifest.legacy_v1_quarantined.json"
    )
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.replace(quarantine_path)
    return str(quarantine_path)


def _source_hashes(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    existing = snapshot.get("source_hashes")
    if isinstance(existing, Mapping) and existing:
        return dict(existing)
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    return {
        "feature_payload_hash": hashlib.sha256(
            json.dumps(features, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest(),
        "snapshot_payload_hash": hashlib.sha256(
            json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest(),
    }


def _snapshot_times(snapshot: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    decision_time = (
        snapshot.get("decision_time")
        or snapshot.get("decision_time_est")
        or snapshot.get("decision_cutoff_time_est")
        or snapshot.get("generated_utc")
        or snapshot.get("generated_at")
    )
    feature_cutoff = (
        snapshot.get("feature_cutoff")
        or snapshot.get("decision_cutoff_time_est")
        or snapshot.get("source_event_time_est")
        or snapshot.get("generated_utc")
        or snapshot.get("generated_at")
    )
    available_at = (
        snapshot.get("available_at")
        or snapshot.get("source_available_time")
        or snapshot.get("source_received_time_est")
        or snapshot.get("generated_utc")
        or snapshot.get("generated_at")
    )
    return (
        str(feature_cutoff) if feature_cutoff not in (None, "") else None,
        str(decision_time) if decision_time not in (None, "") else None,
        str(available_at) if available_at not in (None, "") else None,
    )


def _mtf_snapshot_for(
    loader: V2HybridTrainerDataLoader,
    *,
    symbol: str,
    decision_time: str,
    candle_cache: dict[tuple[str, str], Any],
    mtf_index: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if mtf_index:
        indexed = _mtf_snapshot_from_feature_index(
            symbol=symbol,
            decision_time=decision_time,
            mtf_index=mtf_index,
        )
        if indexed.get("valid") is True:
            return indexed
    candles_by_timeframe: dict[str, Any] = {}
    for timeframe in REQUIRED_DECISION_TIMEFRAMES:
        cache_key = (symbol, timeframe)
        if cache_key not in candle_cache:
            candle_cache[cache_key], _key = loader._read_closed_candle_series(  # noqa: SLF001
                symbol=symbol,
                timeframe=timeframe,
            )
        candles_by_timeframe[timeframe] = candle_cache[cache_key]
    return build_multi_timeframe_decision_snapshot(
        symbol=symbol,
        decision_time=decision_time,
        candles_by_timeframe=candles_by_timeframe,
    )


def archive_record_from_redis_snapshot(
    snapshot: Mapping[str, Any],
    *,
    loader: V2HybridTrainerDataLoader,
    candle_cache: dict[tuple[str, str], Any] | None = None,
    mtf_index: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    snapshot_id = snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id")
    symbol = str(snapshot.get("symbol") or "").upper()
    timeframe = str(snapshot.get("timeframe") or "")
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    feature_cutoff, decision_time, available_at = _snapshot_times(snapshot)
    if snapshot_id in (None, ""):
        reasons.append("SNAPSHOT_ID_MISSING")
    if not symbol:
        reasons.append("SYMBOL_MISSING")
    if not timeframe:
        reasons.append("TIMEFRAME_MISSING")
    if not features:
        reasons.append("FEATURES_EMPTY")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    feature_cutoff_dt = parse_utc(feature_cutoff)
    decision_time_dt = parse_utc(decision_time)
    available_at_dt = parse_utc(available_at)
    if feature_cutoff_dt is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if decision_time_dt is None:
        reasons.append("DECISION_TIME_MISSING")
    if available_at_dt is None:
        reasons.append("AVAILABLE_AT_MISSING")
    if feature_cutoff_dt is not None and decision_time_dt is not None and feature_cutoff_dt > decision_time_dt:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_at_dt is not None and decision_time_dt is not None and available_at_dt > decision_time_dt:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if reasons:
        return None, sorted(set(reasons))
    assert snapshot_id is not None and feature_cutoff is not None and decision_time is not None and available_at is not None
    mtf = _mtf_snapshot_for(
        loader,
        symbol=symbol,
        decision_time=decision_time,
        candle_cache=candle_cache if candle_cache is not None else {},
        mtf_index=mtf_index,
    )
    if mtf.get("valid") is not True:
        return None, [f"MTF_SNAPSHOT:{reason}" for reason in (mtf.get("reject_reasons") or ["INVALID"])]
    missing_names = snapshot.get("missing_feature_flags") or snapshot.get("missing_feature_names") or []
    stale_names = snapshot.get("stale_feature_flags") or snapshot.get("stale_feature_names") or []
    record = build_archive_record(
        snapshot_id=snapshot_id,
        symbol=symbol,
        timeframe=timeframe,
        feature_cutoff=feature_cutoff,
        decision_time=decision_time,
        available_at=available_at,
        mtf_snapshot_id=mtf.get("mtf_snapshot_id"),
        features=features,
        missing_mask=missing_names,
        stale_mask=stale_names,
        source_availability=snapshot.get("categories_present") or snapshot.get("external_v2_sources_present") or {},
        source_hashes=_source_hashes(snapshot),
        created_at=snapshot.get("generated_utc") or snapshot.get("generated_at") or utc_now(),
        extra={
            "decision_id": mtf.get("decision_id"),
            "mtf_snapshot_valid": True,
            "multi_timeframe_decision_snapshot": mtf,
            "candle_closed_confirmed": True,
            "latest_unclosed_kline_excluded": snapshot.get("latest_unclosed_kline_excluded"),
            "feature_freshness_state": snapshot.get("feature_freshness_state"),
            "source_redis_snapshot_key": snapshot.get("source_redis_snapshot_key"),
        },
    )
    return record, []


def bootstrap_trusted_replay_dataset(
    *,
    client: Any,
    repo_root: Path,
    scan_limit: int = 25_000,
    replay_limit: int = 20_000,
    archive_root: Path | None = None,
    import_from_redis: bool = True,
) -> dict[str, Any]:
    archive_root = archive_root or default_archive_root(repo_root)
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(client=client),
        trusted_replay_archive_root=archive_root,
        canonical_5m_label_archive_path=(
            default_canonical_5m_label_archive_path(repo_root)
        ),
    )
    snapshot_keys = _scan_keys(client, "v2:features:snapshot:*", limit=scan_limit) if import_from_redis else []
    mtf_index = _build_feature_snapshot_candle_index(client, keys=snapshot_keys) if import_from_redis else {}
    import_rejections: Counter[str] = Counter()
    imported = 0
    already_present = 0
    candle_cache: dict[tuple[str, str], Any] = {}
    if import_from_redis:
        for key in snapshot_keys:
            snapshot = _json_for_key(client, key)
            if not isinstance(snapshot, dict):
                continue
            snapshot = dict(snapshot)
            snapshot["source_redis_snapshot_key"] = key
            record, reasons = archive_record_from_redis_snapshot(
                snapshot,
                loader=loader,
                candle_cache=candle_cache,
                mtf_index=mtf_index,
            )
            if record is None:
                import_rejections.update(reasons)
                continue
            try:
                result = append_snapshot(record, root=archive_root, update_checksum_manifest=False)
            except SnapshotArchiveError as exc:
                import_rejections.update([str(exc)])
                continue
            imported += 0 if result.already_present else 1
            already_present += 1 if result.already_present else 0
        write_checksum_manifest(archive_root)

    # Bootstrap is a historical replay operation.  It must not relabel old
    # snapshots from the mutable, short-retention Redis 5m frontier; the
    # backfill lane stays fail-closed until a durable time-indexed canonical
    # finalized-5m label archive is available.
    replay_examples = loader.load_trusted_replay_examples(
        limit=replay_limit,
        backfill=True,
    )
    replay_scan = dict(loader.last_trusted_replay_backfill_scan)
    replay_rejections: Counter[str] = Counter(
        {
            str(reason): int(count)
            for reason, count in dict(
                replay_scan.get("rejection_reasons") or {}
            ).items()
        }
    )
    label_counts: Counter[str] = Counter()
    symbols: set[str] = set()
    timeframes: set[str] = set()
    decision_times: list[tuple[str, str]] = []
    for example in replay_examples:
        row = example.trust_row or {}
        label_counts[str(row.get("target_action") or "unknown")] += 1
        symbols.add(example.symbol)
        timeframes.add(example.timeframe)
        decision_times.append((str(row.get("decision_time") or ""), str(row.get("sample_id") or "")))
    split_manifest_status = build_temporal_split_manifest(decision_times)
    point_in_time = {
        "schema_version": "trusted_replay_point_in_time_validation_v1",
        "generated_utc": utc_now(),
        "accepted_rows": len(replay_examples),
        "future_labels_not_in_feature_tensor": all(
            bool((example.trust_row or {}).get("future_labels_not_in_feature_tensor"))
            for example in replay_examples
        ),
        "available_at_after_decision_rejected": import_rejections.get("AVAILABLE_AT_AFTER_DECISION_TIME", 0),
        "open_candle_rejected": import_rejections.get("OPEN_CANDLE_REJECTED", 0),
        "snapshot_hash_mismatch_rejected": sum(
            count
            for reason, count in import_rejections.items()
            if "CONTENT_SHA256_MISMATCH" in reason
        ),
        "rejections_by_reason": dict(import_rejections + replay_rejections),
    }
    label_distribution = {
        "schema_version": "trusted_replay_label_distribution_v1",
        "generated_utc": utc_now(),
        "row_count": len(replay_examples),
        "target_action_counts": dict(label_counts),
        "positive_directional_labels": label_counts.get("long", 0),
        "negative_directional_labels": label_counts.get("short", 0),
        "hold_labels": label_counts.get("hold", 0),
        "both_positive_and_negative_directional_labels": bool(
            label_counts.get("long", 0) > 0 and label_counts.get("short", 0) > 0
        ),
    }
    dataset_status = {
        "schema_version": "trusted_replay_dataset_status_v1",
        "generated_utc": utc_now(),
        "archive_root": str(archive_root),
        "redis_snapshot_import_enabled": bool(import_from_redis),
        "redis_snapshot_scan_limit": int(scan_limit),
        "redis_snapshots_scanned": len(snapshot_keys),
        "redis_snapshots_imported": imported,
        "redis_snapshots_already_present": already_present,
        "trusted_replay_rows": len(replay_examples),
        "trusted_replay_rows_requirement": 10_000,
        "trusted_replay_rows_requirement_met": len(replay_examples) >= 10_000,
        "symbols": sorted(symbols),
        "symbol_count": len(symbols),
        "symbol_count_requirement_met": len(symbols) >= 50,
        "timeframes": sorted(timeframes),
        "all_required_timeframes_present": all(tf in timeframes for tf in ("1m", "5m", "15m", "1h", "4h")),
        "label_distribution": label_distribution,
        "import_rejections_by_reason": dict(import_rejections),
        "replay_rejections_by_reason": dict(replay_rejections),
        "trusted_replay_scan": replay_scan,
        "historical_label_source_status": replay_scan.get("status"),
        "required_historical_label_source": (
            "DURABLE_TIME_INDEXED_CANONICAL_FINALIZED_5M_CANDLE_ARCHIVE"
        ),
        "same_timeframe_label_fallback_used": False,
        "mutable_redis_history_used_for_historical_labels": False,
        "learning_lane": "OUTCOME_SUPERVISED_TRUSTED_REPLAY",
        "ppo_objective_used": False,
        "live_or_exchange_mutation": False,
    }

    operator_dir = repo_root / "v2/frontend/public" / ARTIFACT_REL
    goal_dir = repo_root / "goal_state" / GOAL_ID
    worklog_dir = repo_root / "claude_worklog/final_readiness" / GOAL_ID / "latest"
    archive_rollover = rollover_archive(root=archive_root)
    archive_artifacts = publish_status_artifacts(
        output_dir=operator_dir,
        root=archive_root,
        rollover_status=archive_rollover,
    )
    quarantined_legacy_manifests: list[str] = []
    for output_dir in (operator_dir, goal_dir, worklog_dir):
        if output_dir != operator_dir:
            for name, payload in archive_artifacts.items():
                _write_json(output_dir / name, payload)
        _write_json(output_dir / "trusted_replay_dataset_status.json", dataset_status)
        _write_json(output_dir / "trusted_replay_point_in_time_validation.json", point_in_time)
        _write_json(output_dir / "trusted_replay_label_distribution.json", label_distribution)
        quarantined = _quarantine_legacy_v1_manifest(output_dir)
        if quarantined is not None:
            quarantined_legacy_manifests.append(quarantined)
        _write_json(
            output_dir
            / "trusted_replay_train_validation_holdout_manifest_status.json",
            {
                **split_manifest_status,
                "legacy_v1_manifest_quarantined": quarantined is not None,
                "legacy_v1_manifest_quarantine_path": quarantined,
            },
        )
    return {
        "dataset_status": dataset_status,
        "point_in_time": point_in_time,
        "label_distribution": label_distribution,
        "split_manifest_status": split_manifest_status,
        "quarantined_legacy_manifests": quarantined_legacy_manifests,
        "archive_status": build_archive_status(root=archive_root),
        "reference_retention_status": build_reference_retention_status(root=archive_root),
        "archive_rollover_status": archive_rollover,
    }
