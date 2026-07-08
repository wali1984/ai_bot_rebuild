from __future__ import annotations

import json

from v2.backend.app.services.feature_pipeline.ta_flat_hash_adapter import publish_flat_ta
from v2.backend.app.services.feature_pipeline.unified_feature_bridge import build_unified_feature_payload
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    V2UnifiedFeatureTensorBuilder,
)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands: list[tuple[str, tuple, dict]] = []

    def delete(self, key: str):
        self.commands.append(("delete", (key,), {}))
        return self

    def hset(self, key: str, mapping):
        self.commands.append(("hset", (key, mapping), {}))
        return self

    def expire(self, key: str, ttl: int):
        self.commands.append(("expire", (key, ttl), {}))
        return self

    def execute(self):
        for name, args, _kwargs in self.commands:
            if name == "delete":
                self.redis.hashes.pop(args[0], None)
            elif name == "hset":
                self.redis.hashes[args[0]] = dict(args[1])
            elif name == "expire":
                self.redis.ttls[args[0]] = args[1]
        return True


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str):
        return self.data.get(key)

    def ttl(self, key: str) -> int:
        if key in self.hashes or key in self.data:
            return self.ttls.get(key, -1)
        return -2

    def hgetall(self, key: str):
        return self.hashes.get(key, {})

    def pipeline(self):
        return FakePipeline(self)


def test_ta_flat_hash_rejects_unfinished_candle() -> None:
    r = FakeRedis()
    r.set(
        "v2:technical_analysis:BTCUSDT:4h",
        json.dumps({"candle_closed_confirmed": False, "indicators": {"ta_RSI_14": 55}}),
        ex=900,
    )
    result = publish_flat_ta(r, symbol="BTCUSDT", timeframe="4h")
    assert result["published"] is False
    assert result["missing_reason"] == "UNFINISHED_CANDLE_NOT_FINAL"


def test_unified_feature_bridge_combines_ta_and_provider_features() -> None:
    r = FakeRedis()
    r.set(
        "v2:technical_analysis:BTCUSDT:1m",
        json.dumps(
            {
                "candle_closed_confirmed": True,
                "available_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T11:59:00Z",
                "indicators": {"ta_RSI_14": 55, "ta_MACD": 1.2},
            }
        ),
        ex=900,
    )
    assert publish_flat_ta(r, symbol="BTCUSDT", timeframe="1m")["published"] is True
    r.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(
            {
                "subscription_status": "READY",
                "actual_payload_present": True,
                "heartbeat_only": False,
                "available_at": "2026-07-08T12:00:00Z",
                "feature_cutoff": "2026-07-08T11:59:00Z",
                "features": {"coinglass_funding_rate": 0.0003},
            }
        ),
        ex=180,
    )
    payload = build_unified_feature_payload(
        r,
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:01:00Z",
    )
    assert payload["features"]["RSI"] == 55.0
    assert payload["features"]["funding_rate"] == 0.0003
    assert payload["point_in_time_safe"] is True


def test_tensor_builder_consumes_provider_bridge_features_without_new_dimension() -> None:
    builder = V2UnifiedFeatureTensorBuilder()
    record = builder.build(
        symbol="BTCUSDT",
        timeframe="1m",
        payloads={
            "provider_feature_context": {
                "provider_features": {
                    "funding_rate": 0.0004,
                    "open_interest": 12345,
                }
            }
        },
    )
    funding_index = record.feature_names.index("funding_rate")
    oi_index = record.feature_names.index("open_interest")
    assert record.values[funding_index] == 0.0004
    assert record.values[oi_index] == 12345
    assert record.source_labels[funding_index] == "provider_feature_bridge"
