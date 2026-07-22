from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_binance_usdm_commission_evidence_broker as cli
from v2.backend.app.services import binance_usdm_commission_evidence_broker as broker
from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    BinanceUSDMCommissionCaptureV1TransportError,
)


def _ready_universe() -> dict[str, Any]:
    return {
        "status": "READY",
        "source_key": broker.DYNAMIC_COMMISSION_UNIVERSE_KEY,
        "source_payload_sha256": "a" * 64,
        "source_pttl_ms": 60_000,
        "server_observed_at": "2026-07-22T05:00:00.000000Z",
        "source_expires_at": "2026-07-22T05:01:00.000000Z",
        "symbols": ("BTCUSDT", "ETHUSDT"),
        "rejected_symbols": ("币安人生USDT",),
    }


def test_run_turn_uses_only_current_dynamic_universe_and_one_request(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        cli,
        "read_adaptive_commission_rotation_universe",
        lambda _redis: _ready_universe(),
    )
    calls: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {
            "status": "READY",
            "selected_symbol": "BTCUSDT",
            "request_count": 1,
            "request_executed": True,
            "pacing_ms": 10_000,
            "places_real_order": False,
            "order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }

    result = cli.run_turn(
        adapter=object(),
        redis_client=object(),
        store=object(),  # type: ignore[arg-type]
        security_context=object(),  # type: ignore[arg-type]
        environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
        capture_function=capture,
    )

    assert len(calls) == 1
    assert calls[0]["symbols"] == ("BTCUSDT", "ETHUSDT")
    assert calls[0]["priority_symbols"] == ()
    assert result["universe_symbol_count"] == 2
    assert result["universe_rejected_symbol_count"] == 1
    assert result["request_count"] == 1
    assert result["places_real_order"] is False


def test_run_turn_defers_without_request_when_universe_is_unavailable(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        cli,
        "read_adaptive_commission_rotation_universe",
        lambda _redis: {
            "status": "DYNAMIC_COMMISSION_UNIVERSE_MISSING",
            "symbols": (),
            "rejected_symbols": (),
        },
    )
    calls = 0

    def forbidden_capture(**_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise AssertionError("missing selection metadata must not call Binance")

    result = cli.run_turn(
        adapter=object(),
        redis_client=object(),
        store=object(),  # type: ignore[arg-type]
        security_context=object(),  # type: ignore[arg-type]
        environ={"BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE": "120"},
        capture_function=forbidden_capture,
    )

    assert calls == 0
    assert result["status"] == "DEFERRED"
    assert result["reason"] == "DYNAMIC_COMMISSION_UNIVERSE_MISSING"
    assert result["request_executed"] is False
    assert result["pacing_ms"] == 10_000


def test_main_requires_explicit_read_only_opt_in_before_credentials(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    credential_calls = 0

    def forbidden_credentials() -> tuple[Any, Any]:
        nonlocal credential_calls
        credential_calls += 1
        raise AssertionError("no credentials before explicit opt-in")

    monkeypatch.setattr(
        cli,
        "adapter_and_security_context_from_systemd_credentials",
        forbidden_credentials,
    )

    exit_code = cli.main(["--once", "--data-root", str(tmp_path.absolute())])

    assert exit_code == 78
    assert credential_calls == 0
    output = capsys.readouterr().err
    assert "COMMISSION_BROKER_EXPLICIT_READ_ONLY_OPT_IN_REQUIRED" in output


def test_main_accepts_absolute_path_subclass_and_runs_one_isolated_turn(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "adapter_and_security_context_from_systemd_credentials",
        lambda: (object(), object()),
    )
    monkeypatch.setattr(cli, "_redis_client", lambda _url: object())
    monkeypatch.setattr(cli, "default_commission_broker_store", lambda _root: object())
    monkeypatch.setattr(
        cli,
        "run_turn",
        lambda **_kwargs: {
            "status": "READY",
            "request_count": 1,
            "request_executed": True,
            "read_only": True,
            "places_real_order": False,
            "order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        },
    )
    cli._STOP.clear()  # noqa: SLF001

    exit_code = cli.main(
        [
            "--once",
            "--execute-read-only",
            "--data-root",
            str(tmp_path.absolute()),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "READY"


def test_public_status_cannot_render_secret_or_raw_material() -> None:
    status = cli.public_status(
        {
            "status": "READY",
            "selected_symbol": "BTCUSDT",
            "api_key": "DO_NOT_RENDER_API_KEY",
            "api_secret": "DO_NOT_RENDER_API_SECRET",
            "evidence_hmac_key": "DO_NOT_RENDER_HMAC",
            "raw_response_bytes": b"DO_NOT_RENDER_RAW",
            "request_count": 1,
        }
    )
    rendered = json.dumps(status)

    assert "DO_NOT_RENDER" not in rendered
    assert status["exchange_credentials_exposed"] is False
    assert status["evidence_hmac_key_exposed"] is False
    assert status["raw_response_exposed"] is False
    assert status["live_authority"] is False


def test_capture_failure_keeps_exact_safe_reason_and_suppresses_unknown_detail() -> None:
    capture_error = BinanceUSDMCommissionCaptureV1TransportError(
        "COMMISSION_CAPTURE_HTTP_TRANSPORT_FAILED"
    )
    unknown = RuntimeError("API_SECRET_SHOULD_NOT_ESCAPE")

    assert cli._safe_failure_reason(  # noqa: SLF001
        capture_error,
        scope="TURN_EXCEPTION",
    ) == "COMMISSION_CAPTURE_HTTP_TRANSPORT_FAILED"
    rendered = cli._safe_failure_reason(unknown, scope="TURN_EXCEPTION")  # noqa: SLF001
    assert rendered == "COMMISSION_BROKER_TURN_EXCEPTION_RUNTIMEERROR"
    assert "SHOULD_NOT_ESCAPE" not in rendered


def test_tracked_producer_unit_is_isolated_hardened_and_commission_only() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    unit = (
        repo_root
        / "tools/systemd_units/ai-bot-v2-binance-usdm-commission-evidence-broker.service"
    ).read_text(encoding="utf-8")
    broker_root = (
        "/home/wali/ai_bot_local_data/v2_authenticated_evidence/"
        "binance_usdm_commission_broker_v1"
    )

    assert unit.count("LoadCredential=") == 3
    assert "--execute-read-only" in unit
    assert "v2_binance_usdm_commission_evidence_broker" in unit
    assert "v2_binance_usdm_leverage_bracket_evidence" not in unit
    assert f"ReadWritePaths={broker_root}" in unit
    assert f"BINANCE_COMMISSION_BROKER_DATA_ROOT={broker_root}" in unit
    assert "BINANCE_REST_FALLBACK_BUDGET_PER_MINUTE=120" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=read-only" in unit
    assert "NoNewPrivileges=true" in unit
    assert "RestartPreventExitStatus=2 78" in unit
    assert "LIVE_GATE=blocked_human_only" in unit
    for forbidden in (
        "EnvironmentFile=",
        "BINANCE_API_KEY=",
        "BINANCE_API_SECRET=",
        "/order",
        "/leverage",
        "/marginType",
        "/cancel",
        "/transfer",
    ):
        assert forbidden not in unit


def test_producer_immutable_dropin_uses_one_clean_release_identity() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    dropin = (
        repo_root
        / "tools/systemd_units/"
        "ai-bot-v2-binance-usdm-commission-evidence-broker.service.d/"
        "90-immutable-release.conf"
    ).read_text(encoding="utf-8")
    release_shas = set(
        re.findall(r"deployments/ai_bot_rebuild/([0-9a-f]{40})", dropin)
    )

    assert release_shas == {"a11d4c7aa188edda310abede1ef33c5afec33e51"}
    assert "AI_BOT_CODE_SHA=a11d4c7aa188edda310abede1ef33c5afec33e51" in dropin
    assert "git -C /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/" in dropin
    assert "diff --quiet --exit-code a11d4c7aa188edda310abede1ef33c5afec33e51 --" in dropin
    assert "v2_binance_usdm_commission_evidence_broker --execute-read-only" in dropin
    assert "WorkingDirectory=/home/wali/Desktop/AI BOT REBUILD" not in dropin
