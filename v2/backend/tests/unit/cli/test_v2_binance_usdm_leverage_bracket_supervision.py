from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_binance_usdm_leverage_bracket_evidence as cli
from v2.backend.app.services import binance_usdm_leverage_bracket_evidence as mod

TRADER_ID = "trader-asjad"
CREDENTIAL_REF = "ASJAD_BINANCE_READONLY"
API_KEY = "test-only-scoped-api-key"
API_SECRET = "test-only-scoped-api-secret"  # noqa: S105
EVIDENCE_HMAC_KEY = "test-only-separate-evidence-hmac-key-with-32-bytes"
EVIDENCE_HMAC_KEY_ID = "test-bracket-evidence-v1"


def _credential_name(suffix: str) -> str:
    return f"{TRADER_ID}--{CREDENTIAL_REF}--{suffix}"


def _write_credential(directory: Path, name: str, value: str) -> None:
    path = directory / name
    if path.exists():
        path.chmod(0o600)
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o400)


def _runtime_environment(directory: Path, **overrides: str) -> dict[str, str]:
    return {
        cli.SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(directory),
        cli.TRADER_ID_ENV: TRADER_ID,
        cli.CREDENTIAL_REF_ENV: CREDENTIAL_REF,
        cli.BASE_URL_ENV: mod.MAINNET_BASE_URL,
        cli.EVIDENCE_AUTH_KEY_ID_ENV: EVIDENCE_HMAC_KEY_ID,
        **overrides,
    }


def _write_runtime_credentials(directory: Path) -> None:
    _write_credential(directory, _credential_name("api_key"), API_KEY)
    _write_credential(directory, _credential_name("api_secret"), API_SECRET)
    _write_credential(
        directory,
        cli.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        EVIDENCE_HMAC_KEY,
    )


def test_systemd_credentials_build_exact_read_only_binding(tmp_path: Path) -> None:
    _write_runtime_credentials(tmp_path)

    adapter, context = cli._adapter_and_security_context_from_systemd_credentials(
        environ=_runtime_environment(tmp_path)
    )

    assert adapter.api_key == API_KEY
    assert adapter.api_secret == API_SECRET
    assert adapter.base_url == mod.MAINNET_BASE_URL
    assert context.binding_id == f"mainnet:{TRADER_ID}:{CREDENTIAL_REF}"
    assert context.safe_metadata()["credential_ref_read_only_assertion"] is True
    assert context.safe_metadata()["exchange_key_permissions_proven_by_connector"] is False
    serialized = json.dumps(context.safe_metadata())
    assert API_KEY not in serialized
    assert API_SECRET not in serialized
    assert EVIDENCE_HMAC_KEY not in serialized
    assert EVIDENCE_HMAC_KEY not in repr(context)
    public = cli.public_status({"status": "READY", **context.safe_metadata()})
    assert public["credential_ref_read_only_assertion"] is True
    assert (
        public["credential_ref_read_only_assertion_semantics"]
        == "OPERATOR_USAGE_LABEL_NOT_BINANCE_PERMISSION_PROOF"
    )
    assert public["exchange_key_permissions_proven_by_connector"] is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {cli.CREDENTIAL_REF_ENV: "BINANCE"},
            "SYSTEMD_CREDENTIAL_UNAVAILABLE_TRADER-ASJAD--BINANCE--API_KEY",
        ),
        (
            {cli.CREDENTIAL_REF_ENV: "BINANCE_READONLY"},
            "SYSTEMD_CREDENTIAL_UNAVAILABLE_TRADER-ASJAD--BINANCE_READONLY--API_KEY",
        ),
        (
            {cli.CREDENTIAL_REF_ENV: CREDENTIAL_REF.lower()},
            (
                "SYSTEMD_CREDENTIAL_UNAVAILABLE_TRADER-ASJAD--"
                "ASJAD_BINANCE_READONLY--API_KEY"
            ),
        ),
        ({cli.BASE_URL_ENV: "http://fapi.binance.com"}, "BINANCE_BASE_URL_NOT_SAFE_ORIGIN"),
        ({cli.EVIDENCE_AUTH_KEY_ID_ENV: ""}, "EVIDENCE_AUTH_KEY_ID_UNSAFE"),
    ],
)
def test_systemd_credentials_fail_closed_on_binding_or_origin_change(
    tmp_path: Path,
    overrides: dict[str, str],
    expected: str,
) -> None:
    _write_runtime_credentials(tmp_path)

    with pytest.raises(mod.LeverageBracketEvidenceError, match=expected):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(tmp_path, **overrides)
        )


@pytest.mark.parametrize(
    ("exchange_credential", "expected"),
    [
        (API_KEY, "EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_API_KEY"),
        (API_SECRET, "EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_SECRET"),
    ],
)
def test_systemd_credentials_reject_reused_exchange_credential_as_hmac(
    tmp_path: Path,
    exchange_credential: str,
    expected: str,
) -> None:
    _write_runtime_credentials(tmp_path)
    _write_credential(
        tmp_path,
        cli.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        exchange_credential,
    )

    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match=expected,
    ):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_systemd_credentials_reject_directory_and_leaf_symlinks(tmp_path: Path) -> None:
    credential_directory = tmp_path / "credentials"
    credential_directory.mkdir()
    _write_runtime_credentials(credential_directory)
    directory_link = tmp_path / "credential-link"
    directory_link.symlink_to(credential_directory, target_is_directory=True)

    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIALS_DIRECTORY_INVALID",
    ):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(directory_link)
        )

    api_key_path = credential_directory / _credential_name("api_key")
    api_key_path.unlink()
    api_key_target = tmp_path / "api-key-target"
    api_key_target.write_text(API_KEY, encoding="utf-8")
    api_key_path.symlink_to(api_key_target)
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIAL_UNAVAILABLE_.*API_KEY",
    ):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(credential_directory)
        )


def test_systemd_credentials_reject_intermediate_symlink_and_parent_traversal(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    credential_directory = real_parent / "credentials"
    credential_directory.mkdir(parents=True)
    _write_runtime_credentials(credential_directory)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIALS_DIRECTORY_INVALID",
    ):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(linked_parent / "credentials")
        )

    traversal = real_parent / "ignored" / ".." / "credentials"
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIALS_DIRECTORY_INVALID",
    ):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(traversal)
        )


def test_systemd_fifo_credential_fails_without_blocking(tmp_path: Path) -> None:
    _write_runtime_credentials(tmp_path)
    api_key_path = tmp_path / _credential_name("api_key")
    api_key_path.unlink()
    os.mkfifo(api_key_path, mode=0o400)
    environment = {**os.environ, **_runtime_environment(tmp_path)}
    script = """
from v2.backend.app.cli import v2_binance_usdm_leverage_bracket_evidence as cli
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    LeverageBracketEvidenceError,
)
try:
    cli._adapter_and_security_context_from_systemd_credentials()
except LeverageBracketEvidenceError as exc:
    print(str(exc))
    raise SystemExit(0)
raise SystemExit(1)
"""

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=2,
    )

    assert completed.returncode == 0
    assert "SYSTEMD_CREDENTIAL_NOT_REGULAR" in completed.stdout
    assert API_KEY not in completed.stdout


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a" * (cli.MAX_SYSTEMD_CREDENTIAL_BYTES + 1), "SYSTEMD_CREDENTIAL_TOO_LARGE"),
        (f"{EVIDENCE_HMAC_KEY}\nsecond-line", "SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE"),
        (f" {EVIDENCE_HMAC_KEY}", "SYSTEMD_CREDENTIAL_NOT_SINGLE_LINE"),
    ],
)
def test_systemd_hmac_credential_is_bounded_single_line(
    tmp_path: Path,
    value: str,
    expected: str,
) -> None:
    _write_runtime_credentials(tmp_path)
    _write_credential(tmp_path, cli.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL, value)

    with pytest.raises(mod.LeverageBracketEvidenceError, match=expected):
        cli._adapter_and_security_context_from_systemd_credentials(
            environ=_runtime_environment(tmp_path)
        )


def test_empty_credentials_directory_env_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(cli.SYSTEMD_CREDENTIALS_DIRECTORY_ENV, "")
    monkeypatch.setattr(
        cli.BinanceUSDMAdapter,
        "from_env",
        classmethod(lambda _cls: pytest.fail("legacy env fallback must not run")),
    )
    monkeypatch.setattr(
        cli,
        "_redis_client",
        lambda _url=None: pytest.fail("Redis must not be contacted"),
    )

    assert cli.main(["--once", "--json"]) == 2
    output = capsys.readouterr().out
    assert "SYSTEMD_CREDENTIALS_DIRECTORY_INVALID" in output
    assert API_KEY not in output
    assert API_SECRET not in output
    assert EVIDENCE_HMAC_KEY not in output


def test_generic_binance_reference_is_not_a_valid_evidence_context() -> None:
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="CREDENTIAL_REF_NOT_EXPLICITLY_READ_ONLY",
    ):
        mod.build_evidence_security_context(
            trader_id=TRADER_ID,
            credential_ref="BINANCE",
            base_url=mod.MAINNET_BASE_URL,
            credential_account_specific=True,
            hmac_key=EVIDENCE_HMAC_KEY,
            auth_key_id=EVIDENCE_HMAC_KEY_ID,
        )


@pytest.mark.parametrize(
    "credential_ref",
    [
        "NOT_READONLY",
        "READONLY_DISABLED",
        "WRITE_READONLY",
        "READONLY-WRITE",
        "NO_READONLY",
        "FALSE_READONLY",
        "DISALLOW_READONLY",
        "NOTRADE_READONLY",
        "BINANCE_READONLY",
    ],
)
def test_contradictory_read_only_reference_is_rejected(credential_ref: str) -> None:
    with pytest.raises(
        mod.LeverageBracketEvidenceError,
        match="CREDENTIAL_REF_NOT_EXPLICITLY_READ_ONLY",
    ):
        mod.build_evidence_security_context(
            trader_id=TRADER_ID,
            credential_ref=credential_ref,
            base_url=mod.MAINNET_BASE_URL,
            credential_account_specific=True,
            hmac_key=EVIDENCE_HMAC_KEY,
            auth_key_id=EVIDENCE_HMAC_KEY_ID,
        )


def test_supervised_unit_contains_no_plaintext_secret_configuration() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    unit = (
        repo_root / "tools/systemd_units/ai-bot-v2-binance-usdm-leverage-bracket-evidence.service"
    ).read_text(encoding="utf-8")

    assert "LoadCredential=" in unit
    assert "EnvironmentFile=" not in unit
    assert "BINANCE_API_KEY=" not in unit
    assert "BINANCE_API_SECRET=" not in unit
    assert "BINANCE_BRACKET_EVIDENCE_HMAC_KEY=" not in unit
    assert f"ALPHAFORGE_INITIAL_TRADER_ID={TRADER_ID}" in unit
    assert f"ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF={CREDENTIAL_REF}" in unit
    assert "BINANCE_REST_FALLBACK_ALLOWED=true" in unit
    assert "v2_binance_usdm_leverage_bracket_evidence --loop" in unit
    assert "LIVE_GATE=blocked_human_only" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert f"LoadCredential={_credential_name('api_key')}:" in unit
    assert f"LoadCredential={_credential_name('api_secret')}:" in unit
    assert f"LoadCredential={cli.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL}:" in unit
