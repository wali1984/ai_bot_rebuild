"""Immutable content-addressed storage for exact source payload bytes.

This module is an intentionally unwired storage primitive for the durable
feature snapshot ledger.  It does not read Redis, call an exchange, or alter a
trainer.  Callers supply exact ``bytes`` and receive a SHA-256 address plus the
verified byte count.

Objects are created as anonymous Linux ``O_TMPFILE`` inodes and atomically
linked at their final address with ``linkat(AT_EMPTY_PATH)`` after an exact
pre-publication byte readback and file fsync.  The containing directory is then
fsynced and the final named inode is read back again.  Every path component is
opened relative to an already-verified directory descriptor with
``O_NOFOLLOW``.  Existing objects are accepted idempotently only after durable,
byte-for-byte verification.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_PAYLOAD_STORE_SCHEMA_VERSION = "immutable_source_payload_store_v1"
SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION = "source_payload_content_address_v1"
DEFAULT_MAX_SOURCE_PAYLOAD_BYTES = 256 * 1024 * 1024
MIN_SOURCE_PAYLOAD_BYTES = 1
READ_CHUNK_BYTES = 1024 * 1024

_OBJECT_NAMESPACE = "sha256"
_MAX_PATH_COMPONENTS = 128
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHARD_RE = re.compile(r"^[0-9a-f]{2}$")
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_OBJECT_MODE = 0o400
_ANONYMOUS_OBJECT_BUILD_MODE = 0o600
_AT_EMPTY_PATH = 0x1000


class SourcePayloadStoreError(RuntimeError):
    """Base error for source-payload storage failures."""


class SourcePayloadValidationError(SourcePayloadStoreError):
    """The caller supplied an invalid payload, digest, count, or store path."""


class SourcePayloadIntegrityError(SourcePayloadStoreError):
    """Stored bytes or their filesystem identity violate the store contract."""


class SourcePayloadCollisionError(SourcePayloadIntegrityError):
    """An address already exists but does not contain the exact supplied bytes."""


class SourcePayloadNotFoundError(SourcePayloadStoreError):
    """No immutable object exists at a valid content address."""


class _SourcePayloadDirectoryMissingError(SourcePayloadIntegrityError):
    """Internal distinction between an absent shard and an unsafe shard."""


@dataclass(frozen=True, slots=True)
class SourcePayloadAddress:
    """Stable locator returned after a successful put or verification."""

    schema_version: str
    payload_sha256: str
    payload_byte_count: int
    relative_path: str


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int
    name: str
    child_fd: int
    identity: tuple[int, int]
    private_owner_uid: int | None = None


class _DirectoryChain:
    """Descriptor-retained, no-symlink walk of an absolute directory path."""

    __slots__ = ("_bindings", "_closed", "_descriptors")

    def __init__(self, root_fd: int) -> None:
        self._descriptors = [root_fd]
        self._bindings: list[_DirectoryBinding] = []
        self._closed = False

    @property
    def final_fd(self) -> int:
        if self._closed:
            raise SourcePayloadIntegrityError("source_payload_directory_chain_closed")
        return self._descriptors[-1]

    @property
    def final_identity(self) -> tuple[int, int]:
        descriptor_stat = os.fstat(self.final_fd)
        return (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))

    def append(self, name: str, *, create: bool) -> bool:
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise SourcePayloadValidationError("source_payload_path_component_invalid")
        parent_fd = self.final_fd
        created = False
        if create:
            try:
                os.mkdir(name, mode=_PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                raise SourcePayloadStoreError(
                    "source_payload_directory_create_failed"
                ) from exc
            else:
                created = True
            # ``EEXIST`` may be a retry after this exact directory entry was
            # created but its containing-parent fsync failed.  Take over that
            # missed durability before treating either path as successful.
            _fsync_directory(parent_fd)
        flags = os.O_RDONLY
        flags |= getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError as exc:
            raise _SourcePayloadDirectoryMissingError(
                "source_payload_directory_missing"
            ) from exc
        except OSError as exc:
            raise SourcePayloadIntegrityError(
                "source_payload_directory_open_failed"
            ) from exc
        try:
            descriptor_stat = os.fstat(child_fd)
            path_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISDIR(descriptor_stat.st_mode) or not stat.S_ISDIR(
                path_stat.st_mode
            ):
                raise SourcePayloadIntegrityError(
                    "source_payload_path_component_not_directory"
                )
            identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
            if identity != (int(path_stat.st_dev), int(path_stat.st_ino)):
                raise SourcePayloadIntegrityError(
                    "source_payload_directory_inode_changed"
                )
        except BaseException:
            os.close(child_fd)
            raise
        self._descriptors.append(child_fd)
        self._bindings.append(
            _DirectoryBinding(
                parent_fd=parent_fd,
                name=name,
                child_fd=child_fd,
                identity=identity,
            )
        )
        return created

    def require_final_private(self, *, expected_owner_uid: int) -> None:
        """Pin owner-only mode validation to the current final binding."""

        if self._closed or not self._bindings:
            raise SourcePayloadIntegrityError(
                "source_payload_private_directory_binding_missing"
            )
        binding = self._bindings[-1]
        try:
            descriptor_stat = os.fstat(binding.child_fd)
            path_stat = os.stat(
                binding.name,
                dir_fd=binding.parent_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise SourcePayloadIntegrityError(
                "source_payload_directory_binding_missing"
            ) from exc
        _validate_private_directory_stats(
            descriptor_stat,
            path_stat,
            expected_owner_uid=expected_owner_uid,
        )
        self._bindings[-1] = _DirectoryBinding(
            parent_fd=binding.parent_fd,
            name=binding.name,
            child_fd=binding.child_fd,
            identity=binding.identity,
            private_owner_uid=expected_owner_uid,
        )

    def verify(self) -> None:
        if self._closed:
            raise SourcePayloadIntegrityError("source_payload_directory_chain_closed")
        for binding in self._bindings:
            try:
                descriptor_stat = os.fstat(binding.child_fd)
                path_stat = os.stat(
                    binding.name,
                    dir_fd=binding.parent_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SourcePayloadIntegrityError(
                    "source_payload_directory_binding_missing"
                ) from exc
            if not stat.S_ISDIR(descriptor_stat.st_mode) or not stat.S_ISDIR(
                path_stat.st_mode
            ):
                raise SourcePayloadIntegrityError(
                    "source_payload_directory_binding_not_directory"
                )
            if (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino)) != (
                binding.identity
            ) or (int(path_stat.st_dev), int(path_stat.st_ino)) != binding.identity:
                raise SourcePayloadIntegrityError(
                    "source_payload_directory_inode_changed"
                )
            if binding.private_owner_uid is not None:
                _validate_private_directory_stats(
                    descriptor_stat,
                    path_stat,
                    expected_owner_uid=binding.private_owner_uid,
                )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close_error: BaseException | None = None
        for descriptor in reversed(self._descriptors):
            try:
                os.close(descriptor)
            except BaseException as exc:
                if close_error is None:
                    close_error = exc
        self._descriptors.clear()
        self._bindings.clear()
        if close_error is not None:
            raise SourcePayloadStoreError(
                "source_payload_directory_close_failed"
            ) from close_error

    def __enter__(self) -> _DirectoryChain:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _fsync_directory(directory_fd: int) -> None:
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        raise SourcePayloadStoreError("source_payload_directory_fsync_failed") from exc


def _validate_private_directory_stats(
    descriptor_stat: os.stat_result,
    path_stat: os.stat_result,
    *,
    expected_owner_uid: int,
) -> None:
    if (
        descriptor_stat.st_uid != expected_owner_uid
        or path_stat.st_uid != expected_owner_uid
    ):
        raise SourcePayloadIntegrityError(
            "source_payload_directory_owner_mismatch"
        )
    if (
        stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
        or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
    ):
        raise SourcePayloadIntegrityError(
            "source_payload_directory_private_mode_required"
        )


def _lexical_absolute_store_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise SourcePayloadValidationError("source_payload_store_path_exact_path_required")
    raw = os.fspath(path.expanduser())
    if "\x00" in raw:
        raise SourcePayloadValidationError("source_payload_store_path_invalid")
    raw_parts = Path(raw).parts
    if any(component == ".." for component in raw_parts):
        raise SourcePayloadValidationError("source_payload_store_path_traversal_forbidden")
    exact = Path(os.path.abspath(raw))
    if exact == Path(exact.anchor) or exact.name in {"", ".", ".."}:
        raise SourcePayloadValidationError("source_payload_store_root_invalid")
    if len(exact.parts) - 1 > _MAX_PATH_COMPONENTS:
        raise SourcePayloadValidationError("source_payload_store_path_too_deep")
    return exact


def _open_absolute_directory_chain(path: Path, *, create_final: bool) -> _DirectoryChain:
    exact = _lexical_absolute_store_path(path)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        anchor_fd = os.open(exact.anchor, flags)
    except OSError as exc:
        raise SourcePayloadIntegrityError("source_payload_store_anchor_open_failed") from exc
    chain = _DirectoryChain(anchor_fd)
    try:
        components = exact.parts[1:]
        for index, component in enumerate(components):
            chain.append(
                component,
                create=create_final and index == len(components) - 1,
            )
        chain.verify()
    except BaseException:
        chain.close()
        raise
    return chain


def _validated_sha256(value: Any) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise SourcePayloadValidationError("source_payload_sha256_invalid")
    return value


def _validated_expected_byte_count(value: Any, *, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < MIN_SOURCE_PAYLOAD_BYTES or value > maximum:
        raise SourcePayloadValidationError("source_payload_expected_byte_count_invalid")
    return value


def _address_for(digest: str, byte_count: int) -> SourcePayloadAddress:
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=byte_count,
        relative_path=f"{_OBJECT_NAMESPACE}/{digest[:2]}/{digest}",
    )


def _open_regular_payload(
    directory_fd: int,
    name: str,
    *,
    missing_ok: bool,
    expected_owner_uid: int,
) -> tuple[int, os.stat_result] | None:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise SourcePayloadNotFoundError("source_payload_not_found") from None
    except OSError as exc:
        raise SourcePayloadIntegrityError("source_payload_object_open_failed") from exc
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(
            path_stat.st_mode
        ):
            raise SourcePayloadIntegrityError("source_payload_object_not_regular")
        if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
            raise SourcePayloadIntegrityError("source_payload_object_hardlink_forbidden")
        if (
            descriptor_stat.st_uid != expected_owner_uid
            or path_stat.st_uid != expected_owner_uid
        ):
            raise SourcePayloadIntegrityError("source_payload_object_owner_mismatch")
        if (
            stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_OBJECT_MODE
            or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_OBJECT_MODE
        ):
            raise SourcePayloadIntegrityError("source_payload_object_not_immutable_mode")
        identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
        if identity != (int(path_stat.st_dev), int(path_stat.st_ino)):
            raise SourcePayloadIntegrityError("source_payload_object_inode_changed")
        return descriptor, descriptor_stat
    except BaseException:
        os.close(descriptor)
        raise


def _verify_payload_binding(
    descriptor: int,
    directory_fd: int,
    name: str,
    *,
    expected_identity: tuple[int, int],
    expected_size: int,
    expected_owner_uid: int,
) -> os.stat_result:
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise SourcePayloadIntegrityError("source_payload_object_binding_missing") from exc
    descriptor_identity = (
        int(descriptor_stat.st_dev),
        int(descriptor_stat.st_ino),
    )
    path_identity = (int(path_stat.st_dev), int(path_stat.st_ino))
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or descriptor_stat.st_nlink != 1
        or path_stat.st_nlink != 1
        or descriptor_identity != expected_identity
        or path_identity != expected_identity
    ):
        raise SourcePayloadIntegrityError("source_payload_object_inode_changed")
    if descriptor_stat.st_size != expected_size or path_stat.st_size != expected_size:
        raise SourcePayloadIntegrityError("source_payload_object_size_changed")
    if (
        descriptor_stat.st_uid != expected_owner_uid
        or path_stat.st_uid != expected_owner_uid
    ):
        raise SourcePayloadIntegrityError("source_payload_object_owner_mismatch")
    if (
        stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_OBJECT_MODE
        or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_OBJECT_MODE
    ):
        raise SourcePayloadIntegrityError("source_payload_object_not_immutable_mode")
    return descriptor_stat


def _verify_anonymous_payload_descriptor(
    descriptor: int,
    *,
    expected_identity: tuple[int, int],
    expected_size: int,
    expected_owner_uid: int,
    expected_mode: int,
    expected_link_count: int,
) -> os.stat_result:
    try:
        descriptor_stat = os.fstat(descriptor)
    except OSError as exc:
        raise SourcePayloadIntegrityError(
            "source_payload_anonymous_inode_missing"
        ) from exc
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
        != expected_identity
    ):
        raise SourcePayloadIntegrityError(
            "source_payload_anonymous_inode_changed"
        )
    if descriptor_stat.st_nlink != expected_link_count:
        raise SourcePayloadIntegrityError(
            "source_payload_anonymous_link_count_invalid"
        )
    if descriptor_stat.st_uid != expected_owner_uid:
        raise SourcePayloadIntegrityError(
            "source_payload_object_owner_mismatch"
        )
    if stat.S_IMODE(descriptor_stat.st_mode) != expected_mode:
        raise SourcePayloadIntegrityError(
            "source_payload_anonymous_mode_invalid"
        )
    if descriptor_stat.st_size != expected_size:
        raise SourcePayloadIntegrityError(
            "source_payload_anonymous_size_changed"
        )
    return descriptor_stat


def _verify_anonymous_payload_bytes(
    descriptor: int,
    *,
    payload: bytes,
    digest: str,
    expected_identity: tuple[int, int],
    expected_owner_uid: int,
    expected_link_count: int,
) -> None:
    initial_stat = _verify_anonymous_payload_descriptor(
        descriptor,
        expected_identity=expected_identity,
        expected_size=len(payload),
        expected_owner_uid=expected_owner_uid,
        expected_mode=_PRIVATE_OBJECT_MODE,
        expected_link_count=expected_link_count,
    )
    initial_change_identity = (
        int(initial_stat.st_mtime_ns),
        int(initial_stat.st_ctime_ns),
    )
    view = memoryview(payload)
    hasher = hashlib.sha256()
    offset = 0
    while offset < len(payload):
        read_size = min(READ_CHUNK_BYTES, len(payload) - offset)
        try:
            chunk = os.pread(descriptor, read_size, offset)
        except OSError as exc:
            raise SourcePayloadIntegrityError(
                "source_payload_prepublish_read_failed"
            ) from exc
        if not chunk:
            raise SourcePayloadIntegrityError(
                "source_payload_prepublish_truncated"
            )
        if chunk != view[offset : offset + len(chunk)]:
            raise SourcePayloadIntegrityError(
                "source_payload_prepublish_bytes_mismatch"
            )
        hasher.update(chunk)
        offset += len(chunk)
    try:
        trailing = os.pread(descriptor, 1, len(payload))
    except OSError as exc:
        raise SourcePayloadIntegrityError(
            "source_payload_prepublish_read_failed"
        ) from exc
    if trailing:
        raise SourcePayloadIntegrityError("source_payload_prepublish_size_mismatch")
    final_stat = _verify_anonymous_payload_descriptor(
        descriptor,
        expected_identity=expected_identity,
        expected_size=len(payload),
        expected_owner_uid=expected_owner_uid,
        expected_mode=_PRIVATE_OBJECT_MODE,
        expected_link_count=expected_link_count,
    )
    if (
        int(final_stat.st_mtime_ns),
        int(final_stat.st_ctime_ns),
    ) != initial_change_identity:
        raise SourcePayloadIntegrityError(
            "source_payload_prepublish_changed_during_read"
        )
    if hasher.hexdigest() != digest:
        raise SourcePayloadIntegrityError(
            "source_payload_prepublish_sha256_mismatch"
        )


_LIBC = ctypes.CDLL(None, use_errno=True)
_LIBC_LINKAT = getattr(_LIBC, "linkat", None)
if _LIBC_LINKAT is not None:
    _LIBC_LINKAT.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    _LIBC_LINKAT.restype = ctypes.c_int


def _link_tmpfile_noreplace(
    anonymous_file_fd: int,
    destination_dir_fd: int,
    destination_name: str,
) -> None:
    """Atomically link an anonymous inode without replacing a destination."""

    if _LIBC_LINKAT is None:
        raise SourcePayloadStoreError("source_payload_linkat_empty_path_unsupported")
    result = _LIBC_LINKAT(
        anonymous_file_fd,
        b"",
        destination_dir_fd,
        os.fsencode(destination_name),
        _AT_EMPTY_PATH,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number), destination_name)
    raise OSError(error_number, os.strerror(error_number), destination_name)


class ImmutableSourcePayloadStore:
    """Durable, immutable SHA-256 store for exact raw source payloads."""

    __slots__ = (
        "_identity_lock",
        "_max_payload_bytes",
        "_namespace_identity",
        "_owner_uid",
        "_root_identity",
        "_root_path",
        "_shard_identities",
    )

    def __init__(
        self,
        root_path: Path,
        *,
        max_payload_bytes: int = DEFAULT_MAX_SOURCE_PAYLOAD_BYTES,
    ) -> None:
        if (
            type(max_payload_bytes) is not int
            or max_payload_bytes <= 0
            or max_payload_bytes > DEFAULT_MAX_SOURCE_PAYLOAD_BYTES
        ):
            raise SourcePayloadValidationError("source_payload_max_bytes_invalid")
        self._root_path = _lexical_absolute_store_path(root_path)
        self._max_payload_bytes = max_payload_bytes
        self._owner_uid = os.geteuid()
        self._identity_lock = threading.Lock()
        self._shard_identities: dict[str, tuple[int, int]] = {}
        chain = _open_absolute_directory_chain(self._root_path, create_final=True)
        try:
            self._root_identity = chain.final_identity
            chain.require_final_private(expected_owner_uid=self._owner_uid)
            chain.append(_OBJECT_NAMESPACE, create=True)
            self._namespace_identity = chain.final_identity
            chain.require_final_private(expected_owner_uid=self._owner_uid)
            chain.verify()
        finally:
            chain.close()

    @property
    def root_path(self) -> Path:
        return self._root_path

    @property
    def max_payload_bytes(self) -> int:
        return self._max_payload_bytes

    def path_for(self, payload_sha256: str) -> Path:
        """Return the deterministic path for a validated digest without opening it."""

        digest = _validated_sha256(payload_sha256)
        return self._root_path / _OBJECT_NAMESPACE / digest[:2] / digest

    def _open_shard_chain(
        self,
        digest: str,
        *,
        create_shard: bool,
    ) -> _DirectoryChain:
        if os.geteuid() != self._owner_uid:
            raise SourcePayloadIntegrityError(
                "source_payload_store_process_owner_changed"
            )
        chain = _open_absolute_directory_chain(self._root_path, create_final=False)
        try:
            if chain.final_identity != self._root_identity:
                raise SourcePayloadIntegrityError("source_payload_store_root_inode_changed")
            chain.require_final_private(expected_owner_uid=self._owner_uid)
            chain.append(_OBJECT_NAMESPACE, create=False)
            if chain.final_identity != self._namespace_identity:
                raise SourcePayloadIntegrityError(
                    "source_payload_store_namespace_inode_changed"
                )
            chain.require_final_private(expected_owner_uid=self._owner_uid)
            shard = digest[:2]
            if _SHARD_RE.fullmatch(shard) is None:
                raise SourcePayloadValidationError("source_payload_shard_invalid")
            try:
                chain.append(shard, create=create_shard)
            except _SourcePayloadDirectoryMissingError:
                if not create_shard:
                    raise SourcePayloadNotFoundError(
                        "source_payload_not_found"
                    ) from None
                raise
            shard_identity = chain.final_identity
            with self._identity_lock:
                prior_identity = self._shard_identities.setdefault(shard, shard_identity)
            if shard_identity != prior_identity:
                raise SourcePayloadIntegrityError("source_payload_store_shard_inode_changed")
            chain.require_final_private(expected_owner_uid=self._owner_uid)
            chain.verify()
            return chain
        except BaseException:
            chain.close()
            raise

    def put(
        self,
        payload: bytes,
        *,
        expected_sha256: str | None = None,
        expected_byte_count: int | None = None,
    ) -> SourcePayloadAddress:
        """Durably publish exact bytes, or verify an identical existing object."""

        if type(payload) is not bytes:
            raise SourcePayloadValidationError("source_payload_exact_bytes_required")
        payload_size = len(payload)
        if payload_size < MIN_SOURCE_PAYLOAD_BYTES:
            raise SourcePayloadValidationError("source_payload_empty_forbidden")
        if payload_size > self._max_payload_bytes:
            raise SourcePayloadValidationError("source_payload_size_limit_exceeded")
        validated_count = _validated_expected_byte_count(
            expected_byte_count,
            maximum=self._max_payload_bytes,
        )
        if validated_count is not None and validated_count != payload_size:
            raise SourcePayloadValidationError("source_payload_expected_byte_count_mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None:
            validated_digest = _validated_sha256(expected_sha256)
            if validated_digest != digest:
                raise SourcePayloadValidationError("source_payload_expected_sha256_mismatch")

        address = _address_for(digest, payload_size)
        chain = self._open_shard_chain(digest, create_shard=True)
        try:
            existing = _open_regular_payload(
                chain.final_fd,
                digest,
                missing_ok=True,
                expected_owner_uid=self._owner_uid,
            )
            if existing is not None:
                descriptor, descriptor_stat = existing
                try:
                    self._durably_verify_existing_against_bytes(
                        chain,
                        descriptor,
                        digest,
                        descriptor_stat,
                        payload,
                    )
                    return address
                finally:
                    os.close(descriptor)
            self._publish_new(chain, digest, payload)
            return address
        finally:
            chain.close()

    def get(
        self,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
    ) -> bytes:
        """Read and fully verify one bounded immutable object before returning it."""

        digest = _validated_sha256(payload_sha256)
        validated_count = _validated_expected_byte_count(
            expected_byte_count,
            maximum=self._max_payload_bytes,
        )
        chain = self._open_shard_chain(digest, create_shard=False)
        try:
            opened = _open_regular_payload(
                chain.final_fd,
                digest,
                missing_ok=False,
                expected_owner_uid=self._owner_uid,
            )
            if opened is None:  # pragma: no cover - ``missing_ok=False`` is exhaustive.
                raise SourcePayloadNotFoundError("source_payload_not_found")
            descriptor, descriptor_stat = opened
            try:
                result = self._read_verified(
                    descriptor,
                    chain.final_fd,
                    digest,
                    descriptor_stat,
                    expected_byte_count=validated_count,
                )
                chain.verify()
                return result
            finally:
                os.close(descriptor)
        finally:
            chain.close()

    def verify(
        self,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
    ) -> SourcePayloadAddress:
        """Stream-verify an object without materializing the full payload."""

        digest = _validated_sha256(payload_sha256)
        validated_count = _validated_expected_byte_count(
            expected_byte_count,
            maximum=self._max_payload_bytes,
        )
        chain = self._open_shard_chain(digest, create_shard=False)
        try:
            opened = _open_regular_payload(
                chain.final_fd,
                digest,
                missing_ok=False,
                expected_owner_uid=self._owner_uid,
            )
            if opened is None:  # pragma: no cover - ``missing_ok=False`` is exhaustive.
                raise SourcePayloadNotFoundError("source_payload_not_found")
            descriptor, descriptor_stat = opened
            try:
                byte_count = self._stream_and_verify(
                    descriptor,
                    chain.final_fd,
                    digest,
                    descriptor_stat,
                    expected_byte_count=validated_count,
                    compare_to=None,
                )
                chain.verify()
                return _address_for(digest, byte_count)
            finally:
                os.close(descriptor)
        finally:
            chain.close()

    def _validated_stored_size(
        self,
        descriptor_stat: os.stat_result,
        *,
        expected_byte_count: int | None,
    ) -> int:
        stored_size = int(descriptor_stat.st_size)
        if (
            stored_size < MIN_SOURCE_PAYLOAD_BYTES
            or stored_size > self._max_payload_bytes
        ):
            raise SourcePayloadIntegrityError("source_payload_stored_size_limit_exceeded")
        if expected_byte_count is not None and stored_size != expected_byte_count:
            raise SourcePayloadIntegrityError("source_payload_stored_byte_count_mismatch")
        return stored_size

    def _stream_and_verify(
        self,
        descriptor: int,
        directory_fd: int,
        digest: str,
        descriptor_stat: os.stat_result,
        *,
        expected_byte_count: int | None,
        compare_to: bytes | None,
    ) -> int:
        stored_size = self._validated_stored_size(
            descriptor_stat,
            expected_byte_count=expected_byte_count,
        )
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as exc:
            raise SourcePayloadIntegrityError("source_payload_seek_failed") from exc
        expected_identity = (
            int(descriptor_stat.st_dev),
            int(descriptor_stat.st_ino),
        )
        initial_change_identity = (
            int(descriptor_stat.st_mtime_ns),
            int(descriptor_stat.st_ctime_ns),
        )
        hasher = hashlib.sha256()
        offset = 0
        comparison_view = memoryview(compare_to) if compare_to is not None else None
        while offset < stored_size:
            chunk_size = min(READ_CHUNK_BYTES, stored_size - offset)
            try:
                chunk = os.read(descriptor, chunk_size)
            except OSError as exc:
                raise SourcePayloadIntegrityError("source_payload_read_failed") from exc
            if not chunk:
                raise SourcePayloadIntegrityError("source_payload_truncated_during_read")
            if comparison_view is not None and chunk != comparison_view[
                offset : offset + len(chunk)
            ]:
                raise SourcePayloadCollisionError("source_payload_address_collision")
            hasher.update(chunk)
            offset += len(chunk)
        try:
            trailing = os.read(descriptor, 1)
        except OSError as exc:
            raise SourcePayloadIntegrityError("source_payload_read_failed") from exc
        if trailing:
            raise SourcePayloadIntegrityError("source_payload_grew_during_read")
        final_stat = _verify_payload_binding(
            descriptor,
            directory_fd,
            digest,
            expected_identity=expected_identity,
            expected_size=stored_size,
            expected_owner_uid=self._owner_uid,
        )
        if (
            int(final_stat.st_mtime_ns),
            int(final_stat.st_ctime_ns),
        ) != initial_change_identity:
            raise SourcePayloadIntegrityError("source_payload_changed_during_read")
        if hasher.hexdigest() != digest:
            if compare_to is not None:
                raise SourcePayloadCollisionError("source_payload_address_collision")
            raise SourcePayloadIntegrityError("source_payload_sha256_mismatch")
        return stored_size

    def _read_verified(
        self,
        descriptor: int,
        directory_fd: int,
        digest: str,
        descriptor_stat: os.stat_result,
        *,
        expected_byte_count: int | None,
    ) -> bytes:
        stored_size = self._validated_stored_size(
            descriptor_stat,
            expected_byte_count=expected_byte_count,
        )
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
        except OSError as exc:
            raise SourcePayloadIntegrityError("source_payload_seek_failed") from exc
        expected_identity = (
            int(descriptor_stat.st_dev),
            int(descriptor_stat.st_ino),
        )
        initial_change_identity = (
            int(descriptor_stat.st_mtime_ns),
            int(descriptor_stat.st_ctime_ns),
        )
        # Allocation happens only after the trusted descriptor's size is bounded.
        result = bytearray(stored_size)
        view = memoryview(result)
        offset = 0
        hasher = hashlib.sha256()
        while offset < stored_size:
            read_size = min(READ_CHUNK_BYTES, stored_size - offset)
            try:
                count = os.readv(descriptor, [view[offset : offset + read_size]])
            except OSError as exc:
                raise SourcePayloadIntegrityError("source_payload_read_failed") from exc
            if count <= 0:
                raise SourcePayloadIntegrityError("source_payload_truncated_during_read")
            hasher.update(view[offset : offset + count])
            offset += count
        try:
            trailing = os.read(descriptor, 1)
        except OSError as exc:
            raise SourcePayloadIntegrityError("source_payload_read_failed") from exc
        if trailing:
            raise SourcePayloadIntegrityError("source_payload_grew_during_read")
        final_stat = _verify_payload_binding(
            descriptor,
            directory_fd,
            digest,
            expected_identity=expected_identity,
            expected_size=stored_size,
            expected_owner_uid=self._owner_uid,
        )
        if (
            int(final_stat.st_mtime_ns),
            int(final_stat.st_ctime_ns),
        ) != initial_change_identity:
            raise SourcePayloadIntegrityError("source_payload_changed_during_read")
        if hasher.hexdigest() != digest:
            raise SourcePayloadIntegrityError("source_payload_sha256_mismatch")
        return bytes(result)

    def _verify_existing_against_bytes(
        self,
        descriptor: int,
        directory_fd: int,
        digest: str,
        descriptor_stat: os.stat_result,
        payload: bytes,
    ) -> None:
        if descriptor_stat.st_size != len(payload):
            raise SourcePayloadCollisionError("source_payload_address_collision")
        self._stream_and_verify(
            descriptor,
            directory_fd,
            digest,
            descriptor_stat,
            expected_byte_count=len(payload),
            compare_to=payload,
        )

    def _durably_verify_existing_against_bytes(
        self,
        chain: _DirectoryChain,
        descriptor: int,
        digest: str,
        descriptor_stat: os.stat_result,
        payload: bytes,
    ) -> None:
        """Take over durability after an idempotent or racing publication."""

        self._verify_existing_against_bytes(
            descriptor,
            chain.final_fd,
            digest,
            descriptor_stat,
            payload,
        )
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise SourcePayloadStoreError("source_payload_file_fsync_failed") from exc
        _fsync_directory(chain.final_fd)
        chain.verify()
        self._verify_named_payload_via_fresh_chain(
            digest,
            payload,
            expected_identity=(
                int(descriptor_stat.st_dev),
                int(descriptor_stat.st_ino),
            ),
        )

    def _verify_named_payload_via_fresh_chain(
        self,
        digest: str,
        payload: bytes,
        *,
        expected_identity: tuple[int, int],
    ) -> None:
        """Re-resolve the namespace, inode, hash, count, and exact bytes."""

        fresh_chain = self._open_shard_chain(digest, create_shard=False)
        try:
            opened = _open_regular_payload(
                fresh_chain.final_fd,
                digest,
                missing_ok=False,
                expected_owner_uid=self._owner_uid,
            )
            if opened is None:  # pragma: no cover - exhaustive above.
                raise SourcePayloadNotFoundError(
                    "source_payload_not_found"
                ) from None
            descriptor, descriptor_stat = opened
            try:
                if (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino)) != (
                    expected_identity
                ):
                    raise SourcePayloadIntegrityError(
                        "source_payload_object_inode_changed"
                    )
                self._verify_existing_against_bytes(
                    descriptor,
                    fresh_chain.final_fd,
                    digest,
                    descriptor_stat,
                    payload,
                )
            finally:
                os.close(descriptor)
        finally:
            fresh_chain.close()

    def _publish_new(self, chain: _DirectoryChain, digest: str, payload: bytes) -> None:
        directory_fd = chain.final_fd
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if type(temporary_flag) is not int or temporary_flag == 0:
            raise SourcePayloadStoreError("source_payload_otmpfile_unsupported")
        flags = os.O_RDWR | temporary_flag
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = -1
        try:
            try:
                descriptor = os.open(
                    ".",
                    flags,
                    _ANONYMOUS_OBJECT_BUILD_MODE,
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                raise SourcePayloadStoreError(
                    "source_payload_otmpfile_open_failed"
                ) from exc
            descriptor_stat = os.fstat(descriptor)
            temporary_identity = (
                int(descriptor_stat.st_dev),
                int(descriptor_stat.st_ino),
            )
            _verify_anonymous_payload_descriptor(
                descriptor,
                expected_identity=temporary_identity,
                expected_size=0,
                expected_owner_uid=self._owner_uid,
                expected_mode=_ANONYMOUS_OBJECT_BUILD_MODE,
                expected_link_count=0,
            )
            view = memoryview(payload)
            written = 0
            while written < len(payload):
                try:
                    count = os.write(descriptor, view[written:])
                except OSError as exc:
                    raise SourcePayloadStoreError("source_payload_write_failed") from exc
                if count <= 0:
                    raise SourcePayloadStoreError("source_payload_write_incomplete")
                written += count
            _verify_anonymous_payload_descriptor(
                descriptor,
                expected_identity=temporary_identity,
                expected_size=len(payload),
                expected_owner_uid=self._owner_uid,
                expected_mode=_ANONYMOUS_OBJECT_BUILD_MODE,
                expected_link_count=0,
            )
            os.fchmod(descriptor, _PRIVATE_OBJECT_MODE)
            try:
                os.fsync(descriptor)
            except OSError as exc:
                raise SourcePayloadStoreError("source_payload_file_fsync_failed") from exc
            _verify_anonymous_payload_bytes(
                descriptor,
                payload=payload,
                digest=digest,
                expected_identity=temporary_identity,
                expected_owner_uid=self._owner_uid,
                expected_link_count=0,
            )
            chain.verify()
            try:
                _link_tmpfile_noreplace(
                    descriptor,
                    directory_fd,
                    digest,
                )
            except FileExistsError:
                _verify_anonymous_payload_descriptor(
                    descriptor,
                    expected_identity=temporary_identity,
                    expected_size=len(payload),
                    expected_owner_uid=self._owner_uid,
                    expected_mode=_PRIVATE_OBJECT_MODE,
                    expected_link_count=0,
                )
                existing = _open_regular_payload(
                    directory_fd,
                    digest,
                    missing_ok=False,
                    expected_owner_uid=self._owner_uid,
                )
                if existing is None:  # pragma: no cover - exhaustive above.
                    raise SourcePayloadNotFoundError(
                        "source_payload_not_found"
                    ) from None
                existing_fd, existing_stat = existing
                try:
                    self._durably_verify_existing_against_bytes(
                        chain,
                        existing_fd,
                        digest,
                        existing_stat,
                        payload,
                    )
                finally:
                    os.close(existing_fd)
                return
            except OSError as exc:
                raise SourcePayloadStoreError("source_payload_atomic_link_failed") from exc
            _verify_payload_binding(
                descriptor,
                directory_fd,
                digest,
                expected_identity=temporary_identity,
                expected_size=len(payload),
                expected_owner_uid=self._owner_uid,
            )
            _fsync_directory(directory_fd)
            chain.verify()
            _verify_payload_binding(
                descriptor,
                directory_fd,
                digest,
                expected_identity=temporary_identity,
                expected_size=len(payload),
                expected_owner_uid=self._owner_uid,
            )
            self._verify_named_payload_via_fresh_chain(
                digest,
                payload,
                expected_identity=temporary_identity,
            )
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


__all__ = [
    "DEFAULT_MAX_SOURCE_PAYLOAD_BYTES",
    "ImmutableSourcePayloadStore",
    "MIN_SOURCE_PAYLOAD_BYTES",
    "SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION",
    "SOURCE_PAYLOAD_STORE_SCHEMA_VERSION",
    "SourcePayloadAddress",
    "SourcePayloadCollisionError",
    "SourcePayloadIntegrityError",
    "SourcePayloadNotFoundError",
    "SourcePayloadStoreError",
    "SourcePayloadValidationError",
]
