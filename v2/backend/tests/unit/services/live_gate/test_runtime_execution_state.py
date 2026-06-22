from __future__ import annotations

import json
from pathlib import Path

from app.services.live_gate.runtime_execution_state import (
    ALLOWED_RUNTIME_KEYS,
    KEY_LIVE_GATE_STATE,
    LIVE_GATE_BLOCKED,
    LIVE_GATE_ENABLED,
    apply_runtime_state_to_trader_status,
    get_canonical_live_gate_status,
    read_runtime_execution_state,
    refresh_runtime_execution_state_heartbeat,
    validate_order_lineage_candidate,
    write_runtime_execution_state,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def _risk_record() -> dict:
    return {
        "audit_id": "risk_audit",
        "accepted_profile_id": "conservative",
        "accepted_profile_name": "conservative",
        "accepted_profile_fields": {
            "cooldown_seconds": 1200,
            "kill_switch_conditions": ["daily_loss_cap_breach"],
            "max_daily_loss": 15.0,
            "max_drawdown": 75.0,
            "max_leverage": 1.0,
            "max_notional_per_trade": 25.0,
            "max_open_positions": 1,
            "max_slippage_bps": 2.0,
            "max_spread_bps": 3.5,
            "max_symbol_exposure": 45.0,
            "max_total_exposure": 100.0,
            "min_confidence_calibrated": 0.66,
            "min_expected_move_after_cost_bps": 12.0,
        },
    }


def _write_state(tmp_path: Path, redis_client: FakeRedis) -> dict:
    return write_runtime_execution_state(
        repo_root=tmp_path,
        accepted_symbols=["BTCUSDT", "ETHUSDT"],
        risk_record=_risk_record(),
        symbol_record={"audit_id": "symbols_audit"},
        final_record={"audit_id": "final_audit"},
        enable_audit_id="enable_audit",
        enabled_by="unit-test",
        source_payload_ids=["source_a", "source_b"],
        redis_client=redis_client,
    )


def test_runtime_writer_defaults_to_disarmed_non_live_state(tmp_path: Path) -> None:
    fake = FakeRedis()
    result = _write_state(tmp_path, fake)

    assert result["ok"] is True
    assert set(fake.values) == set(ALLOWED_RUNTIME_KEYS)
    assert all(key.startswith("v2:") for key in fake.values)
    payload = json.loads(fake.values[KEY_LIVE_GATE_STATE])
    assert payload["trader_execution_enabled"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["risk_profile"]["profile_name"] == "conservative"
    assert payload["leverage_mutation_allowed"] is False
    assert payload["margin_mutation_allowed"] is False
    assert payload["order_transport_write_guard_enabled"] is True
    assert payload["order_transport_submit_enabled"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["operator_approved"] is False
    assert payload["order_transport_submit_source"] == "runtime_execution_state_writer"


def test_runtime_writer_uses_enabled_state_only_when_release_mode_approved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("V2_RELEASE_MODE", "LIVE_CANARY_APPROVED")
    fake = FakeRedis()
    result = _write_state(tmp_path, fake)

    assert result["ok"] is True
    payload = json.loads(fake.values[KEY_LIVE_GATE_STATE])
    assert payload["trader_execution_enabled"] is True
    assert payload["live_gate"] == "enabled_operator_approved"
    assert payload["live_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["order_transport_submit_enabled"] is True
    assert payload["live_trading_enabled"] is True
    assert payload["operator_approved"] is True


def test_trader_status_consumes_valid_runtime_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("V2_RELEASE_MODE", "LIVE_CANARY_APPROVED")
    fake = FakeRedis()
    _write_state(tmp_path, fake)
    runtime_read = read_runtime_execution_state(repo_root=tmp_path, redis_client=fake)

    trader = apply_runtime_state_to_trader_status(
        {
            "runtime_observation_rows": [
                {
                    "symbol": "BTCUSDT",
                    "prediction_id": "pred",
                    "risk_decision_id": "risk",
                    "orchestrator_decision_id": "orch",
                }
            ]
        },
        runtime_read,
    )

    assert trader["trader_execution_enabled"] is True
    assert trader["live_gate"] == "enabled_operator_approved"
    assert trader["live_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert trader["runtime_observation_rows"][0]["eligible_for_live_execution"] is True
    assert trader["writes_exchange_orders"] is False


def test_unaccepted_symbol_and_missing_lineage_are_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("V2_RELEASE_MODE", "LIVE_CANARY_APPROVED")
    fake = FakeRedis()
    _write_state(tmp_path, fake)
    payload = json.loads(fake.values[KEY_LIVE_GATE_STATE])

    wrong_symbol = validate_order_lineage_candidate(
        runtime_state=payload,
        symbol="BNBUSDT",
        prediction_id="pred",
        risk_decision_id="risk",
        orchestrator_decision_id="orch",
    )
    missing_lineage = validate_order_lineage_candidate(
        runtime_state=payload,
        symbol="BTCUSDT",
        prediction_id="pred",
        risk_decision_id=None,
        orchestrator_decision_id="orch",
    )

    assert wrong_symbol["allowed"] is False
    assert "SYMBOL_NOT_ACCEPTED_FOR_LIVE_EXECUTION" in wrong_symbol["blockers"]
    assert missing_lineage["allowed"] is False
    assert "RISK_DECISION_ID_MISSING" in missing_lineage["blockers"]


def test_heartbeat_refresh_preserves_enable_time_and_repairs_freshness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("V2_RELEASE_MODE", "LIVE_CANARY_APPROVED")
    fake = FakeRedis()
    _write_state(tmp_path, fake)
    payload = json.loads(fake.values[KEY_LIVE_GATE_STATE])
    payload["enabled_at_est"] = "2026-06-01T00:00:00-04:00"
    payload["generated_est"] = "2026-06-01T00:00:00-04:00"
    payload.pop("runtime_refreshed_at_est", None)
    fake.values[KEY_LIVE_GATE_STATE] = json.dumps(payload)

    stale_read = read_runtime_execution_state(repo_root=tmp_path, redis_client=fake, max_age_seconds=1)
    assert "LIVE_GATE_RUNTIME_STATE_STALE" in stale_read["validation"]["blockers"]

    refreshed = refresh_runtime_execution_state_heartbeat(repo_root=tmp_path, redis_client=fake)
    refreshed_payload = json.loads(fake.values[KEY_LIVE_GATE_STATE])

    assert refreshed["ok"] is True
    assert refreshed_payload["enabled_at_est"] == "2026-06-01T00:00:00-04:00"
    assert refreshed_payload["runtime_refreshed_at_est"] != "2026-06-01T00:00:00-04:00"
    fresh_read = read_runtime_execution_state(repo_root=tmp_path, redis_client=fake, max_age_seconds=60)
    assert fresh_read["validation"]["valid"] is True


# ---------------------------------------------------------------------------
# Canonical live gate status — no conflicting display
# ---------------------------------------------------------------------------


def test_canonical_live_gate_always_blocked_without_release_mode(tmp_path: Path) -> None:
    """Without LIVE_CANARY_APPROVED env, canonical status is always blocked."""
    fake = FakeRedis()
    result = get_canonical_live_gate_status(redis_client=fake, repo_root=tmp_path)
    assert result["live_gate"] == LIVE_GATE_BLOCKED
    assert result["live_trading_enabled"] is False
    assert result["live_blocked"] is True
    assert result["operator_approved"] is False
    assert result["live_symbols"] == []


def test_canonical_live_gate_blocked_without_approval_even_with_release_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """LIVE_CANARY_APPROVED alone is not enough; full approval flow required."""
    monkeypatch.setenv("V2_RELEASE_MODE", "LIVE_CANARY_APPROVED")
    fake = FakeRedis()
    # No runtime state written — gate must still be blocked.
    result = get_canonical_live_gate_status(redis_client=fake, repo_root=tmp_path)
    assert result["live_gate"] == LIVE_GATE_BLOCKED
    assert result["live_trading_enabled"] is False
    assert result["operator_approved"] is False


def test_canonical_live_gate_no_enabled_operator_approved_without_full_flow(
    tmp_path: Path,
) -> None:
    """No surface must ever show enabled_operator_approved when release mode is not approved."""
    fake = FakeRedis()
    result = get_canonical_live_gate_status(redis_client=fake, repo_root=tmp_path)
    # The value must never be LIVE_GATE_ENABLED without the full approval flow.
    assert result["live_gate"] != LIVE_GATE_ENABLED, (
        f"CONFLICT: live_gate is '{result['live_gate']}' but should be blocked_human_only. "
        "This would cause frontend to show 'enabled_operator_approved' without approval."
    )


def test_canonical_live_gate_returns_enabled_when_full_flow_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Gate becomes enabled only when release mode + approval flow are both complete."""
    monkeypatch.setenv("V2_RELEASE_MODE", "LIVE_CANARY_APPROVED")
    fake = FakeRedis()
    _write_state(tmp_path, fake)
    # With full approval + correct release mode the gate should be enabled.
    result = get_canonical_live_gate_status(redis_client=fake, repo_root=tmp_path)
    assert result["live_gate"] == LIVE_GATE_ENABLED
    assert result["live_trading_enabled"] is True
    assert result["operator_approved"] is True
    assert "BTCUSDT" in result["live_symbols"]
    # conflict_check must not indicate split-brain.
    assert "no_conflict" in result.get("conflict_check", "")


def test_canonical_live_gate_conflict_check_field_present(tmp_path: Path) -> None:
    """The conflict_check field proves no split-brain on every response."""
    fake = FakeRedis()
    result = get_canonical_live_gate_status(redis_client=fake, repo_root=tmp_path)
    assert "conflict_check" in result
    assert result["conflict_check"].startswith("no_conflict")
