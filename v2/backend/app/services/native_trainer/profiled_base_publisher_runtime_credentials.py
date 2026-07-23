"""Protected systemd credentials for the profiled base-feature publisher.

The publisher's only exchange-authenticated operation is the signed, read-only
Binance USD-M commission-rate ``GET``.  This module binds that operation to one
exact account-specific ``READONLY`` credential reference and an independent
fingerprint HMAC key.  Secret values are accepted only from systemd's protected
credential directory; generic Binance environment variables and repository
environment files are never consulted.
"""

from __future__ import annotations

import hmac
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    MIN_CREDENTIAL_FINGERPRINT_HMAC_KEY_BYTES,
)

SYSTEMD_CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
TRADER_ID_ENV = "ALPHAFORGE_INITIAL_TRADER_ID"
CREDENTIAL_REF_ENV = "ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF"

EXPECTED_TRADER_ID = "trader-wajidali1984"
EXPECTED_CREDENTIAL_REF = "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY"
API_KEY_SYSTEMD_CREDENTIAL = f"{EXPECTED_CREDENTIAL_REF}_API_KEY"
API_SECRET_SYSTEMD_CREDENTIAL = f"{EXPECTED_CREDENTIAL_REF}_API_SECRET"
FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL = (
    "PROFILED_BASE_COMMISSION_FINGERPRINT_HMAC_SECRET"
)
MAX_SYSTEMD_CREDENTIAL_BYTES = 4096
SYSTEMD_UNIT_NAME = "ai-bot-v2-profiled-base-feature-publisher.service"

_SYSTEMD_CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SYSTEMD_CREDENTIAL_DIRECTORY_MODE = stat.S_IRUSR | stat.S_IXUSR
_SYSTEMD_CREDENTIAL_FILE_MODE = stat.S_IRUSR


class ProfiledBasePublisherCredentialError(RuntimeError):
    """Stable fail-closed credential-contract error with no secret detail."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ProtectedCommissionCredentialBinding:
    """Exact binding consumed directly by the commission capture factory."""

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    trader_id: str = EXPECTED_TRADER_ID
    credential_ref: str = EXPECTED_CREDENTIAL_REF
    api_key_name: str = API_KEY_SYSTEMD_CREDENTIAL
    api_secret_name: str = API_SECRET_SYSTEMD_CREDENTIAL
    account_specific: bool = True
    read_only_ref: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


@dataclass(frozen=True, slots=True)
class ProfiledBasePublisherRuntimeCredentials:
    """Secrets loaded from one protected credential directory."""

    commission_binding: ProtectedCommissionCredentialBinding = field(repr=False)
    fingerprint_hmac_key: bytes = field(repr=False)


def _fail(reason: str) -> NoReturn:
    raise ProfiledBasePublisherCredentialError(reason) from None


def _expected_credentials_directory() -> Path:
    """Return systemd's exact per-user credential mount for this fixed unit."""

    return Path("/run/user") / str(os.geteuid()) / "credentials" / SYSTEMD_UNIT_NAME


def _open_credentials_directory(
    directory: Path,
    *,
    allow_absent_final_directory: bool = False,
) -> int | None:
    if not directory.is_absolute() or directory.anchor != os.sep or ".." in directory.parts:
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(os.sep, flags)
        components = directory.parts[1:]
        for index, component in enumerate(components):
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.close(descriptor)
                descriptor = -1
                if allow_absent_final_directory and index == len(components) - 1:
                    return None
                raise
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    if metadata.st_uid != os.geteuid():
        os.close(descriptor)
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_OWNER_INVALID")
    if stat.S_IMODE(metadata.st_mode) != _SYSTEMD_CREDENTIAL_DIRECTORY_MODE:
        os.close(descriptor)
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID")
    if metadata.st_nlink != 2:
        os.close(descriptor)
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_LINK_COUNT_INVALID")
    return descriptor


def _read_credential(directory_descriptor: int, name: str) -> str:
    if _SYSTEMD_CREDENTIAL_NAME_RE.fullmatch(name) is None:
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_NAME_INVALID")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError:
        _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_UNAVAILABLE_{name}")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_NOT_REGULAR_{name}")
        if metadata.st_uid != os.geteuid():
            _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_OWNER_INVALID_{name}")
        if stat.S_IMODE(metadata.st_mode) != _SYSTEMD_CREDENTIAL_FILE_MODE:
            _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_PERMISSIONS_INVALID_{name}")
        if metadata.st_nlink != 1:
            _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_LINK_COUNT_INVALID_{name}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SYSTEMD_CREDENTIAL_BYTES + 1)
    except OSError:
        _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_UNREADABLE_{name}")
    finally:
        os.close(descriptor)
    if len(raw) > MAX_SYSTEMD_CREDENTIAL_BYTES:
        _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_TOO_LARGE_{name}")
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_NOT_UTF8_{name}")
    value = value.removesuffix("\n").removesuffix("\r")
    if not value or value != value.strip() or any(char in value for char in "\r\n\x00"):
        _fail(f"PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE_{name}")
    return value


def load_profiled_base_publisher_runtime_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> ProfiledBasePublisherRuntimeCredentials:
    """Load the exact publisher binding without any environment-file fallback."""

    values = os.environ if environ is None else environ
    if values.get(TRADER_ID_ENV) != EXPECTED_TRADER_ID:
        _fail("PROFILED_BASE_PUBLISHER_TRADER_ID_BINDING_INVALID")
    if values.get(CREDENTIAL_REF_ENV) != EXPECTED_CREDENTIAL_REF:
        _fail("PROFILED_BASE_PUBLISHER_CREDENTIAL_REF_BINDING_INVALID")
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    if not directory_text:
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    directory = Path(directory_text)
    if directory != _expected_credentials_directory():
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID")
    directory_descriptor = _open_credentials_directory(directory)
    if directory_descriptor is None:
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    try:
        api_key = _read_credential(directory_descriptor, API_KEY_SYSTEMD_CREDENTIAL)
        api_secret = _read_credential(directory_descriptor, API_SECRET_SYSTEMD_CREDENTIAL)
        fingerprint_hmac = _read_credential(
            directory_descriptor,
            FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL,
        )
    finally:
        os.close(directory_descriptor)

    fingerprint_hmac_key = fingerprint_hmac.encode("utf-8", errors="strict")
    if len(fingerprint_hmac_key) < MIN_CREDENTIAL_FINGERPRINT_HMAC_KEY_BYTES:
        _fail("PROFILED_BASE_PUBLISHER_COMMISSION_FINGERPRINT_HMAC_SECRET_INVALID")
    if hmac.compare_digest(fingerprint_hmac_key, api_key.encode("utf-8")):
        _fail("PROFILED_BASE_PUBLISHER_FINGERPRINT_HMAC_MUST_DIFFER_FROM_API_KEY")
    if hmac.compare_digest(fingerprint_hmac_key, api_secret.encode("utf-8")):
        _fail("PROFILED_BASE_PUBLISHER_FINGERPRINT_HMAC_MUST_DIFFER_FROM_API_SECRET")

    return ProfiledBasePublisherRuntimeCredentials(
        commission_binding=ProtectedCommissionCredentialBinding(
            api_key=api_key,
            api_secret=api_secret,
        ),
        fingerprint_hmac_key=fingerprint_hmac_key,
    )


def load_profiled_base_publisher_runtime_credentials_if_available(
    *,
    environ: Mapping[str, str] | None = None,
) -> ProfiledBasePublisherRuntimeCredentials | None:
    """Return a complete protected bundle, or ``None`` for exact total absence.

    ``ImportCredential=`` exports the fixed per-unit credential-directory path
    even when no matching credential exists, but systemd 255 does not create
    the final directory in that case.  Only that exact final-directory absence
    selects masked-cost observation mode.  An existing directory is always
    passed through the strict all-or-nothing loader, so partial, malformed, or
    permission-invalid bundles cannot silently degrade.
    """

    values = os.environ if environ is None else environ
    if values.get(TRADER_ID_ENV) != EXPECTED_TRADER_ID:
        _fail("PROFILED_BASE_PUBLISHER_TRADER_ID_BINDING_INVALID")
    if values.get(CREDENTIAL_REF_ENV) != EXPECTED_CREDENTIAL_REF:
        _fail("PROFILED_BASE_PUBLISHER_CREDENTIAL_REF_BINDING_INVALID")
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    if not directory_text:
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    directory = Path(directory_text)
    if directory != _expected_credentials_directory():
        _fail("PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID")
    directory_descriptor = _open_credentials_directory(
        directory,
        allow_absent_final_directory=True,
    )
    if directory_descriptor is None:
        return None
    os.close(directory_descriptor)
    return load_profiled_base_publisher_runtime_credentials(environ=values)


__all__ = [
    "API_KEY_SYSTEMD_CREDENTIAL",
    "API_SECRET_SYSTEMD_CREDENTIAL",
    "CREDENTIAL_REF_ENV",
    "EXPECTED_CREDENTIAL_REF",
    "EXPECTED_TRADER_ID",
    "FINGERPRINT_HMAC_SYSTEMD_CREDENTIAL",
    "MAX_SYSTEMD_CREDENTIAL_BYTES",
    "ProfiledBasePublisherCredentialError",
    "ProfiledBasePublisherRuntimeCredentials",
    "ProtectedCommissionCredentialBinding",
    "SYSTEMD_CREDENTIALS_DIRECTORY_ENV",
    "SYSTEMD_UNIT_NAME",
    "TRADER_ID_ENV",
    "load_profiled_base_publisher_runtime_credentials",
    "load_profiled_base_publisher_runtime_credentials_if_available",
]
