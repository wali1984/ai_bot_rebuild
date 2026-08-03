"""Tests for the V2 live-canary one-order enablement CLI.

Every test uses ``FakeExchangeAdapter`` — no test reaches Binance.
Codex marker files are written into per-test ``tmp_path`` so the
test never needs to touch the real workspace markers.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_live_canary_one_order_enablement as one_order_mod
from v2.backend.app.cli.v2_live_canary_one_order_enablement import (
    ALLOWED_SYMBOL,
    CODEX_DRY_RUN_BINDING_PASS_CONTENT,
    CODEX_ONE_ORDER_PASS_CONTENT,
    CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT,
    EXECUTE_OUTCOME_BLOCKED,
    EXECUTE_OUTCOME_REJECTED,
    MAX_NOTIONAL_USDT,
    MIN_NOTIONAL_USDT,
    execute_live_once,
    preflight,
)
from v2.backend.app.services.live_canary.execution_adapter import (
    FakeExchangeAdapter,
    KEY_KILL_SWITCH,
    KEY_LEDGER,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def ping(self) -> bool:
        return True


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


def _approval_body(
    *,
    canary_mode: str = "LEGACY_SIGNAL_V2_EXECUTION_CANARY",
    live_symbols: str = "BTCUSDT",
    max_notional_usdt: float = 55.0,
    max_daily_live_trades: int = 1,
    max_daily_loss_usdt: float = 5.0,
    runtime_live_gate: str = "live_canary_operator_approved",
    runtime_live_symbols: str = "BTCUSDT",
    leverage_change_approved: str = "NO",
    margin_mode_change_approved: str = "NO",
    redis_trim_approved: str = "NO",
    legacy_shutdown_approved: str = "NO",
) -> str:
    return "\n".join(
        [
            "# OPERATOR ACCEPTS V2 LIVE CANARY LIMITATIONS",
            "",
            "This is live canary only.",
            f"Legacy shutdown is not approved.",
            f"Redis trim is not approved.",
            f"Leverage change is not approved.",
            f"Margin mode change is not approved.",
            "",
            f"Approved live canary mode: {canary_mode}",
            f"Approved live symbols: {live_symbols}",
            f"Max notional USDT per order: {max_notional_usdt}",
            f"Max daily live trades: {max_daily_live_trades}",
            f"Max daily loss USDT: {max_daily_loss_usdt}",
            f"leverage_change_approved: {leverage_change_approved}",
            f"margin_mode_change_approved: {margin_mode_change_approved}",
            f"redis_trim_approved: {redis_trim_approved}",
            f"legacy_shutdown_approved: {legacy_shutdown_approved}",
            f"runtime_live_gate: {runtime_live_gate}",
            f"runtime_live_symbols: {runtime_live_symbols}",
        ]
    )


def _write_probe_status(path: Path, *, go: str, age_seconds: int = 0) -> None:
    gen = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "go_no_go": go,
                "generated_utc": gen.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "exchange_credentials_present": True,
                "account_read_permission_status": "OK",
                "exchange_info_call_status": "OK",
                "raw_credential_in_payload": "NEVER",
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def gates_dir(tmp_path: Path) -> dict[str, Path]:
    """Materialise every external dependency (approval file, probe,
    Codex markers) at fresh / READY state by default. Tests then
    selectively break individual gates."""
    paths = {
        "approval": tmp_path / "OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md",
        "probe": tmp_path / "probe" / "permission_probe_status.json",
        "codex_one_order": tmp_path / "codex" / "CODEX_GO_NO_GO.md",
        "codex_private_signed_post": tmp_path / "codex" / "BYPASS_GO_NO_GO.md",
        "codex_dry_run_binding": tmp_path / "codex" / "BINDING_GO_NO_GO.md",
    }
    paths["approval"].write_text(_approval_body(), encoding="utf-8")
    _write_probe_status(paths["probe"], go="V2_LIVE_CANARY_PERMISSION_PROBE_READY")
    paths["codex_one_order"].parent.mkdir(parents=True, exist_ok=True)
    paths["codex_one_order"].write_text(CODEX_ONE_ORDER_PASS_CONTENT + "\n", encoding="utf-8")
    paths["codex_private_signed_post"].write_text(
        CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT + "\n", encoding="utf-8"
    )
    paths["codex_dry_run_binding"].write_text(
        CODEX_DRY_RUN_BINDING_PASS_CONTENT + "\n", encoding="utf-8"
    )
    return paths


def _preflight_with(gates_dir, redis_client, **kwargs):
    return preflight(
        redis_client=redis_client,
        approval_path=gates_dir["approval"],
        permission_probe_status_path=gates_dir["probe"],
        codex_one_order_pass_marker_path=gates_dir["codex_one_order"],
        codex_private_signed_post_bypass_pass_marker_path=gates_dir["codex_private_signed_post"],
        codex_dry_run_binding_pass_marker_path=gates_dir["codex_dry_run_binding"],
        **kwargs,
    )


def _execute_with(gates_dir, redis_client, transport, **kwargs):
    return execute_live_once(
        redis_client=redis_client,
        transport=transport,
        approval_path=gates_dir["approval"],
        permission_probe_status_path=gates_dir["probe"],
        codex_one_order_pass_marker_path=gates_dir["codex_one_order"],
        codex_private_signed_post_bypass_pass_marker_path=gates_dir["codex_private_signed_post"],
        codex_dry_run_binding_pass_marker_path=gates_dir["codex_dry_run_binding"],
        codex_final_pass_marker_path=gates_dir["codex_one_order"],
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Preflight tests                                                             #
# --------------------------------------------------------------------------- #


def test_preflight_passes_with_current_approved_config(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    result = _preflight_with(gates_dir, fake_redis)
    assert result.preflight_ready is True, result.blockers
    assert result.blockers == ()
    assert result.kill_switch_armed is False
    assert result.daily_live_trade_count == 0
    assert result.codex_one_order_pass_present is True
    assert result.codex_private_signed_post_bypass_pass_present is True
    assert result.codex_dry_run_binding_pass_present is True


def test_preflight_blocks_without_codex_one_order_pass(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_one_order"].write_text("FAIL_NOT_THE_RIGHT_CONTENT\n", encoding="utf-8")
    result = _preflight_with(gates_dir, fake_redis)
    assert result.preflight_ready is False
    assert "PREFLIGHT_CODEX_ONE_ORDER_PASS_MARKER_ABSENT_OR_MISMATCH" in result.blockers


def test_preflight_blocks_when_codex_one_order_file_missing(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_one_order"].unlink()
    result = _preflight_with(gates_dir, fake_redis)
    assert "PREFLIGHT_CODEX_ONE_ORDER_PASS_MARKER_ABSENT_OR_MISMATCH" in result.blockers


def test_preflight_blocks_with_armed_kill_switch(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    fake_redis.set(KEY_KILL_SWITCH, "ARMED")
    result = _preflight_with(gates_dir, fake_redis)
    assert "PREFLIGHT_KILL_SWITCH_ARMED" in result.blockers


def test_preflight_blocks_with_daily_live_trade_count_at_limit(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake_redis.set(
        KEY_LEDGER,
        json.dumps(
            [
                {
                    "generated_utc": today_iso,
                    "one_order_enablement_invocation": True,
                    "real_order_attempted": False,
                }
            ]
        ),
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert any(
        b.startswith("PREFLIGHT_DAILY_LIVE_TRADE_COUNT_AT_OR_ABOVE_LIMIT")
        for b in result.blockers
    )


def test_preflight_blocks_with_notional_above_55(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    result = _preflight_with(gates_dir, fake_redis, candidate_notional_usdt=99.0)
    assert any(
        b.startswith("PREFLIGHT_CANDIDATE_NOTIONAL_ABOVE_CAP")
        for b in result.blockers
    )


def test_preflight_blocks_with_notional_below_exchange_min(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    result = _preflight_with(gates_dir, fake_redis, candidate_notional_usdt=10.0)
    assert any(
        b.startswith("PREFLIGHT_CANDIDATE_NOTIONAL_BELOW_EXCHANGE_MIN")
        for b in result.blockers
    )


def test_preflight_blocks_with_symbol_not_btcusdt(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    result = _preflight_with(gates_dir, fake_redis, candidate_symbol="DOGEUSDT")
    assert any(
        b.startswith("PREFLIGHT_CANDIDATE_SYMBOL_NOT_BTCUSDT")
        for b in result.blockers
    )


def test_preflight_blocks_with_stale_permission_probe(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    _write_probe_status(
        gates_dir["probe"],
        go="V2_LIVE_CANARY_PERMISSION_PROBE_READY",
        age_seconds=999_999,
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert any(
        b.startswith("PREFLIGHT_PERMISSION_PROBE_STALE")
        for b in result.blockers
    )


def test_preflight_blocks_when_runtime_live_symbols_not_exactly_btcusdt(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["approval"].write_text(
        _approval_body(runtime_live_symbols="ETHUSDT"), encoding="utf-8"
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert "PREFLIGHT_RUNTIME_LIVE_SYMBOLS_NOT_EXACTLY_BTCUSDT" in result.blockers


def test_preflight_blocks_when_leverage_change_approval_present(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    # Operator file with explicit YES + no "is not approved" sentence
    body = "\n".join(
        [
            "Approved live canary mode: LEGACY_SIGNAL_V2_EXECUTION_CANARY",
            "Approved live symbols: BTCUSDT",
            "Max notional USDT per order: 55",
            "Max daily live trades: 1",
            "Max daily loss USDT: 5",
            "leverage_change_approved: YES",
            "runtime_live_gate: live_canary_operator_approved",
            "runtime_live_symbols: BTCUSDT",
        ]
    )
    gates_dir["approval"].write_text(body, encoding="utf-8")
    result = _preflight_with(gates_dir, fake_redis)
    assert "PREFLIGHT_LEVERAGE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED" in result.blockers


def test_preflight_blocks_when_margin_change_approval_present(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    body = "\n".join(
        [
            "Approved live canary mode: LEGACY_SIGNAL_V2_EXECUTION_CANARY",
            "Approved live symbols: BTCUSDT",
            "Max notional USDT per order: 55",
            "Max daily live trades: 1",
            "Max daily loss USDT: 5",
            "margin_mode_change_approved: YES",
            "runtime_live_gate: live_canary_operator_approved",
            "runtime_live_symbols: BTCUSDT",
        ]
    )
    gates_dir["approval"].write_text(body, encoding="utf-8")
    result = _preflight_with(gates_dir, fake_redis)
    assert "PREFLIGHT_MARGIN_MODE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED" in result.blockers


# --------------------------------------------------------------------------- #
# Execute-live-once tests                                                     #
# --------------------------------------------------------------------------- #


def test_execute_live_once_blocks_without_codex_pass(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_one_order"].unlink()
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(gates_dir, fake_redis, fake_transport)
    assert result["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert result["auto_relocked"] is True
    assert result["one_order_attempt_consumed"] is False
    assert result["real_order_attempted"] is False
    assert result["real_order_submitted"] is False
    # Fake transport must not have been called at all on blocked path.
    assert fake_transport.call_count == 0


def test_execute_live_once_blocks_if_kill_switch_armed(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    fake_redis.set(KEY_KILL_SWITCH, "ARMED")
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(gates_dir, fake_redis, fake_transport)
    assert result["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert "PREFLIGHT_KILL_SWITCH_ARMED" in result["fail_blockers"]
    assert fake_transport.call_count == 0
    assert result["real_order_submitted"] is False


def test_execute_live_once_blocks_if_notional_above_cap(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(
        gates_dir, fake_redis, fake_transport, candidate_notional_usdt=99.0
    )
    assert result["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert fake_transport.call_count == 0


def test_execute_live_once_blocks_if_symbol_not_btcusdt(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(
        gates_dir, fake_redis, fake_transport, candidate_symbol="DOGEUSDT"
    )
    assert result["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert fake_transport.call_count == 0


def test_execute_live_once_blocks_if_permission_probe_stale(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    _write_probe_status(
        gates_dir["probe"],
        go="V2_LIVE_CANARY_PERMISSION_PROBE_READY",
        age_seconds=99_999,
    )
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(gates_dir, fake_redis, fake_transport)
    assert result["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert fake_transport.call_count == 0


def test_execute_live_once_fake_path_attempts_then_relocks(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    """Full happy path with FakeExchangeAdapter: preflight passes,
    adapter is invoked exactly once, status auto-relocks back to
    blocked_human_only / [], one_order_attempt_consumed=True."""
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(gates_dir, fake_redis, fake_transport)
    # Outcome is "exchange rejected or fake adapter" because fake
    # transport sets real_order_submitted=False. The execute path
    # WAS traversed (adapter was invoked).
    assert result["go_no_go"] == EXECUTE_OUTCOME_REJECTED
    assert result["auto_relocked"] is True
    assert result["one_order_attempt_consumed"] is True
    assert result["exchange_adapter_kind"] == "FakeExchangeAdapter"
    # Fake adapter received exactly one call.
    assert fake_transport.call_count == 1
    # Auto-relock results:
    assert result["live_gate_before"] == "live_canary_operator_approved"
    assert result["live_gate_after"] == "blocked_human_only"
    assert result["live_symbols_before"] == [ALLOWED_SYMBOL]
    assert result["live_symbols_after"] == []
    assert result["real_order_submitted"] is False
    assert result["real_order_attempted"] is False
    assert result["writes_exchange_orders"] is False
    assert result["writes_legacy_redis"] is False
    assert result["leverage_changed"] is False
    assert result["margin_mode_changed"] is False
    assert result["raw_credential_in_payload"] == "NEVER"


def test_no_second_attempt_after_one_order_consumed(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    """First execute_live_once writes a ledger entry tagged with
    one_order_enablement_invocation=True. The second execute_live_once
    sees the prior entry and the daily-trade-count gate fires
    in preflight."""
    fake_transport_first = FakeExchangeAdapter()
    first = _execute_with(gates_dir, fake_redis, fake_transport_first)
    assert first["one_order_attempt_consumed"] is True
    assert fake_transport_first.call_count == 1

    fake_transport_second = FakeExchangeAdapter()
    second = _execute_with(gates_dir, fake_redis, fake_transport_second)
    assert second["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert any(
        b.startswith("PREFLIGHT_DAILY_LIVE_TRADE_COUNT_AT_OR_ABOVE_LIMIT")
        for b in second["fail_blockers"]
    )
    # Crucial: second call's fake transport NEVER touched.
    assert fake_transport_second.call_count == 0
    assert second["real_order_submitted"] is False
    assert second["real_order_attempted"] is False


def test_no_old_redis_writes(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    """All redis writes must land in v2:live_canary:*. Verify by
    running through the happy path + the blocked path and listing
    what was written."""
    fake_transport = FakeExchangeAdapter()
    _execute_with(gates_dir, fake_redis, fake_transport)
    fake_redis.set(KEY_KILL_SWITCH, "ARMED")
    _execute_with(gates_dir, fake_redis, fake_transport)
    forbidden_prefixes = (
        "order_intent:",
        "order_execution:",
        "trader:positions",
        "trainer_state:",
        "live_kill_switch",
    )
    for key in fake_redis.store.keys():
        assert key.startswith("v2:live_canary:"), key
        for fp in forbidden_prefixes:
            assert fp not in key, key


def test_no_raw_credential_serialization(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    """The CLI's status/dashboard payloads must never serialize a
    real credential value. We sanity-check by injecting a synthetic
    credential-looking string in env and verifying it does not
    leak into the result dict."""
    super_secret = "sk-NEVER-LEAK-1234567890abcdef-CANARY-PROBE-TEST"
    import os as _os

    saved_key = _os.environ.get("BINANCE_API_KEY")
    saved_sec = _os.environ.get("BINANCE_API_SECRET")
    _os.environ["BINANCE_API_KEY"] = super_secret
    _os.environ["BINANCE_API_SECRET"] = super_secret
    try:
        fake_transport = FakeExchangeAdapter()
        result = _execute_with(gates_dir, fake_redis, fake_transport)
    finally:
        if saved_key is None:
            _os.environ.pop("BINANCE_API_KEY", None)
        else:
            _os.environ["BINANCE_API_KEY"] = saved_key
        if saved_sec is None:
            _os.environ.pop("BINANCE_API_SECRET", None)
        else:
            _os.environ["BINANCE_API_SECRET"] = saved_sec
    flat = json.dumps(result)
    assert super_secret not in flat
    assert result["raw_credential_in_payload"] == "NEVER"


def test_preflight_payload_pins_all_safety_invariants_when_blocked(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_one_order"].unlink()
    result = _preflight_with(gates_dir, fake_redis)
    payload = result.as_payload()
    assert payload["preflight_ready"] is False
    assert payload["max_daily_live_trades_cap"] == 1
    assert payload["max_notional_usdt_cap"] == 55.0
    assert payload["min_notional_usdt_floor"] == 50.0
    assert payload["allowed_symbol_only"] == "BTCUSDT"


def test_relock_payload_safety_invariants(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(gates_dir, fake_redis, fake_transport)
    # Auto-relocked status written to v2:live_canary:status.
    status_raw = fake_redis.get("v2:live_canary:status")
    assert status_raw is not None
    relock = json.loads(status_raw)
    assert relock["live_gate"] == "blocked_human_only"
    assert relock["live_symbols"] == []
    assert relock["leverage_changed"] is False
    assert relock["margin_mode_changed"] is False
    assert relock["writes_legacy_redis"] is False
    assert relock["approves_live"] is False
    assert relock["approves_canary"] is False
    assert relock["approves_legacy_shutdown"] is False
    assert relock["approves_redis_trim"] is False
    assert relock["raw_credential_in_payload"] == "NEVER"
    assert relock["auto_relocked"] is True
    assert relock["one_order_attempt_consumed"] is True


# --------------------------------------------------------------------------- #
# Codex marker enforcement regression tests                                   #
# (would have caught the FAIL surfaced in                                     #
#  v2_live_canary_one_order_enablement CODEX_REVIEW.md)                       #
# --------------------------------------------------------------------------- #


_PRIVATE_SIGNED_POST_READY_STRING = (
    "V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_READY"
)
_DRY_RUN_BINDING_READY_STRING = (
    "V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_READY"
)


def test_private_signed_post_implementation_ready_marker_does_not_satisfy_codex_prerequisite(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_private_signed_post"].write_text(
        _PRIVATE_SIGNED_POST_READY_STRING + "\n", encoding="utf-8"
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert result.codex_private_signed_post_bypass_pass_present is False
    assert (
        "PREFLIGHT_CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_ABSENT_OR_MISMATCH"
        in result.blockers
    )
    payload = result.as_payload()
    assert payload["prerequisite_private_signed_post_codex_marker_passed"] is False
    assert (
        payload["prerequisite_private_signed_post_codex_marker_actual"]
        == _PRIVATE_SIGNED_POST_READY_STRING
    )
    assert (
        payload["prerequisite_private_signed_post_codex_marker_expected"]
        == CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT
    )
    assert (
        payload["implementation_ready_markers_accepted_for_codex_prerequisites"]
        is False
    )


def test_dry_run_binding_implementation_ready_marker_does_not_satisfy_codex_prerequisite(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_dry_run_binding"].write_text(
        _DRY_RUN_BINDING_READY_STRING + "\n", encoding="utf-8"
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert result.codex_dry_run_binding_pass_present is False
    assert (
        "PREFLIGHT_CODEX_DRY_RUN_BINDING_PASS_MARKER_ABSENT_OR_MISMATCH"
        in result.blockers
    )
    payload = result.as_payload()
    assert payload["prerequisite_dry_run_binding_codex_marker_passed"] is False
    assert (
        payload["prerequisite_dry_run_binding_codex_marker_actual"]
        == _DRY_RUN_BINDING_READY_STRING
    )
    assert (
        payload["prerequisite_dry_run_binding_codex_marker_expected"]
        == CODEX_DRY_RUN_BINDING_PASS_CONTENT
    )


def test_private_signed_post_codex_pass_marker_required_exactly(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    # Substring/prefix should not satisfy.
    gates_dir["codex_private_signed_post"].write_text(
        CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT + "_EXTRA\n", encoding="utf-8"
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert result.codex_private_signed_post_bypass_pass_present is False


def test_dry_run_binding_codex_pass_marker_required_exactly(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    gates_dir["codex_dry_run_binding"].write_text(
        CODEX_DRY_RUN_BINDING_PASS_CONTENT + "_EXTRA\n", encoding="utf-8"
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert result.codex_dry_run_binding_pass_present is False


def test_preflight_blocks_when_prerequisite_files_contain_ready_strings_only(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    # Both implementation-side ``*_READY`` strings on disk simultaneously.
    gates_dir["codex_private_signed_post"].write_text(
        _PRIVATE_SIGNED_POST_READY_STRING + "\n", encoding="utf-8"
    )
    gates_dir["codex_dry_run_binding"].write_text(
        _DRY_RUN_BINDING_READY_STRING + "\n", encoding="utf-8"
    )
    result = _preflight_with(gates_dir, fake_redis)
    assert result.preflight_ready is False
    assert (
        "PREFLIGHT_CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_ABSENT_OR_MISMATCH"
        in result.blockers
    )
    assert (
        "PREFLIGHT_CODEX_DRY_RUN_BINDING_PASS_MARKER_ABSENT_OR_MISMATCH"
        in result.blockers
    )


def test_preflight_passes_prerequisites_when_exact_codex_pass_files_exist(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    # Default fixture already writes the exact CODEX_PASS tokens.
    result = _preflight_with(gates_dir, fake_redis)
    assert result.codex_private_signed_post_bypass_pass_present is True
    assert result.codex_dry_run_binding_pass_present is True
    assert result.codex_one_order_pass_present is True
    payload = result.as_payload()
    assert payload["prerequisite_private_signed_post_codex_marker_passed"] is True
    assert payload["prerequisite_dry_run_binding_codex_marker_passed"] is True
    assert payload["prerequisite_one_order_codex_marker_passed"] is True


def test_one_order_execution_still_blocks_without_one_order_codex_pass_marker(
    gates_dir: dict[str, Path], fake_redis: _FakeRedis
) -> None:
    # Even when both prerequisite Codex PASS markers are valid, the
    # one-order CODEX_PASS marker is still required.
    gates_dir["codex_one_order"].write_text(
        "V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_READY_PENDING_CODEX\n",
        encoding="utf-8",
    )
    fake_transport = FakeExchangeAdapter()
    result = _execute_with(gates_dir, fake_redis, fake_transport)
    assert result["go_no_go"] == EXECUTE_OUTCOME_BLOCKED
    assert (
        "PREFLIGHT_CODEX_ONE_ORDER_PASS_MARKER_ABSENT_OR_MISMATCH"
        in result["fail_blockers"]
    )
    assert fake_transport.call_count == 0
    assert result["real_order_attempted"] is False
    assert result["real_order_submitted"] is False


def test_module_default_marker_paths_point_at_codex_review_files() -> None:
    """Defence in depth: the module-level default paths must point at
    ``codex_review/CODEX_GO_NO_GO.md`` files for both prerequisites,
    not the implementation ``latest/GO_NO_GO.md`` files."""
    expected_priv = (
        "claude_worklog/final_readiness/"
        "v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/"
        "latest/codex_review/CODEX_GO_NO_GO.md"
    )
    expected_dry = (
        "claude_worklog/final_readiness/"
        "v2_live_canary_dry_run_approval_binding_remediation/"
        "latest/codex_review/CODEX_GO_NO_GO.md"
    )
    assert (
        str(one_order_mod.CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_PATH)
        == expected_priv
    )
    assert (
        str(one_order_mod.CODEX_DRY_RUN_BINDING_PASS_MARKER_PATH) == expected_dry
    )
    # Token contents are the CODEX_PASS strings, not the READY strings.
    assert (
        one_order_mod.CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_CONTENT
        == "V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_CODEX_PASS"
    )
    assert (
        one_order_mod.CODEX_DRY_RUN_BINDING_PASS_CONTENT
        == "V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_CODEX_PASS"
    )
