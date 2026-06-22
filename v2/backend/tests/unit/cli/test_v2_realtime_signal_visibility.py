from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_realtime_signal_visibility as worker


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _minimal_payloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    public = tmp_path / "public"
    paths = {
        "paper_runtime": public / "operator_runtime/paper_online/latest/paper_runtime_status.json",
        "current_signal_lineage": public / "operator_runtime/paper_online/latest/current_signal_lineage.json",
        "trainer_prediction_record": public / "operator_runtime/paper_online/latest/trainer_prediction_current_record.json",
        "current_risk_decisions": public / "operator_runtime/paper_online/latest/current_risk_decisions.json",
        "paper_ledger_tail": public / "operator_runtime/paper_online/latest/paper_ledger_tail.json",
        "runtime_truth": public / "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
        "balance_hold": public / "v2_signed_read_recovered_balance_hold_and_first_order_resume/latest/operator_dashboard_payload.json",
        "symbol_universe": public / "operator_runtime/symbol_universe/latest/symbol_universe_status.json",
    }
    monkeypatch.setattr(worker, "PATHS", {**worker.PATHS, **paths})
    monkeypatch.setattr(worker, "PUBLIC_OUT", tmp_path / "out_public")
    monkeypatch.setattr(worker, "LOCAL_OUT", tmp_path / "out_local")

    generated = "2026-06-04T18:00:00-04:00"
    trainer = {
        "prediction_id": "pred_1",
        "feature_snapshot_id": "fs_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "generated_at": generated,
        "trainer_source": "V2_PAPER_TRAINER_WRAPPER",
        "model_checkpoint": "ckpt_1",
        "confidence_raw": 0.81,
        "confidence_calibrated": 0.79,
        "expected_move_bps": None,
        "raw_output": {"side": "long"},
    }
    lineage = {
        "generated_at": generated,
        "lineage_ids": {
            "prediction_id": "pred_1",
            "risk_decision_id": "risk_1",
            "orchestrator_decision_id": "orch_1",
            "execution_intent_id": "pei_1",
        },
        "signal": {
            "signal_id": "sig_1",
            "prediction_id": "pred_1",
            "symbol": "BTCUSDT",
            "proposed_action": "open_long",
            "confidence_calibrated": 0.79,
            "generated_at": generated,
        },
        "risk_decision": {
            "risk_decision_id": "risk_1",
            "risk_result": "BLOCKED",
            "risk_reason_code": "deny_expected_move_missing",
            "generated_at": generated,
        },
        "orchestrator_decision": {
            "orchestrator_decision_id": "orch_1",
            "decision_action": "open_long",
            "generated_at": generated,
        },
        "execution_intent": {"execution_intent_id": "pei_1", "generated_at": generated},
        "feature_snapshot": {"feature_snapshot_id": "fs_1", "missing_feature_flags": [], "stale_feature_flags": []},
    }
    paper_runtime = {
        "generated_at": generated,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "market_feed": {"symbol": "BTCUSDT", "price": 100.0, "generated_at": generated},
        "trainer_prediction": trainer,
        "current_signal_lineage": lineage,
        "current_risk_decision": lineage["risk_decision"],
        "paper_ledger_tail": [
            {
                "paper_ledger_entry_id": "pledger_1",
                "execution_intent_id": "pei_1",
                "risk_decision_id": "risk_1",
                "signal_id": "sig_1",
                "paper_result": "NO_FILL_RISK_BLOCKED",
                "generated_at": generated,
                "live_order": False,
            }
        ],
    }
    _write(paths["paper_runtime"], paper_runtime)
    _write(paths["trainer_prediction_record"], trainer)
    _write(paths["current_signal_lineage"], lineage)
    _write(paths["current_risk_decisions"], {"generated_at": generated, "decisions": [lineage["risk_decision"]]})
    _write(paths["paper_ledger_tail"], {"generated_at": generated, "entries": paper_runtime["paper_ledger_tail"]})
    _write(
        paths["runtime_truth"],
        {
            "generated_at": generated,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
        },
    )
    _write(
        paths["balance_hold"],
        {
            "generated_at": generated,
            "live_gate": "blocked_human_only",
            "accepted_symbols": [],
        },
    )
    _write(paths["symbol_universe"], {"generated_at": generated, "paper_symbols": ["BTCUSDT", "ETHUSDT"], "training_symbols": ["BTCUSDT", "ETHUSDT"]})


def test_all_timeframe_contract_keeps_missing_rows_visible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_payloads(tmp_path, monkeypatch)

    payload = worker.build_payload(worker.parse_args(["--no-write", "--production-base-url", "http://127.0.0.1:9", "--routes", "/signals"]))
    rows = payload["prediction_contract"]["prediction_rows"]

    assert payload["safety"]["live_gate"] == "blocked_human_only"
    assert payload["safety"]["live_symbols"] == []
    assert payload["safety"]["execution_live_symbols"] == []
    assert any(row["symbol"] == "BTCUSDT" and row["timeframe"] == "1m" and row["status"] == "PRESENT_CURRENT" for row in rows)
    missing = [row for row in rows if row["status"] == "MISSING_TF_PREDICTION"]
    assert missing
    assert payload["prediction_contract"]["status"] == "MISSING_TF_PREDICTION"
    assert payload["summary"]["present_prediction_count"] == 1


def test_price_target_formula_validates_direction() -> None:
    long_target = worker.price_targets(100.0, 25.0, 20.0, "long")
    short_target = worker.price_targets(100.0, -25.0, -20.0, "short")

    assert long_target["validation_status"] == "VALID"
    assert long_target["price_target"] == 100.25
    assert short_target["validation_status"] == "VALID"
    assert short_target["price_target"] == 99.75


def test_writes_expected_public_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_payloads(tmp_path, monkeypatch)
    payload = worker.build_payload(worker.parse_args(["--no-write", "--production-base-url", "http://127.0.0.1:9", "--routes", "/signals"]))

    worker.write_outputs(payload)

    for filename in (
        "signals_payload.json",
        "realtime_signal_runtime_source_inventory.json",
        "realtime_prediction_all_tf_contract_status.json",
        "price_target_generation_status.json",
        "realtime_signal_publisher_status.json",
        "realtime_signal_lineage_status.json",
        "website_deployment_truth_status.json",
    ):
        assert (tmp_path / "out_public" / filename).exists()
        assert (tmp_path / "out_local" / filename).exists()


def test_worker_source_has_no_exchange_or_redis_mutation_tokens() -> None:
    source = Path(worker.__file__).read_text()
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures" + "_change" + "_leverage",
        "futures" + "_change" + "_margin_type",
        "xtrim",
        "flushdb",
        "redis.Redis(",
        ".set(",
        ".xadd(",
    ]
    for token in forbidden:
        assert token not in source
