from __future__ import annotations

import json
import hashlib
from pathlib import Path

from v2.backend.app.cli import run_real_inference_paper_batch as m1
from v2.backend.app.cli.run_real_inference_paper_batch import build_m1_report, main


class FakeRedis:
    def __init__(self, rows: dict[str, dict], *, ttls: dict[str, int] | None = None) -> None:
        self.rows = rows
        self.ttls = ttls or {}

    def get(self, key: str) -> str | None:
        value = self.rows.get(key)
        return json.dumps(value) if value is not None else None

    def scan_iter(self, match: str, count: int = 500):
        prefix = match.replace("*", "")
        for key in sorted(self.rows):
            if key.startswith(prefix):
                yield key

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, 120)


def _safe_live_rows() -> dict[str, dict]:
    safe = {
        "live_gate": "blocked_human_only",
        "order_transport_submit_enabled": False,
        "live_trading_enabled": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return {key: dict(safe) for key in m1.LIVE_CONTROL_KEYS}


def test_m1_no_go_when_only_proof_predictions_exist() -> None:
    client = FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": {
                "prediction_id": "p1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "confidence_raw": 0.0,
                "confidence_calibrated": 0.0,
                "confidence_source": "PROOF_DEFAULT",
                "proof_only": True,
                "model_consumable": False,
                "paper_intent_consumable": False,
                "routeability_candidate": False,
                "routes_to_live": False,
                "live_order_allowed": False,
            },
            **_safe_live_rows(),
        }
    )

    report = build_m1_report(client=client, symbols=("BTCUSDT",), max_predictions=50)

    assert report["m1_release_gate"]["verdict"] == "M1 NO-GO"
    assert report["m1_release_gate"]["reason"] == "CURRENT_RUNTIME_CONTRACT_INVALID"
    assert report["real_inference_batch_report"]["root_cause"] == (
        "PREDICTION_WRITER_ONLY_PROOF_PUBLISHER_FOR_CURRENT_CANONICAL_KEYS"
    )
    assert report["real_inference_batch_report"]["real_model_confidence_count"] == 0
    assert report["real_inference_batch_report"]["placeholder_or_default_confidence_count"] == 1


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _current_runtime_and_prediction_rows() -> dict[str, dict]:
    envelope = {
        "schema_version": "v2_native_trainer_current_cycle_learning_envelope_v1",
        "generated_utc": "2026-07-06T12:00:00Z",
        "cycle_id": "cycle_m1",
        "process_instance_id": "host:456:nonce",
        "checkpoint_id": "ckpt_m1",
        "candidate_policy_fingerprint": "a" * 64,
    }
    status = {
        **envelope,
        "runtime_readiness_status": "READY",
        "trainer_learning_ready": True,
        "status_publication_status": "ACTIVE",
        "status_payload_expires_at": "2026-07-06T12:10:00Z",
        "current_cycle_learning_envelope": envelope,
        "current_cycle_verified_serving_checkpoint_evidence": {
            "checkpoint_artifact_verified": True,
            "causal_order_verified": True,
            "exact_optimizer_contract_durable": True,
            "manager_semantic_verification_recomputed_this_cycle": True,
            "checkpoint_id": "ckpt_m1",
            "model_parameter_fingerprint": "a" * 64,
        },
    }
    prediction = {
        "prediction_id": "pred_m1_current",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "batch_run_id": "m1_run_current",
        "cycle_id": "cycle_m1",
        "process_instance_id": "host:456:nonce",
        "checkpoint_id": "ckpt_m1",
        "candidate_policy_fingerprint": "a" * 64,
        "confidence_source": "REAL_MODEL",
        "confidence_calibrated": 0.71,
        "confidence_calibration_fitted": True,
        "proof_only": False,
        "model_consumable": True,
        "paper_intent_consumable": True,
        "routeability_candidate": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "exchange_mutation": False,
        "trainer_direct_trading": False,
        "feature_cutoff": "2026-07-06T11:59:00Z",
        "masa_feature_cutoff": "2026-07-06T11:59:00Z",
        "ppo_feature_cutoff": "2026-07-06T11:59:00Z",
        "available_at": "2026-07-06T11:59:30Z",
        "decision_time": "2026-07-06T12:00:00Z",
        "generated_at": "2026-07-06T12:00:00Z",
        "candle_closed_confirmed": True,
        "source_hashes": {"feature_vector_hash": "b" * 64},
        "trust_gate_result": {"allowed": True},
        "replay_snapshot_write_success": True,
        "replay_snapshot_readback_verified": True,
        "routes_to_live": False,
        "live_order_allowed": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return {
        **_safe_live_rows(),
        m1.TRAINER_STATUS_KEY: status,
        m1.TRAINER_HEARTBEAT_KEY: {
            "generated_utc": "2026-07-06T12:00:00Z",
            "cycle_id": "cycle_m1",
            "process_instance_id": "host:456:nonce",
            "expires_at": "2026-07-06T12:10:00Z",
        },
        "v2:prediction:BTCUSDT:1m": prediction,
    }


def test_m1_executed_batch_receipt_contract(monkeypatch) -> None:
    monkeypatch.setattr(m1, "utc_now", lambda: "2026-07-06T12:01:00Z")
    rows = _current_runtime_and_prediction_rows()
    initial = build_m1_report(
        client=FakeRedis(rows),
        symbols=("BTCUSDT",),
        max_predictions=50,
    )
    validation = initial["real_inference_batch_report"]["batch_execution_receipt"]
    receipt = {
        "schema_version": "v2_real_inference_paper_batch_execution_receipt_v1",
        "run_id": "m1_run_current",
        "cycle_id": "cycle_m1",
        "process_instance_id": "host:456:nonce",
        "checkpoint_id": "ckpt_m1",
        "candidate_policy_fingerprint": "a" * 64,
        "completed_at": "2026-07-06T12:00:30Z",
        "expires_at": "2026-07-06T12:10:00Z",
        "safe_paper_execution_path_invoked": True,
        "paper_only": True,
        "routes_to_live": False,
        "outcome": "PASSED",
        "exit_code": 0,
        "runner_command": (
            ".venv/bin/pytest -q v2/backend/tests/unit/cli/"
            "test_run_real_inference_paper_batch.py::"
            "test_m1_executed_batch_receipt_contract"
        ),
        "pytest_nodeid": (
            "v2/backend/tests/unit/cli/test_run_real_inference_paper_batch.py::"
            "test_m1_executed_batch_receipt_contract"
        ),
        "production_source_sha256": validation["production_source_sha256"],
        "test_source_sha256": validation["test_source_sha256"],
        "prediction_ids": ["pred_m1_current"],
        "prediction_output_sha256": validation["prediction_output_sha256"],
        "symbols_requested": ["BTCUSDT"],
        "predictions_attempted": 1,
    }
    receipt["runner_command_sha256"] = hashlib.sha256(
        receipt["runner_command"].encode("utf-8")
    ).hexdigest()
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    rows[m1.BATCH_RECEIPT_KEY] = receipt

    report = build_m1_report(
        client=FakeRedis(rows),
        symbols=("BTCUSDT",),
        max_predictions=50,
    )

    assert report["m1_release_gate"]["verdict"] == "M1 GO"
    assert report["m1_release_gate"]["executed_batch_receipt_valid"] is True
    assert report["real_inference_batch_report"]["predictions_attempted"] == 1


def test_m1_stale_or_cross_cycle_real_model_row_cannot_go(monkeypatch) -> None:
    monkeypatch.setattr(m1, "utc_now", lambda: "2026-07-06T12:01:00Z")
    rows = _current_runtime_and_prediction_rows()
    rows["v2:prediction:BTCUSDT:1m"]["cycle_id"] = "stale_cycle"

    report = build_m1_report(
        client=FakeRedis(rows),
        symbols=("BTCUSDT",),
        max_predictions=50,
    )

    assert report["m1_release_gate"]["verdict"] == "M1 NO-GO"
    assert report["real_inference_batch_report"]["routeability_candidates"] == 0
    assert report["real_inference_batch_report"]["predictions_attempted"] == 0
    assert report["real_inference_batch_report"]["block_reason_distribution"][
        "CURRENT_RUNTIME_CYCLE_ID_MISMATCH"
    ] == 1


def test_m1_missing_live_control_key_is_not_inferred_safe(monkeypatch) -> None:
    monkeypatch.setattr(m1, "utc_now", lambda: "2026-07-06T12:01:00Z")
    rows = _current_runtime_and_prediction_rows()
    del rows["v2:live_order_transport:status"]

    report = build_m1_report(
        client=FakeRedis(rows),
        symbols=("BTCUSDT",),
        max_predictions=50,
    )

    assert report["m1_release_gate"]["reason"] == (
        "EXPLICIT_CURRENT_LIVE_DISABLE_EVIDENCE_MISSING_OR_UNSAFE"
    )
    assert report["m1_release_gate"]["live_submit_disabled"] is False


def test_m1_cli_requires_paper_only_and_no_live(tmp_path: Path) -> None:
    out = tmp_path / "out"

    assert main(["--redis-url", "redis://127.0.0.1:6379/0", "--output-dir", str(out)]) == 1

    gate = json.loads((out / "m1_release_gate.json").read_text(encoding="utf-8"))
    assert gate["reason"] == "PAPER_ONLY_AND_NO_LIVE_FLAGS_REQUIRED"
