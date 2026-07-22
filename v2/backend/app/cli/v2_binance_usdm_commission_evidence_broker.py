"""Publish adaptive authenticated Binance USD-M commission evidence.

This isolated producer executes only signed read-only
``GET /fapi/v1/commissionRate`` requests. It never submits, cancels, or
modifies orders, leverage, margin mode, or transfers. The symbol rotation is
read from the current expiring trainer universe and paced by the host-shared
Binance request-weight budget.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from v2.backend.app.services.binance_usdm_commission_evidence_broker import (
    CommissionEvidenceBrokerError,
    adaptive_commission_request_pacing_ms,
    capture_and_publish_next_commission_evidence,
    default_commission_broker_store,
    read_adaptive_commission_rotation_universe,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    EvidenceSecurityContext,
    LeverageBracketEvidenceError,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_runtime_credentials import (
    adapter_and_security_context_from_systemd_credentials,
)
from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    BinanceUSDMCommissionCaptureV1Error,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)

_CONFIG_EXIT_STATUS = 78
_STOP = threading.Event()
_SAFE_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,159}$", re.ASCII)


def _request_stop(_signum: int, _frame: Any) -> None:
    _STOP.set()


def _safe_failure_reason(exc: BaseException, *, scope: str) -> str:
    candidate = (
        exc.reason
        if isinstance(
            exc,
            CommissionEvidenceBrokerError | BinanceUSDMCommissionCaptureV1Error,
        )
        else None
    )
    if isinstance(exc, LeverageBracketEvidenceError):
        candidate = str(exc)
    if type(candidate) is str and _SAFE_REASON_RE.fullmatch(candidate) is not None:
        return candidate
    return f"COMMISSION_BROKER_{scope}_{type(exc).__name__.upper()}"


def _redis_client(redis_url: str) -> Any:
    try:
        import redis
    except ImportError as exc:
        raise CommissionEvidenceBrokerError(
            "COMMISSION_BROKER_REDIS_LIBRARY_UNAVAILABLE"
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
    except Exception as exc:  # noqa: BLE001 - transport detail must not escape
        raise CommissionEvidenceBrokerError(
            "COMMISSION_BROKER_REDIS_CONNECTION_FAILED"
        ) from exc
    return client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=(
            Path(value)
            if (value := os.environ.get("BINANCE_COMMISSION_BROKER_DATA_ROOT"))
            else None
        ),
        required=os.environ.get("BINANCE_COMMISSION_BROKER_DATA_ROOT") is None,
    )
    parser.add_argument(
        "--execute-read-only",
        action="store_true",
        help="explicitly authorize the fixed signed read-only commission GET",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def run_turn(
    *,
    adapter: Any,
    redis_client: Any,
    store: ImmutableSourcePayloadStore,
    security_context: EvidenceSecurityContext,
    environ: Mapping[str, str] | None = None,
    capture_function: Callable[..., dict[str, Any]] = (
        capture_and_publish_next_commission_evidence
    ),
) -> dict[str, Any]:
    """Run one isolated scheduling turn with at most one exchange request."""

    pacing_ms = adaptive_commission_request_pacing_ms(environ)
    universe = read_adaptive_commission_rotation_universe(redis_client)
    if universe.get("status") != "READY":
        return {
            "status": "DEFERRED",
            "reason": universe.get("status"),
            "universe_symbol_count": 0,
            "universe_rejected_symbol_count": 0,
            "pacing_ms": pacing_ms,
            "request_executed": False,
            "request_count": 0,
            "read_only": True,
            "places_real_order": False,
            "order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
    symbols = universe["symbols"]
    result = capture_function(
        adapter=adapter,
        redis_client=redis_client,
        store=store,
        security_context=security_context,
        symbols=symbols,
        priority_symbols=(),
        environ=environ,
    )
    return {
        **result,
        "universe_source_key": universe["source_key"],
        "universe_source_payload_sha256": universe["source_payload_sha256"],
        "universe_source_pttl_ms": universe["source_pttl_ms"],
        "universe_server_observed_at": universe["server_observed_at"],
        "universe_source_expires_at": universe["source_expires_at"],
        "universe_symbol_count": len(symbols),
        "universe_rejected_symbol_count": len(universe["rejected_symbols"]),
        "universe_selection_metadata_only": True,
    }


def public_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop any accidental object or secret material before journalling."""

    allowed = {
        "status",
        "reason",
        "publication_status",
        "selected_symbol",
        "symbol_count",
        "cache_current_count",
        "cache_missing_count",
        "cache_invalid_count",
        "cache_expired_count",
        "pacing_ms",
        "observed_capture_sample_count",
        "observed_capture_max_ms",
        "projected_turn_ms",
        "projected_revisit_ms",
        "continuous_coverage_feasible",
        "request_executed",
        "request_count",
        "request_method",
        "request_path",
        "request_weight",
        "shared_budget_required",
        "raw_response_sha256",
        "raw_response_byte_count",
        "rotation_receipt_sha256",
        "broker_available_at",
        "expires_at",
        "universe_source_key",
        "universe_source_payload_sha256",
        "universe_source_pttl_ms",
        "universe_server_observed_at",
        "universe_source_expires_at",
        "universe_symbol_count",
        "universe_rejected_symbol_count",
        "universe_selection_metadata_only",
        "read_only",
        "places_real_order",
        "order_submitted",
        "leverage_mutated",
        "margin_mutated",
    }
    return {
        "schema_version": "v2_binance_usdm_commission_broker_cli_status_v1",
        **{key: payload[key] for key in sorted(allowed) if key in payload},
        "exchange_credentials_exposed": False,
        "evidence_hmac_key_exposed": False,
        "raw_response_exposed": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }


def _emit(payload: Mapping[str, Any], *, pretty: bool, error: bool = False) -> None:
    print(
        json.dumps(
            public_status(payload),
            allow_nan=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
        ),
        file=sys.stderr if error else sys.stdout,
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.execute_read_only:
        _emit(
            {
                "status": "BLOCKED",
                "reason": "COMMISSION_BROKER_EXPLICIT_READ_ONLY_OPT_IN_REQUIRED",
            },
            pretty=args.json,
            error=True,
        )
        return _CONFIG_EXIT_STATUS
    data_root = args.data_root
    if not isinstance(data_root, Path) or not data_root.is_absolute():
        _emit(
            {
                "status": "BLOCKED",
                "reason": "COMMISSION_BROKER_DATA_ROOT_MUST_BE_ABSOLUTE",
            },
            pretty=args.json,
            error=True,
        )
        return _CONFIG_EXIT_STATUS
    try:
        adapter, security_context = (
            adapter_and_security_context_from_systemd_credentials()
        )
        redis_client = _redis_client(str(args.redis_url))
        store = default_commission_broker_store(data_root)
        signal.signal(signal.SIGINT, _request_stop)
        signal.signal(signal.SIGTERM, _request_stop)
        while not _STOP.is_set():
            pacing_ms = adaptive_commission_request_pacing_ms(os.environ)
            try:
                status = run_turn(
                    adapter=adapter,
                    redis_client=redis_client,
                    store=store,
                    security_context=security_context,
                    environ=os.environ,
                )
                _emit(status, pretty=args.json)
            except Exception as exc:  # noqa: BLE001 - isolate every broker turn
                reason = _safe_failure_reason(exc, scope="TURN_EXCEPTION")
                _emit(
                    {
                        "status": "BLOCKED",
                        "reason": reason,
                        "pacing_ms": pacing_ms,
                        "read_only": True,
                        "places_real_order": False,
                        "order_submitted": False,
                        "leverage_mutated": False,
                        "margin_mutated": False,
                    },
                    pretty=args.json,
                    error=True,
                )
            if args.once:
                break
            if _STOP.wait(pacing_ms / 1_000.0):
                break
        return 0
    except (
        CommissionEvidenceBrokerError,
        LeverageBracketEvidenceError,
        SourcePayloadStoreError,
    ) as exc:
        reason = _safe_failure_reason(exc, scope="CONFIGURATION_EXCEPTION")
        _emit(
            {"status": "BLOCKED", "reason": reason},
            pretty=args.json,
            error=True,
        )
        return _CONFIG_EXIT_STATUS


if __name__ == "__main__":
    raise SystemExit(main())
