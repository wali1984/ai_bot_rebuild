from __future__ import annotations

import json

from v2.backend.app.services.a_plus_trade_gate.service import load_a_plus_context


class FakeRedis:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = {
            key: json.dumps(value)
            for key, value in payloads.items()
        }

    def get(self, key: str) -> str | None:
        return self.payloads.get(key)


def test_load_a_plus_context_falls_back_to_1m_microstructure_trust() -> None:
    redis = FakeRedis(
        {
            "v2:microstructure:trust_score:BTCUSDT:1m": {
                "generated_utc": "2026-07-06T12:00:00Z",
                "microstructure_trust_score": 0.73,
            }
        }
    )

    context = load_a_plus_context(redis, symbol="btcusdt", timeframe="15m")

    assert context["microstructure_trust"]["microstructure_trust_score"] == 0.73
    assert context["microstructure_trust_source_key"] == (
        "v2:microstructure:trust_score:BTCUSDT:1m"
    )
    assert context["microstructure_trust_lookup_keys"] == [
        "v2:microstructure:trust_score:BTCUSDT:15m",
        "v2:microstructure:trust_score:BTCUSDT:1m",
        "v2:microstructure:feed_quality:binance:BTCUSDT",
    ]
