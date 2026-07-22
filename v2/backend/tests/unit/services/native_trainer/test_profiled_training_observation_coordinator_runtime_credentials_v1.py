from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_runtime_credentials_v1 as credentials,
)

_ROLE_VALUES = {
    credentials.STATE_HMAC_SYSTEMD_CREDENTIAL: "state-local-role-key-material-0000000001",
    credentials.MANIFEST_HMAC_SYSTEMD_CREDENTIAL: (
        "manifest-local-role-key-material-00000002"
    ),
    credentials.HEAD_HMAC_SYSTEMD_CREDENTIAL: "head-local-role-key-material-00000000003",
    credentials.EPOCH_HMAC_SYSTEMD_CREDENTIAL: "epoch-local-role-key-material-0000000004",
}
_BEARER = "independent-witness-bearer-token-for-tests"
_PUBLIC_KEY = bytes(range(32))
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


def _write_witness(directory: Path) -> None:
    _write_text(directory, credentials.WITNESS_BEARER_SYSTEMD_CREDENTIAL, _BEARER)
    _write_bytes(
        directory,
        credentials.WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
        _PUBLIC_KEY,
    )
    directory.chmod(0o500)


def _environment(directory: Path, **overrides: str) -> dict[str, str]:
    return {
        credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(directory),
        # Ambient generic secrets are deliberately irrelevant.
        "BINANCE_API_KEY": "must-not-be-read",
        "BINANCE_API_SECRET": "must-not-be-read",
        **overrides,
    }


def _witness_environment(directory: Path, **overrides: str) -> dict[str, str]:
    return _environment(
        directory,
        **{
            credentials.WITNESS_BASE_URL_ENV: "https://witness.example.test/v1",
            credentials.WITNESS_ID_ENV: "independent-witness-v1",
            credentials.WITNESS_PUBLIC_KEY_SHA256_ENV: hashlib.sha256(
                _PUBLIC_KEY
            ).hexdigest(),
            credentials.WITNESS_TIMEOUT_SECONDS_ENV: "15",
            **overrides,
        },
    )


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


def test_local_roles_load_without_external_witness_and_hide_values(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)

    loaded = credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
        environ=_environment(tmp_path)
    )

    assert loaded.external_witness is None
    assert loaded.local_roles.state_hmac_key == _ROLE_VALUES[
        credentials.STATE_HMAC_SYSTEMD_CREDENTIAL
    ].encode()
    rendered = repr(loaded) + repr(loaded.local_roles)
    assert all(value not in rendered for value in _ROLE_VALUES.values())
    assert "must-not-be-read" not in rendered


def test_complete_external_witness_bundle_is_pinned_and_hidden(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_witness(tmp_path)

    loaded = credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
        environ=_witness_environment(tmp_path)
    )

    witness = loaded.external_witness
    assert witness is not None
    assert witness.base_url == "https://witness.example.test/v1"
    assert witness.witness_id == "independent-witness-v1"
    assert witness.timeout_seconds == 15.0
    assert witness.bearer_token == _BEARER
    assert witness.public_key_bytes == _PUBLIC_KEY
    rendered = repr(loaded) + repr(witness)
    assert _BEARER not in rendered
    assert repr(_PUBLIC_KEY) not in rendered


def test_production_directory_is_bound_to_exact_user_unit() -> None:
    assert _PRODUCTION_EXPECTED_DIRECTORY() == Path(
        f"/run/user/{os.geteuid()}/credentials/"
        "ai-bot-v2-profiled-training-observation-coordinator.service"
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
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_BINDING_INVALID",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
    assert opened is False


def test_missing_local_role_fails_closed(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    path = tmp_path / credentials.EPOCH_HMAC_SYSTEMD_CREDENTIAL
    tmp_path.chmod(0o700)
    path.chmod(0o600)
    path.unlink()
    tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_UNAVAILABLE_.*epoch",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_environment(tmp_path)
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
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_LOCAL_ROLE_KEY_REUSE_FORBIDDEN",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )


@pytest.mark.parametrize("public_configured", [False, True])
def test_partial_external_witness_bundle_never_degrades_to_absent(
    tmp_path: Path,
    public_configured: bool,
) -> None:
    _write_local_roles(tmp_path)
    if not public_configured:
        _write_text(
            tmp_path,
            credentials.WITNESS_BEARER_SYSTEMD_CREDENTIAL,
            _BEARER,
        )
        tmp_path.chmod(0o500)
        environ = _environment(tmp_path)
    else:
        environ = _witness_environment(tmp_path)

    with pytest.raises(
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_EXTERNAL_WITNESS_BUNDLE_INCOMPLETE",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=environ
        )


def test_external_public_key_pin_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_witness(tmp_path)

    with pytest.raises(
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_EXTERNAL_WITNESS_PUBLIC_KEY_PIN_MISMATCH",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_witness_environment(
                tmp_path,
                **{credentials.WITNESS_PUBLIC_KEY_SHA256_ENV: "f" * 64},
            )
        )


def test_external_public_key_requires_exact_raw_ed25519_length(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    _write_text(tmp_path, credentials.WITNESS_BEARER_SYSTEMD_CREDENTIAL, _BEARER)
    invalid_key = _PUBLIC_KEY + b"\n"
    _write_bytes(
        tmp_path,
        credentials.WITNESS_PUBLIC_KEY_SYSTEMD_CREDENTIAL,
        invalid_key,
    )
    tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_EXTERNAL_WITNESS_PUBLIC_KEY_INVALID",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_witness_environment(
                tmp_path,
                **{
                    credentials.WITNESS_PUBLIC_KEY_SHA256_ENV: hashlib.sha256(
                        invalid_key
                    ).hexdigest()
                },
            )
        )


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        (0o700, "PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID"),
        (0o400, "PROFILED_COORDINATOR_SYSTEMD_CREDENTIALS_DIRECTORY_PERMISSIONS_INVALID"),
    ],
)
def test_directory_permissions_are_exact(
    tmp_path: Path,
    mode: int,
    reason: str,
) -> None:
    _write_local_roles(tmp_path)
    tmp_path.chmod(mode)
    with pytest.raises(
        credentials.ProfiledObservationCoordinatorCredentialError,
        match=reason,
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )


def test_credential_symlink_is_rejected(tmp_path: Path) -> None:
    _write_local_roles(tmp_path)
    state_path = tmp_path / credentials.STATE_HMAC_SYSTEMD_CREDENTIAL
    target = tmp_path / "target"
    tmp_path.chmod(0o700)
    state_path.chmod(0o600)
    state_path.unlink()
    target.write_text(_ROLE_VALUES[credentials.STATE_HMAC_SYSTEMD_CREDENTIAL])
    target.chmod(0o400)
    state_path.symlink_to(target)
    tmp_path.chmod(0o500)

    with pytest.raises(
        credentials.ProfiledObservationCoordinatorCredentialError,
        match="PROFILED_COORDINATOR_SYSTEMD_CREDENTIAL_UNAVAILABLE_.*state",
    ):
        credentials.load_profiled_observation_coordinator_runtime_credentials_v1(
            environ=_environment(tmp_path)
        )
