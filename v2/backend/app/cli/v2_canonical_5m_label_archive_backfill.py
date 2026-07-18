"""Resumable historical gap recovery for canonical finalized 5m labels.

The default is a no-write/no-network plan.  ``--execute-public-rest`` is an
explicit operator action and still requires the repository-wide Binance REST
fallback policy flag.  Only the public USD-M kline endpoint is reachable; no
credentials, orders, leverage, margin, balance, or position endpoint exists in
this command.

Range semantics are exact: ``--start-utc`` is inclusive and ``--end-utc`` is
exclusive, and both must be UTC 5-minute candle-open boundaries.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_repo = Path(__file__).resolve().parents[4]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from v2.backend.app.services.binance_unified_websocket_transport import (  # noqa: E402
    REST_FALLBACK_ENV,
    report_binance_rest_response,
    require_binance_rest_fallback,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (  # noqa: E402
    LABEL_SLOT_MILLISECONDS,
    default_archive_path,
)
from v2.backend.app.services.native_trainer.historical_canonical_5m_backfill import (  # noqa: E402
    MAX_LOCAL_REQUEST_WEIGHT_PER_UTC_MINUTE,
    MAX_REQUEST_WEIGHT_PER_RUN,
    BackfillJobSpec,
    BackfillRunBounds,
    BinanceKlineRequest,
    Historical5mBackfillError,
    PublicHttpResponse,
    UrllibPublicKlineTransport,
    WssAuthorityCutoffAttestation,
    historical_backfill_paths_alias,
    historical_backfill_sqlite_artifact_paths,
    job_spec_as_jsonable,
    run_historical_5m_backfill,
    validate_historical_backfill_state_path,
)


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _parse_utc_boundary(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("expected an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include UTC timezone")
    if parsed.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("timestamp must be UTC, not a local offset")
    parsed_ms = int(parsed.astimezone(UTC).timestamp() * 1000.0)
    if parsed_ms % LABEL_SLOT_MILLISECONDS != 0:
        raise argparse.ArgumentTypeError("timestamp must align to a 5-minute boundary")
    return parsed_ms


def _parse_symbols(value: str) -> tuple[str, ...]:
    symbols = tuple(
        sorted({item.strip().upper() for item in str(value).split(",") if item.strip()})
    )
    if not symbols:
        raise argparse.ArgumentTypeError("at least one explicit symbol is required")
    if any(
        not symbol.isascii() or not symbol.isalnum() or not 2 <= len(symbol) <= 32
        for symbol in symbols
    ):
        raise argparse.ArgumentTypeError("symbols must be canonical uppercase alphanumerics")
    return symbols


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True, type=_parse_symbols)
    parser.add_argument("--start-utc", required=True, type=_parse_utc_boundary)
    parser.add_argument("--end-utc", required=True, type=_parse_utc_boundary)
    parser.add_argument(
        "--authority-cutoff-utc",
        required=True,
        type=_parse_utc_boundary,
        help=(
            "Fixed authority boundary. It must exactly equal --end-utc; "
            "REST may recover only candle opens strictly before it."
        ),
    )
    parser.add_argument(
        "--archive-path",
        type=Path,
        default=default_archive_path(),
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=(
            _repo / ".local_data/v2_native_trainer/"
            "canonical_5m_historical_backfill_outbox.sqlite3"
        ),
    )
    parser.add_argument("--page-limit", type=int, default=1_000)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--max-slots-per-run", type=int, default=4_000)
    parser.add_argument(
        "--local-weight-budget-per-minute",
        type=int,
        default=120,
        help=(
            "Per-invocation UTC-minute request-weight safety sub-budget, capped "
            "at 120. The shared host-wide REST fallback budget and Binance "
            "response headers also apply."
        ),
    )
    parser.add_argument(
        "--max-request-weight-per-run",
        type=int,
        default=120,
        help="One-invocation request-weight cap; immutable safety ceiling is 120.",
    )
    parser.add_argument("--http-timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--execute-public-rest",
        action="store_true",
        help=(
            "Enable receipt-backed archive writes and credential-free public "
            "REST gap requests. Without this flag, print the plan only."
        ),
    )
    parser.add_argument(
        "--wss-inactive-attestation",
        type=Path,
        default=None,
        help=(
            "Operator-provided JSON authorization stating that the canonical "
            "archive WSS producer is inactive. This command does not claim or "
            "verify a cryptographic signature. Required with execution opt-in."
        ),
    )
    parser.add_argument("--report-path", type=Path, default=None)
    return parser


def _emit(report: dict[str, Any], *, report_path: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _validated_operator_paths(
    *,
    archive_path: Path,
    state_path: Path,
    attestation_path: Path | None,
    report_path: Path | None,
) -> tuple[Path, Path, Path | None, Path | None]:
    """Resolve paths and reject every destructive artifact or hard-link alias."""

    resolved_archive = Path(archive_path).expanduser().resolve()
    resolved_state = validate_historical_backfill_state_path(
        state_path=state_path,
        archive_path=resolved_archive,
    )
    protected = (
        *historical_backfill_sqlite_artifact_paths(resolved_archive),
        *historical_backfill_sqlite_artifact_paths(resolved_state),
    )
    resolved_attestation = (
        Path(attestation_path).expanduser().resolve() if attestation_path is not None else None
    )
    if resolved_attestation is not None and any(
        historical_backfill_paths_alias(resolved_attestation, artifact) for artifact in protected
    ):
        raise Historical5mBackfillError(
            "wss_inactive_attestation_path_collides_with_runtime_artifact"
        )
    resolved_report = Path(report_path).expanduser().resolve() if report_path is not None else None
    if resolved_report is not None and (
        any(historical_backfill_paths_alias(resolved_report, artifact) for artifact in protected)
        or (
            resolved_attestation is not None
            and historical_backfill_paths_alias(
                resolved_report,
                resolved_attestation,
            )
        )
    ):
        raise Historical5mBackfillError(
            "backfill_report_path_collides_with_protected_input_or_runtime_artifact"
        )
    return resolved_archive, resolved_state, resolved_attestation, resolved_report


def _before_public_request(request: BinanceKlineRequest) -> None:
    require_binance_rest_fallback(
        endpoint="/fapi/v1/klines",
        fallback_reason=("operator_requested_missing_canonical_5m_trainer_label_slot_recovery"),
        role="historical_canonical_5m_label_archive_gap_recovery",
        request_weight=request.weight,
        require_shared_budget=True,
    )
    if request.contract().get("credentials_used") is not False:
        raise Historical5mBackfillError("public_backfill_request_used_credentials")


def _on_rate_limit(response: PublicHttpResponse) -> None:
    retry_after: float | None = None
    normalized = {str(key).lower(): str(value) for key, value in response.headers.items()}
    if "retry-after" in normalized:
        try:
            retry_after = float(normalized["retry-after"])
        except ValueError:
            retry_after = None
    if (
        report_binance_rest_response(
            status_code=response.status_code,
            retry_after_seconds=retry_after,
        )
        is not True
    ):
        raise Historical5mBackfillError("binance_shared_rate_limit_cooldown_persistence_failed")


def _load_wss_inactive_attestation(
    path: Path,
    *,
    archive_path: Path,
    authority_cutoff_open_time_ms: int,
) -> WssAuthorityCutoffAttestation:
    try:
        decoded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Historical5mBackfillError(
            "wss_inactive_attestation_file_unreadable_or_invalid_json"
        ) from exc
    if not isinstance(decoded, dict):
        raise Historical5mBackfillError("wss_inactive_attestation_must_be_object")
    required = {
        "attestation_id",
        "archive_path",
        "authority_cutoff_open_time_ms",
        "attested_at_ms",
        "valid_until_ms",
        "producer_worker_id",
        "producer_archive_writes_inactive",
        "operator_authorized",
    }
    if set(decoded) != required:
        raise Historical5mBackfillError("wss_inactive_attestation_fields_missing_or_unexpected")
    attestation = WssAuthorityCutoffAttestation(
        attestation_id=decoded["attestation_id"],
        archive_path=Path(decoded["archive_path"]),
        authority_cutoff_open_time_ms=decoded["authority_cutoff_open_time_ms"],
        attested_at_ms=decoded["attested_at_ms"],
        valid_until_ms=decoded["valid_until_ms"],
        producer_worker_id=decoded["producer_worker_id"],
        producer_archive_writes_inactive=decoded["producer_archive_writes_inactive"],
        operator_authorized=decoded["operator_authorized"],
    ).validated(observed_at_ms=_clock_ms())
    if attestation.archive_path != archive_path.resolve():
        raise Historical5mBackfillError("wss_cutoff_archive_path_mismatch")
    if attestation.authority_cutoff_open_time_ms != authority_cutoff_open_time_ms:
        raise Historical5mBackfillError("wss_cutoff_cli_boundary_mismatch")
    return attestation


def _wss_archive_producer_inactive_probe(
    *,
    archive_path: Path,
) -> dict[str, Any]:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        raise Historical5mBackfillError("linux_proc_process_probe_unavailable")
    active_process_ids: list[int] = []
    enabled_writer_processes_other_archive: list[dict[str, Any]] = []
    for process_dir in proc_root.iterdir():
        if not process_dir.name.isdigit():
            continue
        try:
            command_bytes = (process_dir / "cmdline").read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise Historical5mBackfillError("wss_runtime_process_probe_incomplete") from exc
        if b"v2_binance_kline_wss_loop" not in command_bytes:
            continue
        try:
            command = [
                part.decode("utf-8", errors="strict")
                for part in command_bytes.split(b"\x00")
                if part
            ]
        except UnicodeDecodeError as exc:
            raise Historical5mBackfillError("wss_runtime_enabled_process_cmdline_invalid") from exc
        worker_identity_present = any(
            argument.rsplit("/", 1)[-1] == "v2_binance_kline_wss_loop.py"
            or argument == "v2.backend.app.cli.v2_binance_kline_wss_loop"
            for argument in command
        )
        if not worker_identity_present:
            continue
        if "--enable-canonical-5m-label-archive" not in command:
            # A market-data-only WSS process has no archive writer authority.
            continue
        if command.count("--enable-canonical-5m-label-archive") != 1:
            raise Historical5mBackfillError("wss_runtime_enabled_process_args_malformed")
        path_flag = "--canonical-5m-label-archive-path"
        path_values: list[str] = []
        for index, argument in enumerate(command):
            if argument == path_flag:
                if index + 1 >= len(command) or command[index + 1].startswith("--"):
                    raise Historical5mBackfillError(
                        "wss_runtime_enabled_archive_path_arg_malformed"
                    )
                path_values.append(command[index + 1])
            elif argument.startswith(path_flag + "="):
                path_values.append(argument.split("=", 1)[1])
        if len(path_values) > 1 or (path_values and not path_values[0].strip()):
            raise Historical5mBackfillError("wss_runtime_enabled_archive_path_arg_malformed")
        process_archive_path = Path(
            path_values[0] if path_values else default_archive_path()
        ).expanduser()
        if not process_archive_path.is_absolute():
            try:
                process_cwd = (process_dir / "cwd").resolve(strict=True)
            except (FileNotFoundError, OSError) as exc:
                raise Historical5mBackfillError(
                    "wss_runtime_enabled_process_cwd_unavailable"
                ) from exc
            process_archive_path = process_cwd / process_archive_path
        resolved_process_archive_path = process_archive_path.resolve()
        process_id = int(process_dir.name)
        if resolved_process_archive_path == archive_path.resolve():
            active_process_ids.append(process_id)
        else:
            enabled_writer_processes_other_archive.append(
                {
                    "process_id": process_id,
                    "archive_path": str(resolved_process_archive_path),
                }
            )
    observed_at_ms = _clock_ms()
    return {
        "probe_method": "linux_proc_enabled_writer_exact_archive_path_v2",
        "producer_worker_id": "v2_binance_kline_wss_loop",
        "archive_path": str(archive_path.resolve()),
        "observed_at_ms": observed_at_ms,
        "active_process_ids": sorted(active_process_ids),
        "wss_archive_producer_inactive": not active_process_ids,
        "enabled_writer_processes_other_archive": sorted(
            enabled_writer_processes_other_archive,
            key=lambda value: int(value["process_id"]),
        ),
        "process_probe_role": "SECONDARY_EVIDENCE_ONLY",
        "shared_exact_archive_writer_lease_is_primary": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    safe_report_path: Path | None = None
    try:
        if int(args.authority_cutoff_utc) != int(args.end_utc):
            raise Historical5mBackfillError("authority_cutoff_must_exactly_equal_end_utc")
        if int(args.end_utc) <= int(args.start_utc):
            raise Historical5mBackfillError("backfill_range_must_be_nonempty")
        bounds = BackfillRunBounds(
            max_pages=int(args.max_pages),
            max_slots=int(args.max_slots_per_run),
            local_weight_budget_per_minute=int(args.local_weight_budget_per_minute),
            max_request_weight_per_run=int(args.max_request_weight_per_run),
        ).validated()
        (
            archive_path,
            state_path,
            attestation_path,
            safe_report_path,
        ) = _validated_operator_paths(
            archive_path=args.archive_path,
            state_path=args.state_path,
            attestation_path=args.wss_inactive_attestation,
            report_path=args.report_path,
        )
        if not args.execute_public_rest:
            report = {
                "schema_version": "canonical_5m_historical_backfill_plan_v2",
                "status": "PLAN_ONLY_EXPLICIT_PUBLIC_REST_OPT_IN_REQUIRED",
                "job": {
                    "archive_path": str(archive_path),
                    "symbols": list(args.symbols),
                    "start_open_time_ms": int(args.start_utc),
                    "end_open_time_ms_exclusive": int(args.end_utc),
                    "authority_cutoff_open_time_ms": int(args.authority_cutoff_utc),
                    "page_limit": int(args.page_limit),
                    "job_id_available_after_attestation": True,
                },
                "run_bounds": {
                    "max_pages": bounds.max_pages,
                    "max_slots": bounds.max_slots,
                    "local_weight_budget_per_utc_minute": (bounds.local_weight_budget_per_minute),
                    "max_request_weight_per_run": bounds.max_request_weight_per_run,
                    "immutable_local_weight_per_utc_minute_ceiling": (
                        MAX_LOCAL_REQUEST_WEIGHT_PER_UTC_MINUTE
                    ),
                    "immutable_request_weight_per_run_ceiling": (MAX_REQUEST_WEIGHT_PER_RUN),
                },
                "state_path": str(state_path),
                "network_requests_made": 0,
                "local_files_written": bool(args.report_path),
                "archive_mutated": False,
                "credentials_used": False,
                "orders_or_account_mutations": False,
                "required_execution_controls": [
                    "--execute-public-rest",
                    f"{REST_FALLBACK_ENV}=true",
                    "--wss-inactive-attestation=<operator-provided JSON authorization>",
                    (
                        "runtime /proc secondary probe finds no enabled WSS "
                        "archive writer for the exact resolved archive path"
                    ),
                    "shared exact archive-path writer lease acquired",
                    "fixed --authority-cutoff-utc exactly equals --end-utc",
                ],
                "rest_authority_rule": "OPEN_TIME_STRICTLY_BEFORE_CUTOFF",
                "wss_activation_performed": False,
            }
            output_path = safe_report_path
            safe_report_path = None
            _emit(report, report_path=output_path)
            return 0

        if attestation_path is None:
            raise Historical5mBackfillError("execute_requires_wss_inactive_attestation_file")
        attestation = _load_wss_inactive_attestation(
            attestation_path,
            archive_path=archive_path,
            authority_cutoff_open_time_ms=int(args.authority_cutoff_utc),
        )
        spec = BackfillJobSpec(
            archive_path=archive_path,
            symbols=tuple(args.symbols),
            start_open_time_ms=int(args.start_utc),
            end_open_time_ms_exclusive=int(args.end_utc),
            authority_cutoff=attestation,
            page_limit=int(args.page_limit),
        ).validated()
        transport = UrllibPublicKlineTransport(
            timeout_seconds=float(args.http_timeout_seconds),
            clock_ms=_clock_ms,
        )
        report = run_historical_5m_backfill(
            spec=spec,
            bounds=bounds,
            state_path=state_path,
            transport=transport,
            clock_ms=_clock_ms,
            wss_inactive_probe=lambda: _wss_archive_producer_inactive_probe(
                archive_path=spec.archive_path
            ),
            before_public_request=_before_public_request,
            on_rate_limit=_on_rate_limit,
        )
        report["job"] = job_spec_as_jsonable(spec)
        report["status"] = (
            "COMPLETE_READY_FOR_WSS_ACTIVATION"
            if report.get("wss_activation_ready") is True
            else "HISTORICAL_FIXED_CUTOFF_COMPLETE_ARCHIVE_TAIL_ADVANCED"
            if report["job_complete"]
            else "PAUSED_RESUMABLE"
            if report["paused"]
            else "BOUNDED_SLICE_COMPLETE_RESUME_REQUIRED"
        )
        output_path = safe_report_path
        safe_report_path = None
        _emit(report, report_path=output_path)
        return 0
    except (RuntimeError, OSError, TypeError, ValueError, sqlite3.Error) as exc:
        report = {
            "schema_version": "canonical_5m_historical_backfill_error_v1",
            "status": "BLOCKED_FAIL_CLOSED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "credentials_used": False,
            "orders_or_account_mutations": False,
        }
        try:
            _emit(report, report_path=safe_report_path)
        except OSError:
            _emit(report, report_path=None)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
