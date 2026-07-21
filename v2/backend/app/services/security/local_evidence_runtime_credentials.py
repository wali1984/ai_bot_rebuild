"""Protected systemd credentials for local paper-evidence HMAC domains.

Only public key identifiers are accepted through environment variables.  Key
material is read from systemd's protected ``CREDENTIALS_DIRECTORY``.  Each
retained key has its own versioned credential slot so rotation can sign with
the active key while still verifying in-flight receipts made by an old key.
"""

from __future__ import annotations

import hmac
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from v2.backend.app.services.security.local_evidence_hmac import (
    LocalEvidenceAuthenticationError,
    authentication_key_bytes,
)

SYSTEMD_CREDENTIALS_DIRECTORY_ENV = "CREDENTIALS_DIRECTORY"
MARK_ACTIVE_KEY_ID_ENV = "V2_MARK_EVIDENCE_HMAC_ACTIVE_KEY_ID"
MARK_RETAINED_KEY_IDS_ENV = "V2_MARK_EVIDENCE_HMAC_RETAINED_KEY_IDS"
PAPER_ACTIVE_KEY_ID_ENV = "V2_PAPER_AUTHORITY_HMAC_ACTIVE_KEY_ID"
PAPER_RETAINED_KEY_IDS_ENV = "V2_PAPER_AUTHORITY_HMAC_RETAINED_KEY_IDS"
MARK_CREDENTIAL_PREFIX = "v2_mark_evidence_hmac_key"
PAPER_CREDENTIAL_PREFIX = "v2_paper_authority_hmac_key"
MAX_SYSTEMD_CREDENTIAL_BYTES = 4096

_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAFE_CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,239}$")


@dataclass(frozen=True)
class RuntimeHmacKeyRing:
    """Active signer plus retained verification keys; secret-safe repr."""

    active_key_id: str
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        if _SAFE_COMPONENT_RE.fullmatch(self.active_key_id) is None:
            raise LocalEvidenceAuthenticationError(
                "RUNTIME_HMAC_ACTIVE_KEY_ID_INVALID"
            )
        copied: dict[str, bytes] = {}
        for key_id, raw_key in self.keys.items():
            if not isinstance(key_id, str) or _SAFE_COMPONENT_RE.fullmatch(key_id) is None:
                raise LocalEvidenceAuthenticationError(
                    "RUNTIME_HMAC_RETAINED_KEY_ID_INVALID"
                )
            copied[key_id] = authentication_key_bytes(raw_key)
        if self.active_key_id not in copied:
            raise LocalEvidenceAuthenticationError(
                "RUNTIME_HMAC_ACTIVE_KEY_NOT_RETAINED"
            )
        key_rows = list(copied.items())
        for index, (left_id, left_key) in enumerate(key_rows):
            for right_id, right_key in key_rows[index + 1 :]:
                if hmac.compare_digest(left_key, right_key):
                    raise LocalEvidenceAuthenticationError(
                        "RUNTIME_HMAC_KEY_MATERIAL_REUSED_ACROSS_KEY_IDS:"
                        f"{left_id}:{right_id}"
                    )
        object.__setattr__(self, "keys", MappingProxyType(copied))

    @property
    def signing_key(self) -> bytes:
        return self.keys[self.active_key_id]

    @property
    def retained_key_ids(self) -> tuple[str, ...]:
        return tuple(self.keys)

    def safe_metadata(self) -> dict[str, object]:
        return {
            "active_key_id": self.active_key_id,
            "retained_key_ids": list(self.keys),
            "retained_key_count": len(self.keys),
            "key_material_exposed": False,
            "environment_secret_fallback_allowed": False,
            "protected_systemd_credentials_required": True,
        }


def _open_credentials_directory(path: Path) -> int:
    if not path.is_absolute() or path.anchor != os.sep or ".." in path.parts:
        raise LocalEvidenceAuthenticationError(
            "SYSTEMD_CREDENTIALS_DIRECTORY_INVALID"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(os.sep, flags)
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise LocalEvidenceAuthenticationError(
            "SYSTEMD_CREDENTIALS_DIRECTORY_INVALID"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise LocalEvidenceAuthenticationError(
            "SYSTEMD_CREDENTIALS_DIRECTORY_INVALID"
        )
    return descriptor


def _credential_name(prefix: str, key_id: str) -> str:
    if _SAFE_COMPONENT_RE.fullmatch(prefix) is None or _SAFE_COMPONENT_RE.fullmatch(
        key_id
    ) is None:
        raise LocalEvidenceAuthenticationError(
            "SYSTEMD_CREDENTIAL_COMPONENT_INVALID"
        )
    name = f"{prefix}.{key_id}"
    if len(name.encode("utf-8")) > 240:
        raise LocalEvidenceAuthenticationError("SYSTEMD_CREDENTIAL_NAME_TOO_LONG")
    return name


def _read_credential(directory_descriptor: int, name: str) -> bytes:
    if _SAFE_CREDENTIAL_NAME_RE.fullmatch(name) is None:
        raise LocalEvidenceAuthenticationError("SYSTEMD_CREDENTIAL_NAME_INVALID")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise LocalEvidenceAuthenticationError(
            f"SYSTEMD_CREDENTIAL_UNAVAILABLE_{name.upper()}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise LocalEvidenceAuthenticationError(
                f"SYSTEMD_CREDENTIAL_NOT_REGULAR_{name.upper()}"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_SYSTEMD_CREDENTIAL_BYTES + 1)
    except OSError as exc:
        raise LocalEvidenceAuthenticationError(
            f"SYSTEMD_CREDENTIAL_UNREADABLE_{name.upper()}"
        ) from exc
    finally:
        os.close(descriptor)
    if len(raw) > MAX_SYSTEMD_CREDENTIAL_BYTES:
        raise LocalEvidenceAuthenticationError(
            f"SYSTEMD_CREDENTIAL_TOO_LARGE_{name.upper()}"
        )
    # systemd-creds examples often store a final newline.  Remove exactly one
    # line ending, but reject multi-line/NUL material rather than normalizing it.
    raw = raw.removesuffix(b"\n").removesuffix(b"\r")
    if not raw or b"\x00" in raw or b"\n" in raw or b"\r" in raw:
        raise LocalEvidenceAuthenticationError(
            f"SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE_{name.upper()}"
        )
    return authentication_key_bytes(raw)


def _key_ids(
    values: Mapping[str, str],
    *,
    active_key_id_env: str,
    retained_key_ids_env: str,
) -> tuple[str, tuple[str, ...]]:
    active = values.get(active_key_id_env, "")
    if _SAFE_COMPONENT_RE.fullmatch(active) is None:
        raise LocalEvidenceAuthenticationError("RUNTIME_HMAC_ACTIVE_KEY_ID_INVALID")
    retained_text = values.get(retained_key_ids_env, "")
    retained = tuple(
        item.strip() for item in retained_text.split(",") if item.strip()
    ) or (active,)
    if active not in retained or len(set(retained)) != len(retained):
        raise LocalEvidenceAuthenticationError(
            "RUNTIME_HMAC_RETAINED_KEY_IDS_INVALID"
        )
    if any(_SAFE_COMPONENT_RE.fullmatch(item) is None for item in retained):
        raise LocalEvidenceAuthenticationError(
            "RUNTIME_HMAC_RETAINED_KEY_ID_INVALID"
        )
    return active, retained


def _load_keyring(
    *,
    environ: Mapping[str, str] | None,
    active_key_id_env: str,
    retained_key_ids_env: str,
    credential_prefix: str,
) -> RuntimeHmacKeyRing:
    values = os.environ if environ is None else environ
    directory_text = values.get(SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    active, retained = _key_ids(
        values,
        active_key_id_env=active_key_id_env,
        retained_key_ids_env=retained_key_ids_env,
    )
    descriptor = _open_credentials_directory(Path(directory_text))
    try:
        keys = {
            key_id: _read_credential(
                descriptor,
                _credential_name(credential_prefix, key_id),
            )
            for key_id in retained
        }
    finally:
        os.close(descriptor)
    return RuntimeHmacKeyRing(active_key_id=active, keys=keys)


def load_mark_keyring_from_systemd_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeHmacKeyRing:
    return _load_keyring(
        environ=environ,
        active_key_id_env=MARK_ACTIVE_KEY_ID_ENV,
        retained_key_ids_env=MARK_RETAINED_KEY_IDS_ENV,
        credential_prefix=MARK_CREDENTIAL_PREFIX,
    )


def load_paper_authority_keyring_from_systemd_credentials(
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeHmacKeyRing:
    return _load_keyring(
        environ=environ,
        active_key_id_env=PAPER_ACTIVE_KEY_ID_ENV,
        retained_key_ids_env=PAPER_RETAINED_KEY_IDS_ENV,
        credential_prefix=PAPER_CREDENTIAL_PREFIX,
    )


def require_disjoint_authentication_keys(
    keyrings: Sequence[RuntimeHmacKeyRing],
    *,
    forbidden_keys: Sequence[bytes | bytearray] = (),
) -> None:
    """Reject reuse across mark, paper-authority, bracket, or other domains."""

    labelled: list[tuple[str, bytes]] = []
    for ring_index, ring in enumerate(keyrings):
        if not isinstance(ring, RuntimeHmacKeyRing):
            raise LocalEvidenceAuthenticationError("RUNTIME_HMAC_KEYRING_INVALID")
        labelled.extend(
            (f"ring-{ring_index}:{key_id}", key)
            for key_id, key in ring.keys.items()
        )
    labelled.extend(
        (f"forbidden-{index}", authentication_key_bytes(value))
        for index, value in enumerate(forbidden_keys)
    )
    for index, (left_id, left_key) in enumerate(labelled):
        for right_id, right_key in labelled[index + 1 :]:
            if hmac.compare_digest(left_key, right_key):
                raise LocalEvidenceAuthenticationError(
                    "EVIDENCE_AUTHENTICATION_KEY_REUSED_ACROSS_TRUST_DOMAINS:"
                    f"{left_id}:{right_id}"
                )


__all__ = [
    "MARK_ACTIVE_KEY_ID_ENV",
    "MARK_CREDENTIAL_PREFIX",
    "MARK_RETAINED_KEY_IDS_ENV",
    "PAPER_ACTIVE_KEY_ID_ENV",
    "PAPER_CREDENTIAL_PREFIX",
    "PAPER_RETAINED_KEY_IDS_ENV",
    "RuntimeHmacKeyRing",
    "load_mark_keyring_from_systemd_credentials",
    "load_paper_authority_keyring_from_systemd_credentials",
    "require_disjoint_authentication_keys",
]
