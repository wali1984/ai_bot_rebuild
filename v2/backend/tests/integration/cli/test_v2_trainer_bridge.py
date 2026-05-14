from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_trainer_bridge as worker
from v2.backend.app.cli.v2_trainer_bridge import (
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    WORKER_ID,
    parse_args,
    run_once,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)
from v2.backend.app.services.trainer_bridge.service import (
    LEGACY_EXPECTED_SHA256,
    LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT,
    LEGACY_HYBRID_TRAINER_LOG_EVIDENCE_PRESENT,
    WRAPPER_NOT_LEGACY_HYBRID_PARITY,
    inspect_legacy_trainer_source,
    utc_now,
)


def _route_worker_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    prediction = tmp_path / "trainer_prediction.json"
    feature = tmp_path / "feature_snapshot.json"
    scope = tmp_path / "feature_pipeline_scope.json"
    legacy_log = tmp_path / "missing_hybrid_trainer.log"
    checkpoint_metadata = tmp_path / "missing_checkpoint_metadata_latest.json"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", public_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "WORKER_STATUS_FILE", worker_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "PREDICTION_CANDIDATES", [prediction])
    monkeypatch.setattr(worker, "FEATURE_SNAPSHOT_CANDIDATES", [feature])
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [tmp_path / "missing_symbol_universe.json"])
    monkeypatch.setattr(worker, "UPSTREAM_SYMBOL_SCOPE_CANDIDATES", [scope])
    monkeypatch.setattr(worker, "LEGACY_READONLY_TRAINER_LOG", legacy_log)
    monkeypatch.setattr(worker, "LEGACY_READONLY_CHECKPOINT_METADATA", checkpoint_metadata)
    monkeypatch.setattr(worker, "detect_trainer_process", lambda: {
        "trainer_process_state": "RUNNING_READONLY_OBSERVED",
        "trainer_process_count": 1,
        "trainer_process_sample": ["123 1 60 0.0 1.0 python3 -m rl.hybrid_trainer"],
    })
    monkeypatch.setattr(worker, "detect_gpu_state", lambda: {
        "gpu_state": "GPU_EVIDENCE_PRESENT",
        "gpus": [{"name": "RTX 5080", "gpu_util_pct": 12.0, "memory_used_mb": 1024.0, "memory_total_mb": 16384.0}],
    })
    monkeypatch.setattr(worker, "inspect_legacy_trainer_source", lambda *, repo_root: {
        "legacy_binary_state": "PRESENT",
        "legacy_source_sha256": LEGACY_EXPECTED_SHA256,
        "manifest_sha256": LEGACY_EXPECTED_SHA256,
        "manifest_status": "SHA_MATCH",
        "legacy_behavior_features": ["RTX5080FeatureExtractor", "RTX5080Policy", "GPUForcedPPO", "HybridTrainer"],
        "legacy_methods_required_present": {"setup_models": True},
        "legacy_config_dependencies": ["SYMBOLS", "SIGNAL_OUTPUT_STREAM", "SIGNAL_HEARTBEAT_STREAM"],
        "legacy_stream_contracts_readonly_reference": ["signals:trading", "signals:trainer:heartbeat", "wma:proposals"],
        "legacy_gpu_behavior": ["GPUForcedPPO", "mixed precision GradScaler"],
        "legacy_checkpoint_behavior": ["PPO checkpoint load", "checkpoint compatibility guards"],
    })
    return {
        "public": public_dir,
        "local": local_dir,
        "worker": worker_dir,
        "prediction": prediction,
        "feature": feature,
        "scope": scope,
    }


def _write_ready_feature(path: Path, *, missing: list[str] | None = None, stale: list[str] | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "worker_id": "v2_feature_snapshot_builder",
                "last_snapshot_id": "feature_snapshot_test_001",
                "last_snapshot_ts": utc_now(),
                "trainer_readiness": "READY",
                "missing_features": missing or [],
                "stale_features": stale or [],
                "feature_categories_present": ["price", "liquidity", "open_interest", "funding", "technical"],
            }
        )
    )


def _write_scope(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "legacy_active_symbols": list(LEGACY_ACTIVE_SYMBOLS_25),
                "discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "COINANK_ONLY_USDT", "KUCOIN_ONLY_USDT"],
                "dynamic_discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "COINANK_ONLY_USDT", "KUCOIN_ONLY_USDT"],
                "observed_symbols": ["BTCUSDT"],
                "training_symbols": ["BTCUSDT", "ETHUSDT"],
                "paper_symbols": ["BTCUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            }
        )
    )


def _legacy_prediction(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_type": "LEGACY_HYBRID_TRAINER_PARITY",
        "prediction_id": "legacy_pred_001",
        "feature_snapshot_id": "feature_snapshot_test_001",
        "model_checkpoint": "legacy_hybrid_ppo_checkpoint_001",
        "confidence_raw": 0.71,
        "confidence_calibrated": 0.64,
        "generated_at": utc_now(),
        "symbol": "BTCUSDT",
        "top_features": [
            {"name": "funding", "value": 0.12},
            {"name": "open_interest", "value": 0.08},
            {"name": "spread", "value": -0.03},
        ],
    }
    payload.update(overrides)
    return payload


def test_legacy_baseline_hash_is_cited_from_copied_manifest() -> None:
    result = inspect_legacy_trainer_source(repo_root=REPO_ROOT)

    assert result["legacy_binary_state"] == "PRESENT"
    assert result["legacy_source_sha256"] == LEGACY_EXPECTED_SHA256
    assert result["manifest_sha256"] == LEGACY_EXPECTED_SHA256
    assert result["manifest_status"] == "SHA_MATCH"
    assert "HybridTrainer" in result["legacy_behavior_features"]
    assert "RTX5080FeatureExtractor" in result["legacy_behavior_features"]


def test_paper_momentum_wrapper_prediction_is_rejected_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    _write_ready_feature(paths["feature"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(
        json.dumps(
            {
                "source_type": "V2_PAPER_TRAINER_WRAPPER",
                "prediction_id": "pred_wrapper_001",
                "feature_snapshot_id": "feature_snapshot_test_001",
                "model_checkpoint": "v2_paper_readonly_momentum_wrapper_v1",
                "confidence_raw": 0.73,
                "confidence_calibrated": 0.71,
                "generated_at": utc_now(),
                "symbol": "BTCUSDT",
                "top_features": [{"name": "return_5m", "value": -0.01}],
            }
        )
    )

    status = run_once(parse_args(["--once"]))

    assert status["accepted_as_legacy_hybrid_prediction"] is False
    assert status["prediction_evidence_status"] == WRAPPER_NOT_LEGACY_HYBRID_PARITY
    assert status["predictions_emitted_total"] == 0
    assert status["fail_closed"] is True
    assert WRAPPER_NOT_LEGACY_HYBRID_PARITY in status["error_blocker_state"]
    assert status["trainer_readiness"] == "BLOCKED"
    assert status["live_gate"] == "blocked_human_only"
    assert status["exchange_action_taken"] is False
    assert status["old_redis_write_performed"] is False


def test_current_legacy_log_prediction_supersedes_wrapper_but_keeps_full_parity_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    legacy_log = tmp_path / "hybrid_trainer.log"
    checkpoint_metadata = tmp_path / "checkpoint_metadata_latest.json"
    monkeypatch.setattr(worker, "LEGACY_READONLY_TRAINER_LOG", legacy_log)
    monkeypatch.setattr(worker, "LEGACY_READONLY_CHECKPOINT_METADATA", checkpoint_metadata)
    _write_ready_feature(paths["feature"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(
        json.dumps(
            {
                "source_type": "V2_PAPER_TRAINER_WRAPPER",
                "prediction_id": "pred_wrapper_001",
                "feature_snapshot_id": "feature_snapshot_test_001",
                "model_checkpoint": "v2_paper_readonly_momentum_wrapper_v1",
                "confidence_raw": 0.73,
                "confidence_calibrated": 0.71,
                "generated_at": utc_now(),
                "symbol": "BTCUSDT",
                "top_features": [{"name": "return_5m", "value": -0.01}],
            }
        )
    )
    legacy_ts = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    legacy_log.write_text(
        f"{legacy_ts} - INFO - hybrid_trainer - "
        "PPO_DECISION_RAW | account=primary | symbol=ALICEUSDT | tf=4h | "
        "action_id=1 | action=OPEN_LONG | ppo_conf=0.8611 | top1=0.8026 | "
        "top2=0.0938 | top1_id=1 | top2_id=2\n"
    )
    checkpoint_metadata.write_text(
        json.dumps(
            {
                "timestamp": 1778800487,
                "datetime": "2026-05-14T23:14:49.535378+00:00",
                "ppo_path": "models/checkpoints/live_legacy/ppo_checkpoint_1778800487.zip",
            }
        )
    )

    status = run_once(parse_args(["--once"]))

    assert status["accepted_as_legacy_hybrid_prediction"] is True
    assert status["prediction_evidence_status"] == LEGACY_HYBRID_TRAINER_LOG_EVIDENCE_PRESENT
    assert status["runtime_evidence_status"] == LEGACY_HYBRID_TRAINER_LOG_EVIDENCE_PRESENT
    assert status["prediction_source_type"] == "LEGACY_HYBRID_TRAINER_LOG_READONLY"
    assert status["prediction_source_path"].startswith("legacy_readonly:")
    assert status["prediction_id"].startswith("legacy_log_pred_")
    assert status["feature_snapshot_id"].startswith("legacy_log_feature_ALICEUSDT_4h_")
    assert status["model_version"] == "legacy_hybrid_trainer_live_legacy"
    assert status["checkpoint_id"] == "legacy_live_checkpoint_1778800487"
    assert status["checkpoint_evidence_status"] == "PRESENT"
    assert status["confidence_raw"] == pytest.approx(0.8611)
    assert status["confidence_calibrated"] == pytest.approx(0.8611)
    assert status["top_positive_features"][0]["name"] == "ppo_action_OPEN_LONG_probability"
    assert status["trainer_readiness"] == "BLOCKED"
    assert status["fail_closed"] is True
    assert WRAPPER_NOT_LEGACY_HYBRID_PARITY not in status["error_blocker_state"]
    assert "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE" in status["error_blocker_state"]
    assert "top_negative_features_absent_from_legacy_log_line" in status["lineage_derivation_warnings"]
    assert status["legacy_readonly_log_bridge"]["status"] == "PRESENT"
    assert status["live_gate"] == "blocked_human_only"
    assert status["exchange_action_taken"] is False
    assert status["old_redis_write_performed"] is False


def test_accepted_legacy_hybrid_prediction_maps_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    _write_ready_feature(paths["feature"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(json.dumps(_legacy_prediction()))

    status = run_once(parse_args(["--once"]))

    assert status["accepted_as_legacy_hybrid_prediction"] is True
    assert status["prediction_evidence_status"] == LEGACY_HYBRID_TRAINER_PREDICTION_PRESENT
    assert status["predictions_emitted_total"] == 1
    assert status["prediction_id"] == "legacy_pred_001"
    assert status["feature_snapshot_id"] == "feature_snapshot_test_001"
    assert status["model_checkpoint_id"] == "legacy_hybrid_ppo_checkpoint_001"
    assert status["checkpoint_evidence_status"] == "PRESENT"
    assert status["raw_confidence"] == pytest.approx(0.71)
    assert status["calibrated_confidence"] == pytest.approx(0.64)
    assert status["top_positive_features"][0]["name"] == "funding"
    assert status["top_negative_features"][0]["name"] == "spread"
    assert status["trainer_readiness"] == "READY"
    assert status["fail_closed"] is False
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["worker_id"] == WORKER_ID
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written


def test_generic_prediction_source_is_not_accepted_as_trainer_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    _write_ready_feature(paths["feature"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(json.dumps(_legacy_prediction(source_type="STATIC_TEST_FIXTURE")))

    status = run_once(parse_args(["--once"]))

    assert status["accepted_as_legacy_hybrid_prediction"] is False
    assert status["prediction_evidence_status"] == "PREDICTION_SOURCE_NOT_LEGACY_HYBRID_OR_V2_NATIVE"
    assert status["predictions_emitted_total"] == 0
    assert status["fail_closed"] is True


def test_stale_prediction_is_not_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    _write_ready_feature(paths["feature"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(json.dumps(_legacy_prediction(generated_at="2026-01-01T00:00:00Z")))

    status = run_once(parse_args(["--once"]))

    assert status["accepted_as_legacy_hybrid_prediction"] is False
    assert status["prediction_evidence_status"] == "PREDICTION_EVIDENCE_STALE"
    assert status["fail_closed"] is True


def test_feature_missing_and_stale_flags_propagate_and_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    _write_ready_feature(paths["feature"], missing=["oi_delta"], stale=["funding_rate"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(json.dumps(_legacy_prediction()))

    status = run_once(parse_args(["--once"]))

    assert status["accepted_as_legacy_hybrid_prediction"] is True
    assert status["missing_feature_flags"] == ["oi_delta"]
    assert status["stale_feature_flags"] == ["funding_rate"]
    assert status["feature_snapshot_trainer_readiness_signal"] == "READY"
    assert status["trainer_readiness"] == "BLOCKED"
    assert "MISSING_FEATURE_FLAGS" in status["error_blocker_state"]
    assert "STALE_FEATURE_FLAGS" in status["error_blocker_state"]


def test_symbol_universe_roles_are_preserved_from_upstream_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_worker_io(tmp_path, monkeypatch)
    _write_ready_feature(paths["feature"])
    _write_scope(paths["scope"])
    paths["prediction"].write_text(json.dumps(_legacy_prediction()))

    status = run_once(parse_args(["--once"]))

    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_public_payload_status"] == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    assert status["symbol_scope_upstream_payload_status"] == "PRESENT"
    assert status["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert len(status["legacy_active_symbols"]) == 25
    assert status["dynamic_discovered_symbols"] == ["BTCUSDT", "COINANK_ONLY_USDT", "ETHUSDT", "KUCOIN_ONLY_USDT", "SOLUSDT"]
    assert status["training_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["coinank_symbols_directly_tradable"] is False
    assert set(status["training_symbols"]) < set(status["dynamic_discovered_symbols"])
    assert set(status["paper_symbols"]) < set(status["dynamic_discovered_symbols"])
    assert status["symbol_selection_score_factors"] == list(SYMBOL_SELECTION_SCORE_FACTORS)


def test_cli_accepts_descriptor_invocation_template() -> None:
    args = parse_args(["--mode", "bridge", "--readonly", "--once"])

    assert args.mode == "bridge"
    assert args.readonly is True
    assert args.once is True


def test_new_trainer_bridge_sources_do_not_contain_mutation_tokens() -> None:
    paths = [
        REPO_ROOT / "v2/backend/app/cli/v2_trainer_bridge.py",
        REPO_ROOT / "v2/backend/app/services/trainer_bridge/service.py",
    ]
    source = "\n".join(path.read_text() for path in paths)
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures" + "_create" + "_order",
        "futures" + "_change" + "_leverage",
        "futures" + "_change" + "_margin" + "_type",
        "X" + "ADD",
        "H" + "S" + "E" + "T",
        "X" + "TRIM",
        "FL" + "USH",
    ]

    for token in forbidden:
        assert token not in source
