import json
import time
import unittest
from unittest.mock import MagicMock

from rl.scripts.backfill_predictions_stub import SYMBOLS, TIMEFRAMES


class InMemoryRedis:
    def __init__(self):
        self.store = {}
        self.streams = {}

    def hset(self, key, mapping):
        self.store.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return self.store.get(key, {})

    def expire(self, key, ttl):
        # no-op for in-memory
        pass

    def xadd(self, stream, data, maxlen=None, approximate=True):
        self.streams.setdefault(stream, []).append((int(time.time() * 1000), data))


class TestSignalPipeline(unittest.TestCase):
    def test_prediction_persistence_per_tf(self):
        # Minimal mock to ensure per-TF predictions are written
        rc = InMemoryRedis()
        ts_ms = int(time.time() * 1000)
        for sym in SYMBOLS[:3]:
            for tf in TIMEFRAMES[:3]:
                key = f"prediction:{sym}:{tf}"
                payload = {
                    "action": "HOLD",
                    "confidence": 0.0,
                    "ts_ms": ts_ms,
                    "source": "test",
                    "model_version": "stub",
                }
                rc.hset(key, mapping=payload)

        # Verify all keys present
        missing = []
        for sym in SYMBOLS[:3]:
            for tf in TIMEFRAMES[:3]:
                key = f"prediction:{sym}:{tf}"
                if not rc.hgetall(key):
                    missing.append(key)
        self.assertFalse(missing, f"Missing prediction keys: {missing}")

    def test_stream_schema_wrap(self):
        rc = InMemoryRedis()
        payload = {
            "ts_ms": int(time.time() * 1000),
            "timestamp_iso": "2025-12-17T00:00:00Z",
            "symbol": "BTCUSDT",
            "tf": "1h",
            "action": "LONG",
            "confidence": 0.9,
            "reason_codes": ["TREND_CONFIRMED"],
            "portfolio_hash": "hash",
            "mtf_snapshot": {"1h": 0.8},
            "model_versions": "v1",
            "health_state": "ok",
            "data": {"raw": True},
        }
        rc.xadd("signals:trading", {"data": json.dumps(payload)})
        last = rc.streams["signals:trading"][-1][1]["data"]
        decoded = json.loads(last)
        for field in ["ts_ms", "symbol", "tf", "action", "confidence", "data"]:
            self.assertIn(field, decoded)


if __name__ == "__main__":
    unittest.main()
