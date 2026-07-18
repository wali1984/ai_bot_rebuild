#!/usr/bin/env python3
"""Build guardian PIT prediction coverage artifacts from current V2 predictions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.continuous_edge_guardian.guardian import (  # noqa: E402
    ContinuousEdgeGuardianPaths,
)
from v2.backend.app.services.continuous_edge_guardian.pit_prediction_counter import (  # noqa: E402
    DEFAULT_GUARDIAN_PIT_ARCHIVE_CONSUMER_BATCH_ROWS,
    DEFAULT_TIMEFRAMES,
    REDIS_HOT_CACHE_OBSERVATION_KEY,
    REDIS_STATUS_KEY,
    blocker_projection,
    collect_hot_cache_prediction_rows,
    collect_prediction_rows,
    consume_durable_guardian_pit_archive,
    coverage_status_from_archive_consumer,
    dedupe_records,
    maturity_queue,
    update_holdout_manifest,
    utc_now,
)


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=5)


def _read_json(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_symbols(client: Any) -> list[str]:
    latest_positive = _read_json(client, "v2:strategy_supply:latest_positive_summary")
    positive_symbols = [
        str(symbol).strip().upper()
        for symbol in latest_positive.get("positive_symbols") or []
        if str(symbol).strip()
    ]
    symbols = set(positive_symbols)
    try:
        from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

        symbols.update(
            str(symbol).strip().upper()
            for symbol in resolve_symbols()
            if str(symbol).strip()
        )
    except Exception:
        pass
    if symbols:
        return sorted(symbols)
    return ["BTCUSDT", "ETHUSDT"]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="guardian_pit_prediction_counter")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--archive-path", default="")
    parser.add_argument("--source-sqlite-archive-path", default="")
    parser.add_argument(
        "--archive-consumer-batch-rows",
        type=int,
        default=DEFAULT_GUARDIAN_PIT_ARCHIVE_CONSUMER_BATCH_ROWS,
    )
    parser.add_argument("--manifest-path", default="")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--timeframes", nargs="*", default=list(DEFAULT_TIMEFRAMES))
    parser.add_argument("--publish-redis", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    generated_utc = utc_now()
    output_dir = Path(args.output_dir)
    archive_path = Path(args.archive_path) if args.archive_path else output_dir / "guardian_pit_predictions_append_only.jsonl"
    source_sqlite_archive_path = (
        Path(args.source_sqlite_archive_path)
        if args.source_sqlite_archive_path
        else Path(
            os.getenv(
                "V2_GUARDIAN_PIT_ARCHIVE_PATH",
                str(REPO_ROOT / ".local_data/v2_guardian/pit_prediction_observations.sqlite3"),
            )
        )
    )
    manifest_path = (
        Path(args.manifest_path)
        if args.manifest_path
        else ContinuousEdgeGuardianPaths(repo_root=REPO_ROOT).holdout_manifest_path
    )
    client = _redis_client(str(args.redis_url))
    symbols = (
        sorted({str(symbol).strip().upper() for symbol in args.symbols if str(symbol).strip()})
        if args.symbols
        else _default_symbols(client)
    )
    timeframes = tuple(str(tf).strip() for tf in args.timeframes if str(tf).strip())

    durable_valid_rows, archive_consumption = consume_durable_guardian_pit_archive(
        source_archive_path=source_sqlite_archive_path,
        guardian_coverage_archive_path=archive_path,
        allowed_timeframes=timeframes,
        batch_rows=int(args.archive_consumer_batch_rows),
        generated_utc=generated_utc,
    )
    latest_valid_rows, latest_rejected_rows = collect_prediction_rows(client, symbols=symbols, timeframes=timeframes)
    hot_cache_valid_rows, hot_cache_rejected_rows = collect_hot_cache_prediction_rows(
        client,
        timeframes=timeframes,
    )
    # SQLite is authoritative. Redis rows remain useful diagnostics, but are
    # never a substitute for advancing the hash-verified durable cursor.
    valid_rows = dedupe_records(durable_valid_rows)
    rejected_rows = [*latest_rejected_rows, *hot_cache_rejected_rows]
    if str(archive_consumption.get("status") or "").startswith("BLOCKED_"):
        rejected_rows.append(
            {
                "source": "durable_guardian_pit_sqlite_archive",
                "reasons": list(archive_consumption.get("block_reasons") or []),
            }
        )
    appended = int(
        archive_consumption.get("guardian_coverage_archive_rows_appended_this_cycle")
        or 0
    )
    status = coverage_status_from_archive_consumer(
        archive_consumer_status=archive_consumption,
        current_valid_rows=valid_rows,
        rejected_rows=rejected_rows,
        new_rows_appended=appended,
        generated_utc=generated_utc,
    )
    status["archive_path"] = str(archive_path)
    status["source_sqlite_archive_path"] = str(source_sqlite_archive_path)
    status["durable_archive_consumption"] = archive_consumption
    status["manifest_path"] = str(manifest_path)
    status["symbol_source"] = "strategy_supply_latest_positive_summary_plus_runtime_universe"
    status["requested_symbol_count"] = len(symbols)
    status["requested_timeframes"] = list(timeframes)
    status["latest_key_cycle_valid_prediction_count"] = len(latest_valid_rows)
    status["latest_key_role"] = "DIAGNOSTIC_NOT_DURABLE_COVERAGE_SOURCE"
    status["redis_hot_cache_cycle_valid_prediction_count"] = len(hot_cache_valid_rows)
    status["redis_hot_cache_cycle_rejected_prediction_count"] = len(hot_cache_rejected_rows)
    status["redis_hot_cache_key"] = REDIS_HOT_CACHE_OBSERVATION_KEY
    status["redis_hot_cache_role"] = "BOUNDED_CACHE_NOT_DURABLE_APPEND_ONLY_ARCHIVE"
    status["durable_archive_role"] = (
        "SQLITE_HASH_VERIFIED_SOURCE_CONSUMED_IN_BOUNDED_BATCHES_INTO_GUARDIAN_JSONL"
    )
    status["combined_cycle_valid_prediction_count"] = len(valid_rows)
    if str(archive_consumption.get("status") or "").startswith("BLOCKED_"):
        status["status"] = "BLOCKED_DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION"
        status["exact_blocker"] = "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_FAILED_CLOSED"

    manifest = update_holdout_manifest(manifest_path, status, generated_utc=generated_utc)
    queue = maturity_queue(status, archive_path=archive_path, generated_utc=generated_utc)
    projection = blocker_projection(status, generated_utc=generated_utc)
    phase7 = {
        "schema_version": "phase7_guardian_holdout_acceleration_status_v1",
        "generated_utc": generated_utc,
        "status": projection["status"],
        "exact_blocker": projection["exact_blocker"],
        "prediction_publisher_growth_observed": appended > 0,
        "current_cycle_valid_prediction_count": status["current_cycle_valid_prediction_count"],
        "point_in_time_valid_prediction_count": status["point_in_time_valid_prediction_count"],
        "guardian_manifest_updated": True,
        "guardian_manifest_path": str(manifest_path),
        "manifest_status": manifest.get("status"),
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "places_real_order": False,
        "routes_to_live": False,
        "test_order_submitted": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "durable_archive_consumption": archive_consumption,
    }
    if str(archive_consumption.get("status") or "").startswith("BLOCKED_"):
        phase7["status"] = "GUARDIAN_DURABLE_ARCHIVE_CONSUMPTION_BLOCKED_FAIL_CLOSED"
        phase7["exact_blocker"] = "DURABLE_GUARDIAN_PIT_ARCHIVE_CONSUMPTION_FAILED_CLOSED"

    _write_json(output_dir / "guardian_pit_prediction_growth_status.json", status)
    _write_json(output_dir / "guardian_holdout_maturity_queue.json", queue)
    _write_json(output_dir / "guardian_holdout_blocker_projection.json", projection)
    _write_json(output_dir / "phase7_pit_prediction_counter.json", status)
    _write_json(output_dir / "phase7_guardian_holdout_acceleration_status.json", phase7)

    redis_publish = {"status": "SKIPPED"}
    if args.publish_redis:
        try:
            client.set(REDIS_STATUS_KEY, json.dumps(status, sort_keys=True, default=str))
            redis_publish = {"status": "PUBLISHED", "key": REDIS_STATUS_KEY}
        except Exception as exc:  # noqa: BLE001
            redis_publish = {"status": f"FAILED:{type(exc).__name__}", "key": REDIS_STATUS_KEY}
    phase7["redis_publish"] = redis_publish
    _write_json(output_dir / "phase7_guardian_holdout_acceleration_status.json", phase7)
    return phase7


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if str((result.get("durable_archive_consumption") or {}).get("status") or "").startswith(
        "BLOCKED_"
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
