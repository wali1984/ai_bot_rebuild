from __future__ import annotations

import errno
import hashlib
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NoReturn

import pytest

from v2.backend.app.services.native_trainer import (
    immutable_source_payload_store as store_module,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadCollisionError,
    SourcePayloadIntegrityError,
    SourcePayloadNotFoundError,
    SourcePayloadStoreError,
    SourcePayloadValidationError,
)


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _payload_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _create_read_only_at(
    directory_fd: int,
    name: str,
    payload: bytes,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def test_round_trip_retains_exact_raw_bytes_and_address(tmp_path: Path) -> None:
    payload = b"\x00raw\xffpayload\r\nwithout-normalization\x00"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    address = store.put(
        payload,
        expected_sha256=_payload_digest(payload),
        expected_byte_count=len(payload),
    )

    assert address.schema_version == SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
    assert address.payload_sha256 == _payload_digest(payload)
    assert address.payload_byte_count == len(payload)
    assert address.relative_path == (
        f"sha256/{address.payload_sha256[:2]}/{address.payload_sha256}"
    )
    assert store.get(
        address.payload_sha256,
        expected_byte_count=len(payload),
    ) == payload
    assert store.verify(address.payload_sha256) == address
    object_stat = store.path_for(address.payload_sha256).stat()
    assert stat.S_ISREG(object_stat.st_mode)
    assert object_stat.st_nlink == 1
    assert stat.S_IMODE(object_stat.st_mode) == 0o400
    assert object_stat.st_uid == os.geteuid()
    for directory in (
        store.root_path,
        store.root_path / "sha256",
        store.path_for(address.payload_sha256).parent,
    ):
        directory_stat = directory.stat()
        assert stat.S_IMODE(directory_stat.st_mode) == 0o700
        assert directory_stat.st_uid == os.geteuid()


def test_empty_payload_is_rejected_to_match_ledger_receipt_contract(
    tmp_path: Path,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    with pytest.raises(SourcePayloadValidationError, match="empty_forbidden"):
        store.put(b"")
    with pytest.raises(
        SourcePayloadValidationError,
        match="expected_byte_count_invalid",
    ):
        store.get(hashlib.sha256(b"").hexdigest(), expected_byte_count=0)


def test_idempotent_same_content_put_does_not_replace_inode(
    tmp_path: Path,
) -> None:
    payload = b"same exact source response"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    first = store.put(payload)
    path = store.path_for(first.payload_sha256)
    before = path.stat()

    second = store.put(payload)

    after = path.stat()
    assert second == first
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ctime_ns == before.st_ctime_ns


def test_concurrent_independent_writers_publish_one_immutable_inode(
    tmp_path: Path,
) -> None:
    payload = b"concurrent source payload" * 4096
    root = tmp_path / "payloads"
    stores = [ImmutableSourcePayloadStore(root) for _ in range(8)]
    barrier = threading.Barrier(len(stores))

    def put_after_barrier(store: ImmutableSourcePayloadStore) -> SourcePayloadAddress:
        barrier.wait(timeout=5)
        return store.put(payload)

    with ThreadPoolExecutor(max_workers=len(stores)) as executor:
        addresses = list(executor.map(put_after_barrier, stores))

    assert len(set(addresses)) == 1
    address = addresses[0]
    object_path = stores[0].path_for(address.payload_sha256)
    object_stat = object_path.stat()
    assert object_stat.st_nlink == 1
    assert stores[0].get(address.payload_sha256) == payload
    assert not any(
        path.name.startswith(".source-payload-tmp-")
        for path in object_path.parent.iterdir()
    )


@pytest.mark.parametrize(
    ("payload", "expected_sha256", "expected_byte_count", "reason"),
    [
        (b"payload", "0" * 64, None, "expected_sha256_mismatch"),
        (b"payload", None, 6, "expected_byte_count_mismatch"),
        (b"payload", "ABC", None, "sha256_invalid"),
    ],
)
def test_expected_digest_and_count_mismatches_write_nothing(
    tmp_path: Path,
    payload: bytes,
    expected_sha256: str | None,
    expected_byte_count: int | None,
    reason: str,
) -> None:
    root = tmp_path / "payloads"
    store = ImmutableSourcePayloadStore(root)

    with pytest.raises(SourcePayloadValidationError, match=reason):
        store.put(
            payload,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )

    assert list((root / "sha256").iterdir()) == []


def test_put_rejects_non_exact_bytes_before_invoking_conversion_hooks(
    tmp_path: Path,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    class HostileBytes(bytes):
        def __bytes__(self) -> bytes:
            raise AssertionError("conversion hook must not run")

    with pytest.raises(SourcePayloadValidationError, match="exact_bytes_required"):
        store.put(HostileBytes(b"payload"))
    with pytest.raises(SourcePayloadValidationError, match="exact_bytes_required"):
        store.put(bytearray(b"payload"))  # type: ignore[arg-type]


def test_put_enforces_configured_bound_before_hashing_or_opening_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "payloads"
    store = ImmutableSourcePayloadStore(root, max_payload_bytes=4)

    def forbidden_sha256(*_: object, **__: object) -> NoReturn:
        raise AssertionError("hashing must happen after the cheap size bound")

    monkeypatch.setattr(store_module.hashlib, "sha256", forbidden_sha256)
    with pytest.raises(SourcePayloadValidationError, match="size_limit_exceeded"):
        store.put(b"12345")
    assert list((root / "sha256").iterdir()) == []


@pytest.mark.parametrize(
    "digest",
    [
        "../" + "0" * 61,
        "/" + "0" * 63,
        "A" * 64,
        "0" * 63,
        "0" * 65,
        "00/" + "0" * 61,
        "0" * 63 + "\x00",
    ],
)
def test_digest_path_traversal_and_noncanonical_forms_are_rejected(
    tmp_path: Path,
    digest: str,
) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"operator-owned")
    before = sentinel.read_bytes()
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    with pytest.raises(SourcePayloadValidationError, match="sha256_invalid"):
        store.get(digest)
    with pytest.raises(SourcePayloadValidationError, match="sha256_invalid"):
        store.path_for(digest)

    assert sentinel.read_bytes() == before


def test_missing_read_does_not_create_a_shard(tmp_path: Path) -> None:
    root = tmp_path / "payloads"
    digest = "ff" + "0" * 62
    store = ImmutableSourcePayloadStore(root)

    with pytest.raises(SourcePayloadNotFoundError):
        store.get(digest)

    assert not (root / "sha256" / "ff").exists()


@pytest.mark.parametrize("attack", ["parent_symlink", "root_symlink"])
def test_symlinked_store_namespace_is_rejected_without_touching_target(
    tmp_path: Path,
    attack: str,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    sentinel = real / "sentinel"
    sentinel.write_bytes(b"operator-owned")
    before = sentinel.read_bytes()
    if attack == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(real, target_is_directory=True)
        root = alias / "payloads"
    else:
        root = tmp_path / "payloads"
        root.symlink_to(real, target_is_directory=True)

    with pytest.raises(SourcePayloadIntegrityError):
        ImmutableSourcePayloadStore(root)

    assert sentinel.read_bytes() == before


def test_symlinked_shard_is_rejected_without_touching_target(tmp_path: Path) -> None:
    root = tmp_path / "payloads"
    target = tmp_path / "attacker-directory"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_bytes(b"operator-owned")
    payload = b"payload"
    digest = _payload_digest(payload)
    store = ImmutableSourcePayloadStore(root)
    (root / "sha256" / digest[:2]).symlink_to(target, target_is_directory=True)

    with pytest.raises(SourcePayloadIntegrityError):
        store.get(digest)
    with pytest.raises(SourcePayloadIntegrityError):
        store.put(payload, expected_sha256=digest)

    assert sentinel.read_bytes() == b"operator-owned"
    assert list(target.iterdir()) == [sentinel]


@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory"])
def test_non_regular_object_attacks_fail_closed(
    tmp_path: Path,
    attack: str,
) -> None:
    payload = b"payload whose address is attacked"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    path = store.path_for(address.payload_sha256)
    path.unlink()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"operator-owned")
    before = sentinel.read_bytes()
    if attack == "symlink":
        path.symlink_to(sentinel)
    elif attack == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()

    with pytest.raises(SourcePayloadIntegrityError):
        store.get(address.payload_sha256)

    assert sentinel.read_bytes() == before


def test_hardlinked_object_is_rejected_for_read_verify_and_put(
    tmp_path: Path,
) -> None:
    payload = b"immutable payload"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    path = store.path_for(address.payload_sha256)
    alias = path.with_name("attacker-hardlink")
    os.link(path, alias)

    for operation in (
        lambda: store.get(address.payload_sha256),
        lambda: store.verify(address.payload_sha256),
        lambda: store.put(payload),
    ):
        with pytest.raises(SourcePayloadIntegrityError, match="hardlink_forbidden"):
            operation()


def test_corruption_fails_read_and_same_address_put_closed(tmp_path: Path) -> None:
    payload = b"original immutable source bytes"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    path = store.path_for(address.payload_sha256)
    path.chmod(0o600)
    path.write_bytes(b"X" * len(payload))
    path.chmod(0o400)

    with pytest.raises(SourcePayloadIntegrityError, match="sha256_mismatch"):
        store.get(address.payload_sha256)
    with pytest.raises(SourcePayloadCollisionError, match="address_collision"):
        store.put(payload)


def test_equal_length_os_write_corruption_is_rejected_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"prepublication exact-byte evidence"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    digest = _payload_digest(payload)
    original_write = os.write

    def corrupting_write(descriptor: int, data: object) -> int:
        material = bytes(data)  # type: ignore[arg-type]
        corrupted = bytes([material[0] ^ 0xFF]) + material[1:]
        return original_write(descriptor, corrupted)

    monkeypatch.setattr(store_module.os, "write", corrupting_write)
    with pytest.raises(SourcePayloadIntegrityError, match="prepublish_bytes_mismatch"):
        store.put(payload)

    assert not store.path_for(digest).exists()
    assert list(store.path_for(digest).parent.iterdir()) == []


def test_equal_length_corruption_after_link_is_rejected_by_final_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"final named inode exact-byte evidence"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    digest = _payload_digest(payload)
    original_link = store_module._link_tmpfile_noreplace

    def corrupting_link(
        anonymous_file_fd: int,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        original_link(anonymous_file_fd, destination_dir_fd, destination_name)
        assert os.pwrite(anonymous_file_fd, b"X", 0) == 1

    monkeypatch.setattr(store_module, "_link_tmpfile_noreplace", corrupting_link)
    with pytest.raises(SourcePayloadCollisionError, match="address_collision"):
        store.put(payload)

    with pytest.raises(SourcePayloadIntegrityError, match="sha256_mismatch"):
        store.get(digest)


@pytest.mark.parametrize("substitution_hook", ["directory_fsync", "chain_verify"])
def test_post_publish_substitution_after_durability_hooks_cannot_return_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution_hook: str,
) -> None:
    payload = b"same bytes but substituted inode"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    digest = _payload_digest(payload)
    path = store.path_for(digest)
    displaced = path.with_name(f"displaced-after-{substitution_hook}")
    swapped = False

    def substitute_once() -> None:
        nonlocal swapped
        if swapped or not path.exists():
            return
        swapped = True
        path.rename(displaced)
        path.write_bytes(payload)
        path.chmod(0o400)

    if substitution_hook == "directory_fsync":
        original_fsync_directory = store_module._fsync_directory

        def substituting_fsync(directory_fd: int) -> None:
            original_fsync_directory(directory_fd)
            substitute_once()

        monkeypatch.setattr(store_module, "_fsync_directory", substituting_fsync)
    else:
        original_verify = store_module._DirectoryChain.verify

        def substituting_verify(chain: object) -> None:
            original_verify(chain)  # type: ignore[arg-type]
            substitute_once()

        monkeypatch.setattr(store_module._DirectoryChain, "verify", substituting_verify)

    with pytest.raises(SourcePayloadIntegrityError, match="inode_changed"):
        store.put(payload)
    assert swapped is True


def test_shard_substitution_after_chain_verify_is_caught_by_fresh_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"fresh namespace resolution after durability"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    path = store.path_for(_payload_digest(payload))
    shard = path.parent
    displaced_shard = shard.with_name("displaced-after-chain-verify")
    original_verify = store_module._DirectoryChain.verify
    swapped = False

    def substituting_verify(chain: object) -> None:
        nonlocal swapped
        original_verify(chain)  # type: ignore[arg-type]
        if swapped or not path.exists():
            return
        swapped = True
        shard.rename(displaced_shard)
        shard.mkdir(mode=0o700)

    monkeypatch.setattr(store_module._DirectoryChain, "verify", substituting_verify)
    with pytest.raises(SourcePayloadIntegrityError, match="shard_inode_changed"):
        store.put(payload)
    assert swapped is True


def test_root_namespace_and_seen_shard_substitution_are_detected(
    tmp_path: Path,
) -> None:
    payload = b"pinned identities"

    root_store_path = tmp_path / "root-store"
    root_store = ImmutableSourcePayloadStore(root_store_path)
    root_address = root_store.put(payload)
    root_store_path.rename(tmp_path / "displaced-root")
    root_store_path.mkdir()
    with pytest.raises(SourcePayloadIntegrityError, match="root_inode_changed"):
        root_store.get(root_address.payload_sha256)

    namespace_store_path = tmp_path / "namespace-store"
    namespace_store = ImmutableSourcePayloadStore(namespace_store_path)
    namespace_address = namespace_store.put(payload)
    namespace = namespace_store_path / "sha256"
    namespace.rename(namespace_store_path / "displaced-namespace")
    namespace.mkdir()
    with pytest.raises(SourcePayloadIntegrityError, match="namespace_inode_changed"):
        namespace_store.get(namespace_address.payload_sha256)

    shard_store_path = tmp_path / "shard-store"
    shard_store = ImmutableSourcePayloadStore(shard_store_path)
    shard_address = shard_store.put(payload)
    shard = shard_store_path / "sha256" / shard_address.payload_sha256[:2]
    shard.rename(shard.with_name("displaced-shard"))
    shard.mkdir()
    with pytest.raises(SourcePayloadIntegrityError, match="shard_inode_changed"):
        shard_store.get(shard_address.payload_sha256)


def test_object_substitution_during_read_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"read binding" * 128
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    path = store.path_for(address.payload_sha256)
    displaced = path.with_name("displaced-object")
    original_readv = os.readv
    swapped = False

    def substituting_readv(descriptor: int, buffers: list[memoryview]) -> int:
        nonlocal swapped
        if not swapped:
            swapped = True
            path.rename(displaced)
            path.write_bytes(payload)
            path.chmod(0o400)
        return original_readv(descriptor, buffers)

    monkeypatch.setattr(store_module.os, "readv", substituting_readv)
    with pytest.raises(SourcePayloadIntegrityError, match="inode_changed"):
        store.get(address.payload_sha256)
    assert swapped is True


def test_oversized_stored_object_is_rejected_before_any_payload_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads", max_payload_bytes=32)
    digest = _payload_digest(b"claimed-address")
    path = store.path_for(digest)
    path.parent.mkdir(mode=0o700)
    with path.open("wb") as handle:
        handle.truncate(33)
    path.chmod(0o400)
    read_called = False

    def forbidden_read(*_: object, **__: object) -> NoReturn:
        nonlocal read_called
        read_called = True
        raise AssertionError("size must be bounded before reading or allocating")

    monkeypatch.setattr(store_module.os, "read", forbidden_read)
    monkeypatch.setattr(store_module.os, "readv", forbidden_read)
    with pytest.raises(SourcePayloadIntegrityError, match="stored_size_limit_exceeded"):
        store.get(digest)
    assert read_called is False


def test_expected_count_mismatch_is_rejected_before_payload_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"bounded object"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    read_called = False

    def forbidden_read(*_: object, **__: object) -> NoReturn:
        nonlocal read_called
        read_called = True
        raise AssertionError("count mismatch must reject before reading")

    monkeypatch.setattr(store_module.os, "read", forbidden_read)
    monkeypatch.setattr(store_module.os, "readv", forbidden_read)
    with pytest.raises(SourcePayloadIntegrityError, match="stored_byte_count_mismatch"):
        store.get(address.payload_sha256, expected_byte_count=len(payload) - 1)
    assert read_called is False


def test_file_fsync_precedes_atomic_link_and_directory_fsync_follows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    events: list[str] = []
    original_fsync = os.fsync
    original_link = store_module._link_tmpfile_noreplace

    def tracking_fsync(descriptor: int) -> None:
        descriptor_stat = os.fstat(descriptor)
        events.append("dir_fsync" if stat.S_ISDIR(descriptor_stat.st_mode) else "file_fsync")
        original_fsync(descriptor)

    def tracking_link(
        anonymous_file_fd: int,
        destination_dir_fd: int,
        destination_name: str,
    ) -> None:
        events.append("link_noreplace")
        original_link(
            anonymous_file_fd,
            destination_dir_fd,
            destination_name,
        )

    monkeypatch.setattr(store_module.os, "fsync", tracking_fsync)
    monkeypatch.setattr(store_module, "_link_tmpfile_noreplace", tracking_link)
    store.put(b"durability ordering")

    file_fsync_index = events.index("file_fsync")
    link_index = events.index("link_noreplace")
    assert file_fsync_index < link_index
    assert "dir_fsync" in events[link_index + 1 :]


def test_retry_after_post_link_fsync_failure_takes_over_durability_and_reverifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"retry takes over incomplete directory durability"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    path = store.path_for(_payload_digest(payload))
    original_fsync = os.fsync
    injected = False

    def fail_first_post_link_directory_fsync(descriptor: int) -> None:
        nonlocal injected
        descriptor_stat = os.fstat(descriptor)
        if stat.S_ISDIR(descriptor_stat.st_mode) and path.exists() and not injected:
            injected = True
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        original_fsync(descriptor)

    monkeypatch.setattr(store_module.os, "fsync", fail_first_post_link_directory_fsync)
    with pytest.raises(SourcePayloadStoreError, match="directory_fsync_failed"):
        store.put(payload)
    assert injected is True
    assert path.exists()

    events: list[str] = []
    original_verify = ImmutableSourcePayloadStore._verify_existing_against_bytes

    def tracking_fsync(descriptor: int) -> None:
        descriptor_stat = os.fstat(descriptor)
        events.append("dir_fsync" if stat.S_ISDIR(descriptor_stat.st_mode) else "file_fsync")
        original_fsync(descriptor)

    def tracking_verify(
        target_store: ImmutableSourcePayloadStore,
        descriptor: int,
        directory_fd: int,
        digest: str,
        descriptor_stat: os.stat_result,
        exact_payload: bytes,
    ) -> None:
        events.append("verify")
        original_verify(
            target_store,
            descriptor,
            directory_fd,
            digest,
            descriptor_stat,
            exact_payload,
        )

    monkeypatch.setattr(store_module.os, "fsync", tracking_fsync)
    monkeypatch.setattr(
        ImmutableSourcePayloadStore,
        "_verify_existing_against_bytes",
        tracking_verify,
    )
    address = store.put(payload)

    assert events == [
        "dir_fsync",  # Existing shard-entry durability takeover.
        "verify",
        "file_fsync",
        "dir_fsync",
        "verify",
    ]
    assert store.get(address.payload_sha256) == payload


def test_retry_reverification_detects_tamper_after_existing_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"retry must not trust its first verification"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    path = store.path_for(_payload_digest(payload))
    original_fsync = os.fsync
    injected_failure = False

    def fail_first_post_link_directory_fsync(descriptor: int) -> None:
        nonlocal injected_failure
        descriptor_stat = os.fstat(descriptor)
        if (
            stat.S_ISDIR(descriptor_stat.st_mode)
            and path.exists()
            and not injected_failure
        ):
            injected_failure = True
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        original_fsync(descriptor)

    monkeypatch.setattr(store_module.os, "fsync", fail_first_post_link_directory_fsync)
    with pytest.raises(SourcePayloadStoreError, match="directory_fsync_failed"):
        store.put(payload)
    monkeypatch.setattr(store_module.os, "fsync", original_fsync)

    original_fsync_directory = store_module._fsync_directory
    tampered = False

    def tamper_after_directory_fsync(directory_fd: int) -> None:
        nonlocal tampered
        original_fsync_directory(directory_fd)
        if not tampered:
            tampered = True
            path.chmod(0o600)
            path.write_bytes(b"X" * len(payload))
            path.chmod(0o400)

    monkeypatch.setattr(store_module, "_fsync_directory", tamper_after_directory_fsync)
    with pytest.raises(SourcePayloadCollisionError, match="address_collision"):
        store.put(payload)
    assert tampered is True


@pytest.mark.parametrize("directory_level", ["root", "namespace", "shard"])
def test_existing_directory_retry_takes_over_failed_parent_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directory_level: str,
) -> None:
    payload = b"directory entry durability takeover"
    digest = _payload_digest(payload)
    root = tmp_path / "payloads"
    original_fsync_directory = store_module._fsync_directory
    initial_store = (
        ImmutableSourcePayloadStore(root)
        if directory_level == "shard"
        else None
    )
    parent_path = {
        "root": tmp_path,
        "namespace": root,
        "shard": root / "sha256",
    }[directory_level]
    child_path = {
        "root": root,
        "namespace": root / "sha256",
        "shard": root / "sha256" / digest[:2],
    }[directory_level]
    injected = False

    def fail_after_directory_entry_creation(directory_fd: int) -> None:
        nonlocal injected
        descriptor_stat = os.fstat(directory_fd)
        parent_stat = parent_path.stat()
        if (
            not injected
            and child_path.exists()
            and (descriptor_stat.st_dev, descriptor_stat.st_ino)
            == (parent_stat.st_dev, parent_stat.st_ino)
        ):
            injected = True
            raise SourcePayloadStoreError("injected_parent_fsync_failure")
        original_fsync_directory(directory_fd)

    monkeypatch.setattr(
        store_module,
        "_fsync_directory",
        fail_after_directory_entry_creation,
    )
    with pytest.raises(SourcePayloadStoreError, match="injected_parent_fsync_failure"):
        if initial_store is None:
            ImmutableSourcePayloadStore(root)
        else:
            initial_store.put(payload)
    assert injected is True
    created_identity = (child_path.stat().st_dev, child_path.stat().st_ino)

    retry_parent_fsyncs = 0

    def tracking_retry_parent_fsync(directory_fd: int) -> None:
        nonlocal retry_parent_fsyncs
        descriptor_stat = os.fstat(directory_fd)
        parent_stat = parent_path.stat()
        if (descriptor_stat.st_dev, descriptor_stat.st_ino) == (
            parent_stat.st_dev,
            parent_stat.st_ino,
        ):
            retry_parent_fsyncs += 1
        original_fsync_directory(directory_fd)

    monkeypatch.setattr(
        store_module,
        "_fsync_directory",
        tracking_retry_parent_fsync,
    )
    retry_store = initial_store or ImmutableSourcePayloadStore(root)
    address = retry_store.put(payload)

    assert retry_parent_fsyncs >= 1
    assert (child_path.stat().st_dev, child_path.stat().st_ino) == created_identity
    assert retry_store.get(address.payload_sha256) == payload


@pytest.mark.parametrize("winner_matches", [True, False])
def test_concurrent_no_replace_winner_is_byte_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    winner_matches: bool,
) -> None:
    payload = b"concurrent exact payload"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    def competing_link(
        _anonymous_file_fd: int,
        destination_dir_fd: int,
        destination_name: str,
    ) -> NoReturn:
        winner_payload = payload if winner_matches else b"X" * len(payload)
        _create_read_only_at(destination_dir_fd, destination_name, winner_payload)
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), destination_name)

    monkeypatch.setattr(store_module, "_link_tmpfile_noreplace", competing_link)
    if winner_matches:
        address = store.put(payload)
        assert store.get(address.payload_sha256) == payload
    else:
        with pytest.raises(SourcePayloadCollisionError, match="address_collision"):
            store.put(payload)
    shard = store.path_for(_payload_digest(payload)).parent
    assert not any(path.name.startswith(".source-payload-tmp-") for path in shard.iterdir())


def test_link_failure_leaves_no_named_temporary_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"link failure"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    observed_anonymous_inode = False

    def failing_link(
        anonymous_file_fd: int,
        destination_dir_fd: int,
        _destination_name: str,
    ) -> NoReturn:
        nonlocal observed_anonymous_inode
        anonymous_stat = os.fstat(anonymous_file_fd)
        assert anonymous_stat.st_nlink == 0
        assert os.listdir(destination_dir_fd) == []
        observed_anonymous_inode = True
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(store_module, "_link_tmpfile_noreplace", failing_link)
    before_fds = _fd_count()
    with pytest.raises(SourcePayloadStoreError, match="atomic_link_failed"):
        store.put(payload)
    assert observed_anonymous_inode is True
    assert _fd_count() == before_fds
    shard = store.path_for(_payload_digest(payload)).parent
    assert list(shard.iterdir()) == []


@pytest.mark.parametrize("component", ["root", "namespace", "shard"])
@pytest.mark.parametrize("unsafe_mode", [0o750, 0o770, 0o707])
def test_store_directories_require_exact_private_owner_only_mode_each_operation(
    tmp_path: Path,
    component: str,
    unsafe_mode: int,
) -> None:
    payload = b"private directory contract"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    component_path = {
        "root": store.root_path,
        "namespace": store.root_path / "sha256",
        "shard": store.path_for(address.payload_sha256).parent,
    }[component]
    component_path.chmod(unsafe_mode)

    for operation in (
        lambda: store.get(address.payload_sha256),
        lambda: store.verify(address.payload_sha256),
        lambda: store.put(payload),
    ):
        with pytest.raises(
            SourcePayloadIntegrityError,
            match="directory_private_mode_required",
        ):
            operation()


@pytest.mark.parametrize("unsafe_mode", [0o440, 0o404, 0o600])
def test_objects_require_exact_private_read_only_mode_each_operation(
    tmp_path: Path,
    unsafe_mode: int,
) -> None:
    payload = b"private immutable object contract"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    store.path_for(address.payload_sha256).chmod(unsafe_mode)

    for operation in (
        lambda: store.get(address.payload_sha256),
        lambda: store.verify(address.payload_sha256),
        lambda: store.put(payload),
    ):
        with pytest.raises(
            SourcePayloadIntegrityError,
            match="object_not_immutable_mode",
        ):
            operation()


@pytest.mark.parametrize("target", ["directory", "object"])
def test_expected_owner_is_revalidated_from_open_descriptor_each_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    payload = b"owner identity contract"
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    address = store.put(payload)
    target_path = (
        store.path_for(address.payload_sha256).parent
        if target == "directory"
        else store.path_for(address.payload_sha256)
    )
    target_identity = (target_path.stat().st_dev, target_path.stat().st_ino)
    original_fstat = os.fstat

    def wrong_owner_fstat(descriptor: int) -> os.stat_result:
        observed = original_fstat(descriptor)
        if (observed.st_dev, observed.st_ino) != target_identity:
            return observed
        fields = list(observed)
        fields[4] = os.geteuid() + 1
        return os.stat_result(fields)

    monkeypatch.setattr(store_module.os, "fstat", wrong_owner_fstat)
    expected_reason = (
        "directory_owner_mismatch"
        if target == "directory"
        else "object_owner_mismatch"
    )
    with pytest.raises(SourcePayloadIntegrityError, match=expected_reason):
        store.get(address.payload_sha256)


def test_publication_uses_anonymous_tmpfile_without_named_cleanup_window() -> None:
    source = Path(store_module.__file__).read_text(encoding="utf-8")

    assert "O_TMPFILE" in source
    assert "AT_EMPTY_PATH" in source
    assert "os.unlink" not in source
    assert ".source-payload-tmp-" not in source


def test_module_has_no_runtime_or_exchange_wiring() -> None:
    source = Path(store_module.__file__).read_text(encoding="utf-8").lower()

    for forbidden in (
        "import redis",
        "from redis",
        "binance",
        "submit_order",
        "systemctl",
        "subprocess",
    ):
        assert forbidden not in source
