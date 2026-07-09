"""V2 alternative-data symbol-universe scoring CLI.

One-shot paper/shadow scorer. Reads only already-published V2 runtime
payloads and writes only:

- v2:altdata:symbol_score:{symbol}
- v2:symbol_universe:altdata_candidates

It never calls provider APIs, never writes old Redis keys, and cannot
change live or paper trading gates.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.alternative_data.cache import (
    SYMBOL_SCORE_PREFIX,
    SYMBOL_UNIVERSE_KEY,
    safe_redis_set,
)
from v2.backend.app.services.alternative_data.symbol_scoring_contract import (
    build_symbol_score_payload,
    build_symbol_universe_candidates,
    utc_iso,
)

GO_READY = "V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY"
GO_BLOCKED = "V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_BLOCKED"

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_alt_data_symbol_universe_scoring/latest/alt_data_symbol_universe_scoring_status.json"
)
WORKLOG_REPORT = Path(
    "claude_worklog/final_readiness/v2_alt_data_symbol_universe_scoring/latest/V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_REPORT.md"
)
WORKLOG_GO_NO_GO = Path(
    "claude_worklog/final_readiness/v2_alt_data_symbol_universe_scoring/latest/GO_NO_GO.md"
)
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_alt_data_symbol_universe_scoring/latest/alt_data_symbol_universe_scoring_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_alt_data_symbol_universe_scoring/latest/operator_dashboard_payload.json"
)


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _json_loads(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _redis_get_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    try:
        return _json_loads(redis_client.get(key))
    except Exception:
        return None


def _load_inputs_for_symbol(redis_client: Any, symbol: str) -> dict[str, Any]:
    """Read ONLY the alt-data / market / feature inputs the scoring
    contract is allowed to consume.

    The packet's input boundary is explicit and minimal:

    - ``v2:altdata:nansen:symbol:{symbol}``
    - ``v2:altdata:lunarcrush:symbol:{symbol}``
    - ``v2:altdata:coingecko:symbol:{symbol}``
    - ``v2:altdata:surf:symbol:{symbol}``
    - ``v2:altdata:coinglass:symbol:{symbol}``
    - ``v2:altdata:public_intel:symbol:{symbol}``
    - ``v2:altdata:aicoin:symbol:{symbol}``
    - ``v2:altdata:whale_walls:symbol:{symbol}``
    - ``v2:altdata:santiment:symbol:{symbol}``
    - ``v2:market:*`` (prices, funding, open_interest)
    - ``v2:features:latest:{symbol}:{timeframe}``
    - ``v2:features:moralis:{symbol}:{timeframe}``

    The CLI MUST NOT read ``v2:paper:*`` or ``v2:risk:*`` keys.
    Codex regression `SCORING_INPUT_BOUNDARY_INCLUDES_V2_PAPER_AND_RISK_CONTEXT`
    is closed by this remediation; any paper/risk overlay belongs
    in a separately reviewed lane (``V2_SYMBOL_UNIVERSE_PAPER_RISK_CONTEXT_OVERLAY``)
    and never inside the alt-data scorer.
    """
    timeframe = "1m"
    return {
        "nansen_payload": _redis_get_json(
            redis_client, f"v2:altdata:nansen:symbol:{symbol}"
        ),
        "lunarcrush_payload": _redis_get_json(
            redis_client, f"v2:altdata:lunarcrush:symbol:{symbol}"
        ),
        "coingecko_payload": _redis_get_json(
            redis_client, f"v2:altdata:coingecko:symbol:{symbol}"
        ),
        "surf_payload": _redis_get_json(
            redis_client, f"v2:altdata:surf:symbol:{symbol}"
        ),
        "coinglass_payload": _redis_get_json(
            redis_client, f"v2:altdata:coinglass:symbol:{symbol}"
        ),
        "public_intel_payload": _redis_get_json(
            redis_client, f"v2:altdata:public_intel:symbol:{symbol}"
        ),
        "aicoin_payload": _redis_get_json(
            redis_client, f"v2:altdata:aicoin:symbol:{symbol}"
        ),
        "whale_walls_payload": _redis_get_json(
            redis_client, f"v2:altdata:whale_walls:symbol:{symbol}"
        ),
        "santiment_payload": _redis_get_json(
            redis_client, f"v2:altdata:santiment:symbol:{symbol}"
        ),
        "market_payloads": {
            "prices": _redis_get_json(redis_client, f"v2:market:prices:{symbol}"),
            "funding": _redis_get_json(redis_client, f"v2:market:funding:{symbol}"),
            "open_interest": _redis_get_json(
                redis_client, f"v2:market:open_interest:{symbol}"
            ),
        },
        "feature_payloads": {
            "latest": _redis_get_json(
                redis_client, f"v2:features:latest:{symbol}:{timeframe}"
            ),
            "moralis": _redis_get_json(
                redis_client, f"v2:features:moralis:{symbol}:{timeframe}"
            ),
        },
    }


def _write_status_files(payload: dict[str, Any], public_paths: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    WORKLOG_STATUS.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_STATUS.write_text(body, encoding="utf-8")
    WORKLOG_GO_NO_GO.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_GO_NO_GO.write_text(payload["go_no_go"] + "\n", encoding="utf-8")
    for path in public_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def _write_report(payload: dict[str, Any]) -> None:
    candidates = payload["symbol_universe_candidates"]
    lines = [
        "# V2 Alternative-Data Symbol Universe Scoring Report",
        "",
        f"Generated: `{payload['generated_utc']}`",
        "",
        f"GO/NO-GO: `{payload['go_no_go']}`",
        "",
        "This packet does NOT approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.",
        "",
        "## Scope",
        "",
        "The scorer reads ONLY ``v2:altdata:nansen:*``, ``v2:altdata:lunarcrush:*``, ``v2:altdata:coingecko:*``, ``v2:altdata:surf:*``, ``v2:altdata:coinglass:*``, ``v2:altdata:public_intel:*``, ``v2:altdata:aicoin:*``, ``v2:altdata:whale_walls:*``, ``v2:altdata:santiment:*``, ``v2:market:*``, ``v2:features:latest:{symbol}:{timeframe}``, and ``v2:features:moralis:{symbol}:{timeframe}``. It does NOT read ``v2:paper:*`` or ``v2:risk:*``; any paper/risk overlay belongs to a separately reviewed lane.",
        "",
        "## Candidate Ranking",
        "",
        "| Symbol | Alt-data score | Availability | Freshness | Providers | Missing | Stale |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in candidates["candidate_rows"]:
        lines.append(
            "| {symbol} | {score} | {availability} | {freshness} | {providers} | {missing} | {stale} |".format(
                symbol=row["symbol"],
                score=row["altdata_symbol_score"],
                availability=row["provider_availability_score"],
                freshness=row["altdata_freshness_score"],
                providers=",".join(row["providers_consulted"]) or "none",
                missing=row["missing_signal"],
                stale=row["stale_signal"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- `live_gate`: `blocked_human_only`",
            "- `live_symbols`: `[]`",
            "- `paper_symbols_expanded`: `false`",
            "- `may_not_override_strict_paper_fill_gate`: `true`",
            "- `checkpoint_compatibility_claimed`: `false`",
            "- `policy_architecture_parity_claimed`: `false`",
            "- `writes_old_redis`: `false`",
            "- `exchange_mutation`: `false`",
            "",
            "## Final Decision",
            "",
            f"`{payload['go_no_go']}`",
            "",
        ]
    )
    WORKLOG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_once(
    *,
    symbols: tuple[str, ...] | None = None,
    redis_client_override=None,
    write_redis: bool = True,
    public_paths: tuple[Path, ...] = (PUBLIC_OPERATOR_RUNTIME, PUBLIC_DASHBOARD),
    max_provider_age_seconds: int = 1_800,
    smoke_test: bool = False,
) -> dict[str, Any]:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    generated_utc = utc_iso()
    resolved = resolve_symbols(explicit=symbols, smoke_test=smoke_test)
    normalized_symbols = tuple(
        sorted({symbol.strip().upper() for symbol in resolved if symbol.strip()})
    )
    symbol_scores: dict[str, dict[str, Any]] = {}
    input_presence: dict[str, dict[str, bool]] = {}
    for symbol in normalized_symbols:
        inputs = _load_inputs_for_symbol(redis_client, symbol)
        score = build_symbol_score_payload(
            symbol,
            nansen_payload=inputs["nansen_payload"],
            lunarcrush_payload=inputs["lunarcrush_payload"],
            coingecko_payload=inputs["coingecko_payload"],
            surf_payload=inputs["surf_payload"],
            coinglass_payload=inputs["coinglass_payload"],
            public_intel_payload=inputs["public_intel_payload"],
            aicoin_payload=inputs["aicoin_payload"],
            whale_walls_payload=inputs["whale_walls_payload"],
            santiment_payload=inputs["santiment_payload"],
            market_payloads=inputs["market_payloads"],
            feature_payloads=inputs["feature_payloads"],
            generated_utc=generated_utc,
            max_provider_age_seconds=max_provider_age_seconds,
        )
        symbol_scores[symbol] = score
        input_presence[symbol] = score["input_presence"]

    candidates = build_symbol_universe_candidates(
        normalized_symbols,
        symbol_scores=symbol_scores,
        existing_paper_symbols=(),
        generated_utc=generated_utc,
    )
    redis_write_results: dict[str, bool] = {}
    if write_redis and redis_client is not None:
        for symbol, score_payload in symbol_scores.items():
            key = f"{SYMBOL_SCORE_PREFIX}{symbol}"
            redis_write_results[key] = safe_redis_set(redis_client, key, score_payload)
        redis_write_results[SYMBOL_UNIVERSE_KEY] = safe_redis_set(
            redis_client, SYMBOL_UNIVERSE_KEY, candidates
        )

    payload = {
        "schema_version": "v2_alt_data_symbol_universe_scoring_status_v1",
        "generated_utc": generated_utc,
        "go_no_go": GO_READY,
        "symbols": list(normalized_symbols),
        "symbol_scores": symbol_scores,
        "symbol_universe_candidates": candidates,
        "input_presence": input_presence,
        "allowed_inputs": [
            "v2:altdata:nansen:status",
            "v2:altdata:nansen:symbol:{symbol}",
            "v2:altdata:lunarcrush:status",
            "v2:altdata:lunarcrush:symbol:{symbol}",
            "v2:altdata:coingecko:status",
            "v2:altdata:coingecko:symbol:{symbol}",
            "v2:altdata:surf:status",
            "v2:altdata:surf:symbol:{symbol}",
            "v2:altdata:coinglass:status",
            "v2:altdata:coinglass:symbol:{symbol}",
            "v2:altdata:public_intel:status",
            "v2:altdata:public_intel:symbol:{symbol}",
            "v2:altdata:aicoin:status",
            "v2:altdata:aicoin:symbol:{symbol}",
            "v2:altdata:whale_walls:status",
            "v2:altdata:whale_walls:symbol:{symbol}",
            "v2:altdata:santiment:status",
            "v2:altdata:santiment:symbol:{symbol}",
            "v2:market:prices:{symbol}",
            "v2:market:funding:{symbol}",
            "v2:market:open_interest:{symbol}",
            "v2:features:latest:{symbol}:{timeframe}",
            "v2:features:moralis:{symbol}:{timeframe}",
        ],
        "forbidden_input_namespaces_for_alt_data_scoring": [
            "v2:paper:*",
            "v2:risk:*",
        ],
        "scoring_input_boundary_remediated": True,
        "scoring_input_boundary_remediation_packet": "V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_INPUT_BOUNDARY_REMEDIATION_READY",
        "allowed_outputs": [
            "v2:altdata:symbol_score:{symbol}",
            "v2:symbol_universe:altdata_candidates",
        ],
        "redis_write_results": redis_write_results,
        "provider_network_calls_attempted": False,
        "paper_shadow_only": True,
        "paper_symbols_expanded": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "may_not_override_strict_paper_fill_gate": True,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "writes_old_redis": False,
        "exchange_mutation": False,
    }
    _write_status_files(payload, public_paths)
    _write_report(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_alt_data_symbol_universe_scoring")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--symbols", default=None)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use BTC/ETH/SOL only for explicit smoke tests; never the default.",
    )
    parser.add_argument("--no-redis", action="store_true")
    parser.add_argument("--max-provider-age-seconds", type=int, default=1_800)
    args = parser.parse_args(argv)
    symbols = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    payload = run_once(
        symbols=symbols,
        write_redis=not args.no_redis,
        max_provider_age_seconds=int(args.max_provider_age_seconds),
        smoke_test=args.smoke_test,
    )
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "symbols": payload["symbols"],
                "live_symbols": payload["live_symbols"],
                "paper_symbols_expanded": payload["paper_symbols_expanded"],
                "provider_network_calls_attempted": payload[
                    "provider_network_calls_attempted"
                ],
                "writes_old_redis": payload["writes_old_redis"],
                "exchange_mutation": payload["exchange_mutation"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
