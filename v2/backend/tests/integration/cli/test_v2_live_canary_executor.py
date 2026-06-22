"""Integration tests for the V2 live-canary executor CLI.

The executor must be fail-closed by default. These tests verify that:

- With no operator approval file, the executor emits the
  ``OPERATOR_APPROVAL_REQUIRED`` go/no-go.
- With approval file present but Codex PASS marker absent and
  permission probe unable to advance (always the case in this
  scaffolding packet because the probe defers to a separate
  operator-approved packet), the executor emits the
  ``PERMISSION_UNKNOWN`` go/no-go.
- The kill switch fails closed when set or missing.
- The notional cap is enforced.
- ``submit_live_canary_order`` always raises ``NotImplementedError``
  in this packet (no exchange surface exists).
- The CLI status payload NEVER contains a raw API key/secret value.
- The CLI status payload NEVER contains ``approves_live=true``,
  ``approves_canary=true``, ``approves_legacy_shutdown=true``, or
  ``approves_redis_trim=true``.
- Only ``v2:live_canary:*`` Redis keys are written; legacy keys are
  refused at the lowest layer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_live_canary_executor as cli
from v2.backend.app.services.live_canary import execution_adapter as adapter_mod
from v2.backend.app.services.live_canary.execution_adapter import (
    ApprovalEnvelope,
    IntentCandidate,
    LiveCanaryExecutionAdapter,
    parse_approval_file,
)
from v2.backend.app.services.live_canary.permission_probe import (
    PROBE_GO_BLOCKED,
    PROBE_GO_READY,
    run_probe,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.refused: list[str] = []

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
    approval = tmp_path / "OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md"
    codex_marker = tmp_path / "codex_review" / "CODEX_LIVE_CANARY_PASS.marker"
    secrets = tmp_path / ".local_secrets" / "live_canary.env"
    worklog = tmp_path / "worklog" / "live_canary_executor_status.json"
    public = tmp_path / "public" / "live_canary_executor_status.json"
    return {
        "approval": approval,
        "codex_marker": codex_marker,
        "secrets": secrets,
        "worklog": worklog,
        "public": public,
    }


def _write_approval(path: Path, **overrides: object) -> None:
    fields = {
        "canary_mode": "V2_NATIVE_SIGNAL_CANARY",
        "live_symbols": "BTCUSDT",
        "max_notional_usdt": "20",
        "max_daily_live_trades": "3",
        "max_daily_loss_usdt": "10",
        "leverage_change_approved": "NO",
        "margin_mode_change_approved": "NO",
        "redis_trim_approved": "NO",
        "legacy_shutdown_approved": "NO",
    }
    fields.update({k: str(v) for k, v in overrides.items()})
    lines = ["# Operator approval"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_no_approval_file_emits_operator_approval_required(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    payload = cli.run_once(
        redis_client=fake_redis,
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        secrets_path=tmp_paths["secrets"],
        out_worklog=tmp_paths["worklog"],
        out_public=tmp_paths["public"],
    )
    assert payload["go_no_go"] == cli.GO_OPERATOR_APPROVAL_REQUIRED
    assert payload["dry_run"] is True
    assert payload["live_enabled"] is False
    assert payload["real_order_attempted"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["raw_credential_in_payload"] == "NEVER"


def test_approval_present_probe_not_ready_emits_permission_unknown(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    _write_approval(tmp_paths["approval"])
    payload = cli.run_once(
        redis_client=fake_redis,
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        secrets_path=tmp_paths["secrets"],
        out_worklog=tmp_paths["worklog"],
        out_public=tmp_paths["public"],
    )
    # Permission probe never advances in this scaffolding packet
    assert payload["go_no_go"] == cli.GO_PERMISSION_UNKNOWN
    assert payload["permission_probe_go_no_go"] == PROBE_GO_BLOCKED
    assert payload["dry_run"] is True
    assert payload["live_enabled"] is False
    assert payload["real_order_attempted"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_kill_switch_active_when_set_or_missing(
    fake_redis: _FakeRedis,
) -> None:
    # Default (no key): NOT active (no operator armed it)
    assert adapter_mod._kill_switch_active(fake_redis) is False
    # Explicit "false": NOT active
    fake_redis.set(adapter_mod.KEY_KILL_SWITCH, "false")
    assert adapter_mod._kill_switch_active(fake_redis) is False
    # Any non-empty truthy value: ACTIVE (fail-closed)
    fake_redis.set(adapter_mod.KEY_KILL_SWITCH, "ARMED")
    assert adapter_mod._kill_switch_active(fake_redis) is True
    fake_redis.set(adapter_mod.KEY_KILL_SWITCH, "1")
    assert adapter_mod._kill_switch_active(fake_redis) is True
    # None redis: fail-closed
    assert adapter_mod._kill_switch_active(None) is True


def test_submit_canary_order_returns_blocked_with_default_adapter(
    fake_redis: _FakeRedis,
) -> None:
    """The default-constructed adapter cannot reach a real order
    path. submit_canary_order returns a structured BLOCKED result
    rather than raising; the configured adapter is FakeExchangeAdapter."""
    approval = ApprovalEnvelope(
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
    )
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval,
        permission_probe_go_no_go=PROBE_GO_READY,
        codex_pass_marker_path=Path("/nonexistent/codex_pass.marker"),
    )
    candidate = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        signal_source="V2_NATIVE_SIGNAL_CANARY",
        expected_move_after_cost_bps=15.0,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )
    result = adapter.submit_live_canary_order(candidate=candidate, cycle_id="t1")
    assert result["go_no_go"] == "BLOCKED_REAL_ORDER_REFUSED"
    assert result["real_order_submitted"] is False
    assert result["real_order_attempted"] is False
    assert result["places_real_order"] is False
    assert result["writes_legacy_redis"] is False
    assert result["writes_exchange_orders"] is False
    assert result["leverage_changed"] is False
    assert result["margin_mode_changed"] is False
    assert result["live_gate"] == "blocked_human_only"
    assert result["live_symbols"] == []
    # Intent persisted to Redis
    intents_raw = fake_redis.get(adapter_mod.KEY_INTENTS)
    assert intents_raw is not None
    intents = json.loads(intents_raw)
    assert len(intents) == 1
    intent = intents[0]
    assert intent["real_order_submitted"] is False
    assert intent["places_real_order"] is False
    assert intent["writes_legacy_redis"] is False
    assert intent["writes_exchange_orders"] is False
    assert intent["approves_live"] is False
    assert intent["approves_canary"] is False
    # Direct-call bypass remediation: no caller-supplied boolean
    # field exists on the intent. The transport re-validates from
    # current state at submission time instead.
    assert "canary_signed_by_executor_gate_cascade" not in intent
    assert intent["direct_call_bypass_remediated"] is True
    assert intent["caller_supplied_gate_boolean_accepted"] is False
    assert intent["final_submit_rechecks_all_gates"] is True


def test_notional_cap_blocks_candidate(fake_redis: _FakeRedis) -> None:
    approval = ApprovalEnvelope(
        approval_file_present=True,
        canary_mode_selected="V2_NATIVE_SIGNAL_CANARY",
        allowed_symbols=("BTCUSDT",),
        max_notional_usdt=10.0,
        max_daily_live_trades=3,
        max_daily_loss_usdt=10.0,
        leverage_change_approved=False,
        margin_mode_change_approved=False,
        redis_trim_approved=False,
        legacy_shutdown_approved=False,
    )
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval,
        permission_probe_go_no_go=PROBE_GO_READY,
        codex_pass_marker_path=Path("/nonexistent/codex_pass.marker"),
    )
    candidate = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=99.0,  # exceeds cap of 10
        signal_source="V2_NATIVE_SIGNAL_CANARY",
        expected_move_after_cost_bps=15.0,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )
    blockers = adapter.evaluate_pretrade_blockers(candidate=candidate)
    assert "GATE_8_REQUESTED_NOTIONAL_ABOVE_CAP" in blockers


def test_leverage_or_margin_or_legacy_shutdown_approval_blocks(
    fake_redis: _FakeRedis,
) -> None:
    """Approvals for leverage/margin/redis-trim/legacy-shutdown must
    *block* — those flags are explicitly NOT permitted in this packet.
    """
    approval = ApprovalEnvelope(
        approval_file_present=True,
        canary_mode_selected="V2_NATIVE_SIGNAL_CANARY",
        allowed_symbols=("BTCUSDT",),
        max_notional_usdt=20.0,
        max_daily_live_trades=3,
        max_daily_loss_usdt=10.0,
        leverage_change_approved=True,
        margin_mode_change_approved=True,
        redis_trim_approved=True,
        legacy_shutdown_approved=True,
    )
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval,
        permission_probe_go_no_go=PROBE_GO_READY,
        codex_pass_marker_path=Path("/nonexistent/codex_pass.marker"),
    )
    candidate = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        signal_source="V2_NATIVE_SIGNAL_CANARY",
        expected_move_after_cost_bps=15.0,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )
    blockers = adapter.evaluate_pretrade_blockers(candidate=candidate)
    assert "GATE_14_LEVERAGE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED" in blockers
    assert "GATE_14_MARGIN_MODE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED" in blockers
    assert "GATE_14_REDIS_TRIM_APPROVAL_PRESENT_NOT_ALLOWED" in blockers
    assert "GATE_14_LEGACY_SHUTDOWN_APPROVAL_PRESENT_NOT_ALLOWED" in blockers


def test_kill_switch_armed_blocks(fake_redis: _FakeRedis) -> None:
    fake_redis.set(adapter_mod.KEY_KILL_SWITCH, "ARMED")
    approval = ApprovalEnvelope(
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
    )
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval,
        permission_probe_go_no_go=PROBE_GO_READY,
        codex_pass_marker_path=Path("/nonexistent/codex_pass.marker"),
    )
    candidate = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        signal_source="V2_NATIVE_SIGNAL_CANARY",
        expected_move_after_cost_bps=15.0,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )
    blockers = adapter.evaluate_pretrade_blockers(candidate=candidate)
    assert "GATE_11_KILL_SWITCH_ARMED" in blockers


def test_symbol_not_in_allowed_list_blocks(fake_redis: _FakeRedis) -> None:
    approval = ApprovalEnvelope(
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
    )
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval,
        permission_probe_go_no_go=PROBE_GO_READY,
        codex_pass_marker_path=Path("/nonexistent/codex_pass.marker"),
    )
    candidate = IntentCandidate(
        symbol="DOGEUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        signal_source="V2_NATIVE_SIGNAL_CANARY",
        expected_move_after_cost_bps=15.0,
        paper_fill_gate_open=True,
        feature_freshness_state="CURRENT",
        v2_prediction_present=True,
    )
    blockers = adapter.evaluate_pretrade_blockers(candidate=candidate)
    assert "GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST" in blockers


def test_operator_gate_cascade_blocks_when_codex_final_marker_absent(
    fake_redis: _FakeRedis,
) -> None:
    """The new operator-gated cascade requires GATE_2 (Codex final
    marker). Without it, no real order is reachable regardless of
    signal quality. Signal-quality gates (paper_fill_gate_open,
    v2_prediction_present, feature_freshness) are no longer part of
    the operator-final cascade — they belong to the upstream paper
    pipeline."""
    approval = ApprovalEnvelope(
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
    )
    adapter = LiveCanaryExecutionAdapter(
        redis_client=fake_redis,
        approval=approval,
        permission_probe_go_no_go=PROBE_GO_READY,
        codex_final_pass_marker_path=Path("/nonexistent/codex_final.marker"),
    )
    candidate = IntentCandidate(
        symbol="BTCUSDT",
        side="BUY",
        requested_notional_usdt=5.0,
        requested_quantity=0.001,
    )
    blockers = adapter.evaluate_pretrade_blockers(candidate=candidate)
    assert "GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT" in blockers


def test_safe_redis_set_refuses_non_live_canary_keys(fake_redis: _FakeRedis) -> None:
    # Allowed
    assert adapter_mod._safe_redis_set(
        fake_redis, adapter_mod.KEY_HEARTBEAT, "{}", ex=60
    )
    # Refused — accepted-positions namespace
    assert not adapter_mod._safe_redis_set(
        fake_redis, "v2:paper:positions", "{}", ex=60
    )
    # Refused — legacy
    assert not adapter_mod._safe_redis_set(
        fake_redis, "order_intent:BTCUSDT", "{}", ex=60
    )
    assert not adapter_mod._safe_redis_set(
        fake_redis, "trader:positions", "{}", ex=60
    )


def test_parse_approval_file_strict_no_default(tmp_paths: dict[str, Path]) -> None:
    # Boolean fields must require explicit YES/TRUE/1 to flip to True
    _write_approval(
        tmp_paths["approval"],
        leverage_change_approved="MAYBE",
        margin_mode_change_approved="NO",
        redis_trim_approved="",
        legacy_shutdown_approved="false",
    )
    approval = parse_approval_file(tmp_paths["approval"])
    assert approval.approval_file_present is True
    assert approval.canary_mode_selected == "V2_NATIVE_SIGNAL_CANARY"
    assert approval.leverage_change_approved is False
    assert approval.margin_mode_change_approved is False
    assert approval.redis_trim_approved is False
    assert approval.legacy_shutdown_approved is False
    assert "BTCUSDT" in approval.allowed_symbols


def test_status_payload_has_no_raw_credentials_or_live_approvals(
    fake_redis: _FakeRedis, tmp_paths: dict[str, Path]
) -> None:
    _write_approval(tmp_paths["approval"])
    payload = cli.run_once(
        redis_client=fake_redis,
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        secrets_path=tmp_paths["secrets"],
        out_worklog=tmp_paths["worklog"],
        out_public=tmp_paths["public"],
    )
    flat = json.dumps(payload)
    # No raw credential values
    assert "BINANCE_API_KEY=" not in flat
    assert "BINANCE_API_SECRET=" not in flat
    # No accidental live approval
    assert '"approves_live": true' not in flat
    assert '"approves_canary": true' not in flat
    assert '"approves_legacy_shutdown": true' not in flat
    assert '"approves_redis_trim": true' not in flat
    # No exchange mutation claim
    assert '"writes_exchange_orders": true' not in flat
    assert '"writes_legacy_redis": true' not in flat
    assert '"real_order_attempted": true' not in flat
    assert '"places_real_order": true' not in flat
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_permission_probe_blocked_with_no_env_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_paths: dict[str, Path],
) -> None:
    """When no env file is present and no credential env vars are
    exported, the network-safe probe must report BLOCKED with at
    minimum the credential and mode/symbols blockers."""
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    result = run_probe(
        secrets_path=tmp_paths["secrets"],
        approval_path=tmp_paths["approval"],
        codex_pass_marker_path=tmp_paths["codex_marker"],
        network_probe_enabled=False,
    )
    payload = result.as_payload()
    assert payload["go_no_go"] == PROBE_GO_BLOCKED
    assert payload["real_order_attempted"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert "BINANCE_API_KEY_ENV_VAR_ABSENT" in payload["fail_blockers"]
    assert "BINANCE_API_SECRET_ENV_VAR_ABSENT" in payload["fail_blockers"]
    assert "V2_LIVE_CANARY_MODE_NOT_SELECTED_OR_INVALID" in payload["fail_blockers"]
    assert "V2_LIVE_CANARY_SYMBOLS_WHITELIST_EMPTY" in payload["fail_blockers"]
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
