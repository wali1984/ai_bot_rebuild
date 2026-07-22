from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services import binance_usdm_leverage_bracket_evidence as evidence
from v2.backend.app.services import (
    binance_usdm_leverage_bracket_runtime_credentials as credentials,
)
from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter

TRADER_ID = "trader-wajidali1984"
CREDENTIAL_REF = "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY"
HMAC_KEY = "paper-consumer-only-test-hmac-key-at-least-32-bytes"
WRONG_HMAC_KEY = "paper-consumer-wrong-test-hmac-key-at-least-32-bytes"
HMAC_KEY_ID = "binance-bracket-evidence-v1"
ENV_API_KEY = "exchange-api-key-that-must-not-be-loaded"
ENV_API_SECRET = "exchange-api-secret-that-must-not-be-loaded"  # noqa: S105


class _FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, key: str) -> object:
        return self.values.get(key)


def _write_credential(directory: Path, value: str = HMAC_KEY) -> None:
    path = directory / credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o400)


def _environment(directory: Path, **overrides: str) -> dict[str, str]:
    return {
        credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(directory),
        credentials.TRADER_ID_ENV: TRADER_ID,
        credentials.CREDENTIAL_REF_ENV: CREDENTIAL_REF,
        credentials.BASE_URL_ENV: evidence.MAINNET_BASE_URL,
        credentials.EVIDENCE_AUTH_KEY_ID_ENV: HMAC_KEY_ID,
        **overrides,
    }


def test_paper_consumer_loads_only_protected_hmac_and_reports_safe_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_credential(tmp_path)
    monkeypatch.setattr(
        BinanceUSDMAdapter,
        "from_env",
        classmethod(lambda _cls: pytest.fail("paper consumer must not load exchange credentials")),
    )

    context, status = paper_loop._paper_maintenance_bracket_security_context(  # noqa: SLF001
        environ=_environment(tmp_path)
    )

    assert context is not None
    assert context.binding_id == f"mainnet:{TRADER_ID}:{CREDENTIAL_REF}"
    assert status["status"] == "READY"
    assert status["exchange_api_credentials_loaded"] is False
    assert status["environment_secret_fallback_allowed"] is False
    assert status["protected_systemd_hmac_credential_required"] is True
    assert status["exchange_key_permissions_proven_by_connector"] is False
    serialized = json.dumps(status, sort_keys=True)
    assert HMAC_KEY not in serialized
    assert "api_key" not in serialized.lower()
    assert status["exchange_api_secret_used_for_evidence_auth"] is False
    assert HMAC_KEY not in repr(context)


def test_paper_consumer_missing_hmac_never_uses_environment_secret_fallback(
    tmp_path: Path,
) -> None:
    environment_hmac = "plaintext-environment-hmac-that-must-not-be-used"
    environment = _environment(
        tmp_path,
        BINANCE_BRACKET_EVIDENCE_HMAC_KEY=environment_hmac,
        BINANCE_API_KEY=ENV_API_KEY,
        BINANCE_API_SECRET=ENV_API_SECRET,
    )

    context, status = paper_loop._paper_maintenance_bracket_security_context(  # noqa: SLF001
        environ=environment
    )

    assert context is None
    assert status["status"] == "BLOCKED"
    assert status["reason"] == ("SYSTEMD_CREDENTIAL_UNAVAILABLE_BINANCE_BRACKET_EVIDENCE_HMAC_KEY")
    serialized = json.dumps(status, sort_keys=True)
    assert environment_hmac not in serialized
    assert environment["BINANCE_API_KEY"] not in serialized
    assert environment["BINANCE_API_SECRET"] not in serialized


def test_paper_consumer_requires_credentials_directory_even_with_env_hmac() -> None:
    with pytest.raises(
        evidence.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIALS_DIRECTORY_INVALID",
    ):
        credentials.consumer_security_context_from_systemd_credentials(
            environ={
                credentials.TRADER_ID_ENV: TRADER_ID,
                credentials.CREDENTIAL_REF_ENV: CREDENTIAL_REF,
                credentials.BASE_URL_ENV: evidence.MAINNET_BASE_URL,
                credentials.EVIDENCE_AUTH_KEY_ID_ENV: HMAC_KEY_ID,
                evidence.HMAC_KEY_ENV: HMAC_KEY,
            }
        )


def test_paper_consumer_rejects_directory_and_hmac_leaf_symlinks(tmp_path: Path) -> None:
    real_directory = tmp_path / "real-credentials"
    real_directory.mkdir()
    _write_credential(real_directory)
    directory_link = tmp_path / "credential-directory-link"
    directory_link.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(
        evidence.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIALS_DIRECTORY_INVALID",
    ):
        credentials.consumer_security_context_from_systemd_credentials(
            environ=_environment(directory_link)
        )

    hmac_path = real_directory / credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL
    hmac_path.unlink()
    target = tmp_path / "hmac-target"
    target.write_text(HMAC_KEY, encoding="utf-8")
    hmac_path.symlink_to(target)
    with pytest.raises(
        evidence.LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIAL_UNAVAILABLE_BINANCE_BRACKET_EVIDENCE_HMAC_KEY",
    ):
        credentials.consumer_security_context_from_systemd_credentials(
            environ=_environment(real_directory)
        )


def test_paper_consumer_fifo_hmac_fails_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL, mode=0o400)
    environment = {**os.environ, **_environment(tmp_path)}
    script = """
from v2.backend.app.services import binance_usdm_leverage_bracket_runtime_credentials as c
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    LeverageBracketEvidenceError,
)
try:
    c.consumer_security_context_from_systemd_credentials()
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
    assert "SYSTEMD_CREDENTIAL_NOT_REGULAR_BINANCE_BRACKET_EVIDENCE_HMAC_KEY" in (completed.stdout)
    assert HMAC_KEY not in completed.stdout


def test_paper_consumer_wrong_hmac_rejects_producer_evidence(tmp_path: Path) -> None:
    observed_at = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    producer_context = evidence.build_evidence_security_context(
        trader_id=TRADER_ID,
        credential_ref=CREDENTIAL_REF,
        base_url=evidence.MAINNET_BASE_URL,
        credential_account_specific=True,
        hmac_key=HMAC_KEY,
        auth_key_id=HMAC_KEY_ID,
    )
    payload = evidence.build_symbol_evidence(
        {
            "symbol": "BTCUSDT",
            "brackets": [
                {
                    "bracket": 1,
                    "initialLeverage": 20,
                    "notionalFloor": 0,
                    "notionalCap": 1_000_000,
                    "maintMarginRatio": "0.004",
                    "cum": "0",
                }
            ],
        },
        security_context=producer_context,
        fetched_at=observed_at,
    )
    _write_credential(tmp_path, WRONG_HMAC_KEY)
    consumer_context = credentials.consumer_security_context_from_systemd_credentials(
        environ=_environment(tmp_path)
    )
    key = evidence.redis_key("BTCUSDT", security_context=consumer_context)
    decision_time = observed_at + timedelta(seconds=1)

    selected = evidence.select_paper_bracket_evidence(
        _FakeRedis({key: payload}),
        security_context=consumer_context,
        symbol="BTCUSDT",
        candidate_notional=100.0,
        decision_time=decision_time,
        now_fn=lambda: decision_time,
    )

    assert selected["evidence_usable"] is False
    assert selected["status"] == "LEVERAGE_BRACKET_EVIDENCE_MALFORMED"
    assert selected["validation_error_code"] == "EVIDENCE_HMAC_MISMATCH"


def test_paper_consumer_dropin_matches_producer_public_binding_and_only_loads_hmac() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    producer_unit = (
        repo_root / "tools/systemd_units/ai-bot-v2-binance-usdm-leverage-bracket-evidence.service"
    ).read_text(encoding="utf-8")
    consumer_dropin = (
        repo_root
        / "tools/systemd_units/ai-bot-v2-trade-management-paper-loop.service.d"
        / "60-binance-usdm-leverage-bracket-consumer.conf"
    ).read_text(encoding="utf-8")

    for public_binding in (
        f"ALPHAFORGE_INITIAL_TRADER_ID={TRADER_ID}",
        f"ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF={CREDENTIAL_REF}",
        f"BINANCE_USDM_REST_BASE_URL={evidence.MAINNET_BASE_URL}",
        f"BINANCE_BRACKET_EVIDENCE_HMAC_KEY_ID={HMAC_KEY_ID}",
    ):
        assert public_binding in producer_unit
        assert public_binding in consumer_dropin
    hmac_load = (
        "LoadCredential=binance_bracket_evidence_hmac_key:"
        "%h/.config/ai-bot-v2/credentials/binance-bracket-evidence/"
        "evidence-hmac.cred"
    )
    assert hmac_load in producer_unit
    assert hmac_load in consumer_dropin
    assert consumer_dropin.count("LoadCredential=") == 1
    assert "LoadCredentialEncrypted=" not in consumer_dropin
    assert "--api_key" not in consumer_dropin
    assert "--api_secret" not in consumer_dropin
    assert "BINANCE_API_KEY=" not in consumer_dropin
    assert "BINANCE_API_SECRET=" not in consumer_dropin
    assert "BINANCE_BRACKET_EVIDENCE_HMAC_KEY=" not in consumer_dropin
    assert "EnvironmentFile=" not in consumer_dropin
