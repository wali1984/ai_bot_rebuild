from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import legacy_runtime_readonly_observer as worker
from v2.backend.app.services.legacy_runtime_observer import service as observer_service


def test_legacy_runtime_observer_reads_logs_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    legacy_log = tmp_path / "hybrid_trainer_stdout.log"
    legacy_log.write_text(
        "\n".join(
            [
                "2026-05-15 00:00:00,000 INFO PPO_DECISION_RAW | account=primary | symbol=BTCUSDT | tf=1m | action_id=1 | action=OPEN_LONG | ppo_conf=0.82 | top1=0.82 | top2=0.11 | top1_id=1 | top2_id=0",
                "2026-05-15 00:00:01,000 INFO trainer heartbeat",
            ]
        )
    )
    checkpoint = tmp_path / "checkpoint_metadata_latest.json"
    checkpoint.write_text(json.dumps({"timestamp": 1778800000, "ppo_path": "/readonly/model.zip"}))
    monkeypatch.setattr(observer_service, "LEGACY_TRAINER_LOG_CANDIDATES", [legacy_log])
    monkeypatch.setattr(observer_service, "LEGACY_CHECKPOINT_METADATA_CANDIDATES", [checkpoint])
    monkeypatch.setattr(observer_service, "LEGACY_SIGNAL_LOG_CANDIDATES", [tmp_path / "signal.log"])
    monkeypatch.setattr(observer_service, "LEGACY_ORCHESTRATOR_LOG_CANDIDATES", [tmp_path / "orch.log"])
    monkeypatch.setattr(observer_service, "LEGACY_FEATURE_LOG_CANDIDATES", [tmp_path / "feature.log"])
    monkeypatch.setattr(observer_service, "LEGACY_INGESTOR_LOG_CANDIDATES", [tmp_path / "ingest.log"])
    monkeypatch.setattr(observer_service, "LEGACY_COINANK_LOG_CANDIDATES", [tmp_path / "coinank.log"])
    monkeypatch.setattr(observer_service, "LEGACY_LIQUIDATION_LOG_CANDIDATES", [tmp_path / "liq.log"])

    status = worker.run_once(worker.parse_args(["--once"]))

    assert status["read_only_status"] == "READ_ONLY_REFERENCE_ONLY"
    assert status["latest_prediction_id"].startswith("legacy_log_pred_")
    assert status["latest_symbol"] == "BTCUSDT"
    assert status["trainer_prediction_count"] == 1
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["old_redis_write_performed"] is False
    assert status["exchange_action_taken"] is False
