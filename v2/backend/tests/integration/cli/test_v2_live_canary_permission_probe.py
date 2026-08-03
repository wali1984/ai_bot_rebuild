"""Integration tests for the V2 live-canary network-safe permission probe.

The probe must be fail-closed and verify exchange access *without
ever placing a real order*. These tests cover:

- env-config parsing (no raw credentials propagated)
- credential presence checks
- exchangeInfo (public) probe + per-symbol filter extraction
- account-read permission (signed GET)
- the legacy no-fill REST endpoint stays NOT_CHECKED even if old
  test-order gates are open, because trader/order readiness is
  WebSocket API primary and REST is fallback-only for reads/metadata
- READY transition when every check passes
- BLOCKED transition for each missing precondition
- the status payload NEVER contains raw credentials, NEVER claims
  ``approves_live=true``, NEVER claims ``writes_exchange_orders=true``,
  and pins ``live_gate=blocked_human_only`` / ``live_symbols=[]``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_live_canary_permission_probe as cli
from v2.backend.app.services.live_canary import permission_probe as probe_mod


def _exchange_info_body(symbols: list[dict[str, Any]]) -> str:
    return json.dumps({"symbols": symbols})


def _stub_exchange_info_response(
    symbols: list[dict[str, Any]],
):
    def _fn(path: str, params=None, timeout=10):
        assert path == probe_mod.EXCHANGE_INFO_PATH
        return 200, _exchange_info_body(symbols)

    return _fn


def _stub_signed_response(status_code: int):
    def _fn(api_key: str, api_secret: str, path: str, params=None, timeout=10):
        assert api_key, "signed call must have a key"
        assert api_secret, "signed call must have a secret"
        return status_code, f"HTTP_{status_code}"

    return _fn


def _stub_post_signed_test_response(status_code: int):
    def _fn(api_key: str, api_secret: str, path: str, params=None, timeout=10):
        assert path == probe_mod.TEST_ENDPOINT_PATH
        return status_code, f"HTTP_{status_code}"

    return _fn


def _write_env_file(
    path: Path,
    *,
    mode: str = "V2_NATIVE_SIGNAL_CANARY",
    symbols: str = "BTCUSDT",
    max_notional: str = "20",
    max_daily_trades: str = "3",
    max_daily_loss: str = "10",
    dry_run: str = "true",
    allow_test_order: str | None = None,
) -> None:
    lines = [
        f"V2_LIVE_CANARY_MODE={mode}",
        f"V2_LIVE_CANARY_SYMBOLS={symbols}",
        f"V2_LIVE_CANARY_MAX_NOTIONAL_USDT={max_notional}",
        f"V2_LIVE_CANARY_MAX_DAILY_TRADES={max_daily_trades}",
        f"V2_LIVE_CANARY_MAX_DAILY_LOSS_USDT={max_daily_loss}",
        f"V2_LIVE_CANARY_DRY_RUN={dry_run}",
    ]
    if allow_test_order is not None:
        lines.append(f"V2_LIVE_CANARY_ALLOW_TEST_ORDER={allow_test_order}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _good_symbol(sym: str) -> dict[str, Any]:
    return {
        "symbol": sym,
        "status": "TRADING",
        "contractType": "PERPETUAL",
        "filters": [
            {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        ],
    }


@pytest.fixture
def tmp_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "secrets": tmp_path / ".local_secrets" / "live_canary.env",
        "approval": tmp_path / "approvals" / "OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md",
        "codex_marker": tmp_path / "codex_review" / "CODEX_LIVE_CANARY_PASS.marker",
        "codex_test_order_marker": (
            tmp_path / "codex_review" / "CODEX_TEST_ORDER_DOCS_APPROVED.marker"
        ),
        "worklog": tmp_path / "worklog" / "permission_probe_status.json",
        "public": tmp_path / "public" / "permission_probe_status.json",
        "go_no_go": tmp_path / "worklog" / "GO_NO_GO.md",
    }


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("BINANCE_TEST_ORDER_PROBE_ALLOWED", raising=False)


def test_probe_blocked_when_no_env_file(tmp_paths: dict[str, Path]) -> None:
    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=False,
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == probe_mod.PROBE_GO_BLOCKED
    assert "BINANCE_API_KEY_ENV_VAR_ABSENT" in payload["fail_blockers"]
    assert "BINANCE_API_SECRET_ENV_VAR_ABSENT" in payload["fail_blockers"]
    assert "V2_LIVE_CANARY_MODE_NOT_SELECTED_OR_INVALID" in payload["fail_blockers"]
    assert "V2_LIVE_CANARY_SYMBOLS_WHITELIST_EMPTY" in payload["fail_blockers"]
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert payload["real_order_attempted"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False


def test_default_rest_helpers_are_fallback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)

    public_status, public_body = probe_mod._http_get_public_default(probe_mod.EXCHANGE_INFO_PATH)
    signed_status, signed_body = probe_mod._http_get_signed_default(
        "dummy-key",
        "dummy-secret",
        probe_mod.ACCOUNT_READ_PATH,
    )
    test_status, test_body = probe_mod._http_post_signed_test_default(
        "dummy-key",
        "dummy-secret",
        probe_mod.TEST_ENDPOINT_PATH,
        {"symbol": "BTCUSDT"},
    )

    assert public_status == 0
    assert signed_status == 0
    assert test_status == 0
    assert public_body.startswith("REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY")
    assert signed_body.startswith("REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY")
    assert test_body == probe_mod.REST_TEST_ORDER_DISABLED_REASON


def test_probe_blocked_when_credentials_absent_but_config_present(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    _write_env_file(tmp_paths["secrets"])
    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == probe_mod.PROBE_GO_BLOCKED
    assert "BINANCE_API_KEY_ENV_VAR_ABSENT" in payload["fail_blockers"]
    assert "BINANCE_API_SECRET_ENV_VAR_ABSENT" in payload["fail_blockers"]
    assert payload["mode_selected"] == "V2_NATIVE_SIGNAL_CANARY"
    assert payload["account_read_permission_status"] == "NOT_CHECKED_CREDENTIALS_ABSENT"
    assert payload["symbols_tradable"]["BTCUSDT"] is True
    assert payload["min_notional_by_symbol"]["BTCUSDT"] == 5.0


def test_probe_ready_when_all_checks_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key-not-logged")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret-not-logged")
    _write_env_file(tmp_paths["secrets"], symbols="BTCUSDT,ETHUSDT")
    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response(
            [_good_symbol("BTCUSDT"), _good_symbol("ETHUSDT")]
        ),
        http_get_signed_fn=_stub_signed_response(200),
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == probe_mod.PROBE_GO_READY
    assert payload["fail_blockers"] == []
    assert payload["account_read_permission_status"] == "OK"
    assert payload["exchange_info_call_status"] == "OK"
    assert payload["symbols_tradable"]["BTCUSDT"] is True
    assert payload["symbols_tradable"]["ETHUSDT"] is True
    assert payload["min_notional_by_symbol"]["BTCUSDT"] == 5.0
    assert payload["step_size_by_symbol"]["BTCUSDT"] == 0.001
    assert payload["tick_size_by_symbol"]["BTCUSDT"] == 0.10
    assert payload["test_order_endpoint_status"] == "NOT_CHECKED_FLAG_NOT_SET"
    assert payload["test_order_endpoint_attempted"] is False


def test_probe_uses_canonical_local_binance_binding_without_exposing_values(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    raw_key = "local-key-value-never-serialized"
    raw_secret = "local-secret-value-never-serialized"
    _write_env_file(tmp_paths["secrets"], symbols="BTCUSDT")
    monkeypatch.setattr(probe_mod, "LOCAL_SECRETS_PATH", tmp_paths["secrets"])
    monkeypatch.setattr(
        probe_mod,
        "resolve_binance_credential_binding",
        lambda: SimpleNamespace(
            api_key=raw_key,
            api_secret=raw_secret,
            api_key_source="v2/.env.local",
            api_secret_source="v2/.env.local",
            credential_ref="ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY",
            account_specific=True,
        ),
    )

    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
    )
    payload = result.as_payload()
    flat = json.dumps(payload, sort_keys=True)

    assert payload["exchange_credentials_present"] is True
    assert payload["binance_credential_ref"] == "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY"
    assert payload["binance_api_key_source"] == "v2/.env.local"
    assert payload["binance_api_secret_source"] == "v2/.env.local"
    assert payload["binance_credential_account_specific"] is True
    assert "BINANCE_API_KEY_ENV_VAR_ABSENT" not in payload["fail_blockers"]
    assert "BINANCE_API_SECRET_ENV_VAR_ABSENT" not in payload["fail_blockers"]
    assert raw_key not in flat
    assert raw_secret not in flat
    assert payload["raw_credential_in_payload"] == "NEVER"


def test_probe_blocked_when_symbol_not_tradable(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    _write_env_file(tmp_paths["secrets"], symbols="HALTEDUSDT")
    halted = _good_symbol("HALTEDUSDT")
    halted["status"] = "BREAK"
    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([halted]),
        http_get_signed_fn=_stub_signed_response(200),
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == probe_mod.PROBE_GO_BLOCKED
    assert "SYMBOL_NOT_TRADABLE:HALTEDUSDT" in payload["fail_blockers"]
    assert payload["symbols_tradable"]["HALTEDUSDT"] is False


def test_probe_blocked_when_account_read_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    _write_env_file(tmp_paths["secrets"])
    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(401),
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == probe_mod.PROBE_GO_BLOCKED
    assert payload["account_read_permission_status"].startswith("DENIED_HTTP_")
    matched = [
        b for b in payload["fail_blockers"]
        if b.startswith("ACCOUNT_READ_PERMISSION_DENIED")
    ]
    assert matched, payload["fail_blockers"]


def test_probe_blocked_when_exchange_info_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    _write_env_file(tmp_paths["secrets"])

    def _down(path, params=None, timeout=10):
        return 0, "ERROR:URLError"

    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_down,
        http_get_signed_fn=_stub_signed_response(200),
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == probe_mod.PROBE_GO_BLOCKED
    assert payload["exchange_info_call_status"].startswith("HTTP_0") or payload[
        "exchange_info_call_status"
    ].startswith("HTTP_")
    assert any(
        b.startswith("EXCHANGE_INFO_CALL_FAILED")
        for b in payload["fail_blockers"]
    )


def test_test_order_endpoint_blocked_when_flag_not_set(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    _write_env_file(tmp_paths["secrets"])  # no V2_LIVE_CANARY_ALLOW_TEST_ORDER

    called: list[tuple] = []

    def _no_call(api_key, api_secret, path, params=None, timeout=10):
        called.append((path,))
        return 200, "OK"

    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
        http_post_signed_test_fn=_no_call,
    )
    payload = result.as_payload()
    assert payload["test_order_endpoint_status"] == "NOT_CHECKED_FLAG_NOT_SET"
    assert payload["test_order_endpoint_attempted"] is False
    assert called == []


def test_test_order_endpoint_blocked_when_codex_marker_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    _write_env_file(tmp_paths["secrets"], allow_test_order="true")
    called: list[tuple] = []

    def _no_call(api_key, api_secret, path, params=None, timeout=10):
        called.append((path,))
        return 200, "OK"

    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
        http_post_signed_test_fn=_no_call,
    )
    payload = result.as_payload()
    assert payload["test_order_endpoint_status"] == (
        "NOT_CHECKED_CODEX_TEST_ORDER_DOCS_MARKER_ABSENT"
    )
    assert payload["test_order_endpoint_attempted"] is False
    assert called == []


def test_test_order_endpoint_blocked_when_operator_probe_flag_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    _write_env_file(tmp_paths["secrets"], allow_test_order="true")
    tmp_paths["codex_test_order_marker"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["codex_test_order_marker"].write_text("codex-passes-docs", encoding="utf-8")
    called: list[tuple] = []

    def _no_call(api_key, api_secret, path, params=None, timeout=10):
        called.append((path,))
        return 200, "OK"

    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
        http_post_signed_test_fn=_no_call,
    )
    payload = result.as_payload()
    assert payload["test_order_endpoint_status"] == (
        "NOT_CHECKED_BINANCE_TEST_ORDER_PROBE_ALLOWED_FLAG_NOT_SET"
    )
    assert payload["test_order_endpoint_attempted"] is False
    assert called == []


def test_test_order_endpoint_blocked_even_when_all_legacy_test_probe_gates_open(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy-secret")
    monkeypatch.setenv("BINANCE_TEST_ORDER_PROBE_ALLOWED", "true")
    _write_env_file(tmp_paths["secrets"], allow_test_order="true")
    tmp_paths["codex_test_order_marker"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["codex_test_order_marker"].write_text("codex-passes-docs", encoding="utf-8")
    called: list[tuple] = []

    def _capture(api_key, api_secret, path, params=None, timeout=10):
        called.append((path, params))
        return 200, "OK"

    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
        http_post_signed_test_fn=_capture,
    )
    payload = result.as_payload()
    assert payload["test_order_endpoint_status"] == probe_mod.REST_TEST_ORDER_DISABLED_REASON
    assert payload["test_order_endpoint_attempted"] is False
    assert called == []


def test_payload_never_contains_raw_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    super_secret = "AKIA-LIKE-RAW-SECRET-VALUE-NEVER-LEAK-1234567890"
    monkeypatch.setenv("BINANCE_API_KEY", super_secret)
    monkeypatch.setenv("BINANCE_API_SECRET", super_secret)
    _write_env_file(tmp_paths["secrets"])
    result = probe_mod.run_probe(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        http_get_public_fn=_stub_exchange_info_response([_good_symbol("BTCUSDT")]),
        http_get_signed_fn=_stub_signed_response(200),
    )
    payload = result.as_payload()
    flat = json.dumps(payload)
    assert super_secret not in flat
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert payload["writes_exchange_orders"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_env_config_drops_credential_keys_even_if_placed_in_file(
    tmp_paths: dict[str, Path],
) -> None:
    tmp_paths["secrets"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["secrets"].write_text(
        "\n".join(
            [
                "V2_LIVE_CANARY_MODE=V2_NATIVE_SIGNAL_CANARY",
                "V2_LIVE_CANARY_SYMBOLS=BTCUSDT",
                "V2_LIVE_CANARY_MAX_NOTIONAL_USDT=20",
                "V2_LIVE_CANARY_MAX_DAILY_TRADES=3",
                "V2_LIVE_CANARY_MAX_DAILY_LOSS_USDT=10",
                "V2_LIVE_CANARY_DRY_RUN=true",
                "BINANCE_API_KEY=should-be-dropped-by-parser",
                "BINANCE_API_SECRET=should-be-dropped-by-parser",
                "TOKEN=should-be-dropped",
                "SOME_OTHER_VAR=should-be-dropped",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = probe_mod.read_env_config(tmp_paths["secrets"])
    assert "V2_LIVE_CANARY_MODE" in cfg
    assert "BINANCE_API_KEY" not in cfg
    assert "BINANCE_API_SECRET" not in cfg
    assert "TOKEN" not in cfg
    assert "SOME_OTHER_VAR" not in cfg


def test_run_probe_writes_no_redis_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    # The probe service has no Redis dependency. We assert by reading
    # the module source for any actual import statements or method
    # invocations against a redis client. Docstring text mentioning
    # the word is not a code-level dependency.
    src = Path(probe_mod.__file__).read_text(encoding="utf-8")
    code_lines = [
        line for line in src.splitlines()
        if not line.strip().startswith("#")
        and not line.strip().startswith('"""')
        and not line.strip().startswith("*")
    ]
    code_blob = "\n".join(code_lines)
    assert "import redis" not in code_blob
    assert "from redis" not in code_blob
    assert ".rpush(" not in code_blob
    assert ".xadd(" not in code_blob
    assert ".set(" not in code_blob or ".set(timespec" in code_blob


def test_cli_run_once_writes_status_and_go_no_go(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: dict[str, Path]
) -> None:
    monkeypatch.setenv("BINANCE_API_KEY", "dummy")
    monkeypatch.setenv("BINANCE_API_SECRET", "dummy")
    _write_env_file(tmp_paths["secrets"])
    # Monkeypatch the module-level fallback HTTP funcs and the WebSocket signed
    # read used by the CLI path when no override is passed in.
    monkeypatch.setattr(
        probe_mod,
        "_http_get_public_default",
        _stub_exchange_info_response([_good_symbol("BTCUSDT")]),
    )
    monkeypatch.setattr(
        probe_mod, "_http_get_signed_default", _stub_signed_response(200)
    )

    def _signed_ws_read(self, method: str, params=None, *, execute: bool = False):
        return {
            "status": "SIGNED_WS_READ_EXECUTED",
            "ws_status_code": 200,
            "response_json": {
                "status": 200,
                "result": {
                    "canTrade": True,
                    "canDeposit": True,
                    "canWithdraw": False,
                    "assets": [],
                    "positions": [],
                },
            },
        }

    monkeypatch.setattr(probe_mod.BinanceUSDMAdapter, "signed_ws_read", _signed_ws_read)
    payload = cli.run_once(
        secrets_path=tmp_paths["secrets"],
        codex_test_order_marker_path=tmp_paths["codex_test_order_marker"],
        network_probe_enabled=True,
        out_worklog=tmp_paths["worklog"],
        out_public=tmp_paths["public"],
        out_go_no_go=tmp_paths["go_no_go"],
    )
    assert payload["go_no_go"] == probe_mod.PROBE_GO_READY
    assert tmp_paths["worklog"].exists()
    assert tmp_paths["public"].exists()
    assert tmp_paths["go_no_go"].exists()
    body = tmp_paths["go_no_go"].read_text(encoding="utf-8").strip()
    assert body in (probe_mod.PROBE_GO_READY, probe_mod.PROBE_GO_BLOCKED)
    # Status payload must be deterministic JSON and parse cleanly.
    worklog = json.loads(tmp_paths["worklog"].read_text(encoding="utf-8"))
    assert worklog["raw_credential_in_payload"] == "NEVER"
    assert worklog["real_order_attempted"] is False
    assert worklog["leverage_changed"] is False
    assert worklog["margin_mode_changed"] is False
    assert worklog["writes_legacy_redis"] is False
    assert worklog["writes_exchange_orders"] is False
    assert worklog["live_gate"] == "blocked_human_only"
    assert worklog["live_symbols"] == []
