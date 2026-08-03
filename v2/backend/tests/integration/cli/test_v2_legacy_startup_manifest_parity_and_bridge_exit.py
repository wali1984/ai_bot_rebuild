"""Tests for the V2 legacy-startup-manifest parity planner."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.legacy_startup_parity.native_runtime_legacy_parity import (
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    V2_NATIVE_ACTIVE_SYMBOLS,
    build_first_batch_startup_parity_task_dispatch,
    build_legacy_redis_to_v2_redis_contract_map,
    build_legacy_startup_dynamic_symbol_coverage,
    build_legacy_startup_manifest,
    build_legacy_to_v2_service_parity_matrix,
    build_v2_startup_order_parity_plan,
    default_paths,
    run_legacy_parity_packet,
)


def test_manifest_carries_safety_pins_and_at_least_30_items(tmp_path: Path):
    manifest = build_legacy_startup_manifest(tmp_path)
    assert manifest["live_gate"] == LIVE_GATE_BLOCKED
    assert manifest["live_symbols"] == []
    assert manifest["approves_live"] is False
    assert manifest["item_count"] >= 30
    phases = {item["phase"] for item in manifest["items"]}
    for required in (
        "0_preflight",
        "0_5_monitoring",
        "1_ingestors",
        "2_features",
        "2_5_ta",
        "2_5_validation",
        "3_trainer",
        "3B_orchestrator",
        "4A_signal_router",
        "4B_traders",
        "4C_portfolio",
        "5_health",
        "6_final_status",
    ):
        assert required in phases, required


def test_manifest_records_local_and_snapshot_sha_and_diff_classification(tmp_path: Path):
    manifest = build_legacy_startup_manifest(tmp_path)
    src = manifest["canonical_sources"]
    assert "diff_classification" in src
    assert src["parsing_source_used"] in {"local", "snapshot", "MISSING_NO_PARSE"}
    if src["parsing_source_used"] == "local":
        assert src["local_runtime_script_used_for_parsing"] is True
        assert src["snapshot_used_only_as_drift_reference"] is True


def test_parity_matrix_marks_no_v2_native_for_legacy_only_traders(tmp_path: Path):
    manifest = build_legacy_startup_manifest(tmp_path)
    parity = build_legacy_to_v2_service_parity_matrix(manifest)
    by_id = {r["service_id"]: r for r in parity["rows"]}
    # Legacy traders must never be marked V2_NATIVE in the parity matrix.
    assert by_id["trading_trader_primary"]["migration_status"] != "V2_NATIVE"
    assert by_id["trading_trader_asjad"]["migration_status"] != "V2_NATIVE"
    # Legacy trainer is bridge-only.
    assert (
        by_id["rl_hybrid_trainer"]["migration_status"]
        == "V2_BRIDGE_FROM_LEGACY_REDIS"
    )


def test_redis_contract_map_lists_all_documented_legacy_keys():
    redis_map = build_legacy_redis_to_v2_redis_contract_map()
    patterns = {row["legacy_key_pattern"] for row in redis_map["rows"]}
    for needed in (
        "price:{symbol}",
        "orderbook:{symbol}",
        "ohlcv:list:{symbol}:{timeframe}",
        "latest:{symbol}",
        "coinank:*",
        "features:coinank:*",
        "features:global_coinank:*",
        "kc:*",
        "features:kucoin:*",
        "microfeat:*",
        "msnap:coinapi_wsds:*",
        "normalized:ohlcv:*",
        "ta:*",
        "latest:ta:*",
        "unified_features:*",
        "prediction:*",
        "trainer:intent:*",
        "rl:metrics:*",
        "signals:trading",
        "signals:trading:primary",
        "signals:trading:asjad",
        "wma:*",
        "executed_signals",
        "heartbeat:*",
    ):
        assert needed in patterns, needed


def test_symbol_coverage_covers_full_universe_and_all_families():
    coverage = build_legacy_startup_dynamic_symbol_coverage()
    assert len(coverage["rows"]) == len(KNOWN_UNIVERSE)
    families = coverage["service_families"]
    assert len(families) >= 15
    allowed = set(coverage["classification_vocabulary"])
    for row in coverage["rows"]:
        assert set(row["per_family"].values()) <= allowed
        if row["symbol"] in V2_NATIVE_ACTIVE_SYMBOLS:
            assert row["per_family"]["price"] == "V2_NATIVE"
            assert row["per_family"]["unified_features"] == "V2_NATIVE"
            assert row["per_family"]["prediction"] == "V2_BRIDGE_FROM_LEGACY_REDIS"
            assert row["per_family"]["coinank"] == "V2_BRIDGE_FROM_LEGACY_REDIS"
            assert row["per_family"]["ohlcv"] == "PLACEHOLDER_NOT_READY"
            assert row["per_family"]["orderbook"] == "PLACEHOLDER_NOT_READY"
    assert coverage["live_symbols_unchanged"] is True
    assert coverage["paper_symbols_unchanged_pending_governance"] is True


def test_startup_order_plan_lists_required_v2_phase_order(tmp_path: Path):
    manifest = build_legacy_startup_manifest(tmp_path)
    plan = build_v2_startup_order_parity_plan(manifest)
    required_order = plan["required_v2_phase_order"]
    for ph in ("0_preflight", "1_ingestors", "3_trainer", "3B_orchestrator"):
        assert ph in required_order
    assert plan["does_not_start_or_stop_anything"] is True


def test_first_batch_dispatch_carries_all_required_tasks():
    batch = build_first_batch_startup_parity_task_dispatch()
    ids = {t["task_id"] for t in batch["tasks"]}
    for needed in (
        "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
        "v2_native_binance_orderbook_dynamic_symbol_ingestor",
        "v2_native_coinank_dynamic_symbol_ingestor",
        "v2_native_kucoin_dynamic_symbol_ingestor",
        "v2_native_coinapi_wsds_dynamic_symbol_ingestor",
        "v2_native_feature_pipeline_dynamic_symbol_expansion",
        "v2_native_technical_analysis_dynamic_symbol_service",
        "v2_trainer_bridge_exit_native_prediction_publisher_contract",
        "v2_trainer_dataset_builder_from_v2_replay_features",
        "v2_startup_order_parity_control_plane",
    ):
        assert needed in ids, needed
    for t in batch["tasks"]:
        # Every task must carry a forbidden-actions allow-list and tests flag.
        assert t["forbidden_actions"]
        assert "tests_required" in t
        # Every codex review command must use the supported subcommand form.
        assert "codex exec review --uncommitted" in t["codex_review_descriptor"]
        assert t["codex_review_required"] is True
        assert t["broad_audit"] is False
        assert t["status"] == "QUEUED_NOT_RUNNING"
        assert t["file_lock_group"]


def test_run_legacy_parity_packet_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_legacy_parity_packet(paths)
    assert result.go_no_go == (
        "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_READY"
    )
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go
    for required in [
        "V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_REPORT.md",
        "legacy_startup_manifest.json",
        "legacy_to_v2_service_parity_matrix.json",
        "legacy_redis_to_v2_redis_contract_map.json",
        "legacy_startup_dynamic_symbol_coverage.json",
        "v2_startup_order_parity_plan.json",
        "first_batch_startup_parity_task_dispatch.json",
        "automation_integration_status.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()


def test_emitted_artifacts_have_no_truthy_approval_tokens(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_legacy_parity_packet(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"did_not_weaken_paper_fill_gate": false',
        '"did_not_mutate_live_symbols_paper_symbols_or_training_symbols": false',
        '"did_not_install_systemd_units_or_scheduler_daemons": false',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
