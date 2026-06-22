"""V2-owned paper trade-management runtime CLI (paper-only smoke).

Probes the trade-management modules under v2/legacy_owned_runtime/ and
emits a paper-only status payload. All exchange mutation paths route
through the fail-closed adapter.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v2.backend.app.services.v2_owned_runtime.smoke_base import (
    base_status,
    emit_status,
    ensure_v2_owned_sys_path,
    probe_imports,
    summarize_import_probes,
)
from v2.backend.app.services.v2_owned_runtime.exchange_fail_closed_adapter import (
    exchange_invariants_snapshot,
)

REPO = Path(__file__).resolve().parents[4]
PUBLIC_STATUS = REPO / "v2/frontend/public/operator_runtime/v2_owned_trade_management/latest/status.json"

MODULES = [
    "trading.stealth_stops",
    "trading.stealth_dynamic_integration",
    "trading.dynamic_adaptive_stops",
    "trading.dynamic_tp_engine",
    "trading.churn_prevention",
    "trading.fee_ratio_gate",
    "trading.exit_coordinator",
    "trading.smart_entry_gate",
    "trading.adaptive_edge_gate",
    "trading.adaptive_threshold_engine",
    "trading.depth_execution_gate",
    "trading.market_intelligence",
    "trading.market_regime_detector",
    "trading.dynamic_margin_manager",
    "trading.opportunity_tracker",
    "trading.adaptive_hedge_builder",
    "trading.dynamic_adaptive_hedge",
    "trading.hedge_context",
    "trading.hedge_intelligence_engine",
    "trading.hedge_pair_coordinator",
    "trading.leg_manager",
    "trading.lifecycle_controller",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2-owned paper trade management smoke")
    p.add_argument("--once", action="store_true")
    p.add_argument("--paper-only", action="store_true", default=True)
    p.add_argument("--out", type=Path, default=PUBLIC_STATUS)
    args = p.parse_args(argv)

    added = ensure_v2_owned_sys_path()
    probes = probe_imports(MODULES)
    probe_summary = summarize_import_probes(probes)

    status = base_status("v2_owned_trade_management")
    status.update({
        "sys_path_added": added,
        "module_count": len(MODULES),
        **probe_summary,
        "exchange_invariants": exchange_invariants_snapshot(),
        "paper_only": True,
    })
    emit_status(args.out, status)
    print(json.dumps({k: status[k] for k in ("resolved_count", "legacy_root_rejected_count", "smoke_pass")}))
    return 0 if status["smoke_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
