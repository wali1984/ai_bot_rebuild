"""Safety helpers for the paper/shadow hybrid trainer."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .config import LIVE_GATE_BLOCKED


def assert_v2_key(key: str) -> None:
    if not isinstance(key, str) or not key.startswith("v2:"):
        raise ValueError(f"non_v2_key_rejected:{key}")


def assert_prediction_or_trainer_key(key: str) -> None:
    assert_v2_key(key)
    allowed = (
        "v2:prediction:",
        "v2:trainer:feature_schema_status",
        "v2:trainer:hybrid_cuda:",
        "v2:replay:",
        "v2:market:mtf_snapshot:",
        # Full v2:decision: namespace — per-ID immutable risk/orchestrator
        # decision records + candidate/signal indexes (operator mission
        # 2026-07-10: last-write-wins previews are not per-candidate lineage).
        "v2:decision:",
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

    def get_json_many(self, keys: "Sequence[str]") -> dict[str, Any]:
        """Pipelined batch read: one Redis round-trip for many v2 keys.

        Missing keys map to None so request caches can record definitive
        misses. Falls back to an empty dict (callers then use get_json) if the
        pipeline itself fails.
        """
        result: dict[str, Any] = {}
        valid: list[str] = []
        for key in keys:
            try:
                assert_v2_key(key)
            except ValueError:
                continue
            valid.append(key)
        if self.client is None or not valid:
            return result
        try:
            pipe = self.client.pipeline(transaction=False)
            for key in valid:
                pipe.get(key)
            raws = pipe.execute()
        except Exception as exc:  # noqa: BLE001
            self.audit.errors.append(f"pipeline_get_failed:{type(exc).__name__}")
            return result
        for key, raw in zip(valid, raws):
            self.audit.reads_attempted += 1
            if raw is None:
                self.audit.reads_missing += 1
                result[key] = None
                continue
            try:
                result[key] = json.loads(raw)
            except (TypeError, ValueError):
                result[key] = None
        return result

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

    def set_json(self, key: str, payload: Any, *, ex: int | None = None) -> bool:
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
            serialized = json.dumps(payload, sort_keys=True, default=str)
            if ex is not None:
                try:
                    self.client.set(key, serialized, ex=ex)
                except TypeError:
                    # Fallback for clients that don't accept ex kwarg (e.g. test fakes)
                    self.client.set(key, serialized)
            else:
                self.client.set(key, serialized)
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"set_failed:{key}:{type(exc).__name__}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True

    def set_json_expiring(self, key: str, payload: Any, *, ex: int) -> bool:
        """Write JSON only when the backend proves native expiry support."""

        self.audit.writes_attempted += 1
        try:
            assert_prediction_or_trainer_key(key)
        except ValueError as exc:
            self.audit.old_redis_write_attempts += 1
            self.audit.writes_failed += 1
            self.audit.errors.append(str(exc))
            return False
        if self.client is None or isinstance(ex, bool) or int(ex) <= 0:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"expiring_write_precondition_failed:{key}")
            return False
        try:
            serialized = json.dumps(payload, sort_keys=True, default=str)
            result = self.client.set(key, serialized, ex=int(ex))
        except TypeError:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"expiry_not_supported:{key}")
            return False
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"set_failed:{key}:{type(exc).__name__}")
            return False
        # redis-py returns literal ``True`` only after Redis acknowledges the
        # expiring SET.  ``None`` (a common permissive test-double result) is
        # not proof that the TTL was accepted, so status publication must fail
        # closed instead of creating an immortal ACTIVE heartbeat.
        if result is not True:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"expiring_set_not_acknowledged:{key}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True

    def set_json_immutable(
        self,
        key: str,
        payload: Any,
        *,
        ex: int | None = None,
    ) -> bool:
        """Create a content-addressed JSON record once, or verify exact identity.

        A backend that cannot provide Redis ``SET ... NX`` semantics fails closed;
        silently degrading to a last-write-wins write would make an audit receipt
        mutable.
        """
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
            serialized = json.dumps(payload, sort_keys=True, default=str)
            created = self.client.set(key, serialized, ex=ex, nx=True)
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(
                f"immutable_set_failed:{key}:{type(exc).__name__}"
            )
            return False
        if created:
            self.audit.writes_succeeded += 1
            self.audit.keys_written.append(key)
            return True
        try:
            existing = self.client.get(key)
            if isinstance(existing, (bytes, bytearray)):
                existing = existing.decode("utf-8")
            existing_payload = json.loads(existing) if isinstance(existing, str) else existing
            identical = json.dumps(
                existing_payload,
                sort_keys=True,
                default=str,
            ) == serialized
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(
                f"immutable_verify_failed:{key}:{type(exc).__name__}"
            )
            return False
        if identical:
            self.audit.writes_succeeded += 1
            return True
        self.audit.writes_failed += 1
        self.audit.errors.append(f"immutable_content_conflict:{key}")
        return False
