"""Regression tests for the V2 full-observation portfolio-state burndown.

The portfolio-state expansion is V2-only, paper/shadow, and explicitly
separate from the tracker-derived position-history slice. It may expose
paper/risk/prediction/trainer/orchestrator/alt-data context, but it must
not synthesize accepted fills, PnL, MFE, MAE, ROE, or any trading authority.
"""
from __future__ import annotations

import importlib


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


def _field_map(result):
    return {
        name: (value, source)
        for name, value, source in zip(
            result.field_names,
            result.field_values,
            result.field_sources,
        )
    }


def _base_result(**overrides):
    b = _builder()
    kwargs = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot": None,
        "paper_positions": [],
        "paper_ledger": {},
        "risk_decisions": [],
        "orchestrator_decisions": {},
        "trainer_heartbeat": {},
        "prediction": {},
        "paper_intents": [],
        "paper_intents_held": [],
        "position_history": None,
        "position_price_track": None,
        "altdata_symbol_score": None,
        "altdata_candidates": None,
        "position_history_consumption_allowed": True,
        "position_history_consumption_blocked_reason": None,
    }
    kwargs.update(overrides)
    return b.build_full_observation_for_symbol(**kwargs)


def test_portfolio_state_burndown_fields_use_allowed_v2_sources() -> None:
    result = _base_result(
        paper_positions=[
            {"symbol": "BTCUSDT", "side": "long", "expected_move_after_cost_bps": 11.0}
        ],
        paper_ledger={
            "generated_utc": "2026-05-22T00:00:00Z",
            "accepted": [
                {
                    "symbol": "BTCUSDT",
                    "decision": "ACCEPTED_PAPER_FILL",
                    "paper_fill_allowed": True,
                    "fill_price": 100.0,
                },
                {
                    "symbol": "BTCUSDT",
                    "decision": "SHADOW_OBSERVATION_ONLY",
                    "counted_as_accepted_position": False,
                    "fill_price": 100.0,
                },
            ],
            "shadow_observations": [
                {"symbol": "BTCUSDT", "decision": "SHADOW_OBSERVATION_ONLY"}
            ],
            "held_by_paper_fill_gate": [
                {"symbol": "BTCUSDT", "decision": "HELD_BY_PAPER_FILL_GATE"}
            ],
            "close_event_count": 0,
        },
        risk_decisions=[
            {
                "symbol": "BTCUSDT",
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
            }
        ],
        orchestrator_decisions={
            "generated_utc": "2026-05-22T00:00:00Z",
            "considered_count": 1,
            "bucket_winners": [{"symbol": "BTCUSDT"}],
            "held_by_paper_fill_gate_count": 0,
        },
        trainer_heartbeat={
            "generated_utc": "2026-05-22T00:00:00Z",
            "predictions_count": 1,
            "predictions_with_open_gate": ["BTCUSDT"],
            "predictions_blocked": [],
        },
        prediction={
            "generated_utc": "2026-05-22T00:00:00Z",
            "paper_fill_allowed": True,
            "expected_move_after_cost_bps": 8.5,
            "confidence_calibrated": 0.72,
            "paper_fill_gate_block_reasons": [],
        },
        paper_intents=[
            {"symbol": "BTCUSDT", "decision": "SHADOW_OBSERVATION_ONLY"}
        ],
        position_history={
            "symbol": "BTCUSDT",
            "position_state": "NO_OPEN_POSITION",
            "accepted_intent_count": 0,
            "held_intent_count": 1,
            "shadow_observation_count": 2,
            "max_favorable_bps": None,
            "max_adverse_bps": None,
            "unrealized_bps": None,
        },
        altdata_symbol_score={
            "symbol": "BTCUSDT",
            "generated_utc": "2026-05-22T00:00:00Z",
            "altdata_symbol_score": 0.61,
            "altdata_symbol_rank": 1,
            "provider_availability_score": 0.5,
            "altdata_freshness_score": 0.9,
            "public_intel_score": 0.7,
            "coingecko_discovery_score": 0.8,
            "news_attention_score": 0.3,
            "whale_wall_score": 0.82,
            "whale_bid_pressure_score": 0.9,
            "missing_provider_flags": ["moralis_payload_missing"],
            "stale_provider_flags": [],
        },
        altdata_candidates={
            "generated_utc": "2026-05-22T00:00:00Z",
            "candidate_only_not_adopted": True,
            "live_symbols_expanded": False,
            "paper_symbols_expanded": False,
            "training_symbols_expanded": False,
            "candidates": [
                {
                    "symbol": "BTCUSDT",
                    "candidate_state": "MISSING_PROVIDER_DATA",
                    "candidate_publisher_rank": 1,
                    "proposed_use": [],
                    "live_symbol_candidate": False,
                    "paper_symbol_candidate": False,
                    "training_symbol_candidate": False,
                    "missing_provider_flags": ["moralis_payload_missing"],
                    "stale_provider_flags": [],
                }
            ],
        },
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_ledger_accepted_fill_count"] == (
        1.0,
        "V2_PAPER_LEDGER_ACCEPTED_FILLS_SAFE",
    )
    assert fields["portfolio_state.portfolio_symbol_altdata_score"] == (
        0.61,
        "V2_ALTDATA_SYMBOL_SCORE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_symbol_public_intel_score"] == (
        0.7,
        "V2_ALTDATA_SYMBOL_SCORE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_symbol_coingecko_discovery_score"] == (
        0.8,
        "V2_ALTDATA_SYMBOL_SCORE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_symbol_news_attention_score"] == (
        0.3,
        "V2_ALTDATA_SYMBOL_SCORE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_symbol_whale_wall_score"] == (
        0.82,
        "V2_ALTDATA_SYMBOL_SCORE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_symbol_whale_bid_pressure_score"] == (
        0.9,
        "V2_ALTDATA_SYMBOL_SCORE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_altdata_candidate_only_not_adopted"] == (
        1.0,
        "V2_ALTDATA_CANDIDATE_CONTEXT",
    )
    assert fields["portfolio_state.portfolio_symbol_live_candidate"] == (
        0.0,
        "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY",
    )
    assert result.zero_filled_field_count == 0


def test_shadow_and_held_rows_do_not_count_as_accepted_fills() -> None:
    result = _base_result(
        paper_ledger={
            "accepted_count": 99,
            "accepted": [
                {
                    "symbol": "BTCUSDT",
                    "decision": "SHADOW_OBSERVATION_ONLY",
                    "counted_as_accepted_position": False,
                    "fill_price": 100.0,
                },
                {
                    "symbol": "BTCUSDT",
                    "decision": "HELD_BY_PAPER_FILL_GATE",
                    "paper_fill_allowed": False,
                    "fill_price": 101.0,
                },
            ],
        }
    )
    fields = _field_map(result)
    assert fields["portfolio_state.paper_accepted_count"] == (
        0.0,
        "V2_PAPER_LEDGER",
    )
    assert fields["portfolio_state.portfolio_symbol_accepted_fill_count"] == (
        0.0,
        "V2_PAPER_LEDGER_ACCEPTED_FILLS_SAFE",
    )


def test_portfolio_state_does_not_fabricate_pnl_mfe_mae_or_roe() -> None:
    result = _base_result(
        paper_positions=[],
        paper_ledger={"accepted": [], "closes": [], "close_event_count": 0},
        position_history={
            "symbol": "BTCUSDT",
            "position_state": "NO_OPEN_POSITION",
            "max_favorable_bps": None,
            "max_adverse_bps": None,
            "unrealized_bps": None,
        },
    )
    fields = _field_map(result)
    for field_name, expected_source in (
        ("portfolio_state.portfolio_realized_pnl_bps_sum", "MISSING_V2_REALIZED_PNL"),
        ("portfolio_state.portfolio_realized_pnl_usdt_sum", "MISSING_V2_REALIZED_PNL"),
        ("portfolio_state.portfolio_symbol_unrealized_pnl_bps", "MISSING_V2_UNREALIZED_PNL"),
        ("portfolio_state.portfolio_symbol_unrealized_pnl_usdt", "MISSING_V2_UNREALIZED_PNL"),
        ("portfolio_state.portfolio_tracker_mfe_bps", "MISSING_V2_TRACKER_MFE"),
        ("portfolio_state.portfolio_tracker_mae_bps", "MISSING_V2_TRACKER_MAE"),
        ("portfolio_state.portfolio_tracker_roe_bps", "MISSING_V2_TRACKER_ROE"),
    ):
        assert fields[field_name] == (None, expected_source)
    assert result.zero_filled_field_count == 0


def test_altdata_candidate_context_cannot_authorize_symbol_adoption() -> None:
    result = _base_result(
        altdata_candidates={
            "candidate_only_not_adopted": True,
            "live_symbols_expanded": False,
            "paper_symbols_expanded": False,
            "training_symbols_expanded": False,
            "candidates": [
                {
                    "symbol": "BTCUSDT",
                    "candidate_state": "CANDIDATE_READY",
                    "proposed_use": ["watchlist"],
                    "live_symbol_candidate": False,
                    "paper_symbol_candidate": False,
                    "training_symbol_candidate": False,
                    "missing_provider_flags": [],
                    "stale_provider_flags": [],
                }
            ],
        }
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_altdata_live_symbols_expanded"] == (
        0.0,
        "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY",
    )
    assert fields["portfolio_state.portfolio_altdata_paper_symbols_expanded"] == (
        0.0,
        "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY",
    )
    assert fields["portfolio_state.portfolio_altdata_training_symbols_expanded"] == (
        0.0,
        "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY",
    )
    assert fields["portfolio_state.portfolio_symbol_live_candidate"] == (
        0.0,
        "V2_ALTDATA_CANDIDATE_CONTEXT_NO_ADOPTION_AUTHORITY",
    )


def test_full_observation_status_remains_partial_and_safety_pinned() -> None:
    b = _builder()
    status = b.build_full_observation_status(symbols=("BTCUSDT",), timeframe="1m")
    assert status["state"] == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    assert status["zero_filled_field_count"] == 0
    assert status["no_zero_fill_for_unknown_fields"] is True
    assert status["checkpoint_compatibility_claimed"] is False
    assert status["policy_architecture_parity_claimed"] is False
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["approves_canary"] is False
    assert status["approves_legacy_shutdown"] is False
    assert status["approves_redis_trim"] is False


# ---------------------------------------------------------------------------
# Burndown task 198 — v2_orchestrator_keys_written_count exact-source labelling.
# Exact V2 source key: v2:orchestrator:decisions.
# Contract: when the payload includes the count, label V2_ORCHESTRATOR_DECISIONS;
# when the key is None or the field absent from the payload, label
# MISSING_FROM_V2_ORCHESTRATOR with value None. No zero-fill.
# ---------------------------------------------------------------------------

def test_v2_orchestrator_keys_written_count_present_from_payload() -> None:
    result = _base_result(
        orchestrator_decisions={
            "generated_utc": "2026-05-22T00:00:00Z",
            "considered_count": 3,
            "bucket_winners": [{"symbol": "BTCUSDT"}],
            "v2_orchestrator_keys_written_count": 7,
        },
    )
    fields = _field_map(result)
    assert fields["portfolio_state.v2_orchestrator_keys_written_count"] == (
        7.0,
        "V2_ORCHESTRATOR_DECISIONS",
    )
    assert result.zero_filled_field_count == 0


def test_v2_orchestrator_keys_written_count_missing_label_when_no_key() -> None:
    # Payload present but the field is absent — must NOT silently claim
    # V2_ORCHESTRATOR_DECISIONS; must emit MISSING_FROM_V2_ORCHESTRATOR.
    result_field_absent = _base_result(
        orchestrator_decisions={
            "generated_utc": "2026-05-22T00:00:00Z",
            "considered_count": 3,
            "bucket_winners": [],
        },
    )
    fields = _field_map(result_field_absent)
    assert fields["portfolio_state.v2_orchestrator_keys_written_count"] == (
        None,
        "MISSING_FROM_V2_ORCHESTRATOR",
    )
    # Payload missing entirely — same expected missing label.
    result_key_absent = _base_result(orchestrator_decisions=None)
    fields_no_key = _field_map(result_key_absent)
    assert fields_no_key["portfolio_state.v2_orchestrator_keys_written_count"] == (
        None,
        "MISSING_FROM_V2_ORCHESTRATOR",
    )
    assert result_field_absent.zero_filled_field_count == 0
    assert result_key_absent.zero_filled_field_count == 0


# ---------------------------------------------------------------------------
# Burndown task 200 — portfolio_trainer_heartbeat_age_seconds exact-source.
# Exact V2 source key: v2:trainer:heartbeat (publisher uses finished_at /
# started_at, not generated_utc). When the heartbeat is missing or has no
# usable timestamp, emit MISSING_FROM_V2_TRAINER with value None.
# ---------------------------------------------------------------------------

def test_portfolio_trainer_heartbeat_age_seconds_present_age_monotonic() -> None:
    from datetime import datetime, timedelta, timezone

    finished_at = (
        datetime.now(timezone.utc) - timedelta(seconds=42)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = _base_result(
        trainer_heartbeat={
            "schema_version": "v2_trainer_heartbeat_v1",
            "worker_id": "test",
            "started_at": finished_at,
            "finished_at": finished_at,
            "predictions_count": 1,
            "predictions_with_open_gate": ["BTCUSDT"],
            "predictions_blocked": [],
        },
    )
    fields = _field_map(result)
    value, source = fields["portfolio_state.portfolio_trainer_heartbeat_age_seconds"]
    assert source == "V2_TRAINER_HEARTBEAT"
    assert value is not None
    # Age must be a non-negative number close to 42 seconds (we tolerate
    # the small drift between sample time and field-build time).
    assert 30.0 <= float(value) <= 120.0
    assert result.zero_filled_field_count == 0


# ---------------------------------------------------------------------------
# Burndown field group: v2:risk:decisions exact-source.
# Six fields (tasks 202/204/206/208/210/212) all sourced from the same
# Redis key v2:risk:decisions:
#   portfolio_state.portfolio_symbol_risk_decision_present
#   portfolio_state.portfolio_symbol_pre_trade_allowed
#   portfolio_state.portfolio_symbol_fee_gate_allowed
#   portfolio_state.portfolio_symbol_churn_blocked
#   position_context.pre_trade_allowed
#   position_context.fee_gate_allowed
# (position_context.churn_blocked covered by the helper too)
#   position_context.v2_pre_trade_allowed_rate
#   position_context.v2_fee_gate_allowed_rate
#   position_context.v2_churn_blocked_rate
# ---------------------------------------------------------------------------

_RISK_FIELDS_ALL_SOURCED = {
    "portfolio_state.portfolio_symbol_risk_decision_present": (1.0, "V2_RISK_DECISIONS"),
    "portfolio_state.portfolio_symbol_pre_trade_allowed": (1.0, "V2_RISK_DECISIONS"),
    "portfolio_state.portfolio_symbol_fee_gate_allowed": (1.0, "V2_RISK_DECISIONS"),
    "portfolio_state.portfolio_symbol_churn_blocked": (0.0, "V2_RISK_DECISIONS"),
    "position_context.pre_trade_allowed": (1.0, "V2_RISK_DECISIONS"),
    "position_context.fee_gate_allowed": (1.0, "V2_RISK_DECISIONS"),
    "position_context.churn_blocked": (0.0, "V2_RISK_DECISIONS"),
    "position_context.v2_pre_trade_allowed_rate": (1.0, "V2_RISK_DECISIONS"),
    "position_context.v2_fee_gate_allowed_rate": (1.0, "V2_RISK_DECISIONS"),
    "position_context.v2_churn_blocked_rate": (0.0, "V2_RISK_DECISIONS"),
}


def test_risk_decision_field_group_sources_only_from_v2_risk_decisions() -> None:
    result = _base_result(
        risk_decisions=[
            {
                "symbol": "BTCUSDT",
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
            },
        ],
    )
    fields = _field_map(result)
    for name, expected in _RISK_FIELDS_ALL_SOURCED.items():
        assert fields[name] == expected, name
    assert result.zero_filled_field_count == 0


def test_risk_decision_field_group_payload_absent_emits_payload_missing_label() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    # When the payload key is absent entirely we must emit
    # MISSING_FROM_V2_RISK_DECISIONS (the "payload absent" sentinel).
    expect_payload_missing = {
        "portfolio_state.portfolio_symbol_pre_trade_allowed",
        "portfolio_state.portfolio_symbol_fee_gate_allowed",
        "portfolio_state.portfolio_symbol_churn_blocked",
        "position_context.pre_trade_allowed",
        "position_context.fee_gate_allowed",
        "position_context.churn_blocked",
        "position_context.v2_pre_trade_allowed_rate",
        "position_context.v2_fee_gate_allowed_rate",
        "position_context.v2_churn_blocked_rate",
    }
    for name in expect_payload_missing:
        value, source = fields[name]
        assert value is None, name
        assert source == "MISSING_FROM_V2_RISK_DECISIONS", (name, source)
    # risk_decision_present must NOT fabricate a 1.0/0.0 when the payload
    # is absent — it must stay None with the payload-missing label.
    assert fields["portfolio_state.portfolio_symbol_risk_decision_present"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )
    assert result.zero_filled_field_count == 0


def test_risk_decision_field_group_no_symbol_row_emits_symbol_row_missing_label() -> None:
    # Payload exists with rows for OTHER symbols only — no row for BTCUSDT.
    result = _base_result(
        risk_decisions=[
            {
                "symbol": "ETHUSDT",
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
            },
        ],
    )
    fields = _field_map(result)
    # The "present" field is honestly derivable: publisher exists but no
    # row for this symbol -> 0.0 with a sourced "no symbol row" label.
    assert fields["portfolio_state.portfolio_symbol_risk_decision_present"] == (
        0.0,
        "V2_RISK_DECISIONS_NO_SYMBOL_ROW",
    )
    for name in (
        "portfolio_state.portfolio_symbol_pre_trade_allowed",
        "portfolio_state.portfolio_symbol_fee_gate_allowed",
        "portfolio_state.portfolio_symbol_churn_blocked",
        "position_context.pre_trade_allowed",
        "position_context.fee_gate_allowed",
        "position_context.churn_blocked",
        "position_context.v2_pre_trade_allowed_rate",
        "position_context.v2_fee_gate_allowed_rate",
        "position_context.v2_churn_blocked_rate",
    ):
        value, source = fields[name]
        assert value is None, name
        assert source == "MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW", (
            name,
            source,
        )
    assert result.zero_filled_field_count == 0


def test_risk_decision_field_group_per_field_missing_label_when_row_present_but_field_none() -> None:
    # Row matches but per-field gates are None in the payload.
    result = _base_result(
        risk_decisions=[
            {
                "symbol": "BTCUSDT",
                "pre_trade_allowed": None,
                "fee_gate_allowed": None,
                "churn_blocked": None,
            },
        ],
    )
    fields = _field_map(result)
    # The "present" field IS sourced (row exists), but the per-field
    # values stay None with per-field MISSING labels.
    assert fields["portfolio_state.portfolio_symbol_risk_decision_present"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )
    per_field_expected = {
        "portfolio_state.portfolio_symbol_pre_trade_allowed":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED",
        "portfolio_state.portfolio_symbol_fee_gate_allowed":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED",
        "portfolio_state.portfolio_symbol_churn_blocked":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED",
        "position_context.pre_trade_allowed":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED",
        "position_context.fee_gate_allowed":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED",
        "position_context.churn_blocked":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED",
        "position_context.v2_pre_trade_allowed_rate":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED",
        "position_context.v2_fee_gate_allowed_rate":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED",
        "position_context.v2_churn_blocked_rate":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED",
    }
    for name, expected_source in per_field_expected.items():
        value, source = fields[name]
        assert value is None, name
        assert source == expected_source, (name, source)
    assert result.zero_filled_field_count == 0


def test_risk_decision_field_group_does_not_fall_back_to_paper_or_orchestrator() -> None:
    # Even when paper/orchestrator/trainer/prediction payloads carry truthy
    # signals, the risk-decision fields must NOT borrow truth from them.
    result = _base_result(
        risk_decisions=None,
        paper_positions=[
            {
                "symbol": "BTCUSDT",
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
            }
        ],
        orchestrator_decisions={
            "pre_trade_allowed": True,
            "fee_gate_allowed": True,
            "churn_blocked": False,
        },
        trainer_heartbeat={
            "pre_trade_allowed": True,
            "fee_gate_allowed": True,
            "churn_blocked": False,
        },
        prediction={
            "pre_trade_allowed": True,
            "fee_gate_allowed": True,
            "churn_blocked": False,
        },
    )
    fields = _field_map(result)
    for name in (
        "portfolio_state.portfolio_symbol_risk_decision_present",
        "portfolio_state.portfolio_symbol_pre_trade_allowed",
        "portfolio_state.portfolio_symbol_fee_gate_allowed",
        "portfolio_state.portfolio_symbol_churn_blocked",
        "position_context.pre_trade_allowed",
        "position_context.fee_gate_allowed",
        "position_context.churn_blocked",
        "position_context.v2_pre_trade_allowed_rate",
        "position_context.v2_fee_gate_allowed_rate",
        "position_context.v2_churn_blocked_rate",
    ):
        value, source = fields[name]
        assert value is None, name
        assert source == "MISSING_FROM_V2_RISK_DECISIONS", (name, source)
    assert result.zero_filled_field_count == 0


# Individual per-task test entry points (named per the task spec) so that
# the supervisor's `tests_required` list resolves to concrete test ids.
def test_portfolio_symbol_risk_decision_present_true_when_row_present() -> None:
    result = _base_result(
        risk_decisions=[
            {"symbol": "BTCUSDT", "pre_trade_allowed": True}
        ]
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_risk_decision_present"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_portfolio_symbol_risk_decision_present_missing_label_when_no_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "ETHUSDT", "pre_trade_allowed": True}]
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_risk_decision_present"] == (
        0.0,
        "V2_RISK_DECISIONS_NO_SYMBOL_ROW",
    )


def test_portfolio_symbol_pre_trade_allowed_truth_from_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "BTCUSDT", "pre_trade_allowed": True}]
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_pre_trade_allowed"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_portfolio_symbol_pre_trade_allowed_missing_label_when_no_row() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_pre_trade_allowed"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_portfolio_symbol_fee_gate_allowed_truth_from_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "BTCUSDT", "fee_gate_allowed": True}]
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_fee_gate_allowed"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_portfolio_symbol_fee_gate_allowed_missing_label_when_no_row() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_fee_gate_allowed"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_portfolio_symbol_churn_blocked_truth_from_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "BTCUSDT", "churn_blocked": True}]
    )
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_churn_blocked"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_portfolio_symbol_churn_blocked_missing_label_when_no_row() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["portfolio_state.portfolio_symbol_churn_blocked"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_position_context_pre_trade_allowed_truth_from_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "BTCUSDT", "pre_trade_allowed": True}]
    )
    fields = _field_map(result)
    assert fields["position_context.pre_trade_allowed"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_position_context_pre_trade_allowed_missing_label_when_no_row() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["position_context.pre_trade_allowed"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_position_context_fee_gate_allowed_truth_from_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "BTCUSDT", "fee_gate_allowed": True}]
    )
    fields = _field_map(result)
    assert fields["position_context.fee_gate_allowed"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_position_context_fee_gate_allowed_missing_label_when_no_row() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["position_context.fee_gate_allowed"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_position_context_churn_blocked_truth_from_row() -> None:
    result = _base_result(
        risk_decisions=[{"symbol": "BTCUSDT", "churn_blocked": True}]
    )
    fields = _field_map(result)
    assert fields["position_context.churn_blocked"] == (
        1.0,
        "V2_RISK_DECISIONS",
    )


def test_position_context_churn_blocked_missing_label_when_no_row() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["position_context.churn_blocked"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_position_context_v2_pre_trade_allowed_rate_value_from_history() -> None:
    result = _base_result(
        risk_decisions=[
            {"symbol": "BTCUSDT", "pre_trade_allowed": True},
            {"symbol": "BTCUSDT", "pre_trade_allowed": False},
        ]
    )
    fields = _field_map(result)
    assert fields["position_context.v2_pre_trade_allowed_rate"] == (
        0.5,
        "V2_RISK_DECISIONS",
    )


def test_position_context_v2_pre_trade_allowed_rate_missing_label_when_empty() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["position_context.v2_pre_trade_allowed_rate"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_position_context_v2_fee_gate_allowed_rate_value_from_history() -> None:
    result = _base_result(
        risk_decisions=[
            {"symbol": "BTCUSDT", "fee_gate_allowed": True},
            {"symbol": "BTCUSDT", "fee_gate_allowed": False},
        ]
    )
    fields = _field_map(result)
    assert fields["position_context.v2_fee_gate_allowed_rate"] == (
        0.5,
        "V2_RISK_DECISIONS",
    )


def test_position_context_v2_fee_gate_allowed_rate_missing_label_when_empty() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["position_context.v2_fee_gate_allowed_rate"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


def test_position_context_v2_churn_blocked_rate_value_from_history() -> None:
    result = _base_result(
        risk_decisions=[
            {"symbol": "BTCUSDT", "churn_blocked": True},
            {"symbol": "BTCUSDT", "churn_blocked": False},
        ]
    )
    fields = _field_map(result)
    assert fields["position_context.v2_churn_blocked_rate"] == (
        0.5,
        "V2_RISK_DECISIONS",
    )


def test_position_context_v2_churn_blocked_rate_missing_label_when_empty() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    assert fields["position_context.v2_churn_blocked_rate"] == (
        None,
        "MISSING_FROM_V2_RISK_DECISIONS",
    )


# ---------------------------------------------------------------------------
# Burndown field group: v2:risk:decisions rate-and-churn context.
# Tasks 214 (position_context.churn_blocked), 216 (v2_pre_trade_allowed_rate),
# 218 (v2_fee_gate_allowed_rate), 220 (v2_churn_blocked_rate).
# These hardening tests pin the contract:
#   - exact source only (no paper/orchestrator/trainer/legacy fallback)
#   - explicit per-payload-state missing labels
#   - no fake 0.0 rate when there is no field-truth to compute over
#   - zero_filled_field_count remains 0
# ---------------------------------------------------------------------------

_RATE_AND_CHURN_FIELDS = (
    "position_context.churn_blocked",
    "position_context.v2_pre_trade_allowed_rate",
    "position_context.v2_fee_gate_allowed_rate",
    "position_context.v2_churn_blocked_rate",
)


def test_rate_and_churn_context_payload_absent_emits_payload_missing_label() -> None:
    result = _base_result(risk_decisions=None)
    fields = _field_map(result)
    for name in _RATE_AND_CHURN_FIELDS:
        value, source = fields[name]
        assert value is None, name
        assert source == "MISSING_FROM_V2_RISK_DECISIONS", (name, source)
    assert result.zero_filled_field_count == 0


def test_rate_and_churn_context_no_symbol_row_emits_symbol_row_missing_label() -> None:
    result = _base_result(
        risk_decisions=[
            {
                "symbol": "ETHUSDT",
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
            }
        ],
    )
    fields = _field_map(result)
    for name in _RATE_AND_CHURN_FIELDS:
        value, source = fields[name]
        assert value is None, name
        assert source == "MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW", (name, source)
    assert result.zero_filled_field_count == 0


def test_rate_and_churn_context_per_field_missing_label_when_field_none() -> None:
    result = _base_result(
        risk_decisions=[
            {
                "symbol": "BTCUSDT",
                "pre_trade_allowed": None,
                "fee_gate_allowed": None,
                "churn_blocked": None,
            }
        ],
    )
    fields = _field_map(result)
    per_field_expected = {
        "position_context.churn_blocked":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED",
        "position_context.v2_pre_trade_allowed_rate":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED",
        "position_context.v2_fee_gate_allowed_rate":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED",
        "position_context.v2_churn_blocked_rate":
            "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED",
    }
    for name, expected_source in per_field_expected.items():
        value, source = fields[name]
        assert value is None, name
        assert source == expected_source, (name, source)
    assert result.zero_filled_field_count == 0


def test_rate_and_churn_context_does_not_fall_back_to_paper_or_orchestrator() -> None:
    # Even with truthy paper/orchestrator/trainer/prediction signals, the
    # four risk-decision-sourced fields must NOT borrow truth from them.
    result = _base_result(
        risk_decisions=None,
        paper_positions=[
            {
                "symbol": "BTCUSDT",
                "churn_blocked": False,
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
            }
        ],
        paper_intents=[
            {"symbol": "BTCUSDT", "pre_trade_allowed": True, "fee_gate_allowed": True},
            {"symbol": "BTCUSDT", "pre_trade_allowed": False, "churn_blocked": True},
        ],
        paper_intents_held=[
            {"symbol": "BTCUSDT", "pre_trade_allowed": True, "churn_blocked": False},
        ],
        orchestrator_decisions={
            "pre_trade_allowed": True,
            "fee_gate_allowed": True,
            "churn_blocked": False,
            "held_by_paper_fill_gate": [{"symbol": "BTCUSDT"}],
        },
        trainer_heartbeat={
            "pre_trade_allowed": True,
            "fee_gate_allowed": True,
            "churn_blocked": False,
        },
        prediction={
            "pre_trade_allowed": True,
            "fee_gate_allowed": True,
            "churn_blocked": False,
            "paper_fill_allowed": True,
        },
    )
    fields = _field_map(result)
    for name in _RATE_AND_CHURN_FIELDS:
        value, source = fields[name]
        assert value is None, name
        assert source == "MISSING_FROM_V2_RISK_DECISIONS", (name, source)
    assert result.zero_filled_field_count == 0


def test_rate_fields_do_not_fake_zero_when_no_field_truth() -> None:
    # Row matches but the gate fields are explicitly None (no truth to
    # compute over). The rate fields must NOT collapse to 0.0; they must
    # stay None with a per-field MISSING label.
    result = _base_result(
        risk_decisions=[
            {
                "symbol": "BTCUSDT",
                "pre_trade_allowed": None,
                "fee_gate_allowed": None,
                "churn_blocked": None,
            }
        ],
    )
    fields = _field_map(result)
    for name in (
        "position_context.v2_pre_trade_allowed_rate",
        "position_context.v2_fee_gate_allowed_rate",
        "position_context.v2_churn_blocked_rate",
    ):
        value, source = fields[name]
        assert value is None, name
        assert source.startswith("MISSING_FROM_V2_RISK_DECISIONS_FIELD_"), (
            name,
            source,
        )
    assert result.zero_filled_field_count == 0


def test_rate_fields_compute_real_rate_when_multiple_rows_present() -> None:
    # Two rows for the same symbol: rate must equal mean of truth values.
    result = _base_result(
        risk_decisions=[
            {"symbol": "BTCUSDT", "pre_trade_allowed": True, "fee_gate_allowed": False, "churn_blocked": True},
            {"symbol": "BTCUSDT", "pre_trade_allowed": True, "fee_gate_allowed": True, "churn_blocked": False},
        ]
    )
    fields = _field_map(result)
    assert fields["position_context.v2_pre_trade_allowed_rate"] == (
        1.0, "V2_RISK_DECISIONS",
    )
    assert fields["position_context.v2_fee_gate_allowed_rate"] == (
        0.5, "V2_RISK_DECISIONS",
    )
    assert fields["position_context.v2_churn_blocked_rate"] == (
        0.5, "V2_RISK_DECISIONS",
    )
    assert result.zero_filled_field_count == 0


def test_portfolio_trainer_heartbeat_age_seconds_missing_label_when_no_key() -> None:
    result_no_payload = _base_result(trainer_heartbeat=None)
    fields = _field_map(result_no_payload)
    assert fields["portfolio_state.portfolio_trainer_heartbeat_age_seconds"] == (
        None,
        "MISSING_FROM_V2_TRAINER",
    )
    # Payload present but no usable timestamp — still MISSING_FROM_V2_TRAINER.
    result_no_timestamp = _base_result(
        trainer_heartbeat={
            "schema_version": "v2_trainer_heartbeat_v1",
            "worker_id": "test",
            "predictions_count": 0,
            "predictions_with_open_gate": [],
            "predictions_blocked": [],
        },
    )
    fields_no_ts = _field_map(result_no_timestamp)
    assert fields_no_ts["portfolio_state.portfolio_trainer_heartbeat_age_seconds"] == (
        None,
        "MISSING_FROM_V2_TRAINER",
    )
    assert result_no_payload.zero_filled_field_count == 0
    assert result_no_timestamp.zero_filled_field_count == 0
