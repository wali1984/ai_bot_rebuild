from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
