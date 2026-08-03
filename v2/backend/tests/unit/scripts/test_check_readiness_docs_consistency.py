from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_readiness_docs_consistency import (  # noqa: E402
    _check_history_event_ledger,
    _check_history_event_monitor_log,
)


def test_history_event_ledger_accepts_existing_timestamp_field_variants(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    history_path = docs_dir / "product-readiness-status-history.jsonl"
    rows = [
        {
            "generated_at": "2026-06-14T00:00:00-04:00",
            "event": "generated_at_event",
            "status": "IN_PROGRESS",
            "details": {
                "evidence_key": "example_evidence_key",
                "evidence_status": "PENDING",
            },
        },
        {
            "timestamp": "2026-06-15T00:00:00Z",
            "event": "timestamp_event",
            "status": "in_progress",
        },
        {
            "generated": "2026-06-14",
            "event": "generated_event",
            "status": "IN_PROGRESS",
        },
        {
            "date": "2026-06-14",
            "event": "date_event",
            "status": "IN_PROGRESS",
        },
    ]
    history_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    ledger_text = "\n".join(
        [
            "| `1` | `2026-06-14T00:00:00-04:00` | `generated_at_event` | `IN_PROGRESS` | `example_evidence_key` | `PENDING` |",
            "| `2` | `2026-06-15T00:00:00Z` | `timestamp_event` | `in_progress` | `NO_EVIDENCE_KEY` | `NO_EVIDENCE_STATUS` |",
            "| `3` | `2026-06-14` | `generated_event` | `IN_PROGRESS` | `NO_EVIDENCE_KEY` | `NO_EVIDENCE_STATUS` |",
            "| `4` | `2026-06-14` | `date_event` | `IN_PROGRESS` | `NO_EVIDENCE_KEY` | `NO_EVIDENCE_STATUS` |",
        ]
    )
    errors: list[str] = []

    _check_history_event_ledger(
        "docs/product-readiness-history-event-ledger.md",
        ledger_text,
        tmp_path,
        errors,
    )

    assert errors == []


def test_history_event_monitor_log_requires_event_slug_coverage(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    history_path = docs_dir / "product-readiness-status-history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": "2026-06-15T00:00:00Z", "event": "covered_event", "status": "IN_PROGRESS"}),
                json.dumps({"date": "2026-06-14", "event": "missing_event", "status": "IN_PROGRESS"}),
            ]
        ),
        encoding="utf-8",
    )
    errors: list[str] = []

    _check_history_event_monitor_log(
        "docs/product-readiness-monitor-log.md",
        "covered_event",
        tmp_path,
        errors,
    )

    assert errors == ["docs/product-readiness-monitor-log.md missing status-history event slug: missing_event"]
