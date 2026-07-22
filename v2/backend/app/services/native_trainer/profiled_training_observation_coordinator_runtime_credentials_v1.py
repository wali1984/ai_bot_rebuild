"""Protected runtime credentials for the profiled observation coordinator.

Four independent local HMAC roles are mandatory.  The independent witness
bundle is optional only as a *complete* bundle: public endpoint/identity/key
pin plus protected bearer token and raw Ed25519 public key.  Secret material is
accepted only from the exact systemd credential mount for the fixed user unit;
environment variables and repository secret files are never secret sources.
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
SYSTEMD_UNIT_NAME: Final = (
    "ai-bot-v2-profiled-training-observation-coordinator.service"
)

STATE_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_state_hmac_key"
MANIFEST_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_manifest_hmac_key"
HEAD_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_head_hmac_key"
EPOCH_HMAC_SYSTEMD_CREDENTIAL: Final = "profiled_observation_epoch_hmac_key"
WITNESS_BEARER_SYSTEMD_CREDENTIAL: Final = "profiled_observation_witness_bearer_token"
WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL: Final = (
    "profiled_observation_witness_ed25519_public_key"
)

WITNESS_BASE_URL_ENV: Final = "PROFILED_OBSERVATION_WITNESS_BASE_URL"
WITNESS_ID_ENV: Final = "PROFILED_OBSERVATION_WITNESS_ID"
WITNESS_PUBLIC_KEY_SHA256_ENV: Final = (
    "PROFILED_OBSERVATION_WITNESS_PUBLIC_KEY_SHA256"
)
WITNESS_TIMEOUT_SECONDS_ENV: Final = (
    "PROFILED_OBSERVATION_WITNESS_TIMEOUT_SECONDS"
)

MIN_HMAC_KEY_BYTES: Final = 32
ED25519_PUBLIC_KEY_BYTES: Final = 32
MAX_SYSTEMD_CREDENTIAL_BYTES: Final = 4096
MIN_WITNESS_TIMEOUT_SECONDS: Final = 0.1
MAX_WITNESS_TIMEOUT_SECONDS: Final = 60.0

_CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_BEARER_TOKEN_RE = re.compile(r"^[\x21-\x7e]{16,4096}$", re.ASCII)
_DIRECTORY_MODE = stat.S_IRUSR | stat.S_IXUSR
_FILE_MODE = stat.S_IRUSR
_LOCAL_CREDENTIAL_NAMES: Final = (
    STATE_HMAC_SYSTEMD_CREDENTIAL,
    MANIFEST_HMAC_SYSTEMD_CREDENTIAL,
    HEAD_HMAC_SYSTEMD_CREDENTIAL,
    EPOCH_HMAC_SYSTEMD_CREDENTIAL,
)
_WITNESS_CREDENTIAL_NAMES: Final = (
    WITNESS_BEARER_SYSTEMD_CREDENTIAL,
    WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
)
_WITNESS_PUBLIC_ENV_NAMES: Final = (
    WITNESS_BASE_URL_ENV,
    WITNESS_ID_ENV,
    WITNESS_PUBLIC_KEY_SHA256_ENV,
    WITNESS_TIMEOUT_SECONDS_ENV,
)


class ProfiledObservationCoordinatorCredentialError(RuntimeError):
    """Stable fail-closed credential error that never includes secret data."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ProfiledObservationCoordinatorLocalRoleCredentialsV1:
    state_hmac_key: bytes = field(repr=False)
    manifest_hmac_key: bytes = field(repr=False)
    head_hmac_key: bytes = field(repr=False)
    epoch_hmac_key: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProfiledObservationCoordinatorExternalWitnessCredentialsV1:
    base_url: str
    witness_id: str
    expected_public_key_sha256: str
    timeout_seconds: float
    bearer_token: str = field(repr=False)
    public_key_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProfiledObservationCoordinatorRuntimeCredentialsV1:
    local_roles: ProfiledObservationCoordinatorLocalRoleCredentialsV1 = field(
        repr=False
    )
    external_witness: (
        ProfiledObservationCoordinatorExternalWitnessCredentialsV1 | None
    ) = field(default=None, repr=False)


def _fail(reason: str) -> NoReturn:
    raise ProfiledObservationCoordinatorCredentialError(reason) from None


def _expected_credentials_directory() -> Path:
    return Path("/run/user") / str(os.geteuid()) / "credentials" / SYSTEMD_UNIT_NAME


def _open_credentials_directory(directory: Path) -> int:
    if not directory.is_absolute() or directory.anchor != os.sep or ".." in directory.parts:
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
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
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    if metadata.st_uid != os.geteuid():
        os.close(descriptor)
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_OWNER_INVALID")
    if stat.S_IMODE(metadata.st_mode) != _DIRECTORY_MODE:
        os.close(descriptor)
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID")
    if metadata.st_nlink != 2:
        os.close(descriptor)
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_LINK_COUNT_INVALID")
    return descriptor


def _credential_exists(directory_descriptor: int, name: str) -> bool:
    if _CREDENTIAL_NAME_RE.fullmatch(name) is None:
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_NAME_INVALID")
    try:
        os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError:
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_UNAVAILABLE_{name}")
    return True


def _read_credential_bytes(directory_descriptor: int, name: str) -> bytes:
    if _CREDENTIAL_NAME_RE.fullmatch(name) is None:
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_NAME_INVALID")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError:
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_UNAVAILABLE_{name}")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_NOT_REGULAR_{name}")
        if metadata.st_uid != os.geteuid():
            _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_OWNER_INVALID_{name}")
        if stat.S_IMODE(metadata.st_mode) != _FILE_MODE:
            _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_PERMISSIONS_INVALID_{name}")
        if metadata.st_nlink != 1:
            _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_LINK_COUNT_INVALID_{name}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SYSTEMD_CREDENTIAL_BYTES + 1)
    except OSError:
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_UNREADABLE_{name}")
    finally:
        os.close(descriptor)
    if not raw:
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_EMPTY_{name}")
    if len(raw) > MAX_SYSTEMD_CREDENTIAL_BYTES:
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_TOO_LARGE_{name}")
    return raw


def _read_single_line_credential(directory_descriptor: int, name: str) -> str:
    raw = _read_credential_bytes(directory_descriptor, name)
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_NOT_UTF8_{name}")
    value = value.removesuffix("\n").removesuffix("\r")
    if not value or value != value.strip() or any(char in value for char in "\r\n\x00"):
        _fail(f"PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE_{name}")
    return value


def _read_hmac_key(directory_descriptor: int, name: str) -> bytes:
    value = _read_single_line_credential(directory_descriptor, name).encode(
        "utf-8", errors="strict"
    )
    if len(value) < MIN_HMAC_KEY_BYTES:
        _fail(f"PROFILED_COORDINATOR_HMAC_KEY_INVALID_{name}")
    return value


def _witness_public_configuration(
    values: Mapping[str, str],
    *,
    secret_presence: tuple[bool, bool],
) -> tuple[str, str, str, float] | None:
    public_presence = tuple(bool(values.get(name, "")) for name in _WITNESS_PUBLIC_ENV_NAMES)
    any_bundle_value = any(public_presence) or any(secret_presence)
    if not any_bundle_value:
        return None
    if not all(public_presence) or not all(secret_presence):
        _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_BUNDLE_INCOMPLETE")
    base_url = values[WITNESS_BASE_URL_ENV]
    witness_id = values[WITNESS_ID_ENV]
    public_key_sha256 = values[WITNESS_PUBLIC_KEY_SHA256_ENV]
    timeout_text = values[WITNESS_TIMEOUT_SECONDS_ENV]
    if base_url != base_url.strip() or not base_url:
        _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_BASE_URL_INVALID")
    if _IDENTIFIER_RE.fullmatch(witness_id) is None:
        _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_ID_INVALID")
    if _SHA256_RE.fullmatch(public_key_sha256) is None:
        _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_PUBLIC_KEY_SHA256_INVALID")
    try:
        timeout_seconds = float(timeout_text)
    except ValueError:
        _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_TIMEOUT_INVALID")
    if not MIN_WITNESS_TIMEOUT_SECONDS <= timeout_seconds <= MAX_WITNESS_TIMEOUT_SECONDS:
        _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_TIMEOUT_INVALID")
    return base_url, witness_id, public_key_sha256, timeout_seconds


def load_profiled_observation_coordinator_runtime_credentials_v1(
    *,
    environ: Mapping[str, str] | None = None,
) -> ProfiledObservationCoordinatorRuntimeCredentialsV1:
    """Load mandatory local roles and an optional all-or-nothing witness."""

    values = os.environ if environ is None else environ
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    if not directory_text:
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    directory = Path(directory_text)
    if directory != _expected_credentials_directory():
        _fail("PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID")
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
            _fail("PROFILED_COORDINATOR_LOCAL_ROLE_KEY_REUSE_FORBIDDEN")
        witness_presence = tuple(
            _credential_exists(descriptor, name)
            for name in _WITNESS_CREDENTIAL_NAMES
        )
        witness_shape = _witness_public_configuration(
            values,
            secret_presence=witness_presence,
        )
        if witness_shape is None:
            witness = None
        else:
            base_url, witness_id, public_key_sha256, timeout_seconds = witness_shape
            bearer_token = _read_single_line_credential(
                descriptor, WITNESS_BEARER_SYSTEMD_CREDENTIAL
            )
            if _BEARER_TOKEN_RE.fullmatch(bearer_token) is None:
                _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_BEARER_INVALID")
            public_key_bytes = _read_credential_bytes(
                descriptor, WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL
            )
            if len(public_key_bytes) != ED25519_PUBLIC_KEY_BYTES:
                _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_PUBLIC_KEY_INVALID")
            if not hmac.compare_digest(
                hashlib.sha256(public_key_bytes).hexdigest(),
                public_key_sha256,
            ):
                _fail("PROFILED_COORDINATOR_EXTERNAL_WITNESS_PUBLIC_KEY_PIN_MISMATCH")
            witness = ProfiledObservationCoordinatorExternalWitnessCredentialsV1(
                base_url=base_url,
                witness_id=witness_id,
                expected_public_key_sha256=public_key_sha256,
                timeout_seconds=timeout_seconds,
                bearer_token=bearer_token,
                public_key_bytes=public_key_bytes,
            )
    finally:
        os.close(descriptor)
    return ProfiledObservationCoordinatorRuntimeCredentialsV1(
        local_roles=ProfiledObservationCoordinatorLocalRoleCredentialsV1(
            state_hmac_key=local_keys[0],
            manifest_hmac_key=local_keys[1],
            head_hmac_key=local_keys[2],
            epoch_hmac_key=local_keys[3],
        ),
        external_witness=witness,
    )


__all__ = [
    "EPOCH_HMAC_SYSTEMD_CREDENTIAL",
    "HEAD_HMAC_SYSTEMD_CREDENTIAL",
    "MANIFEST_HMAC_SYSTEMD_CREDENTIAL",
    "ProfiledObservationCoordinatorCredentialError",
    "ProfiledObservationCoordinatorExternalWitnessCredentialsV1",
    "ProfiledObservationCoordinatorLocalRoleCredentialsV1",
    "ProfiledObservationCoordinatorRuntimeCredentialsV1",
    "STATE_HMAC_SYSTEMD_CREDENTIAL",
    "SYSTEMD_CREDENTIALS_DIRECTORY_ENV",
    "SYSTEMD_UNIT_NAME",
    "WITNESS_BASE_URL_ENV",
    "WITNESS_BEARER_SYSTEMD_CREDENTIAL",
    "WITNESS_ID_ENV",
    "WITNESS_PUBLIC_KEY_SHA256_ENV",
    "WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL",
    "WITNESS_TIMEOUT_SECONDS_ENV",
    "load_profiled_observation_coordinator_runtime_credentials_v1",
]
