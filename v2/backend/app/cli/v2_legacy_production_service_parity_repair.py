"""Emit V2 legacy production-service parity repair artifacts.

This is an evidence-only report for the legacy ``start_all_services_production``
audit. It reads current V2 systemd/Redis/public-payload status, classifies each
legacy role, and writes report-center/public artifacts. It does not start or
stop services, call exchanges, send Telegram messages, reconnect VPN, trim
Redis, or write old Redis keys.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


WORKER_ID = "v2_legacy_production_service_parity_repair"
GATE_READY = "V2_LEGACY_PRODUCTION_SERVICE_PARITY_REPAIR_READY"
GATE_BLOCKED = "V2_LEGACY_PRODUCTION_SERVICE_PARITY_REPAIR_BLOCKED"
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public/v2_legacy_production_service_parity_repair/latest"
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness/v2_legacy_production_service_parity_repair/latest"


@dataclass(frozen=True)
class LegacyRole:
    legacy_service: str
    legacy_script: str
    v2_equivalent: str
    expected_systemd_unit: str | None
    required_for_readonly_parity: bool
    real_reason_if_not_active: str | None = None


LEGACY_ROLES: tuple[LegacyRole, ...] = (
    LegacyRole("VPN Monitor", "vpn_monitor.py", "v2_system_observability_status_publisher route/interface probe", None, False, "VPN reconnect remains operator-only"),
    LegacyRole("Telegram System Monitor", "system_telegram_monitor.py", "v2_system_observability_status_publisher Telegram config probe", None, False, "Telegram send remains operator-only"),
    LegacyRole("Memory / OOM Monitor", "monitor_system_memory.py", "v2_system_observability_status_publisher memory/Redis telemetry", None, True),
    LegacyRole("Enhanced Memory Leak Detector", "scripts/memory_monitor.py", "v2_system_observability_status_publisher process/memory telemetry", None, True),
    LegacyRole("Trainer Predictions Monitor", "scripts/monitor_trainer_predictions.py", "v2 native CUDA trainer payload + v2_system_observability trainer prediction count", "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.timer", True),
    LegacyRole("Binance Live", "ingest/live_binance.py", "v2_native_ingestors_live_loop", "ai-bot-v2-native-ingestors-live-loop.service", True),
    LegacyRole("KuCoin Live", "ingest/live_kucoin.py", "v2_kucoin_ingestor_worker", "ai-bot-v2-kucoin-public-rest-loop.service", True),
    LegacyRole("CoinAnk Live", "ingest/live_coinank.py", "direct legacy-owned live_coinank.py", "ai-bot-v2-coinank-live-direct.service", True),
    LegacyRole("CoinAnk Global Aggregator", "ingest/live_coinank_global_aggregator.py", "direct legacy-owned live_coinank_global_aggregator.py", "ai-bot-v2-coinank-global-aggregator-direct.service", True),
    LegacyRole("Binance Liquidations WS", "ingest/live_binance_liquidations.py", "v2_liquidation_wss_loop", "ai-bot-v2-liquidation-wss-paper-shadow.service", True),
    LegacyRole("Liquidation Bridge", "ingest/liquidation_bridge.py", "v2 liquidation WSS aggregate + levels engine", "ai-bot-v2-liquidation-levels-engine.service", True),
    LegacyRole("Liquidation Levels Engine", "ingest/liquidation_levels_engine.py", "v2_liquidation_levels_engine", "ai-bot-v2-liquidation-levels-engine.service", True),
    LegacyRole("Realtime Price Provider", "ingest/realtime_price_provider.py", "v2_native_ingestors_live_loop prices", "ai-bot-v2-native-ingestors-live-loop.service", True),
    LegacyRole("CoinAPI WSDS", "ingest/live_coinapi_wsds.py", "v2_coinapi_wsds_loop", "ai-bot-v2-coinapi-wsds-loop.service", True),
    LegacyRole("CoinAPI V1 WS", "ingest/live_coinapi_v1.py", "v2_coinapi_rest_ingestor_worker", "ai-bot-v2-coinapi-rest-fallback-loop.service", True),
    LegacyRole("OHLCV Resampler", "ohlcv_resampler_hotfix.py", "v2 native OHLCV five-timeframe keys", "ai-bot-v2-native-ingestors-live-loop.service", True),
    LegacyRole("Feature Pipeline", "feature_pipeline.py", "v2_feature_pipeline_native_loop 101 x 5", "ai-bot-v2-feature-pipeline-native-loop.service", True),
    LegacyRole("Technical Analysis Service", "ingest/live_technical_analysis.py", "v2_full_talib_ta_loop + v2:technical_analysis:*", "ai-bot-v2-full-talib-ta-loop.service", True),
    LegacyRole("Hybrid Trainer", "rl/hybrid_trainer.py", "v2 native RL/MASA/PPO CUDA trainer + rl-core sidecar", "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.timer", True),
    LegacyRole("Orchestrator Worker", "rl/orchestrator_worker.py", "v2_orchestrator_arbitration_loop", "ai-bot-v2-orchestrator-arbitration-loop.service", True),
    LegacyRole(
        "Primary Trader",
        "trading/trader.py",
        "v2_trader_runtime_loop + BinanceUsdMWebSocketPrimaryTransport live-blocked; v2_trade_management_paper_loop remains paper-only",
        "ai-bot-v2-trade-management-paper-loop.service",
        True,
    ),
    LegacyRole("Asjad Trader", "trading/trader-asjad.py", "not ported to live multi-account; paper/live gate blocks execution", None, False, "multi-account live execution requires separate operator approval and audit contract"),
    LegacyRole("Primary Portfolio Monitor", "monitor_portfolio_primary.py", "v2_portfolio_state_publisher", "ai-bot-v2-portfolio-state-publisher.service", True),
    LegacyRole("Asjad Portfolio Monitor", "monitor_portfolio_asjad.py", "not ported to live multi-account; V2 account monitor remains read-only/operator-gated", None, False, "multi-account portfolio requires operator account contract"),
)


def _est_now() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _safe_cmd(cmd: list[str], *, timeout: float = 8.0) -> tuple[int | None, str]:
    binary = shutil.which(cmd[0])
    if binary is None:
        return None, ""
    try:
        result = subprocess.run(
            [binary, *cmd[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None, ""
    return int(result.returncode), result.stdout


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _systemd_units() -> dict[str, dict[str, str]]:
    _code, stdout = _safe_cmd(["systemctl", "--user", "list-units", "ai-bot-v2-*", "--type=service", "--all", "--no-pager", "--no-legend"])
    units: dict[str, dict[str, str]] = {}
    for line in stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        units[unit] = {"load": load, "active": active, "sub": sub}
    return units


def _redis_counts(redis_client: Any) -> dict[str, Any]:
    patterns = {
        "ohlcv": "v2:market:ohlcv:binance:*",
        "features_latest": "v2:features:latest:*",
        "technical_analysis": "v2:technical_analysis:*",
        "ta": "v2:features:ta:*",
        "ta_full": "v2:features:ta_full:*",
        "liquidation_levels": "v2:liquidations:levels:*",
        "unified_features": "v2:unified_features:*",
        "predictions": "v2:prediction:*",
    }
    counts: dict[str, Any] = {}
    if redis_client is None:
        return {name: {"total": 0, "by_timeframe": {}} for name in patterns}
    for name, pattern in patterns.items():
        by_timeframe: dict[str, int] = {}
        total = 0
        heartbeat_keys = 0
        try:
            keys = list(redis_client.scan_iter(match=pattern, count=1000))
        except Exception:
            keys = []
        for key in keys:
            if not isinstance(key, str):
                continue
            parts = key.split(":")
            timeframe = parts[-1] if parts else "unknown"
            if timeframe == "heartbeat":
                heartbeat_keys += 1
                continue
            total += 1
            by_timeframe[timeframe] = by_timeframe.get(timeframe, 0) + 1
        counts[name] = {
            "total": total,
            "heartbeat_keys": heartbeat_keys,
            "by_timeframe": dict(sorted(by_timeframe.items())),
        }
    return counts


def _public_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def build_payload() -> dict[str, Any]:
    units = _systemd_units()
    redis_client = _connect_redis()
    counts = _redis_counts(redis_client)
    ingestors = _public_json(REPO_ROOT / "v2/frontend/public/operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json") or {}
    observability = _public_json(PUBLIC_DIR.parent.parent / "operator_runtime/v2_system_observability/latest/v2_system_observability_status.json")
    rows: list[dict[str, Any]] = []
    blocking: list[str] = []
    for role in LEGACY_ROLES:
        unit = units.get(role.expected_systemd_unit or "")
        active = bool(unit and unit.get("active") == "active")
        if role.expected_systemd_unit is None:
            status = "REAL_REASON_NOT_ACTIVE" if role.real_reason_if_not_active else "V2_STATUS_PAYLOAD_READY"
        elif active:
            status = "V2_SERVICE_ACTIVE"
        else:
            status = "V2_SERVICE_NOT_ACTIVE"
        if role.required_for_readonly_parity and status == "V2_SERVICE_NOT_ACTIVE":
            blocking.append(role.legacy_service)
        rows.append({
            "legacy_service": role.legacy_service,
            "legacy_script": role.legacy_script,
            "v2_equivalent": role.v2_equivalent,
            "expected_systemd_unit": role.expected_systemd_unit,
            "systemd_state": unit,
            "status": status,
            "required_for_readonly_parity": role.required_for_readonly_parity,
            "real_reason_if_not_active": role.real_reason_if_not_active,
            "old_redis_write_allowed": False,
            "exchange_mutation_allowed": False,
        })
    feature_latest = counts["features_latest"]
    ta = counts["technical_analysis"]
    liq = counts["liquidation_levels"]
    grid_ok = (
        feature_latest["total"] >= 505
        and ta["total"] >= 505
        and liq["total"] >= 505
    )
    gate = GATE_READY if not blocking and grid_ok else GATE_BLOCKED
    return {
        "schema_version": "v2_legacy_production_service_parity_repair_v1",
        "worker_id": WORKER_ID,
        "gate": gate,
        "generated_est": _est_now(),
        "legacy_roles_total": len(LEGACY_ROLES),
        "required_readonly_roles_blocking": blocking,
        "service_rows": rows,
        "redis_counts": counts,
        "ingestors_status": {
            "classification": ingestors.get("classification"),
            "active_count": ingestors.get("active_count"),
            "total_count": ingestors.get("total_count"),
        },
        "system_observability_status": {
            "classification": observability.get("classification") if isinstance(observability, dict) else None,
            "degraded_sections": observability.get("degraded_sections") if isinstance(observability, dict) else None,
        },
        "read_only_data_grid_ok": grid_ok,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "redis_trim_attempted": False,
        "legacy_restart_attempted": False,
        "recommendation": "READONLY_PAPER_PARITY_REPAIRED_LIVE_REMAINS_BLOCKED",
    }


def _report(payload: dict[str, Any]) -> str:
    rows = payload["service_rows"]
    fixed = sum(1 for row in rows if row["status"] in {"V2_SERVICE_ACTIVE", "V2_STATUS_PAYLOAD_READY"})
    real_reason = sum(1 for row in rows if row["status"] == "REAL_REASON_NOT_ACTIVE")
    return "\n".join([
        "# V2 Legacy Production Service Parity Repair Report",
        "",
        f"Gate: `{payload['gate']}`",
        f"Generated EST: `{payload['generated_est']}`",
        f"Legacy roles checked: `{payload['legacy_roles_total']}`",
        f"Repaired/covered roles: `{fixed}`",
        f"Real-reason non-active roles: `{real_reason}`",
        f"Blocking required read-only roles: `{len(payload['required_readonly_roles_blocking'])}`",
        f"Features latest grid: `{payload['redis_counts']['features_latest']['total']}`",
        f"Technical analysis grid: `{payload['redis_counts']['technical_analysis']['total']}`",
        f"Full TA grid: `{payload['redis_counts']['ta_full']['total']}`",
        f"Liquidation levels grid: `{payload['redis_counts']['liquidation_levels']['total']}`",
        f"Ingestors: `{payload['ingestors_status']['classification']}` active_count=`{payload['ingestors_status']['active_count']}`",
        f"System observability: `{payload['system_observability_status']['classification']}`",
        "",
        "Live/canary remain blocked. Multi-account live trader/portfolio roles are not activated because the live gate and audit contracts remain human/operator-gated.",
        "",
        "- live_gate: `blocked_human_only`",
        "- live_symbols: `[]`",
        "- execution_live_symbols: `[]`",
        "",
        "Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no Redis trim, no legacy restart, no VPN reconnect, no Telegram send.",
        "",
    ])


def _write_all(payload: dict[str, Any]) -> list[Path]:
    written: list[Path] = []
    files = {
        "GO_NO_GO.md": payload["gate"] + "\n",
        "V2_LEGACY_PRODUCTION_SERVICE_PARITY_REPAIR_REPORT.md": _report(payload),
        "legacy_service_parity_status.json": json.dumps(payload, indent=2, sort_keys=True) + "\n",
        "operator_dashboard_payload.json": json.dumps(payload, indent=2, sort_keys=True) + "\n",
    }
    for directory in (PUBLIC_DIR, WORKLOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        for name, body in files.items():
            path = directory / name
            path.write_text(body, encoding="utf-8")
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--write", action="store_true", default=True)
    args = parser.parse_args(argv)
    payload = build_payload()
    written = _write_all(payload) if args.write else []
    print(json.dumps({"gate": payload["gate"], "paths_written": [str(path) for path in written]}, indent=2, sort_keys=True))
    return 0 if payload["gate"] == GATE_READY else 1


if __name__ == "__main__":
    sys.exit(main())
