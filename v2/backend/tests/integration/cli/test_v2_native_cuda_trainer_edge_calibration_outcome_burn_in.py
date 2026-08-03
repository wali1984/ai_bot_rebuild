from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from v2.backend.app.services.native_trainer.cuda_trainer_edge_burn_in import (
    GO_READY,
    EdgeBurnInPaths,
    build_edge_burn_in,
    write_edge_burn_in_artifacts,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    TRAINER_SOURCE,
    TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


ANCHOR = "2026-06-04T12:00:00-04:00"
ANCHOR_MS = _ms(ANCHOR)


def _prediction(
    prediction_id: str,
    *,
    symbol: str,
    action: str,
    expected_after: float,
    confidence: float,
    paper_fill_allowed: bool,
    premium_context: bool = False,
) -> dict[str, object]:
    prediction: dict[str, object] = {
        "prediction_id": prediction_id,
        "generated_est": ANCHOR,
        "symbol": symbol,
        "timeframe": "1m",
        "selected_action": action,
        "expected_move_bps": expected_after + 12.0,
        "expected_move_after_cost_bps": expected_after,
        "confidence_calibrated": confidence,
        "trainer_source": TRAINER_SOURCE,
        "model_source": MODEL_SOURCE,
        "cuda_active": True,
        "model_tensors_device_verified": True,
        "paper_fill_allowed": paper_fill_allowed,
        "paper_fill_gate_status": "PAPER_SHADOW_GATE_ALLOWED" if paper_fill_allowed else "PAPER_SHADOW_GATE_BLOCKED",
        "paper_fill_gate_block_reasons": [] if paper_fill_allowed else ["risk_denied"],
        "data_coverage_percent": 100.0,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }
    if premium_context:
        prediction.update(
            {
                "feature_cutoff": "2026-06-04T11:59:59-04:00",
                "available_at": "2026-06-04T11:59:59-04:00",
                "decision_time": ANCHOR,
                "entry_feature_snapshot_id": f"fs_{prediction_id}",
                "liquidation_engine_context_status": "LIQUIDATION_ENGINE_CONTEXT_READY",
                "premium_ingestor_context_status": "PREMIUM_CONTEXT_READY",
                "liquidity_context": {
                    "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
                    "depth_imbalance": 0.33,
                    "orderbook_depth_usd": 1_900_000.0,
                },
                "liquidation_context": {
                    "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
                    "liquidation_short_strength": 5.0,
                    "liquidation_long_strength": 1.0,
                },
                "microstructure_context": {
                    "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
                    "orderbook_imbalance": 0.33,
                    "spread_bps": 1.2,
                },
                "oi_funding_context": {
                    "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
                    "funding_bps": 0.3,
                    "oi_change_pct": 1.6,
                },
                "public_intel_context": {
                    "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
                    "public_intel_score": 0.62,
                },
            }
        )
    return prediction


def _lineage(prediction_id: str, *, symbol: str, allowed: bool) -> dict[str, object]:
    return {
        "trainer_prediction_record": {
            "prediction_id": prediction_id,
            "prediction_ts_ms": ANCHOR_MS,
            "symbol": symbol,
        },
        "orchestrator_decision_record": {
            "decision_id": f"dec_{prediction_id}",
            "prediction_id": prediction_id,
            "decision_action": "open_long" if allowed else "abstain",
            "decision_reason_code": "proceed_long" if allowed else "abstain_low_confidence",
            "live_blocked": True,
        },
        "risk_decision_record": {
            "risk_decision_id": f"rd_{prediction_id}",
            "decision_id": f"dec_{prediction_id}",
            "prediction_id": prediction_id,
            "risk_action": "allow" if allowed else "deny",
            "risk_reason_code": "allow_proceed_long" if allowed else "deny_orchestrator_abstained",
            "live_blocked": True,
        },
        "paper_execution_ledger_entry": {
            "paper_trade_id": f"pt_{prediction_id}",
            "risk_decision_id": f"rd_{prediction_id}",
            "decision_id": f"dec_{prediction_id}",
            "prediction_id": prediction_id,
            "ledger_action": "record_allow" if allowed else "record_deny",
            "ledger_reason_code": "mirror_allow" if allowed else "mirror_deny",
            "live_blocked": True,
        },
        "paper_signal_lineage": {
            "trainer_prediction_id": prediction_id,
            "risk_decision_id": f"rd_{prediction_id}",
            "orchestrator_decision_id": f"dec_{prediction_id}",
            "selected_action": "long",
            "pnl_outcome": None,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
    }


def _source_payload() -> dict[str, object]:
    predictions = [
        _prediction("p1", symbol="BTCUSDT", action="long", expected_after=20.0, confidence=0.82, paper_fill_allowed=True),
        _prediction("p2", symbol="ETHUSDT", action="short", expected_after=-20.0, confidence=0.76, paper_fill_allowed=True),
        _prediction(
            "p3",
            symbol="SOLUSDT",
            action="hold",
            expected_after=18.0,
            confidence=0.48,
            paper_fill_allowed=False,
            premium_context=True,
        ),
    ]
    return {
        "go_no_go": TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
        "trainer": {
            "trainer_source": TRAINER_SOURCE,
            "model_source": MODEL_SOURCE,
            "cuda_active": True,
            "model_tensors_device_verified": True,
            "model_device": "cuda:0",
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
        "metrics": {
            "training": {
                "status": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINING_STEP_RAN",
                "cuda_active": True,
                "cuda_claim_verified": True,
                "gpu_name": "NVIDIA GeForce RTX 5080",
                "training_steps": 2,
                "loss_before": 5.0,
                "loss_after": 3.0,
            },
            "missing_feature_count_total": 0,
            "stale_feature_count_total": 0,
        },
        "prediction_count": len(predictions),
        "lineage_count": len(predictions),
        "predictions_by_symbol": predictions,
        "lineage_samples": [
            _lineage("p1", symbol="BTCUSDT", allowed=True),
            _lineage("p2", symbol="ETHUSDT", allowed=True),
            _lineage("p3", symbol="SOLUSDT", allowed=False),
        ],
    }


def _timeline(symbol: str) -> list[dict[str, object]]:
    start = ANCHOR_MS - 60_000
    base = {"BTCUSDT": 100.0, "ETHUSDT": 100.0, "SOLUSDT": 100.0}[symbol]
    closes = {
        "BTCUSDT": [100.0, 100.4, 100.7, 101.0, 101.2, 101.5, 101.7],
        "ETHUSDT": [100.0, 100.5, 101.0, 101.5, 101.8, 102.0, 102.2],
        "SOLUSDT": [100.0, 100.3, 100.7, 101.0, 101.3, 101.6, 101.8],
    }[symbol]
    rows = []
    for i, close in enumerate(closes):
        open_ms = start + i * 60_000
        rows.append(
            {
                "open_time_ms": open_ms,
                "close_time_ms": open_ms + 59_999,
                "open": base if i == 0 else closes[i - 1],
                "high": max(base if i == 0 else closes[i - 1], close) + 0.1,
                "low": min(base if i == 0 else closes[i - 1], close) - 0.1,
                "close": close,
            }
        )
    return rows


def test_cuda_edge_burn_in_mines_outcomes_and_blocks_live(tmp_path: Path) -> None:
    result = build_edge_burn_in(_source_payload(), timeline_provider=_timeline, generated_est="2026-06-04T12:10:00-04:00")

    assert result.go_no_go == GO_READY
    outcome = result.artifacts["v2_cuda_prediction_outcome_mining_status.json"]
    edge = result.artifacts["v2_cuda_trainer_edge_recompute_after_burn_in.json"]
    calibration = result.artifacts["v2_cuda_confidence_calibration_status.json"]

    assert outcome["outcome_sample_count"] == 3
    assert outcome["classification_counts"]["correct_trade"] == 1
    assert outcome["classification_counts"]["false_positive"] == 1
    assert outcome["classification_counts"]["false_negative"] == 1
    sol_row = next(row for row in outcome["rows"] if row["symbol"] == "SOLUSDT")
    assert sol_row["entry_feature_snapshot_id"] == "fs_p3"
    assert sol_row["feature_cutoff"] == "2026-06-04T11:59:59-04:00"
    assert sol_row["liquidation_engine_context_status"] == "LIQUIDATION_ENGINE_CONTEXT_READY"
    assert sol_row["liquidation_context"]["liquidation_short_strength"] == 5.0
    assert sol_row["microstructure_context"]["orderbook_imbalance"] == 0.33
    assert edge["edge_proven"] is False
    assert edge["primary_recommendation"] == "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"
    assert edge["false_positive_count"] == 1
    assert edge["false_negative_count"] == 1
    assert calibration["high_confidence_loser_count"] >= 1
    assert result.operator_dashboard_payload["approves_live"] is False
    assert result.operator_dashboard_payload["approves_canary"] is False
    assert result.operator_dashboard_payload["live_gate"] == LIVE_GATE_BLOCKED
    assert result.operator_dashboard_payload["live_symbols"] == []
    assert result.operator_dashboard_payload["execution_live_symbols"] == []
    rendered = json.dumps(result.operator_dashboard_payload, sort_keys=True)
    assert "LIVE_READY" not in rendered
    assert "CANARY_READY" not in rendered

    paths = EdgeBurnInPaths(
        repo_root=tmp_path,
        worklog_dir=tmp_path / "claude_worklog/final_readiness/v2_native_cuda_trainer_edge_calibration_and_outcome_burn_in/latest",
        public_dir=tmp_path / "v2/frontend/public/v2_native_cuda_trainer_edge_calibration_and_outcome_burn_in/latest",
        source_payload_path=tmp_path / "source.json",
    )
    written = write_edge_burn_in_artifacts(paths=paths, result=result)
    required = {
        "GO_NO_GO.md",
        "V2_NATIVE_CUDA_TRAINER_EDGE_CALIBRATION_AND_OUTCOME_BURN_IN_REPORT.md",
        "v2_cuda_trainer_burn_in_expansion_status.json",
        "v2_cuda_prediction_outcome_mining_status.json",
        "v2_cuda_confidence_calibration_status.json",
        "v2_cuda_signal_runtime_lineage_status.json",
        "v2_cuda_trainer_edge_recompute_after_burn_in.json",
        "v2_cuda_trainer_edge_website_sync_status.json",
        "operator_dashboard_payload.json",
    }
    public_dir = paths.public_dir
    assert required == {path.name for path in public_dir.iterdir()}
    assert len(written.paths_written) == 2 * len(required)
