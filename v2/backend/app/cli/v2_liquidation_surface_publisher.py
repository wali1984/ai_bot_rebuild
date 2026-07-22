"""Continuously publish prospective liquidation levels for universe x timeframe.

The command reads finalized Binance USD-M candles, exact Binance mark-price
cache bytes, CoinAnk Plan3 open-interest series, and authenticated account-
scoped USD-M leverage brackets from Redis.  It never calls a provider, never
uses liquidation heatmaps/maps, never treats forced-liquidation events as
prospective levels, and never submits or modifies an exchange order.

Publication receipts authenticate storage only.  This process cannot grant
trainer authority; trainer admission is a separate source-revalidation gate.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from v2.backend.app.services import (
    binance_usdm_leverage_bracket_runtime_credentials as bracket_credentials,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    EvidenceSecurityContext,
)
from v2.backend.app.services.liquidation_surface.producer import (
    SURFACE_TIMEFRAMES,
    MarkPriceHistory,
    publication_scope_metadata,
    run_producer_cycle,
)
from v2.backend.app.services.liquidation_surface.publication import (
    SurfacePublicationSecurityContext,
    build_surface_publication_security_context,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    resolve_symbols_with_provenance,
)

DEFAULT_INTERVAL_SECONDS = 1.0
PUBLICATION_HMAC_SYSTEMD_CREDENTIAL = "liquidation_surface_publication_hmac_key"
PUBLICATION_AUTH_KEY_ID_ENV = "LIQUIDATION_SURFACE_PUBLICATION_HMAC_KEY_ID"
MAX_SAFE_REASON_TEXT = 240


class LiquidationSurfacePublisherCLIError(RuntimeError):
    """Fail-closed publisher configuration or runtime initialization error."""


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis
    except Exception as exc:  # pragma: no cover - deployment dependency
        raise LiquidationSurfacePublisherCLIError("REDIS_CLIENT_IMPORT_FAILED") from exc
    url = (
        redis_url
        or os.environ.get("V2_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://127.0.0.1:6379/0"
    )
    try:
        client = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_timeout=10.0,
        )
        if client.ping() is not True:
            raise LiquidationSurfacePublisherCLIError("REDIS_PING_NOT_ACKNOWLEDGED")
    except LiquidationSurfacePublisherCLIError:
        raise
    except Exception as exc:
        raise LiquidationSurfacePublisherCLIError("REDIS_UNAVAILABLE") from exc
    return client


def _parse_values(values: Iterable[str]) -> tuple[str, ...]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip() for item in str(value).split(",") if item.strip())
    return tuple(parsed)


def security_contexts_from_systemd_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[EvidenceSecurityContext, SurfacePublicationSecurityContext]:
    """Load two independent protected HMAC keys and bind their exact scope."""

    values = os.environ if environ is None else environ
    bracket_context = (
        bracket_credentials.consumer_security_context_from_systemd_credentials(
            environ=values
        )
    )
    publication_hmac = bracket_credentials.read_protected_systemd_credential(
        PUBLICATION_HMAC_SYSTEMD_CREDENTIAL,
        environ=values,
    )
    publication_hmac_bytes = publication_hmac.encode("utf-8")
    if hmac.compare_digest(publication_hmac_bytes, bracket_context.hmac_key):
        raise LiquidationSurfacePublisherCLIError(
            "PUBLICATION_HMAC_KEY_MUST_DIFFER_FROM_BRACKET_EVIDENCE_HMAC_KEY"
        )
    auth_key_id = values.get(PUBLICATION_AUTH_KEY_ID_ENV, "")
    publication_context = build_surface_publication_security_context(
        scope_metadata=publication_scope_metadata(bracket_context),
        hmac_key=publication_hmac_bytes,
        auth_key_id=auth_key_id,
    )
    return bracket_context, publication_context


def _resolve_universe(
    *,
    explicit_symbols: Sequence[str],
    smoke_test: bool,
) -> dict[str, Any]:
    profile = resolve_symbols_with_provenance(
        explicit=explicit_symbols or None,
        smoke_test=smoke_test,
        include_baseline=True,
    )
    symbols = profile.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise LiquidationSurfacePublisherCLIError("DYNAMIC_SYMBOL_UNIVERSE_EMPTY")
    return profile


def run_once(
    *,
    redis_client: Any,
    bracket_security_context: EvidenceSecurityContext,
    publication_security_context: SurfacePublicationSecurityContext,
    mark_history: MarkPriceHistory,
    explicit_symbols: Sequence[str] = (),
    timeframes: Sequence[str] = SURFACE_TIMEFRAMES,
    smoke_test: bool = False,
) -> dict[str, Any]:
    """Resolve the current universe and publish one complete producer cycle."""

    profile = _resolve_universe(
        explicit_symbols=explicit_symbols,
        smoke_test=smoke_test,
    )
    result = run_producer_cycle(
        redis_client,
        symbols=tuple(profile["symbols"]),
        timeframes=tuple(timeframes),
        bracket_security_context=bracket_security_context,
        publication_security_context=publication_security_context,
        mark_history=mark_history,
    )
    return {
        **result,
        "symbol_profile": profile.get("symbol_profile"),
        "symbol_universe_source_path": profile.get("source_path"),
        "symbol_universe_smoke_test": profile.get("smoke_test") is True,
    }


def run_loop(
    *,
    redis_client: Any,
    bracket_security_context: EvidenceSecurityContext,
    publication_security_context: SurfacePublicationSecurityContext,
    mark_history: MarkPriceHistory,
    explicit_symbols: Sequence[str] = (),
    timeframes: Sequence[str] = SURFACE_TIMEFRAMES,
    smoke_test: bool = False,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    stop_event: threading.Event | None = None,
    max_cycles: int | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run continuously, re-resolving the adaptive symbol universe each cycle."""

    if not isinstance(interval_seconds, int | float) or interval_seconds <= 0:
        raise LiquidationSurfacePublisherCLIError("INTERVAL_SECONDS_MUST_BE_POSITIVE")
    if max_cycles is not None and (type(max_cycles) is not int or max_cycles <= 0):
        raise LiquidationSurfacePublisherCLIError("MAX_CYCLES_MUST_BE_POSITIVE")
    stopper = stop_event or threading.Event()
    latest: dict[str, Any] = {}
    completed_cycles = 0
    while not stopper.is_set():
        latest = run_once(
            redis_client=redis_client,
            bracket_security_context=bracket_security_context,
            publication_security_context=publication_security_context,
            mark_history=mark_history,
            explicit_symbols=explicit_symbols,
            timeframes=timeframes,
            smoke_test=smoke_test,
        )
        completed_cycles += 1
        if on_result is not None:
            on_result(latest)
        if max_cycles is not None and completed_cycles >= max_cycles:
            break
        stopper.wait(float(interval_seconds))
    return latest


def public_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return count-heavy status without secret-bearing security contexts."""

    allowed = (
        "schema_version",
        "status",
        "reason",
        "venue",
        "publication_scope_sha256",
        "cycle_started_at",
        "cycle_completed_at",
        "cycle_duration_ms",
        "archive_ttl_seconds",
        "receipt_ttl_seconds",
        "status_ttl_seconds",
        "receipt_ttl_margin_ms",
        "continuous_pointer_coverage",
        "symbol_count",
        "timeframe_count",
        "lane_count",
        "candidate_built_count",
        "published_lane_count",
        "all_lanes_published",
        "trainer_semantic_candidate_count",
        "trainer_candidate_pointer_count",
        "verified_prepared_source_bundle_count",
        "observation_pointer_count",
        "trainer_authority_count",
        "two_mark_sample_symbol_count",
        "authenticated_bracket_symbol_count",
        "adaptive_oi_selected_symbol_count",
        "adaptive_oi_selected_timeframes",
        "timeframe_published_counts",
        "timeframe_semantic_candidate_counts",
        "trainer_semantic_reason_counts",
        "build_error_counts",
        "publication_error_counts",
        "symbol_profile",
        "symbol_universe_source_path",
        "symbol_universe_smoke_test",
        "adaptive_market_freshness",
        "static_market_threshold_used",
        "coinank_plan",
        "coinank_open_interest_endpoint",
        "coinank_liquidation_heatmap_or_map_used",
        "forced_liquidation_stream_used_as_level_source",
        "trainer_admission_required_separately",
        "prediction_authority",
        "paper_trading_authority",
        "live_trading_authority",
        "places_real_order",
        "order_submitted",
        "leverage_mutated",
        "margin_mutated",
    )
    return {field: payload.get(field) for field in allowed if field in payload}


def _blocked_status(reason: object) -> dict[str, Any]:
    text = str(reason).replace("\n", " ")[:MAX_SAFE_REASON_TEXT]
    return {
        "schema_version": "v2_liquidation_surface_publisher_cli_status_v1",
        "status": "BLOCKED",
        "reason": text or "UNKNOWN",
        "trainer_authority_count": 0,
        "prediction_authority": False,
        "paper_trading_authority": False,
        "live_trading_authority": False,
        "places_real_order": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="publish one cycle")
    mode.add_argument("--loop", action="store_true", help="publish until interrupted")
    parser.add_argument("--symbols", action="append", default=[])
    parser.add_argument("--timeframes", action="append", default=[])
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--redis-url", default=None)
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="operational delay after each completed full-universe cycle",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    explicit_symbols = _parse_values(args.symbols)
    timeframes = _parse_values(args.timeframes) or SURFACE_TIMEFRAMES

    def emit(payload: Mapping[str, Any]) -> None:
        print(
            json.dumps(
                public_status(payload),
                allow_nan=False,
                ensure_ascii=True,
                indent=2 if args.json else None,
                sort_keys=True,
            ),
            flush=True,
        )

    try:
        bracket_context, publication_context = security_contexts_from_systemd_credentials()
        redis_client = _redis_client(args.redis_url)
        history = MarkPriceHistory()
        if args.loop:
            latest = run_loop(
                redis_client=redis_client,
                bracket_security_context=bracket_context,
                publication_security_context=publication_context,
                mark_history=history,
                explicit_symbols=explicit_symbols,
                timeframes=timeframes,
                smoke_test=args.smoke_test,
                interval_seconds=args.interval_seconds,
                on_result=emit,
            )
        else:
            latest = run_once(
                redis_client=redis_client,
                bracket_security_context=bracket_context,
                publication_security_context=publication_context,
                mark_history=history,
                explicit_symbols=explicit_symbols,
                timeframes=timeframes,
                smoke_test=args.smoke_test,
            )
            emit(latest)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        emit(_blocked_status(f"{type(exc).__name__}:{exc}"))
        return 2
    return 0 if latest.get("status") in {"COMPLETE", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
