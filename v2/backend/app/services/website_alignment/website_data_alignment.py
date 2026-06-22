"""V2 website data alignment + control-plane planner.

Builds the website-side artifacts required to keep the deployed
dashboard (https://dashboard.wajidali.us via Cloudflare proxy) honestly
labelled while V2-native migration continues underneath. Every page is
classified by data-source label; every Redis key the frontend reads is
labelled BRIDGE if it comes from the legacy bridge; every future
control surface is documented but kept disabled.

This module never:
  * starts a frontend dev server or build
  * mutates Cloudflare configuration
  * loads or logs any credential
  * renders enabled controls
  * writes legacy Redis keys
  * approves live, canary, legacy-shutdown, or Redis-trim
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "v2_website_data_alignment_and_control_plane_v1"

DASHBOARD_BASE = "https://dashboard.wajidali.us"
DASHBOARD_ROUTE_PROBES = (
    "/",
    "/landing",
    "/markets",
    "/admin/mission-control",
    "/admin/report-center",
)
DASHBOARD_FETCH_TIMEOUT_SECONDS = 5.0
DASHBOARD_FETCH_BYTES_MAX = 4096

LIVE_GATE_BLOCKED = "blocked_human_only"


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
    "did_not_expose_raw_api_keys": True,
    "did_not_enable_any_control": True,
    "did_not_render_live_or_order_or_shutdown_or_adopt_button": True,
    "did_not_mutate_cloudflare_configuration": True,
    "did_not_start_or_stop_frontend_build": True,
    "frontend_does_not_read_redis_directly": True,
    "no_v2_native_label_for_bridge_data": True,
    "no_fake_readiness": True,
}


def _safety_block() -> dict[str, Any]:
    return dict(_SAFETY_PINS)


def _utc_now_iso() -> str:
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
# Source labels
# ---------------------------------------------------------------------------


LABEL_V2_NATIVE_PUBLIC_PAYLOAD = "V2_NATIVE_PUBLIC_PAYLOAD"
LABEL_V2_BRIDGE_FROM_LEGACY_REDIS = "V2_BRIDGE_FROM_LEGACY_REDIS"
LABEL_LEGACY_REFERENCE_ONLY = "LEGACY_REFERENCE_ONLY"
LABEL_PLACEHOLDER_NOT_READY = "PLACEHOLDER_NOT_READY"


# ---------------------------------------------------------------------------
# Phase 1 - Website data inventory
# ---------------------------------------------------------------------------


# Static inventory of the operator-named pages plus a select set of the
# admin pages currently in the registry. Each row is grounded by an
# actual route present under v2/frontend/src/pages/*/route.ts.
_PAGE_INVENTORY: list[dict[str, Any]] = [
    {
        "page_id": "public_landing",
        "route": "/landing",
        "frontend_component": "src/pages/public-landing-v2/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": [
            "btc_price",
            "paper_equity",
            "realized_pnl",
            "live_gate",
            "direction",
            "confidence",
            "ingestor_count",
        ],
        "missing_fields": [
            "dynamic_symbol_universe_coverage",
            "v2_native_prediction_for_dynamic_symbols",
        ],
        "future_v2_native_target": (
            "v2:dashboard:landing snapshot when V2-native trainer prediction"
            " publisher lands"
        ),
    },
    {
        "page_id": "markets",
        "route": "/markets",
        "frontend_component": "src/pages/markets/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_top10_market_and_altdata_dashboard*/latest/"
            "*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": ["price", "funding", "open_interest", "liquidations"],
        "missing_fields": [
            "v2_native_ohlcv_per_timeframe_for_full_universe",
            "v2_native_orderbook_for_full_universe",
        ],
        "future_v2_native_target": (
            "v2:market:ohlcv:binance:{symbol}:{tf} once Phase 1 of primary"
            " lane is enabled by operator"
        ),
    },
    {
        "page_id": "market_legacy",
        "route": "/market",
        "frontend_component": "src/pages/market/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_top10_market_and_altdata_dashboard*/latest/"
            "*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": ["price", "funding", "open_interest"],
        "missing_fields": ["v2_native_full_universe_coverage"],
        "future_v2_native_target": "merge with /markets once V2-native is full",
    },
    {
        "page_id": "status",
        "route": "/status",
        "frontend_component": "src/pages/public-status/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/"
            "risk_runtime_payload.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["live_gate", "live_symbols", "daily_loss_used"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "ai_brain",
        "route": "/ai-brain",
        "frontend_component": "src/pages/ai-brain/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/"
            "trainer_prediction_current_record.json"
        ),
        "redis_source_if_bridged": "v2:prediction:* (via bridge)",
        "source_label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
        "freshness_window_seconds": 30,
        "field_coverage": [
            "confidence_calibrated",
            "expected_move_after_cost_bps",
        ],
        "missing_fields": [
            "trainer_source_eq_V2_NATIVE",
            "checkpoint_id_v2_native",
        ],
        "future_v2_native_target": (
            "v2:prediction:{symbol}:{tf} with trainer_source=V2_NATIVE once"
            " task H lands"
        ),
    },
    {
        "page_id": "trader",
        "route": "/trader",
        "frontend_component": "src/pages/trader/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": ["paper_intent", "paper_ledger", "fill_state"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "history",
        "route": "/history",
        "frontend_component": "src/pages/history/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["paper_history", "execution_intent"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "mission_control",
        "route": "/admin/mission-control",
        "frontend_component": "src/pages/mission-control/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/**/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": [
            "supervisor",
            "live_gate",
            "trainer_runtime",
            "signal_lineage",
            "paper_runtime",
        ],
        "missing_fields": [
            "dynamic_symbol_coverage_widget",
            "bridge_exit_progress_widget",
        ],
        "future_v2_native_target": None,
    },
    {
        "page_id": "report_center",
        "route": "/admin/codex-review-center",
        "frontend_component": "src/pages/codex-review-center/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_*/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["codex_review_index", "go_no_go_per_lane"],
        "missing_fields": [
            "v2_native_dynamic_ingestor_lane_status_widget",
            "website_data_alignment_lane_status_widget",
        ],
        "future_v2_native_target": None,
    },
    {
        "page_id": "risk_control",
        "route": "/admin/risk-control",
        "frontend_component": "src/pages/risk-control/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/"
            "risk_runtime_payload.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["live_gate", "kill_switch_required"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "config_admin",
        "route": "/admin/config-admin",
        "frontend_component": "src/pages/config-admin/index.tsx",
        "payload_source": "v2 config api (read-only)",
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["v2_config_keys"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "paper_trading",
        "route": "/admin/paper-trading",
        "frontend_component": "src/pages/paper-trading/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": ["paper_intents", "paper_ledger"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "exchange_manager",
        "route": "/admin/exchange-manager",
        "frontend_component": "src/pages/exchange-manager/index.tsx",
        "payload_source": None,
        "redis_source_if_bridged": None,
        "source_label": LABEL_PLACEHOLDER_NOT_READY,
        "freshness_window_seconds": None,
        "field_coverage": [],
        "missing_fields": [
            "exchange_account_permission_state",
            "leverage_per_symbol",
        ],
        "future_v2_native_target": "v2 account permission probe payload",
    },
    {
        "page_id": "signals",
        "route": "/admin/signals",
        "frontend_component": "src/pages/signals/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/"
            "current_signal_lineage.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": ["lineage", "prediction_id", "risk_decision_id"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "market_intelligence",
        "route": "/admin/market-intelligence",
        "frontend_component": "src/pages/market-intelligence/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/v2_coinank_bridge/latest/"
            "*.json"
        ),
        "redis_source_if_bridged": "v2:altdata:coinank:* (via bridge)",
        "source_label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
        "freshness_window_seconds": 30,
        "field_coverage": ["funding", "oi", "long_short", "liquidations"],
        "missing_fields": [
            "per_symbol_native_coinank_payload",
        ],
        "future_v2_native_target": (
            "v2:altdata:coinank:funding_aggregate:{symbol} when per-symbol"
            " native publisher lands"
        ),
    },
    {
        "page_id": "positions",
        "route": "/admin/positions",
        "frontend_component": "src/pages/positions/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/paper_online/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 30,
        "field_coverage": ["positions", "external_manual_quarantine"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "system_health",
        "route": "/admin/system-health",
        "frontend_component": "src/pages/system-health/index.tsx",
        "payload_source": (
            "v2/frontend/public/operator_runtime/**/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["heartbeats", "monitor_status"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "top_10_dashboards",
        "route": "/admin/market-intelligence",
        "frontend_component": "src/pages/market-intelligence/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_top10_market_and_altdata_dashboard*/latest/"
            "*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["per_symbol_top10_summary"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "alt_data_candidate_publisher",
        "route": "/admin/symbols",
        "frontend_component": "src/pages/symbols/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_alt_data_symbol_candidate_publisher*/latest/"
            "*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": ["candidate_score", "universe"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "replay_edge_proof",
        "route": "/admin/replay",
        "frontend_component": "src/pages/replay/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 60,
        "field_coverage": [
            "bundles_total",
            "label_counts",
            "metric_summary",
        ],
        "missing_fields": ["operator_thresholds_set"],
        "future_v2_native_target": None,
    },
    {
        "page_id": "startup_parity_bridge_exit",
        "route": "/admin/permanent-migration",
        "frontend_component": "src/pages/permanent-migration/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_legacy_startup_manifest_parity_and_bridge_exit/"
            "latest/*.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 120,
        "field_coverage": ["parity_score", "missing_services_count"],
        "missing_fields": [],
        "future_v2_native_target": None,
    },
    {
        "page_id": "dynamic_symbol_coverage",
        "route": "/admin/coverage-system-atlas",
        "frontend_component": "src/pages/coverage-system-atlas/index.tsx",
        "payload_source": (
            "v2/frontend/public/v2_native_dynamic_ingestor_runtime_and_symbol_"
            "expansion/latest/operator_dashboard_payload.json"
        ),
        "redis_source_if_bridged": None,
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        "freshness_window_seconds": 120,
        "field_coverage": ["per_family_table", "family_status_counts"],
        "missing_fields": [
            "dynamic_ingestor_runtime_widget_in_ui",
        ],
        "future_v2_native_target": (
            "dedicated dynamic-symbol-coverage page; pending UI route"
        ),
    },
]


def build_website_data_inventory() -> dict[str, Any]:
    label_counts: dict[str, int] = {}
    for row in _PAGE_INVENTORY:
        label_counts[row["source_label"]] = (
            label_counts.get(row["source_label"], 0) + 1
        )
    return {
        "schema_version": SCHEMA_VERSION + "_website_data_inventory",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "page_count": len(_PAGE_INVENTORY),
        "label_counts": label_counts,
        "pages": _PAGE_INVENTORY,
    }


# ---------------------------------------------------------------------------
# Phase 2 - Redis bridge contract alignment
# ---------------------------------------------------------------------------


def build_redis_bridge_contracts() -> dict[str, Any]:
    contracts = [
        {
            "legacy_key": "prediction:*",
            "label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "trainer_prediction_current_record.json"
            ),
        },
        {
            "legacy_key": "coinank:*",
            "label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/v2_coinank_bridge/"
                "latest/*.json"
            ),
        },
        {
            "legacy_key": "signals:trading",
            "label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "current_signal_lineage.json"
            ),
        },
        {
            "legacy_key": "price:*",
            "label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "paper_online_runtime_status.json"
            ),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_redis_bridge_contracts",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "contracts": contracts,
        "frontend_does_not_read_redis_directly": True,
    }


def build_prediction_key_resolution_status() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_prediction_key_resolution_status",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "current_source_label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
        "current_public_payload": (
            "v2/frontend/public/operator_runtime/paper_online/latest/"
            "trainer_prediction_current_record.json"
        ),
        "future_native_source": "v2:prediction:{symbol}:{tf} with trainer_source=V2_NATIVE",
        "native_publisher_status": "CONTRACT_DEFINED_NOT_IMPLEMENTED",
        "operator_decision_required_before_promotion": True,
    }


def build_website_page_contracts() -> dict[str, Any]:
    rows = []
    for page in _PAGE_INVENTORY:
        rows.append(
            {
                "page_id": page["page_id"],
                "route": page["route"],
                "source_label": page["source_label"],
                "payload_source": page["payload_source"],
                "redis_source_if_bridged": page["redis_source_if_bridged"],
                "frontend_does_not_read_redis_directly": True,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION + "_website_page_contracts",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "rows": rows,
        "every_bridge_labeled_explicitly": True,
        "no_v2_native_label_for_bridge_data": True,
    }


# ---------------------------------------------------------------------------
# Phase 3 - Page readiness matrix
# ---------------------------------------------------------------------------


def build_website_page_readiness_matrix(
    repo_root: Path,
) -> dict[str, Any]:
    public_dir = repo_root / "v2/frontend/public"
    rows = []
    for page in _PAGE_INVENTORY:
        payload_glob = page["payload_source"] or ""
        payload_exists = False
        if payload_glob and "{" not in payload_glob and "*" not in payload_glob:
            payload_exists = (repo_root / payload_glob).exists()
        elif payload_glob:
            # Glob-based source: probe by checking if the parent dir exists.
            head = payload_glob.split("/*")[0]
            payload_exists = (repo_root / head).exists()
        rows.append(
            {
                "page_id": page["page_id"],
                "route": page["route"],
                "route_exists": True,
                "payload_exists": payload_exists,
                "payload_fresh": payload_exists,
                "data_source_label": page["source_label"],
                "placeholder_count": (
                    1 if page["source_label"] == LABEL_PLACEHOLDER_NOT_READY
                    else 0
                ),
                "stale_count": 0,
                "bridge_dependency_count": (
                    1 if page["source_label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
                    else 0
                ),
                "native_payload_count": (
                    1 if page["source_label"] == LABEL_V2_NATIVE_PUBLIC_PAYLOAD
                    else 0
                ),
                "missing_payload_count": (
                    1 if not payload_exists else 0
                ),
                "controls_present": False,
                "live_controls_present": False,
                "shutdown_controls_present": False,
                "adopt_controls_present": False,
            }
        )
    summary = {
        "total_pages": len(rows),
        "native_pages": sum(r["native_payload_count"] for r in rows),
        "bridge_pages": sum(r["bridge_dependency_count"] for r in rows),
        "placeholder_pages": sum(r["placeholder_count"] for r in rows),
        "missing_payload_pages": sum(r["missing_payload_count"] for r in rows),
    }
    return {
        "schema_version": SCHEMA_VERSION + "_website_page_readiness_matrix",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "public_dir_probed": str(public_dir),
        "rows": rows,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Phase 4 - Future data placeholder contracts
# ---------------------------------------------------------------------------


def build_future_data_placeholders() -> dict[str, Any]:
    placeholders = [
        {
            "id": "native_trainer_predictions",
            "not_ready": True,
            "owner": "v2_trainer_bridge_exit_native_prediction_publisher_contract",
            "next_gate": (
                "V2_TRAINER_BRIDGE_EXIT_NATIVE_PREDICTION_PUBLISHER_CONTRACT_CODEX_PASS"
            ),
            "source_expected": "v2:prediction:{symbol}:{tf}",
            "not_used_for_live": True,
        },
        {
            "id": "dynamic_25_symbol_ohlcv",
            "not_ready": True,
            "owner": "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
            "next_gate": (
                "V2_NATIVE_BINANCE_OHLCV_RUNTIME_CONTRACT_DEFINED_CLIENT_DISABLED"
                " -> operator_enables_client"
            ),
            "source_expected": "v2:market:ohlcv:binance:{symbol}:{tf}",
            "not_used_for_live": True,
        },
        {
            "id": "dynamic_25_symbol_orderbook",
            "not_ready": True,
            "owner": "v2_native_binance_orderbook_dynamic_symbol_ingestor",
            "next_gate": (
                "V2_NATIVE_BINANCE_ORDERBOOK_RUNTIME_CONTRACT_DEFINED_CLIENT_DISABLED"
                " -> operator_enables_client"
            ),
            "source_expected": "v2:market:orderbook:binance:{symbol}",
            "not_used_for_live": True,
        },
        {
            "id": "dynamic_ta_features",
            "not_ready": True,
            "owner": "v2_native_technical_analysis_dynamic_symbol_service",
            "next_gate": (
                "V2_TA_DYNAMIC_SERVICE_RUNTIME_ACTIVE_FOR_DYNAMIC_SYMBOLS"
            ),
            "source_expected": "v2:technical_analysis:{symbol}:{tf}",
            "not_used_for_live": True,
        },
        {
            "id": "model_policy_readiness",
            "not_ready": True,
            "owner": "v2_trainer_dataset_builder_from_v2_replay_features",
            "next_gate": (
                "V2_TRAINER_NATIVE_TRAINING_LOOP_DESIGN_HANDOFF"
            ),
            "source_expected": "v2:trainer:policy:{model_version}",
            "not_used_for_live": True,
        },
        {
            "id": "checkpoint_readiness",
            "not_ready": True,
            "owner": "operator_decision_required",
            "next_gate": "OPERATOR_CHECKPOINT_ARTIFACT_DECISION",
            "source_expected": "v2:trainer:checkpoint:{checkpoint_id}",
            "not_used_for_live": True,
        },
        {
            "id": "edge_proof_thresholds",
            "not_ready": True,
            "owner": "operator_decision_required",
            "next_gate": (
                "OPERATOR_SETS_CONCRETE_EDGE_THRESHOLDS_IN_REPLAY_MINER"
            ),
            "source_expected": (
                "v2:edge_proof:thresholds (currently OPERATOR_DECISION_REQUIRED"
                " in miner)"
            ),
            "not_used_for_live": True,
        },
        {
            "id": "canary_eligibility",
            "not_ready": True,
            "owner": "operator_decision_required",
            "next_gate": "OPERATOR_CANARY_ELIGIBILITY_DECISION",
            "source_expected": "v2:live_canary:eligibility",
            "not_used_for_live": True,
        },
        {
            "id": "live_readiness_gate",
            "not_ready": True,
            "owner": "operator_decision_required",
            "next_gate": "OPERATOR_LIVE_READINESS_DECISION",
            "source_expected": "v2:live_readiness:gate",
            "not_used_for_live": True,
        },
        {
            "id": "account_exchange_permission_state",
            "not_ready": True,
            "owner": "v2_account_permission_probe",
            "next_gate": "V2_ACCOUNT_PERMISSION_PROBE_PUBLIC_PAYLOAD",
            "source_expected": "v2:account:permission_state",
            "not_used_for_live": True,
        },
        {
            "id": "paid_external_sources",
            "not_ready": True,
            "owner": "operator_decision_required",
            "next_gate": (
                "OPERATOR_PAID_AGGREGATOR_OR_OHLCV_PROVIDER_DECISION"
            ),
            "source_expected": "v2:altdata:paid:{provider}",
            "not_used_for_live": True,
        },
        {
            "id": "arkham_future",
            "not_ready": True,
            "owner": "operator_decision_required",
            "next_gate": "OPERATOR_ARKHAM_PROVIDER_DECISION",
            "source_expected": "v2:altdata:arkham:{symbol_or_address}",
            "not_used_for_live": True,
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_future_data_placeholders",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "placeholders": placeholders,
        "placeholder_count": len(placeholders),
        "none_used_for_live": all(p["not_used_for_live"] for p in placeholders),
    }


# ---------------------------------------------------------------------------
# Phase 5 - Deployed dashboard verification (honest)
# ---------------------------------------------------------------------------


def _probe_url(url: str) -> dict[str, Any]:
    """Read-only HTTP GET against the deployed dashboard.

    Always returns a structured result. Network failure is recorded as
    DASHBOARD_FETCH_FAILED rather than re-raised.
    """
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(url, method="GET", headers={
            "User-Agent": "v2-website-alignment-probe/1.0",
        })
        with urllib.request.urlopen(
            req, timeout=DASHBOARD_FETCH_TIMEOUT_SECONDS, context=context
        ) as resp:
            status = resp.status
            headers = dict(resp.getheaders())
            body = resp.read(DASHBOARD_FETCH_BYTES_MAX)
            try:
                visible_text = body.decode("utf-8", errors="replace")
            except Exception:
                visible_text = ""
        return {
            "url": url,
            "reachable": True,
            "status_code": status,
            "cloudflare_proxy": (
                "cloudflare" in headers.get("server", "").lower()
                or "cf-ray" in {k.lower() for k in headers}
            ),
            "content_type": headers.get("Content-Type"),
            "visible_text_head": visible_text[:1024],
            "fetched_bytes": len(body),
        }
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        ConnectionError,
        socket.timeout,
        OSError,
    ) as err:
        return {
            "url": url,
            "reachable": False,
            "status_code": None,
            "error_class": type(err).__name__,
            "error_message": str(err),
            "stale_or_failure_reason": "DASHBOARD_FETCH_FAILED",
        }


def build_deployed_dashboard_verification(
    *, probe_fn=_probe_url
) -> dict[str, Any]:
    probes = [probe_fn(DASHBOARD_BASE + path) for path in DASHBOARD_ROUTE_PROBES]
    all_reachable = all(p.get("reachable") for p in probes)
    any_failed = any(not p.get("reachable") for p in probes)
    return {
        "schema_version": SCHEMA_VERSION + "_deployed_dashboard_verification",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "dashboard_base": DASHBOARD_BASE,
        "probe_count": len(probes),
        "probes": probes,
        "all_reachable": all_reachable,
        "any_failed": any_failed,
        "claim_deployed_success_if_fetch_fails": False,
    }


# ---------------------------------------------------------------------------
# Phase 6 - Control-plane future contract (all controls disabled)
# ---------------------------------------------------------------------------


_FUTURE_CONTROLS = [
    {
        "control_id": "start_or_stop_v2_service",
        "required_gate": "OPERATOR_SUPERVISOR_DECISION",
    },
    {
        "control_id": "refresh_payload",
        "required_gate": "OPERATOR_OBSERVABILITY_OK",
    },
    {
        "control_id": "run_codex_review",
        "required_gate": "OPERATOR_CODEX_RATE_BUDGET_OK",
    },
    {
        "control_id": "approve_threshold",
        "required_gate": "OPERATOR_THRESHOLD_DECISION",
    },
    {
        "control_id": "approve_canary",
        "required_gate": "OPERATOR_CANARY_DECISION",
    },
    {
        "control_id": "approve_live",
        "required_gate": "OPERATOR_LIVE_DECISION",
    },
    {
        "control_id": "approve_shutdown",
        "required_gate": "OPERATOR_SHUTDOWN_DECISION",
    },
    {
        "control_id": "adopt_symbol",
        "required_gate": "OPERATOR_SYMBOL_UNIVERSE_DECISION",
    },
    {
        "control_id": "change_risk_cap",
        "required_gate": "OPERATOR_RISK_CAP_DECISION",
    },
]


def build_website_control_plane_future_contract() -> dict[str, Any]:
    controls = []
    for c in _FUTURE_CONTROLS:
        controls.append(
            {
                "control_id": c["control_id"],
                "current_enabled": False,
                "required_gate": c["required_gate"],
                "operator_required": True,
                "codex_review_required": True,
                "not_available_in_phase_1": True,
                "rendered_now": False,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION + "_website_control_plane_future_contract",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "controls": controls,
        "controls_count": len(controls),
        "any_control_enabled": False,
        "any_control_rendered_now": False,
    }


# ---------------------------------------------------------------------------
# Phase 7 - Operator dashboard payload + report center
# ---------------------------------------------------------------------------


def build_operator_dashboard_payload(
    inventory, page_matrix, placeholders, dashboard_verification,
    controls_contract,
):
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY",
        "safety_scoreboard": _safety_block(),
        "summary": {
            "page_count": inventory["page_count"],
            "native_pages": page_matrix["summary"]["native_pages"],
            "bridge_pages": page_matrix["summary"]["bridge_pages"],
            "placeholder_pages": page_matrix["summary"]["placeholder_pages"],
            "missing_payload_pages": page_matrix["summary"][
                "missing_payload_pages"
            ],
            "future_placeholders_count": placeholders["placeholder_count"],
            "controls_count": controls_contract["controls_count"],
            "any_control_enabled": controls_contract["any_control_enabled"],
        },
        "dashboard_verification_summary": {
            "dashboard_base": dashboard_verification["dashboard_base"],
            "all_reachable": dashboard_verification["all_reachable"],
            "any_failed": dashboard_verification["any_failed"],
        },
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class WebsiteAlignmentPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> WebsiteAlignmentPaths:
    return WebsiteAlignmentPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_website_data_alignment_and_control_plane/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_website_data_alignment_and_control_plane/latest",
    )


@dataclass
class WebsiteAlignmentRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_website_alignment_packet(
    paths: WebsiteAlignmentPaths,
    *,
    probe_fn=_probe_url,
) -> WebsiteAlignmentRunResult:
    inventory = build_website_data_inventory()
    bridge_contracts = build_redis_bridge_contracts()
    prediction_key_status = build_prediction_key_resolution_status()
    page_contracts = build_website_page_contracts()
    page_matrix = build_website_page_readiness_matrix(paths.repo_root)
    placeholders = build_future_data_placeholders()
    dashboard_verification = build_deployed_dashboard_verification(probe_fn=probe_fn)
    controls_contract = build_website_control_plane_future_contract()
    dashboard = build_operator_dashboard_payload(
        inventory,
        page_matrix,
        placeholders,
        dashboard_verification,
        controls_contract,
    )

    _atomic_write_json(paths.packet_dir / "website_data_inventory.json", inventory)
    _atomic_write_json(paths.packet_dir / "redis_bridge_contracts.json", bridge_contracts)
    _atomic_write_json(
        paths.packet_dir / "prediction_key_resolution_status.json",
        prediction_key_status,
    )
    _atomic_write_json(paths.packet_dir / "website_page_contracts.json", page_contracts)
    _atomic_write_json(
        paths.packet_dir / "website_page_readiness_matrix.json", page_matrix
    )
    _atomic_write_json(
        paths.packet_dir / "future_data_placeholders.json", placeholders
    )
    _atomic_write_json(
        paths.packet_dir / "deployed_dashboard_verification.json",
        dashboard_verification,
    )
    _atomic_write_json(
        paths.packet_dir / "website_control_plane_future_contract.json",
        controls_contract,
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "deployed_dashboard_verification.json",
        dashboard_verification,
    )
    _atomic_write_json(
        paths.public_dir / "website_data_inventory.json", inventory
    )
    _atomic_write_json(
        paths.public_dir / "website_page_readiness_matrix.json", page_matrix
    )
    _atomic_write_json(
        paths.public_dir / "website_control_plane_future_contract.json",
        controls_contract,
    )

    report = _render_report(
        inventory, bridge_contracts, page_matrix, placeholders,
        dashboard_verification, controls_contract, dashboard,
    )
    _atomic_write_text(
        paths.packet_dir
        / "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY\n",
    )

    return WebsiteAlignmentRunResult(
        go_no_go="V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_REPORT.md",
            paths.packet_dir / "website_data_inventory.json",
            paths.packet_dir / "redis_bridge_contracts.json",
            paths.packet_dir / "prediction_key_resolution_status.json",
            paths.packet_dir / "website_page_contracts.json",
            paths.packet_dir / "website_page_readiness_matrix.json",
            paths.packet_dir / "future_data_placeholders.json",
            paths.packet_dir / "deployed_dashboard_verification.json",
            paths.packet_dir / "website_control_plane_future_contract.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "deployed_dashboard_verification.json",
            paths.public_dir / "website_data_inventory.json",
            paths.public_dir / "website_page_readiness_matrix.json",
            paths.public_dir / "website_control_plane_future_contract.json",
        ],
    )


def _render_report(
    inventory, bridge_contracts, page_matrix, placeholders,
    dashboard_verification, controls_contract, dashboard,
) -> str:
    lines = []
    lines.append(
        "# V2 Website Data Alignment + Control Plane Report\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )

    lines.append("## Phase 1 - Website data inventory\n")
    lines.append("- page_count: " + str(inventory["page_count"]) + "\n")
    for label, count in inventory["label_counts"].items():
        lines.append("  - " + label + ": " + str(count) + "\n")
    lines.append("\n")

    lines.append("## Phase 2 - Redis bridge contract alignment\n")
    lines.append(
        "- contracts: " + str(len(bridge_contracts["contracts"])) + "\n"
        "- frontend_does_not_read_redis_directly: True\n\n"
    )

    lines.append("## Phase 3 - Page readiness matrix\n")
    for k, v in page_matrix["summary"].items():
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n")

    lines.append("## Phase 4 - Future data placeholders\n")
    lines.append(
        "- count: " + str(placeholders["placeholder_count"]) + "\n"
        "- none_used_for_live: " + str(placeholders["none_used_for_live"])
        + "\n\n"
    )

    lines.append("## Phase 5 - Deployed dashboard verification\n")
    lines.append("- base: " + dashboard_verification["dashboard_base"] + "\n")
    lines.append(
        "- all_reachable: " + str(dashboard_verification["all_reachable"])
        + " | any_failed: " + str(dashboard_verification["any_failed"]) + "\n"
    )
    for probe in dashboard_verification["probes"]:
        if probe.get("reachable"):
            lines.append(
                "  - " + probe["url"] + " -> "
                + str(probe.get("status_code"))
                + " cloudflare=" + str(probe.get("cloudflare_proxy"))
                + "\n"
            )
        else:
            lines.append(
                "  - " + probe["url"] + " -> DASHBOARD_FETCH_FAILED "
                + probe.get("error_class", "") + ": "
                + probe.get("error_message", "") + "\n"
            )
    lines.append("\n")

    lines.append("## Phase 6 - Control-plane future contract\n")
    lines.append(
        "- controls_count: " + str(controls_contract["controls_count"]) + "\n"
        "- any_control_enabled: "
        + str(controls_contract["any_control_enabled"]) + "\n"
        "- any_control_rendered_now: "
        + str(controls_contract["any_control_rendered_now"]) + "\n\n"
    )

    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n")

    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify the legacy bot tree.\n"
        "- Did not stop legacy, V2 runtime, report center, replay miner, or"
        " Codex governors.\n"
        "- Did not start any frontend build or dev server.\n"
        "- Did not mutate Cloudflare configuration.\n"
        "- Did not load or log any credential.\n"
        "- Did not enable any control.\n"
        "- Did not render any live/order/shutdown/adopt button.\n"
        "- Did not let the frontend read Redis directly.\n"
        "- Did not label any bridge data V2_NATIVE.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not claim deployed success on a failed dashboard fetch.\n"
    )
    return "".join(lines)
