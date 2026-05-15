from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_controller():
    root = Path(__file__).resolve().parents[5]
    path = root / "claude_worklog/tools/codex_legacy_shutdown_readiness_takeover.py"
    spec = importlib.util.spec_from_file_location("codex_shutdown_takeover", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_evidence():
    return {
        "runtime_safety": {
            "final_approval_token": "absent",
            "redis_trim_approval": "absent",
            "live_gate": "blocked_human_only",
            "observed_live_gate_values": ["blocked_human_only"],
            "live_symbols": [],
            "old_redis_writes_absent": True,
            "exchange_actions_absent": True,
            "leverage_changes_absent": True,
            "margin_mode_changes_absent": True,
        },
        "git_corruption": (False, ""),
        "closure": {
            "copied_source_files_on_disk": 248,
            "binary_checkpoint_blobs_inventoried_only": 139,
            "full_runtime_manifest_valid": True,
            "genuine_unresolved_items": [],
        },
        "worker_porting": {"blockers": []},
        "risk_gateway_tests": {"missing_terms": []},
        "worker_parity_markers": {
            "v2_signal_publisher": {"pass_evidence_present": True},
            "v2_orchestrator_adapter": {"pass_evidence_present": True},
            "v2_market_ingestor_from_legacy_baseline": {"pass_evidence_present": True},
            "v2_coinank_and_liquidation_bridge_from_legacy_baseline": {"pass_evidence_present": True},
            "v2_feature_pipeline_ta_worker_from_legacy_baseline": {"pass_evidence_present": True},
            "v2_feature_pipeline_and_ta_worker_from_legacy_baseline": {"pass_evidence_present": True},
        },
        "trainer_bridge": {"blockers": []},
        "trainer_derived_acceptance": {
            "operator_acceptance_required": False,
            "native_evidence_ready": False,
        },
        "trainer_external_packages": {"missing": []},
        "paper_runtime": {
            "blockers": ["paper_realized_pnl_negative", "fills_flat_recent_window"],
        },
        "paper_shadow": {"blockers": []},
        "paper_edge": {"blockers": ["paper_shadow_profitability_proof_negative", "blocked_intents_present"]},
        "paper_post_filter": {
            "historical_negative_pnl_isolated": True,
            "post_filter_realized_pnl_delta_usdt": 0.0,
            "post_filter_safety_classification": "POST_FILTER_NO_UNSAFE_FILLS",
            "post_filter_simulated_fills": 0,
            "no_unsafe_fills": True,
            "positive_edge_proven": False,
        },
        "trade_permission": {
            "blockers": ["trade_permission_readonly_unknown"],
            "paper_only_operator_decision_required": True,
        },
        "symbol_universe": {"blockers": []},
        "public_freshness": {"stale_count": 0},
        "service_liveness": {"inactive_units": []},
        "observatory": {
            "go_no_go": "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY",
            "legacy_signal_health": "CURRENT",
            "legacy_signal_comparison_classification": "BOTH_BLOCK",
            "v2_decision_quality": "PENDING_OUTCOME",
            "paper_edge_status": "POST_FILTER_NO_UNSAFE_FILLS",
            "edge_action_required": False,
            "trainer_parity_status": "FULL_LEGACY_PARITY_READY",
            "trainer_parity_gaps": [],
            "trainer_action_required": False,
        },
    }


def test_post_filter_historical_pnl_is_live_only_while_edge_stays_blocking():
    controller = _load_controller()
    blockers = controller.collect_blockers(_base_evidence())
    pnl_blockers = [item for item in blockers if item["id"] == "PAPER_PNL_NEGATIVE_BLOCKS_CANARY"]
    edge_blockers = [item for item in blockers if item["id"] == "PAPER_EDGE_UNPROVEN"]

    assert pnl_blockers
    assert all(item["category"] == "P2_LIVE_ONLY_BLOCKED" for item in pnl_blockers)
    assert edge_blockers
    assert any(item["category"] == "P0_SHUTDOWN_BLOCKER" for item in edge_blockers)
    assert any("positive edge is not proven" in item["evidence"] for item in edge_blockers)


def test_trade_permission_unknown_requires_operator_decision_for_paper_only():
    controller = _load_controller()
    blockers = controller.collect_blockers(_base_evidence())
    trade = [item for item in blockers if item["id"] == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"]

    assert len(trade) == 1
    assert trade[0]["category"] == "OPERATOR_DECISION_REQUIRED"
    assert "blocks live/canary" in trade[0]["evidence"]


def test_trainer_derived_acceptance_packet_turns_lineage_into_operator_decision():
    controller = _load_controller()
    evidence = _base_evidence()
    evidence["trainer_bridge"] = {
        "blockers": [
            "legacy_log_confidence_calibration_derived",
            "legacy_log_feature_attribution_incomplete",
            "legacy_log_feature_snapshot_id_derived",
        ]
    }
    evidence["trainer_derived_acceptance"] = {
        "operator_acceptance_required": True,
        "native_evidence_ready": False,
        "packet_path": "claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest/TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md",
        "go_no_go": "V2_TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_REQUIRED",
    }

    blockers = controller.collect_blockers(evidence)
    trainer = [
        item
        for item in blockers
        if item["id"]
        in {
            "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED",
            "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE",
            "LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED",
        }
    ]

    assert len(trainer) == 3
    assert all(item["category"] == "OPERATOR_DECISION_REQUIRED" for item in trainer)
    assert all("decision_packet" in item for item in trainer)
    assert all("native trainer evidence was not found" in item["evidence"] for item in trainer)


def test_next_action_surfaces_operator_decision_when_no_dispatchable_task_remains(monkeypatch):
    controller = _load_controller()
    blockers = [
        {
            "id": "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED",
            "category": "OPERATOR_DECISION_REQUIRED",
            "evidence": "trainer derived evidence requires operator decision",
            "decision_packet": "acceptance.md",
            "remediation_task_id": "claude_v2_trainer_derived_evidence_acceptance_or_native_parity_packet",
        }
    ]

    monkeypatch.setattr(controller, "required_outputs_exist", lambda descriptor: True)
    monkeypatch.setattr(controller, "task_effective_status", lambda task_id: "completed")
    monkeypatch.setattr(controller, "codex_passed", lambda task_id: True)
    monkeypatch.setattr(controller, "codex_failed", lambda task_id: False)

    action = controller.select_next_action(blockers, dry_run=True)

    assert action["kind"] == "operator_decision_required"
    assert action["blocker_id"] == "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED"
    assert action["decision_packet"] == "acceptance.md"


def test_observatory_edge_pending_dispatches_paper_edge_recovery(monkeypatch):
    controller = _load_controller()
    evidence = _base_evidence()
    evidence["observatory"] = {
        "go_no_go": "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY",
        "legacy_signal_health": "STALE",
        "legacy_signal_comparison_classification": "MISSING_EVIDENCE_CANNOT_COMPARE",
        "v2_decision_quality": "EDGE_PENDING_INSUFFICIENT_SAMPLE",
        "paper_edge_status": "EDGE_PENDING",
        "edge_action_required": True,
        "trainer_parity_status": "FULL_LEGACY_PARITY_READY",
        "trainer_parity_gaps": [],
        "trainer_action_required": False,
    }
    monkeypatch.setattr(
        controller,
        "codex_passed",
        lambda task_id: task_id != controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    blockers = controller.collect_blockers(evidence)

    assert any(item["id"] == "OBSERVATORY_PAPER_EDGE_RECOVERY_REQUIRED" for item in blockers)
    assert any(
        item.get("remediation_task_id") == controller.PAPER_EDGE_RECOVERY_TASK_ID
        for item in blockers
    )

    monkeypatch.setattr(controller, "required_outputs_exist", lambda descriptor: False)
    monkeypatch.setattr(controller, "task_effective_status", lambda task_id: "pending")
    monkeypatch.setattr(controller, "write_task_descriptors", lambda task_ids: [])

    action = controller.select_next_action(blockers, dry_run=True)

    assert action["kind"] == "dispatch_claude_remediation"
    assert action["task_id"] == controller.PAPER_EDGE_RECOVERY_TASK_ID


def test_failed_paper_edge_review_requeues_paper_edge_implementation(monkeypatch):
    controller = _load_controller()
    blockers = [
        {
            "id": "OBSERVATORY_PAPER_EDGE_RECOVERY_REQUIRED",
            "category": "P0_SHUTDOWN_BLOCKER",
            "evidence": "paper edge recovery remains required",
            "remediation_task_id": controller.PAPER_EDGE_RECOVERY_TASK_ID,
        }
    ]

    monkeypatch.setattr(controller, "required_outputs_exist", lambda descriptor: True)
    monkeypatch.setattr(controller, "task_effective_status", lambda task_id: "completed")
    monkeypatch.setattr(
        controller,
        "codex_passed",
        lambda task_id: task_id != controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    monkeypatch.setattr(
        controller,
        "codex_failed",
        lambda task_id: task_id == controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    monkeypatch.setattr(controller, "current_task_running", lambda task_id: {})
    monkeypatch.setattr(controller, "write_task_descriptors", lambda task_ids: [])
    pending_calls = []
    monkeypatch.setattr(
        controller,
        "set_task_pending",
        lambda task_id, force=False: pending_calls.append((task_id, force)),
    )

    action = controller.select_next_action(blockers, dry_run=False)

    assert action["kind"] == "dispatch_claude_remediation"
    assert action["task_id"] == controller.PAPER_EDGE_RECOVERY_TASK_ID
    assert "Codex review" in action["follow_up"]
    assert pending_calls == [(controller.PAPER_EDGE_RECOVERY_TASK_ID, True)]


def test_failed_paper_edge_review_waits_when_remediation_already_running(monkeypatch):
    controller = _load_controller()
    blockers = [
        {
            "id": "OBSERVATORY_PAPER_EDGE_RECOVERY_REQUIRED",
            "category": "P0_SHUTDOWN_BLOCKER",
            "evidence": "paper edge recovery remains required",
            "remediation_task_id": controller.PAPER_EDGE_RECOVERY_TASK_ID,
        }
    ]

    monkeypatch.setattr(controller, "required_outputs_exist", lambda descriptor: True)
    monkeypatch.setattr(
        controller,
        "task_effective_status",
        lambda task_id: "running"
        if task_id == controller.PAPER_EDGE_RECOVERY_TASK_ID
        else "completed",
    )
    monkeypatch.setattr(
        controller,
        "codex_passed",
        lambda task_id: task_id != controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    monkeypatch.setattr(
        controller,
        "codex_failed",
        lambda task_id: task_id == controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    monkeypatch.setattr(controller, "current_task_running", lambda task_id: {})
    monkeypatch.setattr(controller, "task_running_stale", lambda task_id: False)
    monkeypatch.setattr(controller, "set_task_pending", lambda task_id, force=False: (_ for _ in ()).throw(AssertionError))

    action = controller.select_next_action(blockers, dry_run=False)

    assert action["kind"] == "wait_for_claude_remediation"
    assert action["task_id"] == controller.PAPER_EDGE_RECOVERY_TASK_ID
    assert "already running" in action["follow_up"]


def test_failed_paper_edge_review_waits_when_current_status_has_running_child(monkeypatch):
    controller = _load_controller()
    blockers = [
        {
            "id": "OBSERVATORY_PAPER_EDGE_RECOVERY_REQUIRED",
            "category": "P0_SHUTDOWN_BLOCKER",
            "evidence": "paper edge recovery remains required",
            "remediation_task_id": controller.PAPER_EDGE_RECOVERY_TASK_ID,
        }
    ]

    monkeypatch.setattr(controller, "required_outputs_exist", lambda descriptor: True)
    monkeypatch.setattr(controller, "task_effective_status", lambda task_id: "pending")
    monkeypatch.setattr(
        controller,
        "codex_passed",
        lambda task_id: task_id != controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    monkeypatch.setattr(
        controller,
        "codex_failed",
        lambda task_id: task_id == controller.PAPER_EDGE_RECOVERY_TASK_ID,
    )
    monkeypatch.setattr(controller, "current_task_running", lambda task_id: {"run_pid": 123})
    monkeypatch.setattr(controller, "set_task_pending", lambda task_id, force=False: (_ for _ in ()).throw(AssertionError))

    action = controller.select_next_action(blockers, dry_run=False)

    assert action["kind"] == "wait_for_claude_remediation"
    assert action["task_id"] == controller.PAPER_EDGE_RECOVERY_TASK_ID


def test_observatory_trainer_not_full_routes_to_derived_packet_after_full_task_pass(monkeypatch):
    controller = _load_controller()
    evidence = _base_evidence()
    evidence["paper_runtime"] = {"blockers": []}
    evidence["paper_edge"] = {"blockers": []}
    evidence["trade_permission"] = {"blockers": [], "paper_only_operator_decision_required": False}
    evidence["observatory"] = {
        "go_no_go": "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY",
        "legacy_signal_health": "STALE",
        "legacy_signal_comparison_classification": "MISSING_EVIDENCE_CANNOT_COMPARE",
        "v2_decision_quality": "EDGE_PENDING_INSUFFICIENT_SAMPLE",
        "paper_edge_status": "POST_FILTER_NO_UNSAFE_FILLS",
        "edge_action_required": False,
        "trainer_parity_status": "BLOCKS_LEGACY_SHUTDOWN",
        "trainer_parity_gaps": ["LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE"],
        "trainer_action_required": True,
    }
    monkeypatch.setattr(
        controller,
        "codex_passed",
        lambda task_id: task_id == "claude_port_v2_trainer_bridge_full_legacy_parity",
    )

    blockers = controller.collect_blockers(evidence)
    trainer = [
        item
        for item in blockers
        if item["id"] == "OBSERVATORY_TRAINER_FULL_PARITY_REQUIRED"
    ]

    assert len(trainer) == 1
    assert trainer[0]["remediation_task_id"] == controller.TRAINER_DERIVED_ACCEPTANCE_TASK_ID


def test_observatory_stale_legacy_signals_are_source_limited_info_only():
    controller = _load_controller()
    evidence = _base_evidence()
    evidence["observatory"] = {
        "go_no_go": "CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY",
        "legacy_signal_health": "STALE",
        "legacy_signal_comparison_classification": "MISSING_EVIDENCE_CANNOT_COMPARE",
        "v2_decision_quality": "PENDING_OUTCOME",
        "paper_edge_status": "POST_FILTER_NO_UNSAFE_FILLS",
        "edge_action_required": False,
        "trainer_parity_status": "FULL_LEGACY_PARITY_READY",
        "trainer_parity_gaps": [],
        "trainer_action_required": False,
    }

    blockers = controller.collect_blockers(evidence)
    stale = [
        item
        for item in blockers
        if item["id"] == "OBSERVATORY_LEGACY_SIGNALS_STALE_SOURCE_LIMITED"
    ]

    assert len(stale) == 1
    assert stale[0]["category"] == "INFO_ONLY"
    assert "MISSING_EVIDENCE_CANNOT_COMPARE" in stale[0]["evidence"]
