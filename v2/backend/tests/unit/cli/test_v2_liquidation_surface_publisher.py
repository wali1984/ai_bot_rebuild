from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_liquidation_surface_publisher as cli
from v2.backend.app.services import (
    binance_usdm_leverage_bracket_runtime_credentials as bracket_credentials,
)
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    MAINNET_BASE_URL,
    LeverageBracketEvidenceError,
)
from v2.backend.app.services.liquidation_surface.producer import MarkPriceHistory

TRADER_ID = "trader-wajidali1984"
CREDENTIAL_REF = "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY"
BRACKET_HMAC = "bracket-evidence-test-hmac-material-at-least-32-bytes"
PUBLICATION_HMAC = "surface-publication-test-hmac-material-at-least-32-bytes"


def _environment(directory: Path, **overrides: str) -> dict[str, str]:
    return {
        bracket_credentials.SYSTEMD_CREDENTIALS_DIRECTORY_ENV: str(directory),
        bracket_credentials.TRADER_ID_ENV: TRADER_ID,
        bracket_credentials.CREDENTIAL_REF_ENV: CREDENTIAL_REF,
        bracket_credentials.BASE_URL_ENV: MAINNET_BASE_URL,
        bracket_credentials.EVIDENCE_AUTH_KEY_ID_ENV: "bracket-evidence-v1",
        cli.PUBLICATION_AUTH_KEY_ID_ENV: "surface-publication-v1",
        **overrides,
    }


def _credential(directory: Path, name: str, value: str) -> None:
    path = directory / name
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o400)


def _write_context_credentials(
    directory: Path,
    *,
    bracket_hmac: str = BRACKET_HMAC,
    publication_hmac: str = PUBLICATION_HMAC,
) -> None:
    _credential(
        directory,
        bracket_credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        bracket_hmac,
    )
    _credential(
        directory,
        cli.PUBLICATION_HMAC_SYSTEMD_CREDENTIAL,
        publication_hmac,
    )


def test_security_contexts_load_only_independent_protected_hmac_keys(
    tmp_path: Path,
) -> None:
    _write_context_credentials(tmp_path)

    bracket_context, publication_context = cli.security_contexts_from_systemd_credentials(
        environ=_environment(
            tmp_path,
            BINANCE_API_KEY="environment-api-key-must-not-be-read",
            BINANCE_API_SECRET="environment-api-secret-must-not-be-read",  # noqa: S106
            LIQUIDATION_SURFACE_PUBLICATION_HMAC_KEY=(
                "environment-publication-key-must-not-be-read"
            ),
        )
    )

    assert bracket_context.binding_id == f"mainnet:{TRADER_ID}:{CREDENTIAL_REF}"
    assert publication_context.hmac_key == PUBLICATION_HMAC.encode("utf-8")
    assert publication_context.hmac_key != bracket_context.hmac_key
    assert publication_context.auth_key_id == "surface-publication-v1"
    assert BRACKET_HMAC not in repr(bracket_context)
    assert PUBLICATION_HMAC not in repr(publication_context)


def test_security_contexts_reject_key_reuse(tmp_path: Path) -> None:
    _write_context_credentials(
        tmp_path,
        bracket_hmac=BRACKET_HMAC,
        publication_hmac=BRACKET_HMAC,
    )

    with pytest.raises(
        cli.LiquidationSurfacePublisherCLIError,
        match="PUBLICATION_HMAC_KEY_MUST_DIFFER",
    ):
        cli.security_contexts_from_systemd_credentials(environ=_environment(tmp_path))


def test_publication_credential_has_no_environment_fallback(tmp_path: Path) -> None:
    _credential(
        tmp_path,
        bracket_credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        BRACKET_HMAC,
    )

    with pytest.raises(
        LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIAL_UNAVAILABLE_LIQUIDATION_SURFACE_PUBLICATION_HMAC_KEY",
    ):
        cli.security_contexts_from_systemd_credentials(
            environ=_environment(
                tmp_path,
                LIQUIDATION_SURFACE_PUBLICATION_HMAC_KEY=PUBLICATION_HMAC,
            )
        )


def test_publication_credential_symlink_is_rejected(tmp_path: Path) -> None:
    _credential(
        tmp_path,
        bracket_credentials.EVIDENCE_HMAC_SYSTEMD_CREDENTIAL,
        BRACKET_HMAC,
    )
    target = tmp_path / "publication-target"
    target.write_text(PUBLICATION_HMAC, encoding="utf-8")
    (tmp_path / cli.PUBLICATION_HMAC_SYSTEMD_CREDENTIAL).symlink_to(target)

    with pytest.raises(
        LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIAL_UNAVAILABLE_LIQUIDATION_SURFACE_PUBLICATION_HMAC_KEY",
    ):
        cli.security_contexts_from_systemd_credentials(environ=_environment(tmp_path))


def test_run_once_resolves_dynamic_universe_and_passes_exact_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_context_credentials(tmp_path)
    bracket_context, publication_context = cli.security_contexts_from_systemd_credentials(
        environ=_environment(tmp_path)
    )
    observed: dict[str, Any] = {}
    monkeypatch.setattr(
        cli,
        "resolve_symbols_with_provenance",
        lambda **_kwargs: {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "source_path": "/safe/universe.json",
            "smoke_test": False,
        },
    )

    def cycle(_redis: Any, **kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return {"schema_version": "producer-v1", "status": "COMPLETE", "lane_count": 8}

    monkeypatch.setattr(cli, "run_producer_cycle", cycle)
    history = MarkPriceHistory()

    result = cli.run_once(
        redis_client=object(),
        bracket_security_context=bracket_context,
        publication_security_context=publication_context,
        mark_history=history,
        timeframes=("1m", "5m"),
    )

    assert observed["symbols"] == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert observed["timeframes"] == ("1m", "5m")
    assert observed["bracket_security_context"] is bracket_context
    assert observed["publication_security_context"] is publication_context
    assert observed["mark_history"] is history
    assert result["symbol_profile"] == "dynamic_or_baseline"
    assert result["symbol_universe_smoke_test"] is False


def test_loop_re_resolves_universe_every_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def once(**_kwargs: Any) -> dict[str, Any]:
        calls.append(len(calls) + 1)
        return {"status": "COMPLETE", "cycle": calls[-1]}

    monkeypatch.setattr(cli, "run_once", once)
    emitted: list[dict[str, Any]] = []
    latest = cli.run_loop(
        redis_client=object(),
        bracket_security_context=object(),  # type: ignore[arg-type]
        publication_security_context=object(),  # type: ignore[arg-type]
        mark_history=MarkPriceHistory(),
        interval_seconds=0.001,
        max_cycles=2,
        on_result=emitted.append,
    )

    assert calls == [1, 2]
    assert emitted == [
        {"status": "COMPLETE", "cycle": 1},
        {"status": "COMPLETE", "cycle": 2},
    ]
    assert latest["cycle"] == 2


def test_public_status_is_count_heavy_and_secret_safe() -> None:
    status = cli.public_status(
        {
            "status": "PARTIAL",
            "lane_count": 795,
            "published_lane_count": 639,
            "trainer_authority_count": 0,
            "error_samples": [{"raw": "do-not-print"}],
            "hmac_key": "do-not-print",
        }
    )

    assert status == {
        "status": "PARTIAL",
        "lane_count": 795,
        "published_lane_count": 639,
        "trainer_authority_count": 0,
    }
    assert "do-not-print" not in json.dumps(status)


def test_service_unit_loads_only_verification_keys_and_stays_observation_only() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    unit = (
        repo_root
        / "tools/systemd_units/ai-bot-v2-liquidation-surface-publisher.service"
    ).read_text(encoding="utf-8")

    assert unit.count("LoadCredential=") == 2
    assert "binance_bracket_evidence_hmac_key:" in unit
    assert "liquidation_surface_publication_hmac_key:" in unit
    assert "--api_key" not in unit
    assert "--api_secret" not in unit
    assert "BINANCE_API_KEY=" not in unit
    assert "BINANCE_API_SECRET=" not in unit
    assert 'Environment="LIVE_GATE=blocked_human_only"' in unit
    assert "v2_liquidation_surface_publisher --loop" in unit
    assert "%h/.local/share/ai-bot-v2/worktrees/liquidation-publisher" in unit


def test_protected_named_reader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / cli.PUBLICATION_HMAC_SYSTEMD_CREDENTIAL, mode=0o400)

    with pytest.raises(
        LeverageBracketEvidenceError,
        match="SYSTEMD_CREDENTIAL_NOT_REGULAR_LIQUIDATION_SURFACE_PUBLICATION_HMAC_KEY",
    ):
        bracket_credentials.read_protected_systemd_credential(
            cli.PUBLICATION_HMAC_SYSTEMD_CREDENTIAL,
            environ=_environment(tmp_path),
        )
