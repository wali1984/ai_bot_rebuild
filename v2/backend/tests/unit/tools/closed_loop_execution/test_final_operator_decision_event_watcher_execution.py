"""Tests for the final operator decision/event watcher execution packet."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"


def _load_module():
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        sys.modules.pop("v2_final_operator_decision_and_event_watcher_execution", None)
        return importlib.import_module("v2_final_operator_decision_and_event_watcher_execution")
    finally:
        try:
            sys.path.remove(str(TOOLS_DIR))
        except ValueError:
            pass


def test_operator_decision_center_never_auto_accepts() -> None:
    mod = _load_module()
    center, md = mod.build_operator_decision_center(
        {
            "items": [
                {
                    "blocker_id": "checkpoint_promotion",
                    "current_risk": "checkpoint gate blocks shutdown",
                    "recommended_conservative_default": "option_C_defer_and_keep_legacy_running",
                }
            ]
        }
    )
    assert center["operator_decision_count"] == 1
    assert center["operator_accepted_count"] == 0
    assert center["creates_approval_tokens"] is False
    assert center["decisions"][0]["operator_accepted"] is False
    assert center["decisions"][0]["operator_selected_option"] is None
    assert "operator_accepted=false" in md


def test_external_source_status_exposes_names_not_values(monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("TOKENMETRICS_API_KEY", "raw-secret-value-must-not-appear")
    status = mod.build_external_execution(
        {
            "items": [
                {
                    "blocker_id": "full_observation_builder.external_sources",
                    "source_families": ["unified_feature_family.token_metrics"],
                    "source_requirement": "operator decision required",
                }
            ]
        }
    )
    rendered = json.dumps(status)
    assert "TOKENMETRICS_API_KEY" in rendered
    assert "raw-secret-value-must-not-appear" not in rendered
    assert status["raw_key_values_exposed"] is False
    assert status["raw_values_read"] is False


def test_final_recommendation_blocks_when_external_or_event_unresolved() -> None:
    mod = _load_module()
    recommendation = mod.build_final_recommendation(
        {
            "decisions": [
                {"blocker_id": "risk_caps_canary_hard_gates_unset", "operator_accepted": False}
            ]
        },
        {
            "items": [
                {
                    "blocker_id": "full_observation_builder.external_sources",
                    "classification": "SOURCE_MISSING_KEY_OPERATOR_REQUIRED",
                }
            ]
        },
        {
            "watchers": [
                {"blocker_id": "paper_edge_not_proven", "completed": False}
            ]
        },
    )
    assert recommendation["final_recommendation"] == (
        "BLOCK_LEGACY_SHUTDOWN_PRODUCTION_EQUIVALENCE_INCOMPLETE"
    )
    assert recommendation["shutdown_safe"] is False
    assert recommendation["live_ready"] is False
