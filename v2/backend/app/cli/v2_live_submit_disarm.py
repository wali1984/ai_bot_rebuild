"""Pass 1A live-submit disarm utility.

Disables live submit authority in V2 runtime Redis state without touching order
history, fills, positions, or audit records.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

from v2.backend.app.services.live_gate.binance_live_order_transport import KEY_STATUS as KEY_LIVE_ORDER_TRANSPORT_STATUS
from v2.backend.app.services.live_gate.runtime_execution_state import (
    KEY_LIVE_GATE_STATE,
    KEY_TRADER_EXECUTION_STATE,
    RELEASE_MODE_NON_LIVE,
    disarm_runtime_execution_state_payload,
)

UPDATED_BY = "pass1a_live_submit_disarm"
DEFAULT_BACKUP_PREFIX = "v2:quarantine:live_submit_disarm"


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _connect(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _parse_json_maybe(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{\"-0123456789tfn":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _read_value(client: Any, key: str) -> Any:
    value_type = client.type(key)
    if isinstance(value_type, bytes):
        value_type = value_type.decode("utf-8", errors="replace")
    if value_type == "string":
        return _parse_json_maybe(client.get(key))
    if value_type == "list":
        return [_parse_json_maybe(item) for item in client.lrange(key, 0, 999)]
    if value_type == "hash":
        return {field: _parse_json_maybe(value) for field, value in client.hgetall(key).items()}
    return None


def _can_submit_live_orders(key: str, value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if key in {KEY_LIVE_GATE_STATE, KEY_TRADER_EXECUTION_STATE}:
        return (
            value.get("live_gate") == "enabled_operator_approved"
            or value.get("order_transport_submit_enabled") is True
            or value.get("live_trading_enabled") is True
        )
    if key.startswith("v2:live_order_transport:"):
        return (
            value.get("order_transport_submit_enabled") is True
            or value.get("runtime_submit_enabled") is True
            or value.get("transport_submit_enabled") is True
            or value.get("submit_enabled") is True
        )
    return False


def _disarm_transport_payload(payload: dict[str, Any], *, reason: str) -> dict[str, Any]:
    out = dict(payload)
    out.update(
        {
            "submit_enabled": False,
            "order_transport_submit_enabled": False,
            "runtime_submit_enabled": False,
            "transport_submit_enabled": False,
            "live_trading_enabled": False,
            "live_blocked": True,
            "places_real_order": False,
            "exchange_action_taken": False,
            "updated_by": UPDATED_BY,
            "reason": reason,
            "release_mode": RELEASE_MODE_NON_LIVE,
        }
    )
    return out


def _candidate_keys(client: Any) -> list[str]:
    keys: list[str] = []
    for key in (KEY_LIVE_GATE_STATE, KEY_TRADER_EXECUTION_STATE):
        if client.exists(key):
            keys.append(key)
    for key in sorted(str(item) for item in client.scan_iter(match="v2:live_order_transport:*", count=250)):
        value = _read_value(client, key)
        if _can_submit_live_orders(key, value):
            keys.append(key)
    return keys


def snapshot_live_submit_state(client: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in _candidate_keys(client):
        rows.append(
            {
                "key": key,
                "type": client.type(key),
                "ttl": client.ttl(key),
                "value": _read_value(client, key),
                "can_submit_live_orders": _can_submit_live_orders(key, _read_value(client, key)),
            }
        )
    return rows


def disarm_live_submit_state(
    *,
    client: Any,
    reason: str,
    backup_prefix: str = DEFAULT_BACKUP_PREFIX,
    ttl_hours: int = 24,
    apply: bool,
) -> dict[str, Any]:
    stamp = _utc_stamp()
    backup_ttl_seconds = int(ttl_hours) * 3600
    changes: list[dict[str, Any]] = []
    backup_keys: list[str] = []
    for key in _candidate_keys(client):
        before = _read_value(client, key)
        if not isinstance(before, dict):
            continue
        if key in {KEY_LIVE_GATE_STATE, KEY_TRADER_EXECUTION_STATE}:
            after = disarm_runtime_execution_state_payload(
                before,
                reason=reason,
                updated_by=UPDATED_BY,
                release_mode=RELEASE_MODE_NON_LIVE,
            )
        else:
            after = _disarm_transport_payload(before, reason=reason)
        backup_key = f"{backup_prefix}:{stamp}:{key}"
        changes.append(
            {
                "key": key,
                "type": client.type(key),
                "ttl": client.ttl(key),
                "before": before,
                "after": after,
                "before_can_submit_live_orders": _can_submit_live_orders(key, before),
                "after_can_submit_live_orders": _can_submit_live_orders(key, after),
                "backup_key": backup_key,
            }
        )
        backup_keys.append(backup_key)
        if not apply:
            continue
        client.set(
            backup_key,
            json.dumps(
                {
                    "source_key": key,
                    "backed_up_at_utc": stamp,
                    "reason": reason,
                    "value": before,
                },
                sort_keys=True,
                default=str,
            ),
            ex=backup_ttl_seconds,
        )
        client.set(key, json.dumps(after, sort_keys=True, default=str))
    after_rows = snapshot_live_submit_state(client)
    return {
        "dry_run": not apply,
        "apply": bool(apply),
        "reason": reason,
        "updated_by": UPDATED_BY,
        "backup_prefix": backup_prefix,
        "backup_ttl_seconds": backup_ttl_seconds,
        "keys_changed": [row["key"] for row in changes],
        "backup_keys": backup_keys,
        "changes": changes,
        "post_snapshot": after_rows,
        "any_live_submit_enabled_after": any(row["can_submit_live_orders"] for row in after_rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_live_submit_disarm")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--backup-prefix", default=DEFAULT_BACKUP_PREFIX)
    parser.add_argument("--ttl-hours", type=int, default=24)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    client = _connect(args.redis_url)
    result = disarm_live_submit_state(
        client=client,
        reason=str(args.reason),
        backup_prefix=str(args.backup_prefix),
        ttl_hours=int(args.ttl_hours),
        apply=bool(args.apply),
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
