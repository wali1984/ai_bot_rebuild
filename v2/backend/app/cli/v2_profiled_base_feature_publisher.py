"""CLI loop for authenticated 35+4 or quarantined masked-cost publication."""

from __future__ import annotations

import argparse
import functools
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from v2.backend.app.services.binance_usdm_commission_evidence_broker import (
    CommissionEvidenceBrokerError,
    default_commission_broker_store,
    read_authenticated_commission_evidence,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    LeverageBracketEvidenceError,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_runtime_credentials import (
    consumer_security_context_from_systemd_credentials,
)
from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    capture_binance_usdm_commission_rate_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    FeatureSnapshotLedgerError,
    FeatureSnapshotWriterLease,
    FeatureSnapshotWriterLeaseError,
)
from v2.backend.app.services.native_trainer.profiled_base_feature_publisher_v1 import (
    AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE,
    BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE,
    DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS,
    MASKED_COST_OBSERVATION_MODE,
    ProfiledBaseFeaturePublisherV1,
    ProfiledBaseFeaturePublisherV1Error,
)
from v2.backend.app.services.native_trainer.profiled_base_publisher_runtime_credentials import (
    ProfiledBasePublisherCredentialError,
    load_profiled_base_publisher_runtime_credentials_if_available,
)

_STOP = False
_CONFIG_EXIT_STATUS = 78


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
            "Publish authenticated 35+4 profiled-training records, or a quarantined "
            "35-field parent with an explicit missing-cost mask when the complete optional "
            "credential bundle is absent. This command never writes legacy feature keys. "
            "An authenticated child may be trainer-admission eligible, but the publisher "
            "grants no trainer runtime transition, prediction, paper, or live authority."
        )
    )
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument(
        "--commission-broker-data-root",
        type=Path,
        default=(
            Path(value)
            if (value := os.environ.get("PROFILED_BASE_COMMISSION_BROKER_DATA_ROOT"))
            else None
        ),
        help=(
            "absolute broker CAS root; uses only the protected evidence-verification "
            "credential and never loads Binance API credentials"
        ),
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
            "observed_cycle_count": resource.get("observed_cycle_count"),
            "available_write_credit_bytes": resource.get(
                "available_write_credit_bytes"
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
    authority_semantics = status.get("authority_semantics")
    published_child_admission = (
        authority_semantics.get("published_child_trainer_admission_authorized")
        if type(authority_semantics) is dict
        else False
    )
    summary = {
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
        "masked_cost_observation_symbol_count": status.get(
            "masked_cost_observation_symbol_count"
        ),
        "masked_cost_observation_replay_symbol_count": status.get(
            "masked_cost_observation_replay_symbol_count"
        ),
        "unchanged_symbol_count": status.get("unchanged_symbol_count"),
        "failed_symbol_count": status.get("failed_symbol_count"),
        "cycle_evidence_accounted_bytes": status.get("cycle_evidence_accounted_bytes"),
        "cycle_materialized_artifact_bytes": status.get("cycle_materialized_artifact_bytes"),
        "cycle_materialized_publication_count": status.get("cycle_materialized_publication_count"),
        "cycle_disk_consumption_high_water_bytes": status.get(
            "cycle_disk_consumption_high_water_bytes"
        ),
        "cycle_owned_durable_growth_bytes": status.get(
            "cycle_owned_durable_growth_bytes"
        ),
        "resource_decision": resource_summary,
        "status_sha256": status.get("status_sha256"),
        "full_status_path": str(status_path),
        "publisher_runtime_authority_granted": False,
        "published_child_trainer_admission_authorized": (published_child_admission is True),
        "automatic_trainer_transition_authorized": False,
        "commission_cost_mode": status.get("commission_cost_mode"),
        "commission_credentials_available": (
            status.get("commission_credentials_available") is True
        ),
        "commission_broker_reader_available": (
            status.get("commission_broker_reader_available") is True
        ),
        "exchange_credentials_loaded_by_publisher": (
            status.get("exchange_credentials_loaded_by_publisher") is True
        ),
        "credential_ref_read_only_assertion": True,
        "credential_ref_read_only_assertion_semantics": (
            "OPERATOR_PROVISIONING_LABEL_NOT_BINANCE_PERMISSION_PROOF"
        ),
        "exchange_key_permissions_proven_by_connector": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    return {key: value for key, value in summary.items() if value is not None}


def _run_resident_loop(
    *,
    args: argparse.Namespace,
    publisher: ProfiledBaseFeaturePublisherV1,
) -> int:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if (
            args.commission_broker_data_root is not None
            and not args.commission_broker_data_root.is_absolute()
        ):
            raise ProfiledBaseFeaturePublisherV1Error(
                "PROFILED_BASE_PUBLISHER_COMMISSION_BROKER_DATA_ROOT_INVALID"
            )
        broker_data_root = _absolute(args.commission_broker_data_root)
        if broker_data_root is not None:
            broker_security_context = consumer_security_context_from_systemd_credentials()
            runtime_credentials = None
        else:
            broker_security_context = None
            runtime_credentials = (
                load_profiled_base_publisher_runtime_credentials_if_available()
            )
        client = _raw_redis_client(str(args.redis_url))
        publisher_arguments: dict[str, Any] = {
            "redis_client": client,
            "data_root": _absolute(args.data_root),
            "feature_ledger_path": _absolute(args.feature_ledger_path),
            "state_path": _absolute(args.state_path),
            "status_path": _absolute(args.status_path),
            "cycle_period_seconds": float(args.cycle_seconds),
            "resource_sustainability_horizon_seconds": float(
                args.resource_horizon_seconds
            ),
            "boundary_retry_limit": int(args.boundary_retries),
        }
        if broker_data_root is not None:
            broker_store = default_commission_broker_store(broker_data_root)
            publisher_arguments.update(
                {
                    "commission_cost_mode": (
                        BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
                    ),
                    "commission_evidence_reader": functools.partial(
                        read_authenticated_commission_evidence,
                        client,
                        store=broker_store,
                        security_context=broker_security_context,
                    ),
                }
            )
        elif runtime_credentials is None:
            publisher_arguments["commission_cost_mode"] = (
                MASKED_COST_OBSERVATION_MODE
            )
        else:
            publisher_arguments.update(
                {
                    "commission_cost_mode": (
                        AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE
                    ),
                    "commission_capture_function": functools.partial(
                        capture_binance_usdm_commission_rate_v1,
                        credential_binding=runtime_credentials.commission_binding,
                    ),
                    "commission_fingerprint_hmac_key": (
                        runtime_credentials.fingerprint_hmac_key
                    ),
                    "exchange_credentials_loaded_by_publisher": True,
                }
            )
        feature_ledger_path = publisher_arguments["feature_ledger_path"]
        if not isinstance(feature_ledger_path, Path):
            raise ProfiledBaseFeaturePublisherV1Error(
                "PROFILED_BASE_PUBLISHER_FEATURE_LEDGER_PATH_INVALID"
            )
        with FeatureSnapshotWriterLease.acquire(feature_ledger_path) as writer_lease:
            feature_ledger = DurableFeatureSnapshotLedger(
                feature_ledger_path,
                writer_lease=writer_lease,
            )
            feature_ledger.initialize()
            publisher_arguments["feature_ledger"] = feature_ledger
            publisher = ProfiledBaseFeaturePublisherV1(
                **publisher_arguments,
            )
            with feature_ledger.resident_wal_sidecar_guard():
                return _run_resident_loop(args=args, publisher=publisher)
    except (
        CommissionEvidenceBrokerError,
        FeatureSnapshotLedgerError,
        FeatureSnapshotWriterLeaseError,
        LeverageBracketEvidenceError,
        ProfiledBasePublisherCredentialError,
        ProfiledBaseFeaturePublisherV1Error,
    ) as exc:
        reasons = (
            [exc.reason]
            if isinstance(
                exc,
                ProfiledBasePublisherCredentialError
                | CommissionEvidenceBrokerError
            )
            else list(exc.reasons)
            if isinstance(exc, ProfiledBaseFeaturePublisherV1Error)
            else [str(exc)]
        )
        payload = {
            "schema_version": "profiled_base_feature_publisher_cli_error_v1",
            "classification": "FAIL_CLOSED",
            "reasons": reasons,
            "publisher_runtime_authority_granted": False,
            "published_child_trainer_admission_authorized": False,
            "automatic_trainer_transition_authorized": False,
            "credential_ref_read_only_assertion": True,
            "credential_ref_read_only_assertion_semantics": (
                "OPERATOR_PROVISIONING_LABEL_NOT_BINANCE_PERMISSION_PROOF"
            ),
            "exchange_key_permissions_proven_by_connector": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
        }
        print(
            json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
        return (
            _CONFIG_EXIT_STATUS
            if isinstance(
                exc,
                ProfiledBasePublisherCredentialError
                | CommissionEvidenceBrokerError
                | FeatureSnapshotLedgerError
                | FeatureSnapshotWriterLeaseError
                | LeverageBracketEvidenceError,
            )
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
