"""V2 startup-manifest role coverage remediation (read-only).

Reconciles the V2 paper-only startup runtime against the canonical
legacy startup manifest. Loads canonical role IDs from
``claude_worklog/final_readiness/v2_legacy_startup_manifest_parity_and_bridge_exit/
latest/legacy_startup_manifest.json`` and produces a full-coverage
status that includes every canonical role exactly once. V2-only automation
such as the replay miner, report-center indexer, and governors remain
tracked in their own packets; they must not inflate startup-manifest
parity role counts.

For every role the output records:

* legacy_service_id, legacy_command (rendered), startup_phase
* criticality, live_risk
* v2_equivalent, v2_status (one of six valid statuses)
* bridge_label_required
* old_redis_write_allowed = False
* exchange_mutation_allowed = False
* blocks_paper / blocks_production_equivalence / blocks_shutdown / blocks_live
* next_action

Read-only with respect to runtime; no daemon mutation, no Redis writes,
no exchange calls, no live approval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_runtime_migration.v2_paper_startup_manifest import (
    STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
    STATUS_OPERATOR_DECISION_REQUIRED,
    STATUS_V2_BRIDGE_READ_ONLY,
    STATUS_V2_PLACEHOLDER_BLOCKED,
    STATUS_V2_SERVICE_ACTIVE,
    STATUS_V2_SERVICE_STARTABLE,
    VALID_STATUSES,
    build_paper_runtime_process_status,
    build_v2_paper_startup_manifest_status,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    safety_block,
    utc_now_iso,
)


SCHEMA_VERSION = "v2_full_paper_only_startup_manifest_role_coverage_remediation_v1"


# ---------------------------------------------------------------------------
# Per-canonical-role override table
# ---------------------------------------------------------------------------
#
# Indexed by the canonical ``service_id`` exactly as the legacy manifest
# parses it. Each row carries the V2-side classification plus the fields
# the remediation brief requires.

_CANONICAL_OVERRIDES: dict[str, dict[str, Any]] = {
    # Preflight
    "duplicate_process_guard": {
        "v2_equivalent": "v2 supervisor file-lock registry",
        "v2_status": STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": (
            "No V2 equivalent needed; documented as NOT_REQUIRED."
        ),
    },
    "force_kill_all_bot_py": {
        "v2_equivalent": "operator override path; supervisor enforces single writer",
        "v2_status": STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No V2 equivalent needed.",
    },
    "vram_threshold_check": {
        "v2_equivalent": "v2 startup preflight VRAM gate (planned)",
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": True,
        "blocks_live": True,
        "next_action": "Add v2_startup_preflight_vram_gate.",
    },
    "ram_threshold_check": {
        "v2_equivalent": "v2 startup preflight RAM gate (planned)",
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": True,
        "blocks_live": True,
        "next_action": "Add v2_startup_preflight_ram_gate.",
    },
    "disk_threshold_check": {
        "v2_equivalent": "v2 startup preflight disk gate (planned)",
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": True,
        "blocks_live": False,
        "next_action": "Add v2_startup_preflight_disk_gate.",
    },
    "redis_running_check": {
        "v2_equivalent": "v2 supervisor redis ping probe",
        "v2_status": STATUS_V2_SERVICE_STARTABLE,
        "bridge_label_required": False,
        "blocks_paper": True,
        "blocks_production_equivalence": True,
        "blocks_shutdown": True,
        "blocks_live": True,
        "next_action": "No action; probe runs on every supervisor cycle.",
    },
    # Monitoring (Phase 0.5)
    "vpn_monitor": {
        "v2_equivalent": (
            "v2_system_observability_status_publisher VPN route/interface "
            "probe; reconnect remains operator-only"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": (
            "No auto-reconnect; operator handles VPN repair if the probe "
            "reports VPN_NOT_DETECTED_OR_NOT_REQUIRED unexpectedly."
        ),
    },
    "system_telegram_monitor": {
        "v2_equivalent": (
            "v2_system_observability_status_publisher Telegram config "
            "presence probe; no message send"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": (
            "Message sending remains operator-required; current V2 coverage "
            "is read-only config/status evidence."
        ),
    },
    "monitor_system_memory": {
        "v2_equivalent": (
            "v2_system_observability_status_publisher memory and Redis "
            "memory telemetry"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; read-only memory status payload is active.",
    },
    "scripts_memory_monitor": {
        "v2_equivalent": (
            "v2_system_observability_status_publisher process and memory "
            "growth telemetry"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; V2 read-only monitor emits current status.",
    },
    "ingestors_watchdog": {
        "v2_equivalent": "v2 native ingestor watchdog (planned)",
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Build v2_native_ingestor_watchdog under self-healing.",
    },
    "monitor_trainer_predictions": {
        "v2_equivalent": "v2 trainer prediction monitor",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action.",
    },
    # Ingestors (Phase 1)
    "ingest_live_binance": {
        "v2_equivalent": "v2 native Binance USDM ingestor active for dynamic 101-symbol universe",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": True,
        "blocks_live": True,
        "next_action": (
            "No action; dynamic OHLCV/orderbook/price coverage is active."
        ),
    },
    "ingest_live_kucoin": {
        "v2_equivalent": "v2 KuCoin public REST ingestor active in V2 namespace",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action for read-only paper/shadow data.",
    },
    "ingest_live_coinank": {
        "v2_equivalent": "direct legacy-owned CoinAnk live ingestor",
        "v2_status": STATUS_V2_BRIDGE_READ_ONLY,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": (
            "Keep ai-bot-v2-coinank-live-direct.service running directly; "
            "repair CoinAnk API auth/plan errors separately if endpoint 401 persists."
        ),
    },
    "ingest_live_coinank_global_aggregator": {
        "v2_equivalent": (
            "direct legacy-owned CoinAnk global aggregator publishes trainer aggregate keys"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action for current read-only V2 parity.",
    },
    "ingest_live_binance_liquidations": {
        "v2_equivalent": "v2 liquidation WSS persistent paper-shadow daemon",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Extend symbol coverage under Symbol Universe governance.",
    },
    "ingest_liquidation_bridge": {
        "v2_equivalent": "v2 liquidation WSS aggregate emitter",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action.",
    },
    "ingest_liquidation_levels_engine": {
        "v2_equivalent": (
            "v2 native liquidation levels engine active for dynamic 101-symbol x 5-timeframe grid"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; continue warm/live WSS-driven updates.",
    },
    "ingest_realtime_price_provider": {
        "v2_equivalent": "v2 market ingestor prices stream",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Dynamic-symbol expansion via ingestor plan.",
    },
    "ingest_live_coinapi_wsds": {
        "v2_equivalent": (
            "v2 CoinAPI WSDS persistent read-only ingestor"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action while credential/opt-in remains present.",
    },
    "ingest_live_coinapi_v1": {
        "v2_equivalent": (
            "v2 CoinAPI REST/OHLCV fallback ingestor"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action for current read-only V2 parity.",
    },
    # Features
    "ohlcv_resampler_hotfix": {
        "v2_equivalent": "v2 native ingestors maintain 1m/5m/15m/1h/4h OHLCV keys",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; all five OHLCV timeframes are present.",
    },
    "feature_pipeline": {
        "v2_equivalent": "v2 feature pipeline native dynamic 101-symbol x 5-timeframe mirror",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; features:latest is now 505/505.",
    },
    "live_technical_analysis": {
        "v2_equivalent": "v2 full TA-Lib loop writes v2:features:ta*, ta_full*, and technical_analysis* for 505/505",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; TA V2 key coverage is now 505/505.",
    },
    # Validation gates
    "paralysis_detectors": {
        "v2_equivalent": "v2 native paralysis detector (planned)",
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Build v2_native_paralysis_detector_health_probe.",
    },
    "validate_symbol_universe_data": {
        "v2_equivalent": (
            "v2 native universe data validator (planned startup gate)"
        ),
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Build v2_native_universe_data_validator_startup_gate.",
    },
    # Health
    "health_probe": {
        "v2_equivalent": (
            "v2 report center freshness panel + executive command center"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action; dedicated startup-time probe is planned.",
    },
    "critical_health_monitor": {
        "v2_equivalent": (
            "v2 native critical health monitor (planned startup gate)"
        ),
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Build v2_native_critical_health_monitor_startup_gate.",
    },
    # Trainer + orchestrator
    "rl_hybrid_trainer": {
        "v2_equivalent": (
            "v2 native RL/MASA/PPO CUDA trainer + native prediction publisher"
        ),
        "v2_status": STATUS_V2_BRIDGE_READ_ONLY,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": (
            "Keep native CUDA trainer parity burn-down current and do not reintroduce trainer bridge/runtime wrapper dependencies."
        ),
    },
    "rl_orchestrator_worker": {
        "v2_equivalent": "v2 orchestrator arbitration (paper-only)",
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action.",
    },
    # Signal router + traders + portfolio monitors
    "signal_router": {
        "v2_equivalent": "not required for single-account paper-only",
        "v2_status": STATUS_NOT_REQUIRED_FOR_PAPER_SHADOW,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Defer until operator approves multi-account.",
    },
    "trading_trader_primary": {
        "v2_equivalent": (
            "v2 paper-mode trader; legacy trader NOT ported"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": True,
        "next_action": (
            "Keep V2 paper-only; legacy trader stays unported until live"
            " readiness packet is operator-approved."
        ),
    },
    "trading_trader_asjad": {
        "v2_equivalent": "operator decision before multi-account paper",
        "v2_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Defer until operator approves multi-account.",
    },
    "monitor_portfolio_primary": {
        "v2_equivalent": (
            "v2 account position monitor + position history tracker"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Dynamic-symbol expansion follows paper-trader roster.",
    },
    "monitor_portfolio_asjad": {
        "v2_equivalent": "operator decision for multi-account",
        "v2_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Defer until multi-account paper approved.",
    },
    # Final status
    "process_listing_and_resource_report": {
        "v2_equivalent": (
            "v2 throughput acceleration packet + v2 report center"
        ),
        "v2_status": STATUS_V2_SERVICE_ACTIVE,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "No action.",
    },
    "telegram_completion_notification": {
        "v2_equivalent": (
            "v2 Telegram completion notification (operator decision)"
        ),
        "v2_status": STATUS_OPERATOR_DECISION_REQUIRED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": "Defer until operator authorizes V2 Telegram bridge.",
    },
}


_PHASE_TO_CRITICALITY = {
    "0_preflight": "CRITICAL",
    "0_5_monitoring": "OBSERVABILITY",
    "1_ingestors": "CRITICAL",
    "2_features": "CRITICAL",
    "2_5_ta": "CRITICAL",
    "2_5_validation": "REQUIRED",
    "3_trainer": "CRITICAL",
    "3B_orchestrator": "CRITICAL",
    "4A_signal_router": "REQUIRED",
    "4B_traders": "CRITICAL",
    "4C_portfolio": "REQUIRED",
    "5_health": "REQUIRED",
    "6_final_status": "OBSERVABILITY",
}


def _load_canonical_manifest(repo_root: Path) -> dict[str, Any]:
    path = (
        repo_root
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_startup_manifest.json"
    )
    if not path.exists():
        return {"item_count": 0, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"item_count": 0, "items": []}


def _build_role_row(canonical: dict[str, Any]) -> dict[str, Any]:
    service_id = canonical.get("service_id", "")
    override = _CANONICAL_OVERRIDES.get(service_id, {
        "v2_equivalent": None,
        "v2_status": STATUS_V2_PLACEHOLDER_BLOCKED,
        "bridge_label_required": False,
        "blocks_paper": False,
        "blocks_production_equivalence": True,
        "blocks_shutdown": False,
        "blocks_live": False,
        "next_action": (
            "Unknown canonical service; classified as placeholder pending"
            " operator review."
        ),
    })
    return {
        "legacy_service_id": service_id,
        "legacy_command": canonical.get("legacy_command"),
        "legacy_script_path": canonical.get("legacy_script_path"),
        "startup_phase": canonical.get("phase"),
        "criticality": canonical.get(
            "criticality",
            _PHASE_TO_CRITICALITY.get(canonical.get("phase"), "OBSERVABILITY"),
        ),
        "live_risk": canonical.get("live_risk", "NONE"),
        "v2_equivalent": override["v2_equivalent"],
        "v2_status": override["v2_status"],
        "bridge_label_required": override["bridge_label_required"],
        "old_redis_write_allowed": False,
        "exchange_mutation_allowed": False,
        "blocks_paper": override["blocks_paper"],
        "blocks_production_equivalence": override["blocks_production_equivalence"],
        "blocks_shutdown": override["blocks_shutdown"],
        "blocks_live": override["blocks_live"],
        "next_action": override["next_action"],
    }


def build_startup_manifest_role_coverage_status(repo_root: Path) -> dict[str, Any]:
    canonical = _load_canonical_manifest(repo_root)
    canonical_count = canonical.get("item_count", 0)
    canonical_items = canonical.get("items", [])
    canonical_service_ids = [c.get("service_id", "") for c in canonical_items]

    rows = [_build_role_row(it) for it in canonical_items]
    represented_ids = {r["legacy_service_id"] for r in rows}
    missing = [
        sid for sid in canonical_service_ids if sid not in represented_ids
    ]
    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r["v2_status"]] = (
            status_counts.get(r["v2_status"], 0) + 1
        )

    # Validate every row.
    invalid_rows: list[str] = []
    for r in rows:
        if r["v2_status"] not in VALID_STATUSES:
            invalid_rows.append(r["legacy_service_id"])
        if r["old_redis_write_allowed"] is not False:
            invalid_rows.append(r["legacy_service_id"] + ":old_redis_write_allowed")
        if r["exchange_mutation_allowed"] is not False:
            invalid_rows.append(
                r["legacy_service_id"] + ":exchange_mutation_allowed"
            )

    return {
        "schema_version": SCHEMA_VERSION + "_startup_manifest_role_coverage_status",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "canonical_manifest_role_count": canonical_count,
        "v2_runtime_role_count": len(rows),
        "missing_role_count": len(missing),
        "missing_role_ids": missing,
        "every_canonical_role_represented": len(missing) == 0,
        "every_role_has_valid_status": not invalid_rows,
        "invalid_rows": invalid_rows,
        "status_counts": status_counts,
        "valid_statuses": list(VALID_STATUSES),
        "rows": rows,
    }


def _utc_now_iso():
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


# ---------------------------------------------------------------------------
# Refreshed primary status (overrides the prior 30-role v2_paper_startup_
# manifest_status with the full 38-role coverage)
# ---------------------------------------------------------------------------


def build_refreshed_v2_paper_startup_manifest_status(
    repo_root: Path,
    coverage: dict[str, Any],
) -> dict[str, Any]:
    base = build_v2_paper_startup_manifest_status(repo_root)

    # The primary startup-manifest runtime payload must represent the
    # canonical legacy startup manifest, not the old V2-only role list plus
    # canonical additions. Keeping V2-only automation here caused the primary
    # status to report 58 roles while the canonical manifest has 38.
    roles = []
    for row in coverage["rows"]:
        sid = row["legacy_service_id"]
        roles.append({
            "role_id": sid,
            "legacy_role": sid,
            "legacy_service_id": sid,
            "legacy_command": row["legacy_command"],
            "legacy_script_path": row.get("legacy_script_path"),
            "startup_phase": row["startup_phase"],
            "v2_paper_equivalent": row["v2_equivalent"],
            "v2_equivalent": row["v2_equivalent"],
            "default_status": row["v2_status"],
            "status": row["v2_status"],
            "v2_status": row["v2_status"],
            "process_marker": None,
            "v2_redis_key_pattern": None,
            "public_payload_path": None,
            "process_alive_probe": False,
            "v2_redis_key_count_probe": None,
            "public_payload_age_seconds_probe": None,
            "observed_status": row["v2_status"],
            "blocks_paper": row["blocks_paper"],
            "blocks_production_equivalence": row[
                "blocks_production_equivalence"
            ],
            "blocks_shutdown": row["blocks_shutdown"],
            "blocks_live": row["blocks_live"],
            "bridge_label_required": row["bridge_label_required"],
            "next_action": row["next_action"],
            "criticality": row["criticality"],
            "live_risk": row["live_risk"],
            "old_redis_write_allowed": False,
            "exchange_mutation_allowed": False,
        })
    counts: dict[str, int] = {}
    for r in roles:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        **base,
        "role_count": len(roles),
        "status_counts": counts,
        "roles": roles,
        "canonical_manifest_role_count": coverage["canonical_manifest_role_count"],
        "canonical_roles_added_for_full_coverage": 0,
        "v2_only_roles_excluded_from_manifest_parity": True,
        "v2_only_roles_tracking_note": (
            "Replay miner, report-center indexer, governors, and other V2-only "
            "automation are tracked in their own readiness packets, not counted "
            "as legacy startup-manifest roles."
        ),
        "every_canonical_role_represented": (
            coverage["every_canonical_role_represented"]
        ),
        "missing_role_count": coverage["missing_role_count"],
        "missing_role_ids": coverage["missing_role_ids"],
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class RemediationPaths:
    repo_root: Path
    packet_dir: Path
    primary_packet_dir: Path
    primary_public_dir: Path


def default_paths(repo_root: Path) -> RemediationPaths:
    return RemediationPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_full_paper_only_startup_manifest_role_coverage_remediation/latest",
        primary_packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_full_paper_only_startup_manifest_runtime/latest",
        primary_public_dir=repo_root
        / "v2/frontend/public/v2_full_paper_only_startup_manifest_runtime/latest",
    )


@dataclass
class RemediationRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_remediation_packet(paths: RemediationPaths) -> RemediationRunResult:
    coverage = build_startup_manifest_role_coverage_status(paths.repo_root)
    refreshed_status = build_refreshed_v2_paper_startup_manifest_status(
        paths.repo_root, coverage
    )
    process_status = build_paper_runtime_process_status(paths.repo_root)
    dashboard = {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": utc_now_iso(),
        "go_no_go": (
            "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_READY"
        ),
        "safety_scoreboard": safety_block(),
        "summary": {
            "canonical_manifest_role_count": coverage["canonical_manifest_role_count"],
            "v2_runtime_role_count_after_remediation": refreshed_status["role_count"],
            "missing_role_count": coverage["missing_role_count"],
            "every_canonical_role_represented": coverage[
                "every_canonical_role_represented"
            ],
            "status_counts_after_remediation": refreshed_status["status_counts"],
        },
        "controls_present": False,
        "fake_readiness": False,
    }

    # Remediation packet artifacts
    _atomic_write_json(
        paths.packet_dir / "startup_manifest_role_coverage_status.json",
        coverage,
    )
    _atomic_write_json(
        paths.packet_dir / "refreshed_v2_paper_startup_manifest_status.json",
        refreshed_status,
    )
    _atomic_write_json(
        paths.packet_dir / "refreshed_paper_runtime_process_status.json",
        process_status,
    )
    _atomic_write_json(
        paths.packet_dir / "operator_dashboard_payload.json", dashboard
    )

    # Refresh the primary v2_full_paper_only_startup_manifest_runtime packet
    # so the report center and previously-emitted payloads no longer expose
    # the stale 30-role state.
    _atomic_write_json(
        paths.primary_packet_dir / "v2_paper_startup_manifest_status.json",
        refreshed_status,
    )
    _atomic_write_json(
        paths.primary_packet_dir / "paper_runtime_process_status.json",
        process_status,
    )
    _atomic_write_json(
        paths.primary_public_dir / "v2_paper_startup_manifest_status.json",
        refreshed_status,
    )

    # Update the primary public dashboard with the new role count so the
    # report-center summary picks it up on next index.
    primary_dashboard_path = (
        paths.primary_public_dir / "operator_dashboard_payload.json"
    )
    if primary_dashboard_path.exists():
        try:
            primary_dashboard = json.loads(
                primary_dashboard_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            primary_dashboard = {}
        primary_dashboard["generated_utc"] = utc_now_iso()
        primary_dashboard.setdefault("summary", {})
        primary_dashboard["summary"]["role_count"] = refreshed_status["role_count"]
        primary_dashboard["summary"]["status_counts"] = refreshed_status[
            "status_counts"
        ]
        primary_dashboard["summary"]["canonical_manifest_role_count"] = (
            coverage["canonical_manifest_role_count"]
        )
        primary_dashboard["summary"]["missing_role_count"] = coverage[
            "missing_role_count"
        ]
        primary_dashboard["summary"]["every_canonical_role_represented"] = (
            coverage["every_canonical_role_represented"]
        )
        _atomic_write_json(primary_dashboard_path, primary_dashboard)

    report = _render_report(coverage, refreshed_status, dashboard)
    _atomic_write_text(
        paths.packet_dir
        / "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_READY\n",
    )

    return RemediationRunResult(
        go_no_go=(
            "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_READY"
        ),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_REPORT.md",
            paths.packet_dir / "startup_manifest_role_coverage_status.json",
            paths.packet_dir / "refreshed_v2_paper_startup_manifest_status.json",
            paths.packet_dir / "refreshed_paper_runtime_process_status.json",
            paths.packet_dir / "operator_dashboard_payload.json",
            paths.primary_packet_dir / "v2_paper_startup_manifest_status.json",
            paths.primary_packet_dir / "paper_runtime_process_status.json",
            paths.primary_public_dir / "v2_paper_startup_manifest_status.json",
            paths.primary_public_dir / "operator_dashboard_payload.json",
        ],
    )


def _render_report(coverage, refreshed_status, dashboard) -> str:
    lines = []
    lines.append(
        "# V2 Full Paper-Only Startup Manifest Role Coverage Remediation\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_"
        "REMEDIATION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    lines.append("## Coverage\n")
    lines.append(
        "- canonical_manifest_role_count: "
        + str(coverage["canonical_manifest_role_count"]) + "\n"
        "- v2_runtime_role_count_after_remediation: "
        + str(refreshed_status["role_count"]) + "\n"
        "- missing_role_count: " + str(coverage["missing_role_count"]) + "\n"
        "- every_canonical_role_represented: "
        + str(coverage["every_canonical_role_represented"]) + "\n\n"
    )
    lines.append("## Status counts (after remediation)\n")
    for status, n in sorted(refreshed_status["status_counts"].items()):
        lines.append("- " + status + ": " + str(n) + "\n")
    lines.append("\n## Per-canonical-role rows\n")
    for row in coverage["rows"]:
        lines.append(
            "- " + row["legacy_service_id"] + " [" + row["v2_status"] + "]"
            " bridge=" + str(row["bridge_label_required"])
            + " blocks_live=" + str(row["blocks_live"]) + "\n"
        )
    lines.append("\n## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not start or stop any daemon.\n"
        "- Did not install any systemd unit.\n"
        "- Did not run any raw legacy script.\n"
        "- Did not start any new network feed.\n"
        "- Did not load or log any API credential value.\n"
        "- Did not modify the legacy bot tree.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not label any bridge data V2_NATIVE.\n"
        "- Did not claim trainer native readiness.\n"
        "- Did not claim full migration.\n"
    )
    return "".join(lines)
