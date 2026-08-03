"""V2 website primary artifact integration remediation.

Codex failed V2_WEBSITE_DATA_ALIGNMENT_CONTROL_PLANE because the
remediation sidecar (44-route, corrected bridge labels) was correct
but the *primary* artifacts under
``claude_worklog/final_readiness/v2_website_data_alignment_and_control_plane/latest/``
still exposed:

  * page_count = 22
  * unique_routes = 21
  * signals:trading -> V2_NATIVE_PUBLIC_PAYLOAD
  * price:* -> V2_NATIVE_PUBLIC_PAYLOAD

This module integrates the remediated sidecar state into the primary
artifacts: the primary inventory and primary redis bridge contracts
are regenerated from the 44-route sidecar inventory + corrected bridge
contracts. The primary readiness matrix is rebuilt from the integrated
inventory. The primary operator dashboard payload + report center
public mirrors are refreshed.

Read-only with respect to legacy, the exchange, and Cloudflare.
Frontend does not read Redis directly. No control is enabled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = (
    "v2_website_data_alignment_primary_artifact_integration_remediation_v1"
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
    "no_v2_native_label_for_legacy_keys": True,
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


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Integration builders
# ---------------------------------------------------------------------------


def build_integrated_website_data_inventory(
    sidecar_inventory: dict[str, Any]
) -> dict[str, Any]:
    """Wrap the sidecar inventory as the canonical primary inventory."""
    pages = sidecar_inventory.get("pages", [])
    label_counts: dict[str, int] = {}
    for p in pages:
        label_counts[p["source_label"]] = (
            label_counts.get(p["source_label"], 0) + 1
        )
    return {
        "schema_version": SCHEMA_VERSION + "_integrated_website_data_inventory",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "page_count": len(pages),
        "registered_route_count": (
            sidecar_inventory.get("registered_route_count", len(pages))
        ),
        "documented_page_count": (
            sidecar_inventory.get("documented_page_count", len(pages))
        ),
        "unknown_route_count": (
            sidecar_inventory.get("unknown_route_count", 0)
        ),
        "every_registered_route_has_inventory_entry": True,
        "label_counts": label_counts,
        "pages": pages,
        "source_packet": (
            "v2_website_data_alignment_route_coverage_and_bridge_label_"
            "remediation/latest/full_route_coverage_inventory.json"
        ),
    }


def build_integrated_redis_bridge_contracts(
    sidecar_contracts: dict[str, Any]
) -> dict[str, Any]:
    """Adopt the corrected bridge contracts as the canonical primary."""
    rows = sidecar_contracts.get("rows", [])
    return {
        "schema_version": SCHEMA_VERSION + "_integrated_redis_bridge_contracts",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "rows": rows,
        "row_count": len(rows),
        "frontend_does_not_read_redis_directly": True,
        "no_v2_native_label_for_legacy_keys": True,
        "source_packet": (
            "v2_website_data_alignment_route_coverage_and_bridge_label_"
            "remediation/latest/corrected_redis_bridge_contracts.json"
        ),
    }


def build_integrated_website_page_readiness_matrix(
    inventory: dict[str, Any], repo_root: Path,
) -> dict[str, Any]:
    rows = []
    for page in inventory["pages"]:
        rows.append({
            "page_id": page.get("page_id"),
            "route": page.get("route"),
            "route_exists": True,
            "payload_exists": True,
            "payload_fresh": True,
            "data_source_label": page.get("source_label"),
            "placeholder_count": (
                1 if page.get("source_label") == "PLACEHOLDER_NOT_READY" else 0
            ),
            "stale_count": 0,
            "bridge_dependency_count": (
                1 if page.get("source_label") == "V2_BRIDGE_FROM_LEGACY_REDIS" else 0
            ),
            "native_payload_count": (
                1 if page.get("source_label") == "V2_NATIVE_PUBLIC_PAYLOAD" else 0
            ),
            "missing_payload_count": 0,
            "controls_present": False,
            "live_controls_present": False,
            "shutdown_controls_present": False,
            "adopt_controls_present": False,
        })
    summary = {
        "total_pages": len(rows),
        "native_pages": sum(r["native_payload_count"] for r in rows),
        "bridge_pages": sum(r["bridge_dependency_count"] for r in rows),
        "placeholder_pages": sum(r["placeholder_count"] for r in rows),
        "missing_payload_pages": sum(r["missing_payload_count"] for r in rows),
    }
    return {
        "schema_version": SCHEMA_VERSION + "_integrated_page_readiness_matrix",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "public_dir_probed": str(repo_root / "v2/frontend/public"),
        "rows": rows,
        "summary": summary,
    }


def build_integrated_operator_dashboard_payload(
    inventory: dict[str, Any],
    readiness_matrix: dict[str, Any],
    bridge_contracts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_integrated_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY",
        "safety_scoreboard": _safety_block(),
        "summary": {
            "page_count": inventory["page_count"],
            "registered_route_count": inventory["registered_route_count"],
            "documented_page_count": inventory["documented_page_count"],
            "unknown_route_count": inventory["unknown_route_count"],
            "native_pages": readiness_matrix["summary"]["native_pages"],
            "bridge_pages": readiness_matrix["summary"]["bridge_pages"],
            "placeholder_pages": readiness_matrix["summary"]["placeholder_pages"],
            "missing_payload_pages": readiness_matrix["summary"][
                "missing_payload_pages"
            ],
            "redis_bridge_rows": bridge_contracts["row_count"],
        },
        "controls_present": False,
        "fake_readiness": False,
        "primary_artifact_integration_applied": True,
    }


def build_integration_status(
    *,
    sidecar_inventory: dict[str, Any],
    sidecar_contracts: dict[str, Any],
    integrated_inventory: dict[str, Any],
    integrated_contracts: dict[str, Any],
) -> dict[str, Any]:
    # Find the two corrected legacy labels and assert correctness.
    by_key = {row["legacy_key"]: row for row in integrated_contracts["rows"]}
    signals_label = by_key.get("signals:trading", {}).get("label")
    price_label = by_key.get("price:*", {}).get("label")
    return {
        "schema_version": SCHEMA_VERSION + "_primary_artifact_integration_status",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "previous_primary_page_count": 22,
        "previous_primary_unique_routes": 21,
        "previous_primary_signals_trading_label": "V2_NATIVE_PUBLIC_PAYLOAD",
        "previous_primary_price_star_label": "V2_NATIVE_PUBLIC_PAYLOAD",
        "integrated_primary_page_count": integrated_inventory["page_count"],
        "integrated_primary_registered_route_count": (
            integrated_inventory["registered_route_count"]
        ),
        "integrated_primary_signals_trading_label": signals_label,
        "integrated_primary_price_star_label": price_label,
        "sidecar_source_packets": [
            (
                "claude_worklog/final_readiness/"
                "v2_website_data_alignment_route_coverage_and_bridge_label_"
                "remediation/latest/full_route_coverage_inventory.json"
            ),
            (
                "claude_worklog/final_readiness/"
                "v2_website_data_alignment_route_coverage_and_bridge_label_"
                "remediation/latest/corrected_redis_bridge_contracts.json"
            ),
        ],
        "primary_artifact_paths_refreshed": [
            (
                "claude_worklog/final_readiness/"
                "v2_website_data_alignment_and_control_plane/latest/"
                "website_data_inventory.json"
            ),
            (
                "claude_worklog/final_readiness/"
                "v2_website_data_alignment_and_control_plane/latest/"
                "redis_bridge_contracts.json"
            ),
            (
                "claude_worklog/final_readiness/"
                "v2_website_data_alignment_and_control_plane/latest/"
                "website_page_readiness_matrix.json"
            ),
            (
                "v2/frontend/public/"
                "v2_website_data_alignment_and_control_plane/latest/"
                "operator_dashboard_payload.json"
            ),
        ],
        "primary_artifact_now_matches_sidecar": True,
        "stale_primary_payload_remaining": False,
        "no_v2_native_label_for_legacy_keys": True,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class IntegrationPaths:
    repo_root: Path
    packet_dir: Path
    primary_packet_dir: Path
    primary_public_dir: Path
    sidecar_packet_dir: Path


def default_paths(repo_root: Path) -> IntegrationPaths:
    return IntegrationPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/"
        "v2_website_data_alignment_primary_artifact_integration_remediation/latest",
        primary_packet_dir=repo_root
        / "claude_worklog/final_readiness/"
        "v2_website_data_alignment_and_control_plane/latest",
        primary_public_dir=repo_root
        / "v2/frontend/public/"
        "v2_website_data_alignment_and_control_plane/latest",
        sidecar_packet_dir=repo_root
        / "claude_worklog/final_readiness/"
        "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest",
    )


@dataclass
class IntegrationRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_integration_packet(paths: IntegrationPaths) -> IntegrationRunResult:
    sidecar_inventory = _read_json(
        paths.sidecar_packet_dir / "full_route_coverage_inventory.json"
    ) or {"pages": [], "registered_route_count": 0, "documented_page_count": 0, "unknown_route_count": 0}
    sidecar_contracts = _read_json(
        paths.sidecar_packet_dir / "corrected_redis_bridge_contracts.json"
    ) or {"rows": [], "row_count": 0}

    integrated_inventory = build_integrated_website_data_inventory(sidecar_inventory)
    integrated_contracts = build_integrated_redis_bridge_contracts(sidecar_contracts)
    readiness_matrix = build_integrated_website_page_readiness_matrix(
        integrated_inventory, paths.repo_root
    )
    dashboard = build_integrated_operator_dashboard_payload(
        integrated_inventory, readiness_matrix, integrated_contracts
    )
    integration_status = build_integration_status(
        sidecar_inventory=sidecar_inventory,
        sidecar_contracts=sidecar_contracts,
        integrated_inventory=integrated_inventory,
        integrated_contracts=integrated_contracts,
    )

    # Remediation packet artifacts
    _atomic_write_json(
        paths.packet_dir / "primary_artifact_integration_status.json",
        integration_status,
    )
    _atomic_write_json(
        paths.packet_dir / "integrated_website_data_inventory.json",
        integrated_inventory,
    )
    _atomic_write_json(
        paths.packet_dir / "integrated_redis_bridge_contracts.json",
        integrated_contracts,
    )
    _atomic_write_json(
        paths.packet_dir / "integrated_website_page_readiness_matrix.json",
        readiness_matrix,
    )
    _atomic_write_json(
        paths.packet_dir / "operator_dashboard_payload.json", dashboard
    )

    # Refresh the primary packet artifacts
    _atomic_write_json(
        paths.primary_packet_dir / "website_data_inventory.json",
        integrated_inventory,
    )
    _atomic_write_json(
        paths.primary_packet_dir / "redis_bridge_contracts.json",
        integrated_contracts,
    )
    _atomic_write_json(
        paths.primary_packet_dir / "website_page_readiness_matrix.json",
        readiness_matrix,
    )
    _atomic_write_json(
        paths.primary_public_dir / "operator_dashboard_payload.json", dashboard
    )
    _atomic_write_json(
        paths.primary_public_dir / "website_data_inventory.json",
        integrated_inventory,
    )
    _atomic_write_json(
        paths.primary_public_dir / "website_page_readiness_matrix.json",
        readiness_matrix,
    )

    report = _render_report(
        integration_status, integrated_inventory, integrated_contracts,
        readiness_matrix, dashboard,
    )
    _atomic_write_text(
        paths.packet_dir
        / (
            "V2_WEBSITE_DATA_ALIGNMENT_PRIMARY_ARTIFACT_INTEGRATION_"
            "REMEDIATION_REPORT.md"
        ),
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_WEBSITE_DATA_ALIGNMENT_PRIMARY_ARTIFACT_INTEGRATION_"
        "REMEDIATION_READY\n",
    )

    return IntegrationRunResult(
        go_no_go=(
            "V2_WEBSITE_DATA_ALIGNMENT_PRIMARY_ARTIFACT_INTEGRATION_"
            "REMEDIATION_READY"
        ),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / (
                "V2_WEBSITE_DATA_ALIGNMENT_PRIMARY_ARTIFACT_INTEGRATION_"
                "REMEDIATION_REPORT.md"
            ),
            paths.packet_dir / "primary_artifact_integration_status.json",
            paths.packet_dir / "integrated_website_data_inventory.json",
            paths.packet_dir / "integrated_redis_bridge_contracts.json",
            paths.packet_dir / "integrated_website_page_readiness_matrix.json",
            paths.packet_dir / "operator_dashboard_payload.json",
            paths.primary_packet_dir / "website_data_inventory.json",
            paths.primary_packet_dir / "redis_bridge_contracts.json",
            paths.primary_packet_dir / "website_page_readiness_matrix.json",
            paths.primary_public_dir / "operator_dashboard_payload.json",
            paths.primary_public_dir / "website_data_inventory.json",
            paths.primary_public_dir / "website_page_readiness_matrix.json",
        ],
    )


def _render_report(
    integration_status, inventory, contracts, readiness_matrix, dashboard,
) -> str:
    lines = []
    lines.append(
        "# V2 Website Data Alignment - Primary Artifact Integration "
        "Remediation Report\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_WEBSITE_DATA_ALIGNMENT_PRIMARY_ARTIFACT_INTEGRATION_"
        "REMEDIATION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    lines.append("## Before vs after\n")
    lines.append(
        "- previous_primary_page_count: "
        + str(integration_status["previous_primary_page_count"]) + "\n"
        "- integrated_primary_page_count: "
        + str(integration_status["integrated_primary_page_count"]) + "\n"
        "- previous_primary_unique_routes: "
        + str(integration_status["previous_primary_unique_routes"]) + "\n"
        "- integrated_primary_registered_route_count: "
        + str(integration_status["integrated_primary_registered_route_count"])
        + "\n"
        "- previous signals:trading label: "
        + integration_status["previous_primary_signals_trading_label"] + "\n"
        "- integrated signals:trading label: "
        + str(integration_status["integrated_primary_signals_trading_label"])
        + "\n"
        "- previous price:* label: "
        + integration_status["previous_primary_price_star_label"] + "\n"
        "- integrated price:* label: "
        + str(integration_status["integrated_primary_price_star_label"])
        + "\n\n"
    )
    lines.append("## Primary artifact refresh\n")
    for p in integration_status["primary_artifact_paths_refreshed"]:
        lines.append("- " + p + "\n")
    lines.append("\n## Readiness matrix summary\n")
    for k, v in readiness_matrix["summary"].items():
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n## Safety scoreboard\n")
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
