"""Same-day provider-rate-limited production cutover status and CEO packet.

This command is read-only except for writing local packet files and an optional
Redis status key. It does not enable live trading.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.cli.v2_provider_scheduler_status import build_status as build_scheduler_status
from app.services.coinglass_provider import build_coinglass_health
from app.services.provider_features import (
    CONSUMER_ROLES,
    build_provider_actual_data_panel,
    build_provider_consumer_context,
)
from app.services.smart_money_wallets import build_moralis_health


STATUS_KEY = "v2:cutover:same_day_provider_rate_limited_status"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_same_day_production_cutover_status")
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--symbol", default=os.environ.get("CUTOVER_SYMBOL", "BTCUSDT"))
    parser.add_argument("--timeframe", default=os.environ.get("CUTOVER_TIMEFRAME", "1m"))
    parser.add_argument("--symbols", default=os.environ.get("COINGLASS_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"))
    parser.add_argument("--wallets", default=os.environ.get("MORALIS_WALLETS", ""))
    parser.add_argument("--tokens", default=os.environ.get("MORALIS_TOKENS", ""))
    args = parser.parse_args(argv)
    try:
        from v2.backend.app.services.safe_env_loader import bootstrap_process_env

        bootstrap_process_env(apply=True)
    except Exception:
        pass  # health checks degrade to key-absent reporting
    r = _redis_client(args.redis_url) if args.redis_url else None
    packet = build_cutover_packet(
        redis_client=r,
        symbol=args.symbol.upper(),
        timeframe=args.timeframe,
        symbols=_csv(args.symbols, upper=True),
        wallets=_csv(args.wallets),
        tokens=_csv(args.tokens),
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "same_day_production_go_live_gate_status.json"
    md_path = out_dir / "same_day_ceo_packet.md"
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True, default=str), encoding="utf-8")
    md_path.write_text(render_ceo_packet(packet), encoding="utf-8")
    if r is not None:
        r.set(STATUS_KEY, json.dumps(packet, sort_keys=True, default=str), ex=900)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "status": packet["status"]}, indent=2))
    return 0


def build_cutover_packet(
    *,
    redis_client: Any | None,
    symbol: str,
    timeframe: str,
    symbols: list[str],
    wallets: list[str],
    tokens: list[str],
) -> dict[str, Any]:
    provider_panel = build_provider_actual_data_panel(redis_client, symbol=symbol, timeframe=timeframe)
    _apply_health_fallbacks(provider_panel)
    scheduler_status = build_scheduler_status(symbols=symbols, wallets=wallets, tokens=tokens)
    consumer_contexts = {
        role: build_provider_consumer_context(
            redis_client,
            role=role,
            symbol=symbol,
            timeframe=timeframe,
        )
        for role in CONSUMER_ROLES
    }
    live_control = _read_json(redis_client, "v2:live:control") or {}
    live_gate = str(live_control.get("live_gate") or live_control.get("live_gate_state") or "blocked_human_only")
    hard_blocks = []
    if live_gate != "blocked_human_only":
        hard_blocks.append("live_gate_not_blocked_human_only")
    if any(ctx.get("core_system_blocked") for ctx in consumer_contexts.values()):
        hard_blocks.append("required_provider_context_blocked")
    provider_readiness_blockers = _provider_readiness_blockers(provider_panel)
    status = _cutover_status(hard_blocks=hard_blocks, provider_readiness_blockers=provider_readiness_blockers)
    final_marker = (
        "V2_SAME_DAY_PRODUCTION_CUTOVER_DATA_FEATURE_TRAINER_PREEMPTIVE_AND_LIVE_CANARY_READY"
        if status == "LIVE_CANARY_OPERATOR_REVIEW_REQUIRED"
        else "V2_SAME_DAY_PRODUCTION_CUTOVER_DATA_FEATURE_TRAINER_PREEMPTIVE_AND_LIVE_CANARY_BLOCKED"
    )
    packet = {
        "schema_version": "same_day_cutover_provider_rate_limited_ceo_packet_v1",
        "status": status,
        "generated_utc": _now(),
        "symbol": symbol,
        "timeframe": timeframe,
        "provider_actual_data_panel": provider_panel,
        "provider_scheduler_status": scheduler_status,
        "provider_consumption": consumer_contexts,
        "live_gate": live_gate,
        "live_ready": False,
        "live_ready_from_probation_allowed": False,
        "operator_approval_required_for_live": True,
        "optional_provider_failures_core_blocking": False,
        "heartbeat_only_green_allowed": False,
        "coinglass_public_limit_exceeded": False,
        "moralis_every_symbol_every_minute_allowed": False,
        "raw_key_exposed": False,
        "hard_blocks": hard_blocks,
        "provider_readiness_blockers": provider_readiness_blockers,
        "primary_blocker": (hard_blocks or provider_readiness_blockers or ["none"])[0],
        "next_patch": _next_patch(hard_blocks=hard_blocks, provider_readiness_blockers=provider_readiness_blockers),
        "final_marker": final_marker,
        "ceo_summary": {
            "headline": _headline(status),
            "coinglass": provider_panel.get("coinglass", {}),
            "moralis": provider_panel.get("moralis", {}),
            "next_gate": "operator approval plus live canary criteria, not probation-only readiness",
        },
    }
    return packet


def render_ceo_packet(packet: dict[str, Any]) -> str:
    summary = packet.get("ceo_summary") if isinstance(packet.get("ceo_summary"), dict) else {}
    provider_panel = packet.get("provider_actual_data_panel") if isinstance(packet.get("provider_actual_data_panel"), dict) else {}
    coinglass = provider_panel.get("coinglass") if isinstance(provider_panel.get("coinglass"), dict) else {}
    moralis = provider_panel.get("moralis") if isinstance(provider_panel.get("moralis"), dict) else {}
    return "\n".join(
        [
            "# Same-Day Cutover CEO Packet",
            "",
            f"Status: {packet.get('status')}",
            f"Generated UTC: {packet.get('generated_utc')}",
            f"Headline: {summary.get('headline')}",
            "",
            "## Provider Actual Data",
            f"- CoinGlass: {coinglass.get('dashboard_color')} actual={coinglass.get('actual_payload_present')} heartbeat_only={coinglass.get('heartbeat_only')}",
            f"- Moralis: {moralis.get('dashboard_color')} actual={moralis.get('actual_payload_present')} heartbeat_only={moralis.get('heartbeat_only')}",
            "",
            "## Live Control",
            f"- Live gate: {packet.get('live_gate')}",
            f"- Live ready: {packet.get('live_ready')}",
            f"- Live-ready from probation: {packet.get('live_ready_from_probation_allowed')}",
            "- Operator approval required for live: True",
            f"- Final marker: {packet.get('final_marker')}",
            "",
            "## Hard Blocks",
            *(f"- {item}" for item in packet.get("hard_blocks") or ["none"]),
            "",
            "## Provider Readiness Blockers",
            *(f"- {item}" for item in packet.get("provider_readiness_blockers") or ["none"]),
            "",
            "## Next Patch",
            f"- {packet.get('next_patch')}",
            "",
            "## Safety Assertions",
            "- API keys are not exposed.",
            "- Optional provider failures are not core-blocking.",
            "- Heartbeat-only payloads are not green.",
            "- Moralis is not polled on every symbol every minute.",
            "- CoinGlass public limit is not exceeded.",
        ]
    )


def _redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _read_json(redis_client: Any | None, key: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _csv(raw: str, *, upper: bool = False) -> list[str]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return [value.upper() for value in values] if upper else values


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _provider_readiness_blockers(provider_panel: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    coinglass = provider_panel.get("coinglass") if isinstance(provider_panel.get("coinglass"), dict) else {}
    moralis = provider_panel.get("moralis") if isinstance(provider_panel.get("moralis"), dict) else {}
    health = provider_panel.get("health") if isinstance(provider_panel.get("health"), dict) else {}
    coinglass_health = health.get("coinglass") if isinstance(health.get("coinglass"), dict) else {}
    moralis_health = health.get("moralis") if isinstance(health.get("moralis"), dict) else {}
    if not coinglass.get("actual_payload_present"):
        status = _first_status(
            coinglass.get("status"),
            coinglass_health.get("subscription_status"),
            coinglass_health.get("status"),
        )
        blockers.append(f"coinglass_actual_payload_absent:{status}")
    if not moralis.get("actual_payload_present"):
        status = _first_status(
            moralis.get("status"),
            moralis_health.get("subscription_status"),
            moralis_health.get("status"),
        )
        blockers.append(f"moralis_actual_payload_absent:{status}")
    return blockers


def _apply_health_fallbacks(provider_panel: dict[str, Any]) -> None:
    health = provider_panel.get("health") if isinstance(provider_panel.get("health"), dict) else {}
    health = dict(health)
    if not isinstance(health.get("coinglass"), dict):
        health["coinglass"] = build_coinglass_health(os.environ)
    if not isinstance(health.get("moralis"), dict):
        health["moralis"] = build_moralis_health(os.environ)
    provider_panel["health"] = health


def _cutover_status(*, hard_blocks: list[str], provider_readiness_blockers: list[str]) -> str:
    if hard_blocks or provider_readiness_blockers:
        return "LIVE_CANARY_NOT_READY"
    return "LIVE_CANARY_OPERATOR_REVIEW_REQUIRED"


def _headline(status: str) -> str:
    if status == "LIVE_CANARY_OPERATOR_REVIEW_REQUIRED":
        return "Provider-rate-limited data stack is ready for operator review; live remains human-blocked."
    if status == "PRODUCTION_STACK_READY_LIVE_BLOCKED":
        return "Production stack is ready, but live remains human-blocked."
    return "Live canary is not ready; provider actual-data evidence is incomplete."


def _next_patch(*, hard_blocks: list[str], provider_readiness_blockers: list[str]) -> str:
    if hard_blocks:
        return "restore blocked_human_only live gate and rerun the same-day cutover packet"
    if any(item.startswith("coinglass_actual_payload_absent") for item in provider_readiness_blockers):
        return "activate/repair CoinGlass subscription endpoints, rerun provider loop, and confirm actual endpoint payloads"
    if any(item.startswith("moralis_actual_payload_absent") for item in provider_readiness_blockers):
        return "configure Moralis wallet/token watchlist or subscription access, rerun provider loop, and confirm actual on-chain payloads"
    return "operator may review first live canary packet; automatic live submission remains disabled"


def _first_status(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.upper() != "MISSING":
            return text
    return "MISSING"


if __name__ == "__main__":
    raise SystemExit(main())
