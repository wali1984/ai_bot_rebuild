"""Tests for the V2 native-runtime bridge-exit migration planner."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.bridge_exit.native_runtime_bridge_exit import (
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    V2_NATIVE_ACTIVE_SYMBOLS,
    build_automation_integration_status,
    build_bridge_dependency_inventory,
    build_dynamic_symbol_universe_migration_status,
    build_first_batch_task_dispatch_status,
    build_next_20_ingestor_tasks,
    build_operator_dashboard_payload,
    build_v2_dynamic_paper_trading_plan,
    build_v2_enterprise_website_parallel_lane_plan,
    build_v2_native_ingestor_migration_plan,
    build_v2_trainer_bridge_exit_plan,
    default_paths,
    run_bridge_exit_packet,
)


# ---------------------------------------------------------------------------
# Phase-specific
# ---------------------------------------------------------------------------


def test_bridge_dependency_inventory_lists_20_lanes_and_blocks_production():
    inv = build_bridge_dependency_inventory()
    assert inv["live_gate"] == LIVE_GATE_BLOCKED
    assert inv["approves_live"] is False
    assert inv["lane_total"] == 20
    lane_ids = {l["lane_id"] for l in inv["lanes"]}
    for required in (
        "market_prices",
        "ohlcv",
        "orderbook",
        "liquidation",
        "funding",
        "open_interest",
        "coinank",
        "coinapi",
        "kucoin",
        "ta_indicators",
        "unified_features",
        "trainer_predictions",
        "risk_decisions",
        "orchestrator_decisions",
        "paper_intents",
        "paper_ledger",
        "position_history",
        "alt_data",
        "symbol_universe",
        "website_pages",
    ):
        assert required in lane_ids, required


def test_symbol_universe_migration_reports_correct_missing_count():
    status = build_dynamic_symbol_universe_migration_status()
    assert status["legacy_symbol_count"] == len(KNOWN_UNIVERSE)
    assert status["v2_native_symbol_count"] == len(V2_NATIVE_ACTIVE_SYMBOLS)
    assert status["missing_v2_symbol_count"] == (
        len(KNOWN_UNIVERSE) - len(V2_NATIVE_ACTIVE_SYMBOLS)
    )
    # Planner must never mutate operational rosters.
    assert status["live_symbols"] == []
    assert status["live_symbols_unchanged"] is True
    assert status["paper_symbols_unchanged_pending_governance"] is True
    assert status["training_symbols_unchanged_pending_governance"] is True
    # Currently active symbols all marked V2_NATIVE in onboarding matrix.
    for sym in V2_NATIVE_ACTIVE_SYMBOLS:
        per = status["per_symbol_onboarding_status"][sym]
        assert all(v == "V2_NATIVE" for v in per.values()), per


def test_ingestor_migration_plan_writes_only_v2_namespace():
    plan = build_v2_native_ingestor_migration_plan()
    assert plan["v2_writes_only_v2_namespace"] is True
    for fam in plan["ingestor_families"]:
        for key in fam["v2_native_target_keys"]:
            assert key.startswith("v2:"), (fam["family"], key)


def test_next_20_ingestor_tasks_carries_required_first_batch_ids():
    tasks = build_next_20_ingestor_tasks()
    ids = {t["task_id"] for t in tasks["tasks"]}
    required = {
        "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
        "v2_native_binance_orderbook_dynamic_symbol_ingestor",
        "v2_native_feature_pipeline_dynamic_symbol_expansion",
        "v2_native_trainer_dataset_builder_from_replay_and_features",
        "v2_trainer_bridge_exit_prediction_publisher_contract",
        "website_enterprise_terminal_layout_phase_1",
    }
    assert required.issubset(ids), required - ids
    # Every task must declare forbidden actions and a writes_only allow-list.
    for t in tasks["tasks"]:
        assert "forbidden_actions" in t and t["forbidden_actions"]
        assert "writes_only" in t
        for key in t["writes_only"]:
            assert key.startswith("v2:") or key.startswith("claude_worklog/"), key


def test_trainer_bridge_exit_plan_blocks_checkpoint_parity_claims():
    plan = build_v2_trainer_bridge_exit_plan()
    assert plan["no_checkpoint_compatibility_claim"] is True
    assert plan["no_policy_architecture_parity_claim"] is True
    assert plan["no_legacy_checkpoint_deserialization_in_control_plane"] is True
    assert any(
        "trainer_source_eq_V2_NATIVE" in cond
        for cond in plan["bridge_retirement_conditions"]
    )


def test_paper_trading_plan_does_not_enable_any_new_symbol():
    plan = build_v2_dynamic_paper_trading_plan()
    assert plan["live_symbols"] == []
    assert plan["planner_does_not_enable_any_new_paper_symbol"] is True
    for sym, cap in plan["per_symbol_capability_matrix"].items():
        assert cap["paper_enabled_candidate"] is False


def test_website_plan_does_not_replace_migration_and_bans_controls():
    plan = build_v2_enterprise_website_parallel_lane_plan()
    assert plan["does_not_replace_migration_work"] is True
    layout = plan["enterprise_terminal_layout"]
    assert layout["symbol_watchlist"]["no_adopt_button"] is True
    assert layout["tradingview_workspace"]["no_order_buttons"] is True
    # 9 bottom dock tabs as specified.
    assert len(layout["bottom_dock_tabs"]) == 9


def test_automation_integration_status_picks_next_task_per_family():
    inv = build_bridge_dependency_inventory()
    sym = build_dynamic_symbol_universe_migration_status()
    tasks = build_next_20_ingestor_tasks()
    status = build_automation_integration_status(
        bridge_inventory=inv, symbol_status=sym, next_tasks=tasks
    )
    assert status["primary_p0_mission"] == (
        "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION"
    )
    assert status["next_ingestor_task"] is not None
    assert status["next_trainer_task"] is not None
    assert status["next_symbol_task"] is not None
    assert status["next_website_task"] is not None
    assert status["does_not_install_scheduler_or_daemon"] is True


def test_first_batch_dispatch_queues_all_six_required_ids():
    tasks = build_next_20_ingestor_tasks()
    batch = build_first_batch_task_dispatch_status(tasks)
    assert batch["dispatched_count"] == 6
    assert batch["missing_count"] == 0
    assert batch["planner_does_not_run_tasks_only_queues_them"] is True


def test_operator_dashboard_payload_blocks_production_and_marks_no_controls():
    inv = build_bridge_dependency_inventory()
    sym = build_dynamic_symbol_universe_migration_status()
    trainer = build_v2_trainer_bridge_exit_plan()
    tasks = build_next_20_ingestor_tasks()
    auto = build_automation_integration_status(
        bridge_inventory=inv, symbol_status=sym, next_tasks=tasks
    )
    batch = build_first_batch_task_dispatch_status(tasks)
    dash = build_operator_dashboard_payload(
        bridge_inventory=inv,
        symbol_status=sym,
        trainer_plan=trainer,
        automation_status=auto,
        first_batch=batch,
    )
    sb = dash["safety_scoreboard"]
    assert sb["live_gate"] == LIVE_GATE_BLOCKED
    assert sb["live_symbols"] == []
    assert sb["approves_live"] is False
    assert sb["approves_canary"] is False
    assert sb["approves_legacy_shutdown"] is False
    assert sb["approves_redis_trim"] is False
    assert sb["did_not_weaken_paper_fill_gate"] is True
    assert sb["did_not_mutate_live_symbols_paper_symbols_or_training_symbols"] is True
    assert dash["controls_present"] is False
    assert dash["fake_readiness"] is False


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def test_run_bridge_exit_packet_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_bridge_exit_packet(paths)
    assert result.go_no_go == (
        "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_READY"
    )
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go
    for required in [
        "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_REPORT.md",
        "bridge_dependency_inventory.json",
        "v2_dynamic_symbol_universe_migration_status.json",
        "v2_native_ingestor_migration_plan.json",
        "next_20_ingestor_tasks.json",
        "v2_trainer_bridge_exit_plan.json",
        "v2_dynamic_paper_trading_plan.json",
        "v2_enterprise_website_parallel_lane_plan.json",
        "automation_integration_status.json",
        "first_batch_task_dispatch_status.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()


def test_emitted_artifacts_have_no_truthy_approval_tokens(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_bridge_exit_packet(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"did_not_weaken_paper_fill_gate": false',
        '"did_not_mutate_live_symbols_paper_symbols_or_training_symbols": false',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
