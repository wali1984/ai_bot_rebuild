from __future__ import annotations

import json

from v2.backend.app.services.replay_debugger import build_debugger_payload, query_snapshots


class FakeRedis:
    def __init__(self) -> None:
        self.store = {
            "v2:prediction:BTCUSDT:1m": json.dumps({
                "prediction_id": "pred-btc",
                "feature_snapshot_id": "fs-btc",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "generated_utc": "2026-06-08T10:00:00Z",
                "selected_action": "hold",
            }),
            "v2:paper:ledger": json.dumps({
                "accepted": [{
                    "prediction_id": "pred-btc",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "decision": "ACCEPTED_PAPER_FILL",
                    "strategy_selected_mode": "trend_mode",
                    "strategy_allowed_actions": ["hold", "long"],
                    "strategy_action_mask": {
                        "hold": True,
                        "long": True,
                        "short": False,
                        "close": False,
                    },
                    "strategy_size_multiplier": 1.0,
                    "strategy_router_confidence": 0.78,
                    "strategy_router_block_reason": None,
                    "strategy_reason_codes": ["HTF_CONFIRMED"],
                    "strategy_regime_labels": ["TREND"],
                }],
                "blocked": [{
                    "prediction_id": "pred-eth",
                    "symbol": "ETHUSDT",
                    "timeframe": "1m",
                    "decision": "BLOCKED_BY_ROUTER",
                    "strategy_selected_mode": "no_trade_mode",
                    "strategy_router_block_reason": "DATA_QUALITY_BELOW_THRESHOLD",
                    "strategy_regime_labels": ["DATA_UNRELIABLE", "NO_TRADE"],
                }],
            }),
            "v2:risk:decisions": json.dumps([
                {
                    "prediction_id": "pred-btc",
                    "risk_decision_id": "risk-btc",
                    "strategy_selected_mode": "trend_mode",
                },
                {
                    "prediction_id": "pred-eth",
                    "risk_decision_id": "risk-eth",
                    "strategy_selected_mode": "no_trade_mode",
                },
            ]),
            "v2:prediction:ETHUSDT:1m": json.dumps({
                "prediction_id": "pred-eth",
                "feature_snapshot_id": "fs-eth",
                "symbol": "ETHUSDT",
                "timeframe": "1m",
                "generated_utc": "2026-06-08T10:00:00Z",
                "selected_action": "short",
            }),
        }

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        prefix = match.rstrip("*")
        return (key for key in self.store if key.startswith(prefix))


def test_replay_debugger_can_query_latest_symbol_snapshot() -> None:
    payload = build_debugger_payload(FakeRedis())
    rows = query_snapshots(payload, symbol="BTCUSDT", latest=True)

    assert payload["snapshots_available"] == 2
    assert len(rows) == 1
    assert rows[0]["decision_id"] == "pred-btc"
    assert rows[0]["feature_snapshot_id"] if "feature_snapshot_id" in rows[0] else rows[0]["feature_vector_hash"]
    assert rows[0]["strategy_router"]["selected_mode"] == "trend_mode"
    assert rows[0]["execution_result"] == "ACCEPTED_PAPER_FILL"


def test_replay_debugger_carries_blocked_strategy_router_decision() -> None:
    payload = build_debugger_payload(FakeRedis())
    rows = query_snapshots(payload, prediction_id="pred-eth")

    assert len(rows) == 1
    assert rows[0]["strategy_router"]["selected_mode"] == "no_trade_mode"
    assert rows[0]["strategy_router"]["block_reason"] == "DATA_QUALITY_BELOW_THRESHOLD"
