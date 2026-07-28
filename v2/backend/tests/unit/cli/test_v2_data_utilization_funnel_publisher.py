from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.cli.v2_data_utilization_funnel_publisher import (
    DataUtilizationCollectorError,
    _candidate_profile,
)


def _archive_row(candidate_id: str, decision_time_ms: int, *, matured: bool) -> dict:
    return {
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "record": {
            "decision": {
                "candidate_id": candidate_id,
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "decision_time_ms": decision_time_ms,
            },
            "matured_labels": {"matured": True} if matured else None,
        },
    }


def _status(path: Path) -> dict:
    return {
        "archive": {
            "archive_path": str(path),
            "row_count": 2,
            "candidate_count": 2,
            "matured_revision_count": 1,
            "verified": True,
            "invalid_row_count": 0,
            "duplicate_archive_record_count": 0,
            "terminal_chain_sha256": "a" * 64,
        },
        "maturation": {
            "unmatured_candidate_count": 1,
            "pending_reason_counts": {},
            "unexplained_maturation_drops": 0,
            "counterfactual_counts_as_paper_profit": False,
        },
    }


def test_candidate_profile_streams_archive_and_computes_exact_overlap(tmp_path: Path):
    path = tmp_path / "archive.jsonl"
    rows = [
        _archive_row("one", 1_000, matured=True),
        _archive_row("two", 2_000, matured=False),
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    profile = _candidate_profile(
        _status(path),
        {("BTCUSDT", "5m", 1_000)},
    )
    assert profile["candidate_outcome_rows"] == 2
    assert profile["matured_candidate_outcome_rows"] == 1
    assert profile["gen5_exact_identity_overlap_rows"] == 1
    assert profile["pending_reasons"] == {"HORIZON_NOT_YET_DUE": 1}
    assert profile["archive_verified"] is True


def test_candidate_profile_rejects_live_authority(tmp_path: Path):
    path = tmp_path / "archive.jsonl"
    row = _archive_row("one", 1_000, matured=True)
    row["routes_to_live"] = True
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    status = _status(path)
    status["archive"].update(
        row_count=1,
        candidate_count=1,
        matured_revision_count=1,
    )
    status["maturation"]["unmatured_candidate_count"] = 0
    with pytest.raises(DataUtilizationCollectorError, match="AUTHORITY_INVALID"):
        _candidate_profile(status, set())


def test_candidate_profile_rejects_conflicting_revision_identity(tmp_path: Path):
    path = tmp_path / "archive.jsonl"
    rows = [
        _archive_row("same", 1_000, matured=False),
        _archive_row("same", 2_000, matured=True),
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    status = _status(path)
    status["archive"]["candidate_count"] = 1
    with pytest.raises(DataUtilizationCollectorError, match="IDENTITY_CONFLICT"):
        _candidate_profile(status, set())
