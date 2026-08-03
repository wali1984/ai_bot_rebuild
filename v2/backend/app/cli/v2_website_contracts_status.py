"""V2 Website Rebuild — Phase 1 page-contracts status emitter.

Walks every declared page contract, checks the freshness of each
required and optional payload, derives the effective placeholder state,
and writes the canonical website-contracts status payload under the
worklog directory and the public frontend mirror.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.website.page_contracts import (  # noqa: E402
    DEFAULT_SAFETY_PINS,
    build_contracts_status,
    required_routes,
)

WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_website_rebuild_phase_1"
    / "latest"
)
PUBLIC_DIR_CONTRACTS = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_website_contracts" / "latest"
)
PUBLIC_DIR_PHASE_1 = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_website_rebuild_phase_1" / "latest"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run(*, dry_run: bool = False) -> dict[str, Any]:
    contracts = build_contracts_status()
    operator_dashboard = {
        "schema_version": "v2_website_contracts_operator_dashboard_v1",
        "generated_at": _utc_iso(),
        "page_count": contracts["page_count"],
        "route_count": contracts["route_count"],
        "audience_counts": contracts["audience_counts"],
        "placeholder_state_counts": contracts["placeholder_state_counts"],
        "required_routes": required_routes(),
        "route_reconciliation": contracts["route_reconciliation"],
        "safety_pins": list(DEFAULT_SAFETY_PINS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_live_or_order_or_shutdown_or_adopt_symbol_controls_in_phase_1": True,
    }
    if not dry_run:
        _write(WORKLOG_DIR / "website_page_contracts.json", contracts)
        _write(WORKLOG_DIR / "website_rebuild_phase_1_status.json", {
            "schema_version": "v2_website_rebuild_phase_1_status_v2",
            "generated_utc": _utc_iso(),
            "go_no_go": "V2_WEBSITE_REBUILD_PHASE_1_STRUCTURE_AND_DATA_CONTRACTS_READY",
            "scope": "website_page_structure_and_data_contracts_only",
            "page_count": contracts["page_count"],
            "route_count": contracts["route_count"],
            "audience_counts": contracts["audience_counts"],
            "placeholder_state_counts": contracts["placeholder_state_counts"],
            "route_reconciliation": contracts["route_reconciliation"],
            "frontend_must_not_read_redis_directly": True,
            "did_not_remove_admin_report_center_route": "/admin/report-center" in required_routes(),
            "did_not_create_live_or_order_or_shutdown_or_adopt_symbol_controls": True,
            "did_not_modify_legacy_bot": True,
            "did_not_stop_v2_runtime": True,
            "did_not_stop_report_center_indexer": True,
            "did_not_write_old_redis": True,
            "did_not_call_exchange": True,
            "did_not_expose_raw_api_keys": True,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        })
        _write(PUBLIC_DIR_CONTRACTS / "operator_dashboard_payload.json", operator_dashboard)
        _write(PUBLIC_DIR_CONTRACTS / "website_page_contracts.json", contracts)
        _write(PUBLIC_DIR_PHASE_1 / "operator_dashboard_payload.json", operator_dashboard)
        _write(PUBLIC_DIR_PHASE_1 / "website_page_contracts.json", contracts)
    return contracts


def main() -> int:
    p = argparse.ArgumentParser(prog="v2_website_contracts_status")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    contracts = run(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(contracts, indent=2, sort_keys=True, default=str))
    else:
        print(
            json.dumps(
                {
                    "generated_at": contracts["generated_at"],
                    "page_count": contracts["page_count"],
                    "audience_counts": contracts["audience_counts"],
                    "placeholder_state_counts": contracts["placeholder_state_counts"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
