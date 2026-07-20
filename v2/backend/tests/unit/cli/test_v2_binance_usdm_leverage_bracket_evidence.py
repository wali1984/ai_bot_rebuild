from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.cli import v2_binance_usdm_leverage_bracket_evidence as cli
from v2.backend.app.services import binance_usdm_leverage_bracket_evidence as mod
from v2.backend.tests.unit.services.test_binance_usdm_leverage_bracket_evidence import (
    SECURITY,
    TEST_HMAC_KEY,
    TEST_HMAC_KEY_ID,
    FakeAdapter,
    FakeRedis,
    _row,
)

TEST_EXCHANGE_SECRET = "test-only-exchange-secret"  # noqa: S105


def test_main_once_uses_fake_adapter_and_prints_only_secret_free_status(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    adapter = FakeAdapter([_row()])
    redis = FakeRedis()
    monkeypatch.setattr(
        cli.BinanceUSDMAdapter,
        "from_env",
        classmethod(lambda _cls: adapter),
    )
    monkeypatch.setattr(
        cli,
        "evidence_security_context_for_adapter",
        lambda _adapter: SECURITY,
    )
    monkeypatch.setattr(cli, "_redis_client", lambda _url=None: redis)

    exit_code = cli.main(["--once", "--symbols", "BTCUSDT", "--json"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"status": "READY"' in output
    assert '"credential_binding_id": "mainnet:trader-test:' in output
    assert '"credential_fields_exposed": false' in output
    assert '"evidence_auth_key_exposed": false' in output
    assert TEST_HMAC_KEY not in output
    assert "DO_NOT_STORE" not in output
    assert "signature" not in output
    assert "X-MBX-APIKEY" not in output


def test_run_loop_can_execute_multiple_cycles_with_fakes() -> None:
    adapter = FakeAdapter([_row()])
    redis = FakeRedis()
    results: list[dict[str, Any]] = []

    latest = cli.run_loop(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        interval_seconds=0.0001,
        max_cycles=2,
        on_result=results.append,
    )

    assert latest["status"] == "READY"
    assert len(results) == 2
    assert len(adapter.calls) == 2


def test_no_execute_remains_fail_closed() -> None:
    adapter = FakeAdapter([_row()], status="SIGNED_READ_READY_NOT_EXECUTED")
    redis = FakeRedis()

    status = cli.run_once(
        adapter=adapter,
        redis_client=redis,
        security_context=SECURITY,
        symbols=["BTCUSDT"],
        execute=False,
    )

    assert status["status"] == "BLOCKED"
    assert adapter.calls[0]["execute"] is False


def test_shared_security_context_helper_binds_credentials_and_separate_key(
    monkeypatch: Any,
) -> None:
    binding = SimpleNamespace(
        is_configured=True,
        account_specific=True,
        api_key="exchange-api-key",
        api_secret=TEST_EXCHANGE_SECRET,
        trader_id="trader-test",
        credential_ref="TEST_BINANCE_READONLY",
        read_only_ref=True,
    )
    adapter = SimpleNamespace(
        api_key="exchange-api-key",
        api_secret=TEST_EXCHANGE_SECRET,
        base_url=mod.MAINNET_BASE_URL,
    )
    monkeypatch.setattr(
        mod,
        "resolve_binance_credential_binding",
        lambda: binding,
    )

    context = mod.evidence_security_context_for_adapter(
        adapter,
        environ={
            mod.HMAC_KEY_ENV: TEST_HMAC_KEY,
            mod.HMAC_KEY_ID_ENV: TEST_HMAC_KEY_ID,
        },
    )

    assert context == SECURITY
    assert context.hmac_key != binding.api_secret.encode()


@pytest.mark.parametrize(
    ("binding_overrides", "adapter_overrides", "environ", "error"),
    [
        (
            {"is_configured": False},
            {},
            {},
            "ACCOUNT_SPECIFIC_BINANCE_CREDENTIAL_BINDING_NOT_CONFIGURED",
        ),
        (
            {"account_specific": False},
            {},
            {},
            "CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC",
        ),
        (
            {"read_only_ref": False},
            {},
            {},
            "CREDENTIAL_REF_NOT_EXPLICITLY_READ_ONLY",
        ),
        (
            {},
            {"api_secret": "different-secret"},
            {},
            "ADAPTER_CREDENTIAL_BINDING_MISMATCH",
        ),
        (
            {},
            {},
            {
                mod.HMAC_KEY_ENV: "exchange-api-key",
                mod.HMAC_KEY_ID_ENV: TEST_HMAC_KEY_ID,
            },
            "EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_API_KEY",
        ),
        (
            {},
            {},
            {
                mod.HMAC_KEY_ENV: TEST_EXCHANGE_SECRET,
                mod.HMAC_KEY_ID_ENV: TEST_HMAC_KEY_ID,
            },
            "EVIDENCE_HMAC_KEY_MUST_DIFFER_FROM_EXCHANGE_SECRET",
        ),
        (
            {},
            {},
            {},
            "EVIDENCE_AUTH_KEY_ID_MISSING_OR_NOT_STRING",
        ),
    ],
)
def test_shared_security_context_helper_fails_closed_on_unsafe_configuration(
    monkeypatch: Any,
    binding_overrides: dict[str, Any],
    adapter_overrides: dict[str, Any],
    environ: dict[str, str],
    error: str,
) -> None:
    binding_values = {
        "is_configured": True,
        "account_specific": True,
        "api_key": "exchange-api-key",
        "api_secret": TEST_EXCHANGE_SECRET,
        "trader_id": "trader-test",
        "credential_ref": "TEST_BINANCE_READONLY",
        "read_only_ref": True,
        **binding_overrides,
    }
    adapter_values = {
        "api_key": "exchange-api-key",
        "api_secret": TEST_EXCHANGE_SECRET,
        "base_url": mod.MAINNET_BASE_URL,
        **adapter_overrides,
    }
    monkeypatch.setattr(
        mod,
        "resolve_binance_credential_binding",
        lambda: SimpleNamespace(**binding_values),
    )

    with pytest.raises(mod.LeverageBracketEvidenceError, match=error):
        mod.evidence_security_context_for_adapter(
            SimpleNamespace(**adapter_values),
            environ=environ,
        )


def test_main_missing_security_config_blocks_before_redis_or_signed_read(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    adapter = FakeAdapter([_row()])
    monkeypatch.setattr(
        cli.BinanceUSDMAdapter,
        "from_env",
        classmethod(lambda _cls: adapter),
    )

    def fail_security(_adapter: Any) -> mod.EvidenceSecurityContext:
        raise mod.LeverageBracketEvidenceError("EVIDENCE_HMAC_KEY_MISSING_OR_TOO_SHORT")

    monkeypatch.setattr(
        cli,
        "evidence_security_context_for_adapter",
        fail_security,
    )
    monkeypatch.setattr(
        cli,
        "_redis_client",
        lambda _url=None: pytest.fail("Redis must not be contacted"),
    )

    exit_code = cli.main(["--once", "--symbols", "BTCUSDT", "--json"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert '"status": "BLOCKED"' in output
    assert "EVIDENCE_HMAC_KEY_MISSING_OR_TOO_SHORT" in output
    assert adapter.calls == []
    assert TEST_HMAC_KEY not in output


def test_public_status_drops_secret_and_signature_fields() -> None:
    payload = {
        **SECURITY.safe_metadata(),
        "schema_version": mod.STATUS_SCHEMA_VERSION,
        "status": "READY",
        "reason": "TEST",
        "api_secret": "EXCHANGE_SECRET_DO_NOT_PRINT",
        "evidence_hmac_key": TEST_HMAC_KEY,
        "evidence_hmac_sha256": "signed-tag-do-not-print-here",
        "signature": "exchange-request-signature",
    }
    serialized = json.dumps(cli.public_status(payload))
    assert "EXCHANGE_SECRET_DO_NOT_PRINT" not in serialized
    assert TEST_HMAC_KEY not in serialized
    assert "signed-tag-do-not-print-here" not in serialized
    assert "exchange-request-signature" not in serialized
    assert SECURITY.binding_id in serialized
