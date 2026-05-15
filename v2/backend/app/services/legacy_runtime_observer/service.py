from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from v2.backend.app.services.legacy_v2_observatory_common import (
    LIVE_GATE_STATUS,
    count_terms,
    file_mtime_status,
    safety_footer,
    tail_text,
    utc_now,
)
from v2.backend.app.services.trainer_bridge.service import legacy_log_prediction_payload


LEGACY_ROOT = Path("/home/wali/Desktop/AI BOT")
LEGACY_LOG_ROOT = LEGACY_ROOT / ".logs"
LEGACY_TRAINER_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "hybrid_trainer_stdout.log",
    LEGACY_LOG_ROOT / "gpu_forced_ppo.log",
    LEGACY_LOG_ROOT / "trainer.log",
    LEGACY_LOG_ROOT / "monitor_trainer_predictions.log",
]
LEGACY_ORCHESTRATOR_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "orchestrator.log",
    LEGACY_LOG_ROOT / "orchestrator_worker.log",
]
LEGACY_SIGNAL_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "signal_router.log",
    LEGACY_LOG_ROOT / "monitor_signals.log",
    LEGACY_LOG_ROOT / "trainer_signals.log",
]
LEGACY_FEATURE_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "ta_service.log",
    LEGACY_LOG_ROOT / "ingest_ta.log",
    *sorted(LEGACY_LOG_ROOT.glob("feature_pipeline_dual_*.log"))[-3:],
]
LEGACY_INGESTOR_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "ingest_live_binance.log",
    LEGACY_LOG_ROOT / "kucoin.log",
    LEGACY_LOG_ROOT / "live_coinapi_wsds.restart.nohup.out",
]
LEGACY_COINANK_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "coinank.log",
    LEGACY_LOG_ROOT / "live_coinank_global.log",
]
LEGACY_LIQUIDATION_LOG_CANDIDATES = [
    LEGACY_LOG_ROOT / "live_coinank.log",
    LEGACY_LOG_ROOT / "live_coinank_global.log",
]
LEGACY_CHECKPOINT_METADATA_CANDIDATES = [
    LEGACY_ROOT / ".models" / "checkpoints" / "live_enhanced" / "checkpoint_metadata_latest.json",
    LEGACY_ROOT / ".models" / "checkpoints" / "live_enhanced_pre_corefix_20260304_044604" / "checkpoint_metadata_latest.json",
    LEGACY_ROOT / ".backups" / "collapsed_checkpoint_20260226_2003" / "checkpoint_metadata_latest.json",
    LEGACY_ROOT / ".backups" / "checkpoints_2025-10-14_0136" / "checkpoints" / "live" / "checkpoint_metadata_latest.json",
]


def _first_existing(paths: list[Path]) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def _process_matches(patterns: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid,etime,comm,args"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"state": "PROCESS_SCAN_UNAVAILABLE", "count": 0, "sample": []}
    lines = []
    for line in result.stdout.splitlines():
        lowered = line.lower()
        if "codex_legacy_v2_realtime_decision_observatory" in lowered:
            continue
        if any(pattern.lower() in lowered for pattern in patterns):
            lines.append(line.strip())
    return {
        "state": "RUNNING_READONLY_OBSERVED" if lines else "NOT_OBSERVED",
        "count": len(lines),
        "sample": lines[:5],
    }


def _latest_count_from_logs(paths: list[Path], terms: list[str]) -> dict[str, Any]:
    path = _first_existing(paths)
    text = tail_text(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "count": count_terms(text, terms) if text else 0,
        "freshness": file_mtime_status(path),
    }


def build_legacy_runtime_observer_status(
    *,
    trainer_log_candidates: list[Path] | None = None,
    checkpoint_metadata_candidates: list[Path] | None = None,
) -> dict[str, Any]:
    trainer_logs = trainer_log_candidates or LEGACY_TRAINER_LOG_CANDIDATES
    checkpoint_candidates = checkpoint_metadata_candidates or LEGACY_CHECKPOINT_METADATA_CANDIDATES
    trainer_log = _first_existing(trainer_logs)
    checkpoint_metadata = _first_existing(checkpoint_candidates)
    prediction = legacy_log_prediction_payload(
        log_path=trainer_log,
        checkpoint_metadata_path=checkpoint_metadata,
    )
    trainer_tail = tail_text(trainer_log)
    signal_summary = _latest_count_from_logs(
        LEGACY_SIGNAL_LOG_CANDIDATES,
        ["signal", "signals:trading", "publish", "router"],
    )
    proposal_summary = _latest_count_from_logs(
        LEGACY_ORCHESTRATOR_LOG_CANDIDATES,
        ["proposal", "wma:proposals", "orchestrator"],
    )
    errors = []
    if trainer_tail:
        for line in trainer_tail.splitlines()[-200:]:
            lowered = line.lower()
            if "error" in lowered or "traceback" in lowered or "exception" in lowered:
                errors.append(line[-500:])
    data_gaps = []
    if not trainer_log.exists():
        data_gaps.append("legacy_trainer_log_missing")
    if prediction is None:
        data_gaps.append("legacy_trainer_prediction_missing_or_unparseable")
    if not checkpoint_metadata.exists():
        data_gaps.append("legacy_checkpoint_metadata_missing")
    status = {
        "worker_id": "legacy_runtime_readonly_observer",
        "generated_at": utc_now(),
        "legacy_root": str(LEGACY_ROOT),
        "read_only_status": "READ_ONLY_REFERENCE_ONLY",
        "legacy_redis_read_mode": "DISABLED_BY_DEFAULT_NO_WRITES",
        "legacy_trainer_process_state": _process_matches(
            ["hybrid_trainer", "gpu_forced_ppo", "monitor_trainer_predictions"]
        ),
        "legacy_trader_process_state": _process_matches(
            ["trader_primary", "trader_asjad", "trading.trader", "trader.py"]
        ),
        "orchestrator_process_state": _process_matches(["orchestrator"]),
        "trainer_prediction_count": count_terms(trainer_tail, ["PPO_DECISION_RAW"]),
        "latest_prediction_ts": prediction.get("generated_at") if prediction else None,
        "latest_prediction_id": prediction.get("prediction_id") if prediction else None,
        "latest_symbol": prediction.get("symbol") if prediction else None,
        "latest_timeframe": prediction.get("timeframe") if prediction else None,
        "latest_confidence": prediction.get("confidence_calibrated") if prediction else None,
        "trainer_checkpoint": prediction.get("checkpoint_id") if prediction else "",
        "trainer_log_path": str(trainer_log),
        "trainer_log_freshness": file_mtime_status(trainer_log),
        "trainer_log_errors": errors[-20:],
        "proposal_count": proposal_summary["count"],
        "proposal_log": proposal_summary,
        "signal_count": signal_summary["count"],
        "latest_signal_id": None,
        "latest_signal_reason": "SOURCE_LIMITED_LOG_READONLY_OBSERVATION",
        "signal_log": signal_summary,
        "feature_freshness": file_mtime_status(_first_existing(LEGACY_FEATURE_LOG_CANDIDATES)),
        "ingestor_freshness": file_mtime_status(_first_existing(LEGACY_INGESTOR_LOG_CANDIDATES)),
        "TA_freshness": file_mtime_status(LEGACY_LOG_ROOT / "ta_service.log"),
        "liquidation_freshness": file_mtime_status(_first_existing(LEGACY_LIQUIDATION_LOG_CANDIDATES)),
        "CoinAnk_freshness": file_mtime_status(_first_existing(LEGACY_COINANK_LOG_CANDIDATES)),
        "data_gaps": data_gaps,
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "legacy_streams_readonly_reference": [
            "trainer:predictions",
            "wma:proposals",
            "signals:trading",
            "signals:trading:primary",
            "signals:trading:asjad",
        ],
        "legacy_trader_action": "DO_NOT_START_OR_STOP_LEGACY_TRADER_FROM_OBSERVER",
    }
    status.update(safety_footer())
    return status
