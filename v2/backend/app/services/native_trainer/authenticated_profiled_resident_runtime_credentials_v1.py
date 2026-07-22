"""Least-privilege credentials for the authenticated profiled resident.

The trainer receives four local HMAC verification roles and, optionally, one
raw Ed25519 *public* key pinned by public witness identity settings.  It never
loads witness bearer tokens, endpoint credentials, signing keys, exchange
keys, wallet material, or data-provider secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, NoReturn

SYSTEMD_CREDENTIALS_DIRECTORY_ENV: Final = "CREDENTIALS_DIRECTORY"
SYSTEMD_UNIT_NAME: Final = "ai-bot-v2-native-cuda-trainer-persistent.service"

STATE_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_state_hmac_key"
MANIFEST_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_manifest_hmac_key"
HEAD_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_head_hmac_key"
EPOCH_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_epoch_hmac_key"
WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL: Final = (
    "profiled_observation_witness_ed25519_public_key"
)

WITNESS_ID_ENV: Final = "PROFILED_OBSERVATION_WITNESS_ID"
WITNESS_PUBLIC_KEY_SHA256_ENV: Final = (
    "PROFILED_OBSERVATION_WITNESS_PUBLIC_KEY_SHA256"
)

MIN_HMAC_KEY_BYTES: Final = 32
ED25519_PUBLIC_KEY_BYTES: Final = 32
MAX_SYSTEMD_CREDENTIAL_BYTES: Final = 4096

_DIRECTORY_MODE: Final = stat.S_IRUSR | stat.S_IXUSR
_FILE_MODE: Final = stat.S_IRUSR
_CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LOCAL_CREDENTIAL_NAMES: Final = (
    STATE_HMAC_SYSTEMD_CREDENTIAL,
    MANIFEST_HMAC_SYSTEMD_CREDENTIAL,
    HEAD_HMAC_SYSTEMD_CREDENTIAL,
    EPOCH_HMAC_SYSTEMD_CREDENTIAL,
)


class AuthenticatedProfiledResidentCredentialV1Error(RuntimeError):
    """Stable fail-closed credential error that never embeds secret data."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledResidentLocalRoleCredentialsV1:
    state_hmac_key: bytes = field(repr=False)
    manifest_hmac_key: bytes = field(repr=False)
    head_hmac_key: bytes = field(repr=False)
    epoch_hmac_key: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledResidentWitnessVerifierCredentialsV1:
    witness_id: str
    expected_public_key_sha256: str
    public_key_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledResidentRuntimeCredentialsV1:
    local_roles: AuthenticatedProfiledResidentLocalRoleCredentialsV1 = field(
        repr=False
    )
    witness_verifier: (
        AuthenticatedProfiledResidentWitnessVerifierCredentialsV1 | None
    ) = field(default=None, repr=False)


def _fail(reason: str) -> NoReturn:
    raise AuthenticatedProfiledResidentCredentialV1Error(reason) from None


def _expected_credentials_directory() -> Path:
    return Path("/run/user") / str(os.geteuid()) / "credentials" / SYSTEMD_UNIT_NAME


def _file_signature(
    observed: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_uid,
        observed.st_nlink,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _open_credentials_directory(directory: Path) -> int:
    if not directory.is_absolute() or directory.anchor != os.sep or ".." in directory.parts:
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(os.sep, flags)
        for component in directory.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    if metadata.st_uid != os.geteuid():
        os.close(descriptor)
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_OWNER_INVALID")
    if stat.S_IMODE(metadata.st_mode) != _DIRECTORY_MODE:
        os.close(descriptor)
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID")
    if metadata.st_nlink != 2:
        os.close(descriptor)
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_LINK_COUNT_INVALID")
    return descriptor


def _credential_exists(directory_descriptor: int, name: str) -> bool:
    if _CREDENTIAL_NAME_RE.fullmatch(name) is None:
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_NAME_INVALID")
    try:
        os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        _fail(f"PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_UNAVAILABLE_{name}")
    return True


def _read_credential_bytes(directory_descriptor: int, name: str) -> bytes:
    if _CREDENTIAL_NAME_RE.fullmatch(name) is None:
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_NAME_INVALID")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != _FILE_MODE
            or not 0 < before.st_size <= MAX_SYSTEMD_CREDENTIAL_BYTES
        ):
            _fail(f"PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_FILE_INVALID_{name}")
        chunks: list[bytes] = []
        observed_bytes = 0
        while True:
            chunk = os.read(
                descriptor,
                min(4096, MAX_SYSTEMD_CREDENTIAL_BYTES + 1 - observed_bytes),
            )
            if not chunk:
                break
            chunks.append(chunk)
            observed_bytes += len(chunk)
            if observed_bytes > MAX_SYSTEMD_CREDENTIAL_BYTES:
                _fail(f"PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_TOO_LARGE_{name}")
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            _file_signature(before) != _file_signature(after)
            or _file_signature(before) != _file_signature(path_stat)
            or len(raw) != after.st_size
        ):
            _fail(f"PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_CHANGED_{name}")
        return raw
    except AuthenticatedProfiledResidentCredentialV1Error:
        raise
    except OSError:
        _fail(f"PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_UNAVAILABLE_{name}")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_hmac_key(directory_descriptor: int, name: str) -> bytes:
    raw = _read_credential_bytes(directory_descriptor, name)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(f"PROFILED_RESIDENT_HMAC_KEY_INVALID_{name}")
    text = text.removesuffix("\n").removesuffix("\r")
    if (
        not text
        or text != text.strip()
        or any(character in text for character in "\r\n\x00")
    ):
        _fail(f"PROFILED_RESIDENT_HMAC_KEY_INVALID_{name}")
    value = text.encode("utf-8", errors="strict")
    if len(value) < MIN_HMAC_KEY_BYTES:
        _fail(f"PROFILED_RESIDENT_HMAC_KEY_INVALID_{name}")
    return value


def load_authenticated_profiled_resident_runtime_credentials_v1(
    *,
    environ: Mapping[str, str] | None = None,
) -> AuthenticatedProfiledResidentRuntimeCredentialsV1:
    """Load exact local roles and an optional all-or-nothing verifier key."""

    values = os.environ if environ is None else environ
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    if type(directory_text) is not str or not directory_text:
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    directory = Path(directory_text)
    if directory != _expected_credentials_directory():
        _fail("PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID")
    descriptor = _open_credentials_directory(directory)
    try:
        local_keys = tuple(
            _read_hmac_key(descriptor, name) for name in _LOCAL_CREDENTIAL_NAMES
        )
        if any(
            hmac.compare_digest(left, right)
            for index, left in enumerate(local_keys)
            for right in local_keys[index + 1 :]
        ):
            _fail("PROFILED_RESIDENT_LOCAL_ROLE_KEY_REUSE_FORBIDDEN")

        witness_id = values.get(WITNESS_ID_ENV, "")
        public_key_sha256 = values.get(WITNESS_PUBLIC_KEY_SHA256_ENV, "")
        if type(witness_id) is not str or type(public_key_sha256) is not str:
            _fail("PROFILED_RESIDENT_WITNESS_CONFIGURATION_INVALID")
        key_present = _credential_exists(
            descriptor,
            WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
        )
        presence = (bool(witness_id), bool(public_key_sha256), key_present)
        if any(presence) and not all(presence):
            _fail("PROFILED_RESIDENT_WITNESS_VERIFIER_BUNDLE_INCOMPLETE")

        verifier: AuthenticatedProfiledResidentWitnessVerifierCredentialsV1 | None = None
        if all(presence):
            if _IDENTIFIER_RE.fullmatch(witness_id) is None:
                _fail("PROFILED_RESIDENT_WITNESS_ID_INVALID")
            if _SHA256_RE.fullmatch(public_key_sha256) is None:
                _fail("PROFILED_RESIDENT_WITNESS_PUBLIC_KEY_SHA256_INVALID")
            public_key = _read_credential_bytes(
                descriptor,
                WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
            )
            if len(public_key) != ED25519_PUBLIC_KEY_BYTES:
                _fail("PROFILED_RESIDENT_WITNESS_PUBLIC_KEY_INVALID")
            observed_sha256 = hashlib.sha256(public_key).hexdigest()
            if not hmac.compare_digest(observed_sha256, public_key_sha256):
                _fail("PROFILED_RESIDENT_WITNESS_PUBLIC_KEY_PIN_MISMATCH")
            verifier = AuthenticatedProfiledResidentWitnessVerifierCredentialsV1(
                witness_id=witness_id,
                expected_public_key_sha256=public_key_sha256,
                public_key_bytes=public_key,
            )
        return AuthenticatedProfiledResidentRuntimeCredentialsV1(
            local_roles=AuthenticatedProfiledResidentLocalRoleCredentialsV1(
                state_hmac_key=local_keys[0],
                manifest_hmac_key=local_keys[1],
                head_hmac_key=local_keys[2],
                epoch_hmac_key=local_keys[3],
            ),
            witness_verifier=verifier,
        )
    finally:
        os.close(descriptor)


__all__ = (
    "EPOCH_HMAC_SYSTEMD_CREDENTIAL",
    "HEAD_HMAC_SYSTEMD_CREDENTIAL",
    "MANIFEST_HMAC_SYSTEMD_CREDENTIAL",
    "STATE_HMAC_SYSTEMD_CREDENTIAL",
    "SYSTEMD_CREDENTIALS_DIRECTORY_ENV",
    "SYSTEMD_UNIT_NAME",
    "WITNESS_ID_ENV",
    "WITNESS_PUBLIC_KEY_SHA256_ENV",
    "WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL",
    "AuthenticatedProfiledResidentCredentialV1Error",
    "AuthenticatedProfiledResidentLocalRoleCredentialsV1",
    "AuthenticatedProfiledResidentRuntimeCredentialsV1",
    "AuthenticatedProfiledResidentWitnessVerifierCredentialsV1",
    "load_authenticated_profiled_resident_runtime_credentials_v1",
)
