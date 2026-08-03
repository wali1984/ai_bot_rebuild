"""Read-only verification of one immutable source-payload CAS object.

This audit-only primitive resolves an object from a trusted-caller-selected
absolute root and an exact lowercase SHA-256 digest.  It never instantiates the
mutating store and has no mkdir, chmod, fsync, write, runtime, Redis, network,
trainer, or trading behavior.

Successful return means only that the bytes read during this call matched the
filesystem and content-address contract.  The root must be an exact built-in
``str`` selected by a trusted caller.  Root selection is outside this module's
trust boundary, so returned bytes confer no source identity,
provenance, semantic, finality, trainer-admission, prediction, paper-trading,
or live-execution authority.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, NoReturn

from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    SourcePayloadAddress,
)

# These are parser and allocation safety constants.  They are unrelated to
# market conditions, strategy, risk, leverage, margin, sizing, or admission.
MAX_IMMUTABLE_SOURCE_PAYLOAD_BYTES_V4 = 256 * 1024 * 1024
READ_CHUNK_BYTES_V4 = 1024 * 1024
MAX_STORE_PATH_COMPONENTS_V4 = 128
MAX_STORE_ROOT_UTF8_BYTES_V4 = 4096

_MIN_PAYLOAD_BYTES = 1
_OBJECT_NAMESPACE = "sha256"
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_OBJECT_MODE = 0o400
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class ImmutableSourcePayloadReaderV4Error(RuntimeError):
    """Base error with a bounded, non-secret reason code."""


class ImmutableSourcePayloadReaderV4ValidationError(ImmutableSourcePayloadReaderV4Error):
    """Caller input violates the exact bounded reader contract."""


class ImmutableSourcePayloadReaderV4NotFoundError(ImmutableSourcePayloadReaderV4Error):
    """The requested root, namespace, shard, or object does not exist."""


class ImmutableSourcePayloadReaderV4IntegrityError(ImmutableSourcePayloadReaderV4Error):
    """A filesystem identity, mode, owner, size, or digest check failed."""


def _validation_error(reason: str) -> NoReturn:
    raise ImmutableSourcePayloadReaderV4ValidationError(reason) from None


def _not_found(reason: str) -> NoReturn:
    raise ImmutableSourcePayloadReaderV4NotFoundError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise ImmutableSourcePayloadReaderV4IntegrityError(reason) from None


def _validated_root_path(root_path: object) -> Path:
    if type(root_path) is not str:
        _validation_error("immutable_source_payload_root_exact_string_required")
    raw = root_path
    if "\x00" in raw:
        _validation_error("immutable_source_payload_root_nul_forbidden")
    try:
        encoded_root = raw.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _validation_error("immutable_source_payload_root_utf8_invalid")
    if len(encoded_root) > MAX_STORE_ROOT_UTF8_BYTES_V4:
        _validation_error("immutable_source_payload_root_too_long")
    root_path = Path(raw)
    if not root_path.is_absolute():
        _validation_error("immutable_source_payload_root_absolute_required")
    if any(component == ".." for component in root_path.parts):
        _validation_error("immutable_source_payload_root_traversal_forbidden")
    if root_path == Path(root_path.anchor) or root_path.name in {"", ".", ".."}:
        _validation_error("immutable_source_payload_root_invalid")
    if len(root_path.parts) - 1 > MAX_STORE_PATH_COMPONENTS_V4:
        _validation_error("immutable_source_payload_root_too_deep")
    return root_path


def _validated_digest(value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _validation_error("immutable_source_payload_sha256_invalid")
    return value


def _validated_byte_count(value: object, *, optional: bool) -> int | None:
    if optional and value is None:
        return None
    if (
        type(value) is not int
        or value < _MIN_PAYLOAD_BYTES
        or value > MAX_IMMUTABLE_SOURCE_PAYLOAD_BYTES_V4
    ):
        _validation_error("immutable_source_payload_byte_count_invalid")
    return value


def _relative_path_for(digest: str) -> str:
    return f"{_OBJECT_NAMESPACE}/{digest[:2]}/{digest}"


def _validated_address_count(
    address: object,
    *,
    digest: str,
    expected_byte_count: int | None,
) -> int | None:
    if address is None:
        return expected_byte_count
    if type(address) is not SourcePayloadAddress:
        _validation_error("immutable_source_payload_address_exact_type_required")
    try:
        schema_version = object.__getattribute__(address, "schema_version")
        payload_sha256 = object.__getattribute__(address, "payload_sha256")
        payload_byte_count = object.__getattribute__(address, "payload_byte_count")
        relative_path = object.__getattribute__(address, "relative_path")
    except (AttributeError, TypeError):
        _validation_error("immutable_source_payload_address_fields_invalid")
    if type(schema_version) is not str:
        _validation_error("immutable_source_payload_address_schema_invalid")
    if type(payload_sha256) is not str:
        _validation_error("immutable_source_payload_address_digest_invalid")
    if type(relative_path) is not str:
        _validation_error("immutable_source_payload_address_relative_path_invalid")
    if schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION:
        _validation_error("immutable_source_payload_address_schema_mismatch")
    if payload_sha256 != digest:
        _validation_error("immutable_source_payload_address_digest_mismatch")
    address_count = _validated_byte_count(payload_byte_count, optional=False)
    if relative_path != _relative_path_for(digest):
        _validation_error("immutable_source_payload_address_relative_path_mismatch")
    if expected_byte_count is not None and address_count != expected_byte_count:
        _validation_error("immutable_source_payload_address_byte_count_mismatch")
    return address_count


def _directory_open_flags(*, suppress_atime: bool) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    if suppress_atime:
        flags |= getattr(os, "O_NOATIME", 0)
    return flags


def _object_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    # CAS objects must be owned by the current euid.  O_NOATIME therefore both
    # avoids read-induced metadata changes and fails closed if that premise is
    # false on Linux.  On platforms without O_NOATIME, the flag is zero.
    flags |= getattr(os, "O_NOATIME", 0)
    return flags


def _safe_fstat(descriptor: int, *, reason: str) -> os.stat_result:
    try:
        return os.fstat(descriptor)
    except OSError:
        _integrity_error(reason)


def _safe_path_stat(parent_fd: int, name: str, *, reason: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        _not_found("immutable_source_payload_not_found")
    except OSError:
        _integrity_error(reason)


def _inode_identity(value: os.stat_result) -> tuple[int, int]:
    return (int(value.st_dev), int(value.st_ino))


def _object_fingerprint(
    value: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_nlink),
    )


class _DescriptorOwner:
    """Close every adopted descriptor, including after partial-open failures."""

    __slots__ = ("_closed", "_descriptors")

    def __init__(self) -> None:
        self._descriptors: list[int] = []
        self._closed = False

    def adopt(self, descriptor: int) -> int:
        self._descriptors.append(descriptor)
        return descriptor

    def close(self) -> bool:
        if self._closed:
            return False
        self._closed = True
        close_failed = False
        for descriptor in reversed(self._descriptors):
            try:
                os.close(descriptor)
            except OSError:
                close_failed = True
        self._descriptors.clear()
        return close_failed

    def __enter__(self) -> _DescriptorOwner:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> Literal[False]:
        close_failed = self.close()
        if close_failed and exc_type is None:
            _integrity_error("immutable_source_payload_descriptor_close_failed")
        return False


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int
    name: str
    descriptor: int
    identity: tuple[int, int]
    require_private: bool


def _open_directory(
    owner: _DescriptorOwner,
    *,
    parent_fd: int | None,
    name_or_path: str,
    suppress_atime: bool,
) -> int:
    try:
        if parent_fd is None:
            descriptor = os.open(
                name_or_path,
                _directory_open_flags(suppress_atime=suppress_atime),
            )
        else:
            descriptor = os.open(
                name_or_path,
                _directory_open_flags(suppress_atime=suppress_atime),
                dir_fd=parent_fd,
            )
    except FileNotFoundError:
        _not_found("immutable_source_payload_not_found")
    except OSError:
        _integrity_error("immutable_source_payload_directory_open_failed")
    return owner.adopt(descriptor)


def _validate_directory_stats(
    descriptor_stat: os.stat_result,
    path_stat: os.stat_result,
    *,
    expected_identity: tuple[int, int] | None,
    expected_owner_uid: int,
    require_private: bool,
) -> tuple[int, int]:
    if not stat.S_ISDIR(descriptor_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        _integrity_error("immutable_source_payload_path_component_not_directory")
    descriptor_identity = _inode_identity(descriptor_stat)
    if descriptor_identity != _inode_identity(path_stat):
        _integrity_error("immutable_source_payload_directory_inode_changed")
    if expected_identity is not None and descriptor_identity != expected_identity:
        _integrity_error("immutable_source_payload_directory_inode_changed")
    if require_private and (
        descriptor_stat.st_uid != expected_owner_uid or path_stat.st_uid != expected_owner_uid
    ):
        _integrity_error("immutable_source_payload_directory_owner_mismatch")
    if require_private and (
        stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
        or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
    ):
        _integrity_error("immutable_source_payload_directory_mode_mismatch")
    return descriptor_identity


def _append_directory_binding(
    owner: _DescriptorOwner,
    bindings: list[_DirectoryBinding],
    *,
    parent_fd: int,
    name: str,
    expected_owner_uid: int,
    require_private: bool,
) -> int:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        _validation_error("immutable_source_payload_path_component_invalid")
    descriptor = _open_directory(
        owner,
        parent_fd=parent_fd,
        name_or_path=name,
        suppress_atime=require_private,
    )
    descriptor_stat = _safe_fstat(
        descriptor,
        reason="immutable_source_payload_directory_stat_failed",
    )
    path_stat = _safe_path_stat(
        parent_fd,
        name,
        reason="immutable_source_payload_directory_stat_failed",
    )
    identity = _validate_directory_stats(
        descriptor_stat,
        path_stat,
        expected_identity=None,
        expected_owner_uid=expected_owner_uid,
        require_private=require_private,
    )
    bindings.append(
        _DirectoryBinding(
            parent_fd=parent_fd,
            name=name,
            descriptor=descriptor,
            identity=identity,
            require_private=require_private,
        )
    )
    return descriptor


def _verify_directory_bindings(
    *,
    anchor_fd: int,
    anchor_identity: tuple[int, int],
    bindings: list[_DirectoryBinding],
    expected_owner_uid: int,
) -> None:
    anchor_stat = _safe_fstat(
        anchor_fd,
        reason="immutable_source_payload_anchor_stat_failed",
    )
    if not stat.S_ISDIR(anchor_stat.st_mode) or _inode_identity(anchor_stat) != anchor_identity:
        _integrity_error("immutable_source_payload_anchor_inode_changed")
    for binding in bindings:
        descriptor_stat = _safe_fstat(
            binding.descriptor,
            reason="immutable_source_payload_directory_stat_failed",
        )
        path_stat = _safe_path_stat(
            binding.parent_fd,
            binding.name,
            reason="immutable_source_payload_directory_stat_failed",
        )
        _validate_directory_stats(
            descriptor_stat,
            path_stat,
            expected_identity=binding.identity,
            expected_owner_uid=expected_owner_uid,
            require_private=binding.require_private,
        )


def _open_object(
    owner: _DescriptorOwner,
    *,
    shard_fd: int,
    digest: str,
    expected_owner_uid: int,
) -> tuple[int, tuple[int, int, int, int, int, int, int, int]]:
    try:
        descriptor = os.open(digest, _object_open_flags(), dir_fd=shard_fd)
    except FileNotFoundError:
        _not_found("immutable_source_payload_not_found")
    except OSError:
        _integrity_error("immutable_source_payload_object_open_failed")
    owner.adopt(descriptor)
    descriptor_stat = _safe_fstat(
        descriptor,
        reason="immutable_source_payload_object_stat_failed",
    )
    path_stat = _safe_path_stat(
        shard_fd,
        digest,
        reason="immutable_source_payload_object_stat_failed",
    )
    if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        _integrity_error("immutable_source_payload_object_not_regular")
    if descriptor_stat.st_uid != expected_owner_uid or path_stat.st_uid != expected_owner_uid:
        _integrity_error("immutable_source_payload_object_owner_mismatch")
    if (
        stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_OBJECT_MODE
        or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_OBJECT_MODE
    ):
        _integrity_error("immutable_source_payload_object_mode_mismatch")
    if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
        _integrity_error("immutable_source_payload_object_hardlink_forbidden")
    descriptor_fingerprint = _object_fingerprint(descriptor_stat)
    if descriptor_fingerprint != _object_fingerprint(path_stat):
        _integrity_error("immutable_source_payload_object_inode_changed")
    return descriptor, descriptor_fingerprint


def _read_exact_payload(
    descriptor: int,
    *,
    digest: str,
    object_fingerprint: tuple[int, int, int, int, int, int, int, int],
    expected_byte_count: int | None,
) -> bytes:
    stored_size = object_fingerprint[2]
    if not _MIN_PAYLOAD_BYTES <= stored_size <= MAX_IMMUTABLE_SOURCE_PAYLOAD_BYTES_V4:
        _integrity_error("immutable_source_payload_stored_size_invalid")
    if expected_byte_count is not None and stored_size != expected_byte_count:
        _integrity_error("immutable_source_payload_stored_byte_count_mismatch")

    # Allocation occurs only after the descriptor-backed size is bounded.
    material = bytearray(stored_size)
    hasher = hashlib.sha256()
    offset = 0
    while offset < stored_size:
        requested = min(READ_CHUNK_BYTES_V4, stored_size - offset)
        try:
            chunk = os.pread(descriptor, requested, offset)
        except OSError:
            _integrity_error("immutable_source_payload_read_failed")
        if not chunk:
            _integrity_error("immutable_source_payload_truncated_during_read")
        if len(chunk) > requested:
            _integrity_error("immutable_source_payload_read_size_invalid")
        material[offset : offset + len(chunk)] = chunk
        hasher.update(chunk)
        offset += len(chunk)
    try:
        trailing = os.pread(descriptor, 1, stored_size)
    except OSError:
        _integrity_error("immutable_source_payload_read_failed")
    if trailing:
        _integrity_error("immutable_source_payload_grew_during_read")
    if hasher.hexdigest() != digest:
        _integrity_error("immutable_source_payload_sha256_mismatch")
    return bytes(material)


def _verify_object_after_read(
    descriptor: int,
    *,
    shard_fd: int,
    digest: str,
    expected_fingerprint: tuple[int, int, int, int, int, int, int, int],
) -> None:
    descriptor_stat = _safe_fstat(
        descriptor,
        reason="immutable_source_payload_object_stat_failed",
    )
    path_stat = _safe_path_stat(
        shard_fd,
        digest,
        reason="immutable_source_payload_object_stat_failed",
    )
    if (
        _object_fingerprint(descriptor_stat) != expected_fingerprint
        or _object_fingerprint(path_stat) != expected_fingerprint
    ):
        _integrity_error("immutable_source_payload_object_changed_during_read")


class ImmutableSourcePayloadReaderV4:
    """Audit-only, non-authoritative, read-only CAS verifier."""

    __slots__ = ("_owner_uid", "_root_path")

    def __init__(self, root_path: str) -> None:
        # Lexical validation only: construction opens and mutates nothing.
        self._root_path = _validated_root_path(root_path)
        self._owner_uid = os.geteuid()

    def read(
        self,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
        address: SourcePayloadAddress | None = None,
    ) -> bytes:
        """Return detached exact bytes after full descriptor/path verification."""

        digest = _validated_digest(payload_sha256)
        validated_count = _validated_byte_count(expected_byte_count, optional=True)
        validated_count = _validated_address_count(
            address,
            digest=digest,
            expected_byte_count=validated_count,
        )
        if os.geteuid() != self._owner_uid:
            _integrity_error("immutable_source_payload_process_owner_changed")

        bindings: list[_DirectoryBinding] = []
        with _DescriptorOwner() as owner:
            anchor_fd = _open_directory(
                owner,
                parent_fd=None,
                name_or_path=self._root_path.anchor,
                suppress_atime=False,
            )
            anchor_stat = _safe_fstat(
                anchor_fd,
                reason="immutable_source_payload_anchor_stat_failed",
            )
            if not stat.S_ISDIR(anchor_stat.st_mode):
                _integrity_error("immutable_source_payload_anchor_not_directory")
            anchor_identity = _inode_identity(anchor_stat)

            parent_fd = anchor_fd
            components = self._root_path.parts[1:]
            for index, component in enumerate(components):
                parent_fd = _append_directory_binding(
                    owner,
                    bindings,
                    parent_fd=parent_fd,
                    name=component,
                    expected_owner_uid=self._owner_uid,
                    require_private=index == len(components) - 1,
                )
            namespace_fd = _append_directory_binding(
                owner,
                bindings,
                parent_fd=parent_fd,
                name=_OBJECT_NAMESPACE,
                expected_owner_uid=self._owner_uid,
                require_private=True,
            )
            shard_fd = _append_directory_binding(
                owner,
                bindings,
                parent_fd=namespace_fd,
                name=digest[:2],
                expected_owner_uid=self._owner_uid,
                require_private=True,
            )
            _verify_directory_bindings(
                anchor_fd=anchor_fd,
                anchor_identity=anchor_identity,
                bindings=bindings,
                expected_owner_uid=self._owner_uid,
            )

            object_fd, object_fingerprint = _open_object(
                owner,
                shard_fd=shard_fd,
                digest=digest,
                expected_owner_uid=self._owner_uid,
            )
            result = _read_exact_payload(
                object_fd,
                digest=digest,
                object_fingerprint=object_fingerprint,
                expected_byte_count=validated_count,
            )
            _verify_object_after_read(
                object_fd,
                shard_fd=shard_fd,
                digest=digest,
                expected_fingerprint=object_fingerprint,
            )
            _verify_directory_bindings(
                anchor_fd=anchor_fd,
                anchor_identity=anchor_identity,
                bindings=bindings,
                expected_owner_uid=self._owner_uid,
            )
            if os.geteuid() != self._owner_uid:
                _integrity_error("immutable_source_payload_process_owner_changed")
            return result
