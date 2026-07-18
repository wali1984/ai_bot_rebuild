from __future__ import annotations

import json
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tools import quarantine_legacy_trainer_redis_namespace as quarantine


@dataclass
class _Entry:
    redis_type: bytes
    dump: bytes
    pttl_ms: int


class WatchError(RuntimeError):
    pass


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self.client = client
        self.watched: dict[bytes, int] = {}
        self.commands: list[tuple[str, tuple[Any, ...]]] = []
        self.in_multi = False

    def watch(self, *keys: bytes) -> None:
        self.watched = {key: self.client.revisions.get(key, 0) for key in keys}

    def type(self, key: bytes) -> bytes:
        return self.client.type(key)

    def dump(self, key: bytes) -> bytes | None:
        return self.client.dump(key)

    def pttl(self, key: bytes) -> int:
        return self.client.pttl(key)

    def ttl(self, key: bytes) -> int:
        return self.client.ttl(key)

    def exists(self, key: bytes) -> int:
        return self.client.exists(key)

    def multi(self) -> None:
        self.in_multi = True

    def delete(self, *keys: bytes) -> None:
        assert self.in_multi
        self.commands.append(("delete", tuple(keys)))

    def restore(self, key: bytes, ttl_ms: int, dump: bytes, *, replace: bool) -> None:
        assert self.in_multi
        self.commands.append(("restore", (key, ttl_ms, dump, replace)))

    def execute(self) -> list[Any]:
        if self.client.conflict_on_execute:
            self.client.conflict_on_execute = False
            raise WatchError("simulated writer race")
        if any(
            self.client.revisions.get(key, 0) != revision
            for key, revision in self.watched.items()
        ):
            raise WatchError("watched key changed")
        responses: list[Any] = []
        for command, arguments in self.commands:
            if command == "delete":
                responses.append(self.client.delete(*arguments))
            elif command == "restore":
                key, ttl_ms, dump, replace = arguments
                responses.append(self.client.restore(key, ttl_ms, dump, replace=replace))
        return responses

    def reset(self) -> None:
        self.commands.clear()
        self.watched.clear()


class _FakeRedis:
    def __init__(self, entries: dict[bytes, _Entry]) -> None:
        self.entries = dict(entries)
        self.revisions = {key: 1 for key in entries}
        self.scan_number = 0
        self.before_scan: dict[int, Callable[[_FakeRedis], None]] = {}
        self.conflict_on_execute = False

    def time(self) -> tuple[int, int]:
        return 1_789_000_000, self.scan_number

    def scan_iter(self, *, match: bytes, count: int):  # noqa: ARG002
        self.scan_number += 1
        callback = self.before_scan.get(self.scan_number)
        if callback is not None:
            callback(self)
        assert match == quarantine.SCAN_PATTERN
        for key in sorted(self.entries):
            if key.startswith(quarantine.NAMESPACE):
                yield key

    def type(self, key: bytes) -> bytes:
        entry = self.entries.get(key)
        return entry.redis_type if entry is not None else b"none"

    def dump(self, key: bytes) -> bytes | None:
        entry = self.entries.get(key)
        return entry.dump if entry is not None else None

    def pttl(self, key: bytes) -> int:
        entry = self.entries.get(key)
        return entry.pttl_ms if entry is not None else -2

    def ttl(self, key: bytes) -> int:
        pttl = self.pttl(key)
        if pttl < 0:
            return pttl
        return max(0, pttl // 1000)

    def exists(self, key: bytes) -> int:
        return int(key in self.entries)

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        return _FakePipeline(self)

    def delete(self, *keys: bytes) -> int:
        deleted = 0
        for key in keys:
            if key in self.entries:
                deleted += 1
                del self.entries[key]
                self.revisions[key] = self.revisions.get(key, 0) + 1
        return deleted

    def restore(self, key: bytes, ttl_ms: int, dump: bytes, *, replace: bool) -> bytes:
        if key in self.entries and not replace:
            raise RuntimeError("BUSYKEY")
        self.entries[key] = _Entry(b"string", dump, -1 if ttl_ms == 0 else ttl_ms)
        self.revisions[key] = self.revisions.get(key, 0) + 1
        return b"OK"

    def mutate(self, key: bytes, entry: _Entry | None) -> None:
        if entry is None:
            self.entries.pop(key, None)
        else:
            self.entries[key] = entry
        self.revisions[key] = self.revisions.get(key, 0) + 1


def _entry(dump: bytes, *, redis_type: bytes = b"string", pttl_ms: int = -1) -> _Entry:
    return _Entry(redis_type, dump, pttl_ms)


def _safe_services() -> list[dict[str, Any]]:
    return [
        {
            "unit": unit,
            "load_state": "loaded",
            "active_state": "inactive",
            "safe": True,
            "query_error": None,
        }
        for unit in quarantine.REQUIRED_INACTIVE_UNITS
    ]


def _archive_for(client: _FakeRedis) -> tuple[quarantine.NamespaceSnapshot, dict[str, Any]]:
    first = quarantine.capture_namespace(client)
    second = quarantine.capture_namespace(client)
    payload = quarantine.build_archive_payload(
        first=first,
        second=second,
        first_services=_safe_services(),
        second_services=_safe_services(),
        first_writer_processes=[],
        second_writer_processes=[],
    )
    return second, payload


def test_exact_prefix_inventory_is_lossless_and_cleanup_is_narrow() -> None:
    legacy_status = quarantine.NAMESPACE + b"status"
    legacy_signal = quarantine.NAMESPACE + b"signals:paper:BTCUSDT:1h"
    current_signal = quarantine.NAMESPACE + b"signals:paper:ETHUSDT:1h"
    on_policy = quarantine.NAMESPACE + b"on_policy_receipt:abc"
    unknown_immortal = quarantine.NAMESPACE + b"future_schema:keep"
    outside = b"v2:trainer:hybrid_cuda_not_exact:status"
    client = _FakeRedis(
        {
            legacy_status: _entry(b"rdb\x00status"),
            legacy_signal: _entry(b"rdb\xffsignal", redis_type=b"hash"),
            current_signal: _entry(b"current", pttl_ms=45_000),
            on_policy: _entry(b"durable-receipt"),
            unknown_immortal: _entry(b"unknown"),
            outside: _entry(b"outside"),
        }
    )

    snapshot = quarantine.capture_namespace(client)

    assert len(snapshot.records) == 5
    by_key = {row["key_utf8"]: row for row in snapshot.records}
    assert by_key[legacy_status.decode()]["cleanup_eligible"] is True
    assert by_key[legacy_signal.decode()]["cleanup_eligible"] is True
    assert (
        by_key[current_signal.decode()]["cleanup_classification"]
        == "PRESERVE_EXPIRING_CURRENT_RECORD"
    )
    assert (
        by_key[on_policy.decode()]["cleanup_classification"]
        == "PRESERVE_ON_POLICY_BEHAVIOR_RECEIPT"
    )
    assert (
        by_key[unknown_immortal.decode()]["cleanup_classification"]
        == "PRESERVE_UNCLASSIFIED_IMMORTAL_RECORD"
    )
    assert all(row["key_utf8"] != outside.decode() for row in snapshot.records)
    assert by_key[legacy_signal.decode()]["content_sha256"] == quarantine._sha256(b"rdb\xffsignal")


def test_all_supported_core_types_are_archived_as_dump_payloads() -> None:
    entries = {
        quarantine.NAMESPACE + b"future:" + redis_type: _entry(
            b"dump-" + redis_type, redis_type=redis_type
        )
        for redis_type in quarantine.SUPPORTED_REDIS_TYPES
    }
    snapshot = quarantine.capture_namespace(_FakeRedis(entries))
    assert {row["redis_type"] for row in snapshot.records} == {
        value.decode() for value in quarantine.SUPPORTED_REDIS_TYPES
    }
    assert all(row["cleanup_eligible"] is False for row in snapshot.records)


def test_unsupported_module_type_refuses_whole_archive() -> None:
    client = _FakeRedis(
        {quarantine.NAMESPACE + b"json": _entry(b"module-dump", redis_type=b"ReJSON-RL")}
    )
    with pytest.raises(quarantine.QuarantineError, match="UNSUPPORTED_REDIS_TYPE"):
        quarantine.capture_namespace(client)


def test_candidate_change_between_scans_fails_closed() -> None:
    key = quarantine.NAMESPACE + b"status"
    client = _FakeRedis({key: _entry(b"old")})
    first = quarantine.capture_namespace(client)
    client.mutate(key, _entry(b"new"))
    second = quarantine.capture_namespace(client)

    with pytest.raises(quarantine.QuarantineError, match="CANDIDATE_SET_CHANGED"):
        quarantine.assert_candidate_stability(first, second)


def test_inconsistent_immortal_ttl_observation_fails_closed() -> None:
    key = quarantine.NAMESPACE + b"status"
    client = _FakeRedis({key: _entry(b"legacy")})
    client.ttl = lambda observed_key: 0  # type: ignore[method-assign]
    with pytest.raises(quarantine.QuarantineError, match="IMMORTAL_TTL_OBSERVATION_INCONSISTENT"):
        quarantine.capture_namespace(client)


def test_positive_ttl_current_key_may_drift_without_blocking_candidate_archive() -> None:
    legacy = quarantine.NAMESPACE + b"metrics"
    current = quarantine.NAMESPACE + b"signals:paper:ETHUSDT:1m"
    client = _FakeRedis({legacy: _entry(b"legacy"), current: _entry(b"cycle-a", pttl_ms=20_000)})
    first = quarantine.capture_namespace(client)
    client.mutate(current, _entry(b"cycle-b", pttl_ms=19_000))
    second = quarantine.capture_namespace(client)

    quarantine.assert_candidate_stability(first, second)
    drift = quarantine.namespace_drift(first, second)
    assert len(drift["content_type_or_classification_changed_key_b64"]) == 1
    payload = quarantine.build_archive_payload(
        first=first,
        second=second,
        first_services=_safe_services(),
        second_services=_safe_services(),
        first_writer_processes=[],
        second_writer_processes=[],
    )
    assert len(payload["inventory"]) == 2
    assert len(payload["cleanup_candidates"]) == 1


def test_apply_archive_is_atomic_protected_and_deletes_only_candidates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    legacy = quarantine.NAMESPACE + b"paper_intent_preview"
    receipt = quarantine.NAMESPACE + b"on_policy_receipt:def"
    current = quarantine.NAMESPACE + b"status"
    client = _FakeRedis(
        {
            legacy: _entry(b"legacy-intent", redis_type=b"list"),
            receipt: _entry(b"receipt"),
            current: _entry(b"current-status", pttl_ms=60_000),
        }
    )
    snapshot, payload = _archive_for(client)
    archive = repo / ".local_models/quarantine/trainer_redis_namespace/archive.json"

    persisted = quarantine.write_and_validate_archive(archive, payload, repo)
    deleted = quarantine.atomic_delete_candidates(client, payload["cleanup_candidates"])

    assert deleted == 1
    assert legacy not in client.entries
    assert receipt in client.entries
    assert current in client.entries
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(archive.parent.stat().st_mode) == 0o700
    assert persisted == payload
    loaded = quarantine.read_and_validate_archive(archive, repo)
    assert loaded["inventory_digest"] == snapshot.inventory_digest
    assert len(loaded["inventory"]) == 3


def test_archive_write_refuses_parent_outside_dedicated_quarantine_directory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = _FakeRedis({quarantine.NAMESPACE + b"status": _entry(b"legacy")})
    _, payload = _archive_for(client)

    with pytest.raises(
        quarantine.QuarantineError,
        match="ARCHIVE_PATH_MUST_USE_DEDICATED_QUARANTINE_DIRECTORY",
    ):
        quarantine.atomic_write_protected_json(repo / "archive.json", payload, repo)


def test_compare_before_delete_refuses_value_change_and_watch_conflict() -> None:
    key = quarantine.NAMESPACE + b"risk_decision_preview"
    client = _FakeRedis({key: _entry(b"archived")})
    _, payload = _archive_for(client)
    client.mutate(key, _entry(b"changed"))

    with pytest.raises(quarantine.QuarantineError, match="COMPARE_BEFORE_DELETE_MISMATCH"):
        quarantine.atomic_delete_candidates(client, payload["cleanup_candidates"])
    assert key in client.entries

    client.mutate(key, _entry(b"archived"))
    client.conflict_on_execute = True
    with pytest.raises(quarantine.QuarantineError, match="WATCH_CONFLICT"):
        quarantine.atomic_delete_candidates(client, payload["cleanup_candidates"])
    assert key in client.entries


def test_delete_post_exec_verification_disconnect_is_explicit() -> None:
    key = quarantine.NAMESPACE + b"status"
    client = _FakeRedis({key: _entry(b"legacy")})
    _, payload = _archive_for(client)
    original_exists = client.exists
    calls = 0

    def _disconnect_after_delete(observed_key: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls >= 1:
            raise ConnectionError("simulated post-EXEC disconnect")
        return original_exists(observed_key)

    client.exists = _disconnect_after_delete  # type: ignore[method-assign]
    with pytest.raises(
        quarantine.QuarantineError,
        match="DELETE_POST_EXEC_VERIFICATION_UNAVAILABLE",
    ):
        quarantine.atomic_delete_candidates(client, payload["cleanup_candidates"])
    assert key not in client.entries


def test_rollback_restores_only_deleted_candidate_and_refuses_overwrite(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    key = quarantine.NAMESPACE + b"heartbeat"
    receipt = quarantine.NAMESPACE + b"on_policy_receipt:keep"
    client = _FakeRedis({key: _entry(b"legacy-heartbeat"), receipt: _entry(b"receipt")})
    _, payload = _archive_for(client)
    archive = repo / ".local_models/quarantine/trainer_redis_namespace/archive.json"
    quarantine.atomic_write_protected_json(archive, payload, repo)
    quarantine.atomic_delete_candidates(client, payload["cleanup_candidates"])

    restored = quarantine.atomic_restore_candidates(client, payload["cleanup_candidates"])
    assert restored == 1
    assert client.dump(key) == b"legacy-heartbeat"
    assert client.pttl(key) == -1
    assert client.dump(receipt) == b"receipt"

    with pytest.raises(quarantine.QuarantineError, match="ROLLBACK_REFUSES_EXISTING_KEYS"):
        quarantine.atomic_restore_candidates(client, payload["cleanup_candidates"])


def test_archive_tampering_is_detected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    client = _FakeRedis({quarantine.NAMESPACE + b"status": _entry(b"legacy")})
    _, payload = _archive_for(client)
    archive = repo / ".local_models/quarantine/trainer_redis_namespace/archive.json"
    quarantine.atomic_write_protected_json(archive, payload, repo)
    material = json.loads(archive.read_text(encoding="utf-8"))
    material["inventory"][0]["redis_dump_rdb_b64"] = "dGFtcGVyZWQ="
    archive.write_text(json.dumps(material), encoding="utf-8")
    archive.chmod(0o600)

    with pytest.raises(quarantine.QuarantineError, match="ARCHIVE_PAYLOAD_DIGEST_MISMATCH"):
        quarantine.read_and_validate_archive(archive, repo)


@pytest.mark.parametrize(
    "target",
    [
        "redis://example.com:6379/0",
        "redis://127.0.0.1:6379/1",
        "redis://user:secret@127.0.0.1:6379/0",
        "rediss://127.0.0.1:6379/0",
        "redis://127.0.0.1:6380/0",
    ],
)
def test_redis_target_is_hard_bound_to_loopback_db_zero(target: str) -> None:
    with pytest.raises(quarantine.QuarantineError, match="REDIS_TARGET_MUST_BE_LOCAL_DB_ZERO"):
        quarantine.normalize_local_redis_target(target)


def test_archive_is_bound_to_normalized_local_redis_target() -> None:
    client = _FakeRedis({quarantine.NAMESPACE + b"status": _entry(b"legacy")})
    _, payload = _archive_for(client)
    payload["redis_target_contract"]["database_index"] = 1
    material = dict(payload)
    material.pop("archive_payload_sha256")
    payload["archive_payload_sha256"] = quarantine._sha256(quarantine._canonical_bytes(material))

    with pytest.raises(quarantine.QuarantineError, match="ARCHIVE_REDIS_TARGET_MISMATCH"):
        quarantine.validate_archive_payload(payload)


def test_parser_default_does_not_inherit_redis_url_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://example.com:6379/9")
    args = quarantine._parser().parse_args([])
    assert args.redis_url == quarantine.LOCAL_REDIS_TARGET


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--apply"], "APPLY_REQUIRES_EXACT_ACK"),
        ([quarantine.APPLY_ACK], "APPLY_ACK_WITHOUT_APPLY"),
        (["--rollback", "archive.json"], "ROLLBACK_REQUIRES_EXACT_ACK"),
        ([quarantine.ROLLBACK_ACK], "ROLLBACK_ACK_WITHOUT_ROLLBACK"),
    ],
)
def test_mutating_modes_require_exact_ack(arguments: list[str], message: str) -> None:
    args = quarantine._parser().parse_args(arguments)
    with pytest.raises(quarantine.QuarantineError, match=message):
        quarantine._validate_mode(args)


def test_service_gate_requires_every_canonical_unit_loaded_and_inactive() -> None:
    observations = _safe_services()
    assert quarantine.service_gate_safe(observations) is True
    observations[1]["active_state"] = "active"
    observations[1]["safe"] = False
    assert quarantine.service_gate_safe(observations) is False
    assert quarantine.service_gate_safe(observations[:-1]) is False
