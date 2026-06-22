"""Phase 4: bridged ingestors shutdown closure emitter."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.native_ingestors import (
    classify_all_ingestors,
    ingestors_invariants_snapshot,
)

TARGET_WORKLOG = Path(
    "claude_worklog/final_readiness/core_completion_blocker_burndown/latest/v2_native_ingestors_shutdown_closure.json"
)
TARGET_PUBLIC = Path(
    "v2/frontend/public/core_completion_blocker_burndown/latest/v2_native_ingestors_shutdown_closure.json"
)


def main() -> int:
    records = classify_all_ingestors()
    closure_view = []
    any_residual_readonly_bridged = False
    for r in records:
        c = r.classification.classification
        closure_view.append(
            {
                "name": r.name,
                "legacy_path": r.legacy_path,
                "legacy_sha256": r.legacy_sha256,
                "classification": c,
                "rationale": r.classification.rationale,
                "requires_secret_env": list(r.classification.requires_secret_env),
                "public_market_data_only": r.classification.public_market_data_only,
            }
        )
        if c == "READONLY_BRIDGED":
            any_residual_readonly_bridged = True
    out = {
        "phase": "P4_BRIDGED_INGESTORS_SHUTDOWN_CLOSURE",
        "schema_version": "v2_native_ingestors_shutdown_closure_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ingestors": closure_view,
        "ingestor_count": len(closure_view),
        "any_residual_readonly_bridged": any_residual_readonly_bridged,
        "all_residuals_explicitly_classified": not any_residual_readonly_bridged,
        "invariants": ingestors_invariants_snapshot(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    body = json.dumps(out, indent=2, sort_keys=True) + "\n"
    TARGET_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    TARGET_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    TARGET_WORKLOG.write_text(body)
    TARGET_PUBLIC.write_text(body)
    print(
        "ingestor_count",
        len(closure_view),
        "any_residual_readonly_bridged",
        any_residual_readonly_bridged,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
