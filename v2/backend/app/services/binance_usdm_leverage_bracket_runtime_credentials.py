"""Protected runtime credentials for Binance USD-M bracket evidence.

The producer needs an account-scoped Binance key pair plus an independent
evidence-authentication key.  The paper consumer needs only that independent
HMAC key and the same public binding.  Both paths use systemd's credential
directory exclusively; secret values are never accepted from environment
variables by this module.
"""

from __future__ import annotations

import hmac
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    EvidenceSecurityContext,
    LeverageBracketEvidenceError,
    build_evidence_security_context,
)

if TYPE_CHECKING:
    from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter

SYSTEMD_CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
TRADER_ID_ENV = "ALPHAFORGE_INITIAL_TRADER_ID"
CREDENTIAL_REF_ENV = "ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF"
BASE_URL_ENV = "BINANCE_USDM_REST_BASE_URL"
EVIDENCE_AUTH_KEY_ID_ENV = "BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID"
EVIDENCE_HMAC_SYSTEMD_CREDENTIAL = "binance_bracket_evidence_hmac_key"
MAX_SYSTEMD_CREDENTIAL_BYTES = 4096

_SYSTEMD_CREDENTIAL_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def binding_credential_name(*, trader_id: str, credential_ref: str, suffix: str) -> str:
    """Bind a systemd credential slot to one exact public account identity."""

    for field_name, value in (
        ("TRADER_ID", trader_id),
        ("CREDENTIAL_REF", credential_ref),
        ("CREDENTIAL_SUFFIX", suffix),
    ):
        if not isinstance(value, str) or not _SYSTEMD_CREDENTIAL_COMPONENT_RE.fullmatch(value):
            raise LeverageBracketEvidenceError(f"{field_name}_UNSAFE_FOR_SYSTEMD_CREDENTIAL")
    name = f"{trader_id}--{credential_ref}--{suffix}"
    if len(name.encode("utf-8")) > 240:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIAL_NAME_TOO_LONG")
    return name


def _open_systemd_credentials_directory(directory: Path) -> int:
    if not directory.is_absolute() or directory.anchor != os.sep or ".." in directory.parts:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
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
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    return descriptor


def _read_systemd_credential(directory_descriptor: int, name: str) -> str:
    """Read one bounded regular-file credential without exposing its value."""

    if not _SYSTEMD_CREDENTIAL_COMPONENT_RE.fullmatch(name):
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIAL_NAME_UNSAFE")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise LeverageBracketEvidenceError(
            f"SYSTEMD_CREDENTIAL_UNAVAILABLE_{name.upper()}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_NOT_REGULAR_{name.upper()}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SYSTEMD_CREDENTIAL_BYTES + 1)
    except OSError as exc:
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_UNREADABLE_{name.upper()}") from exc
    finally:
        os.close(descriptor)
    if len(raw) > MAX_SYSTEMD_CREDENTIAL_BYTES:
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_TOO_LARGE_{name.upper()}")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_NOT_UTF8_{name.upper()}") from exc
    value = value.removesuffix("\n").removesuffix("\r")
    if not value or value != value.strip() or any(char in value for char in "\r\n\x00"):
        raise LeverageBracketEvidenceError(f"SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE_{name.upper()}")
    return value


def read_protected_systemd_credential(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Read one named systemd credential through the hardened bounded reader.

    The credential name cannot contain a path separator, the credentials
    directory must be an absolute non-symlink directory, and the leaf must be
    a bounded regular file.  This intentionally has no environment-value or
    ordinary-file fallback.
    """

    values = os.environ if environ is None else environ
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    if not directory_text:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    directory_descriptor = _open_systemd_credentials_directory(Path(directory_text))
    try:
        return _read_systemd_credential(directory_descriptor, name)
    finally:
        os.close(directory_descriptor)


def _runtime_values(
    environ: Mapping[str, str] | None,
) -> tuple[Path, str, str, str, str]:
    values = os.environ if environ is None else environ
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    if not directory_text:
        raise LeverageBracketEvidenceError("SYSTEMD_CREDENTIALS_DIRECTORY_INVALID")
    return (
        Path(directory_text),
        values.get(TRADER_ID_ENV, ""),
        values.get(CREDENTIAL_REF_ENV, ""),
        values.get(BASE_URL_ENV, ""),
        values.get(EVIDENCE_AUTH_KEY_ID_ENV, ""),
    )


def _context_from_hmac(
    *,
    trader_id: str,
    credential_ref: str,
    base_url: str,
    auth_key_id: str,
    evidence_hmac_key: str,
) -> EvidenceSecurityContext:
    return build_evidence_security_context(
        trader_id=trader_id,
        credential_ref=credential_ref,
        base_url=base_url,
        credential_account_specific=True,
        hmac_key=evidence_hmac_key,
        auth_key_id=auth_key_id,
    )


def consumer_security_context_from_systemd_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> EvidenceSecurityContext:
    """Build the paper verifier context without reading exchange credentials."""

    directory, trader_id, credential_ref, base_url, auth_key_id = _runtime_values(environ)
    directory_descriptor = _open_systemd_credentials_directory(directory)
    try:
        evidence_hmac_key = _read_systemd_credential(
            directory_descriptor,
            EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        )
    finally:
        os.close(directory_descriptor)
    return _context_from_hmac(
        trader_id=trader_id,
        credential_ref=credential_ref,
        base_url=base_url,
        auth_key_id=auth_key_id,
        evidence_hmac_key=evidence_hmac_key,
    )


def adapter_and_security_context_from_systemd_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[BinanceUSDMAdapter, EvidenceSecurityContext]:
    """Build the producer adapter and context from one protected directory."""

    from v2.backend.app.services.execution.binance_usdm_adapter import (  # noqa: PLC0415
        BinanceUSDMAdapter,
    )

    directory, trader_id, credential_ref, base_url, auth_key_id = _runtime_values(environ)
    api_key_name = binding_credential_name(
        trader_id=trader_id,
        credential_ref=credential_ref,
        suffix="api_key",
    )
    api_secret_name = binding_credential_name(
        trader_id=trader_id,
        credential_ref=credential_ref,
        suffix="api_secret",
    )
    directory_descriptor = _open_systemd_credentials_directory(directory)
    try:
        api_key = _read_systemd_credential(directory_descriptor, api_key_name)
        api_secret = _read_systemd_credential(directory_descriptor, api_secret_name)
        evidence_hmac_key = _read_systemd_credential(
            directory_descriptor,
            EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        )
    finally:
        os.close(directory_descriptor)
    evidence_hmac_key_bytes = evidence_hmac_key.encode("utf-8")
    if hmac.compare_digest(evidence_hmac_key_bytes, api_key.encode("utf-8")):
        raise LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_API_KEY")
    if hmac.compare_digest(evidence_hmac_key_bytes, api_secret.encode("utf-8")):
        raise LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_SECRET")
    context = _context_from_hmac(
        trader_id=trader_id,
        credential_ref=credential_ref,
        base_url=base_url,
        auth_key_id=auth_key_id,
        evidence_hmac_key=evidence_hmac_key,
    )
    return (
        BinanceUSDMAdapter(
            api_key=api_key,
            api_secret=api_secret,
            base_url=context.base_url_origin,
        ),
        context,
    )


__all__ = [
    "BASE_URL_ENV",
    "CREDENTIAL_REF_ENV",
    "EVIDENCE_AUTH_KEY_ID_ENV",
    "EVIDENCE_HMAC_SYSTEMD_CREDENTIAL",
    "MAX_SYSTEMD_CREDENTIAL_BYTES",
    "SYSTEMD_CREDENTIALS_DIRECTORY_ENV",
    "TRADER_ID_ENV",
    "adapter_and_security_context_from_systemd_credentials",
    "binding_credential_name",
    "consumer_security_context_from_systemd_credentials",
    "read_protected_systemd_credential",
]
