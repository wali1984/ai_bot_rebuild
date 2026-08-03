"""V2 trainer training live loop.

Continuously rebuilds the V2-native trainer dataset from V2-owned Redis keys
and replay labels, evaluates the native baseline model, and publishes a V2-only
training heartbeat. It does not place orders, does not write legacy Redis, and
does not overwrite the production inference predictions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.baseline_model import (
    evaluate_all_baselines,
)
from v2.backend.app.services.native_trainer.dataset_builder import (
    V2OnlyReader,
    _index_labels_by_snapshot,
    build_dataset_for_universe,
    build_quality_report,
    build_rows_from_replay_bundles,
    default_dataset_paths,
    default_replay_bundles_path,
    emit_dataset_artifacts,
    load_label_rows,
)
from v2.backend.app.services.native_trainer.packet import (
    default_packet_paths,
    emit_packet,
)

V2_REDIS_PREFIX = "v2:"
WORKER_ID = "v2_trainer_training_live_loop"
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime"
    / WORKER_ID
    / "latest"
    / f"{WORKER_ID}_status.json"
)
LOCAL_STATUS = (
    REPO_ROOT
    / "v2/runtime"
    / WORKER_ID
    / "latest"
    / f"{WORKER_ID}_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _reader_from_client(client: Any | None) -> V2OnlyReader:
    return V2OnlyReader(client=client)


def _safe_set_v2(client: Any | None, key: str, value: str, *, ex: int) -> bool:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        client.set(key, value, ex=int(ex))
        return True
    except Exception:
        return False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_once(
    *,
    repo_root: Path = REPO_ROOT,
    minimum_train_rows: int = 64,
    max_label_rows: int | None = None,
    write_v2_redis: bool = True,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    training_observed_at = datetime.now(timezone.utc)
    started = training_observed_at.isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    client = _connect_redis()
    reader = _reader_from_client(client)
    dataset_paths = default_dataset_paths(repo_root)
    packet_paths = default_packet_paths(repo_root)
    replay_bundles_path = default_replay_bundles_path(repo_root)

    labels = load_label_rows(
        replay_bundles_path,
        max_rows=max_label_rows,
        training_observed_at=training_observed_at,
    )
    label_index = _index_labels_by_snapshot(labels)
    build_result = build_dataset_for_universe(
        reader=reader,
        label_rows_by_snapshot=label_index,
        training_observed_at=training_observed_at,
    )
    replay_rows = build_rows_from_replay_bundles(
        replay_bundles_path,
        max_rows=max_label_rows,
        training_observed_at=training_observed_at,
    )
    build_result.rows.extend(replay_rows)
    quality = build_quality_report(build_result.rows)
    emit_dataset_artifacts(
        paths=dataset_paths,
        result=build_result,
        quality=quality,
    )

    eval_result = evaluate_all_baselines(
        build_result.rows,
        minimum_train_rows=minimum_train_rows,
    )
    packet_result = emit_packet(
        paths=packet_paths,
        build_result=build_result,
        quality=quality,
        eval_result=eval_result,
        publisher_result=None,
    )

    trained_model_available = eval_result.trained_model is not None
    classification = (
        "V2_TRAINER_TRAINING_LIVE_OK"
        if trained_model_available and quality.train_rows >= minimum_train_rows
        else "V2_TRAINER_TRAINING_LIVE_INSUFFICIENT_TRAIN_ROWS"
    )
    payload: dict[str, Any] = {
        "worker_id": WORKER_ID,
        "schema_version": "v2_trainer_training_live_loop_v1",
        "started_at": started,
        "finished_at": _utc_iso(),
        "classification": classification,
        "training_loop_active": True,
        "dataset_rebuilt": True,
        "baseline_evaluated": True,
        "trained_model_available": trained_model_available,
        "publishable_baseline_available": eval_result.publishable_baseline_available,
        "baseline_predictions_published": False,
        "production_prediction_writer": "v2_rl_core_inference_loop",
        "row_count": len(build_result.rows),
        "train_rows": quality.train_rows,
        "validation_rows": quality.validation_rows,
        "labels_loaded": build_result.labels_loaded,
        "replay_rows_loaded": len(replay_rows),
        "minimum_train_rows": int(minimum_train_rows),
        "minimum_sample_satisfied": quality.minimum_sample_satisfied,
        "symbol_resolution": build_result.symbol_resolution,
        "universe_count": len(build_result.universe),
        "universe": list(build_result.universe),
        "timeframes": list(build_result.timeframes),
        "non_v2_read_attempts": build_result.non_v2_read_attempts,
        "read_errors": build_result.read_errors,
        "go_no_go": packet_result.go_no_go,
        "packet_paths_written": [str(p) for p in packet_result.paths_written],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "trader_execution_enabled": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "writes_legacy_redis": False,
        "old_redis_write_attempts": 0,
    }

    keys_written: list[str] = []
    if write_v2_redis:
        body = json.dumps(payload, sort_keys=True)
        for key in (
            f"{V2_REDIS_PREFIX}trainer:training:heartbeat",
            f"{V2_REDIS_PREFIX}trainer:training:status",
        ):
            if _safe_set_v2(client, key, body, ex=ttl_seconds):
                keys_written.append(key)
    payload["redis_ok"] = client is not None
    payload["v2_redis_keys_written"] = keys_written
    payload["v2_redis_keys_written_count"] = len(keys_written)
    for path in (PUBLIC_STATUS, LOCAL_STATUS):
        _write_json(path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_trainer_training_live_loop")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--minimum-train-rows", type=int, default=64)
    parser.add_argument("--max-label-rows", type=int, default=None)
    parser.add_argument("--no-redis-write", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    while True:
        payload = run_once(
            minimum_train_rows=int(args.minimum_train_rows),
            max_label_rows=args.max_label_rows,
            write_v2_redis=not args.no_redis_write,
            ttl_seconds=int(args.v2_redis_ttl_seconds),
        )
        if not args.loop:
            print(json.dumps({
                "classification": payload["classification"],
                "row_count": payload["row_count"],
                "train_rows": payload["train_rows"],
                "validation_rows": payload["validation_rows"],
                "trained_model_available": payload["trained_model_available"],
                "v2_redis_keys_written_count": payload["v2_redis_keys_written_count"],
            }, indent=2, sort_keys=True))
            return 0 if payload["classification"] == "V2_TRAINER_TRAINING_LIVE_OK" else 1
        time.sleep(max(30, int(args.interval_seconds)))


if __name__ == "__main__":
    sys.exit(main())
