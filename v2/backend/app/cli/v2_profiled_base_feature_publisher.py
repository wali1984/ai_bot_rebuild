"""CLI loop for authenticated quarantined 35-feature base publication."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.profiled_base_feature_publisher_v1 import (
    DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS,
    ProfiledBaseFeaturePublisherV1,
    ProfiledBaseFeaturePublisherV1Error,
)

_STOP = False


def _request_stop(_signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not parsed > 0 or parsed in {float("inf"), float("-inf")}:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish authenticated 35-feature OHLCV profile records to the durable "
            "quarantined evidence ledger. This command never writes legacy feature "
            "keys and grants no trainer, prediction, paper, or live authority."
        )
    )
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(
            os.environ.get(
                "PROFILED_BASE_PUBLISHER_DATA_ROOT",
                ".local_data/v2_native_trainer/profiled_base_publisher_v1",
            )
        ),
    )
    parser.add_argument(
        "--feature-ledger-path",
        type=Path,
        default=Path(
            os.environ.get(
                "PROFILED_BASE_FEATURE_LEDGER_PATH",
                ".local_data/v2_native_trainer/durable_feature_snapshot_ledger.sqlite3",
            )
        ),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=(
            Path(value) if (value := os.environ.get("PROFILED_BASE_PUBLISHER_STATE_PATH")) else None
        ),
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=(
            Path(value)
            if (value := os.environ.get("PROFILED_BASE_PUBLISHER_STATUS_PATH"))
            else None
        ),
    )
    parser.add_argument(
        "--cycle-seconds",
        type=_positive_float,
        default=_positive_float(os.environ.get("PROFILED_BASE_PUBLISHER_CYCLE_SECONDS", "300")),
        help="service cadence used by the adaptive observed-latency workload controller",
    )
    parser.add_argument(
        "--boundary-retries",
        type=_positive_int,
        default=_positive_int(os.environ.get("PROFILED_BASE_PUBLISHER_BOUNDARY_RETRIES", "2")),
        help="bounded integrity retry count for a candle-boundary read race",
    )
    parser.add_argument(
        "--resource-horizon-seconds",
        type=_positive_float,
        default=_positive_float(
            os.environ.get(
                "PROFILED_BASE_PUBLISHER_RESOURCE_HORIZON_SECONDS",
                str(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
            )
        ),
        help=(
            "resource-only disk sustainability horizon used to derive the per-cycle "
            "evidence write budget (minimum 90 days) above the immutable shared-disk "
            "reserve; it never classifies a market"
        ),
    )
    parser.add_argument("--once", action="store_true")
    return parser


def _absolute(path: Path | None) -> Path | None:
    return None if path is None else path.expanduser().resolve(strict=False)


def _raw_redis_client(redis_url: str) -> object:
    try:
        import redis
    except ImportError as exc:
        raise ProfiledBaseFeaturePublisherV1Error(
            "PROFILED_BASE_PUBLISHER_REDIS_LIBRARY_UNAVAILABLE"
        ) from exc
    try:
        client = redis.Redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_timeout=30.0,
            health_check_interval=30,
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001 - credentials/transport must not leak
        raise ProfiledBaseFeaturePublisherV1Error(
            "PROFILED_BASE_PUBLISHER_REDIS_CONNECTION_FAILED"
        ) from exc
    return client


def bounded_cycle_summary(status: dict[str, Any], *, status_path: Path) -> dict[str, Any]:
    """Return a constant-shape journal record; full evidence stays in the status file."""

    resource = status.get("resource_decision")
    resource_summary = {}
    if type(resource) is dict:
        resource_summary = {
            "estimated_evidence_bytes_per_symbol": resource.get(
                "estimated_evidence_bytes_per_symbol"
            ),
            "estimated_seconds_per_symbol": resource.get("estimated_seconds_per_symbol"),
            "sustainable_cycle_write_budget_bytes": resource.get(
                "sustainable_cycle_write_budget_bytes"
            ),
            "disk_reserve_policy": resource.get("disk_reserve_policy"),
            "disk_reserve_bytes": resource.get("disk_reserve_bytes"),
            "safe_disk_headroom_bytes": resource.get("safe_disk_headroom_bytes"),
            "disk_capacity_symbols": resource.get("disk_capacity_symbols"),
            "publication_latency_capacity_symbols": resource.get(
                "publication_latency_capacity_symbols"
            ),
            "bootstrap_observation_required": resource.get("bootstrap_observation_required"),
        }
    return {
        "schema_version": "profiled_base_feature_publisher_cli_cycle_summary_v1",
        "classification": status.get("classification"),
        "cycle_started_at": status.get("cycle_started_at"),
        "cycle_completed_at": status.get("cycle_completed_at"),
        "cycle_elapsed_seconds": status.get("cycle_elapsed_seconds"),
        "discovered_symbol_count": status.get("discovered_symbol_count"),
        "eligible_symbol_count": status.get("eligible_symbol_count"),
        "selected_symbol_count": status.get("selected_symbol_count"),
        "resource_deferred_symbol_count": status.get("resource_deferred_symbol_count"),
        "published_symbol_count": status.get("published_symbol_count"),
        "exact_replay_symbol_count": status.get("exact_replay_symbol_count"),
        "unchanged_symbol_count": status.get("unchanged_symbol_count"),
        "failed_symbol_count": status.get("failed_symbol_count"),
        "cycle_evidence_accounted_bytes": status.get("cycle_evidence_accounted_bytes"),
        "cycle_materialized_artifact_bytes": status.get("cycle_materialized_artifact_bytes"),
        "cycle_materialized_publication_count": status.get("cycle_materialized_publication_count"),
        "cycle_disk_consumption_high_water_bytes": status.get(
            "cycle_disk_consumption_high_water_bytes"
        ),
        "resource_decision": resource_summary,
        "status_sha256": status.get("status_sha256"),
        "full_status_path": str(status_path),
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = _raw_redis_client(str(args.redis_url))
        publisher = ProfiledBaseFeaturePublisherV1(
            redis_client=client,
            data_root=_absolute(args.data_root),
            feature_ledger_path=_absolute(args.feature_ledger_path),
            state_path=_absolute(args.state_path),
            status_path=_absolute(args.status_path),
            cycle_period_seconds=float(args.cycle_seconds),
            resource_sustainability_horizon_seconds=float(args.resource_horizon_seconds),
            boundary_retry_limit=int(args.boundary_retries),
        )
        signal.signal(signal.SIGINT, _request_stop)
        signal.signal(signal.SIGTERM, _request_stop)
        while not _STOP:
            started = time.monotonic()
            status = publisher.run_cycle()
            summary = bounded_cycle_summary(
                status,
                status_path=publisher.status_path,
            )
            print(
                json.dumps(
                    summary,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                flush=True,
            )
            if args.once:
                break
            remaining = max(0.0, float(args.cycle_seconds) - (time.monotonic() - started))
            deadline = time.monotonic() + remaining
            while not _STOP:
                wait = deadline - time.monotonic()
                if wait <= 0:
                    break
                time.sleep(min(wait, 1.0))
        return 0
    except ProfiledBaseFeaturePublisherV1Error as exc:
        payload = {
            "schema_version": "profiled_base_feature_publisher_cli_error_v1",
            "classification": "FAIL_CLOSED",
            "reasons": list(exc.reasons),
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
        }
        print(
            json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
