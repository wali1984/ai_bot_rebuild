from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.public_payload_freshness_guard import build_guard


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_guard_finds_stale_static_mock_and_hist_current_misuse(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/example/latest/payload.json",
        """
        {
          "generated_at": "2026-05-13T00:00:00Z",
          "source_paths": ["fixture"],
          "current_truth": "STATIC_PROOF_FIXTURE DESIGN_MOCK_DATA",
          "current": {"hist_position": 1},
          "live_gate": "enabled"
        }
        """,
    )

    result = build_guard(
        tmp_path,
        now=datetime(2026, 5, 13, 1, tzinfo=timezone.utc),
        stale_after_seconds=60,
    )

    assert result["result"] == "BLOCKED"
    assert "STALE_PAYLOAD" in result["findings"]
    assert "STATIC_PROOF_FIXTURE_USED_AS_CURRENT_TRUTH" in result["findings"]
    assert "DESIGN_MOCK_DATA_USED_AS_CURRENT_TRUTH" in result["findings"]
    assert "HISTORICAL_FIELD_USED_AS_CURRENT" in result["findings"]
    assert "LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY" in result["findings"]


def test_guard_can_pass_fresh_sourced_payload(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/example/latest/payload.json",
        """
        {
          "generated_at": "2026-05-13T00:00:00Z",
          "source_paths": ["runtime"],
          "live_gate": "blocked_human_only",
          "evidence_status": "EVIDENCE_PRESENT"
        }
        """,
    )

    result = build_guard(
        tmp_path,
        now=datetime(2026, 5, 13, 0, 1, tzinfo=timezone.utc),
        stale_after_seconds=120,
    )

    assert result["result"] == "PASS"
    assert result["payloads_checked"] == 1


def test_guard_accepts_worker_status_last_run_ts_and_worker_id(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/v2_worker/latest/v2_worker_status.json",
        """
        {
          "worker_id": "v2_worker",
          "last_run_ts": "2026-05-13T00:00:00Z",
          "live_gate": "blocked_human_only",
          "runtime_evidence_status": "EVIDENCE_PRESENT"
        }
        """,
    )

    result = build_guard(
        tmp_path,
        now=datetime(2026, 5, 13, 0, 1, tzinfo=timezone.utc),
        stale_after_seconds=120,
    )

    assert result["result"] == "PASS"
    assert result["payload_results"][0]["generated_at"] == "2026-05-13T00:00:00Z"


def test_guard_accepts_ready_worker_payload_with_snapshot_source_evidence(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/v2_worker/latest/v2_worker_status.json",
        """
        {
          "worker_id": "v2_worker",
          "last_run_ts": "2026-05-13T00:00:00Z",
          "live_gate": "blocked_human_only",
          "trainer_readiness": "READY",
          "last_snapshot_id": "feature_snapshot_abc",
          "source_payload_path": "binance_public_rest:BTCUSDT"
        }
        """,
    )

    result = build_guard(
        tmp_path,
        now=datetime(2026, 5, 13, 0, 1, tzinfo=timezone.utc),
        stale_after_seconds=120,
    )

    assert result["result"] == "PASS"


def test_guard_blocks_ready_worker_payload_without_evidence(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/v2_worker/latest/v2_worker_status.json",
        """
        {
          "worker_id": "v2_worker",
          "last_run_ts": "2026-05-13T00:00:00Z",
          "live_gate": "blocked_human_only",
          "trainer_readiness": "READY"
        }
        """,
    )

    result = build_guard(
        tmp_path,
        now=datetime(2026, 5, 13, 0, 1, tzinfo=timezone.utc),
        stale_after_seconds=120,
    )

    assert result["result"] == "BLOCKED"
    assert "READY_CLAIM_WITH_MISSING_EVIDENCE" in result["findings"]


def test_guard_distinguishes_profitability_proof_claim_from_pending_or_negated(tmp_path) -> None:
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/bad/latest/payload.json",
        """
        {
          "generated_at": "2026-05-13T00:00:00Z",
          "source_paths": ["runtime"],
          "live_gate": "blocked_human_only",
          "profitability_status": "paper_runtime_alive profitability proof available"
        }
        """,
    )
    _write(
        tmp_path / "v2/frontend/public/operator_runtime/good/latest/payload.json",
        """
        {
          "generated_at": "2026-05-13T00:00:00Z",
          "source_paths": ["runtime"],
          "live_gate": "blocked_human_only",
          "profitability_status": "PAPER_RUNTIME_ALIVE_BUT_6H_24H_PROFITABILITY_PROOF_PENDING",
          "review_check": "paper_runtime_alive_not_called_profitability_proof"
        }
        """,
    )

    result = build_guard(
        tmp_path,
        now=datetime(2026, 5, 13, 0, 1, tzinfo=timezone.utc),
        stale_after_seconds=120,
    )

    bad = next(item for item in result["payload_results"] if "/bad/" in item["path"])
    good = next(item for item in result["payload_results"] if "/good/" in item["path"])
    assert "PAPER_RUNTIME_ALIVE_CALLED_PROFITABILITY_PROOF" in bad["findings"]
    assert "PAPER_RUNTIME_ALIVE_CALLED_PROFITABILITY_PROOF" not in good["findings"]
