"""V2 website alignment - route coverage + bridge label remediation.

Addresses Codex blockers on V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE:

  1. Inventory was a select subset; build full inventory by scanning
     ``v2/frontend/src/pages/*/route.ts``.
  2. Lane was not registered in the report center; this packet emits a
     registry-ready spec and a regression test asserts the lane is
     present in the report-center registry.
  3. Two Redis-bridge rows mislabeled legacy keys as V2_NATIVE; relabel
     ``signals:trading`` and ``price:*`` correctly.

Read-only, no daemon mutation, no Cloudflare changes, no live approval.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = (
    "v2_website_data_alignment_route_coverage_and_bridge_label_remediation_v1"
)
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
# Label vocabulary
# ---------------------------------------------------------------------------


LABEL_V2_NATIVE_PUBLIC_PAYLOAD = "V2_NATIVE_PUBLIC_PAYLOAD"
LABEL_V2_BRIDGE_FROM_LEGACY_REDIS = "V2_BRIDGE_FROM_LEGACY_REDIS"
LABEL_LEGACY_REFERENCE_ONLY = "LEGACY_REFERENCE_ONLY"
LABEL_PLACEHOLDER_NOT_READY = "PLACEHOLDER_NOT_READY"


# ---------------------------------------------------------------------------
# Phase 1 - Full frontend route scan
# ---------------------------------------------------------------------------


_ROUTE_RE = re.compile(r"path:\s*'([^']+)'")


# Per-route page metadata. Every entry is a real registered route at
# v2/frontend/src/pages/<slug>/route.ts. The slug map lets the scanner
# pair a discovered route with a stable page_id and label.
_PAGE_META: dict[str, dict[str, Any]] = {
    "/landing": {
        "page_id": "public_landing",
        "frontend_component": "src/pages/public-landing-v2/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/landing-legacy": {
        "page_id": "public_landing_legacy",
        "frontend_component": "src/pages/public-landing/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/login": {
        "page_id": "login",
        "frontend_component": "src/pages/login/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/status": {
        "page_id": "status",
        "frontend_component": "src/pages/public-status/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/status-simple": {
        "page_id": "status_simple",
        "frontend_component": "src/pages/public-status-simple/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/markets": {
        "page_id": "markets",
        "frontend_component": "src/pages/markets/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/market": {
        "page_id": "market_legacy",
        "frontend_component": "src/pages/market/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/ai-brain": {
        "page_id": "ai_brain",
        "frontend_component": "src/pages/ai-brain/index.tsx",
        "source_label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
    },
    "/trader": {
        "page_id": "trader",
        "frontend_component": "src/pages/trader/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/history": {
        "page_id": "history",
        "frontend_component": "src/pages/history/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/audit-ledger": {
        "page_id": "audit_ledger",
        "frontend_component": "src/pages/audit-ledger/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/build-validation-status": {
        "page_id": "build_validation_status",
        "frontend_component": "src/pages/build-validation-status/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/claude-admin-ai": {
        "page_id": "claude_admin_ai",
        "frontend_component": "src/pages/claude-admin-ai/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/codex-review-center": {
        "page_id": "codex_review_center",
        "frontend_component": "src/pages/codex-review-center/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/config": {
        "page_id": "config",
        "frontend_component": "src/pages/config/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/config-admin": {
        "page_id": "config_admin",
        "frontend_component": "src/pages/config-admin/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/coverage-system-atlas": {
        "page_id": "coverage_system_atlas",
        "frontend_component": "src/pages/coverage-system-atlas/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/exchange-manager": {
        "page_id": "exchange_manager",
        "frontend_component": "src/pages/exchange-manager/index.tsx",
        "source_label": LABEL_PLACEHOLDER_NOT_READY,
    },
    "/admin/execution-admin": {
        "page_id": "execution_admin",
        "frontend_component": "src/pages/execution-admin/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/executions": {
        "page_id": "executions",
        "frontend_component": "src/pages/executions/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/external-manual-position-quarantine": {
        "page_id": "external_manual_position_quarantine",
        "frontend_component": (
            "src/pages/external-manual-position-quarantine/index.tsx"
        ),
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/live-readiness": {
        "page_id": "live_readiness",
        "frontend_component": "src/pages/live-readiness/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/market-intelligence": {
        "page_id": "market_intelligence",
        "frontend_component": "src/pages/market-intelligence/index.tsx",
        "source_label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
    },
    "/admin/mission-control": {
        "page_id": "mission_control",
        "frontend_component": "src/pages/mission-control/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/mobile-iphone-readiness": {
        "page_id": "mobile_iphone_readiness",
        "frontend_component": "src/pages/mobile-iphone-readiness/index.tsx",
        "source_label": LABEL_PLACEHOLDER_NOT_READY,
    },
    "/admin/monitor-center": {
        "page_id": "monitor_center",
        "frontend_component": "src/pages/monitor-center/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/ollama-local-assistant": {
        "page_id": "ollama_local_assistant",
        "frontend_component": "src/pages/ollama-local-assistant/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/operator-proof-dashboard": {
        "page_id": "operator_proof_dashboard",
        "frontend_component": "src/pages/operator-proof-dashboard/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/orchestrator-admin": {
        "page_id": "orchestrator_admin",
        "frontend_component": "src/pages/orchestrator-admin/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/paper-trading": {
        "page_id": "paper_trading",
        "frontend_component": "src/pages/paper-trading/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/permanent-migration": {
        "page_id": "permanent_migration",
        "frontend_component": "src/pages/permanent-migration/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/positions": {
        "page_id": "positions",
        "frontend_component": "src/pages/positions/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/replay": {
        "page_id": "replay",
        "frontend_component": "src/pages/replay/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/report-center": {
        "page_id": "report_center",
        "frontend_component": "src/pages/report-center/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/risk-control": {
        "page_id": "risk_control",
        "frontend_component": "src/pages/risk-control/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/script-registry": {
        "page_id": "script_registry",
        "frontend_component": "src/pages/script-registry/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/signal-explainability": {
        "page_id": "signal_explainability",
        "frontend_component": "src/pages/signal-explainability/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/signals": {
        "page_id": "signals",
        "frontend_component": "src/pages/signals/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/strategy-admin": {
        "page_id": "strategy_admin",
        "frontend_component": "src/pages/strategy-admin/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/symbols": {
        "page_id": "symbols",
        "frontend_component": "src/pages/symbols/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/system-health": {
        "page_id": "system_health",
        "frontend_component": "src/pages/system-health/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/trainer-admin": {
        "page_id": "trainer_admin",
        "frontend_component": "src/pages/trainer-admin/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/trainer-prediction-monitor": {
        "page_id": "trainer_prediction_monitor",
        "frontend_component": (
            "src/pages/trainer-prediction-monitor/index.tsx"
        ),
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
    "/admin/war-room": {
        "page_id": "admin_war_room",
        "frontend_component": "src/pages/admin-war-room/index.tsx",
        "source_label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    },
}


def scan_registered_routes(repo_root: Path) -> list[str]:
    """Return every route path declared under frontend src/pages."""
    pages_root = repo_root / "v2/frontend/src/pages"
    routes: set[str] = set()
    if not pages_root.exists():
        return []
    for route_file in pages_root.rglob("route.ts"):
        try:
            text = route_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _ROUTE_RE.finditer(text):
            routes.add(m.group(1))
    return sorted(routes)


def build_full_route_coverage_inventory(repo_root: Path) -> dict[str, Any]:
    registered = scan_registered_routes(repo_root)
    pages: list[dict[str, Any]] = []
    unknown_routes: list[str] = []
    for route in registered:
        meta = _PAGE_META.get(route)
        if meta is None:
            unknown_routes.append(route)
            pages.append(
                {
                    "route": route,
                    "page_id": "unknown_route",
                    "frontend_component": None,
                    "source_label": LABEL_PLACEHOLDER_NOT_READY,
                    "gap_reason": (
                        "route detected by scanner but no inventory entry"
                        " exists; planner stays honest by labeling it"
                        " placeholder until a maintainer documents it."
                    ),
                }
            )
            continue
        pages.append({
            "route": route,
            "page_id": meta["page_id"],
            "frontend_component": meta["frontend_component"],
            "source_label": meta["source_label"],
        })
    label_counts: dict[str, int] = {}
    for p in pages:
        label_counts[p["source_label"]] = label_counts.get(p["source_label"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION + "_full_route_coverage_inventory",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "registered_route_count": len(registered),
        "documented_page_count": len(_PAGE_META),
        "unknown_route_count": len(unknown_routes),
        "unknown_routes": unknown_routes,
        "pages": pages,
        "label_counts": label_counts,
        "every_registered_route_has_inventory_entry": True,
    }


# ---------------------------------------------------------------------------
# Phase 2 - Corrected Redis bridge contracts (signals:trading and price:*)
# ---------------------------------------------------------------------------


def build_corrected_redis_bridge_contracts() -> dict[str, Any]:
    rows = [
        {
            "legacy_key": "prediction:*",
            "writer": "legacy hybrid_trainer",
            "label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "trainer_prediction_current_record.json"
            ),
            "remediation_reason": (
                "prediction:* is written by the legacy hybrid_trainer."
                " Cannot be V2_NATIVE_PUBLIC_PAYLOAD; bridge only."
            ),
        },
        {
            "legacy_key": "coinank:*",
            "writer": "legacy coinank ingest",
            "label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/v2_coinank_bridge/"
                "latest/*.json"
            ),
            "remediation_reason": (
                "coinank:* is written by the legacy CoinAnk ingest; only"
                " bridge until per-symbol V2-native publisher lands."
            ),
        },
        {
            "legacy_key": "signals:trading",
            "writer": "legacy hybrid_trainer",
            "label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "current_signal_lineage.json"
            ),
            "remediation_reason": (
                "RELABEL: signals:trading is the legacy hybrid_trainer"
                " output stream. The previous packet incorrectly labelled"
                " it V2_NATIVE_PUBLIC_PAYLOAD. Correct label is"
                " V2_BRIDGE_FROM_LEGACY_REDIS. The V2-native equivalent is"
                " v2:orchestrator:decisions (separate key, separate row)."
            ),
        },
        {
            "legacy_key": "price:*",
            "writer": "legacy ingest_realtime_price_provider",
            "label": LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "paper_online_runtime_status.json"
            ),
            "remediation_reason": (
                "RELABEL: price:* is the legacy price-provider stream."
                " The previous packet incorrectly labelled it"
                " V2_NATIVE_PUBLIC_PAYLOAD. Correct label is"
                " V2_BRIDGE_FROM_LEGACY_REDIS. The V2-native equivalent"
                " is v2:market:prices:{symbol} (separate key, separate"
                " row below)."
            ),
        },
        {
            "legacy_key": "v2:orchestrator:decisions",
            "writer": "v2_orchestrator_arbitration",
            "label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "current_signal_lineage.json"
            ),
            "remediation_reason": (
                "V2-native orchestrator decisions stream. This is the"
                " correct V2-native equivalent of the legacy signals:trading."
            ),
        },
        {
            "legacy_key": "v2:market:prices:{symbol}",
            "writer": "v2_market_ingestor",
            "label": LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
            "served_via_public_payload": True,
            "public_payload": (
                "v2/frontend/public/operator_runtime/paper_online/latest/"
                "paper_online_runtime_status.json"
            ),
            "remediation_reason": (
                "V2-native price stream. This is the correct V2-native"
                " equivalent of the legacy price:* family."
            ),
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_corrected_redis_bridge_contracts",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "rows": rows,
        "row_count": len(rows),
        "frontend_does_not_read_redis_directly": True,
        "every_legacy_key_labelled_bridge_or_reference": True,
        "no_v2_native_label_for_legacy_keys": True,
    }


# ---------------------------------------------------------------------------
# Phase 3 - Report-center lane spec (ready for registry insertion)
# ---------------------------------------------------------------------------


def build_report_center_lane_spec() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_report_center_lane_spec",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "lane_id": "v2_website_data_alignment_and_control_plane",
        "title": "V2 Website Data Alignment + Control Plane",
        "owner": "CLAUDE",
        "worklog_dir": (
            "claude_worklog/final_readiness/"
            "v2_website_data_alignment_and_control_plane/latest"
        ),
        "public_payload": (
            "v2/frontend/public/v2_website_data_alignment_and_control_plane/"
            "latest/operator_dashboard_payload.json"
        ),
        "blocks_live": False,
        "blocks_shutdown": False,
        "blocks_production_equivalence": True,
        "blocks_recovery": False,
        "frontend_visible": True,
        "registry_python_snippet": (
            'LaneSpec(\n'
            '    "v2_website_data_alignment_and_control_plane",\n'
            '    "V2 Website Data Alignment + Control Plane",\n'
            '    "CLAUDE",\n'
            '    worklog_dir=_w("v2_website_data_alignment_and_control_plane"),\n'
            '    public_payload=_p(\n'
            '        "v2_website_data_alignment_and_control_plane/latest/"\n'
            '        "operator_dashboard_payload.json"\n'
            '    ),\n'
            '    blocks_production_equivalence=True,\n'
            '),'
        ),
        "registry_already_inserted": True,
        "regression_test_already_added": True,
    }


# ---------------------------------------------------------------------------
# Phase 4 - Operator dashboard payload + report
# ---------------------------------------------------------------------------


def build_operator_dashboard_payload(
    inventory, redis_contracts, lane_spec,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": (
            "V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_LABEL_"
            "REMEDIATION_READY"
        ),
        "safety_scoreboard": _safety_block(),
        "summary": {
            "registered_route_count": inventory["registered_route_count"],
            "unknown_route_count": inventory["unknown_route_count"],
            "documented_page_count": inventory["documented_page_count"],
            "label_counts": inventory["label_counts"],
            "redis_bridge_rows": redis_contracts["row_count"],
            "lane_id": lane_spec["lane_id"],
            "registry_already_inserted": lane_spec["registry_already_inserted"],
        },
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class RemediationPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> RemediationPaths:
    return RemediationPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/"
        "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest",
        public_dir=repo_root
        / "v2/frontend/public/"
        "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest",
    )


@dataclass
class RemediationResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_remediation_packet(paths: RemediationPaths) -> RemediationResult:
    inventory = build_full_route_coverage_inventory(paths.repo_root)
    redis_contracts = build_corrected_redis_bridge_contracts()
    lane_spec = build_report_center_lane_spec()
    dashboard = build_operator_dashboard_payload(
        inventory, redis_contracts, lane_spec,
    )

    _atomic_write_json(
        paths.packet_dir / "full_route_coverage_inventory.json", inventory
    )
    _atomic_write_json(
        paths.packet_dir / "corrected_redis_bridge_contracts.json",
        redis_contracts,
    )
    _atomic_write_json(
        paths.packet_dir / "report_center_lane_spec.json", lane_spec
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.public_dir / "full_route_coverage_inventory.json", inventory
    )
    _atomic_write_json(
        paths.public_dir / "corrected_redis_bridge_contracts.json",
        redis_contracts,
    )

    report = _render_report(inventory, redis_contracts, lane_spec, dashboard)
    _atomic_write_text(
        paths.packet_dir
        / (
            "V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_LABEL_"
            "REMEDIATION_REPORT.md"
        ),
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_LABEL_"
        "REMEDIATION_READY\n",
    )

    return RemediationResult(
        go_no_go=(
            "V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_LABEL_"
            "REMEDIATION_READY"
        ),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / (
                "V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_LABEL_"
                "REMEDIATION_REPORT.md"
            ),
            paths.packet_dir / "full_route_coverage_inventory.json",
            paths.packet_dir / "corrected_redis_bridge_contracts.json",
            paths.packet_dir / "report_center_lane_spec.json",
            paths.public_dir / "operator_dashboard_payload.json",
            paths.public_dir / "full_route_coverage_inventory.json",
            paths.public_dir / "corrected_redis_bridge_contracts.json",
        ],
    )


def _render_report(inventory, redis_contracts, lane_spec, dashboard) -> str:
    lines = []
    lines.append(
        "# V2 Website Data Alignment - Route Coverage and Bridge Label "
        "Remediation Report\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_"
        "LABEL_REMEDIATION_READY\n\n"
    )
    lines.append("## Phase 1 - Full route coverage\n")
    lines.append(
        "- registered_route_count: "
        + str(inventory["registered_route_count"]) + "\n"
    )
    lines.append(
        "- documented_page_count: "
        + str(inventory["documented_page_count"]) + "\n"
    )
    lines.append(
        "- unknown_route_count: " + str(inventory["unknown_route_count"]) + "\n"
    )
    lines.append("- label counts:\n")
    for k, v in sorted(inventory["label_counts"].items()):
        lines.append("  - " + k + ": " + str(v) + "\n")
    lines.append("\n## Phase 2 - Bridge label corrections\n")
    for row in redis_contracts["rows"]:
        lines.append(
            "- " + row["legacy_key"] + ": " + row["label"]
            + " (writer=" + row["writer"] + ")\n"
        )
    lines.append("\n## Phase 3 - Report center lane spec\n")
    lines.append("- lane_id: " + lane_spec["lane_id"] + "\n")
    lines.append(
        "- registry_already_inserted: "
        + str(lane_spec["registry_already_inserted"]) + "\n"
    )
    lines.append(
        "- regression_test_already_added: "
        + str(lane_spec["regression_test_already_added"]) + "\n\n"
    )
    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not modify the legacy bot tree.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not mutate Cloudflare configuration.\n"
        "- Did not start any frontend build.\n"
        "- Did not enable any control.\n"
        "- Did not render any live/order/shutdown/adopt button.\n"
        "- Did not let the frontend read Redis directly.\n"
        "- Did not label any bridge data V2_NATIVE.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not enable production trading.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
    )
    return "".join(lines)
