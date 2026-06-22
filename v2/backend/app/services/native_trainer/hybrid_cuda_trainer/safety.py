"""Safety helpers for the paper/shadow hybrid trainer."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .config import LIVE_GATE_BLOCKED


def assert_v2_key(key: str) -> None:
    if not isinstance(key, str) or not key.startswith("v2:"):
        raise ValueError(f"non_v2_key_rejected:{key}")


def assert_prediction_or_trainer_key(key: str) -> None:
    assert_v2_key(key)
    allowed = (
        "v2:prediction:",
        "v2:trainer:hybrid_cuda:",
        "v2:replay:",
        "v2:market:mtf_snapshot:",
        "v2:decision:mtf_snapshot:",
        "v2:mtf_snapshot:",
        "v2:risk:decisions",
        "v2:orchestrator:decisions",
        "v2:signals:paper:",
        "v2:paper:",
    )
    if not key.startswith(allowed):
        raise ValueError(f"v2_key_not_allowed_for_hybrid_trainer_write:{key}")


def safety_scoreboard() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "trainer_direct_exchange_calls": False,
        "places_orders": False,
        "cancels_orders": False,
        "modifies_orders": False,
        "changes_leverage": False,
        "changes_margin_mode": False,
        "writes_old_redis": False,
        "imports_raw_legacy_trainer": False,
        "loads_unapproved_external_checkpoint": False,
        "checkpoint_deserialization": "json_manifest_only",
        "paper_shadow_only": True,
    }


@dataclass
class V2OnlyIOAudit:
    reads_attempted: int = 0
    reads_missing: int = 0
    writes_attempted: int = 0
    writes_succeeded: int = 0
    writes_failed: int = 0
    old_redis_write_attempts: int = 0
    keys_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class V2OnlyJsonIO:
    """Duck-typed Redis adapter that refuses non-V2 keys and unsafe writes."""

    def __init__(self, client: Any = None) -> None:
        self.client = client
        self.audit = V2OnlyIOAudit()

    def get_json(self, key: str) -> Any:
        assert_v2_key(key)
        self.audit.reads_attempted += 1
        if self.client is None:
            self.audit.reads_missing += 1
            return None
        hash_payload = None
        try:
            raw = self.client.get(key)
        except Exception as exc:  # noqa: BLE001
            self.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
            hash_payload = self._get_hash_payload(key)
            if hash_payload is not None:
                return hash_payload
            self.audit.reads_missing += 1
            return None
        if raw is None:
            hash_payload = self._get_hash_payload(key)
            if hash_payload is not None:
                return hash_payload
            self.audit.reads_missing += 1
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                self.audit.errors.append(f"json_decode_failed:{key}")
                return None
        return raw

    def _get_hash_payload(self, key: str) -> dict[str, Any] | None:
        try:
            data = self.client.hgetall(key)
        except Exception:
            return None
        if not data:
            return None
        out: dict[str, Any] = {}
        for raw_key, raw_value in dict(data).items():
            field = raw_key.decode("utf-8") if isinstance(raw_key, (bytes, bytearray)) else str(raw_key)
            value: Any = raw_value.decode("utf-8") if isinstance(raw_value, (bytes, bytearray)) else raw_value
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            out[field] = value
        return out

    def set_json(self, key: str, payload: Any) -> bool:
        self.audit.writes_attempted += 1
        try:
            assert_prediction_or_trainer_key(key)
        except ValueError as exc:
            self.audit.old_redis_write_attempts += 1
            self.audit.writes_failed += 1
            self.audit.errors.append(str(exc))
            return False
        if self.client is None:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"no_client:{key}")
            return False
        try:
            self.client.set(key, json.dumps(payload, sort_keys=True, default=str))
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"set_failed:{key}:{type(exc).__name__}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True
