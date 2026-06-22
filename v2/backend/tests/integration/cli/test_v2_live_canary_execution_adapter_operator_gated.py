"""Operator-gated execution-adapter tests for V2 live-canary.

Tests prove every one of the 14 operator-final gate conditions
fails closed. The default-constructed adapter cannot reach a real
exchange call from any code path: the configured exchange adapter
defaults to ``FakeExchangeAdapter``, which has no network surface,
and ``submit_canary_order`` requires ALL gates to clear before it
even passes the intent to the configured adapter.

These tests NEVER construct ``BinanceFuturesExchangeAdapter``.
They NEVER hit a real Binance endpoint. They use a fake exchange
adapter that records intents and explicit blocker assertions.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.live_canary import execution_adapter as adapter_mod
from v2.backend.app.services.live_canary.execution_adapter import (
    ALLOWED_REDIS_KEYS,
    ApprovalEnvelope,
    BinanceFuturesExchangeAdapter,
    DailyCounters,
    FakeExchangeAdapter,
    IntentCandidate,
    LiveCanaryExecutionAdapter,
    PermissionProbeFreshness,
    parse_approval_file,
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


@pytest.fixture
def tmp_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "approval": tmp_path / "approvals" / "OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md",
        "codex_marker": tmp_path / "codex_review" / "CODEX_LIVE_CANARY_PASS.marker",
        "codex_final_marker": tmp_path / "codex_review" / "CODEX_FINAL_LIVE_CANARY_PASS.marker",
        "probe_status": tmp_path / "probe_status.json",
    }


def _write_codex_marker(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("codex-pass\n", encoding="utf-8")


def _write_fresh_probe_status(path: Path, *, go: str = "V2_LIVE_CANARY_PERMISSION_PROBE_READY", age_seconds: int = 0) -> None:
    gen = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "go_no_go": go,
                "generated_utc": gen.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "exchange_credentials_present": True,
                "raw_credential_in_payload": "NEVER",
            }
        ),
        encoding="utf-8",
    )


def _all_gates_passing_approval() -> ApprovalEnvelope:
    return ApprovalEnvelope(
        approval_file_present=True,
        canary_mode_selected="V2_NATIVE_SIGNAL_CANARY",
        allowed_symbols=("BTCUSDT",),
        max_notional_usdt=20.0,
        max_daily_live_trades=3,
        max_daily_loss_usdt=10.0,
        leverage_change_approved=False,
        margin_mode_change_approved=False,
        redis_trim_approved=False,
        legacy_shutdown_approved=False,
        runtime_live_gate_requested="live_canary_operator_approved",
        runtime_live_symbols_requested=("BTCUSDT",),
    )


def _candidate() -> IntentCandidate:
    return IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        requested_quantity=0.001,
        signal_source="V2_NATIVE_SIGNAL_CANARY",
        expected_move_after_cost_bps=15.0,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )


def _build_adapter_with_all_gates_passing(
    fake_redis: _FakeRedis,
    tmp_paths: dict[str, Path],
    *,
    approval: ApprovalEnvelope | None = None,
    exchange_adapter: Any | None = None,
    dry_run: bool = False,
    live_enabled: bool = True,
) -> LiveCanaryExecutionAdapter:
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    return LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval or _all_gates_passing_approval(),
        exchange_adapter=exchange_adapter or FakeExchangeAdapter(),
        codex_final_pass_marker_path=tmp_paths["codex_final_marker"],
        permission_probe_status_path=tmp_paths["probe_status"],
        dry_run=dry_run,
        live_enabled=live_enabled,
    )


# --------------------------------------------------------------------------- #
# Default-construction safety                                                 #
# --------------------------------------------------------------------------- #


def test_default_adapter_uses_fake_exchange(fake_redis: _FakeRedis) -> None:
    adapter = LiveCanaryExecutionAdapter(redis_client=fake_redis)
    assert isinstance(adapter.exchange_adapter, FakeExchangeAdapter)
    assert adapter.dry_run is True
    assert adapter.live_enabled is False


def test_default_adapter_submit_returns_blocked_without_panicking(
    fake_redis: _FakeRedis,
) -> None:
    adapter = LiveCanaryExecutionAdapter(redis_client=fake_redis)
    result = adapter.submit_canary_order(candidate=_candidate(), cycle_id="t1")
    assert result["go_no_go"] == "BLOCKED_REAL_ORDER_REFUSED"
    assert result["fail_blockers"]
    assert result["real_order_submitted"] is False
    assert result["real_order_attempted"] is False
    assert result["places_real_order"] is False
    assert result["writes_exchange_orders"] is False
    assert result["writes_legacy_redis"] is False
    assert result["leverage_changed"] is False
    assert result["margin_mode_changed"] is False
    assert result["live_gate"] == "blocked_human_only"
    assert result["live_symbols"] == []


def test_legacy_alias_submit_live_canary_order_does_not_raise(
    fake_redis: _FakeRedis,
) -> None:
    """The old method name now returns a result dict instead of raising
    NotImplementedError. The behaviour is identical to
    submit_canary_order."""
    adapter = LiveCanaryExecutionAdapter(redis_client=fake_redis)
    result = adapter.submit_live_canary_order(candidate=_candidate(), cycle_id="t1")
    assert result["go_no_go"] == "BLOCKED_REAL_ORDER_REFUSED"
    assert result["real_order_submitted"] is False


# --------------------------------------------------------------------------- #
# Per-gate fail-closed tests                                                  #
# --------------------------------------------------------------------------- #


def test_gate_1_blocks_when_operator_approval_file_absent(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = _all_gates_passing_approval()
    approval = dataclasses_replace(approval, approval_file_present=False)
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_1_OPERATOR_APPROVAL_FILE_ABSENT" in blockers


def test_gate_2_blocks_when_codex_final_marker_absent(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    _write_fresh_probe_status(tmp_paths["probe_status"])
    # codex_final_marker intentionally not written
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=_all_gates_passing_approval(),
        exchange_adapter=FakeExchangeAdapter(),
        codex_final_pass_marker_path=tmp_paths["codex_final_marker"],
        permission_probe_status_path=tmp_paths["probe_status"],
        dry_run=False,
        live_enabled=True,
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT" in blockers


def test_gate_3_blocks_when_permission_probe_absent(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    _write_codex_marker(tmp_paths["codex_final_marker"])
    # probe status intentionally not written
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=_all_gates_passing_approval(),
        exchange_adapter=FakeExchangeAdapter(),
        codex_final_pass_marker_path=tmp_paths["codex_final_marker"],
        permission_probe_status_path=tmp_paths["probe_status"],
        dry_run=False,
        live_enabled=True,
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_3_PERMISSION_PROBE_PASS_NOT_PRESENT" in blockers


def test_gate_3_blocks_when_permission_probe_stale(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"], age_seconds=3600)
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=_all_gates_passing_approval(),
        exchange_adapter=FakeExchangeAdapter(),
        codex_final_pass_marker_path=tmp_paths["codex_final_marker"],
        permission_probe_status_path=tmp_paths["probe_status"],
        permission_probe_freshness_max_seconds=600,
        dry_run=False,
        live_enabled=True,
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert any(b.startswith("GATE_3_PERMISSION_PROBE_STALE") for b in blockers)


def test_gate_4_blocks_when_canary_mode_not_selected(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = dataclasses_replace(
        _all_gates_passing_approval(), canary_mode_selected="BLOCKED_UNSELECTED"
    )
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_4_CANARY_MODE_NOT_SELECTED_OR_INVALID" in blockers


def test_gate_5_blocks_when_symbol_whitelist_empty(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = dataclasses_replace(
        _all_gates_passing_approval(),
        allowed_symbols=tuple(),
        runtime_live_symbols_requested=tuple(),
    )
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_5_APPROVED_SYMBOL_WHITELIST_EMPTY" in blockers


def test_gate_6_blocks_when_candidate_symbol_not_in_whitelist(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    candidate = IntentCandidate(
        symbol="DOGEUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        requested_quantity=0.001,
    )
    blockers = adapter.evaluate_real_order_blockers(candidate)
    assert "GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST" in blockers


def test_gate_7_blocks_when_max_notional_cap_missing(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = dataclasses_replace(
        _all_gates_passing_approval(), max_notional_usdt=None
    )
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_7_MAX_NOTIONAL_CAP_MISSING_OR_NONPOSITIVE" in blockers


def test_gate_7_blocks_when_max_notional_cap_zero(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = dataclasses_replace(
        _all_gates_passing_approval(), max_notional_usdt=0.0
    )
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_7_MAX_NOTIONAL_CAP_MISSING_OR_NONPOSITIVE" in blockers


def test_gate_8_blocks_when_requested_notional_above_cap(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    candidate = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=99.0,  # cap is 20.0
        requested_quantity=0.001,
    )
    blockers = adapter.evaluate_real_order_blockers(candidate)
    assert "GATE_8_REQUESTED_NOTIONAL_ABOVE_CAP" in blockers


def test_gate_9_blocks_when_daily_trade_count_at_limit(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    adapter._daily.live_trades_today = 3  # equals max=3
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_9_DAILY_TRADE_COUNT_AT_OR_ABOVE_LIMIT" in blockers


def test_gate_10_blocks_when_daily_loss_at_limit(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    adapter._daily.realized_loss_usdt_today = 10.0  # equals max=10
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_10_DAILY_LOSS_AT_OR_ABOVE_LIMIT" in blockers


def test_gate_11_blocks_when_kill_switch_armed(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    fake_redis.set(adapter_mod.KEY_KILL_SWITCH, "ARMED")
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_11_KILL_SWITCH_ARMED" in blockers


def test_gate_12_blocks_when_live_enabled_false(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, live_enabled=False, dry_run=False
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_12_LIVE_ENABLED_FALSE" in blockers


def test_gate_12_blocks_when_dry_run_true(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, dry_run=True, live_enabled=True
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER" in blockers


def test_gate_13_blocks_when_runtime_live_gate_not_operator_approved(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = dataclasses_replace(
        _all_gates_passing_approval(),
        runtime_live_gate_requested="blocked_human_only",
    )
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_13_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED" in blockers


def test_gate_13_blocks_when_runtime_live_symbols_differ_from_approved(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    approval = dataclasses_replace(
        _all_gates_passing_approval(),
        runtime_live_symbols_requested=("ETHUSDT",),  # differs from allowed BTCUSDT
    )
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert "GATE_13_RUNTIME_LIVE_SYMBOLS_NOT_EQUAL_APPROVED_SYMBOLS" in blockers


@pytest.mark.parametrize(
    "field",
    [
        "leverage_change_approved",
        "margin_mode_change_approved",
        "redis_trim_approved",
        "legacy_shutdown_approved",
    ],
)
def test_gate_14_blocks_when_mutation_approval_present(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path], field: str
) -> None:
    overrides: dict[str, Any] = {field: True}
    approval = dataclasses_replace(_all_gates_passing_approval(), **overrides)
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, approval=approval
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    matching = [b for b in blockers if b.startswith("GATE_14_")]
    assert matching, blockers


# --------------------------------------------------------------------------- #
# Happy-path tests with fake adapter (never reaches real network)             #
# --------------------------------------------------------------------------- #


def test_all_gates_clear_uses_fake_adapter_when_real_not_supplied(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    """Even when every gate clears, the default fake adapter must
    still be used and no real network call must occur."""
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    assert isinstance(adapter.exchange_adapter, FakeExchangeAdapter)
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert blockers == [], blockers
    result = adapter.submit_canary_order(candidate=_candidate(), cycle_id="t1")
    assert result["fail_blockers"] == []
    # Fake adapter never submits a real order
    assert result["real_order_submitted"] is False
    assert result["real_order_attempted"] is False
    assert result["places_real_order"] is False
    assert result["writes_exchange_orders"] is False
    assert result["writes_legacy_redis"] is False
    assert result["go_no_go"] == "EXCHANGE_REJECTED_OR_FAKE_ADAPTER"
    assert adapter.exchange_adapter.call_count == 1
    # The fake transport receives a GateDecision (not a raw intent dict).
    # No caller-supplied boolean field is part of the contract.
    assert len(adapter.exchange_adapter.submit_calls) == 1
    decision = adapter.exchange_adapter.submit_calls[0]
    from v2.backend.app.services.live_canary.execution_adapter import GateDecision
    assert isinstance(decision, GateDecision)


# --------------------------------------------------------------------------- #
# Real-adapter construction guards                                            #
# --------------------------------------------------------------------------- #


def test_real_adapter_requires_credentials() -> None:
    with pytest.raises(ValueError) as e:
        BinanceFuturesExchangeAdapter("", "")
    assert "BINANCE_FUTURES_EXCHANGE_ADAPTER_REQUIRES_CREDENTIALS" in str(e.value)
    with pytest.raises(ValueError):
        BinanceFuturesExchangeAdapter("k", "")


def test_real_adapter_refuses_non_gate_decision_payload() -> None:
    """The real adapter must refuse anything that is not a
    GateDecision instance — no caller-supplied dict can authorize
    a real order."""
    adapter = BinanceFuturesExchangeAdapter("test-key", "test-secret")
    response = adapter.submit_signed_canary_order(
        gate_decision={"symbol": "BTCUSDT", "side": "BUY", "requested_quantity": 0.001}
    )
    assert response["real_order_submitted"] is False
    assert response["real_order_attempted"] is False
    assert response["places_real_order"] is False
    assert response["writes_exchange_orders"] is False
    assert "REJECTED_NON_GATE_DECISION_OBJECT" in response["fail_blockers"]


def test_real_adapter_endpoint_is_documented_new_order_path_only() -> None:
    """Asserts the only exchange path is /fapi/v1/order. No cancel,
    modify, leverage, or margin path is exposed by the class."""
    assert BinanceFuturesExchangeAdapter.NEW_ORDER_PATH == "/fapi/v1/order"
    public_methods = [
        name for name in vars(BinanceFuturesExchangeAdapter) if not name.startswith("_")
    ]
    # Only `submit_signed_canary_order` plus class-level constants.
    # No cancel/modify/leverage/margin methods exist.
    method_names = [
        name for name in public_methods
        if callable(getattr(BinanceFuturesExchangeAdapter, name))
    ]
    assert method_names == ["submit_signed_canary_order"], method_names


def test_real_adapter_class_has_no_leverage_or_margin_method() -> None:
    """Static check: the real adapter class must not expose any
    method whose name implies leverage or margin mutation."""
    forbidden_substrings = ("leverage", "margin", "cancel", "modify")
    members = dir(BinanceFuturesExchangeAdapter)
    for name in members:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), (
                f"BinanceFuturesExchangeAdapter must not expose any "
                f"member containing '{forbidden}' — found {name}"
            )


# --------------------------------------------------------------------------- #
# Redis-write boundary                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key",
    [
        "v2:paper:positions",
        "v2:paper:shadow_observations",
        "order_intent:BTCUSDT",
        "trader:positions",
        "v2:live_canary:foo_unknown",  # not in allowlist
    ],
)
def test_safe_redis_set_refuses_any_key_outside_allowlist(
    fake_redis: _FakeRedis, key: str
) -> None:
    assert adapter_mod._safe_redis_set(fake_redis, key, "{}", ex=60) is False


@pytest.mark.parametrize("key", list(ALLOWED_REDIS_KEYS))
def test_safe_redis_set_allows_each_allowlisted_key(
    fake_redis: _FakeRedis, key: str
) -> None:
    assert adapter_mod._safe_redis_set(fake_redis, key, "{}", ex=60) is True


def test_safe_redis_set_refuses_when_redis_none() -> None:
    assert adapter_mod._safe_redis_set(None, adapter_mod.KEY_INTENTS, "{}", ex=60) is False


# --------------------------------------------------------------------------- #
# Payload safety                                                              #
# --------------------------------------------------------------------------- #


def test_intent_record_never_contains_raw_credentials(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    """Even with a real adapter constructed via fake credentials,
    the intent record must not contain raw credentials."""
    super_secret = "sk-fakekey-must-never-appear-1234567890abcdef"
    real_adapter = BinanceFuturesExchangeAdapter(super_secret, super_secret)
    adapter = _build_adapter_with_all_gates_passing(
        fake_redis, tmp_paths, exchange_adapter=real_adapter
    )
    intent = adapter.build_intent_record(candidate=_candidate(), cycle_id="t1")
    flat = json.dumps(intent)
    assert super_secret not in flat


def test_intent_record_pins_safety_invariants(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    adapter = _build_adapter_with_all_gates_passing(fake_redis, tmp_paths)
    intent = adapter.build_intent_record(candidate=_candidate(), cycle_id="t1")
    assert intent["real_order_submitted"] is False
    assert intent["real_order_attempted"] is False
    assert intent["places_real_order"] is False
    assert intent["writes_exchange_orders"] is False
    assert intent["writes_legacy_redis"] is False
    assert intent["leverage_changed"] is False
    assert intent["margin_mode_changed"] is False
    assert intent["approves_live"] is False
    assert intent["approves_canary"] is False
    assert intent["approves_legacy_shutdown"] is False
    assert intent["approves_redis_trim"] is False
    assert intent["live_gate"] == "blocked_human_only"
    assert intent["live_symbols"] == []
    # Direct-call bypass remediation: no caller-supplied boolean
    # field exists on the intent. The transport re-validates from
    # current state at submission time instead.
    assert "canary_signed_by_executor_gate_cascade" not in intent
    assert intent["direct_call_bypass_remediated"] is True
    assert intent["caller_supplied_gate_boolean_accepted"] is False
    assert intent["final_submit_rechecks_all_gates"] is True


# --------------------------------------------------------------------------- #
# Approval file parser                                                        #
# --------------------------------------------------------------------------- #


def test_parse_approval_file_reads_runtime_live_gate_and_symbols(
    tmp_path: Path,
) -> None:
    p = tmp_path / "approval.md"
    p.write_text(
        "\n".join(
            [
                "canary_mode: V2_NATIVE_SIGNAL_CANARY",
                "live_symbols: BTCUSDT,ETHUSDT",
                "max_notional_usdt: 20",
                "max_daily_live_trades: 3",
                "max_daily_loss_usdt: 10",
                "leverage_change_approved: NO",
                "margin_mode_change_approved: NO",
                "redis_trim_approved: NO",
                "legacy_shutdown_approved: NO",
                "runtime_live_gate: live_canary_operator_approved",
                "runtime_live_symbols: BTCUSDT,ETHUSDT",
            ]
        ),
        encoding="utf-8",
    )
    approval = parse_approval_file(p)
    assert approval.approval_file_present is True
    assert approval.runtime_live_gate_requested == "live_canary_operator_approved"
    assert approval.runtime_live_symbols_requested == ("BTCUSDT", "ETHUSDT")
    assert approval.allowed_symbols == ("BTCUSDT", "ETHUSDT")
    assert approval.leverage_change_approved is False


def test_parse_approval_file_runtime_gate_strict_default_blocked(
    tmp_path: Path,
) -> None:
    p = tmp_path / "approval.md"
    p.write_text(
        "\n".join(
            [
                "canary_mode: V2_NATIVE_SIGNAL_CANARY",
                "live_symbols: BTCUSDT",
                "runtime_live_gate: yolo_full_speed_ahead",  # not the literal we accept
                "runtime_live_symbols: BTCUSDT",
            ]
        ),
        encoding="utf-8",
    )
    approval = parse_approval_file(p)
    assert approval.runtime_live_gate_requested == "blocked_human_only"


def test_parse_approval_file_accepts_operator_prose_format(tmp_path: Path) -> None:
    """The operator's natural-language approval template
    (``Approved live canary mode: ...``, ``Max notional USDT per
    order: ...``, ``live_gate target for canary only: ...``) must
    parse to a fully populated ApprovalEnvelope so the dry-run
    executor binds correctly."""
    p = tmp_path / "OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md"
    p.write_text(
        "\n".join(
            [
                "# OPERATOR ACCEPTS V2 LIVE CANARY LIMITATIONS",
                "",
                "This is live canary only.",
                "Legacy shutdown is not approved.",
                "Redis trim is not approved.",
                "Leverage change is not approved.",
                "Margin mode change is not approved.",
                "",
                "Approved live canary mode: LEGACY_SIGNAL_V2_EXECUTION_CANARY",
                "Approved live symbols: BTCUSDT",
                "Max notional USDT per order: 55",
                "Max daily live trades: 1",
                "Max daily loss USDT: 5",
                "",
                "Emergency kill switch is required.",
                "",
                "live_gate target for canary only: live_canary_operator_approved",
                "live_symbols target for canary only: [BTCUSDT]",
            ]
        ),
        encoding="utf-8",
    )
    approval = parse_approval_file(p)
    assert approval.approval_file_present is True
    assert approval.canary_mode_selected == "LEGACY_SIGNAL_V2_EXECUTION_CANARY"
    assert approval.allowed_symbols == ("BTCUSDT",)
    assert approval.max_notional_usdt == 55.0
    assert approval.max_daily_live_trades == 1
    assert approval.max_daily_loss_usdt == 5.0
    # All four mutation flags must remain False because the operator
    # wrote "is not approved" sentences for each of them.
    assert approval.leverage_change_approved is False
    assert approval.margin_mode_change_approved is False
    assert approval.redis_trim_approved is False
    assert approval.legacy_shutdown_approved is False
    # Runtime live gate / symbols parsed from the operator's prose form.
    assert approval.runtime_live_gate_requested == "live_canary_operator_approved"
    assert approval.runtime_live_symbols_requested == ("BTCUSDT",)


def test_prose_deny_overrides_explicit_yes_for_mutation_flags(tmp_path: Path) -> None:
    """If the operator writes both a prose deny line ("Leverage
    change is not approved.") and a contradictory explicit YES line
    ("leverage_change_approved: YES"), the prose deny WINS. This
    prevents accidental drift from a stray edit."""
    p = tmp_path / "approval.md"
    p.write_text(
        "\n".join(
            [
                "Leverage change is not approved.",
                "leverage_change_approved: YES",
                "Margin mode change is not approved.",
                "margin_mode_change_approved: YES",
                "Redis trim is not approved.",
                "redis_trim_approved: TRUE",
                "Legacy shutdown is not approved.",
                "legacy_shutdown_approved: 1",
                "canary_mode: V2_NATIVE_SIGNAL_CANARY",
                "live_symbols: BTCUSDT",
            ]
        ),
        encoding="utf-8",
    )
    approval = parse_approval_file(p)
    assert approval.leverage_change_approved is False
    assert approval.margin_mode_change_approved is False
    assert approval.redis_trim_approved is False
    assert approval.legacy_shutdown_approved is False


def test_prose_format_with_no_runtime_live_gate_defaults_to_blocked(
    tmp_path: Path,
) -> None:
    """When the operator's file declares mode + symbols but omits
    runtime_live_gate, the envelope still pins runtime_live_gate to
    blocked_human_only so the 14-gate cascade fails closed on GATE_13."""
    p = tmp_path / "approval.md"
    p.write_text(
        "\n".join(
            [
                "Approved live canary mode: LEGACY_SIGNAL_V2_EXECUTION_CANARY",
                "Approved live symbols: BTCUSDT",
                "Max notional USDT per order: 55",
                "Max daily live trades: 1",
                "Max daily loss USDT: 5",
            ]
        ),
        encoding="utf-8",
    )
    approval = parse_approval_file(p)
    assert approval.runtime_live_gate_requested == "blocked_human_only"
    assert approval.runtime_live_symbols_requested == tuple()


# --------------------------------------------------------------------------- #
# PermissionProbeFreshness                                                    #
# --------------------------------------------------------------------------- #


def test_permission_probe_freshness_from_path_when_absent(
    tmp_path: Path,
) -> None:
    f = PermissionProbeFreshness.from_path(tmp_path / "missing.json")
    assert f.pass_present is False
    assert f.fresh is False
    assert f.age_seconds == float("inf")
    assert f.go_no_go is None


def test_permission_probe_freshness_from_path_when_fresh_and_ready(
    tmp_path: Path,
) -> None:
    p = tmp_path / "probe.json"
    _write_fresh_probe_status(p)
    f = PermissionProbeFreshness.from_path(p, max_age_seconds=600)
    assert f.pass_present is True
    assert f.fresh is True


def test_permission_probe_freshness_from_path_when_stale(
    tmp_path: Path,
) -> None:
    p = tmp_path / "probe.json"
    _write_fresh_probe_status(p, age_seconds=99999)
    f = PermissionProbeFreshness.from_path(p, max_age_seconds=600)
    assert f.pass_present is True
    assert f.fresh is False


def test_permission_probe_freshness_from_path_when_not_ready(
    tmp_path: Path,
) -> None:
    p = tmp_path / "probe.json"
    _write_fresh_probe_status(p, go="V2_LIVE_CANARY_PERMISSION_PROBE_BLOCKED")
    f = PermissionProbeFreshness.from_path(p, max_age_seconds=600)
    assert f.pass_present is False


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def dataclasses_replace(obj: Any, **changes: Any) -> Any:
    import dataclasses

    return dataclasses.replace(obj, **changes)


# --------------------------------------------------------------------------- #
# Codex-regression suite: direct-call bypass cannot reach the network.        #
#                                                                             #
# These tests monkeypatch ``urllib.request.urlopen`` to fail loudly if        #
# called. They then exercise multiple direct-call attack paths against        #
# BinanceFuturesExchangeAdapter.submit_signed_canary_order and verify         #
# that NONE of them result in a urlopen invocation.                           #
# --------------------------------------------------------------------------- #


import urllib.request as _urllib_request

from v2.backend.app.services.live_canary.execution_adapter import (
    _MODULE_GATE_TOKEN,
    _create_gate_decision,
    GateDecision,
)


@pytest.fixture
def urlopen_spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace urllib.request.urlopen with a spy that records every
    call. The spy raises so the test fails loudly if the production
    code ever reaches it."""
    calls: list[Any] = []

    def _spy(*args: Any, **kwargs: Any):
        calls.append({"args": args, "kwargs": kwargs})
        raise RuntimeError(
            "TEST_REGRESSION: urlopen was reached; direct-call bypass not prevented"
        )

    monkeypatch.setattr(_urllib_request, "urlopen", _spy)
    return calls


def _make_decision_with_token(
    candidate: IntentCandidate,
    tmp_paths: dict[str, Path],
    *,
    redis_client: Any = None,
    daily_counters: DailyCounters | None = None,
    dry_run: bool = False,
    live_enabled: bool = True,
    token: str | None = None,
) -> GateDecision:
    return GateDecision(
        candidate=candidate,
        approval_file_path=tmp_paths.get("approval", Path("/nonexistent/approval.md")),
        codex_final_pass_marker_path=tmp_paths.get(
            "codex_final_marker", Path("/nonexistent/codex_final.marker")
        ),
        permission_probe_status_path=tmp_paths.get(
            "probe_status", Path("/nonexistent/probe_status.json")
        ),
        kill_switch_redis_client=redis_client,
        daily_counters=daily_counters or DailyCounters(),
        dry_run=dry_run,
        live_enabled=live_enabled,
        _token=token if token is not None else _MODULE_GATE_TOKEN,
    )


def test_real_exchange_adapter_direct_call_cannot_bypass_gate_cascade(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """Codex regression: importing BinanceFuturesExchangeAdapter and
    calling submit_signed_canary_order directly with a forged
    GateDecision token causes zero urlopen calls. The earlier
    attack (caller-supplied boolean) is no longer reachable —
    there is no boolean field on the contract any more."""
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    # 1) Direct call with a non-GateDecision argument
    r1 = transport.submit_signed_canary_order(
        gate_decision={"forged": True, "canary_signed_by_executor_gate_cascade": True}
    )
    assert r1["real_order_submitted"] is False
    assert r1["real_order_attempted"] is False
    assert r1["places_real_order"] is False
    assert "REJECTED_NON_GATE_DECISION_OBJECT" in r1["fail_blockers"]
    # 2) Direct call with a correctly-typed but forged-token GateDecision
    forged = _make_decision_with_token(
        _candidate(), tmp_paths, token="forged-token-not-real"
    )
    r2 = transport.submit_signed_canary_order(gate_decision=forged)
    assert r2["real_order_submitted"] is False
    assert r2["real_order_attempted"] is False
    assert r2["places_real_order"] is False
    assert "REJECTED_FORGED_GATE_DECISION_TOKEN" in r2["fail_blockers"]
    # NEVER reached urlopen
    assert urlopen_spy == []


def test_direct_call_no_approval_file_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    # No approval file written; codex marker and probe also missing.
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    assert "GATE_1_OPERATOR_APPROVAL_FILE_ABSENT" in response["fail_blockers"]
    assert urlopen_spy == []


def test_direct_call_no_codex_final_marker_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    # Provide an operator approval file but NOT the Codex final marker.
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    assert "GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT" in response["fail_blockers"]
    assert urlopen_spy == []


def test_direct_call_stale_permission_probe_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"], age_seconds=99999)
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    matched = [b for b in response["fail_blockers"] if b.startswith("GATE_3_PERMISSION_PROBE_STALE")]
    assert matched, response["fail_blockers"]
    assert urlopen_spy == []


def test_direct_call_kill_switch_armed_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    redis = _FakeRedis()
    redis.set(adapter_mod.KEY_KILL_SWITCH, "ARMED")
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths, redis_client=redis)
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    assert "GATE_11_KILL_SWITCH_ARMED" in response["fail_blockers"]
    assert urlopen_spy == []


def test_direct_call_runtime_live_gate_blocked_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    # Approval file declares runtime_live_gate=blocked_human_only.
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(
        _approval_file_body(runtime_live_gate="blocked_human_only"), encoding="utf-8"
    )
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    assert "GATE_13_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED" in response["fail_blockers"]
    assert urlopen_spy == []


def test_direct_call_runtime_live_symbols_empty_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    # Approval file declares an empty runtime_live_symbols.
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(
        _approval_file_body(runtime_live_symbols=""), encoding="utf-8"
    )
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    assert "GATE_13_RUNTIME_LIVE_SYMBOLS_NOT_EQUAL_APPROVED_SYMBOLS" in response["fail_blockers"]
    assert urlopen_spy == []


def test_direct_call_over_max_notional_causes_zero_urlopen(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    # Approval has small cap; candidate exceeds it.
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(
        _approval_file_body(max_notional_usdt=10.0), encoding="utf-8"
    )
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(
        IntentCandidate(
            symbol="BTCUSDT",
            side="BUY",
            requested_notional_usdt=99.0,  # exceeds 10.0
            requested_quantity=0.001,
        ),
        tmp_paths,
    )
    response = transport.submit_signed_canary_order(gate_decision=decision)
    assert response["real_order_submitted"] is False
    assert "GATE_8_REQUESTED_NOTIONAL_ABOVE_CAP" in response["fail_blockers"]
    assert urlopen_spy == []


def test_positive_path_all_gates_pass_uses_fake_transport_only(
    urlopen_spy: list[Any], fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    """When all 14 gates are represented as passing, the FAKE
    transport (default) is what gets called. The real transport
    would also re-validate, but in this test we use the fake one
    to guarantee zero network calls."""
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=parse_approval_file(tmp_paths["approval"]),
        approval_file_path=tmp_paths["approval"],
        codex_final_pass_marker_path=tmp_paths["codex_final_marker"],
        permission_probe_status_path=tmp_paths["probe_status"],
        exchange_adapter=FakeExchangeAdapter(),
        dry_run=False,
        live_enabled=True,
    )
    blockers = adapter.evaluate_real_order_blockers(_candidate())
    assert blockers == [], blockers
    result = adapter.submit_canary_order(candidate=_candidate(), cycle_id="t1")
    assert result["real_order_submitted"] is False
    assert result["fail_blockers"] == []
    # Fake transport recorded one call; urlopen never reached
    assert adapter.exchange_adapter.call_count == 1
    assert urlopen_spy == []


def test_positive_path_real_transport_revalidates_and_reaches_urlopen(
    urlopen_spy: list[Any], fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    """Final proof: even on the positive path, the real transport's
    submit method runs re-validation first. When re-validation
    clears, it then calls urlopen. The spy records the call (and
    raises in the production code path, which we catch as a
    blocked outcome). The point: re-validation is what gates the
    network call; the call never happens unless re-validation
    passes."""
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    real = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths, redis_client=fake_redis)
    response = real.submit_signed_canary_order(gate_decision=decision)
    # The spy raised; production code surfaces it as ERROR or similar.
    # The key proof is: re-validation passed (blockers empty), THEN
    # urlopen was attempted. If any gate had failed, urlopen would
    # never have been reached.
    assert len(urlopen_spy) == 1
    assert response["real_order_submitted"] is False  # spy raised
    # Re-validation passed → submission was attempted (network spy raised).
    assert response.get("real_order_attempted") is True


def _approval_file_body(
    *,
    canary_mode: str = "V2_NATIVE_SIGNAL_CANARY",
    live_symbols: str = "BTCUSDT",
    max_notional_usdt: float = 20.0,
    max_daily_live_trades: int = 3,
    max_daily_loss_usdt: float = 10.0,
    runtime_live_gate: str = "live_canary_operator_approved",
    runtime_live_symbols: str = "BTCUSDT",
) -> str:
    return "\n".join(
        [
            f"canary_mode: {canary_mode}",
            f"live_symbols: {live_symbols}",
            f"max_notional_usdt: {max_notional_usdt}",
            f"max_daily_live_trades: {max_daily_live_trades}",
            f"max_daily_loss_usdt: {max_daily_loss_usdt}",
            "leverage_change_approved: NO",
            "margin_mode_change_approved: NO",
            "redis_trim_approved: NO",
            "legacy_shutdown_approved: NO",
            f"runtime_live_gate: {runtime_live_gate}",
            f"runtime_live_symbols: {runtime_live_symbols}",
        ]
    )


# --------------------------------------------------------------------------- #
# Codex regression suite (private signed-post bypass remediation).            #
#                                                                             #
# These tests prove that _perform_signed_post is gone and that no other       #
# private or public callable can reach urllib.request.urlopen without         #
# re-running the 14-gate cascade inside the same function.                    #
# --------------------------------------------------------------------------- #


def test_private_signed_post_method_removed_or_unreachable() -> None:
    """The prior bypass via ``_perform_signed_post`` must be gone.
    The adapter class must not expose any of the canonical
    bypass names enumerated by Codex."""
    adapter = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    forbidden = (
        "_perform_signed_post",
        "_signed_post",
        "_post_order",
        "_submit_order_raw",
        "_send_order",
        "submit_raw",
    )
    for name in forbidden:
        assert not hasattr(adapter, name), (
            f"BinanceFuturesExchangeAdapter must not expose {name}"
        )
        assert not hasattr(BinanceFuturesExchangeAdapter, name), (
            f"BinanceFuturesExchangeAdapter class must not declare {name}"
        )


def test_real_adapter_has_no_callable_signed_post_bypass() -> None:
    """Static scan: enumerate every callable attribute on the real
    adapter class. The ONLY public callable must be
    ``submit_signed_canary_order``. No private callable name may
    match the forbidden bypass set, and no callable other than the
    single public entry may reference ``urllib.request.urlopen``."""
    import inspect

    forbidden_substrings = (
        "perform_signed_post",
        "signed_post",
        "post_order",
        "submit_order_raw",
        "send_order",
        "submit_raw",
    )
    members = inspect.getmembers(BinanceFuturesExchangeAdapter, predicate=callable)
    method_names = [name for name, _ in members if not name.startswith("__")]
    # Only submit_signed_canary_order survives as a public method.
    public_methods = [n for n in method_names if not n.startswith("_")]
    assert public_methods == ["submit_signed_canary_order"], public_methods
    # No private method name matches the forbidden bypass substrings.
    for name in method_names:
        for sub in forbidden_substrings:
            assert sub not in name.lower(), (
                f"BinanceFuturesExchangeAdapter exposes a method named {name} "
                f"that matches forbidden bypass substring '{sub}'"
            )


def test_only_one_urlopen_call_site_in_execution_adapter() -> None:
    """The execution_adapter module must contain EXACTLY ONE
    ``urllib.request.urlopen(`` call site, and it must live inside
    ``BinanceFuturesExchangeAdapter.submit_signed_canary_order``.
    """
    src = Path(adapter_mod.__file__).read_text(encoding="utf-8")
    occurrences = src.count("urllib.request.urlopen(")
    assert occurrences == 1, (
        f"Expected exactly 1 urlopen call site; found {occurrences}"
    )
    # Locate the urlopen line and walk backwards to find the
    # enclosing def. It must be submit_signed_canary_order.
    lines = src.splitlines()
    urlopen_line_idx = next(
        i for i, line in enumerate(lines) if "urllib.request.urlopen(" in line
    )
    enclosing_def: str | None = None
    for i in range(urlopen_line_idx, -1, -1):
        stripped = lines[i].lstrip()
        if stripped.startswith("def "):
            enclosing_def = stripped.split("(", 1)[0].removeprefix("def ").strip()
            break
    assert enclosing_def == "submit_signed_canary_order", enclosing_def


def test_direct_import_cannot_call_order_endpoint_without_gate_revalidation(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """Direct import of the real adapter + direct invocation of its
    public method must run the 14-gate revalidation INSIDE the same
    function that would call urlopen. With every state-check failing
    (no approval file, no Codex marker, no probe), urlopen stays at
    zero."""
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert result["real_order_submitted"] is False
    assert result["real_order_attempted"] is False
    assert result["places_real_order"] is False
    assert urlopen_spy == []


def test_direct_import_with_forged_gate_decision_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """A direct call with a forged token must short-circuit before
    re-validation and before any urlopen call."""
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    forged = _make_decision_with_token(
        _candidate(), tmp_paths, token="this-is-not-the-real-module-token"
    )
    result = transport.submit_signed_canary_order(gate_decision=forged)
    assert "REJECTED_FORGED_GATE_DECISION_TOKEN" in result["fail_blockers"]
    assert urlopen_spy == []


def test_direct_import_with_blocked_live_gate_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """Approval file declares runtime_live_gate=blocked_human_only:
    GATE_13 fails at re-validation and urlopen is not reached."""
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(
        _approval_file_body(runtime_live_gate="blocked_human_only"), encoding="utf-8"
    )
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert "GATE_13_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED" in result["fail_blockers"]
    assert urlopen_spy == []


def test_direct_import_with_empty_live_symbols_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """Approval file declares runtime_live_symbols empty: GATE_13
    fails at re-validation and urlopen is not reached."""
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(
        _approval_file_body(runtime_live_symbols=""), encoding="utf-8"
    )
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert "GATE_13_RUNTIME_LIVE_SYMBOLS_NOT_EQUAL_APPROVED_SYMBOLS" in result["fail_blockers"]
    assert urlopen_spy == []


def test_direct_import_with_kill_switch_armed_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    redis = _FakeRedis()
    redis.set(adapter_mod.KEY_KILL_SWITCH, "ARMED")
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths, redis_client=redis)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert "GATE_11_KILL_SWITCH_ARMED" in result["fail_blockers"]
    assert urlopen_spy == []


def test_direct_import_without_codex_final_marker_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_fresh_probe_status(tmp_paths["probe_status"])
    # codex_final_marker intentionally NOT written
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert "GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT" in result["fail_blockers"]
    assert urlopen_spy == []


def test_direct_import_without_operator_approval_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    # No approval file written (and other state also absent)
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert "GATE_1_OPERATOR_APPROVAL_FILE_ABSENT" in result["fail_blockers"]
    assert urlopen_spy == []


def test_positive_path_revalidates_then_calls_urlopen_exactly_once(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """When every state check clears at submission time, urlopen is
    reached exactly once. The monkeypatched spy raises so we never
    hit Binance; the production code surfaces the raised exception
    as an error response. The point: re-validation is what gates
    the call — and it passed."""
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(_approval_file_body(), encoding="utf-8")
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    # Redis with kill switch absent (not active) so GATE_11 clears.
    redis = _FakeRedis()
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    decision = _make_decision_with_token(_candidate(), tmp_paths, redis_client=redis)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert len(urlopen_spy) == 1
    # Spy raised; production path returns an ERROR result.
    assert result.get("real_order_attempted") is True
    assert result["real_order_submitted"] is False


def test_positive_path_one_failing_gate_makes_zero_urlopen_calls(
    urlopen_spy: list[Any], tmp_paths: dict[str, Path]
) -> None:
    """Even with most gates clear, a single failing gate (here:
    over-cap notional) is enough to make urlopen zero."""
    tmp_paths["approval"].parent.mkdir(parents=True, exist_ok=True)
    tmp_paths["approval"].write_text(
        _approval_file_body(max_notional_usdt=10.0), encoding="utf-8"
    )
    _write_codex_marker(tmp_paths["codex_final_marker"])
    _write_fresh_probe_status(tmp_paths["probe_status"])
    transport = BinanceFuturesExchangeAdapter("dummy-key", "dummy-secret")
    over_cap = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=99.0,
        requested_quantity=0.001,
    )
    decision = _make_decision_with_token(over_cap, tmp_paths)
    result = transport.submit_signed_canary_order(gate_decision=decision)
    assert "GATE_8_REQUESTED_NOTIONAL_ABOVE_CAP" in result["fail_blockers"]
    assert urlopen_spy == []


# --------------------------------------------------------------------------- #
# Endpoint surface scan                                                       #
# --------------------------------------------------------------------------- #


def test_execution_adapter_source_has_no_cancel_modify_leverage_margin_endpoints() -> None:
    """Static source scan: the execution_adapter module must
    reference only /fapi/v1/order as an endpoint path. No cancel,
    modify, leverage, or margin endpoint may appear."""
    src = Path(adapter_mod.__file__).read_text(encoding="utf-8")
    # Allow these substrings in identifiers (e.g. "leverage_change_approved").
    # Disallow only as Binance endpoint URL fragments.
    forbidden_paths = (
        "/fapi/v1/leverage",
        "/fapi/v1/marginType",
        "/fapi/v1/order/cancel",
        "/fapi/v1/allOpenOrders",
        "/fapi/v1/positionMargin",
        "/fapi/v1/positionRisk",
        "/fapi/v1/listenKey",
        "/dapi/v1/leverage",
    )
    for path in forbidden_paths:
        assert path not in src, f"Forbidden endpoint path appears in source: {path}"
    # The only Binance path referenced must be /fapi/v1/order
    assert "/fapi/v1/order" in src
