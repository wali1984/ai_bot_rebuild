from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_observatory():
    root = Path(__file__).resolve().parents[5]
    path = root / "claude_worklog/tools/codex_legacy_v2_realtime_decision_observatory.py"
    spec = importlib.util.spec_from_file_location("codex_realtime_observatory", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_observatory_routes_shadow_outcome_status_to_recommender(monkeypatch) -> None:
    observatory = _load_observatory()
    shadow_status = {
        "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
        "false_block_count": 15,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    shadow_learning_status = {
        "go_no_go": "SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    captured: dict[str, Any] = {}

    def load_first(paths: list[Path]) -> dict[str, Any]:
        if any("paper_shadow_outcome_observer_status.json" in str(path) for path in paths):
            return shadow_status
        if any("paper_shadow_outcome_learning" in str(path) for path in paths):
            return shadow_learning_status
        if any("current_recommendation.json" in str(path) for path in paths):
            return {"current_recommendation": "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE"}
        return {}

    def recommendations(**kwargs: Any) -> dict[str, Any]:
        captured["shadow_outcome_status"] = kwargs["shadow_outcome_status"]
        captured["shadow_learning_status"] = kwargs["shadow_learning_status"]
        return {
            "generated_at": "2026-05-15T00:00:00Z",
            "next_tasks": [
                {
                    "task_id": "claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks",
                    "priority": "P0",
                    "reason": "shadow false blocks require model review",
                    "required_result": "keep strict fill gate and improve expected-move evidence",
                }
            ],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        }

    monkeypatch.setattr(observatory, "_load_first", load_first)
    monkeypatch.setattr(
        observatory,
        "build_legacy_runtime_observer_status",
        lambda: {
            "ingestor_freshness": {"state": "STALE"},
            "legacy_trainer_process_state": {"state": "RUNNING_READONLY_OBSERVED"},
            "signal_log": {"freshness": {"state": "STALE"}},
            "legacy_trader_process_state": {"state": "NOT_OBSERVED"},
        },
    )
    monkeypatch.setattr(
        observatory,
        "build_legacy_v2_decision_comparator_status",
        lambda **_: {"legacy_v2_agreement_status": "MISSING_EVIDENCE_CANNOT_COMPARE"},
    )
    monkeypatch.setattr(
        observatory,
        "build_legacy_signal_outcome_observer_status",
        lambda **_: {"outcome_status": "OUTCOME_PENDING_SOURCE_LIMITED"},
    )
    monkeypatch.setattr(
        observatory,
        "build_decision_quality_scoreboard_status",
        lambda **_: {
            "primary_metric_status": "EDGE_PENDING_INSUFFICIENT_SAMPLE",
            "after_cost_accuracy": "PENDING_OUTCOME",
            "no_trade_correct_rate": "PENDING_OUTCOME",
        },
    )
    monkeypatch.setattr(observatory, "build_decision_improvement_recommendations", recommendations)

    dashboard = observatory.run_once(dry_run=True)

    assert captured["shadow_outcome_status"] == shadow_status
    assert captured["shadow_learning_status"] == shadow_learning_status
    assert dashboard["paper_shadow_false_block_count"] == 15
    assert (
        dashboard["paper_shadow_outcome_observer_status"]
        == "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED"
    )
    assert dashboard["live_gate"] == "blocked_human_only"
    assert dashboard["live_symbols"] == []
