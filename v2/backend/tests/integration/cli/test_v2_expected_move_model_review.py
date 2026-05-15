from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.services.expected_move_model_review.service import (
    ExpectedMoveModelReviewService,
    LIVE_GATE_STATUS,
    REVIEW_GO_NO_GO_STRICT,
    REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND,
)


def _write_payload(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_safety_invariants_pass_for_clean_payload() -> None:
    payload = {
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "go_no_go": REVIEW_GO_NO_GO_STRICT,
    }
    result = ExpectedMoveModelReviewService.assert_safety_invariants(payload)
    assert result["safe"] is True
    assert result["violations"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("live_gate", "live"),
        ("live_symbols", ["BTCUSDT"]),
        ("approves_live", True),
        ("approves_canary", True),
        ("approves_legacy_shutdown", True),
    ],
)
def test_safety_invariants_flag_violations(field: str, value: object) -> None:
    payload = {
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "go_no_go": REVIEW_GO_NO_GO_STRICT,
    }
    payload[field] = value
    result = ExpectedMoveModelReviewService.assert_safety_invariants(payload)
    assert result["safe"] is False
    assert len(result["violations"]) >= 1


def test_unknown_go_no_go_is_flagged() -> None:
    payload = {
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "go_no_go": "MADE_UP_VALUE",
    }
    result = ExpectedMoveModelReviewService.assert_safety_invariants(payload)
    assert result["safe"] is False
    assert any("go_no_go_invalid" in v for v in result["violations"])


def test_summarize_with_real_payload(tmp_path: Path) -> None:
    payload = {
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "go_no_go": REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND,
        "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
        "edge_status": "EDGE_PENDING_MODEL_REVIEW_REQUIRED",
        "false_block_count": 12,
        "false_block_rate": 0.4,
        "no_trade_correct_count": 18,
        "no_trade_correct_rate": 0.6,
        "observations_total": 30,
        "completed_observations": 30,
        "pending_observations": 0,
        "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
        "trainer_remaining_parity_gaps": ["LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED"],
        "paper_symbols": ["BTCUSDT"],
        "best_strict_replay_row": {"min_expected_move_after_cost_bps": 6},
    }
    payload_path = tmp_path / "operator_dashboard_payload.json"
    _write_payload(payload_path, payload)
    fb_path = tmp_path / "false_block_audit.json"
    _write_payload(fb_path, {"sample_size": 30})
    th_path = tmp_path / "threshold_replay_results.json"
    _write_payload(th_path, {"rows": []})

    svc = ExpectedMoveModelReviewService(
        payload_path=payload_path,
        false_block_audit_path=fb_path,
        threshold_replay_path=th_path,
    )
    summary = svc.summarize()
    assert summary["payload_present"] is True
    assert summary["safety"]["safe"] is True
    assert summary["go_no_go"] == REVIEW_GO_NO_GO_BLOCKED_EDGE_NOT_FOUND
    assert summary["live_gate"] == LIVE_GATE_STATUS
    assert summary["live_symbols"] == []
    assert summary["approves_live"] is False
    assert summary["approves_canary"] is False
    assert summary["approves_legacy_shutdown"] is False


def test_summarize_handles_missing_payload(tmp_path: Path) -> None:
    svc = ExpectedMoveModelReviewService(
        payload_path=tmp_path / "missing.json",
        false_block_audit_path=tmp_path / "missing_fb.json",
        threshold_replay_path=tmp_path / "missing_th.json",
    )
    summary = svc.summarize()
    assert summary["payload_present"] is False
    assert summary["go_no_go"] is None
    assert summary["live_gate"] == LIVE_GATE_STATUS
    assert summary["live_symbols"] == []
