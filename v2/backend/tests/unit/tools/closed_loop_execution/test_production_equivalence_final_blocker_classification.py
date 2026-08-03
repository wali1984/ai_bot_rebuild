"""Unit tests for the global production-equivalence final blocker classifier."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
MODULES = (
    "v2_closed_loop_lifecycle",
    "v2_current_work_filter",
    "v2_closed_loop_worker_pool",
    "v2_burndown_fail_to_remediation_mapper",
    "v2_autonomous_mission_backlog_autoseed",
    "v2_production_equivalence_final_blocker_classification",
)


@pytest.fixture
def isolated_classifier(tmp_path, monkeypatch):
    repo = tmp_path / "AI BOT REBUILD"
    (repo / "claude_worklog" / "tools").mkdir(parents=True)
    (repo / "claude_worklog" / "agent_supervisor" / "tasks").mkdir(parents=True)
    for mod in MODULES:
        (repo / "claude_worklog" / "tools" / f"{mod}.py").write_text(
            (TOOLS_DIR / f"{mod}.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    monkeypatch.syspath_prepend(str(repo / "claude_worklog" / "tools"))
    for mod in MODULES:
        sys.modules.pop(mod, None)
    loaded = {name: importlib.import_module(name) for name in MODULES}
    classifier = loaded["v2_production_equivalence_final_blocker_classification"]
    return {"repo": repo, **loaded, "classifier": classifier}


def _full_obs_payload(**over) -> dict[str, Any]:
    base = {
        "operator_required": False,
        "external_source_required_families": [],
        "operator_decision_required_families": [],
        "event_dependent_families": [],
        "conditionally_undefined_families": [],
        "go_no_go": "FULL_OBSERVATION_BUILDER_READY",
    }
    base.update(over)
    return base


def test_external_source_required_classified(isolated_classifier):
    cls = isolated_classifier["classifier"]
    payloads = {"full_observation_builder": _full_obs_payload(
        operator_required=True,
        external_source_required_families=["onchain_btc"],
    )}
    rows = cls.classify_blockers(payloads)
    assert any(r["classification"] == "EXTERNAL_SOURCE_REQUIRED" for r in rows)
    assert all(r["operator_required"] is True for r in rows if r["classification"] == "EXTERNAL_SOURCE_REQUIRED")


def test_operator_decision_required_classified(isolated_classifier):
    cls = isolated_classifier["classifier"]
    payloads = {"full_observation_builder": _full_obs_payload(
        operator_required=True,
        operator_decision_required_families=["unified_feature_family.ccxt_ohlcv"],
    )}
    rows = cls.classify_blockers(payloads)
    assert any(r["classification"] == "OPERATOR_DECISION_REQUIRED" for r in rows)


def test_event_dependent_classified(isolated_classifier):
    cls = isolated_classifier["classifier"]
    payloads = {"full_observation_builder": _full_obs_payload(
        operator_required=True,
        event_dependent_families=["liquidations"],
    )}
    rows = cls.classify_blockers(payloads)
    assert any(
        r["classification"] == "EVENT_DEPENDENT" and "liquidations" in r["requirement"]
        for r in rows
    )


def test_checkpoint_promotion_classified(isolated_classifier):
    cls = isolated_classifier["classifier"]
    payloads = {"checkpoint_promotion": {
        "go_no_go": "V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED",
        "overall_state": "CHECKPOINT_OPERATOR_REQUIRED",
    }}
    rows = cls.classify_blockers(payloads)
    assert any(
        r["blocker_id"] == "checkpoint_promotion"
        and r["classification"] == "OPERATOR_DECISION_REQUIRED"
        for r in rows
    )


def test_paper_edge_not_proven_classified(isolated_classifier):
    cls = isolated_classifier["classifier"]
    payloads = {"war_room": {
        "edge_gate_summary": {
            "edge_claimed": False,
            "edge_claim_blocked_reason": "operator_thresholds_required_and_not_set",
        },
        "evaluator_summary": {"expected_move_after_cost_bps": -3.5},
    }}
    rows = cls.classify_blockers(payloads)
    assert any(
        r["blocker_id"] == "paper_edge_not_proven"
        and r["classification"] == "EVENT_DEPENDENT"
        for r in rows
    )


def test_legacy_shutdown_classified(isolated_classifier):
    cls = isolated_classifier["classifier"]
    payloads = {"runtime_soak_production_equivalence": {
        "shutdown_blockers": [
            "LEGACY_STILL_OWNS_PRODUCTION_RUNTIME",
            "LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE",
        ],
        "go_no_go": "CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_READY",
    }}
    rows = cls.classify_blockers(payloads)
    ids = {r["blocker_id"] for r in rows}
    assert "legacy_shutdown.legacy_runtime_owner" in ids
    assert "legacy_shutdown.legacy_redis_keys_active" in ids


def test_shutdown_recommendation_never_safe_when_blockers_present(isolated_classifier):
    cls = isolated_classifier["classifier"]
    rows = [{
        "blocker_id": "any",
        "classification": "OPERATOR_DECISION_REQUIRED",
        "operator_required": True,
        "blocks_production_equivalence": True,
        "blocks_shutdown": True,
        "blocks_live": True,
        "blocks_paper_only": False,
        "requirement": "x",
    }]
    rec = cls.build_final_shutdown_recommendation(rows)
    assert rec["recommendation"] == "DO_NOT_SHUTDOWN_LEGACY"
    assert rec["shutdown_safe"] is False
    assert rec["live_ready"] is False


def test_technical_automatable_triggers_autoseed_requirement(isolated_classifier):
    cls = isolated_classifier["classifier"]
    rows = [{
        "blocker_id": "fake_auto",
        "classification": "TECHNICAL_AUTOMATABLE",
        "operator_required": False,
        "blocks_production_equivalence": False,
        "blocks_shutdown": False,
        "blocks_live": False,
        "blocks_paper_only": False,
        "requirement": "x",
    }]
    rec = cls.build_final_shutdown_recommendation(rows)
    not_invoked = {"invoked": False}
    ready, blockers = cls.evaluate_ready_gate(rows, rec, not_invoked)
    assert not ready
    assert "TECHNICAL_AUTOMATABLE_PRESENT_BUT_AUTOSEED_NOT_INVOKED" in blockers
    invoked = {"invoked": True}
    ready2, blockers2 = cls.evaluate_ready_gate(rows, rec, invoked)
    assert ready2
    assert blockers2 == []


def test_safe_to_shutdown_value_refused_when_blockers_present(isolated_classifier):
    cls = isolated_classifier["classifier"]
    rec = {"recommendation": "SAFE_TO_SHUTDOWN"}
    ready, blockers = cls.evaluate_ready_gate([], rec, {"invoked": False})
    assert not ready
    assert "INVALID_SHUTDOWN_RECOMMENDATION_VALUE" in blockers


def test_next_action_mapping_per_classification(isolated_classifier):
    cls = isolated_classifier["classifier"]
    rows = [
        {"blocker_id": "a", "classification": "EVENT_DEPENDENT", "operator_required": False,
         "requirement": "x", "blocks_production_equivalence": False, "blocks_shutdown": False,
         "blocks_live": False, "blocks_paper_only": False},
        {"blocker_id": "b", "classification": "OPERATOR_DECISION_REQUIRED", "operator_required": True,
         "requirement": "y", "blocks_production_equivalence": False, "blocks_shutdown": False,
         "blocks_live": False, "blocks_paper_only": False},
        {"blocker_id": "c", "classification": "EXTERNAL_SOURCE_REQUIRED", "operator_required": True,
         "requirement": "z", "blocks_production_equivalence": False, "blocks_shutdown": False,
         "blocks_live": False, "blocks_paper_only": False},
    ]
    actions = cls.build_next_action(rows)
    by_id = {a["blocker_id"]: a for a in actions}
    assert by_id["a"]["next_action"] == "WAIT_FOR_EVENT_DO_NOT_FABRICATE"
    assert by_id["b"]["next_action"] == "OPERATOR_DECISION_REQUIRED_NO_AUTOMATION"
    assert by_id["c"]["next_action"] == "OPERATOR_APPROVES_OR_REJECTS_EXTERNAL_SOURCE"
