"""Adversarial tests for the paper-only portfolio cascade guard."""

from __future__ import annotations

import copy
import json

from v2.backend.app.cli import v2_portfolio_cascade_guard_loop as guard
from v2.backend.app.services.risk.portfolio_cascade_directive import (
    verify_guard_payload,
)
from v2.backend.app.services.risk.cross_margin_liquidation import (
    seal_adaptive_stress_envelope,
)

NOW = "2026-07-09T06:00:00.000Z"
LEDGER_AT = "2026-07-09T05:59:30.000Z"
SESSION = "paper-session-a"


class FakeRedis:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in (values or {}).items()
        }
        self.get_counts: dict[str, int] = {}
        self.writes: list[tuple[str, str, int | None]] = []

    def get(self, key: str):
        self.get_counts[key] = self.get_counts.get(key, 0) + 1
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        self.writes.append((key, value, ex))
        return True


def _position_and_margin(*, mark: float = 99.0, generation: str = "generation-a"):
    quantity, entry, leverage, rate, cum = 10.0, 100.0, 5.0, 0.01, 0.5
    pnl_usd = quantity * (mark - entry)
    pnl_bps = (mark - entry) / entry * 10_000.0
    position = {
        "position_id": "paper_pos_ALTAUSDT_a",
        "position_generation_id": generation,
        "paper_session_id": SESSION,
        "symbol": "ALTAUSDT",
        "side": "long",
        "net_quantity": quantity,
        "avg_entry_price": entry,
        "last_mark_price": mark,
        "effective_leverage": leverage,
        "gross_notional_usd": quantity * entry,
        "maintenance_margin_rate": rate,
        "maintenance_margin_cum": cum,
        "maintenance_margin_mark_price": mark,
        "maintenance_margin_mark_time": LEDGER_AT,
        "maintenance_margin_mark_event_time": LEDGER_AT,
        "maintenance_margin_mark_generated_at": LEDGER_AT,
        "maintenance_margin_mark_available_at": LEDGER_AT,
        "maintenance_margin_mark_decision_time": LEDGER_AT,
        "maintenance_margin_mark_source": "UNIT_AUTHENTICATED_MARK",
        "maintenance_margin_mark_evidence_sha256": "a" * 64,
        "maintenance_margin_mark_contract_authoritative": True,
        "maintenance_margin_mark_freshness_budget_seconds": 1.0,
        "maintenance_margin_mark_cadence_policy_version": "UNIT_MARK_CADENCE_V1",
        "maintenance_margin_mark_consumer_validation_boundary": (
            "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
        ),
        "margin_mode_simulated": "cross_paper_simulated",
        "maintenance_margin_notional_usd": quantity * mark,
        "maintenance_margin_estimate": max(0.0, quantity * mark * rate - cum),
        "unrealized_pnl": pnl_usd,
        "unrealized_pnl_bps": pnl_bps,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    margin = {
        "row_id": position["position_id"],
        "position_generation_id": generation,
        "paper_session_id": SESSION,
        "symbol": "ALTAUSDT",
        "accounting_scope": "OPEN_EXECUTED_POSITION",
        "valid": True,
        "effective_leverage": leverage,
        "canonical_notional_usd": quantity * entry,
        "canonical_margin_usd": quantity * entry / leverage,
        "maintenance_margin_rate": rate,
        "maintenance_margin_cum": cum,
        "maintenance_margin_mark_price": mark,
        "maintenance_margin_mark_time": LEDGER_AT,
        "maintenance_margin_mark_event_time": LEDGER_AT,
        "maintenance_margin_mark_generated_at": LEDGER_AT,
        "maintenance_margin_mark_available_at": LEDGER_AT,
        "maintenance_margin_mark_decision_time": LEDGER_AT,
        "maintenance_margin_mark_source": "UNIT_AUTHENTICATED_MARK",
        "maintenance_margin_mark_evidence_sha256": "a" * 64,
        "maintenance_margin_mark_contract_authoritative": True,
        "maintenance_margin_mark_freshness_budget_seconds": 1.0,
        "maintenance_margin_mark_cadence_policy_version": "UNIT_MARK_CADENCE_V1",
        "maintenance_margin_mark_consumer_validation_boundary": (
            "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
        ),
        "margin_mode_simulated": "cross_paper_simulated",
        "maintenance_margin_notional_usd": quantity * mark,
        "maintenance_margin_estimate": max(0.0, quantity * mark * rate - cum),
        "unrealized_pnl_usd": pnl_usd,
        "unrealized_pnl_bps": pnl_bps,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return position, margin


def _adaptive_stress(*, generated: str = LEDGER_AT, recovery_reserve: float = 200.0):
    return seal_adaptive_stress_envelope(
        {
            "schema_version": "adaptive_portfolio_stress_v1",
            "authority_complete": True,
            "paper_session_id": SESSION,
            "stress_policy_version": "UNIT_ADAPTIVE_STRESS_V1",
            "cadence_policy_version": "UNIT_ADAPTIVE_CADENCE_V1",
            "producer": "adaptive_portfolio_stress_controller",
            "auth_boundary": "PAPER_ADAPTIVE_STRESS_PIT_V1",
            "source_observations_sha256": "f" * 64,
            "generated_at": generated,
            "available_at": generated,
            "decision_time": generated,
            "freshness_budget_seconds": 60.0,
            "guard_lifetime_seconds": 20.0,
            "recovery_reserve_usd": recovery_reserve,
            "scenarios": [
                {
                    "scenario_id": "adaptive_down",
                    "symbol_moves": {"ALTAUSDT": -0.9},
                }
            ],
        }
    )


def _ledger(
    *,
    positions_key: bool = True,
    positions=None,
    margin_rows=None,
    generated=LEDGER_AT,
    adaptive_stress=None,
):
    positions = list(positions or [])
    margin_rows = list(margin_rows or [])
    wallet = 1000.0
    unrealized = sum(float(row["unrealized_pnl_usd"]) for row in margin_rows)
    used = sum(float(row["canonical_margin_usd"]) for row in margin_rows)
    isolated_used = sum(
        float(row["canonical_margin_usd"])
        for row in margin_rows
        if row.get("margin_mode_simulated") == "isolated_paper_simulated"
    )
    cross_unrealized = sum(
        float(row["unrealized_pnl_usd"])
        for row in margin_rows
        if row.get("margin_mode_simulated") == "cross_paper_simulated"
    )
    equity = wallet + unrealized
    margin_base = min(wallet, equity)
    margin = {
        "schema_version": "paper_account_margin_v1",
        "status": "PASS",
        "accounting_complete": True,
        "admission_inputs_valid": True,
        "equity_usd": equity,
        "wallet_balance_usd": wallet,
        "unrealized_pnl_usd": unrealized,
        "used_margin_usd": used,
        "margin_base_usd": margin_base,
        "newly_reserved_margin_usd": 0.0,
        "newly_reserved_included_in_used_margin": True,
        "free_margin_usd": max(0.0, margin_base - used),
        "cross_wallet_balance_usd": wallet - isolated_used,
        "cross_unrealized_pnl_usd": cross_unrealized,
        "cross_equity_usd": wallet - isolated_used + cross_unrealized,
        "open_position_count": len(positions),
        "accounted_open_position_count": len(positions),
        "open_position_canonical_identities_unique": True,
        "position_margin_rows": margin_rows,
        "account_balance_components_complete": True,
        "wallet_balance_source": "SAME_LEDGER_STARTING_EQUITY_PLUS_REALIZED_NET_PNL",
        "equity_source": "SAME_LEDGER_WALLET_BALANCE_PLUS_CURRENT_UNREALIZED_PNL",
        "paper_session_id": SESSION,
        "generated_utc": generated,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    ledger = {
        "schema_version": "paper_ledger_v2",
        "paper_session_id": SESSION,
        "open_position_count": len(positions),
        "paper_account_margin_status": margin,
        "adaptive_portfolio_stress": (
            adaptive_stress
            if adaptive_stress is not None
            else _adaptive_stress(generated=generated)
        ),
        "generated_utc": generated,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if positions_key:
        ledger["open_positions"] = positions
    return ledger


def _cascade(*, status: str = "EVENT_CONFIRMED", generated_at="2026-07-09T05:59:51.000Z"):
    return {
        "schema_version": "cascade_context_v1",
        "symbol": "ALTAUSDT",
        "timeframe": "1m",
        "cascade_context_status": status,
        "cascade_risk_score": 0.8,
        "event_time": "2026-07-09T05:59:40.000Z",
        "available_at": "2026-07-09T05:59:40.000Z",
        "decision_time": "2026-07-09T05:59:50.000Z",
        "generated_at": generated_at,
        "source_available_count": 1,
        "freshness_budget_seconds": 20.0,
        "cadence_policy_version": "UNIT_CASCADE_CADENCE_V1",
        "direction_authority_complete": True,
        "cascade_authority_scope": "PAPER_FORCE_CLOSE",
        "adverse_price_move_direction": "DOWN",
        "direction_policy_version": "UNIT_DIRECTION_V1",
        "direction_evidence_sha256": "d" * 64,
        "fabricated_liquidation_event": False,
        "threshold_lowered": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _run(monkeypatch, redis: FakeRedis):
    monkeypatch.setattr(guard, "_utc_now", lambda: NOW)
    return guard.run_once(redis)


def test_missing_ledger_is_not_equivalent_to_explicit_empty_positions(monkeypatch) -> None:
    missing_redis = FakeRedis()
    missing = _run(monkeypatch, missing_redis)
    assert missing["status"] == "BLOCKED"
    assert missing["directive_authority"] is False
    assert "PAPER_LEDGER_MISSING" in missing["block_reasons"]

    empty_redis = FakeRedis({guard.LEDGER_KEY: _ledger()})
    empty = _run(monkeypatch, empty_redis)
    assert empty["status"] == "AUTHORITATIVE_EMPTY"
    assert empty["directive_authority"] is True
    assert empty["open_position_count"] == 0
    assert empty["directives"] == []


def test_missing_open_positions_key_is_not_treated_as_empty(monkeypatch) -> None:
    redis = FakeRedis({guard.LEDGER_KEY: _ledger(positions_key=False)})
    payload = _run(monkeypatch, redis)
    assert payload["status"] == "BLOCKED"
    assert "PAPER_LEDGER_OPEN_POSITIONS_KEY_MISSING" in payload["block_reasons"]


def test_guard_reads_coherent_ledger_once_and_emits_marginal_stress_close(monkeypatch) -> None:
    position, margin = _position_and_margin()
    redis = FakeRedis(
        {
            guard.LEDGER_KEY: _ledger(positions=[position], margin_rows=[margin]),
            f"{guard.CASCADE_PREFIX}ALTAUSDT:1m": _cascade(),
        }
    )
    payload = _run(monkeypatch, redis)

    assert redis.get_counts[guard.LEDGER_KEY] == 1
    assert payload["status"] == "PASS"
    assert payload["directive_authority"] is True
    assert len(payload["directives"]) == 1
    directive = payload["directives"][0]
    assert directive["action"] == "CLOSE"
    assert directive["reason"] == "ADAPTIVE_PORTFOLIO_STRESS_DE_RISK"
    assert directive["marginal_stress_buffer_relief_if_closed_usd"] > 0.0
    assert directive["paper_session_id"] == SESSION
    assert directive["position_id"] == position["position_id"]
    assert directive["position_generation_id"] == position["position_generation_id"]
    verified, reasons = verify_guard_payload(
        {key: value for key, value in payload.items() if key != "redis_write_success"},
        expected_paper_session_id=SESSION,
        observed_utc=NOW,
    )
    assert reasons == []
    assert len(verified) == 1


def test_stale_or_absent_cascade_status_cannot_trigger(monkeypatch) -> None:
    position, margin = _position_and_margin()
    for status in ("STALE_NO_TRADE", "ABSENT_NO_TRADE"):
        redis = FakeRedis(
            {
                guard.LEDGER_KEY: _ledger(
                    positions=[position],
                    margin_rows=[margin],
                    adaptive_stress=_adaptive_stress(recovery_reserve=0.0),
                ),
                f"{guard.CASCADE_PREFIX}ALTAUSDT:1m": _cascade(status=status),
            }
        )
        payload = _run(monkeypatch, redis)
        assert payload["directive_authority"] is True
        assert payload["directives"] == []


def test_future_or_stale_cascade_clock_cannot_trigger(monkeypatch) -> None:
    position, margin = _position_and_margin()
    future = _cascade(generated_at="2026-07-09T06:00:01.000Z")
    redis = FakeRedis(
        {
            guard.LEDGER_KEY: _ledger(
                positions=[position],
                margin_rows=[margin],
                adaptive_stress=_adaptive_stress(recovery_reserve=0.0),
            ),
            f"{guard.CASCADE_PREFIX}ALTAUSDT:1m": future,
        }
    )
    payload = _run(monkeypatch, redis)
    assert payload["directives"] == []
    state = payload["cascade_by_symbol"]["ALTAUSDT"]
    assert state["trigger_active"] is False
    assert "CASCADE_CONTEXT_CLOCK_ORDER_INVALID" in state["block_reasons"]


def test_stale_ledger_and_generation_mismatch_fail_closed(monkeypatch) -> None:
    position, margin = _position_and_margin()
    stale_redis = FakeRedis(
        {
            guard.LEDGER_KEY: _ledger(
                positions=[position],
                margin_rows=[margin],
                generated="2026-07-09T05:00:00.000Z",
            )
        }
    )
    stale = _run(monkeypatch, stale_redis)
    assert "ADAPTIVE_STRESS_STALE_AT_PORTFOLIO_DECISION" in stale["block_reasons"]

    mismatched = copy.deepcopy(margin)
    mismatched["position_generation_id"] = "old-generation"
    mismatch_redis = FakeRedis(
        {guard.LEDGER_KEY: _ledger(positions=[position], margin_rows=[mismatched])}
    )
    mismatch = _run(monkeypatch, mismatch_redis)
    assert mismatch["status"] == "BLOCKED"
    assert mismatch["directive_authority"] is False


def test_snapshot_exception_is_published_blocked_without_directive(monkeypatch) -> None:
    position, margin = _position_and_margin()
    redis = FakeRedis(
        {guard.LEDGER_KEY: _ledger(positions=[position], margin_rows=[margin])}
    )

    def _raise(**_kwargs):
        raise RuntimeError("unit failure")

    monkeypatch.setattr(guard, "build_portfolio_liquidation_snapshot", _raise)
    payload = _run(monkeypatch, redis)
    assert payload["status"] == "BLOCKED"
    assert payload["directive_authority"] is False
    assert payload["directives"] == []
    assert payload["block_reasons"] == ["PORTFOLIO_SNAPSHOT_EXCEPTION:RuntimeError"]


def test_missing_stress_or_active_hedge_pair_blocks_force_authority(monkeypatch) -> None:
    position, margin = _position_and_margin()
    missing = _run(
        monkeypatch,
        FakeRedis(
            {
                guard.LEDGER_KEY: _ledger(
                    positions=[position],
                    margin_rows=[margin],
                    adaptive_stress={},
                )
            }
        ),
    )
    assert missing["directive_authority"] is False
    assert "ADAPTIVE_STRESS_ENVELOPE_MISSING" not in missing["block_reasons"]
    assert any("ADAPTIVE_STRESS" in reason for reason in missing["block_reasons"])

    paired_position = copy.deepcopy(position)
    paired_position["hedge_pair_id"] = "pair-a"
    paired_position["hedge_state"] = "HEDGE_ACTIVE"
    paired = _run(
        monkeypatch,
        FakeRedis(
            {
                guard.LEDGER_KEY: _ledger(
                    positions=[paired_position],
                    margin_rows=[margin],
                )
            }
        ),
    )
    assert paired["directive_authority"] is False
    assert "ACTIVE_HEDGE_PAIR_REQUIRES_ATOMIC_CLOSE_IMPLEMENTATION" in paired[
        "block_reasons"
    ]


def test_directives_are_ranked_by_positive_marginal_relief_not_current_loss() -> None:
    losing = {
        "position_id": "pos",
        "position_generation_id": "gen",
        "position_evidence_sha256": "b" * 64,
        "symbol": "ALTAUSDT",
        "side": "long",
        "position_quantity": 10.0,
        "entry_price": 100.0,
        "effective_leverage": 5.0,
        "unrealized_pnl_bps": -10.0,
        "margin_mode": "cross",
    }
    winning_protective = {
        **losing,
        "position_id": "hedge",
        "position_generation_id": "hedge-gen",
        "position_evidence_sha256": "d" * 64,
        "symbol": "HEDGEUSDT",
        "side": "short",
        "unrealized_pnl_bps": 30.0,
    }
    snapshot = {
        "authority_complete": True,
        "adaptive_stress_authority_complete": True,
        "portfolio_snapshot_sha256": "c" * 64,
        "worst_case_liquidation_breached": True,
        "worst_case_liquidation_buffer_usd": -10.0,
        "adaptive_recovery_reserve_usd": 20.0,
        "worst_case_scenario": "adaptive_down",
        "adaptive_stress_evidence_sha256": "e" * 64,
        "adaptive_stress_source_observations_sha256": "f" * 64,
        "adaptive_stress_policy_version": "UNIT_STRESS_V1",
        "adaptive_stress_cadence_policy_version": "UNIT_CADENCE_V1",
        "adaptive_stress_freshness_budget_seconds": 60.0,
        "adaptive_guard_lifetime_seconds": 20.0,
        "correlated_shock_scenarios": {
            "adaptive_down": {
                "position_contributions": {
                    "pos": {
                        "position_generation_id": "gen",
                        "symbol": "ALTAUSDT",
                        "symbol_move": -0.2,
                        "shock_pnl_delta_usd": -20.0,
                        "shocked_maintenance_margin_usd": 1.0,
                        "marginal_stress_buffer_relief_if_closed_usd": 21.0,
                    },
                    "hedge": {
                        "position_generation_id": "hedge-gen",
                        "symbol": "HEDGEUSDT",
                        "symbol_move": -0.2,
                        "shock_pnl_delta_usd": -40.0,
                        "shocked_maintenance_margin_usd": 1.0,
                        "marginal_stress_buffer_relief_if_closed_usd": 41.0,
                    },
                }
            }
        },
    }
    kwargs = {
        "paper_session_id": SESSION,
        "source_ledger_generated_utc": LEDGER_AT,
        "source_ledger_sha256": "a" * 64,
        "generated_utc": NOW,
        "expires_utc": "2026-07-09T06:03:00.000Z",
    }
    incomplete = dict(snapshot)
    incomplete.pop("portfolio_level_computed", None)
    assert guard.decide_directives([losing, winning_protective], {}, incomplete, **kwargs) == []

    snapshot["portfolio_level_computed"] = True
    directives = guard.decide_directives(
        [losing, winning_protective], {}, snapshot, **kwargs
    )
    assert len(directives) == 1
    assert directives[0]["position_id"] == "hedge"
    assert directives[0]["unrealized_pnl_bps_at_generation"] > 0.0
    assert directives[0]["stress_close_rank"] == 1
