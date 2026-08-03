#!/usr/bin/env python3
"""Gen-4 identity manifest builder (fallback path).

The shards importer produces SPARSE label bindings that build_serving_dataset_v2
rejects. The build-compatible records (RICH 'profiled_training_finalized_label_
binding_v1' with directional_cost_evidence + label_target_action) already live
in the durable feature-snapshot archive. This enumerates those records, keeps
only rows that the REAL build_serving_dataset_v2._build_row admits, and emits a
gen-4 identity manifest. Read-only on the durable archive; writes only under
.local_models/."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import _build_row

DURABLE_ARCHIVE = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_archive"
)
MANIFEST = DURABLE_ARCHIVE / "manifest.jsonl"
OUT = REPO_ROOT / ".local_models/paper_provisional/gen4_identity.json"


def candidate_snapshot_ids() -> list[str]:
    # Fast prefix grep over the append-only manifest, then dedupe.
    proc = subprocess.run(
        ["grep", "-oE", r'"snapshot_id": ?"profiled[^"]*"', str(MANIFEST)],
        capture_output=True, text=True, check=True,
    )
    ids = []
    seen = set()
    for line in proc.stdout.splitlines():
        m = re.search(r'"snapshot_id": ?"(profiled[^"]*)"', line)
        if not m:
            continue
        sid = m.group(1)
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)
    return ids


def main() -> int:
    ids = candidate_snapshot_ids()
    prefixes = Counter(sid.split(":")[0].split("_v1_")[0] for sid in ids)
    print("CANDIDATES", len(ids), "by_prefix_family", dict(prefixes), flush=True)

    admissible = []
    rejections: Counter[str] = Counter()
    class_balance: Counter[str] = Counter()
    timeframe_dist: Counter[str] = Counter()
    for sid in ids:
        rec = load_snapshot(sid, root=DURABLE_ARCHIVE, verify=True)
        if not isinstance(rec, dict):
            rejections["AUTHENTICATED_ARCHIVE_RECORD_MISSING"] += 1
            continue
        identity = {
            "snapshot_id": sid,
            "content_sha256": rec.get("content_sha256"),
            "row_identity": sid,
        }
        try:
            row = _build_row(identity, rec)
        except ValueError as exc:
            rejections[str(exc)] += 1
            continue
        admissible.append({
            "snapshot_id": sid,
            "content_sha256": str(rec.get("content_sha256")),
            "row_identity": sid,
            "decision_time": row["decision_time"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "target_action": row["target_action"],
        })
        class_balance[row["target_action"]] += 1
        timeframe_dist[row["timeframe"]] += 1

    admissible.sort(key=lambda r: (r["decision_time"], r["snapshot_id"]))
    audit = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "source_archive_root": str(DURABLE_ARCHIVE),
        "candidate_count": len(ids),
        "candidate_by_prefix_family": dict(prefixes),
        "admissible_count": len(admissible),
        "class_balance": dict(class_balance),
        "timeframe_distribution": dict(timeframe_dist),
        "rejections_by_reason": dict(sorted(rejections.items())),
        "earliest_decision_time": admissible[0]["decision_time"] if admissible else None,
        "latest_decision_time": admissible[-1]["decision_time"] if admissible else None,
        "note": (
            "Fallback path: durable-archive rich-binding records "
            "(profiled_training_finalized_label_binding_v1). Shards importer "
            "produces sparse bindings that _build_row rejects."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"audit": audit, "rows": admissible}, indent=2, sort_keys=True) + "\n")
    print("AUDIT", json.dumps(audit, indent=2, sort_keys=True), flush=True)
    print("WROTE", str(OUT), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
