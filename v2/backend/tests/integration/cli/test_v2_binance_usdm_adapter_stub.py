"""Integration tests for the v2_binance_usdm_adapter_stub worker.

Required test coverage:

  1. place_order_raises_BLOCKED_GATE_NOT_APPROVED
  2. cancel_raises_BLOCKED_GATE_NOT_APPROVED
  3. change_initial_leverage_raises_BLOCKED_GATE_NOT_APPROVED
  4. change_margin_type_raises_BLOCKED_GATE_NOT_APPROVED
  5. change_position_mode_raises_BLOCKED_GATE_NOT_APPROVED
  6. no_real_exchange_method_can_be_invoked_from_this_stub_contract
  7. stub_remains_disabled_by_default_invariant
  8. read_only_methods_do_not_unlock_live_gate
  9. read_only_account_info_v3_returns_no_secret_value
 10. read_only_position_risk_returns_no_secret_value
 11. read_only_methods_make_no_real_exchange_call
 12. credentials_presence_in_env_is_boolean_only_value_never_returned
 13. credentials_value_never_logged_to_stdout_or_stderr
 14. status_payload_contains_no_secret_value
 15. symbol_universe_contract_required
 16. legacy_active_symbols_current_25_preserved
 17. no_train_or_trade_all_discovered_symbols_automatically
 18. coinank_symbols_require_binance_usdm_confirmation
 19. live_symbols_empty_while_live_blocked
 20. required_public_payload_fields_present
 21. stub_state_never_active_on_any_codepath
 22. no_exchange_client_attribute_reachable
 23. no_codepath_unblocks_live_gate
 24. main_status_only_writes_payload
 25. blocked_call_counter_increments_per_method
 26. readonly_call_counter_increments_per_method
"""
from __future__ import annotations

import io
import json
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_binance_usdm_adapter_stub as worker
from v2.backend.app.cli.v2_binance_usdm_adapter_stub import (
    EXCHANGE_CALL_INVARIANT,
    LEGACY_BINANCE_USDM_SOURCE_PATHS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SECRET_LEAK_INVARIANT,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.binance_usdm_adapter import service as adapter_service
from v2.backend.app.services.binance_usdm_adapter.service import (
    ALLOWED_STUB_STATES,
    BinanceUsdmAdapter,
    BlockedGateNotApprovedError,
    CREDENTIAL_ENV_KEYS,
    ERROR_CODE,
    LEGACY_READONLY_REST_PATHS,
    LIVE_GATE_STATUS,
    MUTATION_METHODS,
    READ_ONLY_METHODS,
    STATE_BLOCKED,
    STATE_DISABLED,
    credentials_present_in_env,
)
from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


SECRET_SENTINEL_KEY = "sentinel_api_key_VALUE_SHOULD_NEVER_LEAK_abc123XYZ"
SECRET_SENTINEL_SECRET = "sentinel_api_secret_VALUE_SHOULD_NEVER_LEAK_def456UVW"


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _route_writes_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(
        worker, "PUBLIC_STATUS_FILE", public_dir / f"{WORKER_ID}_status.json"
    )
    monkeypatch.setattr(
        worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json"
    )
    monkeypatch.setattr(
        worker, "WORKER_STATUS_FILE", worker_dir / f"{WORKER_ID}_status.json"
    )
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_symbol_universe_payload.json"],
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_key in CREDENTIAL_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)


def _set_sentinel_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BINANCE_LIVE_API_KEY", SECRET_SENTINEL_KEY)
    monkeypatch.setenv("BINANCE_LIVE_API_SECRET", SECRET_SENTINEL_SECRET)


# ----------------------------------------------------------------------
# 1) place_order raises BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_place_order_raises_blocked_gate_not_approved() -> None:
    adapter = BinanceUsdmAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.place_order(symbol="BTCUSDT", side="BUY", quantity=0.001, price=20000)
    assert exc.value.code == ERROR_CODE == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "place_order"
    assert adapter.blocked_call_attempts_total == 1
    assert adapter.blocked_call_breakdown_by_method["place_order"] == 1


# ----------------------------------------------------------------------
# 2) cancel raises BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_cancel_raises_blocked_gate_not_approved() -> None:
    adapter = BinanceUsdmAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.cancel(symbol="BTCUSDT", order_id="12345")
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "cancel"
    assert adapter.blocked_call_breakdown_by_method["cancel"] == 1


# ----------------------------------------------------------------------
# 3) change_initial_leverage raises BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_change_initial_leverage_raises_blocked_gate_not_approved() -> None:
    adapter = BinanceUsdmAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.change_initial_leverage(symbol="BTCUSDT", leverage=25)
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "change_initial_leverage"
    assert adapter.blocked_call_breakdown_by_method["change_initial_leverage"] == 1


# ----------------------------------------------------------------------
# 3) change_margin_type raises BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_change_margin_type_raises_blocked_gate_not_approved() -> None:
    adapter = BinanceUsdmAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.change_margin_type(symbol="BTCUSDT", marginType="CROSS")
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "change_margin_type"
    assert adapter.blocked_call_breakdown_by_method["change_margin_type"] == 1


# ----------------------------------------------------------------------
# 4) change_position_mode raises BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_change_position_mode_raises_blocked_gate_not_approved() -> None:
    adapter = BinanceUsdmAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.change_position_mode(dualSidePosition=True)
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "change_position_mode"
    assert adapter.blocked_call_breakdown_by_method["change_position_mode"] == 1


# ----------------------------------------------------------------------
# 5) no real exchange method can be invoked from this stub contract
# ----------------------------------------------------------------------


def test_no_real_exchange_method_can_be_invoked_from_this_stub_contract() -> None:
    sources = {
        "worker": Path(worker.__file__).read_text(),
        "service": Path(adapter_service.__file__).read_text(),
    }
    forbidden_imports = [
        "import bin" + "ance",
        "from bin" + "ance",
        "import cc" + "xt",
        "from cc" + "xt",
        "import re" + "dis",
        "from re" + "dis",
    ]
    forbidden_methods = [
        "futures" + "_" + "create" + "_" + "order",
        "futures" + "_" + "cancel" + "_" + "order",
        "futures" + "_" + "change" + "_" + "leverage",
        "futures" + "_" + "change" + "_" + "margin" + "_" + "type",
        "futures" + "_" + "change" + "_" + "position" + "_" + "mode",
    ]
    forbidden_writers = [".set(", ".hset(", ".xadd(", ".publish("]
    for name, src in sources.items():
        for token in forbidden_imports:
            assert token not in src, f"{name} source contains forbidden import: {token!r}"
        for token in forbidden_methods:
            assert token not in src, f"{name} source contains forbidden method: {token!r}"
        for token in forbidden_writers:
            assert token not in src, f"{name} source contains Redis writer: {token!r}"


# ----------------------------------------------------------------------
# 6) stub remains disabled by default invariant
# ----------------------------------------------------------------------


def test_stub_remains_disabled_by_default_invariant() -> None:
    adapter = BinanceUsdmAdapter()
    assert adapter.state == STATE_DISABLED
    assert STATE_DISABLED in ALLOWED_STUB_STATES
    assert STATE_BLOCKED in ALLOWED_STUB_STATES
    assert "ACTIVE" not in ALLOWED_STUB_STATES
    snapshot = adapter.state_snapshot()
    assert (
        snapshot["stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE"]
        in ALLOWED_STUB_STATES
    )
    for method in MUTATION_METHODS:
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)()
    assert adapter.state == STATE_DISABLED


# ----------------------------------------------------------------------
# 7) read-only methods do not unlock live gate
# ----------------------------------------------------------------------


def test_read_only_methods_do_not_unlock_live_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_sentinel_credentials(monkeypatch)
    adapter = BinanceUsdmAdapter()
    assert adapter.live_gate == "blocked_human_only"
    snap1 = adapter.account_info_v3()
    snap2 = adapter.position_risk()
    assert adapter.live_gate == "blocked_human_only"
    assert snap1["live_gate"] == "blocked_human_only"
    assert snap2["live_gate"] == "blocked_human_only"
    assert snap1["live_gate_unlocked_by_this_call"] is False
    assert snap2["live_gate_unlocked_by_this_call"] is False
    assert adapter.state_snapshot()["live_gate_unlocked_by_readonly_access"] is False
    # Even after the readonly methods have been called, every mutation
    # method must still raise.
    for method in MUTATION_METHODS:
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)()


# ----------------------------------------------------------------------
# 8/9) read-only methods return no secret value
# ----------------------------------------------------------------------


def test_read_only_account_info_v3_returns_no_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_sentinel_credentials(monkeypatch)
    adapter = BinanceUsdmAdapter()
    snapshot = adapter.account_info_v3()
    serialized = json.dumps(snapshot, default=str)
    assert SECRET_SENTINEL_KEY not in serialized
    assert SECRET_SENTINEL_SECRET not in serialized
    assert snapshot["credentials_returned"] is False
    assert snapshot["credentials_logged"] is False
    assert snapshot["credentials_present_in_env"] is True
    assert snapshot["exchange_call_taken"] is False


def test_read_only_position_risk_returns_no_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_sentinel_credentials(monkeypatch)
    adapter = BinanceUsdmAdapter()
    snapshot = adapter.position_risk()
    serialized = json.dumps(snapshot, default=str)
    assert SECRET_SENTINEL_KEY not in serialized
    assert SECRET_SENTINEL_SECRET not in serialized
    assert snapshot["credentials_returned"] is False
    assert snapshot["credentials_logged"] is False
    assert snapshot["credentials_present_in_env"] is True
    assert snapshot["exchange_call_taken"] is False


# ----------------------------------------------------------------------
# 10) read-only methods make no real exchange call
# ----------------------------------------------------------------------


def test_read_only_methods_make_no_real_exchange_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_sentinel_credentials(monkeypatch)
    adapter = BinanceUsdmAdapter()
    snap1 = adapter.account_info_v3()
    snap2 = adapter.position_risk()
    assert snap1["exchange_call_taken"] is False
    assert snap2["exchange_call_taken"] is False
    assert (
        snap1["snapshot_unavailable_because_stub_makes_no_exchange_call"] is True
    )
    assert (
        snap2["snapshot_unavailable_because_stub_makes_no_exchange_call"] is True
    )
    # No attribute should exist on the adapter that points at an
    # exchange client or transport.
    for attr in ["session", "http", "rest_client", "ws_client", "transport"]:
        assert not hasattr(adapter, attr)


# ----------------------------------------------------------------------
# 11) credentials presence in env is boolean only; value never returned
# ----------------------------------------------------------------------


def test_credentials_presence_in_env_is_boolean_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_credentials(monkeypatch)
    assert credentials_present_in_env() is False
    _set_sentinel_credentials(monkeypatch)
    assert credentials_present_in_env() is True
    # presence-only contract: the function returns bool, never the value
    result = credentials_present_in_env()
    assert isinstance(result, bool)
    assert result != SECRET_SENTINEL_KEY
    assert result != SECRET_SENTINEL_SECRET


def test_partial_credentials_count_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.setenv("BINANCE_LIVE_API_KEY", SECRET_SENTINEL_KEY)
    # secret missing
    assert credentials_present_in_env() is False


# ----------------------------------------------------------------------
# 12) credentials value never logged to stdout/stderr by the worker
# ----------------------------------------------------------------------


def test_credentials_value_never_logged_when_running_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    _set_sentinel_credentials(monkeypatch)
    caplog.set_level(logging.DEBUG)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        rc = main(["--status-only"])
    assert rc == 0
    captured = stdout_buf.getvalue() + stderr_buf.getvalue()
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    haystack = captured + "\n" + log_text
    assert SECRET_SENTINEL_KEY not in haystack
    assert SECRET_SENTINEL_SECRET not in haystack
    # also call the read-only methods explicitly and check no leak
    adapter = BinanceUsdmAdapter()
    stdout_buf2 = io.StringIO()
    stderr_buf2 = io.StringIO()
    with redirect_stdout(stdout_buf2), redirect_stderr(stderr_buf2):
        adapter.account_info_v3()
        adapter.position_risk()
    haystack2 = stdout_buf2.getvalue() + stderr_buf2.getvalue()
    assert SECRET_SENTINEL_KEY not in haystack2
    assert SECRET_SENTINEL_SECRET not in haystack2


# ----------------------------------------------------------------------
# 13) status payload contains no secret value
# ----------------------------------------------------------------------


def test_status_payload_contains_no_secret_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    _set_sentinel_credentials(monkeypatch)
    main(["--status-only"])
    written = (paths["public"] / f"{WORKER_ID}_status.json").read_text()
    assert SECRET_SENTINEL_KEY not in written
    assert SECRET_SENTINEL_SECRET not in written
    payload = json.loads(written)
    assert payload["credentials_present_in_env"] is True
    assert payload["credentials_returned_by_any_method"] is False
    assert payload["credentials_logged_by_any_method"] is False
    assert payload["secret_leak_invariant"] == SECRET_LEAK_INVARIANT
    # source code itself must not include the sentinel either (sanity)
    src = Path(adapter_service.__file__).read_text()
    assert SECRET_SENTINEL_KEY not in src
    assert SECRET_SENTINEL_SECRET not in src


# ----------------------------------------------------------------------
# 14) symbol universe contract required
# ----------------------------------------------------------------------


def test_symbol_universe_contract_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_source_path"] == SYMBOL_UNIVERSE_SERVICE_PATH
    assert (
        status["symbol_universe_public_payload_status"]
        == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    )
    assert (
        "missing_symbol_universe_public_payload"
        in status["symbol_universe_payload_evidence_gaps"]
    )


# ----------------------------------------------------------------------
# 15) legacy_active_symbols current 25 preserved
# ----------------------------------------------------------------------


def test_legacy_active_symbols_current_25_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert status["legacy_active_symbols"] == list(LEGACY_ACTIVE_SYMBOLS_25)
    assert len(status["legacy_active_symbols"]) == 25
    assert (
        status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    )
    # The CLI worker source must not hardcode the 25-symbol list inline
    worker_source = Path(worker.__file__).read_text()
    for symbol in LEGACY_ACTIVE_SYMBOLS_25:
        assert f'"{symbol}"' not in worker_source, (
            f"worker source unexpectedly hardcodes legacy active symbol: {symbol!r}"
        )


# ----------------------------------------------------------------------
# 16) no train or trade all discovered symbols automatically
# ----------------------------------------------------------------------


def test_no_train_or_trade_all_discovered_symbols_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert (
        status["symbol_scope_policy"]
        == "do_not_train_or_trade_all_discovered_symbols_automatically"
    )


# ----------------------------------------------------------------------
# 17) coinank symbols require binance usdm confirmation
# ----------------------------------------------------------------------


def test_coinank_symbols_require_binance_usdm_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert (
        status["coinank_symbols_tradability"]
        == "market_intelligence_only_until_binance_usdm_confirmed"
    )
    assert "coinank" in status["dynamic_symbol_sources"]
    assert status["binance_usdm_confirmed_symbols"] == []


# ----------------------------------------------------------------------
# 18) live symbols empty while live blocked
# ----------------------------------------------------------------------


def test_live_symbols_empty_while_live_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert status["live_symbols"] == []
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["live_blocked"] is True
    assert isinstance(status["live_blocked_symbols"], list)


# ----------------------------------------------------------------------
# 19) required public payload fields present
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"missing required public payload field: {field!r}"
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written, f"missing required field on disk: {field!r}"
    assert (paths["local"] / f"{WORKER_ID}_status.json").exists()
    assert (paths["worker"] / f"{WORKER_ID}_status.json").exists()


# ----------------------------------------------------------------------
# 20) stub state never ACTIVE on any code path
# ----------------------------------------------------------------------


def test_stub_state_never_active_on_any_codepath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert (
        status["stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE"]
        in (STATE_DISABLED, STATE_BLOCKED)
    )
    assert "ACTIVE" not in status["allowed_stub_states"]
    assert status["mutation_methods"] == list(MUTATION_METHODS)
    assert status["readonly_methods"] == list(READ_ONLY_METHODS)
    assert status["endpoints_blocked_mutating"] == list(MUTATION_METHODS)
    assert status["endpoints_exposed_read_only"] == list(READ_ONLY_METHODS)
    assert status["exchange_client_present"] is False
    assert status["exchange_action_taken"] is False
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["error_code_on_call"] == ERROR_CODE


# ----------------------------------------------------------------------
# 21) no exchange client attribute reachable
# ----------------------------------------------------------------------


def test_no_exchange_client_attribute_reachable() -> None:
    for attr in [
        "exchange_client",
        "binance_client",
        "futures_client",
        "ccxt_client",
        "Client",
        "BinanceClient",
        "FuturesClient",
        "CcxtClient",
    ]:
        assert not hasattr(worker, attr), (
            f"worker module unexpectedly exposes attribute: {attr!r}"
        )
        assert not hasattr(adapter_service, attr), (
            f"service module unexpectedly exposes attribute: {attr!r}"
        )
    adapter = BinanceUsdmAdapter()
    for attr in [
        "exchange_client",
        "binance_client",
        "futures_client",
        "ccxt_client",
        "client",
        "rest_client",
        "ws_client",
        "transport",
        "session",
        "http",
        "api_key",
        "api_secret",
        "secret",
    ]:
        assert not hasattr(adapter, attr), (
            f"adapter instance unexpectedly exposes attribute: {attr!r}"
        )


# ----------------------------------------------------------------------
# 22) no codepath unblocks the live gate
# ----------------------------------------------------------------------


def test_no_codepath_unblocks_live_gate() -> None:
    for src in (Path(worker.__file__).read_text(), Path(adapter_service.__file__).read_text()):
        for token in ["un" + "block", "enable" + "_live", "approval" + "_token"]:
            assert token not in src, f"source unexpectedly contains: {token!r}"
    assert LIVE_GATE_STATUS == "blocked_human_only"
    assert adapter_service.LIVE_GATE_STATUS == "blocked_human_only"


# ----------------------------------------------------------------------
# 23) main --status-only writes payload
# ----------------------------------------------------------------------


def test_main_status_only_writes_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    _clear_credentials(monkeypatch)
    rc = main(["--status-only"])
    assert rc == 0
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["worker_id"] == WORKER_ID
    assert written["live_gate"] == "blocked_human_only"
    assert written["blocked_call_attempts_total"] == 0
    assert written["readonly_call_attempts_total"] == 0
    assert written["credentials_present_in_env"] is False
    assert written["legacy_binance_usdm_source_paths"] == list(
        LEGACY_BINANCE_USDM_SOURCE_PATHS
    )
    assert written["legacy_readonly_rest_paths_documented_only"] == list(
        LEGACY_READONLY_REST_PATHS
    )


# ----------------------------------------------------------------------
# 24) blocked call counter increments per method
# ----------------------------------------------------------------------


@pytest.mark.parametrize("method", list(MUTATION_METHODS))
def test_blocked_call_counter_increments_per_method(method: str) -> None:
    adapter = BinanceUsdmAdapter()
    for _ in range(3):
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)(symbol="BTCUSDT")
    snapshot = adapter.state_snapshot()
    assert snapshot["blocked_call_attempts_total"] == 3
    assert snapshot["blocked_call_breakdown_by_method"][method] == 3
    for other in [m for m in MUTATION_METHODS if m != method]:
        assert snapshot["blocked_call_breakdown_by_method"][other] == 0


# ----------------------------------------------------------------------
# 25) readonly call counter increments per method
# ----------------------------------------------------------------------


@pytest.mark.parametrize("method", list(READ_ONLY_METHODS))
def test_readonly_call_counter_increments_per_method(
    method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    adapter = BinanceUsdmAdapter()
    for _ in range(3):
        getattr(adapter, method)()
    snapshot = adapter.state_snapshot()
    assert snapshot["readonly_call_attempts_total"] == 3
    assert snapshot["readonly_call_breakdown_by_method"][method] == 3
    for other in [m for m in READ_ONLY_METHODS if m != method]:
        assert snapshot["readonly_call_breakdown_by_method"][other] == 0
    # readonly calls never increment the blocked counter
    assert snapshot["blocked_call_attempts_total"] == 0


# ----------------------------------------------------------------------
# legacy_binance_usdm_source_paths listed audit-only
# ----------------------------------------------------------------------


def test_legacy_binance_usdm_source_paths_listed_audit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))
    assert status["legacy_binance_usdm_source_paths"] == list(
        LEGACY_BINANCE_USDM_SOURCE_PATHS
    )
    assert "legacy_reference/trading/base_executor.py" in status[
        "legacy_binance_usdm_source_paths"
    ]
    assert status["legacy_readonly_rest_paths_documented_only"] == list(
        LEGACY_READONLY_REST_PATHS
    )
    assert "/fapi/v3/account" in status["legacy_readonly_rest_paths_documented_only"]
    assert "/fapi/v2/positionRisk" in status["legacy_readonly_rest_paths_documented_only"]
