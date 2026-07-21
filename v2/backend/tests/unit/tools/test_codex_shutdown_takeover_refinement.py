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


def test_outcome_guard_overrides_stale_pre_outcome_post_filter_fields(tmp_path, monkeypatch):
    controller = _load_controller()
    status_path = tmp_path / "paper_edge_post_filter_observation_status.json"
    status_path.write_text(
        """
{
  "classification": "POST_FILTER_EDGE_PENDING",
  "cumulative_paper_pnl_usdt_pre_plus_post": -49.15,
  "generated_at": "2026-05-15T08:36:30Z",
  "outcome_guard_fills": 0,
  "outcome_guard_pnl_delta_usdt": 0.0,
  "outcome_guard_start_utc": "2026-05-15T08:32:56Z",
  "outcome_guard_unsafe_fills": 0,
  "post_filter_fees_usdt": 0.03,
  "post_filter_realized_pnl_delta_usdt": -0.03,
  "post_filter_safety_classification": "POST_CANARY_FILTER_HAD_ONE_SOURCE_LIMITED_UNSAFE_FILL",
  "post_filter_simulated_fills": 3,
  "post_outcome_model_guard": {
    "blocked": 2,
    "events": 2,
    "fees_usdt": 0.0,
    "fills": 0,
    "pnl_delta_usdt": 0.0,
    "safety_classification": "NO_FEE_BLEED_SHADOW_OBSERVE_ONLY",
    "unsafe_fills": 0
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(controller, "PAPER_POST_FILTER", status_path)
    monkeypatch.setattr(controller, "PAPER_LOSS_ATTRIBUTION", tmp_path / "missing_loss_attribution.json")

    evidence = controller.paper_post_filter_evidence()

    assert evidence["outcome_guard_active"] is True
    assert evidence["post_filter_safety_classification"] == "POST_FILTER_NO_UNSAFE_FILLS"
    assert evidence["post_filter_simulated_fills"] == 0
    assert evidence["post_filter_realized_pnl_delta_usdt"] == 0.0
    assert evidence["no_unsafe_fills"] is True
    assert evidence["historical_negative_pnl_isolated"] is True
    assert evidence["paper_only_interpretation"] == "POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING"


def test_newer_paper_loss_attribution_overrides_stale_no_fill_outcome_guard(tmp_path, monkeypatch):
    controller = _load_controller()
    status_path = tmp_path / "paper_edge_post_filter_observation_status.json"
    status_path.write_text(
        """
{
  "classification": "POST_FILTER_EDGE_PENDING",
  "cumulative_paper_pnl_usdt_pre_plus_post": -49.15,
  "generated_at": "2026-05-15T08:36:30Z",
  "outcome_guard_fills": 0,
  "outcome_guard_pnl_delta_usdt": 0.0,
  "outcome_guard_start_utc": "2026-05-15T08:32:56Z",
  "outcome_guard_unsafe_fills": 0,
  "post_outcome_model_guard": {
    "events": 2,
    "fees_usdt": 0.0,
    "fills": 0,
    "pnl_delta_usdt": 0.0,
    "safety_classification": "NO_FEE_BLEED_SHADOW_OBSERVE_ONLY",
    "unsafe_fills": 0
  },
  "post_filter_safety_classification": "POST_FILTER_NO_UNSAFE_FILLS"
}
""".strip(),
        encoding="utf-8",
    )
    loss_path = tmp_path / "paper_loss_attribution_status.json"
    loss_path.write_text(
        """
{
  "generated_at": "2026-05-15T09:43:55Z",
  "post_filter_event_detail": {
    "canary_profile_tightening_blocker_distribution": {
      "flip_churn_cooldown": 2
    },
    "cumulative_pnl_delta_usdt": -0.077409,
    "event_count": 1214,
    "fee_usdt": 0.04,
    "fill_count": 4
  },
  "pnl_waterfall": {
    "current_cumulative_paper_pnl_usdt": -49.197409,
    "post_filter_pnl_delta_usdt": -0.03
  },
  "post_filter_classification": {
    "classification": "POST_FILTER_EDGE_PENDING",
    "paper_edge_positive_proven": false,
    "post_filter_safety_classification": "POST_CANARY_FILTER_HAD_ONE_SOURCE_LIMITED_UNSAFE_FILL"
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(controller, "PAPER_POST_FILTER", status_path)
    monkeypatch.setattr(controller, "PAPER_LOSS_ATTRIBUTION", loss_path)

    evidence = controller.paper_post_filter_evidence()

    assert evidence["paper_loss_attribution_override_active"] is True
    assert evidence["paper_loss_attribution_generated_at"] == "2026-05-15T09:43:55Z"
    assert evidence["paper_loss_attribution_post_filter_event_delta_usdt"] == -0.077409
    assert evidence["post_filter_safety_classification"] == "POST_CANARY_FILTER_HAD_ONE_SOURCE_LIMITED_UNSAFE_FILL"
    assert evidence["post_filter_simulated_fills"] == 4
    assert evidence["post_filter_realized_pnl_delta_usdt"] == -0.03
    assert evidence["post_filter_fees_usdt"] == 0.04
    assert evidence["no_unsafe_fills"] is False
    assert evidence["historical_negative_pnl_isolated"] is False


def test_open_paper_position_is_outcome_pending_not_zero_fill_flatline(tmp_path, monkeypatch):
    controller = _load_controller()
    status_path = tmp_path / "paper_runtime_status.json"
    status_path.write_text(
        """
{
  "generated_at": "2026-05-15T09:34:30Z",
  "paper_account": {
    "open_position_count": 1,
    "realized_pnl": -49.16,
    "unrealized_pnl": 0.012538
  },
  "paper_ledger_tail": [
    {
      "ledger_action": "PAPER_POSITION_HELD",
      "fill_price": null,
      "paper_result": "POSITION_HELD_PAPER_ONLY"
    }
  ],
  "paper_position_lifecycle": {
    "status": "OPEN",
    "open_position": {
      "entry_price": 80544.50568,
      "expected_move_after_cost_bps": 8.21900593,
      "status": "OPEN"
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(controller, "PAPER_RUNTIME", status_path)

    evidence = controller.paper_runtime_evidence()

    assert "paper_position_outcome_pending" in evidence["blockers"]
    assert "current_paper_intent_blocked_or_unfilled" not in evidence["blockers"]
    assert "fills_flat_recent_window" not in evidence["blockers"]
    assert evidence["latest_paper_action"] == "PAPER_POSITION_HELD"
    assert evidence["latest_fill_price"] == 80544.50568
    assert evidence["open_position_count"] == 1


def test_trade_permission_unknown_requires_operator_decision_for_paper_only():
    controller = _load_controller()
    blockers = controller.collect_blockers(_base_evidence())
    trade = [item for item in blockers if item["id"] == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"]

    assert len(trade) == 1
    assert trade[0]["category"] == "OPERATOR_DECISION_REQUIRED"
    assert "blocks live/canary" in trade[0]["evidence"]


def test_service_liveness_never_starts_retired_or_masked_units(tmp_path, monkeypatch):
    controller = _load_controller()
    starts: list[str] = []

    monkeypatch.setattr(controller, "systemd_user_available", lambda: True)
    monkeypatch.setattr(controller, "FINAL_APPROVAL", tmp_path / "missing-live-approval")
    monkeypatch.setattr(controller, "REDIS_TRIM_APPROVAL", tmp_path / "missing-trim-approval")

    def fake_unit_state(unit: str):
        if unit == "ai-bot-v2-paper-online-runtime.service":
            return {"unit": unit, "active_state": "inactive", "enabled_state": "enabled"}
        if unit == "ai-bot-v2-trainer-bridge.service":
            return {"unit": unit, "active_state": "inactive", "enabled_state": "masked"}
        return {"unit": unit, "active_state": "active", "enabled_state": "enabled"}

    def fake_run(argv, timeout=15):
        if argv[:3] == ["systemctl", "--user", "start"]:
            starts.append(argv[3])
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(controller, "unit_state", fake_unit_state)
    monkeypatch.setattr(controller, "run", fake_run)

    status = controller.service_liveness(no_service_remediation=False)

    assert starts == []
    assert {
        (row["unit"], row["reason"])
        for row in status["remediation_skips"]
    } == {
        (
            "ai-bot-v2-paper-online-runtime.service",
            "retired_or_masked_unit_auto_start_forbidden",
        ),
        (
            "ai-bot-v2-trainer-bridge.service",
            "retired_or_masked_unit_auto_start_forbidden",
        ),
    }


def test_service_liveness_does_not_override_disabled_unit_state(tmp_path, monkeypatch):
    controller = _load_controller()
    starts: list[str] = []
    disabled = "ai-bot-v2-paper-shadow-observation.service"

    monkeypatch.setattr(controller, "systemd_user_available", lambda: True)
    monkeypatch.setattr(controller, "FINAL_APPROVAL", tmp_path / "missing-live-approval")
    monkeypatch.setattr(controller, "REDIS_TRIM_APPROVAL", tmp_path / "missing-trim-approval")

    def fake_unit_state(unit: str):
        if unit == disabled:
            return {"unit": unit, "active_state": "inactive", "enabled_state": "disabled"}
        return {"unit": unit, "active_state": "active", "enabled_state": "enabled"}

    def fake_run(argv, timeout=15):
        if argv[:3] == ["systemctl", "--user", "start"]:
            starts.append(argv[3])
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(controller, "unit_state", fake_unit_state)
    monkeypatch.setattr(controller, "run", fake_run)

    status = controller.service_liveness(no_service_remediation=False)

    assert starts == []
    assert {
        "unit": disabled,
        "action": "skip_start_if_inactive",
        "reason": "unit_not_enabled_for_auto_start",
        "enabled_state": "disabled",
    } in status["remediation_skips"]


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
