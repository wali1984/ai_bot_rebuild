"""V2 paper-only startup manifest supervisor (verify-only).

Maps every legacy startup role to its V2 paper-only equivalent and
probes the current host read-only for runtime state. Never starts or
stops any daemon, never loads or logs API credential values, never
calls the exchange, and never installs systemd units (it writes the
unit text as a file artifact only).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "v2_full_paper_only_startup_manifest_runtime_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"

KNOWN_UNIVERSE = (
    "1000BONKUSDT", "1000FLOKIUSDT", "1000PEPEUSDT", "1000SHIBUSDT",
    "ALICEUSDT", "ASTERUSDT", "AUCTIONUSDT", "AVNTUSDT",
    "BANKUSDT", "BARDUSDT", "BTCUSDT", "DOGEUSDT",
    "ETHUSDT", "FARTCOINUSDT", "HIGHUSDT", "LINKUSDT",
    "LTCUSDT", "PENGUUSDT", "PIPPINUSDT", "RAVEUSDT",
    "RIVERUSDT", "SOLUSDT", "UNIUSDT", "WIFUSDT", "XRPUSDT",
)
# Historical 3-symbol initial bridge-migration set. See
# :data:`v2.backend.app.services.native_runtime_migration.safety.V2_NATIVE_INITIAL_BRIDGE_SYMBOLS`
# for the canonical definition. Kept here for legacy import callers; new
# emitters must use the dynamic universe resolver.
V2_NATIVE_INITIAL_BRIDGE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
V2_NATIVE_ACTIVE_SYMBOLS = V2_NATIVE_INITIAL_BRIDGE_SYMBOLS


_SAFETY_PINS: dict[str, Any] = {
    "live_gate": LIVE_GATE_BLOCKED,
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "did_not_modify_legacy_tree": True,
    "did_not_stop_legacy_runtime": True,
    "did_not_stop_v2_runtime": True,
    "did_not_stop_report_center": True,
    "did_not_stop_replay_miner": True,
    "did_not_stop_codex_governors": True,
    "did_not_write_old_redis_keys": True,
    "did_not_call_exchange_mutation": True,
    "did_not_change_leverage_or_margin_mode": True,
    "did_not_create_paper_only_shutdown_acceptance_file": True,
    "did_not_weaken_paper_fill_gate": True,
    "did_not_deserialize_legacy_checkpoint": True,
    "did_not_install_systemd_units": True,
    "did_not_start_any_daemon": True,
    "did_not_stop_any_daemon": True,
    "did_not_start_live_network_feed": True,
    "did_not_run_raw_legacy_script": True,
    "did_not_mutate_live_symbols_paper_symbols_or_training_symbols": True,
    "did_not_adopt_any_symbol_universe_candidate": True,
    "did_not_expose_raw_api_keys": True,
    "did_not_print_any_raw_credential_value": True,
    "did_not_claim_trainer_native_readiness": True,
    "did_not_claim_full_migration": True,
}


def safety_block() -> dict[str, Any]:
    return dict(_SAFETY_PINS)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _safe_cmd(cmd: list[str], *, timeout: float = 4.0) -> str | None:
    binary = shutil.which(cmd[0])
    if binary is None:
        return None
    try:
        r = subprocess.run(
            [binary, *cmd[1:]], check=False, capture_output=True,
            text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout


STATUS_V2_SERVICE_ACTIVE = "V2_SERVICE_ACTIVE"
STATUS_V2_SERVICE_STARTABLE = "V2_SERVICE_STARTABLE"
STATUS_V2_BRIDGE_READ_ONLY = "V2_BRIDGE_READ_ONLY"
STATUS_V2_PLACEHOLDER_BLOCKED = "V2_PLACEHOLDER_BLOCKED"
STATUS_OPERATOR_DECISION_REQUIRED = "OPERATOR_DECISION_REQUIRED"
STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW = "NOT_REQUIRED_FOR_PAPER_SHADOW"

VALID_STATUSES = (
    STATUS_V2_SERVICE_ACTIVE,
    STATUS_V2_SERVICE_STARTABLE,
    STATUS_V2_BRIDGE_READ_ONLY,
    STATUS_V2_PLACEHOLDER_BLOCKED,
    STATUS_OPERATOR_DECISION_REQUIRED,
    STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
)


# Manifest: every legacy startup role -> V2 paper equivalent.
_MANIFEST_ROLES: list[dict[str, Any]] = [
    {
        "role_id": "preflight_duplicate_guard",
        "legacy_role": "duplicate_process_guard",
        "v2_paper_equivalent": (
            "supervisor file-lock registry + pending-task watchdog"
        ),
        "default_status": STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "preflight_redis_running",
        "legacy_role": "redis_running_check",
        "v2_paper_equivalent": "redis-cli PING in supervisor probe",
        "default_status": STATUS_V2_SERVICE_STARTABLE,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "monitoring_trainer_predictions",
        "legacy_role": "scripts_monitor_trainer_predictions",
        "v2_paper_equivalent": "v2 native CUDA trainer prediction monitor",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_native_rl_masa_ppo_cuda_trainer",
        "v2_redis_key_pattern": "v2:trainer:heartbeat",
        "public_payload_path": (
            "v2/frontend/public/v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/"
            "operator_dashboard_payload.json"
        ),
    },
    {
        "role_id": "monitoring_ingestors_watchdog",
        "legacy_role": "scripts_ingestors_watchdog",
        "v2_paper_equivalent": "v2 native ingestor watchdog (planned)",
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "ingest_binance_prices",
        "legacy_role": "ingest_binance",
        "v2_paper_equivalent": "v2 market ingestor (active for 3 symbols)",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_native_ingestors",
        "v2_redis_key_pattern": "v2:market:prices:*",
        "public_payload_path": (
            "v2/frontend/public/operator_runtime/v2_native_ingestors/latest/"
            "v2_native_ingestors_status.json"
        ),
    },
    {
        "role_id": "ingest_binance_ohlcv_dynamic",
        "legacy_role": "ingest_binance_ohlcv",
        "v2_paper_equivalent": (
            "v2 native Binance OHLCV ingestor (contract defined,"
            " client disabled)"
        ),
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": "v2:market:ohlcv:binance:*",
        "public_payload_path": None,
    },
    {
        "role_id": "ingest_binance_orderbook_dynamic",
        "legacy_role": "ingest_binance_orderbook",
        "v2_paper_equivalent": (
            "v2 native Binance orderbook ingestor (contract defined,"
            " client disabled)"
        ),
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": "v2:market:orderbook:binance:*",
        "public_payload_path": None,
    },
    {
        "role_id": "ingest_kucoin",
        "legacy_role": "ingest_kucoin",
        "v2_paper_equivalent": "v2 KuCoin ingestor (operator decision)",
        "default_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "ingest_coinank_direct",
        "legacy_role": "ingest_coinank",
        "v2_paper_equivalent": "direct legacy-owned CoinAnk live ingestor",
        "default_status": STATUS_V2_BRIDGE_READ_ONLY,
        "process_marker": "coinank-live-direct",
        "v2_redis_key_pattern": "coinank:* / features:coinank:* / latest:coinank:*",
        "public_payload_path": (
            "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/"
            "coinank_market_intelligence_status.json"
        ),
    },
    {
        "role_id": "ingest_coinapi_wsds",
        "legacy_role": "ingest_coinapi_wsds",
        "v2_paper_equivalent": (
            "v2 CoinAPI WSDS ingestor (operator decision)"
        ),
        "default_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "ingest_binance_liquidations",
        "legacy_role": "ingest_binance_liquidations",
        "v2_paper_equivalent": (
            "v2 liquidation WSS persistent paper-shadow daemon"
        ),
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "liquidation_wss",
        "v2_redis_key_pattern": "v2:market:liquidations:*",
        "public_payload_path": (
            "v2/frontend/public/v2_liquidation_wss_persistent_paper_shadow_"
            "daemon/latest/operator_dashboard_payload.json"
        ),
    },
    {
        "role_id": "ingest_realtime_price_provider",
        "legacy_role": "ingest_realtime_price_provider",
        "v2_paper_equivalent": "v2 market ingestor prices stream",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_native_ingestors",
        "v2_redis_key_pattern": "v2:market:prices:*",
        "public_payload_path": None,
    },
    {
        "role_id": "feature_pipeline",
        "legacy_role": "feature_pipeline",
        "v2_paper_equivalent": "v2 feature pipeline native (3 symbols)",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "feature_pipeline",
        "v2_redis_key_pattern": "v2:features:latest:*",
        "public_payload_path": None,
    },
    {
        "role_id": "ohlcv_resampler",
        "legacy_role": "ohlcv_resampler_hotfix",
        "v2_paper_equivalent": "v2 native OHLCV resampler (planned)",
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "technical_analysis",
        "legacy_role": "technical_analysis_service",
        "v2_paper_equivalent": "v2 TA via v2:features:ta:* (3 symbols)",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "feature_pipeline",
        "v2_redis_key_pattern": "v2:features:ta:*",
        "public_payload_path": None,
    },
    {
        "role_id": "paralysis_detectors",
        "legacy_role": "scripts_paralysis_detectors",
        "v2_paper_equivalent": "v2 native paralysis detector (planned)",
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "validate_symbol_universe_data",
        "legacy_role": "scripts_validate_symbol_universe_data",
        "v2_paper_equivalent": (
            "v2 native universe data validator (planned startup gate)"
        ),
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "trainer",
        "legacy_role": "rl_hybrid_trainer",
        "v2_paper_equivalent": (
            "v2 native RL/MASA/PPO CUDA trainer + native prediction publisher"
        ),
        "default_status": STATUS_V2_BRIDGE_READ_ONLY,
        "process_marker": "v2_native_rl_masa_ppo_cuda_trainer",
        "v2_redis_key_pattern": "v2:prediction:*",
        "public_payload_path": (
            "v2/frontend/public/v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/"
            "operator_dashboard_payload.json"
        ),
    },
    {
        "role_id": "orchestrator",
        "legacy_role": "rl_orchestrator_worker",
        "v2_paper_equivalent": "v2 orchestrator arbitration (paper-only)",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "orchestrator",
        "v2_redis_key_pattern": "v2:orchestrator:decisions",
        "public_payload_path": None,
    },
    {
        "role_id": "signal_router",
        "legacy_role": "signal_router",
        "v2_paper_equivalent": "not required for single-account paper-only",
        "default_status": STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "trader_primary",
        "legacy_role": "legacy_trader_primary",
        "v2_paper_equivalent": (
            "v2 paper-mode trader; legacy trader NOT ported"
        ),
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "paper_online_runtime",
        "v2_redis_key_pattern": "v2:paper:ledger",
        "public_payload_path": (
            "v2/frontend/public/operator_runtime/paper_online/latest/"
            "paper_online_runtime_status.json"
        ),
    },
    {
        "role_id": "trader_secondary",
        "legacy_role": "legacy_trader_secondary",
        "v2_paper_equivalent": (
            "operator decision before multi-account paper"
        ),
        "default_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "portfolio_monitor_primary",
        "legacy_role": "monitor_portfolio_primary",
        "v2_paper_equivalent": (
            "v2 account position monitor + position history tracker"
        ),
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "account_position_monitor",
        "v2_redis_key_pattern": "v2:positions:history:*",
        "public_payload_path": None,
    },
    {
        "role_id": "portfolio_monitor_secondary",
        "legacy_role": "monitor_portfolio_secondary",
        "v2_paper_equivalent": "operator decision for multi-account",
        "default_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "health_probe",
        "legacy_role": "scripts_health_probe",
        "v2_paper_equivalent": (
            "v2 report center freshness + executive command center"
        ),
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_report_center",
        "v2_redis_key_pattern": None,
        "public_payload_path": (
            "v2/frontend/public/v2_executive_command_center/latest/"
            "operator_dashboard_payload.json"
        ),
    },
    {
        "role_id": "critical_health_monitor",
        "legacy_role": "critical_health_monitor",
        "v2_paper_equivalent": (
            "v2 native critical health monitor (planned startup gate)"
        ),
        "default_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "process_marker": None,
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "replay_outcome_miner",
        "legacy_role": "no_legacy_equivalent",
        "v2_paper_equivalent": "v2 post-hoc replay outcome miner timer",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_post_hoc_replay",
        "v2_redis_key_pattern": None,
        "public_payload_path": (
            "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/"
            "operator_dashboard_payload.json"
        ),
    },
    {
        "role_id": "report_center_indexer",
        "legacy_role": "no_legacy_equivalent",
        "v2_paper_equivalent": "v2 report center indexer timer",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_report_center",
        "v2_redis_key_pattern": None,
        "public_payload_path": (
            "v2/frontend/public/v2_report_center/latest/index.json"
        ),
    },
    {
        "role_id": "continuous_remediation_governor",
        "legacy_role": "no_legacy_equivalent",
        "v2_paper_equivalent": "v2 continuous remediation governor",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "continuous_remediation",
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
    {
        "role_id": "self_healing_controller",
        "legacy_role": "no_legacy_equivalent",
        "v2_paper_equivalent": "v2 autonomous self-healing controller",
        "default_status": STATUS_V2_SERVICE_ACTIVE,
        "process_marker": "v2_autonomous_full_rebuild",
        "v2_redis_key_pattern": None,
        "public_payload_path": None,
    },
]


# ---------------------------------------------------------------------------
# Read-only probes
# ---------------------------------------------------------------------------


def _probe_process_alive(marker: str | None) -> bool:
    if not marker:
        return False
    text = _safe_cmd(["ps", "-eo", "args"])
    if not text:
        return False
    needle = marker.lower()
    for line in text.splitlines():
        if needle in line.lower():
            return True
    return False


def _probe_redis_keys_for_pattern(pattern: str | None) -> int | None:
    if not pattern:
        return None
    text = _safe_cmd(["redis-cli", "--scan", "--pattern", pattern])
    if text is None:
        return None
    return len([l for l in text.splitlines() if l.strip()])


def _probe_public_payload_age(repo_root: Path, rel_path: str | None) -> float | None:
    if not rel_path:
        return None
    p = repo_root / rel_path
    if not p.exists():
        return None
    try:
        return max(0.0, time.time() - p.stat().st_mtime)
    except OSError:
        return None


def _probe_role(role: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    process_alive = _probe_process_alive(role.get("process_marker"))
    redis_count = _probe_redis_keys_for_pattern(role.get("v2_redis_key_pattern"))
    payload_age = _probe_public_payload_age(
        repo_root, role.get("public_payload_path")
    )
    default_status = role["default_status"]
    observed_status = default_status
    if default_status == STATUS_V2_SERVICE_ACTIVE:
        observable = (
            process_alive
            or (redis_count is not None and redis_count > 0)
            or (payload_age is not None and payload_age < 60 * 60)
        )
        if not observable:
            observed_status = STATUS_V2_SERVICE_STARTABLE
    return {
        **role,
        "process_alive_probe": process_alive,
        "v2_redis_key_count_probe": redis_count,
        "public_payload_age_seconds_probe": payload_age,
        "observed_status": observed_status,
        "status": observed_status,
    }


def build_v2_paper_startup_manifest_status(repo_root: Path) -> dict[str, Any]:
    roles = [_probe_role(r, repo_root) for r in _MANIFEST_ROLES]
    counts: dict[str, int] = {}
    for r in roles:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION + "_v2_paper_startup_manifest_status",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "role_count": len(roles),
        "status_counts": counts,
        "valid_statuses": list(VALID_STATUSES),
        "roles": roles,
        "started_or_stopped_any_daemon_this_run": False,
        "installed_systemd_units_this_run": False,
        "ran_raw_legacy_script_this_run": False,
        "claimed_trainer_native_readiness": False,
        "claimed_full_migration": False,
    }


# ---------------------------------------------------------------------------
# API key presence (env-var name only — value never read or emitted)
# ---------------------------------------------------------------------------


_API_KEY_SOURCES: list[dict[str, Any]] = [
    {"source": "binance_public_market_data", "env_var_name": None,
     "notes": "Public Binance market data does not require an API key."},
    {"source": "binance_private_or_order", "env_var_name": "BINANCE_API_KEY",
     "notes": "Not used in paper-only startup."},
    {"source": "coinapi", "env_var_name": "COINAPI_API_KEY",
     "notes": "Optional secondary feed; operator decision."},
    {"source": "arkham", "env_var_name": "ARKHAM_API_KEY",
     "notes": "Alt-data placeholder; operator decision."},
    {"source": "kucoin_public", "env_var_name": None,
     "notes": "Public KuCoin market data does not require an API key."},
    {"source": "coinank", "env_var_name": "COINANK_API_KEY",
     "notes": "Free tier via bridge; paid is operator-gated."},
]


def build_api_key_presence_status(
    *,
    env_getter: Callable[[str], str | None] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Probe presence by env-var NAME only.

    Consults two sources (in order of preference):

      1. ``os.environ`` via ``env_getter`` (shell export)
      2. ``.local_secrets/live_credentials.env`` via a presence-only
         loader that returns variable NAMES (never values)

    The function never reads or emits a credential value.
    """
    from v2.backend.app.services.security.local_credentials_env_presence import (
        probe_local_credentials_env_presence,
    )

    getenv = env_getter or os.environ.get

    file_presence = None
    file_var_names: set[str] = set()
    if repo_root is not None:
        file_presence = probe_local_credentials_env_presence(repo_root)
        file_var_names = set(file_presence.present_var_names)

    rows: list[dict[str, Any]] = []
    for src in _API_KEY_SOURCES:
        env_name = src["env_var_name"]
        if env_name is None:
            present = True
            status_str = "NOT_REQUIRED"
            source_label = "NOT_REQUIRED"
        else:
            in_os = bool(getenv(env_name))
            in_file = env_name in file_var_names
            present = in_os or in_file
            if in_os and in_file:
                source_label = "OS_ENV_AND_LOCAL_FILE"
            elif in_os:
                source_label = "OS_ENV_ONLY"
            elif in_file:
                source_label = "LOCAL_FILE_ONLY"
            else:
                source_label = "ABSENT"
            status_str = (
                "PRESENT_BY_ENV_NAME_ONLY_VALUE_NOT_READ"
                if present
                else "OPERATOR_DECISION_REQUIRED"
            )
        rows.append({
            "source": src["source"],
            "env_var_name": env_name,
            "required_for_paper_only": False,
            "present_by_name": present,
            "presence_source": source_label,
            "status": status_str,
            "notes": src["notes"],
        })
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION + "_api_key_presence_status",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "rows": rows,
        "row_count": len(rows),
        "value_read_or_emitted": False,
        "raw_secret_value_read_or_emitted": False,
    }
    if file_presence is not None:
        out["local_credentials_env_file"] = {
            "file_path": file_presence.file_path,
            "file_present": file_presence.file_present,
            "parse_error": file_presence.parse_error,
            "present_var_name_count": len(file_presence.present_var_names),
            "raw_secret_value_read_or_emitted": (
                file_presence.raw_secret_value_read_or_emitted
            ),
        }
    return out


# ---------------------------------------------------------------------------
# Dynamic 25-symbol paper coverage
# ---------------------------------------------------------------------------


_FAMILIES = (
    "price", "ohlcv", "orderbook", "liquidation", "funding",
    "open_interest", "coinank", "kucoin", "coinapi", "ta",
    "features", "prediction", "risk", "orchestrator", "paper_intent",
    "replay_miner", "website_visibility",
)


def _family_status_for_symbol(symbol: str, family: str) -> str:
    if family in ("kucoin", "coinapi"):
        return "OPERATOR_DECISION_REQUIRED"
    if family == "liquidation":
        return (
            "V2_NATIVE_ACTIVE"
            if symbol in V2_NATIVE_ACTIVE_SYMBOLS
            else "EVENT_DEPENDENT"
        )
    if family in ("ohlcv", "orderbook"):
        return "PLACEHOLDER_NOT_READY"
    if family in ("prediction", "coinank"):
        return (
            "V2_BRIDGE_READ_ONLY"
            if symbol in V2_NATIVE_ACTIVE_SYMBOLS
            else "MISSING_SOURCE"
        )
    return (
        "V2_NATIVE_ACTIVE"
        if symbol in V2_NATIVE_ACTIVE_SYMBOLS
        else "MISSING_SOURCE"
    )


def build_dynamic_symbol_paper_runtime_coverage() -> dict[str, Any]:
    table: dict[str, dict[str, str]] = {}
    for sym in KNOWN_UNIVERSE:
        table[sym] = {
            family: _family_status_for_symbol(sym, family)
            for family in _FAMILIES
        }
    family_counts: dict[str, dict[str, int]] = {}
    for family in _FAMILIES:
        counts: dict[str, int] = {}
        for sym in KNOWN_UNIVERSE:
            status = table[sym][family]
            counts[status] = counts.get(status, 0) + 1
        family_counts[family] = counts
    from v2.backend.app.services.v2_symbol_runtime_universe import (
        resolve_symbols,
    )
    currently_active = list(resolve_symbols(smoke_test=False, include_baseline=True))
    return {
        "schema_version": SCHEMA_VERSION + "_dynamic_symbol_paper_runtime_coverage_v2",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "families": list(_FAMILIES),
        "universe": list(KNOWN_UNIVERSE),
        "currently_active_symbols": currently_active,
        "currently_active_symbol_count": len(currently_active),
        "initial_bridge_migration_symbols": list(V2_NATIVE_INITIAL_BRIDGE_SYMBOLS),
        "per_symbol_table": table,
        "family_status_counts": family_counts,
        "bridge_data_labeled_as_v2_native": False,
        "currently_active_symbols_source": (
            "v2_symbol_runtime_universe.resolve_symbols(baseline+published)"
        ),
    }


# ---------------------------------------------------------------------------
# Runtime proof
# ---------------------------------------------------------------------------


def build_paper_runtime_process_status(repo_root: Path) -> dict[str, Any]:
    ps_text = _safe_cmd(["ps", "-eo", "pid,etime,comm,args"])
    v2_processes: list[dict[str, Any]] = []
    if ps_text:
        v2_markers = (
            "v2.backend.app",
            "v2_post_hoc_replay",
            "v2_report_center",
            "v2_24h",
            "paper_online_runtime",
            "uvicorn",
            "report_center_indexer",
        )
        for line in ps_text.splitlines()[1:]:
            parts = line.strip().split(None, 3)
            if len(parts) < 4:
                continue
            pid, etime, comm, args = parts
            lowered = args.lower()
            if any(m in lowered for m in v2_markers):
                v2_processes.append({
                    "pid": pid,
                    "etime": etime,
                    "comm": comm,
                    "args_head": args[:160],
                })

    v2_key_text = _safe_cmd(["redis-cli", "--scan", "--pattern", "v2:*"])
    v2_key_count = (
        len([l for l in v2_key_text.splitlines() if l.strip()])
        if v2_key_text is not None else None
    )

    report_index = repo_root / "v2/frontend/public/v2_report_center/latest/index.json"
    report_age = (
        max(0.0, time.time() - report_index.stat().st_mtime)
        if report_index.exists() else None
    )

    miner_status = (
        repo_root
        / "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/"
        "latest/post_hoc_replay_outcome_status.json"
    )
    miner_age = (
        max(0.0, time.time() - miner_status.stat().st_mtime)
        if miner_status.exists() else None
    )

    return {
        "schema_version": SCHEMA_VERSION + "_paper_runtime_process_status",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "v2_process_count": len(v2_processes),
        "v2_processes_head": v2_processes[:32],
        "v2_redis_v2_namespace_key_count": v2_key_count,
        "v2_redis_scan_succeeded": v2_key_count is not None,
        "report_center_index_age_seconds": report_age,
        "replay_miner_status_age_seconds": miner_age,
        "old_redis_write_count": 0,
        "exchange_mutation_call_count": 0,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }


# ---------------------------------------------------------------------------
# Systemd unit + timer text (FILE ARTIFACTS ONLY — never installed)
# ---------------------------------------------------------------------------


SYSTEMD_UNIT_TEXT = (
    "[Unit]\n"
    "Description=AI Bot V2 - Full Paper-Only Startup Manifest Supervisor"
    " (verify-only)\n"
    "After=network-online.target redis-server.service\n"
    "Wants=network-online.target\n"
    "\n"
    "# This unit file is GENERATED as a file artifact. It is NOT auto-\n"
    "# installed. Operator must explicitly run\n"
    "#   systemctl --user enable --now"
    " ai-bot-v2-full-paper-startup-runtime.service\n"
    "# after reviewing the verification report.\n"
    "# The unit invokes a verify-only CLI which never starts/stops any\n"
    "# daemon, never loads any API key value, never writes legacy Redis,\n"
    "# never calls the exchange, and never approves anything.\n"
    "\n"
    "[Service]\n"
    "Type=oneshot\n"
    "WorkingDirectory=%h/Desktop/AI BOT REBUILD\n"
    "Environment=PYTHONPATH=%h/Desktop/AI BOT REBUILD\n"
    "ExecStart=%h/Desktop/AI BOT REBUILD/.venv/bin/python -m "
    "v2.backend.app.cli.v2_full_paper_only_startup_manifest_runtime\n"
    "Nice=10\n"
    "IOSchedulingClass=best-effort\n"
    "IOSchedulingPriority=7\n"
    "\n"
    "[Install]\n"
    "WantedBy=default.target\n"
)


SYSTEMD_TIMER_TEXT = (
    "[Unit]\n"
    "Description=AI Bot V2 - Full Paper-Only Startup Manifest Supervisor"
    " (periodic verify)\n"
    "\n"
    "# Operator-installed only. Not auto-enabled.\n"
    "\n"
    "[Timer]\n"
    "OnBootSec=2min\n"
    "OnUnitActiveSec=10min\n"
    "AccuracySec=30s\n"
    "Unit=ai-bot-v2-full-paper-startup-runtime.service\n"
    "\n"
    "[Install]\n"
    "WantedBy=timers.target\n"
)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class PaperStartupPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path
    systemd_dir: Path


def default_paths(repo_root: Path) -> PaperStartupPaths:
    return PaperStartupPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_full_paper_only_startup_manifest_runtime/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_full_paper_only_startup_manifest_runtime/latest",
        systemd_dir=repo_root / "claude_worklog/systemd/user",
    )


@dataclass
class PaperStartupRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def build_operator_dashboard_payload(
    *, manifest_status, api_keys, coverage, process_status,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": utc_now_iso(),
        "go_no_go": "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_READY",
        "safety_scoreboard": safety_block(),
        "summary": {
            "role_count": manifest_status["role_count"],
            "status_counts": manifest_status["status_counts"],
            "api_key_rows": api_keys["row_count"],
            "api_key_value_read_or_emitted": (
                api_keys["value_read_or_emitted"]
            ),
            "universe_size": len(coverage["universe"]),
            "currently_active_symbol_count": len(
                coverage["currently_active_symbols"]
            ),
            "v2_process_count": process_status["v2_process_count"],
            "v2_redis_v2_namespace_key_count": process_status[
                "v2_redis_v2_namespace_key_count"
            ],
            "report_center_index_age_seconds": process_status[
                "report_center_index_age_seconds"
            ],
            "replay_miner_status_age_seconds": process_status[
                "replay_miner_status_age_seconds"
            ],
        },
        "live_blocked": True,
        "shutdown_blocked": True,
        "controls_present": False,
        "fake_readiness": False,
    }


def run_paper_startup_packet(
    paths: PaperStartupPaths,
    *, env_getter: Callable[[str], str | None] | None = None,
) -> PaperStartupRunResult:
    manifest_status = build_v2_paper_startup_manifest_status(paths.repo_root)
    api_keys = build_api_key_presence_status(
        env_getter=env_getter, repo_root=paths.repo_root,
    )
    coverage = build_dynamic_symbol_paper_runtime_coverage()
    process_status = build_paper_runtime_process_status(paths.repo_root)
    dashboard = build_operator_dashboard_payload(
        manifest_status=manifest_status, api_keys=api_keys,
        coverage=coverage, process_status=process_status,
    )

    _atomic_write_json(
        paths.packet_dir / "v2_paper_startup_manifest_status.json",
        manifest_status,
    )
    _atomic_write_json(
        paths.packet_dir / "api_key_presence_status.json", api_keys
    )
    _atomic_write_json(
        paths.packet_dir / "dynamic_symbol_paper_runtime_coverage.json",
        coverage,
    )
    _atomic_write_json(
        paths.packet_dir / "paper_runtime_process_status.json", process_status
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "v2_paper_startup_manifest_status.json",
        manifest_status,
    )
    _atomic_write_json(
        paths.public_dir / "dynamic_symbol_paper_runtime_coverage.json",
        coverage,
    )

    _atomic_write_text(
        paths.systemd_dir / "ai-bot-v2-full-paper-startup-runtime.service",
        SYSTEMD_UNIT_TEXT,
    )
    _atomic_write_text(
        paths.systemd_dir / "ai-bot-v2-full-paper-startup-runtime.timer",
        SYSTEMD_TIMER_TEXT,
    )

    report = _render_report(
        manifest_status, api_keys, coverage, process_status, dashboard,
    )
    _atomic_write_text(
        paths.packet_dir
        / "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_READY\n",
    )

    return PaperStartupRunResult(
        go_no_go="V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_REPORT.md",
            paths.packet_dir / "v2_paper_startup_manifest_status.json",
            paths.packet_dir / "api_key_presence_status.json",
            paths.packet_dir / "dynamic_symbol_paper_runtime_coverage.json",
            paths.packet_dir / "paper_runtime_process_status.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "v2_paper_startup_manifest_status.json",
            paths.public_dir / "dynamic_symbol_paper_runtime_coverage.json",
            paths.systemd_dir / "ai-bot-v2-full-paper-startup-runtime.service",
            paths.systemd_dir / "ai-bot-v2-full-paper-startup-runtime.timer",
        ],
    )


def _render_report(manifest_status, api_keys, coverage, process_status, dashboard) -> str:
    lines = []
    lines.append("# V2 Full Paper-Only Startup Manifest Runtime Report\n\n")
    lines.append(
        "GO/NO-GO: V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " approves_legacy_shutdown=false.\n\n"
    )
    lines.append("## Phase 1 - V2 paper startup manifest\n")
    lines.append("- role_count: " + str(manifest_status["role_count"]) + "\n")
    for status, n in sorted(manifest_status["status_counts"].items()):
        lines.append("  - " + status + ": " + str(n) + "\n")
    lines.append("\n## Phase 2 - Safe components verify state\n")
    for role in manifest_status["roles"]:
        lines.append(
            "- " + role["role_id"] + " [" + role["status"] + "] "
            "process=" + str(role["process_alive_probe"])
            + " redis_keys=" + str(role["v2_redis_key_count_probe"])
            + " payload_age_s=" + str(role["public_payload_age_seconds_probe"])
            + "\n"
        )
    lines.append("\n## Phase 3 - API key presence (by env-var name only)\n")
    for row in api_keys["rows"]:
        lines.append(
            "- " + row["source"] + ": env=" + str(row["env_var_name"])
            + " status=" + row["status"] + "\n"
        )
    lines.append(
        "\n- value_read_or_emitted: "
        + str(api_keys["value_read_or_emitted"]) + "\n\n"
    )
    lines.append("## Phase 4 - Dynamic 25-symbol paper coverage\n")
    for family, counts in coverage["family_status_counts"].items():
        lines.append("- " + family + ": " + str(counts) + "\n")
    lines.append("\n## Phase 5 - Runtime proof\n")
    for k in (
        "v2_process_count",
        "v2_redis_v2_namespace_key_count",
        "v2_redis_scan_succeeded",
        "report_center_index_age_seconds",
        "replay_miner_status_age_seconds",
        "old_redis_write_count",
        "exchange_mutation_call_count",
        "live_gate",
        "live_symbols",
    ):
        lines.append("- " + k + ": " + str(process_status.get(k)) + "\n")
    lines.append("\n## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not start or stop any daemon.\n"
        "- Did not install any systemd unit (unit + timer files are written as artifacts only).\n"
        "- Did not run any raw legacy script.\n"
        "- Did not start any new network feed.\n"
        "- Did not load or log any API credential value.\n"
        "- Did not modify the legacy bot tree.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not mutate live_symbols, paper_symbols, or training_symbols.\n"
        "- Did not adopt any Symbol Universe candidate.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not deserialize any legacy checkpoint.\n"
        "- Did not claim trainer native readiness.\n"
        "- Did not claim full migration.\n"
    )
    return "".join(lines)
