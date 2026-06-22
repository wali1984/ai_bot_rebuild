"""V2 alt-data Symbol Universe candidate publisher CLI.

Reads V2 alt-data + market + feature inputs. Writes two Redis keys
in the publisher's tight allowlist and emits worklog + public
operator-dashboard payloads.

NEVER reads ``v2:paper:*`` or ``v2:risk:*``. NEVER calls a provider
endpoint. NEVER places, cancels, or modifies any exchange order.
NEVER mutates ``live_symbols``, ``paper_symbols``, or
``training_symbols`` — those sets belong to the existing Symbol
Universe governance lane and require their own gate.

Allowed Redis writes:
- ``v2:symbol_universe:altdata_candidates``
- ``v2:altdata:candidate_publisher:status``

Allowed file writes:
- ``claude_worklog/final_readiness/v2_alt_data_symbol_candidate_publisher/latest/alt_data_symbol_candidate_publisher_status.json``
- ``v2/frontend/public/operator_runtime/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json``
- ``v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json``
- ``claude_worklog/final_readiness/v2_alt_data_symbol_candidate_publisher/latest/GO_NO_GO.md``
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from v2.backend.app.services.alternative_data.symbol_candidate_publisher import (
    ALLOWED_REDIS_WRITE_KEYS,
    CandidateInputs,
    DEFAULT_PAPER_THRESHOLD,
    DEFAULT_TRAINING_THRESHOLD,
    DEFAULT_WATCHLIST_THRESHOLD,
    KEY_ALTDATA_CANDIDATES,
    KEY_PUBLISHER_STATUS,
    build_candidate_list,
    safe_redis_set,
    utc_iso,
)

def _resolve_default_symbols() -> tuple[str, ...]:
    """Default symbol set for the alt-data candidate publisher.

    Resolves dynamically via :mod:`v2_symbol_runtime_universe` so this CLI
    no longer pins a 3-symbol smoke-test set as its production default. The
    smoke-test 3 (BTC/ETH/SOL) is only returned if the operator explicitly
    opts in via ``V2_SYMBOL_PROFILE=smoke_test``.
    """
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    return tuple(resolve_symbols(smoke_test=False, include_baseline=True))


# DEFAULT_SYMBOLS is resolved lazily at first call site so smoke-test env
# overrides apply at runtime; keep the public name for backwards compat.
DEFAULT_SYMBOLS: tuple[str, ...] = _resolve_default_symbols()

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_alt_data_symbol_candidate_publisher/latest/alt_data_symbol_candidate_publisher_status.json"
)
WORKLOG_GO_NO_GO = Path(
    "claude_worklog/final_readiness/v2_alt_data_symbol_candidate_publisher/latest/GO_NO_GO.md"
)
PUBLIC_OPERATOR_DASHBOARD = Path(
    "v2/frontend/public/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"
)
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"
)


def _connect_redis():  # pragma: no cover — exercised in real-runtime path
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _redis_get_json(redis_client: Any, key: str) -> Any | None:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _load_inputs_for_symbol(
    redis_client: Any,
    symbol: str,
    *,
    nansen_status: Any | None = None,
    lunarcrush_status: Any | None = None,
) -> CandidateInputs:
    """Read ONLY the alt-data, market, and feature keys the
    publisher is allowed to consume. ``v2:paper:*`` / ``v2:risk:*``
    are NEVER touched."""
    timeframe = "1m"
    return CandidateInputs(
        symbol_score=_redis_get_json(
            redis_client, f"v2:altdata:symbol_score:{symbol}"
        ),
        market_prices_payload=_redis_get_json(
            redis_client, f"v2:market:prices:{symbol}"
        ),
        feature_payload=_redis_get_json(
            redis_client, f"v2:features:latest:{symbol}:{timeframe}"
        ),
        nansen_status_payload=nansen_status,
        lunarcrush_status_payload=lunarcrush_status,
    )


def _write_status_files(payload: dict[str, Any], public_paths: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    WORKLOG_STATUS.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_STATUS.write_text(body, encoding="utf-8")
    WORKLOG_GO_NO_GO.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_GO_NO_GO.write_text(payload["go_no_go"] + "\n", encoding="utf-8")
    for path in public_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def run_once(
    *,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    redis_client_override: Any | None = None,
    write_redis: bool = True,
    public_paths: tuple[Path, ...] = (PUBLIC_OPERATOR_RUNTIME, PUBLIC_OPERATOR_DASHBOARD),
    watchlist_threshold: float = DEFAULT_WATCHLIST_THRESHOLD,
    paper_threshold: float = DEFAULT_PAPER_THRESHOLD,
    training_threshold: float = DEFAULT_TRAINING_THRESHOLD,
) -> dict[str, Any]:
    redis_client = (
        redis_client_override if redis_client_override is not None else _connect_redis()
    )
    generated_utc = utc_iso()
    # Provider-level status payloads are read once and reused per
    # symbol so the publisher does not double-poll the same keys.
    nansen_status = _redis_get_json(redis_client, "v2:altdata:nansen:status")
    lunarcrush_status = _redis_get_json(redis_client, "v2:altdata:lunarcrush:status")
    normalized_symbols = sorted(
        {symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()}
    )
    inputs_by_symbol = {
        symbol: _load_inputs_for_symbol(
            redis_client,
            symbol,
            nansen_status=nansen_status,
            lunarcrush_status=lunarcrush_status,
        )
        for symbol in normalized_symbols
    }
    payload = build_candidate_list(
        normalized_symbols,
        inputs_by_symbol,
        watchlist_threshold=watchlist_threshold,
        paper_threshold=paper_threshold,
        training_threshold=training_threshold,
        generated_utc=generated_utc,
    )
    redis_write_results: dict[str, bool] = {}
    if write_redis and redis_client is not None:
        redis_write_results[KEY_ALTDATA_CANDIDATES] = safe_redis_set(
            redis_client, KEY_ALTDATA_CANDIDATES, payload
        )
        publisher_status = {
            "schema_version": "v2_alt_data_symbol_candidate_publisher_status_v1",
            "generated_utc": generated_utc,
            "go_no_go": payload["go_no_go"],
            "candidate_count": payload["candidate_count"],
            "candidate_state_counts": payload["candidate_state_counts"],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "real_order_attempted": False,
            "raw_credential_in_payload": "NEVER",
        }
        redis_write_results[KEY_PUBLISHER_STATUS] = safe_redis_set(
            redis_client, KEY_PUBLISHER_STATUS, publisher_status
        )
    payload["redis_write_results"] = redis_write_results
    if public_paths:
        _write_status_files(payload, public_paths)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_alt_data_symbol_candidate_publisher")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated symbols. Omit to re-resolve the dynamic universe each cycle.",
    )
    parser.add_argument(
        "--watchlist-threshold",
        type=float,
        default=DEFAULT_WATCHLIST_THRESHOLD,
    )
    parser.add_argument(
        "--paper-threshold",
        type=float,
        default=DEFAULT_PAPER_THRESHOLD,
    )
    parser.add_argument(
        "--training-threshold",
        type=float,
        default=DEFAULT_TRAINING_THRESHOLD,
    )
    args = parser.parse_args(argv)
    symbols = tuple(
        s for s in (sym.strip() for sym in (args.symbols or "").split(",")) if s
    ) or _resolve_default_symbols()
    if args.once and not args.loop:
        payload = run_once(
            symbols=symbols,
            watchlist_threshold=args.watchlist_threshold,
            paper_threshold=args.paper_threshold,
            training_threshold=args.training_threshold,
        )
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "candidate_count": payload["candidate_count"],
                    "candidate_state_counts": payload["candidate_state_counts"],
                },
                sort_keys=True,
            )
        )
        return 0
    while True:  # pragma: no cover — runtime loop
        symbols = tuple(
            s for s in (sym.strip() for sym in (args.symbols or "").split(",")) if s
        ) or _resolve_default_symbols()
        run_once(
            symbols=symbols,
            watchlist_threshold=args.watchlist_threshold,
            paper_threshold=args.paper_threshold,
            training_threshold=args.training_threshold,
        )
        try:
            time.sleep(max(15, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
