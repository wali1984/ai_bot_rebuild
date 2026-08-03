"""V2-owned monitoring runtime CLI (smoke / one-shot only)."""
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

REPO = Path(__file__).resolve().parents[4]
PUBLIC_STATUS = REPO / "v2/frontend/public/operator_runtime/v2_owned_monitoring/latest/status.json"

MODULES = [
    "telegram_alerts",
    "monitoring.oom_monitor",
    "monitoring.deep_troubleshooter",
    "monitoring.live_system_auditor",
    "monitoring.regression_alarms",
    "scripts.monitor_trainer_predictions",
    "scripts.validate_symbol_universe_data",
    "scripts.paralysis_detectors",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2-owned monitoring smoke")
    p.add_argument("--once", action="store_true")
    p.add_argument("--out", type=Path, default=PUBLIC_STATUS)
    args = p.parse_args(argv)

    added = ensure_v2_owned_sys_path()
    probes = probe_imports(MODULES)
    probe_summary = summarize_import_probes(probes)

    status = base_status("v2_owned_monitoring")
    status.update({
        "sys_path_added": added,
        "module_count": len(MODULES),
        **probe_summary,
    })
    emit_status(args.out, status)
    print(json.dumps({k: status[k] for k in ("resolved_count", "legacy_root_rejected_count", "smoke_pass")}))
    return 0 if status["smoke_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
