from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as ledger_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    FeatureSnapshotLedgerError,
    FeatureSnapshotWriterLease,
    FeatureSnapshotWriterLeaseError,
)


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _remove_artifact(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        path.rmdir()


def test_only_registered_exact_writer_lease_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"

    class DuckLease:
        def validate_for(self, _: Path) -> None:
            return

    class LeaseSubclass(FeatureSnapshotWriterLease):
        pass

    with pytest.raises(FeatureSnapshotWriterLeaseError, match="exact_authentic_type"):
        DurableFeatureSnapshotLedger(path, writer_lease=DuckLease())  # type: ignore[arg-type]
    subclass = object.__new__(LeaseSubclass)
    with pytest.raises(FeatureSnapshotWriterLeaseError, match="exact_authentic_type"):
        DurableFeatureSnapshotLedger(path, writer_lease=subclass)

    real = FeatureSnapshotWriterLease.acquire(path)
    try:
        forged = object.__new__(FeatureSnapshotWriterLease)
        for slot in FeatureSnapshotWriterLease.__slots__:
            if slot != "__weakref__":
                setattr(forged, slot, getattr(real, slot))
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="exact_authentic_type"):
            DurableFeatureSnapshotLedger(path, writer_lease=forged)
        DurableFeatureSnapshotLedger(path, writer_lease=real)
    finally:
        real.release()


def test_database_hardlinks_are_rejected_across_alias_paths(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    alias = tmp_path / "ledger-alias.sqlite3"
    DurableFeatureSnapshotLedger(path).initialize()
    os.link(path, alias)

    with pytest.raises(FeatureSnapshotWriterLeaseError, match="hardlink_forbidden"):
        FeatureSnapshotWriterLease.acquire(path)
    with pytest.raises(FeatureSnapshotWriterLeaseError, match="hardlink_forbidden"):
        FeatureSnapshotWriterLease.acquire(alias)

    alias.unlink()
    with FeatureSnapshotWriterLease.acquire(path) as lease:
        assert lease.held is True


def test_new_hardlink_invalidates_continuously_held_database_inode(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    alias = tmp_path / "ledger-alias.sqlite3"
    DurableFeatureSnapshotLedger(path).initialize()
    lease = FeatureSnapshotWriterLease.acquire(path)
    try:
        os.link(path, alias)
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="hardlink_forbidden"):
            lease.validate_for(path)
    finally:
        alias.unlink(missing_ok=True)
        lease.release()


def test_lease_acquired_before_initialization_binds_stable_database_inode(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    lease = FeatureSnapshotWriterLease.acquire(path)
    try:
        assert lease.contract()["ledger_inode_lock_held"] is False
        ledger = DurableFeatureSnapshotLedger(path, writer_lease=lease)
        ledger.initialize()
        first_identity = (path.stat().st_dev, path.stat().st_ino)
        assert lease.contract()["ledger_inode_lock_held"] is True
        ledger.initialize()
        assert (path.stat().st_dev, path.stat().st_ino) == first_identity
    finally:
        lease.release()


def test_bound_database_path_substitution_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.sqlite3"
    displaced = tmp_path / "displaced.sqlite3"
    DurableFeatureSnapshotLedger(path).initialize()
    lease = FeatureSnapshotWriterLease.acquire(path)
    try:
        path.rename(displaced)
        shutil.copy2(displaced, path)
        with pytest.raises(FeatureSnapshotWriterLeaseError, match="inode_changed"):
            lease.validate_for(path)
    finally:
        lease.release()


@pytest.mark.parametrize("role", ["main", "wal", "shm", "journal", "writer_lock"])
@pytest.mark.parametrize("attack", ["symlink", "fifo", "directory", "hardlink"])
def test_every_storage_artifact_rejects_unsafe_file_types_and_aliases(
    tmp_path: Path,
    role: str,
    attack: str,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    artifact = ledger_module._feature_snapshot_sqlite_artifact_paths(path)[role]
    _remove_artifact(artifact)
    sentinel = tmp_path / f"sentinel-{role}-{attack}"
    sentinel.write_bytes(b"operator-owned-sentinel")
    before_sha256 = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    before_mtime_ns = sentinel.stat().st_mtime_ns

    if attack == "symlink":
        artifact.symlink_to(sentinel)
    elif attack == "fifo":
        os.mkfifo(artifact)
    elif attack == "directory":
        artifact.mkdir()
    else:
        os.link(sentinel, artifact)

    with pytest.raises(FeatureSnapshotLedgerError):
        ledger.initialize()
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before_sha256
    assert sentinel.stat().st_mtime_ns == before_mtime_ns


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    path = alias_parent / "ledger.sqlite3"

    with pytest.raises(FeatureSnapshotLedgerError, match="parent_symlink_forbidden"):
        DurableFeatureSnapshotLedger(path).initialize()
    assert not (real_parent / "ledger.sqlite3").exists()


@pytest.mark.parametrize("role", ["wal", "shm", "journal"])
@pytest.mark.parametrize("empty_main", [False, True])
def test_orphan_or_empty_main_sidecars_fail_before_sqlite_open(
    tmp_path: Path,
    role: str,
    empty_main: bool,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    if empty_main:
        path.touch()
    sidecar = ledger_module._feature_snapshot_sqlite_artifact_paths(path)[role]
    sidecar.write_bytes(b"untrusted-sidecar")

    with pytest.raises(FeatureSnapshotLedgerError, match="sidecar"):
        DurableFeatureSnapshotLedger(path).initialize()
    assert path.exists() is empty_main
    if empty_main:
        assert path.stat().st_size == 0


def test_read_connection_detects_substitution_between_guard_and_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    displaced = tmp_path / "read-displaced.sqlite3"
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    original_connect = sqlite3.connect
    swapped = False

    def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal swapped
        if kwargs.get("uri") is True and not swapped:
            swapped = True
            path.rename(displaced)
            shutil.copy2(displaced, path)
        return original_connect(database, *args, **kwargs)

    before_fds = _fd_count()
    monkeypatch.setattr(sqlite3, "connect", swapping_connect)
    with pytest.raises(FeatureSnapshotLedgerError, match="inode_changed"):
        ledger.verify_integrity_streaming()
    assert swapped is True
    assert _fd_count() == before_fds


def test_write_connection_detects_substitution_before_pragmas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    displaced = tmp_path / "write-displaced.sqlite3"
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    original_connect = sqlite3.connect
    swapped = False

    def swapping_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal swapped
        if kwargs.get("uri") is not True and not swapped:
            swapped = True
            path.rename(displaced)
            shutil.copy2(displaced, path)
        return original_connect(database, *args, **kwargs)

    before_fds = _fd_count()
    monkeypatch.setattr(sqlite3, "connect", swapping_connect)
    with pytest.raises(FeatureSnapshotWriterLeaseError, match="inode_changed"):
        ledger.initialize()
    assert swapped is True
    assert _fd_count() == before_fds


def test_baseexception_paths_release_all_storage_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = DurableFeatureSnapshotLedger(path)
    before_fds = _fd_count()
    with pytest.raises(SystemExit):
        with ledger.writer_lease():
            raise SystemExit(9)
    assert _fd_count() == before_fds
    with FeatureSnapshotWriterLease.acquire(path):
        pass

    original_connect = sqlite3.connect

    def interrupt_connect(*_: Any, **__: Any) -> sqlite3.Connection:
        raise KeyboardInterrupt

    monkeypatch.setattr(sqlite3, "connect", interrupt_connect)
    with pytest.raises(KeyboardInterrupt):
        ledger.initialize()
    monkeypatch.setattr(sqlite3, "connect", original_connect)
    assert _fd_count() == before_fds
    with FeatureSnapshotWriterLease.acquire(path):
        pass


def test_bind_read_guard_keyboardinterrupt_releases_exact_guard_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    connection_type = ledger_module._StorageGuardedSQLiteConnection
    original_bind = connection_type.bind_read_guard

    def interrupt_bind(
        self: ledger_module._StorageGuardedSQLiteConnection,
        guard: ledger_module._FeatureSnapshotReadPathGuard,
    ) -> None:
        raise KeyboardInterrupt

    before_fds = _fd_count()
    monkeypatch.setattr(connection_type, "bind_read_guard", interrupt_bind)
    with pytest.raises(KeyboardInterrupt):
        ledger.verify_integrity_streaming()
    assert _fd_count() == before_fds

    monkeypatch.setattr(connection_type, "bind_read_guard", original_bind)
    assert ledger.verify_integrity_streaming().integrity_verified is True


def _open_foreign_wal(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    assert str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE foreign_owner(value TEXT)")
    connection.execute("INSERT INTO foreign_owner VALUES ('untouched')")
    connection.commit()
    return connection


def test_foreign_existing_shm_is_byte_and_mtime_immutable_on_rejection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "foreign.sqlite3"
    connection = _open_foreign_wal(path)
    shm_path = Path(f"{path}-shm")
    assert shm_path.is_file()
    before_bytes = shm_path.read_bytes()
    before_mtime_ns = shm_path.stat().st_mtime_ns
    try:
        with pytest.raises(
            FeatureSnapshotLedgerError,
            match="checkpoint_provenance_unattested",
        ):
            DurableFeatureSnapshotLedger(path).verify_integrity_streaming()
        assert shm_path.read_bytes() == before_bytes
        assert shm_path.stat().st_mtime_ns == before_mtime_ns
    finally:
        connection.close()


def test_foreign_wal_without_shm_is_rejected_without_creating_shm(
    tmp_path: Path,
) -> None:
    path = tmp_path / "foreign.sqlite3"
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    connection = _open_foreign_wal(path)
    main_bytes = path.read_bytes()
    wal_bytes = wal_path.read_bytes()
    connection.close()
    path.write_bytes(main_bytes)
    wal_path.write_bytes(wal_bytes)
    shm_path.unlink(missing_ok=True)
    before_wal_bytes = wal_path.read_bytes()
    before_wal_mtime_ns = wal_path.stat().st_mtime_ns

    with pytest.raises(
        FeatureSnapshotLedgerError,
        match="checkpoint_provenance_unattested",
    ):
        DurableFeatureSnapshotLedger(path).verify_integrity_streaming()
    assert not shm_path.exists()
    assert wal_path.read_bytes() == before_wal_bytes
    assert wal_path.stat().st_mtime_ns == before_wal_mtime_ns


def test_checkpointed_direct_read_and_integrity_preserve_results(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    assert not wal_path.exists()
    assert not shm_path.exists()

    connection = ledger._connect_readonly()
    try:
        assert int(connection.execute("PRAGMA application_id").fetchone()[0]) == (
            ledger_module._SQLITE_APPLICATION_ID
        )
        assert int(connection.execute("PRAGMA query_only").fetchone()[0]) == 1
    finally:
        connection.close()
    assert ledger.verify_integrity_streaming().integrity_verified is True


def test_operational_reader_observes_commit_completed_before_begin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    reader = ledger._connect_readonly()
    writer = sqlite3.connect(path)
    committed_user_version = ledger_module._SQLITE_USER_VERSION + 1
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(f"PRAGMA user_version={committed_user_version}")
        writer.commit()

        reader.execute("BEGIN")
        assert int(reader.execute("PRAGMA user_version").fetchone()[0]) == (
            committed_user_version
        )
        reader.commit()
    finally:
        writer.close()
        reader.close()


def test_pristine_main_with_wal_is_rejected_without_creating_shm(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pristine.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE temporary_owner(value TEXT)")
        connection.execute("DROP TABLE temporary_owner")
        connection.commit()
    finally:
        connection.close()
    assert path.stat().st_size > 0
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    wal_path.write_bytes(b"unattested-wal-material")

    with pytest.raises(
        FeatureSnapshotLedgerError,
        match="checkpoint_provenance_unattested",
    ):
        DurableFeatureSnapshotLedger(path).verify_integrity_streaming()
    assert not shm_path.exists()


def test_valid_checkpointed_canonical_main_allows_wal_aware_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.sqlite3"
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    ledger = DurableFeatureSnapshotLedger(path)
    ledger.initialize()
    writer = sqlite3.connect(path)
    try:
        assert str(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(f"PRAGMA user_version={ledger_module._SQLITE_USER_VERSION}")
        writer.commit()
        assert wal_path.is_file()
        assert shm_path.is_file()

        direct = ledger._connect_readonly()
        try:
            assert int(direct.execute("PRAGMA user_version").fetchone()[0]) == (
                ledger_module._SQLITE_USER_VERSION
            )
        finally:
            direct.close()
        assert ledger.verify_integrity_streaming().integrity_verified is True
    finally:
        writer.close()
