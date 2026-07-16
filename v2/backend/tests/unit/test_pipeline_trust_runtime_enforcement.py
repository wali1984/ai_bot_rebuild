from __future__ import annotations

import fnmatch
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from app.cli.export_pipeline_trust_evidence import export_pipeline_trust_evidence
from app.cli.verify_pipeline_trust import main as verify_main
from app.services.market_state_integrity.scoring import score_market_state
from app.services.market_state_integrity.trust import (
    TRUST_SCHEMA_VERSION,
    is_active_runtime_record,
    validate_prediction_trust_contract,
)
from app.services.native_trainer.hybrid_cuda_trainer.data_loader import TrainingExample
from app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import V2HybridPPOTrainer
from app.services.native_trainer.hybrid_cuda_trainer.publisher import build_prediction_payload
from app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import _latest_kline

BASE_MS = 1_700_000_000_000
CLOSE_MS = BASE_MS + 3_600_000
DECISION_MS = CLOSE_MS + 1_000
ISO_OPEN = "2026-06-11T00:00:00Z"
ISO_CLOSE = "2026-06-11T00:01:00Z"
ISO_DECISION = "2026-06-11T00:01:01Z"


class FakeRedis:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.write_calls: list[str] = []

    def scan_iter(self, match: str, count: int = 250):
        del count
        for key in sorted(self.data):
            if fnmatch.fnmatch(key, match):
                yield key

    def type(self, key: str) -> str:
        value = self.data[key]
        if isinstance(value, dict):
            return "hash" if value.get("__redis_type") == "hash" else "string"
        if isinstance(value, list):
            return "list"
        return "string"

    def get(self, key: str) -> str:
        return json.dumps(self.data[key])

    def hgetall(self, key: str) -> dict[str, str]:
        value = dict(self.data[key])
        value.pop("__redis_type", None)
        return {k: json.dumps(v) for k, v in value.items()}

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        return [json.dumps(v) for v in self.data[key][start : end + 1]]

    def xrevrange(self, key: str, count: int = 1000):
        del key, count
        return []

    def zrange(self, key: str, start: int, end: int) -> list[str]:
        return self.lrange(key, start, end)

    def smembers(self, key: str) -> set[str]:
        return {json.dumps(v) for v in self.data[key]}

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        self.write_calls.append("set")
        raise AssertionError("exporter must not mutate redis")

    def hset(self, *_args: Any, **_kwargs: Any) -> None:
        self.write_calls.append("hset")
        raise AssertionError("exporter must not mutate redis")

    def xadd(self, *_args: Any, **_kwargs: Any) -> None:
        self.write_calls.append("xadd")
        raise AssertionError("exporter must not mutate redis")


def candle(tf: str, open_time: int, *, closed: bool = True) -> dict[str, Any]:
    tf_ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}[tf]
    return {
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "timeframe": tf,
        "open_time": open_time,
        "close_time": open_time + tf_ms,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
        "closed_candle": closed,
        "is_closed": closed,
        "available_at": open_time + tf_ms,
        "event_time": open_time + tf_ms,
    }


def clean_records(*, feature_overrides: dict[str, Any] | None = None, decision_overrides: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    feature = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": "pipeline_trust_v3_20260612",
        "producer": "test_fixture",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": DECISION_MS,
        "decision_id": "p1",
        "prediction_id": "p1",
        "mtf_snapshot_id": "mtf-p1",
        "replay_snapshot_id": "snap-p1",
        "all_tf_candle_timestamps": [CLOSE_MS],
        "trainer_consumable": True,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "generated_at": DECISION_MS,
        "feature_cutoff": CLOSE_MS,
        "available_at": CLOSE_MS,
        "source_candle_timestamps": [CLOSE_MS],
        "features": {"ret_pct": 0.01},
    }
    if feature_overrides:
        feature.update(feature_overrides)
    decision = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": "pipeline_trust_v3_20260612",
        "producer": "test_fixture",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": DECISION_MS,
        "prediction_id": "p1",
        "decision_id": "p1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": DECISION_MS,
        "available_at": CLOSE_MS,
        "feature_cutoff": CLOSE_MS,
        "all_tf_candle_timestamps": [CLOSE_MS],
        "prediction_eligible": True,
        "masa_generated_at": CLOSE_MS,
        "masa_feature_cutoff": CLOSE_MS,
        "masa_forecast_horizon": "1m",
        "ppo_observation_time": CLOSE_MS,
        "ppo_feature_cutoff": CLOSE_MS,
        "selected_action": "hold",
        "masa_signal": 0.5,
        "replay_snapshot_id": "snap-p1",
        "replay_snapshot_write_success": True,
        "mtf_snapshot_id": "mtf-p1",
        "mtf_snapshot_valid": True,
    }
    if decision_overrides:
        decision.update(decision_overrides)
    return {
        "candles": [
            candle("1h", CLOSE_MS - 3_600_000),
            candle("4h", CLOSE_MS - 14_400_000),
            candle("15m", CLOSE_MS - 900_000),
            candle("5m", CLOSE_MS - 300_000),
            candle("1m", CLOSE_MS - 60_000),
        ],
        "features": [feature],
        "masa_ppo": [decision],
        "training_samples": [
            {
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "enforcement_epoch": "pipeline_trust_v3_20260612",
                "producer": "test_fixture",
                "producer_version": TRUST_SCHEMA_VERSION,
                "sample_id": "s1",
                "decision_id": "p1",
                "prediction_id": "p1",
                "mtf_snapshot_id": "mtf-p1",
                "replay_snapshot_id": "snap-p1",
                "row_classification": "TRAINABLE",
                "used_for_training": True,
                "accepted_for_training": True,
                "feature_cutoff": CLOSE_MS,
                "label_start_time": CLOSE_MS,
                "label_end_time": CLOSE_MS + 60_000,
                "prediction_horizon_seconds": 60,
                "features": {"ret_pct": 0.01},
                "fee_bps": 5,
                "slippage_bps": 2,
            }
        ],
        "execution_records": [{"position_before": "flat", "requested_action": "hold", "position_after": "flat", "fill_status": "hold"}],
        "positions": [{"symbol": "BTCUSDT", "local_position": "flat", "exchange_position": "flat"}],
        "config_admin": [
            {
                "live_gate": "blocked_human_only",
                "dangerous_settings_pending_approval": [],
                "approval_token_created": False,
                "approval_token_self_creatable": False,
                "secrets_written_to_payload": False,
                "old_redis_write": False,
                "exchange_action_taken": False,
                "leverage_or_margin_change": False,
                "settings_by_risk_class": {"safe": 1},
            }
        ],
        "replay_snapshots": [{"decision_id": "p1", "prediction_id": "p1", "mtf_snapshot_id": "mtf-p1"}],
    }


def write_exported_style(tmp_path: Path, records: dict[str, list[dict[str, Any]]]) -> Path:
    run_dir = tmp_path / "evidence" / "20260611_000000"
    run_dir.mkdir(parents=True)
    file_names = {
        "candles": "candles.jsonl",
        "features": "features.jsonl",
        "masa_ppo": "masa_ppo.jsonl",
        "training_samples": "training_samples.jsonl",
        "execution_records": "execution_records.jsonl",
        "positions": "positions.jsonl",
        "config_admin": "config_admin.jsonl",
        "replay_snapshots": "replay_snapshots.jsonl",
    }
    for category, rows in records.items():
        with (run_dir / file_names[category]).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps({"redis_key": f"v2:test:{category}", "category": category, "value": row}))
                handle.write("\n")
    (run_dir / "manifest.json").write_text(json.dumps({"no_secrets": True}), encoding="utf-8")
    return run_dir


def run_verify(run_dir: Path) -> tuple[int, dict[str, Any]]:
    out = run_dir / "report"
    code = verify_main(["--input", str(run_dir), "--output-dir", str(out), "--strict-unknown"])
    return code, json.loads((out / "pipeline_trust_report.json").read_text(encoding="utf-8"))


def assert_finding(report: dict[str, Any], check_id: str) -> None:
    assert check_id in {item["check_id"] for item in report["findings"]}


def trusted_active_risk_record(**overrides: Any) -> dict[str, Any]:
    row = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": "pipeline_trust_v3_20260612",
        "producer": "test_fixture",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": DECISION_MS,
        "risk_decision_id": "rd-p1",
        "decision_id": "p1",
        "prediction_id": "p1",
        "mtf_snapshot_id": "mtf-p1",
        "replay_snapshot_id": "snap-p1",
        "replay_snapshot_write_success": True,
        "feature_cutoff": CLOSE_MS,
        "available_at": CLOSE_MS,
        "all_tf_candle_timestamps": [CLOSE_MS],
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "risk_action": "allow",
        "pre_trade_allowed": True,
        "risk_eligible": True,
        "paper_eligible": True,
    }
    row.update(overrides)
    return row


def test_runtime_evidence_export_is_read_only_and_redacts_secrets(tmp_path: Path) -> None:
    client = FakeRedis(
        {
            "v2:features:latest:BTCUSDT:1m": {"features": {"ret_pct": 0.01}, "api_key": "raw-secret"},
            "v2:market:ohlcv:binance:BTCUSDT:1m": [candle("1m", CLOSE_MS - 60_000)],
        }
    )

    run_dir = export_pipeline_trust_evidence(
        client=client,
        redis_url="redis://:supersecret@example.invalid:6379/0",
        output_root=tmp_path,
    )

    assert client.write_calls == []
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert "supersecret" not in json.dumps(manifest)
    assert manifest["no_secrets"] is True
    assert "raw-secret" not in (run_dir / "features.jsonl").read_text(encoding="utf-8")
    assert "[REDACTED]" in (run_dir / "features.jsonl").read_text(encoding="utf-8")


def test_replay_snapshot_exporter_sees_publisher_written_snapshot(tmp_path: Path) -> None:
    client = FakeRedis(
        {
            "v2:replay:snapshots:p1": {
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "decision_id": "p1",
                "prediction_id": "p1",
                "mtf_snapshot_id": "mtf-p1",
                "replay_snapshot_id": "snap-p1",
                "feature_cutoff": ISO_CLOSE,
                "available_at": ISO_CLOSE,
                "all_tf_candle_timestamps": [ISO_CLOSE],
            },
            "v2:market:mtf_snapshot:p1": {
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "decision_id": "p1",
                "prediction_id": "p1",
                "mtf_snapshot_id": "mtf-p1",
                "feature_cutoff": ISO_CLOSE,
                "available_at": ISO_CLOSE,
                "all_tf_candle_timestamps": [ISO_CLOSE],
            },
        }
    )

    run_dir = export_pipeline_trust_evidence(
        client=client,
        redis_url="redis://example.invalid:6379/0",
        output_root=tmp_path,
    )

    replay_rows = [
        json.loads(line)
        for line in (run_dir / "replay_snapshots.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["redis_key"] for row in replay_rows} == {
        "v2:market:mtf_snapshot:p1",
        "v2:replay:snapshots:p1",
    }


def test_runtime_evidence_export_skips_legacy_binance_candles_when_canonical_exists(tmp_path: Path) -> None:
    client = FakeRedis(
        {
            "v2:market:ohlcv:binance:BTCUSDT:1m": [[CLOSE_MS - 60_000, "100", "101", "99", "100.5", "12", CLOSE_MS]],
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": [candle("1m", CLOSE_MS - 60_000)],
        }
    )

    run_dir = export_pipeline_trust_evidence(
        client=client,
        redis_url="redis://example.invalid:6379/0",
        output_root=tmp_path,
    )

    candle_rows = [
        json.loads(line)
        for line in (run_dir / "candles.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["redis_key"] for row in candle_rows} == {"v2:market:ohlcv_closed:binance:BTCUSDT:1m"}


def test_strict_verifier_passes_clean_exported_style_evidence(tmp_path: Path) -> None:
    run_dir = write_exported_style(tmp_path, clean_records())

    code, report = run_verify(run_dir)

    assert code == 0
    assert report["summary"]["critical_failures"] == 0
    assert sum(1 for _ in (run_dir / "replay_snapshots.jsonl").open()) > 0


def test_strict_verifier_fails_unfinished_exported_higher_timeframe_candle(tmp_path: Path) -> None:
    records = clean_records()
    records["candles"][0] = candle("1h", CLOSE_MS - 3_600_000, closed=False)
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "mtf_alignment.unfinished_higher_tf")


def test_strict_verifier_fails_missing_available_at(tmp_path: Path) -> None:
    run_dir = write_exported_style(tmp_path, clean_records(feature_overrides={"available_at": None}))

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "feature_integrity.missing_available_at")


def test_strict_verifier_fails_missing_feature_cutoff(tmp_path: Path) -> None:
    run_dir = write_exported_style(tmp_path, clean_records(feature_overrides={"feature_cutoff": None}))

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "feature_integrity.missing_feature_cutoff")


def test_feature_available_after_cutoff_before_decision_is_not_future_leakage(tmp_path: Path) -> None:
    run_dir = write_exported_style(
        tmp_path,
        clean_records(
            feature_overrides={
                "feature_cutoff": CLOSE_MS,
                "available_at": CLOSE_MS + 500,
                "generated_at": DECISION_MS,
                "source_candle_timestamps": [CLOSE_MS],
            }
        ),
    )

    code, report = run_verify(run_dir)

    assert code == 0
    assert "feature_integrity.future_use" not in {item["check_id"] for item in report["findings"]}


def test_trainer_row_accepted_false_fails_if_used(tmp_path: Path) -> None:
    records = clean_records()
    records["training_samples"][0]["accepted_for_training"] = False
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "training_samples.dirty_accepted")


def test_unreplayable_training_sample_fails_if_used(tmp_path: Path) -> None:
    records = clean_records()
    records["training_samples"][0]["replay_snapshot_id"] = None
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "training_samples.dirty_accepted")


def test_quarantined_training_sample_fails_if_used(tmp_path: Path) -> None:
    records = clean_records()
    records["training_samples"][0]["quarantined"] = True
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "training_samples.dirty_accepted")


def test_prediction_without_replay_snapshot_fails_in_strict_mode(tmp_path: Path) -> None:
    run_dir = write_exported_style(
        tmp_path,
        clean_records(decision_overrides={"replay_snapshot_id": None, "replay_snapshot_write_success": False}),
    )

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "replay_snapshot.missing")


def test_strict_verifier_fails_missing_mtf_snapshot_metadata(tmp_path: Path) -> None:
    run_dir = write_exported_style(
        tmp_path,
        clean_records(decision_overrides={"mtf_snapshot_id": None, "mtf_snapshot_valid": None}),
    )

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "mtf_snapshot.missing")


def test_exported_feature_snapshot_with_trainer_consumable_is_not_training_sample(tmp_path: Path) -> None:
    run_dir = write_exported_style(
        tmp_path,
        clean_records(feature_overrides={"trainer_consumable": True, "missing_feature_flags": []}),
    )

    code, report = run_verify(run_dir)

    assert code == 0
    assert_finding(report, "feature_integrity.pass")
    assert "training_samples.dirty_accepted" not in {item["check_id"] for item in report["findings"]}


def test_denied_risk_record_does_not_require_prediction_snapshot_evidence(tmp_path: Path) -> None:
    records = clean_records()
    records["execution_records"].append(
        {
            "risk_decision_id": "rd-denied",
            "prediction_id": "pred-denied",
            "symbol": "BTCUSDT",
            "pre_trade_allowed": False,
            "fee_gate_allowed": False,
            "risk_manager_final_authority": True,
        }
    )
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code == 0
    assert "replay_snapshot.missing" not in {item["check_id"] for item in report["findings"]}
    assert "mtf_snapshot.missing" not in {item["check_id"] for item in report["findings"]}


def test_closed_previous_paper_fill_is_inactive_stale_not_active_critical(tmp_path: Path) -> None:
    records = clean_records()
    stale_fill = {
        "prediction_id": "old-pred-1",
        "intent_id": "old-intent-1",
        "symbol": "BTCUSDT",
        "decision": "ACCEPTED_PAPER_FILL",
        "paper_fill_allowed": True,
        "pre_trade_allowed": True,
        "valid_for_paper": True,
        "paper_lifecycle_status": "CLOSED_PREVIOUSLY",
        "paper_fill_persistence_status": "EXISTING_FILL_CARRIED_FORWARD",
    }
    assert is_active_runtime_record(stale_fill) is False
    records["execution_records"].append(stale_fill)
    records["positions"].append(stale_fill)
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code == 0
    check_ids = {item["check_id"] for item in report["findings"]}
    assert "runtime_trust.active_stale_missing_contract" not in check_ids
    assert "replay_snapshot.missing" not in check_ids
    assert "mtf_snapshot.missing" not in check_ids


def test_active_approved_risk_record_without_replay_snapshot_fails(tmp_path: Path) -> None:
    records = clean_records()
    records["execution_records"].append(
        trusted_active_risk_record(replay_snapshot_id=None, replay_snapshot_write_success=False)
    )
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "runtime_trust.active_stale_missing_contract")


def test_active_approved_risk_record_without_mtf_snapshot_fails(tmp_path: Path) -> None:
    records = clean_records()
    records["execution_records"].append(trusted_active_risk_record(mtf_snapshot_id=None))
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "runtime_trust.active_stale_missing_contract")


def test_pre_trade_allowed_record_without_trust_schema_fails(tmp_path: Path) -> None:
    records = clean_records()
    stale = trusted_active_risk_record()
    stale.pop("trust_schema_version")
    records["execution_records"].append(stale)
    run_dir = write_exported_style(tmp_path, records)

    code, report = run_verify(run_dir)

    assert code != 0
    assert_finding(report, "runtime_trust.active_stale_missing_contract")


def test_alternate_risk_writer_cannot_approve_without_snapshot_evidence() -> None:
    result = validate_prediction_trust_contract(
        {
            "trust_schema_version": TRUST_SCHEMA_VERSION,
            "decision_id": "d1",
            "prediction_id": "p1",
            "feature_cutoff": CLOSE_MS,
            "available_at": CLOSE_MS,
            "all_tf_candle_timestamps": [CLOSE_MS],
            "risk_action": "allow",
            "pre_trade_allowed": True,
        },
        require_replay_write=True,
    )

    assert result.allowed is False
    assert "TRUST_SNAPSHOT_MISSING" in result.reject_reasons


def test_stale_pre_enforcement_prediction_cannot_route_to_paper() -> None:
    result = validate_prediction_trust_contract(
        {"prediction_id": "old-p1", "routed_to_paper": True, "paper_fill_allowed": True},
        require_replay_write=True,
    )

    assert result.allowed is False
    assert "TRUST_SCHEMA_MISSING" in result.reject_reasons


def tensor() -> SimpleNamespace:
    return SimpleNamespace(
        feature_snapshot_id="feature-1",
        tensor_id="tensor-1",
        model_vector=[0.1],
        values=[0.1],
        feature_names=["ret_pct"],
        missing_feature_names=[],
        stale_feature_names=[],
        # Real FeatureTensorRecord carries a per-feature missing mask
        # (tensor_builder.py); the publisher's feature-view merge reads it.
        missing_mask=[0],
        data_coverage_percent=100.0,
        source_availability_vector=[1.0],
        source_labels=["synthetic"],
    )


def trust_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": "pipeline_trust_v3_20260612",
        "producer": "test_fixture",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": ISO_DECISION,
        "sample_id": "row-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "feature-1",
        "feature_vector_hash": "tensor-1",
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "candle_closed_confirmed": True,
        "candle_open_time": ISO_OPEN,
        "candle_close_time": ISO_CLOSE,
        "source_event_time_est": ISO_CLOSE,
        "source_received_time_est": ISO_CLOSE,
        "source_available_time": ISO_CLOSE,
        "available_at": ISO_CLOSE,
        "feature_cutoff": ISO_CLOSE,
        "decision_time_est": ISO_DECISION,
        "masa_feature_cutoff": ISO_CLOSE,
        "ppo_feature_cutoff": ISO_CLOSE,
        "all_tf_candle_timestamps": [ISO_CLOSE],
        "all_source_event_times": [ISO_CLOSE],
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "mtf_snapshot_id": "mtf-1",
        "replay_snapshot_id": "replay-1",
        "mtf_snapshot_valid": True,
        "mtf_snapshot_reject_reasons": [],
        "features": {"ret_pct": 0.1},
        "latency_ms": 100,
    }
    row.update(overrides)
    return row


def example(**trust_overrides: Any) -> TrainingExample:
    row_classification = str(trust_overrides.pop("row_classification", "TRAINABLE"))
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor(),
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=("v2:test",),
        row_classification=row_classification,
        trust_row=trust_row(**trust_overrides),
    )


class FakeModel:
    torch_available = False
    cuda_active = False
    torch = None
    input_dim = 1
    device = "cpu"

    def forward(self, _tensor: Any) -> SimpleNamespace:
        return SimpleNamespace(action_probabilities=[1.0, 0.0, 0.0], expected_move_bps=0.0)


def test_ppo_trainer_excludes_dirty_rows_before_training() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train(
        [
            example(
                old_log_prob=-0.1,
                old_value=0.0,
                reward=0.2,
                done=False,
                rollout_id="rollout-1",
                trajectory_index=0,
            ),
            example(accepted_for_training=False),
        ],
        batch_size=4,
    )

    assert result.train_rows == 1
    assert result.metrics["training_rejection_count"] == 1
    assert "EXPLICIT_ACCEPTED_FOR_TRAINING_FALSE" in result.metrics["training_rejection_reason_counts"]


def test_ppo_trainer_cannot_train_without_snapshot_id() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train([example(mtf_snapshot_id=None)], batch_size=4)

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert "MTF_SNAPSHOT_ID_MISSING" in result.metrics["training_rejection_reason_counts"]


def test_ppo_trainer_cannot_train_without_replay_snapshot_id() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train([example(replay_snapshot_id=None)], batch_size=4)

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert "REPLAY_SNAPSHOT_ID_MISSING" in result.metrics["training_rejection_reason_counts"]


def test_ppo_trainer_rejects_quarantined_evidence() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train([example(quarantined=True, positive_training_sample=True)], batch_size=4)

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert "QUARANTINED_EVIDENCE" in result.metrics["training_rejection_reason_counts"]


def test_ppo_trainer_does_not_train_when_all_rows_rejected() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train([example(candle_closed_confirmed=None)], batch_size=4)

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert result.train_rows == 0
    assert result.training_steps == 0


def test_ppo_trainer_accepts_optional_masked_feature_gaps() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train(
        [
                example(
                    row_classification="MISSING_MASKED",
                    missing_feature_names=["funding_rate", "liquidation_distance_pct", "aicoin_score"],
                    missing_feature_count=3,
                    features={"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "ret_pct": 0.1},
                    old_log_prob=-0.1,
                    old_value=0.0,
                    reward=0.2,
                    done=False,
                    rollout_id="rollout-1",
                    trajectory_index=0,
                )
            ],
            batch_size=4,
    )

    assert result.status != "NO_TRUSTED_TRAINING_ROWS"
    assert result.train_rows == 1
    assert "ROW_CLASSIFICATION_MISSING_MASKED" not in result.metrics["training_rejection_reason_counts"]


def test_ppo_trainer_accepts_historical_replay_missing_mask_without_weakening_live_integrity() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train(
        [
            example(
                row_source="trusted_replay_archive",
                update_lane="OUTCOME_SUPERVISED_TRUSTED_REPLAY",
                trainer_feedback_source="V2_DURABLE_FEATURE_SNAPSHOT_TRUSTED_REPLAY",
                row_classification="MISSING_MASKED",
                missing_feature_names=["critical_family_absent:orderbook_depth"],
                missing_feature_count=1,
                features={
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "ret_pct": 0.1,
                },
                safe_to_train_with_missing_mask=True,
                safe_missing_mask_training_scope="HISTORICAL_REPLAY_ONLY",
                feature_family_introduced_after_snapshot_time=True,
                source_availability={"ohlcv": {"available_at": ISO_CLOSE}},
                source_availability_recorded=True,
                lineage_mask_present=True,
                classification_mask_present=True,
                historical_replay_row=True,
                trusted_replay_row=True,
                old_log_prob=-0.1,
                old_value=0.0,
                reward=0.2,
                done=False,
                rollout_id="rollout-1",
                trajectory_index=0,
            )
        ],
        batch_size=4,
    )

    assert result.status != "NO_TRUSTED_TRAINING_ROWS"
    assert result.train_rows == 1
    reasons = result.metrics["training_rejection_reason_counts"]
    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in reasons
    assert "ROW_CLASSIFICATION_MISSING_MASKED" not in reasons
    assert result.metrics["trusted_replay_rows_loaded"] == 1
    assert result.metrics["policy_sampled_rows_seen"] == 1


def test_ppo_trainer_rejects_historical_missing_mask_when_stale() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train(
        [
            example(
                row_source="trusted_replay_archive",
                update_lane="OUTCOME_SUPERVISED_TRUSTED_REPLAY",
                row_classification="MISSING_MASKED",
                missing_feature_names=["critical_family_absent:orderbook_depth"],
                missing_feature_count=1,
                stale_feature_names=["funding_rate"],
                stale_feature_count=1,
                features={
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "ret_pct": 0.1,
                },
                safe_to_train_with_missing_mask=True,
                safe_missing_mask_training_scope="HISTORICAL_REPLAY_ONLY",
                feature_family_introduced_after_snapshot_time=True,
                source_availability={"ohlcv": {"available_at": ISO_CLOSE}},
                source_availability_recorded=True,
                lineage_mask_present=True,
                classification_mask_present=True,
                historical_replay_row=True,
                trusted_replay_row=True,
                old_log_prob=-0.1,
                old_value=0.0,
                reward=0.2,
                done=False,
                rollout_id="rollout-1",
                trajectory_index=0,
            )
        ],
        batch_size=4,
    )

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    reasons = result.metrics["training_rejection_reason_counts"]
    assert "STALE_FEATURE_FAMILY" in reasons
    diagnostics = result.metrics["training_rejection_family_diagnostics"]
    assert diagnostics[0]["unsafe_to_train_reason"] == "STALE_FEATURE_FAMILY"


def model_output(**overrides: Any) -> SimpleNamespace:
    payload = {
        "selected_action": "hold",
        "selected_action_index": 0,
        "action_probabilities": [1.0, 0.0, 0.0],
        "expected_move_bps": 10.0,
        "confidence_raw": 0.9,
        "confidence_calibrated": 0.9,
        "calibration": "synthetic",
        "policy_value": 0.0,
        "masa_signal": 0.5,
        "model_id": "model-1",
        "device": "cpu",
        "cuda_active": False,
        "model_tensors_device_verified": False,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_prediction_payload_publishes_top_level_trust_metadata() -> None:
    payload = build_prediction_payload(
        example=example(),
        model_output=model_output(),
        checkpoint=None,
        round_trip_cost_bps=0.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.1,
        min_edge_after_cost_bps=1.0,
    )

    assert payload["generated_utc"].endswith("Z")
    assert payload["generated_at"] == payload["generated_utc"]
    assert payload["decision_time"] == payload["generated_utc"]
    assert payload["available_at"] == ISO_CLOSE
    assert payload["feature_decision_time"] == ISO_DECISION
    assert payload["model_version"] == payload["model_source"]
    assert payload["checkpoint_id"] == "v2_hybrid_checkpoint_manifest_pending"
    assert payload["source_hashes"]["feature_vector_hash"] == payload["feature_vector_hash"]
    assert payload["source_hashes"]["input_feature_hash"] == payload["feature_vector_hash"]
    assert payload["source_hashes"]["feature_tensor_id"] == "tensor-1"
    assert payload["source_hashes"]["feature_names_hash"]
    assert payload["source_hashes"]["source_timestamp_hash"]
    replay = payload["replay_snapshot"]
    assert replay["prediction_id"] == payload["prediction_id"]
    assert replay["signal_id"] == payload["signal_id"]
    assert replay["decision_id"] == payload["decision_id"]
    assert replay["feature_snapshot_id"] == payload["feature_snapshot_id"]
    assert replay["feature_snapshot"]["feature_snapshot_id"] == payload["feature_snapshot_id"]
    assert replay["feature_snapshot"]["features"] == {"ret_pct": 0.1}
    assert replay["selected_action"] == payload["selected_action"]
    assert replay["model_version"] == payload["model_version"]
    assert replay["checkpoint_id"] == payload["checkpoint_id"]
    assert replay["source_hashes"] == payload["source_hashes"]


def test_prediction_payload_neutralizes_non_directional_after_cost_edge() -> None:
    payload = build_prediction_payload(
        example=example(),
        model_output=model_output(expected_move_bps=-120.0),
        checkpoint=None,
        round_trip_cost_bps=12.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.1,
        min_edge_after_cost_bps=1.0,
    )

    assert payload["selected_action"] == "hold"
    assert payload["expected_move_bps"] == -120.0
    assert payload["expected_move_after_cost_bps"] == 0.0
    assert payload["paper_fill_allowed"] is False
    assert "action_not_directional" in payload["paper_fill_gate_block_reasons"]


def test_prediction_payload_short_after_cost_moves_toward_zero() -> None:
    payload = build_prediction_payload(
        example=example(),
        model_output=model_output(
            selected_action="short",
            selected_action_index=2,
            action_probabilities=[0.05, 0.05, 0.9],
            expected_move_bps=-120.0,
        ),
        checkpoint=None,
        round_trip_cost_bps=12.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.1,
        min_edge_after_cost_bps=1.0,
    )

    assert payload["selected_action"] == "short"
    assert payload["expected_move_after_cost_bps"] == -108.0
    assert payload["paper_fill_allowed"] is True
    assert payload["paper_fill_gate_block_reasons"] == []


def test_prediction_payload_blocks_directional_sign_mismatch_after_costs() -> None:
    payload = build_prediction_payload(
        example=example(),
        model_output=model_output(
            selected_action="short",
            selected_action_index=2,
            action_probabilities=[0.05, 0.05, 0.9],
            expected_move_bps=-4.0,
        ),
        checkpoint=None,
        round_trip_cost_bps=12.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.1,
        min_edge_after_cost_bps=1.0,
    )

    assert payload["expected_move_after_cost_bps"] == 8.0
    assert payload["paper_fill_allowed"] is False
    assert "expected_move_after_cost_direction_mismatch" in payload["paper_fill_gate_block_reasons"]


def test_prediction_blocks_when_replay_snapshot_evidence_is_missing() -> None:
    payload = build_prediction_payload(
        example=example(all_tf_candle_timestamps=[], all_source_event_times=[]),
        model_output=model_output(),
        checkpoint=None,
        round_trip_cost_bps=0.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.1,
        min_edge_after_cost_bps=1.0,
    )

    assert payload["paper_fill_allowed"] is False
    assert payload["replay_snapshot_ready"] is False
    assert "replay_snapshot:ALL_TIMEFRAME_CANDLE_TIMESTAMPS_MISSING" in payload["paper_fill_gate_block_reasons"]


def test_prediction_blocks_without_snapshot_id() -> None:
    payload = build_prediction_payload(
        example=example(mtf_snapshot_id=None),
        model_output=model_output(),
        checkpoint=None,
        round_trip_cost_bps=0.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.1,
        min_edge_after_cost_bps=1.0,
    )

    assert payload["paper_fill_allowed"] is False
    assert payload["replay_snapshot_ready"] is False
    assert "replay_snapshot:MTF_SNAPSHOT_ID_MISSING" in payload["paper_fill_gate_block_reasons"]


def test_trusted_mode_finality_inference_is_forbidden() -> None:
    row = trust_row()
    row.pop("candle_closed_confirmed")

    score = score_market_state(row)

    assert score.valid_for_training is False
    assert "CANDLE_COMPLETION_UNKNOWN" in score.reject_reasons


def test_current_or_unknown_finality_candle_cannot_reach_tensor_builder() -> None:
    assert _latest_kline([{"open": 1, "high": 1, "low": 1, "close": 1, "closed_candle": False}]) == {}
    assert _latest_kline([{"open": 1, "high": 1, "low": 1, "close": 1}]) == {}
    assert _latest_kline([{"open": 1, "high": 1, "low": 1, "close": 1, "closed_candle": True}])["close"] == 1


def test_binance_legacy_list_klines_without_finality_are_blocked() -> None:
    now_ms = int(time.time() * 1000)
    closed = [now_ms - 120_000, "1", "2", "0.5", "1.5", "10", now_ms - 60_000, "15", 3, "5", "7", "0"]
    unclosed = [now_ms - 30_000, "9", "10", "8", "9.5", "11", now_ms + 30_000, "20", 4, "6", "8", "0"]

    latest = _latest_kline([closed, unclosed])

    assert latest == {}


def test_canonical_closed_kline_can_reach_tensor_builder() -> None:
    latest = _latest_kline(
        [
            {
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
                "candle_closed_confirmed": True,
                "is_closed": True,
            }
        ]
    )

    assert latest["close"] == 1.5


def test_inactive_blocked_hold_paper_intent_does_not_require_snapshots(tmp_path: Path) -> None:
    records = clean_records()
    records["execution_records"].append(
        {
            "_key": "v2:paper:intents",
            "intent_id": "v2_paper_intent_1000BONKUSDT",
            "prediction_id": "old-pre-enforcement-prediction",
            "symbol": "1000BONKUSDT",
            "side": "hold",
            "valid_for_paper": True,
            "paper_fill_allowed": False,
            "pre_trade_allowed": False,
            "fee_gate_allowed": False,
            "routes_to_orchestrator": False,
            "risk_state": "PAPER_GATE_BLOCKED_BEFORE_RISK",
            "orchestrator_state": "BLOCKED_NO_ORCHESTRATOR_DECISION",
            "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
            "strategy_router_block_reason": "PPO_ACTION_NOT_TRADABLE",
        }
    )

    code, report = run_verify(write_exported_style(tmp_path, records))

    assert code == 0
    assert report["summary"]["critical_failures"] == 0
    assert not any(
        finding.get("check_id") in {"replay_snapshot.missing", "mtf_snapshot.missing"}
        and finding.get("severity") == "Critical"
        for finding in report.get("findings", [])
    )


def test_active_paper_intent_without_snapshots_still_fails(tmp_path: Path) -> None:
    records = clean_records()
    records["execution_records"].append(
        {
            "_key": "v2:paper:intents",
            "intent_id": "v2_paper_intent_1000BONKUSDT",
            "prediction_id": "active-prediction-without-snapshots",
            "symbol": "1000BONKUSDT",
            "side": "long",
            "valid_for_paper": True,
            "paper_fill_allowed": True,
            "pre_trade_allowed": True,
            "routes_to_orchestrator": True,
            "risk_state": "APPROVED",
            "orchestrator_state": "ROUTED_TO_PAPER",
            "paper_fill_gate_status": "PAPER_SHADOW_GATE_ALLOWED",
        }
    )

    code, report = run_verify(write_exported_style(tmp_path, records))
    check_ids = {finding.get("check_id") for finding in report.get("findings", [])}

    assert code != 0
    assert "replay_snapshot.missing" in check_ids
    assert "mtf_snapshot.missing" in check_ids
