"""V2 legacy log intelligence observer CLI (read-only)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from v2.backend.app.services.legacy_log_intelligence import (
    discover_legacy_sources,
    enrich_comparison,
    observe_once,
    remediation_hints_from_summary,
)

WORKLOG_DIR = Path("claude_worklog/final_readiness/v2_legacy_log_intelligence/latest")
PUBLIC_DIR = Path("v2/frontend/public/operator_runtime/legacy_log_intelligence/latest")
COMPARATOR_PATH = Path(
    "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json"
)
ENRICHED_WORKLOG = Path(
    "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/legacy_log_enriched_comparison.json"
)
ENRICHED_PUBLIC = Path(
    "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/legacy_log_enriched_comparison.json"
)
DISCOVERY_PATH = WORKLOG_DIR / "legacy_log_source_discovery.json"
STATUS_PATH = PUBLIC_DIR / "legacy_log_intelligence_status.json"
STATUS_WORKLOG = WORKLOG_DIR / "legacy_log_intelligence_status.json"
HINTS_PATH = WORKLOG_DIR / "remediation_hints.jsonl"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _append_jsonl(path: Path, items: list[dict]) -> int:
    if not items:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for item in items:
            fh.write(json.dumps(item, sort_keys=True) + "\n")
    return len(items)


def run_once() -> dict:
    discovery = discover_legacy_sources()
    _write_json(DISCOVERY_PATH, discovery)
    observation = observe_once()
    comparison = _load_json(COMPARATOR_PATH)
    enriched = enrich_comparison(observation, comparison)
    _write_json(ENRICHED_WORKLOG, enriched)
    _write_json(ENRICHED_PUBLIC, enriched)
    hints = remediation_hints_from_summary(observation, enriched)
    appended = _append_jsonl(HINTS_PATH, hints)
    out = dict(observation)
    out["legacy_log_enriched_comparison_path"] = str(ENRICHED_PUBLIC)
    out["remediation_hints_count"] = appended
    out["latest_remediation_hints"] = hints[:5]
    _write_json(STATUS_PATH, out)
    _write_json(STATUS_WORKLOG, out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_legacy_log_intelligence_observer")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            out = run_once()
            print(json.dumps({
                "trainer_present": out["trainer_log_summary"].get("source_path") is not None,
                "orchestrator_present": out["orchestrator_log_summary"].get("source_path") is not None,
                "monitor_script_count": len(out.get("monitor_scripts_summary", [])),
                "remediation_hints_count": out.get("remediation_hints_count", 0),
            }))
            time.sleep(max(15, int(args.interval_seconds)))
    out = run_once()
    print(json.dumps({
        "trainer_present": out["trainer_log_summary"].get("source_path") is not None,
        "orchestrator_present": out["orchestrator_log_summary"].get("source_path") is not None,
        "monitor_script_count": len(out.get("monitor_scripts_summary", [])),
        "remediation_hints_count": out.get("remediation_hints_count", 0),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
