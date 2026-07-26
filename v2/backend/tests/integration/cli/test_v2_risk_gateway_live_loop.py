from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from v2.backend.app.services.market_state_integrity import (
    clear_decision_replays,
    get_decision_replay,
)
from v2.backend.tests.unit.services.test_ordinary_paper_admission import (
    ordinary_source,
)


class _RedisLike:
    def __init__(self, payload):
        self.payload = payload
        self.writes = {}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.store = {"v2:orchestrator:decisions": payload}
        self.ttls = {"v2:orchestrator:decisions": 300}
        for winner in payload.get("bucket_winners") or []:
            decision_id = winner["orchestrator_decision_id"]
            self.store[f"v2:decision:orchestrator:{decision_id}"] = {
                "schema_version": "v2_per_id_orchestrator_decision_record_v1",
                "orchestrator_decision_id": decision_id,
                "prediction_id": winner["winner_proposal_id"],
                "signal_id": winner["signal_id"],
                "symbol": winner["symbol"],
                "timeframe": winner["timeframe"],
                "feature_snapshot_id": winner["feature_snapshot_id"],
                "side": winner["side"],
                "decision": f"proceed_{winner['side']}",
                "orchestrator_action": f"proceed_{winner['side']}",
                "generated_utc": now.isoformat(),
                "expires_at": (now + timedelta(hours=2)).isoformat(),
                "producer": "v2_orchestrator_arbitration_loop",
            }

    def get(self, key):
        if key in self.writes:
            return json.dumps(self.writes[key][0])
        value = self.store.get(key)
        return json.dumps(value) if value is not None else None

    def set(self, key, value, ex=None, nx=False):
        assert key.startswith("v2:")
        if nx and (key in self.store or key in self.writes):
            return False
        self.writes[key] = (json.loads(value), ex)
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def scan(self, cursor=0, match=None, count=1000):  # noqa: ARG002
        prefix = str(match or "").rstrip("*")
        keys = list(self.store) + list(self.writes)
        return 0, [key for key in keys if not match or key.startswith(prefix)]

    def ttl(self, key):
        return self.ttls.get(key, 300 if key in self.store or key in self.writes else -2)


def test_risk_runtime_root_can_be_separate_from_immutable_code(
    monkeypatch,
    tmp_path,
):
    from v2.backend.app.cli import v2_risk_gateway_live_loop as worker

    monkeypatch.setenv("AI_BOT_RUNTIME_ROOT", str(tmp_path))

    assert worker._runtime_root() == tmp_path.resolve()  # noqa: SLF001


def test_risk_gateway_live_loop_stamps_v2_risk_decisions(monkeypatch, tmp_path):
    from v2.backend.app.cli import v2_risk_gateway_live_loop as worker

    clear_decision_replays()
    client = _RedisLike({
        "generated_utc": "2026-06-03T00:00:00Z",
        "bucket_winners": [{
            "symbol": "BTCUSDT",
            "side": "long",
            "winner_proposal_id": "pred_1",
            "signal_id": "sig_pred_1",
            "decision_id": "decision_pred_1",
            "orchestrator_decision_id": "dec_pred_1",
            "feature_snapshot_id": "fs_pred_1",
            "mtf_snapshot_id": "mtf_pred_1",
            "feature_cutoff": "2026-06-02T23:59:00Z",
            "decision_time": "2026-06-03T00:00:00Z",
            "available_at": "2026-06-02T23:59:30Z",
            "candle_closed_confirmed": True,
            "candle_close_time": "2026-06-02T23:59:00Z",
            "masa_feature_cutoff": "2026-06-02T23:59:00Z",
            "ppo_feature_cutoff": "2026-06-02T23:59:00Z",
            "ppo_decision_time": "2026-06-03T00:00:00Z",
            "timeframe": "1m",
            "selected_action": "long",
            "model_version": "model_v1",
            "checkpoint_id": "ckpt_v1",
            "source_hashes": {"feature_vector_hash": "hash_feat"},
            "winner_confidence_calibrated": 0.81,
            "winner_freshness_seconds": 5.0,
            "microstructure_trust_score": 0.2,
            "orderbook_trust_score": 0.2,
            "microstructure_action": "NO_TRADE",
            "sweep_risk_score": 0.8,
            "trust_gate_result": {
                "allowed": True,
                "reject_reasons": [],
                "warnings": [],
            },
        }],
    })
    monkeypatch.setattr(worker, "_connect_redis", lambda: client)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", tmp_path / "local.json")
    monkeypatch.setattr(worker, "WORKLOG_STATUS_FILE", tmp_path / "worklog.json")
    payload = worker.run_once(ttl_seconds=123)
    assert payload["classification"] == "V2_RISK_GATEWAY_LIVE_OK"
    assert payload["decisions_processed_total"] == 1
    assert payload["risk_action"] == "deny"
    assert payload["risk_reason_code"] == "deny_default"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["exchange_action_taken"] is False
    assert payload["writes_legacy_redis"] is False
    assert "v2:risk:gateway:heartbeat" in client.writes
    risk_row = client.writes["v2:risk:gateway:decisions"][0][0]
    assert risk_row["prediction_id"] == "pred_1"
    assert risk_row["signal_id"] == "sig_pred_1"
    assert risk_row["decision_id"] == "decision_pred_1"
    assert risk_row["orchestrator_decision_id"] == "dec_pred_1"
    assert risk_row["feature_snapshot_id"] == "fs_pred_1"
    assert risk_row["mtf_snapshot_id"] == "mtf_pred_1"
    assert risk_row["feature_cutoff"] == "2026-06-02T23:59:00Z"
    assert risk_row["decision_time"] == "2026-06-03T00:00:00Z"
    assert risk_row["available_at"] == "2026-06-02T23:59:30Z"
    assert risk_row["candle_closed_confirmed"] is True
    assert risk_row["candle_close_time"] == "2026-06-02T23:59:00Z"
    assert risk_row["masa_feature_cutoff"] == "2026-06-02T23:59:00Z"
    assert risk_row["ppo_feature_cutoff"] == "2026-06-02T23:59:00Z"
    assert risk_row["ppo_decision_time"] == "2026-06-03T00:00:00Z"
    assert risk_row["timeframe"] == "1m"
    assert risk_row["selected_action"] == "long"
    assert risk_row["model_version"] == "model_v1"
    assert risk_row["checkpoint_id"] == "ckpt_v1"
    assert risk_row["source_hashes"] == {"feature_vector_hash": "hash_feat"}
    assert risk_row["risk_microstructure_reject_reasons"] == [
        "MICROSTRUCTURE_ACTION_NO_TRADE",
        "MICROSTRUCTURE_SWEEP_RISK_BLOCK",
        "MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED",
    ]
    per_id_record = client.writes["v2:decision:risk:rd_dec_pred_1"][0]
    assert per_id_record["candle_closed_confirmed"] is True
    assert per_id_record["candle_close_time"] == "2026-06-02T23:59:00Z"
    assert per_id_record["masa_feature_cutoff"] == "2026-06-02T23:59:00Z"
    assert per_id_record["ppo_decision_time"] == "2026-06-03T00:00:00Z"
    assert per_id_record["producer"] == "v2_risk_gateway_live_loop"
    assert per_id_record["orchestrator_decision_id"] == "dec_pred_1"
    assert "v2:decision:risk:rd_pred_1" not in client.writes
    assert json.loads((tmp_path / "public.json").read_text())["worker_id"] == "v2_risk_gateway_runtime_worker"
    replay = get_decision_replay("dec_pred_1")
    assert replay is not None
    assert replay["block_reason"].startswith("MICROSTRUCTURE_")


def test_risk_gateway_can_allow_trusted_paper_decision_while_live_stays_blocked(
    monkeypatch,
    tmp_path,
) -> None:
    from v2.backend.app.cli import v2_risk_gateway_live_loop as worker

    winner = {
        "symbol": "ETHUSDT",
        "side": "short",
        "winner_proposal_id": "pred_clean",
        "prediction_id": "pred_clean",
        "signal_id": "sig_clean",
        "decision_id": "upstream_clean",
        "orchestrator_decision_id": "dec_pred_clean",
        "feature_snapshot_id": "fs_clean",
        "timeframe": "1m",
        "selected_action": "short",
        "winner_confidence_calibrated": 0.8,
        "winner_freshness_seconds": 2.0,
        "trust_gate_result": {
            "allowed": True,
            "reject_reasons": [],
            "warnings": [],
        },
    }
    client = _RedisLike({"generated_utc": datetime.now(timezone.utc).isoformat(), "bucket_winners": [winner]})
    monkeypatch.setattr(worker, "_connect_redis", lambda: client)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", tmp_path / "local.json")
    monkeypatch.setattr(worker, "WORKLOG_STATUS_FILE", tmp_path / "worklog.json")

    payload = worker.run_once(ttl_seconds=123)

    assert payload["risk_action"] == "allow"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["exchange_action_taken"] is False
    canonical = client.writes["v2:decision:risk:rd_dec_pred_clean"][0]
    assert canonical["risk_action"] == "allow"
    assert canonical["routes_to_live"] is False
    assert canonical["places_real_order"] is False


def test_ordinary_paper_provenance_and_contracted_weight_flow_end_to_end(
    monkeypatch,
    tmp_path,
) -> None:
    from v2.backend.app.cli import v2_orchestrator_arbitration_loop as orchestrator
    from v2.backend.app.cli import v2_risk_gateway_live_loop as worker

    prediction, replay = ordinary_source(
        symbol="SOLUSDT",
        microstructure_trust_score=0.45 - 1e-6,
        sweep_risk_score=0.75 + 1e-6,
        microstructure_action="SHADOW_ONLY",
        latency_within_bound=False,
    )
    prediction.update(
        {
            "confidence_raw": prediction["confidence_calibrated"],
        }
    )
    client = _RedisLike({"bucket_winners": []})
    prediction_key = "v2:prediction:SOLUSDT:1m"
    immutable_prediction_key = (
        f"v2:prediction_by_id:{prediction['prediction_id']}"
    )
    replay_key = str(prediction["replay_snapshot_key"])
    client.store[prediction_key] = prediction
    client.store[immutable_prediction_key] = prediction
    client.store[replay_key] = replay
    client.ttls[prediction_key] = 300
    client.ttls[immutable_prediction_key] = 300
    client.ttls[replay_key] = 300

    class _DegradedIntegrity:
        def to_dict(self):
            return {
                "market_state_id": prediction["market_state_id"],
                "market_state_integrity_score": 80.0 - 1e-6,
                "valid_for_prediction": True,
                "valid_for_risk": False,
                "valid_for_orchestrator": False,
                "valid_for_paper": True,
                "valid_for_live": False,
                "reject_reasons": [
                    "LATENCY_ABOVE_GATE",
                    "MAJOR_SOURCE_DISAGREEMENT",
                ],
            }

    monkeypatch.setattr(orchestrator, "_connect_redis", lambda: client)
    monkeypatch.setattr(
        orchestrator, "_prediction_age_seconds", lambda _prediction: 5.0
    )
    monkeypatch.setattr(
        orchestrator, "score_market_state", lambda _row: _DegradedIntegrity()
    )
    monkeypatch.setattr(
        orchestrator,
        "_live_context",
        lambda _client: {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
            "runtime_validation": {"valid": True},
            "runtime_source": "integration_test",
        },
    )
    orchestrator_status = orchestrator.run_once()
    assert orchestrator_status["bucket_winners_count"] == 1

    monkeypatch.setattr(worker, "_connect_redis", lambda: client)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", tmp_path / "local.json")
    monkeypatch.setattr(worker, "WORKLOG_STATUS_FILE", tmp_path / "worklog.json")
    risk_status = worker.run_once(ttl_seconds=123)

    assert risk_status["risk_action"] == "allow"
    risk_row = client.writes["v2:risk:gateway:decisions"][0][0]
    assert risk_row["ordinary_scale_free_paper_admission_revalidated"] is True
    assert risk_row["market_state_id"] == prediction["market_state_id"]
    assert risk_row["ordinary_paper_raw_microstructure_action"] == "SHADOW_ONLY"
    assert risk_row["ordinary_paper_effective_microstructure_action"] == (
        "REDUCE_SIZE"
    )
    assert 0.0 < risk_row["ordinary_paper_effective_sizing_weight"] < risk_row[
        "paper_quality_sizing_weight"
    ]
    evidence_hash = risk_row["ordinary_paper_admission_evidence_sha256"]
    canonical = client.writes[
        f"v2:decision:risk:{risk_row['risk_decision_id']}"
    ][0]
    assert canonical["ordinary_paper_admission_evidence_sha256"] == evidence_hash
    assert canonical["ordinary_paper_effective_sizing_weight"] == risk_row[
        "ordinary_paper_effective_sizing_weight"
    ]
    assert canonical["routes_to_live"] is False
    assert canonical["places_real_order"] is False
