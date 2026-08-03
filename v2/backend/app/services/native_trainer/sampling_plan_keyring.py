"""Restart-safe HMAC key ring for authenticated sampling-plan envelopes.

The operator supplies an explicit absolute path to one private, canonical JSON
file.  This module does not read environment variables, Redis, or service
configuration and it does not wire itself into a trainer runtime.  It only
loads immutable key bytes for the sampling-plan envelope builder/verifier.

The public configuration fingerprint intentionally commits only to the schema,
active key ID, and retained key IDs.  It is useful for comparing redacted
configuration state without hashing or otherwise deriving output from secret
key material.
"""

from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    MIN_SAMPLING_PLAN_HMAC_KEY_BYTES,
)

SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION = "v2_sampling_plan_hmac_key_ring_v1"
SAMPLING_PLAN_KEY_RING_STATUS_SCHEMA_VERSION = "v2_sampling_plan_hmac_key_ring_redacted_status_v1"

# These are serialization and secret-storage safety bounds, not market gates.
MAX_SAMPLING_PLAN_KEY_RING_BYTES = 64 * 1024
MAX_RETAINED_SAMPLING_PLAN_KEYS = 128

_SAFE_AUTH_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
_LOWER_HEX_RE = re.compile(r"^(?:[0-9a-f]{2})+$")
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "active_key_id", "keys"})
_KEY_RECORD_FIELDS = frozenset({"encoding", "value"})


class SamplingPlanKeyRingError(RuntimeError):
    """Base class whose messages never contain key material."""


class SamplingPlanKeyRingValidationError(SamplingPlanKeyRingError):
    """The key-ring payload or explicit path violates the public contract."""


class SamplingPlanKeyRingIntegrityError(SamplingPlanKeyRingError):
    """The key-ring file or directory binding is not trustworthy."""


class SamplingPlanKeyResolutionError(LookupError, SamplingPlanKeyRingError):
    """A requested retained key ID is unknown or malformed."""


@dataclass(frozen=True, slots=True)
class SamplingPlanKeyRingStatus:
    """Secret-free metadata safe for status logs and operator evidence."""

    schema_version: str
    active_key_id: str
    retained_key_ids: tuple[str, ...]
    retained_key_count: int
    public_configuration_fingerprint: str


class SamplingPlanKeyRing:
    """Immutable active signing key plus retained historical verifier keys."""

    __slots__ = ("_active_key_id", "_keys", "_status")
    _active_key_id: str
    _keys: Mapping[str, bytes]
    _status: SamplingPlanKeyRingStatus

    def __init__(
        self,
        *,
        active_key_id: str,
        keys: Mapping[str, bytes],
    ) -> None:
        if type(active_key_id) is not str or _SAFE_AUTH_KEY_ID_RE.fullmatch(active_key_id) is None:
            raise SamplingPlanKeyRingValidationError("sampling_plan_active_key_id_invalid")
        if not isinstance(keys, Mapping):
            raise SamplingPlanKeyRingValidationError("sampling_plan_retained_keys_invalid")
        try:
            # The generator deliberately suppresses the caller's length hint.
            # Consequently this takes one items() snapshot without consulting
            # an adversarial Mapping.__len__ implementation.
            key_items = tuple(item for item in keys.items())
        except Exception:
            raise SamplingPlanKeyRingValidationError(
                "sampling_plan_retained_keys_invalid"
            ) from None
        if not key_items:
            raise SamplingPlanKeyRingValidationError("sampling_plan_retained_keys_invalid")
        if len(key_items) > MAX_RETAINED_SAMPLING_PLAN_KEYS:
            raise SamplingPlanKeyRingValidationError("sampling_plan_retained_keys_exceeded")
        validated_items: list[tuple[str, bytes]] = []
        seen_key_ids: set[str] = set()
        for item in key_items:
            if type(item) is not tuple or len(item) != 2:
                raise SamplingPlanKeyRingValidationError("sampling_plan_retained_keys_invalid")
            key_id, key_bytes = item
            if type(key_id) is not str or _SAFE_AUTH_KEY_ID_RE.fullmatch(key_id) is None:
                raise SamplingPlanKeyRingValidationError("sampling_plan_auth_key_id_invalid")
            if key_id in seen_key_ids:
                raise SamplingPlanKeyRingValidationError("sampling_plan_auth_key_id_duplicate")
            seen_key_ids.add(key_id)
            if type(key_bytes) is not bytes or len(key_bytes) < MIN_SAMPLING_PLAN_HMAC_KEY_BYTES:
                raise SamplingPlanKeyRingValidationError("sampling_plan_hmac_key_invalid")
            validated_items.append((key_id, key_bytes))
        copied = dict(validated_items)
        if active_key_id not in copied:
            raise SamplingPlanKeyRingValidationError("sampling_plan_active_key_missing")
        copied_keys: Mapping[str, bytes] = MappingProxyType(copied)
        retained_key_ids = tuple(sorted(copied_keys))
        public_material = {
            "active_key_id": active_key_id,
            "retained_key_ids": list(retained_key_ids),
            "schema_version": SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION,
        }
        public_fingerprint = hashlib.sha256(_canonical_json_bytes(public_material)).hexdigest()
        object.__setattr__(self, "_active_key_id", active_key_id)
        object.__setattr__(self, "_keys", copied_keys)
        object.__setattr__(
            self,
            "_status",
            SamplingPlanKeyRingStatus(
                schema_version=SAMPLING_PLAN_KEY_RING_STATUS_SCHEMA_VERSION,
                active_key_id=active_key_id,
                retained_key_ids=retained_key_ids,
                retained_key_count=len(retained_key_ids),
                public_configuration_fingerprint=public_fingerprint,
            ),
        )

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("sampling_plan_key_ring_is_immutable")

    @property
    def active_key_id(self) -> str:
        """Return the key ID to put in a newly built envelope."""

        return self._active_key_id

    @property
    def active_key(self) -> bytes:
        """Return immutable key bytes solely for the envelope builder."""

        return self._keys[self._active_key_id]

    @property
    def resolver(self) -> Callable[[str], bytes]:
        """Return the fail-closed resolver used by historical verification."""

        return self.resolve

    @property
    def status(self) -> SamplingPlanKeyRingStatus:
        """Return metadata containing no key bytes or secret-derived hashes."""

        return self._status

    def resolve(self, key_id: str) -> bytes:
        """Resolve one retained key without disclosing unknown IDs in errors."""

        if type(key_id) is not str or _SAFE_AUTH_KEY_ID_RE.fullmatch(key_id) is None:
            raise SamplingPlanKeyResolutionError("sampling_plan_auth_key_id_unknown")
        try:
            return self._keys[key_id]
        except KeyError:
            raise SamplingPlanKeyResolutionError("sampling_plan_auth_key_id_unknown") from None

    def __call__(self, key_id: str) -> bytes:
        return self.resolve(key_id)

    def __repr__(self) -> str:
        status = self._status
        return (
            "SamplingPlanKeyRing("
            f"active_key_id={status.active_key_id!r}, "
            f"retained_key_count={status.retained_key_count}, "
            "public_configuration_fingerprint="
            f"{status.public_configuration_fingerprint!r})"
        )


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int
    name: str
    child_fd: int
    identity: tuple[int, int]


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_json_invalid") from None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in pairs:
        if key in row:
            raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_duplicate_json_key")
        row[key] = value
    return row


def _reject_nonfinite_constant(_value: str) -> None:
    raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_json_invalid")


def _parse_canonical_payload(payload: bytes) -> dict[str, Any]:
    if not payload or len(payload) > MAX_SAMPLING_PLAN_KEY_RING_BYTES:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_payload_size_invalid")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_utf8_invalid") from None
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except SamplingPlanKeyRingValidationError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_json_invalid") from None
    if type(parsed) is not dict:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_shape_invalid")
    if payload != _canonical_json_bytes(parsed):
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_json_not_canonical")
    return parsed


def _decode_key_record(record: object) -> bytes:
    if type(record) is not dict or set(record) != _KEY_RECORD_FIELDS:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_record_shape_invalid")
    encoding = record.get("encoding")
    encoded_value = record.get("value")
    if type(encoded_value) is not str:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_invalid")
    if encoding == "base64":
        try:
            key_bytes = base64.b64decode(encoded_value.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error, ValueError):
            raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_invalid") from None
        if base64.b64encode(key_bytes).decode("ascii") != encoded_value:
            raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_not_canonical")
    elif encoding == "hex":
        if _LOWER_HEX_RE.fullmatch(encoded_value) is None:
            raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_invalid")
        try:
            key_bytes = bytes.fromhex(encoded_value)
        except ValueError:
            raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_invalid") from None
        if key_bytes.hex() != encoded_value:
            raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_not_canonical")
    else:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_encoding_invalid")
    if len(key_bytes) < MIN_SAMPLING_PLAN_HMAC_KEY_BYTES:
        raise SamplingPlanKeyRingValidationError("sampling_plan_hmac_key_too_short")
    return key_bytes


def _validated_ring_payload(payload: bytes) -> tuple[str, dict[str, bytes]]:
    parsed = _parse_canonical_payload(payload)
    if set(parsed) != _TOP_LEVEL_FIELDS:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_shape_invalid")
    if parsed.get("schema_version") != SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_schema_invalid")
    active_key_id = parsed.get("active_key_id")
    if type(active_key_id) is not str or _SAFE_AUTH_KEY_ID_RE.fullmatch(active_key_id) is None:
        raise SamplingPlanKeyRingValidationError("sampling_plan_active_key_id_invalid")
    encoded_keys = parsed.get("keys")
    if type(encoded_keys) is not dict or not encoded_keys:
        raise SamplingPlanKeyRingValidationError("sampling_plan_retained_keys_invalid")
    if len(encoded_keys) > MAX_RETAINED_SAMPLING_PLAN_KEYS:
        raise SamplingPlanKeyRingValidationError("sampling_plan_retained_keys_exceeded")
    keys: dict[str, bytes] = {}
    for key_id, record in encoded_keys.items():
        if type(key_id) is not str or _SAFE_AUTH_KEY_ID_RE.fullmatch(key_id) is None:
            raise SamplingPlanKeyRingValidationError("sampling_plan_auth_key_id_invalid")
        keys[key_id] = _decode_key_record(record)
    if active_key_id not in keys:
        raise SamplingPlanKeyRingValidationError("sampling_plan_active_key_missing")
    return active_key_id, keys


def _exact_absolute_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_explicit_path_required")
    raw = os.fspath(path)
    exact = Path(raw)
    if not raw or "\x00" in raw or not exact.is_absolute():
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_absolute_path_required")
    if any(component in {"", ".", ".."} for component in exact.parts[1:]):
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_path_invalid")
    if exact == Path(exact.anchor) or exact.name in {"", ".", ".."}:
        raise SamplingPlanKeyRingValidationError("sampling_plan_key_ring_path_invalid")
    return exact


_PLATFORM_CAPABILITY_REASON = "sampling_plan_key_ring_platform_capability_unsupported"
_UNSUPPORTED_PATH_ERRNOS = frozenset(
    {
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.ENOSYS),
        getattr(errno, "EOPNOTSUPP", errno.ENOSYS),
    }
)


def _platform_capability_error() -> None:
    raise SamplingPlanKeyRingIntegrityError(_PLATFORM_CAPABILITY_REASON) from None


def _required_os_flag(name: str) -> int:
    value = getattr(os, name, None)
    if type(value) is not int or value <= 0:
        _platform_capability_error()
    return cast(int, value)


def _require_secure_path_capabilities() -> None:
    _required_os_flag("O_DIRECTORY")
    _required_os_flag("O_NOFOLLOW")
    open_operation = getattr(os, "open", None)
    stat_operation = getattr(os, "stat", None)
    supports_dir_fd: object = getattr(os, "supports_dir_fd", None)
    supports_follow_symlinks: object = getattr(
        os,
        "supports_follow_symlinks",
        None,
    )
    if (
        not isinstance(supports_dir_fd, set)
        or not isinstance(supports_follow_symlinks, set)
        or not callable(open_operation)
        or not callable(stat_operation)
        or open_operation not in supports_dir_fd
        or stat_operation not in supports_dir_fd
        or stat_operation not in supports_follow_symlinks
        or not callable(getattr(os, "geteuid", None))
    ):
        _platform_capability_error()


def _raise_path_operation_error(exc: Exception, *, reason: str) -> None:
    if (
        isinstance(exc, NotImplementedError | TypeError | ValueError | AttributeError)
        or isinstance(exc, OSError)
        and exc.errno in _UNSUPPORTED_PATH_ERRNOS
    ):
        _platform_capability_error()
    raise SamplingPlanKeyRingIntegrityError(reason) from None


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= _required_os_flag("O_DIRECTORY")
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= _required_os_flag("O_NOFOLLOW")
    flags |= getattr(os, "O_NONBLOCK", 0)
    return flags


def _open_parent_chain(path: Path) -> tuple[list[int], list[_DirectoryBinding]]:
    try:
        anchor_fd = os.open(path.anchor, _directory_open_flags())
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_operation_error(
            exc,
            reason="sampling_plan_key_ring_path_open_failed",
        )
    descriptors = [anchor_fd]
    bindings: list[_DirectoryBinding] = []
    try:
        for component in path.parent.parts[1:]:
            parent_fd = descriptors[-1]
            child_fd = -1
            try:
                child_fd = os.open(
                    component,
                    _directory_open_flags(),
                    dir_fd=parent_fd,
                )
                descriptor_stat = os.fstat(child_fd)
                path_stat = os.stat(
                    component,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
                if child_fd >= 0:
                    os.close(child_fd)
                _raise_path_operation_error(
                    exc,
                    reason="sampling_plan_key_ring_parent_open_failed",
                )
            if not stat.S_ISDIR(descriptor_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
                os.close(child_fd)
                raise SamplingPlanKeyRingIntegrityError(
                    "sampling_plan_key_ring_parent_not_directory"
                )
            identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
            if identity != (int(path_stat.st_dev), int(path_stat.st_ino)):
                os.close(child_fd)
                raise SamplingPlanKeyRingIntegrityError(
                    "sampling_plan_key_ring_parent_binding_changed"
                )
            descriptors.append(child_fd)
            bindings.append(
                _DirectoryBinding(
                    parent_fd=parent_fd,
                    name=component,
                    child_fd=child_fd,
                    identity=identity,
                )
            )
        return descriptors, bindings
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _validate_trusted_parent(parent_fd: int, *, expected_owner_uid: int) -> None:
    try:
        parent_stat = os.fstat(parent_fd)
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_operation_error(
            exc,
            reason="sampling_plan_key_ring_parent_stat_failed",
        )
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_parent_not_directory")
    if parent_stat.st_uid != expected_owner_uid:
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_parent_owner_mismatch")
    if stat.S_IMODE(parent_stat.st_mode) & 0o022:
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_parent_writable_by_others")


def _file_open_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= _required_os_flag("O_NOFOLLOW")
    flags |= getattr(os, "O_NONBLOCK", 0)
    return flags


def _validate_file_stats(
    descriptor_stat: os.stat_result,
    path_stat: os.stat_result,
    *,
    expected_owner_uid: int,
) -> tuple[int, int, int, int, int]:
    if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_not_regular_file")
    descriptor_identity = (
        int(descriptor_stat.st_dev),
        int(descriptor_stat.st_ino),
    )
    if descriptor_identity != (int(path_stat.st_dev), int(path_stat.st_ino)):
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_file_binding_changed")
    if descriptor_stat.st_nlink != 1 or path_stat.st_nlink != 1:
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_hardlink_forbidden")
    if descriptor_stat.st_uid != expected_owner_uid or path_stat.st_uid != expected_owner_uid:
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_owner_mismatch")
    if stat.S_IMODE(descriptor_stat.st_mode) & 0o077 or stat.S_IMODE(path_stat.st_mode) & 0o077:
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_private_mode_required")
    if (
        descriptor_stat.st_size <= 0
        or descriptor_stat.st_size > MAX_SAMPLING_PLAN_KEY_RING_BYTES
        or path_stat.st_size != descriptor_stat.st_size
    ):
        raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_file_size_invalid")
    return (
        descriptor_identity[0],
        descriptor_identity[1],
        int(descriptor_stat.st_size),
        int(descriptor_stat.st_mtime_ns),
        int(descriptor_stat.st_ctime_ns),
    )


def _verify_directory_bindings(bindings: list[_DirectoryBinding]) -> None:
    for binding in bindings:
        try:
            descriptor_stat = os.fstat(binding.child_fd)
            path_stat = os.stat(
                binding.name,
                dir_fd=binding.parent_fd,
                follow_symlinks=False,
            )
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_operation_error(
                exc,
                reason="sampling_plan_key_ring_parent_binding_changed",
            )
        descriptor_identity = (
            int(descriptor_stat.st_dev),
            int(descriptor_stat.st_ino),
        )
        path_identity = (int(path_stat.st_dev), int(path_stat.st_ino))
        if (
            not stat.S_ISDIR(descriptor_stat.st_mode)
            or not stat.S_ISDIR(path_stat.st_mode)
            or descriptor_identity != binding.identity
            or path_identity != binding.identity
        ):
            raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_parent_binding_changed")


def _read_exact_file(
    parent_fd: int,
    name: str,
    *,
    expected_owner_uid: int,
    directory_bindings: list[_DirectoryBinding],
) -> bytes:
    try:
        descriptor = os.open(name, _file_open_flags(), dir_fd=parent_fd)
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_operation_error(
            exc,
            reason="sampling_plan_key_ring_file_open_failed",
        )
    try:
        try:
            before_descriptor_stat = os.fstat(descriptor)
            before_path_stat = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_operation_error(
                exc,
                reason="sampling_plan_key_ring_file_stat_failed",
            )
        expected_identity = _validate_file_stats(
            before_descriptor_stat,
            before_path_stat,
            expected_owner_uid=expected_owner_uid,
        )
        chunks: list[bytes] = []
        bytes_read = 0
        while bytes_read <= MAX_SAMPLING_PLAN_KEY_RING_BYTES:
            try:
                chunk = os.read(
                    descriptor,
                    min(
                        8192,
                        MAX_SAMPLING_PLAN_KEY_RING_BYTES + 1 - bytes_read,
                    ),
                )
            except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
                _raise_path_operation_error(
                    exc,
                    reason="sampling_plan_key_ring_file_read_failed",
                )
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
        if bytes_read > MAX_SAMPLING_PLAN_KEY_RING_BYTES:
            raise SamplingPlanKeyRingIntegrityError("sampling_plan_key_ring_file_size_invalid")
        payload = b"".join(chunks)
        try:
            after_descriptor_stat = os.fstat(descriptor)
            after_path_stat = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
            _raise_path_operation_error(
                exc,
                reason="sampling_plan_key_ring_file_binding_changed",
            )
        after_identity = _validate_file_stats(
            after_descriptor_stat,
            after_path_stat,
            expected_owner_uid=expected_owner_uid,
        )
        if after_identity != expected_identity or len(payload) != expected_identity[2]:
            raise SamplingPlanKeyRingIntegrityError(
                "sampling_plan_key_ring_file_changed_during_read"
            )
        _verify_directory_bindings(directory_bindings)
        _validate_trusted_parent(parent_fd, expected_owner_uid=expected_owner_uid)
        return payload
    finally:
        os.close(descriptor)


def load_sampling_plan_key_ring(path: Path) -> SamplingPlanKeyRing:
    """Load one private canonical key ring from an explicit absolute path.

    The final file and every parent component are opened without following
    symlinks where the platform supports ``O_NOFOLLOW``.  The immediate parent
    must be owned by the current effective user and must not be group/other
    writable.  File identity, ownership, mode, size, and modification metadata
    are checked on both sides of the bounded descriptor read.
    """

    exact_path = _exact_absolute_path(path)
    _require_secure_path_capabilities()
    try:
        expected_owner_uid = os.geteuid()
    except (OSError, NotImplementedError, TypeError, ValueError, AttributeError) as exc:
        _raise_path_operation_error(
            exc,
            reason="sampling_plan_key_ring_effective_owner_unavailable",
        )
    descriptors, bindings = _open_parent_chain(exact_path)
    try:
        parent_fd = descriptors[-1]
        _validate_trusted_parent(
            parent_fd,
            expected_owner_uid=expected_owner_uid,
        )
        payload = _read_exact_file(
            parent_fd,
            exact_path.name,
            expected_owner_uid=expected_owner_uid,
            directory_bindings=bindings,
        )
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    active_key_id, keys = _validated_ring_payload(payload)
    return SamplingPlanKeyRing(active_key_id=active_key_id, keys=keys)


__all__ = [
    "MAX_RETAINED_SAMPLING_PLAN_KEYS",
    "MAX_SAMPLING_PLAN_KEY_RING_BYTES",
    "SAMPLING_PLAN_KEY_RING_SCHEMA_VERSION",
    "SAMPLING_PLAN_KEY_RING_STATUS_SCHEMA_VERSION",
    "SamplingPlanKeyResolutionError",
    "SamplingPlanKeyRing",
    "SamplingPlanKeyRingError",
    "SamplingPlanKeyRingIntegrityError",
    "SamplingPlanKeyRingStatus",
    "SamplingPlanKeyRingValidationError",
    "load_sampling_plan_key_ring",
]
