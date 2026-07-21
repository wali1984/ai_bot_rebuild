"""Strict cross-margin portfolio evidence invariants."""

from __future__ import annotations

import copy

import pytest

from v2.backend.app.services.paper_trade_management.margin_accounting import (
    build_paper_margin_status,
)
from v2.backend.app.services.risk.cross_margin_liquidation import (
    adaptive_stress_source_observations_sha256,
    build_portfolio_liquidation_snapshot,
    marginal_liquidation_impact,
    seal_adaptive_stress_envelope,
)

NOW = "2026-07-09T06:00:00Z"
PAPER_AUTH_KEY_ID = "unit-paper-v1"
PAPER_AUTH_KEY = b"p" * 32


def _account(**overrides):
    base = {
        "schema_version": "paper_account_margin_v1",
        "status": "PASS",
        "accounting_complete": True,
        "account_balance_components_complete": True,
        "wallet_balance_source": "SAME_LEDGER_STARTING_EQUITY_PLUS_REALIZED_NET_PNL",
        "equity_source": "SAME_LEDGER_WALLET_BALANCE_PLUS_CURRENT_UNREALIZED_PNL",
        "paper_session_id": "paper-session-a",
        "equity_usd": 950.0,
        "wallet_balance_usd": 1000.0,
        "unrealized_pnl_usd": -50.0,
        "used_margin_usd": 600.0,
        "margin_base_usd": 950.0,
        "newly_reserved_margin_usd": 0.0,
        "newly_reserved_included_in_used_margin": True,
        "free_margin_usd": 350.0,
        "cross_wallet_balance_usd": 1000.0,
        "cross_unrealized_pnl_usd": -50.0,
        "cross_equity_usd": 950.0,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    base.update(overrides)
    return base


def _position(
    *,
    position_id: str = "paper_pos_BTCUSDT_a",
    generation_id: str = "generation-a",
    symbol: str = "BTCUSDT",
    side: str = "long",
    quantity: float = 0.05,
    entry: float = 60_000.0,
    mark: float = 59_000.0,
    leverage: float = 5.0,
    rate: float = 0.004,
    cum: float = 0.0,
) -> tuple[dict, dict]:
    direction = 1.0 if side == "long" else -1.0
    pnl_usd = direction * quantity * (mark - entry)
    pnl_bps = direction * (mark - entry) / entry * 10_000.0
    entry_notional = quantity * entry
    mark_notional = quantity * mark
    maintenance = max(0.0, mark_notional * rate - cum)
    position = {
        "position_id": position_id,
        "position_generation_id": generation_id,
        "paper_session_id": "paper-session-a",
        "symbol": symbol,
        "side": side,
        "net_quantity": quantity,
        "avg_entry_price": entry,
        "last_mark_price": mark,
        "effective_leverage": leverage,
        "gross_notional_usd": entry_notional,
        "maintenance_margin_rate": rate,
        "maintenance_margin_cum": cum,
        "maintenance_margin_mark_price": mark,
        "maintenance_margin_mark_time": NOW,
        "maintenance_margin_mark_event_time": NOW,
        "maintenance_margin_mark_generated_at": NOW,
        "maintenance_margin_mark_available_at": NOW,
        "maintenance_margin_mark_decision_time": NOW,
        "maintenance_margin_mark_source": "UNIT_AUTHENTICATED_MARK",
        "maintenance_margin_mark_evidence_sha256": "a" * 64,
        "maintenance_margin_mark_contract_authoritative": True,
        "maintenance_margin_mark_freshness_budget_seconds": 1.0,
        "maintenance_margin_mark_cadence_policy_version": "UNIT_CADENCE_V1",
        "maintenance_margin_mark_consumer_validation_boundary": (
            "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
        ),
        "margin_mode_simulated": "cross_paper_simulated",
        "maintenance_margin_notional_usd": mark_notional,
        "maintenance_margin_estimate": maintenance,
        "unrealized_pnl": pnl_usd,
        "unrealized_pnl_bps": pnl_bps,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    margin = {
        "row_id": position_id,
        "position_generation_id": generation_id,
        "paper_session_id": "paper-session-a",
        "symbol": symbol,
        "accounting_scope": "OPEN_EXECUTED_POSITION",
        "valid": True,
        "effective_leverage": leverage,
        "canonical_notional_usd": entry_notional,
        "canonical_margin_usd": entry_notional / leverage,
        "maintenance_margin_rate": rate,
        "maintenance_margin_cum": cum,
        "maintenance_margin_mark_price": mark,
        "maintenance_margin_mark_time": NOW,
        "maintenance_margin_mark_event_time": NOW,
        "maintenance_margin_mark_generated_at": NOW,
        "maintenance_margin_mark_available_at": NOW,
        "maintenance_margin_mark_decision_time": NOW,
        "maintenance_margin_mark_source": "UNIT_AUTHENTICATED_MARK",
        "maintenance_margin_mark_evidence_sha256": "a" * 64,
        "maintenance_margin_mark_contract_authoritative": True,
        "maintenance_margin_mark_freshness_budget_seconds": 1.0,
        "maintenance_margin_mark_cadence_policy_version": "UNIT_CADENCE_V1",
        "maintenance_margin_mark_consumer_validation_boundary": (
            "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
        ),
        "margin_mode_simulated": "cross_paper_simulated",
        "maintenance_margin_notional_usd": mark_notional,
        "maintenance_margin_estimate": maintenance,
        "unrealized_pnl_usd": pnl_usd,
        "unrealized_pnl_bps": pnl_bps,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return position, margin


def _adaptive_stress(*pairs, account=None):
    if account is None:
        wallet = 1000.0
        pnl = sum(
            float(value)
            for pair in pairs
            if isinstance((value := pair[0].get("unrealized_pnl")), int | float)
            and not isinstance(value, bool)
        )
        used = sum(pair[1]["canonical_margin_usd"] for pair in pairs)
        equity = wallet + pnl
        account = _account(
            wallet_balance_usd=wallet,
            equity_usd=equity,
            unrealized_pnl_usd=pnl,
            used_margin_usd=used,
            margin_base_usd=min(wallet, equity),
            free_margin_usd=max(0.0, min(wallet, equity) - used),
            cross_wallet_balance_usd=wallet,
            cross_unrealized_pnl_usd=pnl,
            cross_equity_usd=equity,
        )
    symbols = {pair[0]["symbol"] for pair in pairs}
    # Candidate hedge symbols are explicit scenario evidence too; production
    # must derive these moves from PIT data rather than a default beta.
    symbols.update({"BTCUSDT", "ETHUSDT", "SOLUSDT", "TOP5_BASKET"})
    try:
        source_observations_sha256 = adaptive_stress_source_observations_sha256(
            account=account,
            positions=[pair[0] for pair in pairs],
            position_margin_rows=[pair[1] for pair in pairs],
        )
    except ValueError:
        # Invalid/non-finite test rows are rejected before stress authority is
        # considered; keep the envelope serializable so that assertion reaches
        # the intended controlling-evidence gate.
        source_observations_sha256 = "0" * 64
    return seal_adaptive_stress_envelope(
        {
            "schema_version": "adaptive_portfolio_stress_v1",
            "authority_complete": True,
            "paper_session_id": "paper-session-a",
            "stress_policy_version": "UNIT_PIT_STRESS_POLICY_V1",
            "cadence_policy_version": "UNIT_LEDGER_CADENCE_V1",
            "producer": "adaptive_portfolio_stress_controller",
            "auth_boundary": "PAPER_ADAPTIVE_STRESS_PIT_V1",
            "source_observations_sha256": source_observations_sha256,
            "freshness_budget_seconds": 45.0,
            "guard_lifetime_seconds": 30.0,
            "hedge_candidate_maintenance": {
                symbol: {
                    "authority_complete": True,
                    "source": "AUTHENTICATED_BINANCE_USDM_LEVERAGE_BRACKET",
                    "maintenance_margin_rate": 0.005,
                    "maintenance_margin_cum": 0.0,
                    "evidence_sha256": "b" * 64,
                }
                for symbol in symbols
            },
            "generated_at": NOW,
            "available_at": NOW,
            "decision_time": NOW,
            "recovery_reserve_usd": 0.0,
            "scenarios": [
                {
                    "scenario_id": "adaptive_down",
                    "symbol_moves": {symbol: -0.20 for symbol in symbols},
                },
                {
                    "scenario_id": "adaptive_up",
                    "symbol_moves": {symbol: 0.10 for symbol in symbols},
                },
            ],
        },
        authentication_key_id=PAPER_AUTH_KEY_ID,
        authentication_key=PAPER_AUTH_KEY,
    )


def _snapshot(*pairs, account=None, adaptive_stress_envelope=None):
    if account is None:
        wallet = 1000.0
        pnl = sum(
            float(value)
            for pair in pairs
            if isinstance((value := pair[0].get("unrealized_pnl")), int | float)
            and not isinstance(value, bool)
        )
        used = sum(pair[1]["canonical_margin_usd"] for pair in pairs)
        equity = wallet + pnl
        margin_base = min(wallet, equity)
        account = _account(
            wallet_balance_usd=wallet,
            equity_usd=equity,
            unrealized_pnl_usd=pnl,
            used_margin_usd=used,
            margin_base_usd=margin_base,
            free_margin_usd=max(0.0, margin_base - used),
            cross_wallet_balance_usd=wallet,
            cross_unrealized_pnl_usd=pnl,
            cross_equity_usd=equity,
        )
    return build_portfolio_liquidation_snapshot(
        account=account,
        positions=[pair[0] for pair in pairs],
        position_margin_rows=[pair[1] for pair in pairs],
        generated_utc=NOW,
        adaptive_stress_envelope=(
            adaptive_stress_envelope
            if adaptive_stress_envelope is not None
            else _adaptive_stress(*pairs, account=account)
        ),
        adaptive_stress_authentication_keys={
            PAPER_AUTH_KEY_ID: PAPER_AUTH_KEY
        },
    )


def test_portfolio_level_buffer_uses_mark_based_maintenance() -> None:
    btc = _position()
    sol = _position(
        position_id="paper_pos_SOLUSDT_b",
        generation_id="generation-b",
        symbol="SOLUSDT",
        quantity=20.0,
        entry=150.0,
        mark=140.0,
        leverage=10.0,
        rate=0.01,
        cum=2.0,
    )
    snapshot = _snapshot(btc, sol)

    expected_maintenance = (0.05 * 59_000.0 * 0.004) + (20.0 * 140.0 * 0.01 - 2.0)
    assert snapshot["authority_complete"] is True
    assert snapshot["portfolio_level_computed"] is True
    assert snapshot["open_position_count"] == 2
    assert snapshot["maintenance_margin_usd"] == pytest.approx(expected_maintenance)
    assert snapshot["portfolio_liquidation_buffer_usd"] == pytest.approx(
        750.0 - expected_maintenance
    )
    assert len(snapshot["position_liquidation_register"]) == 2


def test_correlated_shock_can_breach_authoritative_portfolio() -> None:
    sol = _position(
        position_id="sol",
        generation_id="sol-gen",
        symbol="SOLUSDT",
        quantity=100.0,
        entry=150.0,
        mark=150.0,
        leverage=20.0,
        rate=0.01,
    )
    eth = _position(
        position_id="eth",
        generation_id="eth-gen",
        symbol="ETHUSDT",
        quantity=3.0,
        entry=3000.0,
        mark=3000.0,
        leverage=20.0,
        rate=0.01,
    )
    snapshot = _snapshot(
        sol,
        eth,
        account=_account(
            equity_usd=300.0,
            wallet_balance_usd=300.0,
            unrealized_pnl_usd=0.0,
            used_margin_usd=1200.0,
            margin_base_usd=300.0,
            free_margin_usd=0.0,
            cross_wallet_balance_usd=300.0,
            cross_unrealized_pnl_usd=0.0,
            cross_equity_usd=300.0,
        ),
    )

    assert snapshot["portfolio_level_computed"] is True
    assert snapshot["correlated_shock_scenarios"]["adaptive_down"][
        "liquidation_breached"
    ] is True


@pytest.mark.parametrize(
    ("target", "field", "value", "reason"),
    [
        ("position", "effective_leverage", None, "POSITION_EFFECTIVE_LEVERAGE"),
        ("position", "effective_leverage", True, "POSITION_EFFECTIVE_LEVERAGE"),
        ("position", "maintenance_margin_rate", 0.0, "POSITION_MAINTENANCE_RATE"),
        ("position", "last_mark_price", float("nan"), "POSITION_MARK_PRICE"),
        ("position", "unrealized_pnl", None, "UNREALIZED_PNL_USD"),
        ("margin", "unrealized_pnl_bps", float("inf"), "UNREALIZED_PNL_BPS"),
    ],
)
def test_missing_or_nonfinite_controlling_evidence_blocks(
    target: str, field: str, value: object, reason: str
) -> None:
    position, margin = _position()
    (position if target == "position" else margin)[field] = value

    snapshot = _snapshot((position, margin))

    assert snapshot["authority_complete"] is False
    assert snapshot["portfolio_level_computed"] is False
    assert any(
        reason in item
        for row in snapshot["invalid_position_rows"]
        for item in row.get("reasons", [])
    )


def test_net_quantity_is_magnitude_and_requires_explicit_side() -> None:
    position, margin = _position()
    position["net_quantity"] = -position["net_quantity"]
    negative = _snapshot((position, margin))
    assert negative["authority_complete"] is False

    position, margin = _position()
    position.pop("side")
    missing_side = _snapshot((position, margin))
    assert missing_side["authority_complete"] is False
    assert any(
        "NET_QUANTITY_REQUIRES_EXPLICIT" in reason
        for row in missing_side["invalid_position_rows"]
        for reason in row.get("reasons", [])
    )


def test_position_and_margin_rows_must_match_account_session() -> None:
    position, margin = _position()
    position["paper_session_id"] = "old-session"
    snapshot = _snapshot((position, margin))
    assert snapshot["authority_complete"] is False
    assert any(
        "POSITION_PAPER_SESSION_ID_MISMATCH" in reason
        for row in snapshot["invalid_position_rows"]
        for reason in row.get("reasons", [])
    )


def test_signed_position_amount_can_infer_side_only_in_both_mode() -> None:
    position, margin = _position(side="short")
    position.pop("net_quantity")
    position.pop("side")
    position["positionAmt"] = -0.05
    position["positionSide"] = "BOTH"
    assert _snapshot((position, margin))["authority_complete"] is True

    position["positionSide"] = "SHORT"
    blocked = _snapshot((position, margin))
    assert blocked["authority_complete"] is False
    assert any(
        "SIDE_INFERENCE_REQUIRES_BOTH" in reason
        for row in blocked["invalid_position_rows"]
        for reason in row.get("reasons", [])
    )


def test_exact_position_id_and_generation_join_rejects_stale_and_extra_rows() -> None:
    position, margin = _position()
    stale = copy.deepcopy(margin)
    stale["position_generation_id"] = "old-generation"
    stale_snapshot = _snapshot((position, stale))
    assert stale_snapshot["authority_complete"] is False
    assert "OPEN_POSITION_HAS_NO_EXACT_MARGIN_ROW" in stale_snapshot["block_reasons"]

    extra = copy.deepcopy(margin)
    extra["row_id"] = "extra-position"
    extra["position_generation_id"] = "extra-generation"
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=[position],
        position_margin_rows=[margin, extra],
        generated_utc=NOW,
    )
    assert snapshot["authority_complete"] is False
    assert "OPEN_POSITION_AND_MARGIN_ROW_COUNTS_DIFFER" in snapshot["block_reasons"]
    assert "POSITION_MARGIN_ROWS_CONTAIN_EXTRAS_OR_REUSE" in snapshot["block_reasons"]

    second_position, second_margin = _position(
        generation_id="generation-b",
        mark=58_000.0,
    )
    reused = _snapshot((position, margin), (second_position, second_margin))
    assert reused["authority_complete"] is False
    assert "OPEN_POSITION_ID_REUSED_ACROSS_GENERATIONS" in reused["block_reasons"]
    assert "POSITION_MARGIN_ROW_ID_REUSED_ACROSS_GENERATIONS" in reused[
        "block_reasons"
    ]


def test_mark_notional_rate_cum_and_maintenance_must_crosscheck() -> None:
    position, margin = _position(mark=59_000.0, rate=0.004, cum=1.0)
    margin["maintenance_margin_estimate"] += 0.01

    snapshot = _snapshot((position, margin))

    assert snapshot["authority_complete"] is False
    assert any(
        reason == "MARK_BASED_MAINTENANCE_RECONCILIATION_FAILED"
        for row in snapshot["invalid_position_rows"]
        for reason in row.get("reasons", [])
    )


def test_zero_pnl_is_preserved_as_evidence_not_treated_as_missing() -> None:
    pair = _position(mark=60_000.0)
    snapshot = _snapshot(pair)
    assert snapshot["authority_complete"] is True
    assert snapshot["positions"][0]["unrealized_pnl_usd"] == 0.0
    assert snapshot["positions"][0]["unrealized_pnl_bps"] == 0.0


def test_stale_or_future_mark_time_blocks() -> None:
    position, margin = _position()
    position["maintenance_margin_mark_time"] = "2026-07-09T05:00:00Z"
    margin["maintenance_margin_mark_time"] = position["maintenance_margin_mark_time"]
    assert _snapshot((position, margin))["authority_complete"] is False

    position["maintenance_margin_mark_time"] = "2026-07-09T06:00:01Z"
    margin["maintenance_margin_mark_time"] = position["maintenance_margin_mark_time"]
    assert _snapshot((position, margin))["authority_complete"] is False


def test_explicit_empty_positions_and_margin_rows_is_authoritative() -> None:
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(
            equity_usd=1000.0,
            wallet_balance_usd=1000.0,
            unrealized_pnl_usd=0.0,
            used_margin_usd=0.0,
            margin_base_usd=1000.0,
            free_margin_usd=1000.0,
            cross_wallet_balance_usd=1000.0,
            cross_unrealized_pnl_usd=0.0,
            cross_equity_usd=1000.0,
        ),
        positions=[],
        position_margin_rows=[],
        generated_utc=NOW,
    )
    assert snapshot["authority_complete"] is True
    assert snapshot["portfolio_level_computed"] is True
    assert snapshot["open_position_count"] == 0
    assert snapshot["worst_case_liquidation_breached"] is None
    assert snapshot["adaptive_stress_authority_complete"] is False


def test_missing_or_tampered_adaptive_stress_never_authorizes_breach() -> None:
    pair = _position()
    missing = _snapshot(pair, adaptive_stress_envelope={})
    assert missing["authority_complete"] is True
    assert missing["adaptive_stress_authority_complete"] is False
    assert missing["worst_case_liquidation_breached"] is None

    tampered = _adaptive_stress(pair)
    tampered["recovery_reserve_usd"] = 999_999.0
    forged = _snapshot(pair, adaptive_stress_envelope=tampered)
    assert forged["authority_complete"] is True
    assert forged["adaptive_stress_authority_complete"] is False
    assert "ADAPTIVE_STRESS_EVIDENCE_HASH_INVALID" in forged[
        "adaptive_stress_block_reasons"
    ]


def test_recomputed_stress_self_hash_wrong_key_and_stale_source_fail_closed() -> None:
    pair = _position()
    original = _adaptive_stress(pair)
    attacker_material = {
        key: value
        for key, value in original.items()
        if key
        not in {
            "evidence_sha256",
            "evidence_auth_algorithm",
            "evidence_auth_key_id",
            "evidence_auth_trust_domain",
            "evidence_hmac_sha256",
        }
    }
    attacker_material["recovery_reserve_usd"] = 999_999.0
    wrong_key_forgery = seal_adaptive_stress_envelope(
        attacker_material,
        authentication_key_id=PAPER_AUTH_KEY_ID,
        authentication_key=b"w" * 32,
    )
    forged = _snapshot(pair, adaptive_stress_envelope=wrong_key_forgery)
    assert forged["adaptive_stress_authority_complete"] is False
    assert "ADAPTIVE_STRESS_AUTH_TAG_MISMATCH" in forged[
        "adaptive_stress_block_reasons"
    ]
    assert "ADAPTIVE_STRESS_EVIDENCE_HASH_INVALID" not in forged[
        "adaptive_stress_block_reasons"
    ]

    changed_position = copy.deepcopy(pair[0])
    changed_margin = copy.deepcopy(pair[1])
    changed_position["attacker_metadata"] = "replayed-against-different-ledger"
    replayed = _snapshot(
        (changed_position, changed_margin),
        adaptive_stress_envelope=original,
    )
    assert replayed["adaptive_stress_authority_complete"] is False
    assert "ADAPTIVE_STRESS_SOURCE_OBSERVATIONS_MISMATCH" in replayed[
        "adaptive_stress_block_reasons"
    ]


def test_isolated_position_is_excluded_from_cross_stress_pool() -> None:
    cross = _position()
    isolated = _position(
        position_id="isolated-sol",
        generation_id="isolated-sol-gen",
        symbol="SOLUSDT",
        quantity=2.0,
        entry=100.0,
        mark=90.0,
        leverage=2.0,
        rate=0.01,
    )
    isolated[0]["margin_mode_simulated"] = "isolated_paper_simulated"
    isolated[1]["margin_mode_simulated"] = "isolated_paper_simulated"
    wallet = 1000.0
    pnl = cross[0]["unrealized_pnl"] + isolated[0]["unrealized_pnl"]
    used = cross[1]["canonical_margin_usd"] + isolated[1]["canonical_margin_usd"]
    isolated_used = isolated[1]["canonical_margin_usd"]
    account = _account(
        wallet_balance_usd=wallet,
        equity_usd=wallet + pnl,
        unrealized_pnl_usd=pnl,
        used_margin_usd=used,
        margin_base_usd=wallet + pnl,
        free_margin_usd=max(0.0, wallet + pnl - used),
        cross_wallet_balance_usd=wallet - isolated_used,
        cross_unrealized_pnl_usd=cross[0]["unrealized_pnl"],
        cross_equity_usd=wallet - isolated_used + cross[0]["unrealized_pnl"],
    )
    snapshot = _snapshot(cross, isolated, account=account)
    assert snapshot["authority_complete"] is True
    assert snapshot["cross_position_count"] == 1
    assert snapshot["isolated_position_count"] == 1
    assert {row["position_id"] for row in snapshot["position_liquidation_register"]} == {
        cross[0]["position_id"]
    }
    assert "isolated-sol" not in snapshot["correlated_shock_scenarios"][
        "adaptive_down"
    ]["position_contributions"]


def test_account_pnl_used_margin_and_mode_mismatch_each_block() -> None:
    position, margin = _position()
    for account_override, target_override in (
        ({"unrealized_pnl_usd": -49.0}, None),
        ({"used_margin_usd": 601.0}, None),
        ({"free_margin_usd": 349.0}, None),
        ({}, "isolated_paper_simulated"),
    ):
        candidate_position = copy.deepcopy(position)
        candidate_margin = copy.deepcopy(margin)
        if target_override is not None:
            candidate_margin["margin_mode_simulated"] = target_override
        snapshot = _snapshot(
            (candidate_position, candidate_margin),
            account=_account(**account_override),
        )
        assert snapshot["authority_complete"] is False


def test_missing_mark_cadence_or_stale_stress_budget_blocks_force_authority() -> None:
    position, margin = _position()
    position.pop("maintenance_margin_mark_cadence_policy_version")
    margin.pop("maintenance_margin_mark_cadence_policy_version")
    assert _snapshot((position, margin))["authority_complete"] is False

    pair = _position()
    stale = _adaptive_stress(pair)
    stale["freshness_budget_seconds"] = 0.5
    stale["generated_at"] = "2026-07-09T05:59:00Z"
    stale["available_at"] = "2026-07-09T05:59:00Z"
    stale["decision_time"] = "2026-07-09T05:59:00Z"
    stale = seal_adaptive_stress_envelope(
        stale,
        authentication_key_id=PAPER_AUTH_KEY_ID,
        authentication_key=PAPER_AUTH_KEY,
    )
    snapshot = _snapshot(pair, adaptive_stress_envelope=stale)
    assert snapshot["adaptive_stress_authority_complete"] is False
    assert "ADAPTIVE_STRESS_STALE_AT_PORTFOLIO_DECISION" in snapshot[
        "adaptive_stress_block_reasons"
    ]


def test_margin_accounting_rows_echo_generation_and_mark_evidence_for_exact_join() -> None:
    position, _ = _position(leverage=1.0)
    status = build_paper_margin_status(
        equity=10_000.0,
        wallet_balance=10_000.0,
        open_positions=[position],
        min_available_margin_buffer_pct=0.0,
        newly_reserved_margin_usd=0.0,
        reservations_included_in_open_positions=True,
    )

    assert status["status"] == "PASS"
    row = status["position_margin_rows"][0]
    assert row["row_id"] == position["position_id"]
    assert row["position_generation_id"] == position["position_generation_id"]
    assert row["maintenance_margin_mark_price"] == position[
        "maintenance_margin_mark_price"
    ]
    assert row["maintenance_margin_mark_time"] == position[
        "maintenance_margin_mark_time"
    ]
    assert row["unrealized_pnl_usd"] == position["unrealized_pnl"]


def test_marginal_impact_requires_authoritative_snapshot() -> None:
    snapshot = _snapshot(_position())
    impact = marginal_liquidation_impact(
        snapshot=snapshot,
        added_notional_usd=1000.0,
        added_symbol="BTCUSDT",
        added_side="short",
        added_maint_rate=0.004,
        added_maint_cum=0.0,
    )
    assert impact["authority_complete"] is True
    assert impact["maintenance_margin_added_usd"] > 0.0
    assert impact["worsens_liquidation_buffer"] is False
    assert impact["marginal_stress_buffer_improvement_usd"] > 0.0

    blocked = marginal_liquidation_impact(
        snapshot={"portfolio_liquidation_buffer_usd": 100.0},
        added_notional_usd=1000.0,
        added_symbol="BTCUSDT",
        added_side="short",
        added_maint_rate=0.004,
        added_maint_cum=0.0,
    )
    assert blocked["risk_decision_blocked"] is True
    assert blocked["worsens_liquidation_buffer"] is None
