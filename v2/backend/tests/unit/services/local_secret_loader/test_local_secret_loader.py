from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from v2.backend.app.services.local_secret_loader import (
    LocalSecretLoader,
    SecretAccessDenied,
)
from v2.backend.app.services.local_secret_loader.service import (
    BACKEND_READONLY_DATA,
    EXCHANGE_MUTATION,
    FRONTEND_PUBLIC,
    LIVE_TRADING,
)


def _write_manifest(vault: Path, env_path: Path) -> None:
    manifest = {
        "schema": "local_legacy_secret_manifest_redacted_v1",
        "value_redacted": True,
        "live_use_allowed": False,
        "key_count_total": 2,
        "records": [
            {
                "source_path": "/legacy/.env",
                "destination_path": str(env_path),
                "copied": True,
                "key_names": ["DATA_PROVIDER_API_KEY", "EXCHANGE_API_SECRET"],
                "key_count": 2,
                "value_redacted": True,
                "secret_type_guess": "env_config",
                "required_by_subsystem": "global_runtime_env",
                "live_use_allowed": False,
            }
        ],
    }
    (vault / "secret_manifest_redacted.json").write_text(json.dumps(manifest), encoding="utf-8")


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / ".local_secrets" / "legacy_runtime"
    raw = vault / "raw"
    raw.mkdir(parents=True)
    os.chmod(tmp_path / ".local_secrets", 0o700)
    os.chmod(vault, 0o700)
    os.chmod(raw, 0o700)
    env_path = raw / ".env"
    env_path.write_text(
        "DATA_PROVIDER_API_KEY=value-one\n"
        "EXCHANGE_API_SECRET=value-two\n",
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)
    _write_manifest(vault, env_path)
    return vault


def test_loader_reads_manifest_and_returns_redacted_status(tmp_path: Path) -> None:
    loader = LocalSecretLoader(_vault(tmp_path))
    status = loader.redacted_public_status()
    assert status["secrets_copied"] is True
    assert status["file_count"] == 1
    assert status["key_count"] == 2
    assert status["value_redacted"] is True
    assert status["live_use_allowed"] is False
    assert "value-one" not in json.dumps(status)
    assert "value-two" not in json.dumps(status)


def test_secret_value_repr_and_str_are_redacted(tmp_path: Path) -> None:
    loader = LocalSecretLoader(_vault(tmp_path))
    value = loader.get("DATA_PROVIDER_API_KEY")
    assert value.reveal(usage=BACKEND_READONLY_DATA) == "value-one"
    assert "value-one" not in repr(value)
    assert "value-one" not in str(value)
    assert value.redacted_dict()["value_redacted"] is True


def test_frontend_usage_is_denied(tmp_path: Path) -> None:
    loader = LocalSecretLoader(_vault(tmp_path))
    with pytest.raises(SecretAccessDenied):
        loader.get("DATA_PROVIDER_API_KEY", usage=FRONTEND_PUBLIC)


def test_live_and_exchange_mutation_usage_denied_without_approval(tmp_path: Path) -> None:
    loader = LocalSecretLoader(_vault(tmp_path))
    value = loader.get("EXCHANGE_API_SECRET")
    with pytest.raises(SecretAccessDenied):
        value.reveal(usage=LIVE_TRADING)
    with pytest.raises(SecretAccessDenied):
        value.reveal(usage=EXCHANGE_MUTATION)


def test_manifest_record_cannot_escape_vault(tmp_path: Path) -> None:
    vault = tmp_path / ".local_secrets" / "legacy_runtime"
    vault.mkdir(parents=True)
    outside = tmp_path / "outside.env"
    outside.write_text("A=B\n", encoding="utf-8")
    manifest = {
        "value_redacted": True,
        "live_use_allowed": False,
        "records": [
            {
                "source_path": "/legacy/.env",
                "destination_path": str(outside),
                "copied": True,
                "key_names": ["A"],
                "key_count": 1,
                "value_redacted": True,
                "secret_type_guess": "env_config",
                "required_by_subsystem": "test",
                "live_use_allowed": False,
            }
        ],
    }
    (vault / "secret_manifest_redacted.json").write_text(json.dumps(manifest), encoding="utf-8")
    loader = LocalSecretLoader(vault)
    with pytest.raises(SecretAccessDenied):
        loader.records()
