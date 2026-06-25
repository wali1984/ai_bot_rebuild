from __future__ import annotations

import json

from v2.backend.app.services.market_state_integrity import (
    clear_decision_replays,
    get_decision_replay,
)


class _RedisLike:
    def __init__(self, payload):
        self.payload = payload
        self.writes = {}

    def get(self, key):
        assert key == "v2:orchestrator:decisions"
        return json.dumps(self.payload)

    def set(self, key, value, ex=None):
        assert key.startswith("v2:")
        self.writes[key] = (json.loads(value), ex)
        return True


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
            "timeframe": "1m",
            "selected_action": "long",
            "model_version": "model_v1",
            "checkpoint_id": "ckpt_v1",
            "source_hashes": {"feature_vector_hash": "hash_feat"},
            "winner_confidence_calibrated": 0.81,
            "winner_freshness_seconds": 5.0,
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
    assert risk_row["timeframe"] == "1m"
    assert risk_row["selected_action"] == "long"
    assert risk_row["model_version"] == "model_v1"
    assert risk_row["checkpoint_id"] == "ckpt_v1"
    assert risk_row["source_hashes"] == {"feature_vector_hash": "hash_feat"}
    assert json.loads((tmp_path / "public.json").read_text())["worker_id"] == "v2_risk_gateway_runtime_worker"
    replay = get_decision_replay("dec_pred_1")
    assert replay is not None
    assert replay["block_reason"] in {"live_trading_disabled", "replay_snapshot_missing"}
