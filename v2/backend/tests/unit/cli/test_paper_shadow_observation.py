from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.paper_shadow_observation import build_observation_status


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def test_observation_summarizes_jsonl_windows(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    now = datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc)
    _write_json(
        paper_dir / "paper_runtime_status.json",
        {
            "runtime_state": "PAPER_RUNTIME_ONLINE_ACTIVE",
            "freshness": {"runtime_age_seconds": 0},
            "paper_account": {"realized_pnl": -1.02},
            "trainer_prediction": {"prediction_id": "pred_latest"},
            "current_signal_lineage": {
                "lineage_ids": {
                    "prediction_id": "pred_latest",
                    "signal_id": "sig_latest",
                    "risk_decision_id": "risk_latest",
                    "execution_intent_id": "intent_latest",
                }
            },
            "paper_ledger_tail": [
                {
                    "paper_ledger_entry_id": "ledger_latest",
                    "execution_intent_id": "intent_latest",
                    "paper_result": "FILLED_PAPER_ONLY",
                    "fee_rate": 0.0004,
                    "slippage_bps": 2,
                    "funding_assumption": "zero_until_funding_feed_adapter_current",
                }
            ],
        },
    )
    events = [
        {
            "generated_at": "2026-05-13T00:30:00Z",
            "ledger_action": "PAPER_FILL_SIMULATED",
            "paper_result": "FILLED_PAPER_ONLY",
            "risk_action": "allow",
            "risk_reason_code": "allow_proceed_long",
            "confidence": 0.72,
            "symbol": "BTCUSDT",
            "paper_realized_pnl": -1.0,
        },
        {
            "generated_at": "2026-05-13T06:30:00Z",
            "ledger_action": "PAPER_INTENT_BLOCKED",
            "paper_result": "NO_FILL_RISK_BLOCKED",
            "risk_action": "deny",
            "risk_reason_code": "deny_orchestrator_held",
            "confidence": 0.53,
            "symbol": "BTCUSDT",
            "paper_realized_pnl": -1.02,
        },
    ]
    (paper_dir / "paper_events.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    status = build_observation_status(paper_dir=paper_dir, public_paper_dir=tmp_path / "missing", now=now)

    assert status["source"] == "V2_PAPER_RUNTIME_JSONL_EVENT"
    assert status["paper_events_count"] == 2
    assert status["simulated_fills"] == 1
    assert status["blocked_intents"] == 1
    assert status["latest_prediction_id"] == "pred_latest"
    assert status["paper_shadow_6h_status"] == "PAPER_SHADOW_6H_COMPLETE"
    assert status["paper_shadow_24h_status"] == "PAPER_SHADOW_24H_PENDING"
    assert status["profitability_proof_status"] == "PROFITABILITY_PROOF_PENDING"


def test_observation_falls_back_to_text_action_log(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    _write_json(paper_dir / "paper_runtime_status.json", {"runtime_state": "PAPER_RUNTIME_ONLINE_ACTIVE"})
    (paper_dir / "paper_online_runtime.log").write_text(
        "2026-05-13T06:58:00Z PAPER_RUNTIME_ONLINE_ACTIVE PAPER_FILL_SIMULATED\n"
        "2026-05-13T06:59:00Z PAPER_RUNTIME_ONLINE_ACTIVE PAPER_INTENT_BLOCKED\n"
    )

    status = build_observation_status(
        paper_dir=paper_dir,
        public_paper_dir=tmp_path / "missing",
        now=datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc),
    )

    assert status["source"] == "V2_PAPER_RUNTIME_TEXT_LOG_FALLBACK"
    assert status["paper_events_count"] == 2
    assert status["simulated_fills"] == 1
    assert status["blocked_intents"] == 1


def test_negative_pnl_blocks_profitability_proof_even_when_windows_complete(tmp_path: Path) -> None:
    paper_dir = tmp_path / "paper"
    now = datetime(2026, 5, 13, 7, 0, tzinfo=timezone.utc)
    _write_json(
        paper_dir / "paper_runtime_status.json",
        {
            "runtime_state": "PAPER_RUNTIME_ONLINE_ACTIVE",
            "freshness": {"runtime_age_seconds": 0},
            "paper_account": {"realized_pnl": -2.5},
            "paper_ledger_tail": [],
        },
    )
    events = [
        {
            "generated_at": "2026-05-12T06:00:00Z",
            "ledger_action": "PAPER_FILL_SIMULATED",
            "paper_result": "FILLED_PAPER_ONLY",
            "risk_action": "allow",
            "risk_reason_code": "allow_proceed_long",
            "confidence": 0.78,
            "symbol": "BTCUSDT",
            "paper_realized_pnl": -2.0,
        },
        {
            "generated_at": "2026-05-13T06:30:00Z",
            "ledger_action": "PAPER_FILL_SIMULATED",
            "paper_result": "FILLED_PAPER_ONLY",
            "risk_action": "allow",
            "risk_reason_code": "allow_proceed_short",
            "confidence": 0.79,
            "symbol": "BTCUSDT",
            "paper_realized_pnl": -2.5,
        },
    ]
    (paper_dir / "paper_events.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    status = build_observation_status(paper_dir=paper_dir, public_paper_dir=tmp_path / "missing", now=now)

    assert status["paper_shadow_6h_status"] == "PAPER_SHADOW_6H_COMPLETE"
    assert status["paper_shadow_24h_status"] == "PAPER_SHADOW_24H_COMPLETE"
    assert status["profitability_proof_status"] == "PROFITABILITY_PROOF_BLOCKED_NEGATIVE_PNL"
    assert status["profitability_proof_blockers"] == ["paper_pnl_negative"]
