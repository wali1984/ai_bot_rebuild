"""Vault-aware native ingestor classification tests (paper-only)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def test_secret_decision_reads_only_key_names_from_vault(tmp_path: Path) -> None:
    from v2.backend.app.services.native_ingestors.secret_decision import (
        key_name_available,
    )

    vault = tmp_path / "legacy.env"
    vault.write_text(
        "# comment line\n"
        "COINAPI_API_KEY=THIS_IS_A_SECRET_VALUE_DO_NOT_LEAK\n"
        "COINANK_API_KEY=ANOTHER_SECRET\n"
        "export ENABLE_COINAPI=true\n"
    )
    assert key_name_available("COINAPI_API_KEY", vault_path=vault, env={}) is True
    assert key_name_available("COINANK_API_KEY", vault_path=vault, env={}) is True
    assert key_name_available("ENABLE_COINAPI", vault_path=vault, env={}) is True
    assert key_name_available("UNKNOWN_KEY", vault_path=vault, env={}) is False


def test_secret_decision_env_overrides_vault(tmp_path: Path) -> None:
    from v2.backend.app.services.native_ingestors.secret_decision import (
        key_name_available,
    )

    empty_vault = tmp_path / "empty.env"
    empty_vault.write_text("")
    assert key_name_available("COINAPI_API_KEY", vault_path=empty_vault, env={"COINAPI_API_KEY": "v"}) is True
    assert key_name_available("COINAPI_API_KEY", vault_path=empty_vault, env={}) is False


def test_decision_snapshot_does_not_include_raw_values(tmp_path: Path) -> None:
    from v2.backend.app.services.native_ingestors.secret_decision import (
        decision_snapshot,
    )

    vault = tmp_path / "legacy.env"
    secret_marker = "RAW_SECRET_VALUE_PROBE_MARKER"
    vault.write_text(
        f"COINAPI_API_KEY={secret_marker}\n"
        f"COINANK_API_KEY=another_{secret_marker}\n"
    )
    snap = decision_snapshot(vault_path=vault, env={})
    body = json.dumps(snap)
    assert secret_marker not in body
    assert snap["raw_secret_values_recorded"] is False
    assert snap["key_presence_redacted"]["COINAPI_API_KEY"] is True
    assert snap["key_presence_redacted"]["COINANK_API_KEY"] is True
    assert snap["live_gate"] == "blocked_human_only"
    assert snap["live_symbols"] == []


def test_decision_snapshot_handles_missing_vault(tmp_path: Path) -> None:
    from v2.backend.app.services.native_ingestors.secret_decision import (
        decision_snapshot,
    )

    snap = decision_snapshot(vault_path=tmp_path / "nope.env", env={})
    assert snap["vault_path_exists"] is False
    for v in snap["key_presence_redacted"].values():
        assert v is False


def test_registry_classifies_coinapi_native_when_vault_present_via_loader_patch(monkeypatch) -> None:
    """Patch key_name_available to simulate vault key presence and verify
    that the runtime classifier upgrades CoinAPI to native read-only data.
    """
    from v2.backend.app.services.native_ingestors import registry as reg_mod

    def fake_available(name: str, **kwargs) -> bool:
        return name in {"COINAPI_API_KEY", "COINANK_API_KEY"}

    monkeypatch.setattr(
        "v2.backend.app.services.native_ingestors.secret_decision.key_name_available",
        fake_available,
    )
    cls = reg_mod._classify("live_coinapi_v1")
    assert cls.classification == "NATIVE_V2_READONLY_PUBLIC_DATA"
    cls = reg_mod._classify("live_coinank")
    assert cls.classification == "NATIVE_V2_READONLY_PUBLIC_DATA"


def test_registry_classifies_coinapi_blocked_when_keys_absent(monkeypatch) -> None:
    from v2.backend.app.services.native_ingestors import registry as reg_mod

    monkeypatch.setattr(
        "v2.backend.app.services.native_ingestors.secret_decision.key_name_available",
        lambda name, **kwargs: False,
    )
    cls = reg_mod._classify("live_coinapi_v1")
    assert cls.classification == "BLOCKED_BY_SECRET_OR_API"
    cls = reg_mod._classify("live_coinank")
    assert cls.classification == "BLOCKED_BY_SECRET_OR_API"


def test_paid_wsds_remains_operator_decision_when_keys_present(monkeypatch) -> None:
    from v2.backend.app.services.native_ingestors import registry as reg_mod

    monkeypatch.setattr(
        "v2.backend.app.services.native_ingestors.secret_decision.key_name_available",
        lambda name, **kwargs: True,
    )
    cls = reg_mod._classify("live_coinapi_wsds")
    assert cls.classification == "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN"


def test_native_ingestors_status_payload_no_raw_secret_strings() -> None:
    """The emitted public status payload must not contain raw secret values."""
    p = Path(
        "v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json"
    )
    if not p.exists():
        pytest.skip("payload not present")
    body = p.read_text()
    # The vault contains values; payload must not embed them.
    # Use a generous deny-list of high-confidence patterns.
    for pattern in ("API_KEY=", "secret_key", "private_key"):
        assert pattern.lower() not in body.lower()


def test_secret_decision_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/native_ingestors/secret_decision.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
        "import requests",
    ):
        assert forbidden not in text
