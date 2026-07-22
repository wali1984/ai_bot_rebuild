from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_profiled_resident_runtime_credentials_v1 as credentials,
)

_ROLE_VALUES = {
    credentials.STATE_HMAC_SYSTEMD_CREDENTIAL: "state-resident-role-key-material-0000000001",
    credentials.MANIFEST_HMAC_SYSTEMD_CREDENTIAL: (
        "manifest-resident-role-key-material-00000002"
    ),
    credentials.HEAD_HMAC_SYSTEMD_CREDENTIAL: (
        "head-resident-role-key-material-00000000003"
    ),
    credentials.EPOCH_HMAC_SYSTEMD_CREDENTIAL: (
        "epoch-resident-role-key-material-0000000004"
    ),
}
_PUBLIC_KEY = bytes(range(32))
_AMBIENT_SECRET_VALUES = (
    "ambient-exchange-secret-must-not-be-read",
    "ambient-moralis-secret-must-not-be-read",
    "ambient-coinapi-secret-must-not-be-read",
)
_OBSOLETE_BEARER_CREDENTIAL_NAMES = (
    "profiled_observation_witness_bearer_token",
    "profiled_observation_completion_authorization_bearer_token",
)
_PRODUCTION_EXPECTED_DIRECTORY = credentials._expected_credentials_directory  # noqa: SLF001


def _write_bytes(directory: Path, name: str, value: bytes) -> None:
    original_mode = stat.S_IMODE(directory.stat().st_mode)
    directory.chmod(0o700)
    try:
        path = directory / name
        if path.exists() and not path.is_symlink():
            path.chmod(0o600)
        path.write_bytes(value)
        path.chmod(0o400)
    finally:
        directory.chmod(original_mode)


def _write_text(directory: Path, name: str, value: str) -> None:
    _write_bytes(directory, name, f"{value}\n".encode())


def _write_local_roles(directory: Path) -> None:
    for name, value in _ROLE_VALUES.items():
        _write_text(directory, name, value)
    directory.chmod(0o500)


def _write_witness_public_key(directory: Path, value: bytes = _PUBLIC_KEY) -> None:
    _write_bytes(
        directory,
        credentials.WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
        value,
    )
    directory.chmod(0o500)


def _environment(directory: Path, **overrides: str) -> dict[str, str]:
    return {
        credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(directory),
        "BINANCE_API_SECRET": _AMBIENT_SECRET_VALUES[0],
        "MORALIS_API_KEY": _AMBIENT_SECRET_VALUES[1],
        "COINAPI_API_KEY": _AMBIENT_SECRET_VALUES[2],
        **overrides,
    }


def _witness_environment(directory: Path, **overrides: str) -> dict[str, str]:
    return _environment(
        directory,
        **{
            credentials.WITNESS_ID_ENV: "independent-witness-v1",
            credentials.WITNESS_PUBLIC_KEY_SHA256_ENV: hashlib.sha256(
                _PUBLIC_KEY
            ).hexdigest(),
            **overrides,
        },
    )


def _assert_safe_failure(
    caught: pytest.ExceptionInfo[BaseException],
    *,
    reason: str,
) -> None:
    rendered = str(caught.value) + repr(caught.value)
    assert caught.value.reason == reason
    assert rendered.startswith(reason)
    assert all(value not in rendered for value in _ROLE_VALUES.values())
    assert all(value not in rendered for value in _AMBIENT_SECRET_VALUES)
    assert repr(_PUBLIC_KEY) not in rendered


@pytest.fixture(autouse=True)
def _bind_test_directory_and_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(credentials, "_expected_credentials_directory", lambda: tmp_path)
    yield
    if not tmp_path.exists():
        return
    for current, directories, filenames in os.walk(tmp_path, topdown=True):
        current_path = Path(current)
        if not current_path.is_symlink():
            current_path.chmod(0o700)
        for name in directories + filenames:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o600 if path.is_file() else 0o700)


def test_production_directory_is_bound_to_exact_trainer_unit() -> None:
    assert credentials.SYSTEMD_UNIT_NAME == (
        "ai-bot-v2-native-cuda-trainer-persistent.service"
    )
    assert _PRODUCTION_EXPECTED_DIRECTORY() == Path(
        f"/run/user/{os.geteuid()}/credentials/"
        "ai-bot-v2-native-cuda-trainer-persistent.service"
    )


def test_arbitrary_directory_binding_fails_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_local_roles(tmp_path)
    monkeypatch.setattr(
        credentials,
        "_expected_credentials_directory",
        lambda: tmp_path.parent / "other.service",
    )
    opened = False

    def forbidden_open(_path: Path) -> int:
        nonlocal opened
        opened = True
        raise AssertionError("binding mismatch must precede credential reads")

    monkeypatch.setattr(credentials, "_open_credentials_directory", forbidden_open)
    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
    assert opened is False
    _assert_safe_failure(
        caught,
        reason="PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID",
    )


def test_local_roles_load_without_verifier_and_hide_all_secret_values(
    tmp_path: Path,
) -> None:
    _write_local_roles(tmp_path)

    loaded = credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
        environ=_environment(tmp_path)
    )

    assert loaded.witness_verifier is None
    assert loaded.local_roles.state_hmac_key == _ROLE_VALUES[
        credentials.STATE_HMAC_SYSTEMD_CREDENTIAL
    ].encode()
    rendered = repr(loaded) + repr(loaded.local_roles)
    assert all(value not in rendered for value in _ROLE_VALUES.values())
    assert all(value not in rendered for value in _AMBIENT_SECRET_VALUES)


def test_complete_verifier_bundle_is_pinned_and_hidden(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_witness_public_key(tmp_path)

    loaded = credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
        environ=_witness_environment(tmp_path)
    )

    verifier = loaded.witness_verifier
    assert verifier is not None
    assert verifier.witness_id == "independent-witness-v1"
    assert verifier.expected_public_key_sha256 == hashlib.sha256(_PUBLIC_KEY).hexdigest()
    assert verifier.public_key_bytes == _PUBLIC_KEY
    rendered = repr(loaded) + repr(verifier)
    assert repr(_PUBLIC_KEY) not in rendered
    assert all(value not in rendered for value in _ROLE_VALUES.values())


def test_public_only_verifier_bundle_fails_closed(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_witness_environment(tmp_path)
        )
    _assert_safe_failure(
        caught,
        reason="PROFILED_RESIDENT_WITNESS_VERIFIER_BUNDLE_INCOMPLETE",
    )


def test_secret_only_verifier_bundle_fails_closed(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_witness_public_key(tmp_path)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
    _assert_safe_failure(
        caught,
        reason="PROFILED_RESIDENT_WITNESS_VERIFIER_BUNDLE_INCOMPLETE",
    )


def test_missing_mandatory_local_role_fails_closed(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    path = tmp_path / credentials.EPOCH_HMAC_SYSTEMD_CREDENTIAL
    tmp_path.chmod(0o700)
    path.chmod(0o600)
    path.unlink()
    tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
    _assert_safe_failure(
        caught,
        reason=(
            "PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_UNAVAILABLE_"
            "profiled_observation_epoch_hmac_key"
        ),
    )


def test_reused_local_role_key_fails_closed(tmp_path: Path) -> None:
    values = dict(_ROLE_VALUES)
    values[credentials.EPOCH_HMAC_SYSTEMD_CREDENTIAL] = values[
        credentials.STATE_HMAC_SYSTEMD_CREDENTIAL
    ]
    for name, value in values.items():
        _write_text(tmp_path, name, value)
    tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
    _assert_safe_failure(
        caught,
        reason="PROFILED_RESIDENT_LOCAL_ROLE_KEY_REUSE_FORBIDDEN",
    )


def test_witness_public_key_pin_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_witness_public_key(tmp_path)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_witness_environment(
                tmp_path,
                **{credentials.WITNESS_PUBLIC_KEY_SHA256_ENV: "f" * 64},
            )
        )
    _assert_safe_failure(
        caught,
        reason="PROFILED_RESIDENT_WITNESS_PUBLIC_KEY_PIN_MISMATCH",
    )


def test_witness_public_key_requires_exact_raw_ed25519_length(tmp_path: Path) -> None:
    invalid_key = _PUBLIC_KEY + b"\n"
    _write_local_roles(tmp_path)
    _write_witness_public_key(tmp_path, invalid_key)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_witness_environment(
                tmp_path,
                **{
                    credentials.WITNESS_PUBLIC_KEY_SHA256_ENV: hashlib.sha256(
                        invalid_key
                    ).hexdigest()
                },
            )
        )
    _assert_safe_failure(
        caught,
        reason="PROFILED_RESIDENT_WITNESS_PUBLIC_KEY_INVALID",
    )


@pytest.mark.parametrize(
    ("violation", "reason"),
    [
        (
            "credential-symlink",
            "PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_UNAVAILABLE_"
            "profiled_observation_state_hmac_key",
        ),
        (
            "credential-mode",
            "PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_FILE_INVALID_"
            "profiled_observation_state_hmac_key",
        ),
        (
            "credential-link",
            "PROFILED_RESIDENT_SYSTEMD_CREDENTIAL_FILE_INVALID_"
            "profiled_observation_state_hmac_key",
        ),
        (
            "directory-mode",
            "PROFILED_RESIDENT_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID",
        ),
    ],
)
def test_systemd_credential_filesystem_safety_fails_closed(
    tmp_path: Path,
    violation: str,
    reason: str,
) -> None:
    _write_local_roles(tmp_path)
    state_path = tmp_path / credentials.STATE_HMAC_SYSTEMD_CREDENTIAL
    tmp_path.chmod(0o700)
    if violation == "credential-symlink":
        state_path.chmod(0o600)
        state_path.unlink()
        target = tmp_path / "state-target"
        target.write_text(_ROLE_VALUES[credentials.STATE_HMAC_SYSTEMD_CREDENTIAL])
        target.chmod(0o400)
        state_path.symlink_to(target)
    elif violation == "credential-mode":
        state_path.chmod(0o600)
    elif violation == "credential-link":
        os.link(state_path, tmp_path / "state-hardlink")
    else:
        tmp_path.chmod(0o700)
    if violation != "directory-mode":
        tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.AuthenticatedProfiledResidentCredentialV1Error
    ) as caught:
        credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
    _assert_safe_failure(caught, reason=reason)


def test_obsolete_bearers_are_not_accepted_or_read(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_witness_public_key(tmp_path)
    tmp_path.chmod(0o700)
    for name in _OBSOLETE_BEARER_CREDENTIAL_NAMES:
        (tmp_path / name).symlink_to(tmp_path / "must-not-be-opened")
    tmp_path.chmod(0o500)

    loaded = credentials.load_authenticated_profiled_resident_runtime_credentials_v1(
        environ=_witness_environment(tmp_path)
    )

    assert loaded.witness_verifier is not None
    assert not hasattr(credentials, "WITNESS_BEARER_SYSTEMD_CREDENTIAL")
    assert not hasattr(
        credentials,
        "COMPLETION_AUTHORIZATION_BEARER_SYSTEMD_CREDENTIAL",
    )
