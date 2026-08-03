from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from v2.backend.app.cli.export_pipeline_trust_evidence import export_pipeline_trust_evidence
from v2.backend.app.cli.run_trusted_prediction_publisher_once import run_publisher_proof_once
from v2.backend.app.cli.verify_pipeline_trust import main as verify_main
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    canonical_from_binance_rest,
    closed_candle_key,
    now_ms,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


class FakeRedis:
    def __init__(self, data: dict[str, Any]) -> None:
        self.store = dict(data)

    def scan_iter(self, match: str, count: int = 250):
        del count
        for key in sorted(self.store):
            if fnmatch.fnmatch(key, match):
                yield key

    def get(self, key: str) -> Any:
        return self.store.get(key)

    def set(self, key: str, value: Any) -> bool:
        self.store[key] = value
        return True

    def type(self, key: str) -> str:
        value = self.store[key]
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "hash" if value.get("__redis_type") == "hash" else "string"
        return "string"

    def hgetall(self, key: str) -> dict[str, str]:
        value = dict(self.store[key])
        value.pop("__redis_type", None)
        return {str(k): json.dumps(v) for k, v in value.items()}

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        return [json.dumps(value) for value in self.store[key][start : end + 1]]

    def xrevrange(self, key: str, count: int = 1000):
        del key, count
        return []

    def zrange(self, key: str, start: int, end: int) -> list[str]:
        return self.lrange(key, start, end)

    def smembers(self, key: str) -> set[str]:
        return {json.dumps(value) for value in self.store[key]}


def rest_row(timeframe: str, open_time: int) -> list[Any]:
    close_time = open_time + TF_MS[timeframe]
    return [open_time, "100", "101", "99", "100.5", "12", close_time, "1206", 10, "6", "603", "0"]


def closed_payload(timeframe: str, *, closed: bool = True) -> dict[str, Any]:
    close_time = now_ms() - 5_000
    open_time = close_time - TF_MS[timeframe]
    payload = canonical_from_binance_rest(
        rest_row(timeframe, open_time),
        symbol="BTCUSDT",
        timeframe=timeframe,
        ingested_at=close_time + 1,
    ).to_dict()
    payload["is_closed"] = closed
    payload["closed_candle"] = closed
    payload["candle_closed_confirmed"] = closed
    payload["feature_eligible"] = closed
    return payload


def closed_store(*, omit: str | None = None, closed: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for timeframe in REQUIRED_DECISION_TIMEFRAMES:
        if timeframe == omit:
            continue
        out[closed_candle_key("binance", "BTCUSDT", timeframe)] = [closed_payload(timeframe, closed=closed)]
    return out


def supporting_strict_runtime_records(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "v2:trainer:samples:publisher_proof": {
            "trust_schema_version": TRUST_SCHEMA_VERSION,
            "sample_id": "publisher-proof-sample",
            "decision_id": result["prediction_id"],
            "prediction_id": result["prediction_id"],
            "mtf_snapshot_id": result["mtf_snapshot_id"],
            "replay_snapshot_id": result["replay_snapshot_id"],
            "row_classification": "TRAINABLE",
            "used_for_training": False,
            "accepted_for_training": False,
            "feature_cutoff": now_ms() - 60_000,
            "label_start_time": now_ms() - 60_000,
            "label_end_time": now_ms(),
            "prediction_horizon_seconds": 60,
            "features": {"ret_pct": 0.0},
            "fee_bps": 0,
            "slippage_bps": 0,
        },
        "v2:paper:intents": [
            {
                "position_before": "flat",
                "requested_action": "hold",
                "position_after": "flat",
                "fill_status": "hold",
            }
        ],
    }


def test_trusted_publisher_once_emits_prediction_replay_and_mtf_snapshot() -> None:
    client = FakeRedis(closed_store())

    result = run_publisher_proof_once(client=client)

    assert result["success"] is True
    assert result["prediction_key"] == "v2:prediction:BTCUSDT:1m"
    assert result["replay_snapshot_key"] in client.store
    assert result["mtf_snapshot_key"] in client.store
    prediction = json.loads(client.store[result["prediction_key"]])
    replay = json.loads(client.store[result["replay_snapshot_key"]])
    mtf = json.loads(client.store[result["mtf_snapshot_key"]])
    assert prediction["trust_schema_version"] == TRUST_SCHEMA_VERSION
    assert prediction["routes_to_live"] is False
    assert prediction["live_order_allowed"] is False
    assert prediction["mtf_snapshot_id"]
    assert prediction["replay_snapshot_id"]
    assert replay["trust_schema_version"] == TRUST_SCHEMA_VERSION
    assert mtf["trust_schema_version"] == TRUST_SCHEMA_VERSION


def test_trusted_publisher_once_refuses_open_current_candle_evidence() -> None:
    client = FakeRedis(closed_store(closed=False))

    result = run_publisher_proof_once(client=client, symbol="BTCUSDT")

    assert result["success"] is False
    assert result["reason"] == "MTF_SNAPSHOT_INVALID"
    assert "v2:prediction:BTCUSDT:1m" not in client.store


def test_trusted_publisher_once_refuses_missing_mtf_snapshot() -> None:
    client = FakeRedis(closed_store(omit="4h"))

    result = run_publisher_proof_once(client=client, symbol="BTCUSDT")

    assert result["success"] is False
    assert result["reason"] == "MTF_SNAPSHOT_INVALID"
    assert "4h" in result["missing_timeframes"]
    assert "v2:prediction:BTCUSDT:1m" not in client.store


def test_export_and_strict_verifier_accept_clean_publisher_proof(tmp_path: Path) -> None:
    client = FakeRedis(closed_store())
    result = run_publisher_proof_once(client=client, symbol="BTCUSDT")
    assert result["success"] is True
    client.store.update(supporting_strict_runtime_records(result))

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
    prediction_rows = [
        json.loads(line)
        for line in (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    mtf_rows = [
        json.loads(line)
        for line in (run_dir / "mtf_snapshots.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(replay_rows) == 2
    assert len(prediction_rows) == 1
    assert len(mtf_rows) == 1

    out = run_dir / "report"
    code = verify_main(["--input", str(run_dir), "--output-dir", str(out), "--strict-unknown"])
    report = json.loads((out / "pipeline_trust_report.json").read_text(encoding="utf-8"))
    finding_ids = {finding["check_id"] for finding in report["findings"]}
    assert code == 0
    assert report["summary"]["critical_failures"] == 0
    assert "masa_ppo.missing_contract" not in finding_ids


def test_trusted_publisher_once_repairs_legacy_binance_ohlcv_into_canonical_closed_coverage() -> None:
    base_now = now_ms()
    data: dict[str, Any] = {}
    for timeframe in REQUIRED_DECISION_TIMEFRAMES:
        previous_open = base_now - (2 * TF_MS[timeframe]) - 5_000
        current_open = base_now - (TF_MS[timeframe] // 2)
        legacy_key = f"v2:market:ohlcv:binance:BTCUSDT:{timeframe}"
        data[legacy_key] = [
            rest_row(timeframe, previous_open),
            rest_row(timeframe, current_open),
        ]
        data[f"{legacy_key}:source"] = {
            "open_time_ms": current_open,
            "close_time_ms": current_open + TF_MS[timeframe],
            "event_time_ms": base_now,
            "closed_candle": False,
            "source_stream": "kline",
            "source_type": "wss",
        }

    client = FakeRedis(data)

    result = run_publisher_proof_once(client=client, symbol="BTCUSDT")

    assert result["success"] is True
    assert result["prediction_key"] == "v2:prediction:BTCUSDT:1m"
    assert result["replay_snapshot_key"] in client.store
    assert result["mtf_snapshot_key"] in client.store

    for timeframe in REQUIRED_DECISION_TIMEFRAMES:
        closed_key = closed_candle_key("binance", "BTCUSDT", timeframe)
        repaired_closed = json.loads(client.store[closed_key])
        assert len(repaired_closed) == 1
        assert repaired_closed[0]["open_time"] == data[f"v2:market:ohlcv:binance:BTCUSDT:{timeframe}"][0][0]
        assert repaired_closed[0]["feature_eligible"] is True

        current_key = f"v2:market:kline_current:binance:BTCUSDT:{timeframe}"
        repaired_current = json.loads(client.store[current_key])
        assert repaired_current["open_time"] == data[f"v2:market:ohlcv:binance:BTCUSDT:{timeframe}"][1][0]
        assert repaired_current["feature_eligible"] is False
