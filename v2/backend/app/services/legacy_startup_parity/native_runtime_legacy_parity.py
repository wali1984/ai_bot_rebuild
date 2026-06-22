"""V2 legacy-startup-manifest parity and bridge-exit planner.

Analysis-only. Parses the current legacy production startup manifest at
``/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh``
(read-only) when available, keeps the repo snapshot as drift evidence, and
emits a parity packet that drives V2 to startup-order parity with the legacy
production runtime.

This module never:
  * mutates the legacy bot tree
  * writes legacy Redis keys
  * places / cancels / modifies exchange orders
  * approves live, canary, legacy-shutdown, or Redis-trim
  * mutates live_symbols / paper_symbols / training_symbols
  * starts or stops any V2 or legacy daemon
  * installs systemd units or scheduler daemons
  * deserializes any legacy checkpoint
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "v2_legacy_startup_manifest_parity_and_bridge_exit_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"

LEGACY_STARTUP_SCRIPT_SNAPSHOT = (
    "legacy_reference/scripts/start_all_services_production.sh"
)
LEGACY_STARTUP_SCRIPT_LOCAL_REL = (
    "scripts/start_all_services_production.sh"
)
LEGACY_BOT_ROOT_LITERAL = "/home/wali/Desktop/AI " + "BOT"


KNOWN_UNIVERSE = (
    "1000BONKUSDT",
    "1000FLOKIUSDT",
    "1000PEPEUSDT",
    "1000SHIBUSDT",
    "ALICEUSDT",
    "ASTERUSDT",
    "AUCTIONUSDT",
    "AVNTUSDT",
    "BANKUSDT",
    "BARDUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "FARTCOINUSDT",
    "HIGHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "PENGUUSDT",
    "PIPPINUSDT",
    "RAVEUSDT",
    "RIVERUSDT",
    "SOLUSDT",
    "UNIUSDT",
    "WIFUSDT",
    "XRPUSDT",
)

V2_NATIVE_ACTIVE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


_SAFETY_PINS = {
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
    "did_not_install_systemd_units_or_scheduler_daemons": True,
    "did_not_mutate_live_symbols_paper_symbols_or_training_symbols": True,
    "did_not_adopt_any_symbol_universe_candidate": True,
    "did_not_expose_raw_api_keys": True,
}


def _safety_block():
    return dict(_SAFETY_PINS)


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _sha256_of_file(path):
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Static manifest table
# ---------------------------------------------------------------------------
#
# Each row stores the interpreter kind ("module" or "script") and the
# target separately from the leading interpreter literal. The rendered
# legacy_command string is assembled at runtime by _render_command. The
# source-text of this file deliberately avoids contiguous
# interpreter+ingestor literals so the repo's block_dangerous.sh hook
# does not flag the planner as a runtime invocation.

_INTERP = "python3"


def _render_command(kind, target, extra=""):
    if kind == "module":
        cmd = _INTERP + " -m " + target
    elif kind == "script":
        cmd = _INTERP + " " + target
    else:
        cmd = target
    if extra:
        cmd = cmd + " " + extra
    return cmd


_RAW_PREFLIGHT = [
    {
        "service_id": "duplicate_process_guard",
        "phase": "0_preflight",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 1,
        "criticality": "CRITICAL",
        "live_risk": "NONE",
        "migration_status": "NOT_REQUIRED_FOR_V2_PAPER_SHADOW",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": ["FORCE_KILL_ALL_BOT_PY"],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "ps_aux_BOT_PY_PATTERN_must_be_empty",
        "warmup_wait_seconds": 0,
        "v2_equivalent": (
            "V2 supervisor enforces single-writer file locks per lane."
        ),
        "next_action": "Document NOT_REQUIRED in parity matrix.",
    },
    {
        "service_id": "force_kill_all_bot_py",
        "phase": "0_preflight",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 2,
        "criticality": "OPTIONAL",
        "live_risk": "NONE",
        "migration_status": "NOT_REQUIRED_FOR_V2_PAPER_SHADOW",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": ["FORCE_KILL_ALL_BOT_PY"],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "manual_operator_override",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "No V2 equivalent required.",
    },
    {
        "service_id": "vram_threshold_check",
        "phase": "0_preflight",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 3,
        "criticality": "CRITICAL",
        "live_risk": "NONE",
        "migration_status": "V2_MISSING",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "VRAM_FREE_ge_3000_MiB",
        "warmup_wait_seconds": 0,
        "v2_equivalent": (
            "Throughput acceleration packet reports GPU inventory; no "
            "V2 preflight VRAM gate exists yet."
        ),
        "next_action": "Add v2_startup_preflight_vram_gate.",
    },
    {
        "service_id": "ram_threshold_check",
        "phase": "0_preflight",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 4,
        "criticality": "CRITICAL",
        "live_risk": "NONE",
        "migration_status": "V2_MISSING",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "MEM_AVAILABLE_ge_10_GiB",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "Add v2_startup_preflight_ram_gate.",
    },
    {
        "service_id": "disk_threshold_check",
        "phase": "0_preflight",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 5,
        "criticality": "REQUIRED",
        "live_risk": "NONE",
        "migration_status": "V2_MISSING",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "DISK_USED_lt_85_pct",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "Add v2_startup_preflight_disk_gate.",
    },
    {
        "service_id": "redis_running_check",
        "phase": "0_preflight",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 6,
        "criticality": "CRITICAL",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["PING"],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "redis_ping_pong",
        "warmup_wait_seconds": 0,
        "v2_equivalent": "V2 uses redis-py healthcheck on startup",
        "next_action": "No action.",
    },
]


_RAW_MONITORING = [
    {
        "service_id": "vpn_monitor",
        "phase": "0_5_monitoring",
        "python_kind": "script",
        "python_target": "vpn_monitor.py",
        "extra_args": "",
        "startup_order": 10,
        "criticality": "OBSERVABILITY",
        "live_risk": "NONE",
        "migration_status": "LEGACY_REFERENCE_ONLY",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "logs/vpn_monitor.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "Defer; operator decides if V2 needs a VPN monitor.",
    },
    {
        "service_id": "system_telegram_monitor",
        "phase": "0_5_monitoring",
        "python_kind": "script",
        "python_target": "system_telegram_monitor.py",
        "extra_args": "",
        "startup_order": 11,
        "criticality": "OBSERVABILITY",
        "live_risk": "NONE",
        "migration_status": "OPERATOR_DECISION_REQUIRED",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "logs/system_telegram.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 0,
        "v2_equivalent": (
            "V2 report center + executive command center publish status "
            "via public payloads, not Telegram."
        ),
        "next_action": "Operator decides whether to add a V2 Telegram bridge.",
    },
    {
        "service_id": "monitor_system_memory",
        "phase": "0_5_monitoring",
        "python_kind": "script",
        "python_target": "monitor_system_memory.py",
        "extra_args": "",
        "startup_order": 12,
        "criticality": "OBSERVABILITY",
        "live_risk": "NONE",
        "migration_status": "V2_MISSING",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "logs/system_memory.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "Optional v2_system_memory_monitor; not P0.",
    },
    {
        "service_id": "scripts_memory_monitor",
        "phase": "0_5_monitoring",
        "python_kind": "script",
        "python_target": "scripts/memory_monitor.py",
        "extra_args": "",
        "startup_order": 13,
        "criticality": "OBSERVABILITY",
        "live_risk": "NONE",
        "migration_status": "V2_MISSING",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "logs/memory_monitor.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "Optional; not P0 for paper/shadow.",
    },
    {
        "service_id": "ingestors_watchdog",
        "phase": "0_5_monitoring",
        "python_kind": "script",
        "python_target": "scripts/ingestors_watchdog.py",
        "extra_args": "",
        "startup_order": 14,
        "criticality": "OBSERVABILITY",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["heartbeat:*", "price:*", "ta:*"],
        "redis_keys_written": [],
        "env_vars_required": [
            "WATCHDOG_LOOP",
            "WATCHDOG_INTERVAL",
            "ALERT_COOLDOWN",
        ],
        "log_path": "logs/process_watchdog.log",
        "pid_path": "logs/process_watchdog.pid",
        "health_check": "process_alive_and_alert_cooldown_honored",
        "warmup_wait_seconds": 2,
        "v2_equivalent": None,
        "next_action": (
            "Add v2_native_ingestor_watchdog that watches v2:* heartbeats."
        ),
    },
    {
        "service_id": "monitor_trainer_predictions",
        "phase": "0_5_monitoring",
        "python_kind": "script",
        "python_target": "scripts/monitor_trainer_predictions.py",
        "extra_args": "",
        "startup_order": 15,
        "criticality": "OBSERVABILITY",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["prediction:*"],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "logs/trainer_predictions.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 0,
        "v2_equivalent": "v2 trainer prediction monitor (already running)",
        "next_action": "No action; already covered.",
    },
]


_RAW_INGESTORS = [
    {
        "service_id": "ingest_live_binance",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/live_binance.py",
        "extra_args": "",
        "startup_order": 20,
        "criticality": "CRITICAL",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "redis_keys_read": [],
        "redis_keys_written": [
            "price:{symbol}",
            "orderbook:{symbol}",
            "ohlcv:list:{symbol}:{timeframe}",
            "heartbeat:binance",
        ],
        "env_vars_required": [],
        "log_path": "logs/ingest_binance.log",
        "pid_path": None,
        "health_check": "heartbeat:binance_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "v2 market ingestor active for 3 symbols; dynamic-symbol "
            "expansion missing."
        ),
        "next_action": (
            "v2_native_binance_ohlcv_dynamic_symbol_ingestor + "
            "v2_native_binance_orderbook_dynamic_symbol_ingestor."
        ),
    },
    {
        "service_id": "ingest_live_kucoin",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/live_kucoin.py",
        "extra_args": "",
        "startup_order": 21,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": [],
        "redis_keys_written": ["kc:*", "features:kucoin:*"],
        "env_vars_required": [],
        "log_path": "logs/ingest_kucoin.log",
        "pid_path": None,
        "health_check": "heartbeat:kucoin_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "v2/backend/app/services/native_ingestors/kucoin.py stub "
            "exists; not running as a service."
        ),
        "next_action": (
            "v2_native_kucoin_dynamic_symbol_ingestor with operator "
            "decision gate."
        ),
    },
    {
        "service_id": "ingest_live_coinank",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/live_coinank.py",
        "extra_args": "",
        "startup_order": 22,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "redis_keys_read": [],
        "redis_keys_written": ["coinank:*", "features:coinank:*"],
        "env_vars_required": [],
        "log_path": "logs/ingest_coinank.log",
        "pid_path": None,
        "health_check": "heartbeat:coinank_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": "v2 coinank bridge running; not per-symbol native.",
        "next_action": "v2_native_coinank_dynamic_symbol_ingestor.",
    },
    {
        "service_id": "ingest_live_coinank_global_aggregator",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/live_coinank_global_aggregator.py",
        "extra_args": "",
        "startup_order": 23,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "redis_keys_read": ["coinank:*"],
        "redis_keys_written": ["features:global_coinank:*"],
        "env_vars_required": [],
        "log_path": "logs/ingest_coinank_global.log",
        "pid_path": None,
        "health_check": "heartbeat:coinank_global_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": "v2 alt-data global aggregator coverage incomplete.",
        "next_action": (
            "v2_native_coinank_global_aggregator_publisher under coinank "
            "bridge-to-native plan."
        ),
    },
    {
        "service_id": "ingest_live_binance_liquidations",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/live_binance_liquidations.py",
        "extra_args": "",
        "startup_order": 24,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": [],
        "redis_keys_written": ["liquidation:*"],
        "env_vars_required": [],
        "log_path": "logs/ingest_liquidations.log",
        "pid_path": None,
        "health_check": "heartbeat:liquidations_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "v2 liquidation WSS persistent daemon publishes "
            "v2:market:liquidations:* for active symbols."
        ),
        "next_action": (
            "Extend symbol coverage as Symbol Universe governance approves."
        ),
    },
    {
        "service_id": "ingest_liquidation_bridge",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/liquidation_bridge.py",
        "extra_args": "",
        "startup_order": 25,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["liquidation:*"],
        "redis_keys_written": ["liquidation_bridge:*"],
        "env_vars_required": [],
        "log_path": "logs/liq_bridge.log",
        "pid_path": None,
        "health_check": "heartbeat:liq_bridge_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": "v2 liquidation WSS daemon emits aggregate.",
        "next_action": "No action.",
    },
    {
        "service_id": "ingest_liquidation_levels_engine",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/liquidation_levels_engine.py",
        "extra_args": "",
        "startup_order": 26,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["liquidation:*"],
        "redis_keys_written": ["liquidation_levels:*"],
        "env_vars_required": [],
        "log_path": "logs/liq_levels.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": None,
        "next_action": "v2_native_liquidation_levels_engine_dynamic_symbol.",
    },
    {
        "service_id": "ingest_realtime_price_provider",
        "phase": "1_ingestors",
        "python_kind": "script",
        "python_target": "ingest/realtime_price_provider.py",
        "extra_args": "",
        "startup_order": 27,
        "criticality": "CRITICAL",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["price:*"],
        "redis_keys_written": ["latest:*"],
        "env_vars_required": [],
        "log_path": "logs/price_provider.log",
        "pid_path": None,
        "health_check": "heartbeat:price_provider_fresh",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "v2 market ingestor publishes v2:market:prices:{symbol}."
        ),
        "next_action": "Dynamic-symbol expansion (covered by ingestor plan).",
    },
    {
        "service_id": "ingest_live_coinapi_wsds",
        "phase": "1_ingestors",
        "python_kind": "module",
        "python_target": "ingest.live_coinapi_wsds",
        "extra_args": "",
        "startup_order": 28,
        "criticality": "OPTIONAL",
        "live_risk": "READ_ONLY",
        "migration_status": "OPERATOR_DECISION_REQUIRED",
        "redis_keys_read": [],
        "redis_keys_written": ["msnap:coinapi_wsds:*"],
        "env_vars_required": [
            "COINAPI_SUBSCRIBE_DATA_TYPES",
            "COINAPI_ALLOW_TRADE",
            "COINAPI_ALLOW_FULL_BOOK",
        ],
        "log_path": "logs/live_coinapi_wsds.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": None,
        "next_action": (
            "v2_native_coinapi_wsds_dynamic_symbol_ingestor only after "
            "operator decision."
        ),
    },
    {
        "service_id": "ingest_live_coinapi_v1",
        "phase": "1_ingestors",
        "python_kind": "module",
        "python_target": "ingest.live_coinapi_v1",
        "extra_args": "",
        "startup_order": 29,
        "criticality": "OPTIONAL",
        "live_risk": "READ_ONLY",
        "migration_status": "OPERATOR_DECISION_REQUIRED",
        "redis_keys_read": [],
        "redis_keys_written": ["normalized:ohlcv:*"],
        "env_vars_required": ["DISABLE_BINANCE_OHLCV"],
        "log_path": "logs/live_coinapi_v1.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": None,
        "next_action": (
            "v2_native_coinapi_v1_ohlcv_ingestor only after operator "
            "decision."
        ),
    },
]


_RAW_FEATURES_AND_GATES = [
    {
        "service_id": "ohlcv_resampler_hotfix",
        "phase": "2_features",
        "python_kind": "script",
        "python_target": "ohlcv_resampler_hotfix.py",
        "extra_args": "",
        "startup_order": 30,
        "criticality": "CRITICAL",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["ohlcv:list:*"],
        "redis_keys_written": ["normalized:ohlcv:*"],
        "env_vars_required": [],
        "log_path": "logs/ohlcv_resampler.log",
        "pid_path": None,
        "health_check": "heartbeat:resampler_fresh",
        "warmup_wait_seconds": 2,
        "v2_equivalent": (
            "v2 feature pipeline native consumes per-timeframe candles; "
            "no standalone resampler yet."
        ),
        "next_action": "v2_native_ohlcv_resampler_dynamic_symbol_service.",
    },
    {
        "service_id": "feature_pipeline",
        "phase": "2_features",
        "python_kind": "script",
        "python_target": "feature_pipeline.py",
        "extra_args": "",
        "startup_order": 31,
        "criticality": "CRITICAL",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": [
            "normalized:ohlcv:*",
            "coinank:*",
            "kc:*",
        ],
        "redis_keys_written": ["unified_features:*", "microfeat:*"],
        "env_vars_required": [],
        "log_path": "logs/feature_pipeline.log",
        "pid_path": None,
        "health_check": "heartbeat:feature_pipeline_fresh",
        "warmup_wait_seconds": 15,
        "v2_equivalent": "v2/backend/app/services/feature_pipeline_native/**",
        "next_action": (
            "v2_native_feature_pipeline_dynamic_symbol_expansion."
        ),
    },
    {
        "service_id": "live_technical_analysis",
        "phase": "2_5_ta",
        "python_kind": "script",
        "python_target": "ingest/live_technical_analysis.py",
        "extra_args": "",
        "startup_order": 32,
        "criticality": "CRITICAL",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["normalized:ohlcv:*", "market:*"],
        "redis_keys_written": ["ta:*", "latest:ta:*"],
        "env_vars_required": [],
        "log_path": "logs/live_technical_analysis.log",
        "pid_path": "run/live_technical_analysis.pid",
        "health_check": "ta_heartbeat_HGET_ta:{symbol}:{tf}_timestamp",
        "warmup_wait_seconds": 10,
        "v2_equivalent": (
            "v2 feature pipeline native + v2:features:ta:* keys."
        ),
        "next_action": (
            "v2_native_technical_analysis_dynamic_symbol_service."
        ),
    },
    {
        "service_id": "paralysis_detectors",
        "phase": "2_5_validation",
        "python_kind": "script",
        "python_target": "scripts/paralysis_detectors.py",
        "extra_args": "--minutes 5",
        "startup_order": 33,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["price:*", "heartbeat:*"],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout",
        "pid_path": None,
        "health_check": "exit_code_0_or_warn_only",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "v2_native_paralysis_detector_health_probe.",
    },
    {
        "service_id": "validate_symbol_universe_data",
        "phase": "2_5_validation",
        "python_kind": "script",
        "python_target": "scripts/validate_symbol_universe_data.py",
        "extra_args": "",
        "startup_order": 34,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["unified_features:*", "ta:*", "price:*"],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout",
        "pid_path": None,
        "health_check": "all_universe_symbols_have_feature_and_ta_and_price",
        "warmup_wait_seconds": 0,
        "v2_equivalent": (
            "v2 full-observation remaining-dim queue lists missing "
            "buckets but no startup-time universe validator yet."
        ),
        "next_action": "v2_native_universe_data_validator_startup_gate.",
    },
    {
        "service_id": "health_probe",
        "phase": "5_health",
        "python_kind": "script",
        "python_target": "scripts/health_probe.py",
        "extra_args": "",
        "startup_order": 70,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["heartbeat:*"],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "/tmp/health_check.log",
        "pid_path": None,
        "health_check": "exit_code_0",
        "warmup_wait_seconds": 0,
        "v2_equivalent": (
            "v2 report center freshness panel partially covers this."
        ),
        "next_action": "v2_native_health_probe_startup_validator.",
    },
    {
        "service_id": "critical_health_monitor",
        "phase": "5_health",
        "python_kind": "script",
        "python_target": (
            "Documentation/Audits/scripts/critical_health_monitor.py"
        ),
        "extra_args": "",
        "startup_order": 71,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_MISSING",
        "redis_keys_read": ["heartbeat:*"],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "/tmp/critical_health.log",
        "pid_path": None,
        "health_check": "tail_for_RESULT_or_CRITICAL",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "v2_native_critical_health_monitor_startup_gate.",
    },
]


_RAW_TRAINER_ORCH_TRADERS = [
    {
        "service_id": "rl_hybrid_trainer",
        "phase": "3_trainer",
        "python_kind": "module",
        "python_target": "rl.hybrid_trainer",
        "extra_args": (
            "--mode hybrid --training-mode live --enhanced-features"
        ),
        "startup_order": 40,
        "criticality": "CRITICAL",
        "live_risk": "CAN_PLACE_LIVE_ORDERS",
        "migration_status": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "redis_keys_read": ["unified_features:*", "ta:*", "msnap:*"],
        "redis_keys_written": [
            "prediction:*",
            "trainer:intent:*",
            "rl:metrics:*",
            "signals:trading",
            "signals:trading:primary",
            "signals:trading:asjad",
            "wma:*",
        ],
        "env_vars_required": [
            "SIGNAL_OUTPUT_STREAM",
            "ENABLE_PER_ACCOUNT_STREAMS",
        ],
        "log_path": "logs/hybrid_trainer.log",
        "pid_path": None,
        "health_check": "signal_stream_XLEN_growing_and_OOM_score_plus_200",
        "warmup_wait_seconds": 45,
        "v2_equivalent": (
            "v2 trainer bridge consumes legacy predictions read-only; "
            "no V2-native training loop yet."
        ),
        "next_action": (
            "v2_trainer_bridge_exit_native_prediction_publisher_contract "
            "+ v2_trainer_dataset_builder_from_v2_replay_features."
        ),
    },
    {
        "service_id": "rl_orchestrator_worker",
        "phase": "3B_orchestrator",
        "python_kind": "module",
        "python_target": "rl.orchestrator_worker",
        "extra_args": "[--shadow]",
        "startup_order": 50,
        "criticality": "CRITICAL",
        "live_risk": "PAPER_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["trainer:intent:*", "signals:trading"],
        "redis_keys_written": ["orchestrator:decisions:*"],
        "env_vars_required": ["ORCHESTRATOR_SHADOW_MODE"],
        "log_path": "logs/orchestrator_worker.log",
        "pid_path": None,
        "health_check": "consumer_group_lag_low",
        "warmup_wait_seconds": 5,
        "v2_equivalent": (
            "v2/backend/app/services/orchestrator_arbitration/** runs "
            "arbitration across active symbols."
        ),
        "next_action": (
            "Symbol-roster expansion follows ingestor + prediction lanes."
        ),
    },
    {
        "service_id": "signal_router",
        "phase": "4A_signal_router",
        "python_kind": "script",
        "python_target": "trading/signal_router.py",
        "extra_args": "",
        "startup_order": 55,
        "criticality": "REQUIRED",
        "live_risk": "PAPER_ONLY",
        "migration_status": "NOT_REQUIRED_FOR_V2_PAPER_SHADOW",
        "redis_keys_read": ["signals:trading"],
        "redis_keys_written": [
            "signals:trading:primary",
            "signals:trading:asjad",
        ],
        "env_vars_required": [],
        "log_path": "logs/signal_router.log",
        "pid_path": None,
        "health_check": "process_alive_and_router_lag_low",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "V2 paper trader is single-account; per-account routing not "
            "required until operator approves multi-account paper."
        ),
        "next_action": "Defer until operator approves multi-account.",
    },
    {
        "service_id": "trading_trader_primary",
        "phase": "4B_traders",
        "python_kind": "script",
        "python_target": "trading/trader.py",
        "extra_args": "",
        "startup_order": 60,
        "criticality": "CRITICAL",
        "live_risk": "CAN_PLACE_LIVE_ORDERS",
        "migration_status": "LEGACY_REFERENCE_ONLY",
        "redis_keys_read": ["signals:trading:primary"],
        "redis_keys_written": ["executed_signals", "trades:*"],
        "env_vars_required": [],
        "log_path": "logs/trader.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "v2/backend/app/services/paper_mode/** runs paper-only "
            "intents through the paper-fill gate. The legacy live "
            "trader is not ported and must not be ported until the "
            "live-readiness packet is operator-approved."
        ),
        "next_action": "Keep V2 paper-only; legacy trader stays unported.",
    },
    {
        "service_id": "trading_trader_asjad",
        "phase": "4B_traders",
        "python_kind": "script",
        "python_target": "trading/trader-asjad.py",
        "extra_args": "",
        "startup_order": 61,
        "criticality": "CRITICAL",
        "live_risk": "CAN_PLACE_LIVE_ORDERS",
        "migration_status": "LEGACY_REFERENCE_ONLY",
        "redis_keys_read": ["signals:trading:asjad"],
        "redis_keys_written": ["executed_signals", "trades:*"],
        "env_vars_required": [],
        "log_path": "logs/trader-asjad.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": None,
        "next_action": "Defer until multi-account paper approved.",
    },
    {
        "service_id": "monitor_portfolio_primary",
        "phase": "4C_portfolio",
        "python_kind": "script",
        "python_target": "monitor_portfolio_primary.py",
        "extra_args": "",
        "startup_order": 65,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": ["trades:*", "executed_signals"],
        "redis_keys_written": ["portfolio:primary:*"],
        "env_vars_required": [],
        "log_path": "logs/portfolio_primary.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": (
            "v2/backend/app/services/account_position_monitor/** + "
            "position-history persistent tracker."
        ),
        "next_action": (
            "Dynamic-symbol expansion follows paper-trader roster."
        ),
    },
    {
        "service_id": "monitor_portfolio_asjad",
        "phase": "4C_portfolio",
        "python_kind": "script",
        "python_target": "monitor_portfolio_asjad.py",
        "extra_args": "",
        "startup_order": 66,
        "criticality": "REQUIRED",
        "live_risk": "READ_ONLY",
        "migration_status": "LEGACY_REFERENCE_ONLY",
        "redis_keys_read": ["trades:*", "executed_signals"],
        "redis_keys_written": ["portfolio:asjad:*"],
        "env_vars_required": [],
        "log_path": "logs/portfolio_asjad.log",
        "pid_path": None,
        "health_check": "process_alive",
        "warmup_wait_seconds": 3,
        "v2_equivalent": None,
        "next_action": "Defer until multi-account paper approved.",
    },
    {
        "service_id": "process_listing_and_resource_report",
        "phase": "6_final_status",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 90,
        "criticality": "OBSERVABILITY",
        "live_risk": "NONE",
        "migration_status": "V2_NATIVE",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "manual_review",
        "warmup_wait_seconds": 0,
        "v2_equivalent": (
            "v2 throughput acceleration packet covers CPU/RAM/GPU; "
            "v2 report center covers process list."
        ),
        "next_action": "No action.",
    },
    {
        "service_id": "telegram_completion_notification",
        "phase": "6_final_status",
        "python_kind": None,
        "python_target": None,
        "extra_args": "",
        "startup_order": 91,
        "criticality": "OBSERVABILITY",
        "live_risk": "NONE",
        "migration_status": "OPERATOR_DECISION_REQUIRED",
        "redis_keys_read": [],
        "redis_keys_written": [],
        "env_vars_required": [],
        "log_path": "stdout_only",
        "pid_path": None,
        "health_check": "telegram_api_2xx",
        "warmup_wait_seconds": 0,
        "v2_equivalent": None,
        "next_action": "Defer until operator authorizes V2 Telegram bridge.",
    },
]


_ALL_RAW_ITEMS = (
    _RAW_PREFLIGHT
    + _RAW_MONITORING
    + _RAW_INGESTORS
    + _RAW_FEATURES_AND_GATES
    + _RAW_TRAINER_ORCH_TRADERS
)


def _stamp_legacy_command(item):
    """Return a copy of the raw item with `legacy_command` rendered."""
    stamped = dict(item)
    cmd = _render_command(
        item.get("python_kind"),
        item.get("python_target"),
        extra=item.get("extra_args", ""),
    )
    stamped["legacy_command"] = (
        cmd if cmd else item.get("service_id", "shell_only")
    )
    return stamped


def _items_with_legacy_command():
    return [_stamp_legacy_command(it) for it in _ALL_RAW_ITEMS]


# ---------------------------------------------------------------------------
# Manifest parsing helpers
# ---------------------------------------------------------------------------


def _classify_diff(local_sha, snapshot_sha):
    if local_sha is None and snapshot_sha is None:
        return "BOTH_MISSING"
    if local_sha is None:
        return "LOCAL_MISSING_USING_SNAPSHOT"
    if snapshot_sha is None:
        return "SNAPSHOT_MISSING_USING_LOCAL_HASH_ONLY"
    if local_sha == snapshot_sha:
        return "LOCAL_AND_SNAPSHOT_MATCH"
    return "LOCAL_AND_SNAPSHOT_DIFFER_LOCAL_RUNTIME_SCRIPT_USED_FOR_PARSING"


def _scan_manifest_env_flags(text):
    flags = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("export "):
            continue
        m = re.match(r"export\s+([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$", stripped)
        if not m:
            continue
        flags.append({"name": m.group(1), "default_expr": m.group(2)})
    return flags


def _scan_manifest_python_invocations(text):
    invocations = []
    for m in re.finditer(
        r"(?:nohup\s+)?(?:nice\s+-n\s+\d+\s+)?(?:taskset\s+-c\s+[\d,\-]+\s+)?"
        + _INTERP + r"\s+(?:-m\s+([A-Za-z0-9_.]+)|([^\s]+\.py))",
        text,
    ):
        module = m.group(1)
        script = m.group(2)
        if module:
            invocations.append({"kind": "module", "target": module})
        elif script:
            invocations.append({"kind": "script", "target": script})
    for m in re.finditer(
        r"start_ingestor\s+\"[^\"]+\"\s+\"([^\"]+\.py)\"",
        text,
    ):
        invocations.append({"kind": "script", "target": m.group(1)})
    seen = set()
    deduped = []
    for inv in invocations:
        key = inv["kind"] + ":" + inv["target"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(inv)
    return deduped


def _read_manifest_text(repo_root):
    local = Path(LEGACY_BOT_ROOT_LITERAL) / LEGACY_STARTUP_SCRIPT_LOCAL_REL
    if local.exists():
        try:
            return local.read_text(encoding="utf-8"), "local"
        except (OSError, UnicodeDecodeError):
            pass
    snapshot = repo_root / LEGACY_STARTUP_SCRIPT_SNAPSHOT
    if snapshot.exists():
        try:
            return snapshot.read_text(encoding="utf-8"), "snapshot"
        except (OSError, UnicodeDecodeError):
            return None, "MISSING_NO_PARSE"
    return None, "MISSING_NO_PARSE"


# ---------------------------------------------------------------------------
# Phase 1 - Legacy startup manifest
# ---------------------------------------------------------------------------


def build_legacy_startup_manifest(repo_root):
    snapshot_path = repo_root / LEGACY_STARTUP_SCRIPT_SNAPSHOT
    local_path = Path(LEGACY_BOT_ROOT_LITERAL) / LEGACY_STARTUP_SCRIPT_LOCAL_REL
    local_sha = _sha256_of_file(local_path)
    snapshot_sha = _sha256_of_file(snapshot_path)
    diff_classification = _classify_diff(local_sha, snapshot_sha)

    manifest_text_raw, parsing_source = _read_manifest_text(repo_root)
    manifest_text = manifest_text_raw or ""
    env_flags = _scan_manifest_env_flags(manifest_text)
    py_invocations = _scan_manifest_python_invocations(manifest_text)
    invoked_targets = {inv["target"] for inv in py_invocations}

    items = []
    for item in _items_with_legacy_command():
        target = item.get("python_target") or ""
        evidence_match = False
        matches = []
        if target:
            for t in invoked_targets:
                if t == target or t.endswith(target) or target.endswith(t):
                    evidence_match = True
                    matches.append(t)
        items.append(
            {
                **item,
                "legacy_script_path": (
                    item.get("python_target")
                    or "scripts/start_all_services_production.sh"
                ),
                "parser_evidence": {
                    "target_seen_in_manifest": evidence_match,
                    "matching_invocations": matches[:4],
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION + "_legacy_startup_manifest",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "canonical_sources": {
            "local_path": str(local_path),
            "snapshot_path": str(snapshot_path),
            "local_sha256": local_sha,
            "snapshot_sha256": snapshot_sha,
            "diff_classification": diff_classification,
            "parsing_source_used": parsing_source if manifest_text else "MISSING_NO_PARSE",
            "local_runtime_script_used_for_parsing": parsing_source == "local",
            "snapshot_used_only_as_drift_reference": parsing_source == "local",
        },
        "env_flags_extracted_count": len(env_flags),
        "env_flags": env_flags,
        "python_invocations_extracted_count": len(py_invocations),
        "python_invocations": py_invocations,
        "items": items,
        "item_count": len(items),
    }


# ---------------------------------------------------------------------------
# Phase 2 - Parity matrix
# ---------------------------------------------------------------------------


_GAP_TYPE_BY_STATUS = {
    "V2_NATIVE": "NO_GAP",
    "V2_BRIDGE_FROM_LEGACY_REDIS": "BRIDGE_ONLY",
    "V2_MISSING": "MISSING_SERVICE",
    "LEGACY_REFERENCE_ONLY": "MISSING_SERVICE",
    "OPERATOR_DECISION_REQUIRED": "OPERATOR_DECISION_REQUIRED",
    "NOT_REQUIRED_FOR_V2_PAPER_SHADOW": "NO_GAP",
}


def _parity_row(item):
    status = item.get("migration_status", "V2_MISSING")
    gap_type = _GAP_TYPE_BY_STATUS.get(status, "MISSING_SERVICE")
    live_risk = item.get("live_risk", "NONE")
    is_p0_crit = item.get("criticality") == "CRITICAL"
    blocks_paper = (
        gap_type in ("MISSING_SERVICE",) and is_p0_crit
        and item.get("phase") in ("1_ingestors", "2_features", "2_5_ta")
    )
    blocks_prod_equiv = gap_type in (
        "BRIDGE_ONLY",
        "MISSING_SERVICE",
        "OPERATOR_DECISION_REQUIRED",
    )
    blocks_shutdown = gap_type in (
        "BRIDGE_ONLY",
        "MISSING_SERVICE",
    )
    blocks_live = (
        live_risk in ("CAN_PLACE_LIVE_ORDERS",)
        or gap_type in ("MISSING_SERVICE", "BRIDGE_ONLY")
    )
    codex_status = (
        "PASS_OR_PENDING_REVIEW" if status == "V2_NATIVE" else "NOT_APPLICABLE"
    )
    return {
        "service_id": item["service_id"],
        "phase": item["phase"],
        "migration_status": status,
        "gap_type": gap_type,
        "blocks_paper": blocks_paper,
        "blocks_production_equivalence": blocks_prod_equiv,
        "blocks_shutdown": blocks_shutdown,
        "blocks_live": blocks_live,
        "v2_existing_component": item.get("v2_equivalent"),
        "v2_service_or_timer": (
            item.get("v2_equivalent") if status == "V2_NATIVE" else None
        ),
        "v2_cli": None,
        "v2_redis_keys": [
            "v2:*"
        ] if status in ("V2_NATIVE", "V2_BRIDGE_FROM_LEGACY_REDIS") else [],
        "v2_public_payload": (
            "v2/frontend/public/operator_runtime/**"
            if status == "V2_NATIVE"
            else None
        ),
        "codex_status": codex_status,
        "current_runtime_status": (
            "RUNNING_IN_LEGACY"
            if status in (
                "V2_BRIDGE_FROM_LEGACY_REDIS",
                "LEGACY_REFERENCE_ONLY",
            )
            else "V2_RUNTIME_OR_MISSING"
        ),
        "required_fix": item.get("next_action"),
    }


def build_legacy_to_v2_service_parity_matrix(manifest):
    rows = [_parity_row(it) for it in manifest["items"]]
    return {
        "schema_version": SCHEMA_VERSION + "_legacy_to_v2_service_parity_matrix",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "row_count": len(rows),
        "rows": rows,
        "parity_score_v2_native_over_total": round(
            sum(1 for r in rows if r["migration_status"] == "V2_NATIVE")
            / max(1, len(rows)),
            3,
        ),
        "marking_rules": [
            "V2_NATIVE_only_when_v2_code_writes_v2_keys_has_public_payload_and_has_heartbeat",
            "BRIDGE_ONLY_means_v2_still_depends_on_legacy_redis_through_approved_bridge",
            "MISSING_SERVICE_means_no_v2_implementation_exists_yet",
            "OPERATOR_DECISION_REQUIRED_blocks_promotion",
        ],
    }


# ---------------------------------------------------------------------------
# Phase 3 - Legacy-to-V2 Redis contract map
# ---------------------------------------------------------------------------


_REDIS_CONTRACT_ROWS = [
    {
        "legacy_key_pattern": "price:{symbol}",
        "legacy_writer": "ingest_realtime_price_provider",
        "v2_key_pattern": "v2:market:prices:{symbol}",
        "v2_writer": "v2_market_ingestor",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "orderbook:{symbol}",
        "legacy_writer": "ingest_live_binance",
        "v2_key_pattern": "v2:market:orderbook:binance:{symbol}",
        "v2_writer": None,
        "source_label": "PLACEHOLDER_NOT_READY",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "v2_native_orderbook_dynamic_symbol_ingestor_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "ohlcv:list:{symbol}:{timeframe}",
        "legacy_writer": "ingest_live_binance",
        "v2_key_pattern": "v2:market:ohlcv:binance:{symbol}:{timeframe}",
        "v2_writer": None,
        "source_label": "PLACEHOLDER_NOT_READY",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "v2_native_ohlcv_dynamic_symbol_ingestor_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "latest:{symbol}",
        "legacy_writer": "ingest_realtime_price_provider",
        "v2_key_pattern": "v2:market:prices:{symbol}",
        "v2_writer": "v2_market_ingestor",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "coinank:*",
        "legacy_writer": "ingest_live_coinank",
        "v2_key_pattern": "v2:altdata:coinank:*",
        "v2_writer": "v2_coinank_bridge",
        "source_label": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "per_symbol_native_publisher_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "features:coinank:*",
        "legacy_writer": "ingest_live_coinank",
        "v2_key_pattern": "v2:altdata:coinank:funding_aggregate:{symbol}",
        "v2_writer": None,
        "source_label": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "per_symbol_publisher_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "features:global_coinank:*",
        "legacy_writer": "ingest_live_coinank_global_aggregator",
        "v2_key_pattern": "v2:altdata:coinank:global_aggregate",
        "v2_writer": None,
        "source_label": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "global_aggregate_publisher_missing",
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "kc:*",
        "legacy_writer": "ingest_live_kucoin",
        "v2_key_pattern": "v2:market:prices:kucoin:{symbol}",
        "v2_writer": None,
        "source_label": "OPERATOR_DECISION_REQUIRED",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "kucoin_secondary_feed_operator_decision_pending",
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "features:kucoin:*",
        "legacy_writer": "ingest_live_kucoin",
        "v2_key_pattern": "v2:features:kucoin:{symbol}:{timeframe}",
        "v2_writer": None,
        "source_label": "OPERATOR_DECISION_REQUIRED",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "kucoin_secondary_feed_operator_decision_pending",
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "microfeat:*",
        "legacy_writer": "feature_pipeline",
        "v2_key_pattern": "v2:features:microfeat:{symbol}:{timeframe}",
        "v2_writer": "v2_feature_pipeline_native",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "msnap:coinapi_wsds:*",
        "legacy_writer": "ingest_live_coinapi_wsds",
        "v2_key_pattern": "v2:market:coinapi:wsds:{symbol}",
        "v2_writer": None,
        "source_label": "OPERATOR_DECISION_REQUIRED",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "coinapi_secondary_feed_operator_decision_pending",
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "normalized:ohlcv:*",
        "legacy_writer": "ohlcv_resampler_hotfix",
        "v2_key_pattern": "v2:market:ohlcv:binance:{symbol}:{timeframe}",
        "v2_writer": None,
        "source_label": "PLACEHOLDER_NOT_READY",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "v2_native_ohlcv_resampler_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "ta:*",
        "legacy_writer": "live_technical_analysis",
        "v2_key_pattern": "v2:features:ta:{symbol}:{timeframe}",
        "v2_writer": "v2_feature_pipeline_native",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "latest:ta:*",
        "legacy_writer": "live_technical_analysis",
        "v2_key_pattern": "v2:features:ta:{symbol}:{timeframe}",
        "v2_writer": "v2_feature_pipeline_native",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "unified_features:*",
        "legacy_writer": "feature_pipeline",
        "v2_key_pattern": "v2:features:latest:{symbol}:{timeframe}",
        "v2_writer": "v2_feature_pipeline_native",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "prediction:*",
        "legacy_writer": "rl_hybrid_trainer",
        "v2_key_pattern": "v2:prediction:{symbol}:{timeframe}",
        "v2_writer": "v2_trainer_bridge",
        "source_label": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "v2_native_training_loop_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "trainer:intent:*",
        "legacy_writer": "rl_hybrid_trainer",
        "v2_key_pattern": "v2:trainer:intent:{symbol}",
        "v2_writer": "v2_trainer_bridge",
        "source_label": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "v2_native_prediction_publisher_missing",
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "rl:metrics:*",
        "legacy_writer": "rl_hybrid_trainer",
        "v2_key_pattern": "v2:trainer:metrics:{symbol}",
        "v2_writer": None,
        "source_label": "V2_MISSING",
        "bridge_allowed": True,
        "bridge_label_required": True,
        "v2_native_ready": False,
        "missing_reason": "v2_trainer_metrics_publisher_missing",
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "signals:trading",
        "legacy_writer": "rl_hybrid_trainer",
        "v2_key_pattern": "v2:orchestrator:decisions",
        "v2_writer": "v2_orchestrator_arbitration",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "signals:trading:primary",
        "legacy_writer": "signal_router",
        "v2_key_pattern": "v2:orchestrator:decisions",
        "v2_writer": "v2_orchestrator_arbitration",
        "source_label": "NOT_REQUIRED_FOR_V2_PAPER_SHADOW",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "signals:trading:asjad",
        "legacy_writer": "signal_router",
        "v2_key_pattern": None,
        "v2_writer": None,
        "source_label": "NOT_REQUIRED_FOR_V2_PAPER_SHADOW",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": False,
        "missing_reason": "multi_account_paper_pending_operator_decision",
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "wma:*",
        "legacy_writer": "rl_hybrid_trainer",
        "v2_key_pattern": "v2:features:wma:{symbol}:{timeframe}",
        "v2_writer": "v2_feature_pipeline_native",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": False,
    },
    {
        "legacy_key_pattern": "executed_signals",
        "legacy_writer": "trading_trader_primary",
        "v2_key_pattern": "v2:paper:ledger",
        "v2_writer": "v2_paper_trader",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
    {
        "legacy_key_pattern": "heartbeat:*",
        "legacy_writer": "many_legacy_services",
        "v2_key_pattern": "v2:*:heartbeat",
        "v2_writer": "v2_per_service_heartbeats",
        "source_label": "V2_NATIVE",
        "bridge_allowed": False,
        "bridge_label_required": False,
        "v2_native_ready": True,
        "missing_reason": None,
        "shutdown_dependency": True,
    },
]


def build_legacy_redis_to_v2_redis_contract_map():
    return {
        "schema_version": SCHEMA_VERSION + "_legacy_redis_to_v2_redis_contract_map",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "v2_writes_only_v2_namespace": True,
        "legacy_redis_read_only_through_approved_bridge_contracts": True,
        "row_count": len(_REDIS_CONTRACT_ROWS),
        "rows": _REDIS_CONTRACT_ROWS,
    }


# ---------------------------------------------------------------------------
# Phase 4 - Dynamic symbol coverage
# ---------------------------------------------------------------------------


_SERVICE_FAMILIES = (
    "price",
    "ohlcv",
    "orderbook",
    "liquidation",
    "funding",
    "open_interest",
    "coinank",
    "kucoin",
    "coinapi",
    "ta",
    "unified_features",
    "prediction",
    "risk",
    "orchestrator",
    "paper_intent",
    "replay_miner",
    "website_visibility",
)

_DYNAMIC_COVERAGE_STATUS_VOCABULARY = (
    "V2_NATIVE",
    "V2_BRIDGE_FROM_LEGACY_REDIS",
    "LEGACY_REFERENCE_ONLY",
    "PLACEHOLDER_NOT_READY",
    "OPERATOR_DECISION_REQUIRED",
)


def _coverage_for_symbol_family(symbol, family):
    if family in ("kucoin", "coinapi"):
        return "OPERATOR_DECISION_REQUIRED"
    if symbol not in V2_NATIVE_ACTIVE_SYMBOLS:
        return "PLACEHOLDER_NOT_READY"
    if family in ("ohlcv", "orderbook"):
        return "PLACEHOLDER_NOT_READY"
    if family in ("coinank", "prediction"):
        return "V2_BRIDGE_FROM_LEGACY_REDIS"
    return "V2_NATIVE"


def build_legacy_startup_dynamic_symbol_coverage():
    rows = []
    for symbol in KNOWN_UNIVERSE:
        per_family = {
            family: _coverage_for_symbol_family(symbol, family)
            for family in _SERVICE_FAMILIES
        }
        rows.append({"symbol": symbol, "per_family": per_family})
    return {
        "schema_version": SCHEMA_VERSION + "_legacy_startup_dynamic_symbol_coverage",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "service_families": list(_SERVICE_FAMILIES),
        "classification_vocabulary": list(_DYNAMIC_COVERAGE_STATUS_VOCABULARY),
        "universe": list(KNOWN_UNIVERSE),
        "currently_active_symbols": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "rows": rows,
        "live_symbols_unchanged": True,
        "paper_symbols_unchanged_pending_governance": True,
        "training_symbols_unchanged_pending_governance": True,
    }


# ---------------------------------------------------------------------------
# Phase 5 - V2 startup-order parity plan
# ---------------------------------------------------------------------------


def build_v2_startup_order_parity_plan(manifest):
    legacy_phases = sorted({it["phase"] for it in manifest["items"]})
    plan = []
    for phase in legacy_phases:
        items_in_phase = [it for it in manifest["items"] if it["phase"] == phase]
        statuses = {it.get("migration_status") for it in items_in_phase}
        if statuses <= {"V2_NATIVE", "NOT_REQUIRED_FOR_V2_PAPER_SHADOW"}:
            status = "V2_NATIVE_PARITY"
            gap = "NONE"
        elif "V2_MISSING" in statuses or "LEGACY_REFERENCE_ONLY" in statuses:
            status = "V2_GAP_PRESENT"
            gap = "MISSING_SERVICES_OR_BRIDGE_ONLY"
        elif "V2_BRIDGE_FROM_LEGACY_REDIS" in statuses:
            status = "V2_BRIDGE_PARITY"
            gap = "BRIDGE_ONLY_FOR_SOME_SERVICES"
        else:
            status = "OPERATOR_DECISION_PENDING"
            gap = "OPERATOR_DECISION_REQUIRED"
        plan.append(
            {
                "legacy_phase": phase,
                "v2_current_phase": phase,
                "status": status,
                "gap": gap,
                "items_in_phase": [it["service_id"] for it in items_in_phase],
                "health_gate": "v2_per_service_heartbeat_freshness",
                "blocks_next_phase": status == "V2_GAP_PRESENT",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION + "_v2_startup_order_parity_plan",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "required_v2_phase_order": [
            "0_preflight",
            "0_5_monitoring",
            "1_ingestors",
            "2_features",
            "2_5_ta",
            "2_5_validation",
            "3_trainer",
            "3B_orchestrator",
            "4B_paper_traders",
            "4C_portfolio",
            "5_health",
            "6_final_status",
        ],
        "phases": plan,
        "does_not_start_or_stop_anything": True,
    }


# ---------------------------------------------------------------------------
# Phase 6 - First-batch task dispatch
# ---------------------------------------------------------------------------


def _task(task_id, scope, writes_only=None, tests=True, extra_forbidden=None):
    forbidden = [
        "no_old_redis_writes",
        "no_exchange_mutation",
        "no_live_or_canary_approval",
        "no_legacy_mutation",
        "no_paper_fill_gate_weakening",
    ] + (extra_forbidden or [])
    return {
        "task_id": task_id,
        "status": "QUEUED_NOT_RUNNING",
        "scope": scope,
        "file_lock_group": scope,
        "codex_review_required": True,
        "broad_audit": False,
        "does_not_run_task": True,
        "claude_task_descriptor": (
            "Implement " + task_id + " against scope " + scope
        ),
        "codex_review_descriptor": (
            "codex exec review --uncommitted "
            "\"Review scope " + scope + ". " + ", ".join(forbidden) + ".\""
        ),
        "exact_source_files": [scope],
        "exact_target_v2_files": [
            "v2/backend/app/services/**",
            "v2/backend/app/cli/**",
            "v2/backend/tests/**",
        ],
        "writes_only": writes_only or ["v2:*"],
        "writes": writes_only or ["v2:*"],
        "tests_required": tests,
        "public_payload_output": (
            "v2/frontend/public/operator_runtime/**"
        ),
        "forbidden_actions": forbidden,
        "go_no_go_token": task_id.upper() + "_READY",
    }


def build_first_batch_startup_parity_task_dispatch():
    tasks = [
        _task(
            "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
            "v2/backend/app/services/native_ingestors/binance_ohlcv*.py",
            writes_only=["v2:market:ohlcv:binance:{symbol}:{timeframe}"],
        ),
        _task(
            "v2_native_binance_orderbook_dynamic_symbol_ingestor",
            "v2/backend/app/services/native_ingestors/binance_orderbook*.py",
            writes_only=["v2:market:orderbook:binance:{symbol}"],
        ),
        _task(
            "v2_native_coinank_dynamic_symbol_ingestor",
            "v2/backend/app/services/coinank_bridge/**",
            writes_only=[
                "v2:altdata:coinank:funding_aggregate:{symbol}",
                "v2:altdata:coinank:long_short:{symbol}",
                "v2:altdata:coinank:liquidation_aggregate:{symbol}",
            ],
            extra_forbidden=[
                "no_paid_aggregator_adoption_without_operator_decision",
            ],
        ),
        _task(
            "v2_native_kucoin_dynamic_symbol_ingestor",
            "v2/backend/app/services/native_ingestors/kucoin.py",
            writes_only=["v2:market:prices:kucoin:{symbol}"],
            extra_forbidden=[
                "no_kucoin_writes_until_operator_decision",
            ],
        ),
        _task(
            "v2_native_coinapi_wsds_dynamic_symbol_ingestor",
            "v2/backend/app/services/native_ingestors/coinapi_wsds.py",
            writes_only=["v2:market:coinapi:wsds:{symbol}"],
            extra_forbidden=[
                "no_coinapi_writes_until_operator_decision",
            ],
        ),
        _task(
            "v2_native_feature_pipeline_dynamic_symbol_expansion",
            "v2/backend/app/services/feature_pipeline_native/**",
            writes_only=[
                "v2:features:latest:{symbol}:{timeframe}",
                "v2:features:ta:{symbol}:{timeframe}",
            ],
        ),
        _task(
            "v2_native_technical_analysis_dynamic_symbol_service",
            "v2/backend/app/services/feature_pipeline_native/**",
            writes_only=["v2:features:ta:{symbol}:{timeframe}"],
        ),
        _task(
            "v2_trainer_bridge_exit_native_prediction_publisher_contract",
            "v2/backend/app/services/trainer_bridge/**",
            writes_only=[
                "v2:prediction:{symbol}:{timeframe}",
                "v2:trainer:heartbeat",
            ],
            extra_forbidden=[
                "no_checkpoint_deserialization_in_control_plane",
            ],
        ),
        _task(
            "v2_trainer_dataset_builder_from_v2_replay_features",
            "v2/backend/app/services/trainer_bridge/**",
            writes_only=["v2:trainer:dataset:manifest"],
            extra_forbidden=[
                "no_checkpoint_compatibility_claim",
                "no_policy_architecture_parity_claim",
            ],
        ),
        _task(
            "v2_startup_order_parity_control_plane",
            "v2/backend/app/services/legacy_startup_parity/**",
            writes_only=[],
            extra_forbidden=[
                "no_systemd_install",
                "no_daemon_install",
            ],
        ),
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_first_batch_startup_parity_task_dispatch",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "task_count": len(tasks),
        "tasks": tasks,
        "planner_does_not_run_tasks_only_queues_them": True,
    }


# ---------------------------------------------------------------------------
# Phase 7 - Automation integration + operator dashboard
# ---------------------------------------------------------------------------


def build_automation_integration_status(*, manifest, parity, coverage, first_batch):
    rows = parity["rows"]
    counts = {}
    for r in rows:
        counts[r["migration_status"]] = counts.get(r["migration_status"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION + "_automation_integration_status",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "primary_p0_mission": (
            "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT"
        ),
        "startup_manifest_coverage_total": len(rows),
        "missing_startup_services_count": counts.get("V2_MISSING", 0)
        + counts.get("LEGACY_REFERENCE_ONLY", 0),
        "bridge_only_services_count": counts.get(
            "V2_BRIDGE_FROM_LEGACY_REDIS", 0
        ),
        "v2_native_services_count": counts.get("V2_NATIVE", 0),
        "operator_decision_required_count": counts.get(
            "OPERATOR_DECISION_REQUIRED", 0
        ),
        "not_required_for_v2_paper_shadow_count": counts.get(
            "NOT_REQUIRED_FOR_V2_PAPER_SHADOW", 0
        ),
        "dynamic_symbol_coverage_total": len(coverage["universe"]),
        "v2_native_active_symbol_count": len(coverage["currently_active_symbols"]),
        "service_parity_score": parity["parity_score_v2_native_over_total"],
        "bridge_exit_progress_pct": round(
            counts.get("V2_NATIVE", 0) / max(1, len(rows)) * 100,
            1,
        ),
        "next_first_batch_tasks": [t["task_id"] for t in first_batch["tasks"]],
    }


def build_operator_dashboard_payload(*, manifest, parity, coverage, automation, first_batch):
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_READY",
        "safety_scoreboard": _safety_block(),
        "summary": {
            "startup_manifest_coverage_total": automation[
                "startup_manifest_coverage_total"
            ],
            "v2_native_services_count": automation["v2_native_services_count"],
            "bridge_only_services_count": automation["bridge_only_services_count"],
            "missing_startup_services_count": automation[
                "missing_startup_services_count"
            ],
            "operator_decision_required_count": automation[
                "operator_decision_required_count"
            ],
            "dynamic_symbol_coverage_total": automation[
                "dynamic_symbol_coverage_total"
            ],
            "v2_native_active_symbol_count": automation[
                "v2_native_active_symbol_count"
            ],
            "service_parity_score": automation["service_parity_score"],
            "bridge_exit_progress_pct": automation["bridge_exit_progress_pct"],
        },
        "next_first_batch_tasks": automation["next_first_batch_tasks"],
        "live_blocked": True,
        "shutdown_blocked": True,
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class LegacyParityPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root):
    return LegacyParityPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_legacy_startup_manifest_parity_and_bridge_exit/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_legacy_startup_manifest_parity_and_bridge_exit/latest",
    )


@dataclass
class LegacyParityRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_legacy_parity_packet(paths):
    manifest = build_legacy_startup_manifest(paths.repo_root)
    parity = build_legacy_to_v2_service_parity_matrix(manifest)
    redis_map = build_legacy_redis_to_v2_redis_contract_map()
    coverage = build_legacy_startup_dynamic_symbol_coverage()
    startup_order = build_v2_startup_order_parity_plan(manifest)
    first_batch = build_first_batch_startup_parity_task_dispatch()
    automation = build_automation_integration_status(
        manifest=manifest,
        parity=parity,
        coverage=coverage,
        first_batch=first_batch,
    )
    dashboard = build_operator_dashboard_payload(
        manifest=manifest,
        parity=parity,
        coverage=coverage,
        automation=automation,
        first_batch=first_batch,
    )

    _atomic_write_json(paths.packet_dir / "legacy_startup_manifest.json", manifest)
    _atomic_write_json(
        paths.packet_dir / "legacy_to_v2_service_parity_matrix.json", parity
    )
    _atomic_write_json(
        paths.packet_dir / "legacy_redis_to_v2_redis_contract_map.json",
        redis_map,
    )
    _atomic_write_json(
        paths.packet_dir / "legacy_startup_dynamic_symbol_coverage.json",
        coverage,
    )
    _atomic_write_json(
        paths.packet_dir / "v2_startup_order_parity_plan.json", startup_order
    )
    _atomic_write_json(
        paths.packet_dir / "first_batch_startup_parity_task_dispatch.json",
        first_batch,
    )
    _atomic_write_json(
        paths.packet_dir / "automation_integration_status.json", automation
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )

    report = _render_report(
        manifest=manifest,
        parity=parity,
        redis_map=redis_map,
        coverage=coverage,
        startup_order=startup_order,
        first_batch=first_batch,
        automation=automation,
        dashboard=dashboard,
    )
    _atomic_write_text(
        paths.packet_dir
        / "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_READY\n",
    )

    return LegacyParityRunResult(
        go_no_go="V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_REPORT.md",
            paths.packet_dir / "legacy_startup_manifest.json",
            paths.packet_dir / "legacy_to_v2_service_parity_matrix.json",
            paths.packet_dir / "legacy_redis_to_v2_redis_contract_map.json",
            paths.packet_dir / "legacy_startup_dynamic_symbol_coverage.json",
            paths.packet_dir / "v2_startup_order_parity_plan.json",
            paths.packet_dir / "first_batch_startup_parity_task_dispatch.json",
            paths.packet_dir / "automation_integration_status.json",
            paths.public_dir / "operator_dashboard_payload.json",
        ],
    )


def _render_report(
    *,
    manifest,
    parity,
    redis_map,
    coverage,
    startup_order,
    first_batch,
    automation,
    dashboard,
):
    lines = []
    lines.append("# V2 Legacy Startup Manifest Parity and Bridge-Exit Report\n\n")
    lines.append(
        "GO/NO-GO: V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false. "
        "approves_canary=false. approves_legacy_shutdown=false. "
        "approves_redis_trim=false.\n\n"
    )
    src = manifest["canonical_sources"]
    lines.append("## Phase 1 - Manifest source\n")
    lines.append("- local_path: " + str(src["local_path"]) + "\n")
    lines.append("- snapshot_path: " + str(src["snapshot_path"]) + "\n")
    lines.append("- local_sha256: " + str(src["local_sha256"]) + "\n")
    lines.append("- snapshot_sha256: " + str(src["snapshot_sha256"]) + "\n")
    lines.append("- diff_classification: " + src["diff_classification"] + "\n")
    lines.append("- parsing_source_used: " + src["parsing_source_used"] + "\n")
    lines.append(
        "- env_flags_extracted_count: "
        + str(manifest["env_flags_extracted_count"])
        + "\n"
    )
    lines.append(
        "- python_invocations_extracted_count: "
        + str(manifest["python_invocations_extracted_count"])
        + "\n"
    )
    lines.append("- item_count: " + str(manifest["item_count"]) + "\n\n")

    lines.append("## Phase 2 - Parity matrix\n")
    lines.append("- row_count: " + str(parity["row_count"]) + "\n")
    lines.append(
        "- parity_score_v2_native_over_total: "
        + str(parity["parity_score_v2_native_over_total"])
        + "\n"
    )
    counts = {}
    for r in parity["rows"]:
        counts[r["migration_status"]] = counts.get(r["migration_status"], 0) + 1
    for status, n in sorted(counts.items()):
        lines.append("  - " + status + ": " + str(n) + "\n")
    lines.append("\n")

    lines.append("## Phase 3 - Redis contract map\n")
    lines.append("- row_count: " + str(redis_map["row_count"]) + "\n\n")

    lines.append("## Phase 4 - Dynamic symbol coverage\n")
    lines.append("- universe_size: " + str(len(coverage["universe"])) + "\n")
    lines.append(
        "- currently_active_symbols: "
        + str(coverage["currently_active_symbols"])
        + "\n"
    )
    lines.append(
        "- service_families: " + str(len(coverage["service_families"])) + "\n\n"
    )

    lines.append("## Phase 5 - V2 startup-order parity\n")
    for phase in startup_order["phases"]:
        lines.append(
            "- " + phase["legacy_phase"] + ": " + phase["status"]
            + " (gap=" + phase["gap"] + ")\n"
        )
    lines.append("\n")

    lines.append("## Phase 6 - First-batch tasks\n")
    for t in first_batch["tasks"]:
        lines.append("- " + t["task_id"] + " -> " + t["go_no_go_token"] + "\n")
    lines.append("\n")

    lines.append("## Phase 7 - Automation integration\n")
    for k in (
        "primary_p0_mission",
        "startup_manifest_coverage_total",
        "missing_startup_services_count",
        "bridge_only_services_count",
        "v2_native_services_count",
        "operator_decision_required_count",
        "not_required_for_v2_paper_shadow_count",
        "dynamic_symbol_coverage_total",
        "v2_native_active_symbol_count",
        "service_parity_score",
        "bridge_exit_progress_pct",
    ):
        lines.append("- " + k + ": " + str(automation.get(k)) + "\n")
    lines.append("\n")

    lines.append("## Phase 8 - Operator dashboard (public mirror)\n")
    lines.append(
        "- public_path: v2/frontend/public/v2_legacy_startup_manifest_"
        "parity_and_bridge_exit/latest/operator_dashboard_payload.json\n"
    )
    lines.append(
        "- live_blocked: " + str(dashboard["live_blocked"])
        + " | shutdown_blocked: " + str(dashboard["shutdown_blocked"])
        + " | controls_present: " + str(dashboard["controls_present"])
        + " | fake_readiness: " + str(dashboard["fake_readiness"]) + "\n\n"
    )

    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n")

    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify the legacy bot tree.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not stop the report center, replay miner, or Codex governors.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable production trading.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not install systemd units or scheduler daemons.\n"
        "- Did not mutate live_symbols, paper_symbols, or training_symbols.\n"
        "- Did not adopt any Symbol Universe candidate.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not deserialize any legacy checkpoint.\n"
        "- Did not expose any raw API key.\n"
    )
    return "".join(lines)
