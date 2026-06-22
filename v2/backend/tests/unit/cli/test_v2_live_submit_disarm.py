from __future__ import annotations

import json

from v2.backend.app.cli.v2_live_submit_disarm import (
    disarm_live_submit_state,
    snapshot_live_submit_state,
)


class _FakeRedis:
    def __init__(self, store: dict[str, str], ttl_map: dict[str, int] | None = None) -> None:
        self.store = dict(store)
        self.ttl_map = dict(ttl_map or {})

    def scan_iter(self, match: str | None = None, count: int = 250):  # noqa: ARG002
        keys = list(self.store.keys())
        if match is None:
            for key in keys:
                yield key
            return
        prefix = match.rstrip("*")
        for key in keys:
            if match.endswith("*"):
                if key.startswith(prefix):
                    yield key
            elif key == match:
                yield key

    def exists(self, key: str) -> bool:
        return key in self.store

    def type(self, key: str) -> str:
        return "string" if key in self.store else "none"

    def ttl(self, key: str) -> int:
        return self.ttl_map.get(key, -1)

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttl_map[key] = ex
        return True


def test_snapshot_detects_armed_live_submit_state() -> None:
    client = _FakeRedis(
        {
            "v2:live_gate:state": json.dumps({"live_gate": "enabled_operator_approved", "order_transport_submit_enabled": True}),
            "v2:trader:execution_state": json.dumps({"live_gate": "enabled_operator_approved", "order_transport_submit_enabled": True}),
            "v2:live_order_transport:status": json.dumps({"runtime_submit_enabled": True, "transport_submit_enabled": True}),
        },
        ttl_map={"v2:live_order_transport:status": 300},
    )
    rows = snapshot_live_submit_state(client)
    assert len(rows) == 3
    assert all(row["can_submit_live_orders"] is True for row in rows)


def test_disarm_cli_changes_only_live_submit_authority_fields() -> None:
    client = _FakeRedis(
        {
            "v2:live_gate:state": json.dumps(
                {
                    "live_gate": "enabled_operator_approved",
                    "order_transport_submit_enabled": True,
                    "accepted_live_symbols": ["BTCUSDT"],
                    "enable_audit_id": "enable_audit",
                }
            ),
            "v2:trader:execution_state": json.dumps(
                {
                    "live_gate": "enabled_operator_approved",
                    "order_transport_submit_enabled": True,
                    "accepted_live_symbols": ["BTCUSDT"],
                }
            ),
            "v2:live_order_transport:status": json.dumps(
                {
                    "runtime_submit_enabled": True,
                    "transport_submit_enabled": True,
                    "places_real_order": False,
                }
            ),
            "v2:live_order_transport:audit": json.dumps({"status": "LIVE_ORDER_TRANSPORT_BLOCKED"}),
            "v2:paper:ledger": json.dumps([{"id": "fill_1"}]),
        }
    )
    result = disarm_live_submit_state(
        client=client,
        reason="Pass 1A release gate: live submit disabled before paper/shadow validation",
        apply=True,
    )
    assert result["any_live_submit_enabled_after"] is False
    assert sorted(result["keys_changed"]) == [
        "v2:live_gate:state",
        "v2:live_order_transport:status",
        "v2:trader:execution_state",
    ]
    live_gate = json.loads(client.get("v2:live_gate:state"))
    trader = json.loads(client.get("v2:trader:execution_state"))
    transport = json.loads(client.get("v2:live_order_transport:status"))
    assert live_gate["live_gate"] == "blocked_human_only"
    assert live_gate["order_transport_submit_enabled"] is False
    assert live_gate["live_trading_enabled"] is False
    assert live_gate["operator_approved"] is False
    assert live_gate["accepted_live_symbols"] == ["BTCUSDT"]
    assert trader["live_gate"] == "blocked_human_only"
    assert trader["order_transport_submit_enabled"] is False
    assert transport["runtime_submit_enabled"] is False
    assert transport["transport_submit_enabled"] is False
    assert transport["places_real_order"] is False
    assert json.loads(client.get("v2:live_order_transport:audit")) == {"status": "LIVE_ORDER_TRANSPORT_BLOCKED"}
    assert json.loads(client.get("v2:paper:ledger")) == [{"id": "fill_1"}]
    assert any(key.startswith("v2:quarantine:live_submit_disarm:") for key in client.store)
