#!/usr/bin/env python3
"""Build the gen-5 dataset from the completed archive + compare to gen-4.

FINAL PASS Phase 7 step 3. Run ONLY after gen5_reconcile.py passes. Builds an
identity manifest over every rich-bound row in the gen-5 challenger archive, runs
build_serving_dataset_v2, and reports the corpus shape + a material-widening
verdict vs gen-4's 215-row Jul-22/23 corpus. Does NOT train or activate.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STATE = Path("/home/wali/ai_bot_local_data/gen5_snapshot_backfill_v1")
ARCHIVE = STATE / "challenger_archive"
OUT_DIR = STATE / "gen5_dataset"
IDENTITY = OUT_DIR / "gen5_identity.json"
REPORT = STATE / "gen5_dataset_report.json"

# gen-4 baseline (committed evidence)
GEN4 = {"rows": 215, "earliest": "2026-07-22T10:22:33Z", "latest": "2026-07-23T22:09:04Z",
        "span_days": 1.5, "timeframes": {"5m": 215}}


def main() -> int:
    from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
        iter_index_records,
        load_snapshot,
    )
    from v2.backend.app.services.prediction_serving.serving_dataset_v2 import (
        build_serving_dataset_v2,
    )

    # 1. identity manifest over rich-bound rows
    rows = []
    for ix in iter_index_records(ARCHIVE):
        sid = ix.get("snapshot_id")
        if not sid:
            continue
        rec = load_snapshot(sid, root=ARCHIVE, verify=True)
        if not isinstance(rec, dict):
            continue
        lb = rec.get("label_binding")
        if not isinstance(lb, dict) or not isinstance(lb.get("directional_cost_evidence"), dict):
            continue
        rows.append({"snapshot_id": sid, "content_sha256": rec.get("content_sha256")})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IDENTITY.write_text(json.dumps({"audit": {"admissible": len(rows)}, "rows": rows}))

    # 2. build the dataset
    dataset, manifest, parity = build_serving_dataset_v2(
        identity_manifest_path=IDENTITY, archive_root=ARCHIVE
    )
    ds_rows = dataset["rows"]
    symbols = Counter(r["symbol"] for r in ds_rows)
    timeframes = Counter(r["timeframe"] for r in ds_rows)
    actions = Counter(r["target_action"] for r in ds_rows)
    splits = Counter(r["split"] for r in ds_rows)
    times = sorted(r["decision_time"] for r in ds_rows)
    earliest, latest = (times[0], times[-1]) if times else (None, None)

    import datetime
    def _parse(t):
        return datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    span_days = round((_parse(latest) - _parse(earliest)).total_seconds() / 86400, 2) if times else 0

    total = len(ds_rows)
    materially_wider = bool(total >= GEN4["rows"] * 1.5 or span_days >= GEN4["span_days"] * 2 or len(timeframes) > 1)

    report = {
        "schema_version": "gen5_dataset_report_v1",
        "dataset_id": dataset.get("dataset_id"),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "feature_abi_sha256": manifest.get("feature_abi_sha256"),
        "total_rows": total,
        "symbols": dict(symbols.most_common()),
        "symbol_count": len(symbols),
        "timeframes": dict(timeframes),
        "class_balance": {a: actions[a] for a in ("long", "short", "hold")},
        "splits": {"train": splits["train"], "validation": splits["validation"], "holdout": splits["holdout"]},
        "earliest_decision_time": earliest,
        "latest_decision_time": latest,
        "span_days": span_days,
        "source_rejections": manifest.get("source_rejections"),
        "gen4_baseline": GEN4,
        "gen5_vs_gen4": {
            "rows_delta": total - GEN4["rows"],
            "span_days_delta": round(span_days - GEN4["span_days"], 2),
            "materially_wider": materially_wider,
            "verdict": ("MATERIALLY_WIDER_TRAIN_CHALLENGER" if materially_wider
                        else "STILL_NARROW_DO_NOT_TRAIN_ACCUMULATE_MORE"),
        },
        "paper_only": True, "live_gate": "blocked_human_only",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: report[k] for k in (
        "total_rows", "symbol_count", "timeframes", "class_balance", "splits",
        "span_days", "gen5_vs_gen4")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
