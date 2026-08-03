"""Tests for the V2 startup-parity first-batch execution packet."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.services.native_runtime_migration.contracts import (
    FRESHNESS_FRESH,
    FreshnessEnvelope,
    SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
    SOURCE_V2_NATIVE,
    TrainerPredictionContract,
)
from v2.backend.app.services.native_runtime_migration.first_batch_executor import (
    default_paths,
    run_first_batch,
    task_a_binance_ohlcv,
    task_b_binance_orderbook,
    task_c_coinank,
    task_d_kucoin,
    task_e_coinapi_wsds,
    task_f_feature_pipeline_expansion,
    task_g_ta_service,
    task_h_trainer_prediction_publisher_contract,
    task_i_trainer_dataset_builder,
    task_j_startup_order_parity_control_plane,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    V2_NATIVE_ACTIVE_SYMBOLS,
)


# ---------------------------------------------------------------------------
# Per-task contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task_fn,expected_id",
    [
        (task_a_binance_ohlcv, "v2_native_binance_ohlcv_dynamic_symbol_ingestor"),
        (task_b_binance_orderbook, "v2_native_binance_orderbook_dynamic_symbol_ingestor"),
        (task_c_coinank, "v2_native_coinank_dynamic_symbol_ingestor"),
        (task_d_kucoin, "v2_native_kucoin_dynamic_symbol_ingestor"),
        (task_e_coinapi_wsds, "v2_native_coinapi_wsds_dynamic_symbol_ingestor"),
        (task_f_feature_pipeline_expansion, "v2_native_feature_pipeline_dynamic_symbol_expansion"),
        (task_g_ta_service, "v2_native_technical_analysis_dynamic_symbol_service"),
        (task_h_trainer_prediction_publisher_contract, "v2_trainer_bridge_exit_native_prediction_publisher_contract"),
    ],
)
def test_task_status_carries_required_fields_and_safety_pins(task_fn, expected_id):
    status = task_fn()
    assert status["task_id"] == expected_id
    assert status["live_gate"] == LIVE_GATE_BLOCKED
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["codex_review_required"] is True
    assert status["broad_audit"] is False
    assert status["queued_not_running"] is True
    assert status["implementation_artifact"]
    assert status["implementation_status"] == status["status"]
    assert status["target_v2_keys"] == status["target_redis_key_patterns"]
    assert status["does_not_fake_data"] is True
    assert status["old_redis_write"] is False
    assert status["exchange_mutation"] is False
    assert status["live_or_shutdown_approval"] is False
    assert status["tests_required"] is True
    assert status["forbidden_actions"]
    assert "codex exec review --uncommitted" in status["codex_review_command"]
    assert status["public_payload"].startswith(
        "v2/frontend/public/v2_startup_parity_first_batch_execution/latest/"
    )


def test_ingestor_tasks_emit_envelope_per_known_universe_symbol():
    for fn in (
        task_a_binance_ohlcv,
        task_b_binance_orderbook,
        task_c_coinank,
        task_d_kucoin,
        task_e_coinapi_wsds,
    ):
        status = fn()
        envs = status["per_symbol_envelopes"]
        symbols = {e["symbol"] for e in envs}
        assert symbols == set(KNOWN_UNIVERSE), fn.__name__


def test_no_ingestor_task_marks_bridge_data_v2_native():
    for fn in (
        task_a_binance_ohlcv,
        task_b_binance_orderbook,
        task_c_coinank,
        task_d_kucoin,
        task_e_coinapi_wsds,
    ):
        status = fn()
        # No envelope should carry source=V2_NATIVE — these are ingestors
        # we have NOT yet implemented natively; they must be honest.
        for e in status["per_symbol_envelopes"]:
            assert e["source_label"] != SOURCE_V2_NATIVE, (fn.__name__, e)


def test_feature_pipeline_and_ta_show_v2_native_only_for_active_symbols():
    f = task_f_feature_pipeline_expansion()
    g = task_g_ta_service()
    for status in (f, g):
        for e in status["per_symbol_envelopes"]:
            if e["symbol"] in V2_NATIVE_ACTIVE_SYMBOLS:
                assert e["source_label"] == SOURCE_V2_NATIVE
                assert e["freshness_state"] == FRESHNESS_FRESH
            else:
                assert e["source_label"] != SOURCE_V2_NATIVE


def test_trainer_prediction_contract_rejects_missing_fields():
    bad = TrainerPredictionContract(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="x",
        trainer_source="V2_BRIDGE_FROM_LEGACY_TRAINER",
        expected_move_after_cost_bps=None,
        confidence_calibrated=None,
        feature_freshness_state=FRESHNESS_FRESH,
        missing_fields=["expected_move_after_cost_bps"],
        stale_fields=[],
    )
    assert bad.is_publishable() is False
    good = TrainerPredictionContract(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="x",
        trainer_source="V2_BRIDGE_FROM_LEGACY_TRAINER",
        expected_move_after_cost_bps=10.0,
        confidence_calibrated=0.7,
        feature_freshness_state=FRESHNESS_FRESH,
    )
    assert good.is_publishable() is True


def test_task_h_does_not_claim_trainer_native_readiness():
    status = task_h_trainer_prediction_publisher_contract()
    assert status["trainer_native_readiness_claimed"] is False
    assert status["trainer_native_claim"] is False
    assert "missing_field_sample" in json.dumps(status["contract_validation_samples"])


def test_task_i_dataset_builder_uses_only_v2_owned_evidence(tmp_path: Path):
    status = task_i_trainer_dataset_builder(tmp_path)
    assert status["data_quality_report"]["uses_only_v2_owned_evidence"] is True
    assert status["data_quality_report"]["checkpoint_compatibility_claimed"] is False


def test_task_j_startup_parity_control_plane_is_read_only(tmp_path: Path):
    status = task_j_startup_order_parity_control_plane(tmp_path)
    assert status["status"] == "CONTROL_PLANE_READ_ONLY_OBSERVABILITY"
    assert "no_systemd_install" in status["forbidden_actions"]
    assert "no_daemon_install" in status["forbidden_actions"]


def test_freshness_envelope_rejects_invalid_states():
    with pytest.raises(ValueError):
        FreshnessEnvelope(
            symbol="BTCUSDT",
            source_label=SOURCE_V2_NATIVE,
            freshness_state="NOT_A_REAL_STATE",
            generated_utc="2026-01-01T00:00:00Z",
        )


def test_envelope_should_publish_only_when_native_or_bridge_and_fresh():
    fresh = FreshnessEnvelope(
        symbol="BTCUSDT",
        source_label=SOURCE_V2_NATIVE,
        freshness_state=FRESHNESS_FRESH,
        generated_utc="2026-01-01T00:00:00Z",
    )
    bridge_fresh = FreshnessEnvelope(
        symbol="BTCUSDT",
        source_label=SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
        freshness_state=FRESHNESS_FRESH,
        generated_utc="2026-01-01T00:00:00Z",
    )
    stale = FreshnessEnvelope(
        symbol="BTCUSDT",
        source_label=SOURCE_V2_NATIVE,
        freshness_state="STALE",
        generated_utc="2026-01-01T00:00:00Z",
    )
    assert fresh.should_publish_to_redis() is True
    assert bridge_fresh.should_publish_to_redis() is True
    assert stale.should_publish_to_redis() is False


# ---------------------------------------------------------------------------
# End-to-end packet
# ---------------------------------------------------------------------------


def test_run_first_batch_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_first_batch(paths)
    assert result.go_no_go == "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_READY"
    assert result.task_count == 10
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go

    for required in [
        "V2_STARTUP_PARITY_FIRST_BATCH_EXECUTION_REPORT.md",
        "first_batch_execution_status.json",
        "refreshed_legacy_to_v2_service_parity_matrix.json",
        "refreshed_legacy_startup_dynamic_symbol_coverage.json",
        "refreshed_bridge_dependency_inventory.json",
        "report_center_payload.json",
    ]:
        assert (paths.packet_dir / required).exists(), required

    per_task_dir = paths.packet_dir / "per_task"
    for task_id in (
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
        assert (per_task_dir / (task_id + ".json")).exists(), task_id
        assert (paths.public_dir / (task_id + ".json")).exists(), task_id
        task_payload = json.loads((per_task_dir / (task_id + ".json")).read_text())
        assert task_payload["implementation_artifact"]
        assert task_payload["implementation_status"] == task_payload["status"]
        assert task_payload["target_v2_keys"] == task_payload[
            "target_redis_key_patterns"
        ]
        assert task_payload["codex_review_required"] is True
        assert task_payload["broad_audit"] is False
        assert task_payload["does_not_fake_data"] is True

    assert (paths.public_dir / "operator_dashboard_payload.json").exists()


def test_first_batch_meets_minimum_active_lane_target(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_first_batch(paths)
    # We require at least 3 active lanes per the war-room SLA; the
    # first-batch packet must satisfy this with the 10 task scaffolds.
    assert result.active_lanes >= 3


def test_first_batch_emits_no_truthy_approval_tokens(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_first_batch(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"did_not_weaken_paper_fill_gate": false',
        '"did_not_start_live_network_feed": false',
        '"did_not_mutate_live_symbols_paper_symbols_or_training_symbols": false',
        '"did_not_claim_trainer_native_readiness": false',
        '"trainer_native_readiness_claimed": true',
        '"full_migration_claimed": true',
        '"bridge_data_labeled_as_v2_native": true',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
