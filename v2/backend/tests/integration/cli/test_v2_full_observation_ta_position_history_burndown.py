"""Tests for the V2 full-observation TA + position-history burndown.

Paper-only. No torch import. No legacy filesystem read. No pickle load.
No silent zero-fill.
"""
from __future__ import annotations

import importlib
import sys


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


def _history():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.position_history_aggregator"
    )


# ---------------------------------------------------------------------------
# Lane 1 — TA stabilization
# ---------------------------------------------------------------------------

def test_htf_lf_trend_agreement_computes_when_both_inputs_present() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"htf_ret_pct": 0.5, "rsi_14": 60.0, "macd": 1.0, "macd_hist": 0.5},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    htf = by_name["technical_analysis.htf_lf_trend_agreement"]
    assert htf[1] == 1.0
    assert htf[2] == "V2_DERIVED_FROM_FEATURES"


def test_htf_lf_trend_agreement_neutral_rsi_treats_50_as_agreement() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"htf_ret_pct": -0.014, "rsi_14": 50.0, "macd": 1.0, "macd_hist": 0.5},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    htf = by_name["technical_analysis.htf_lf_trend_agreement"]
    assert htf[1] == 1.0
    assert htf[2] == "V2_DERIVED_FROM_FEATURES"


def test_htf_lf_trend_agreement_emits_specific_blocker_when_rsi_missing() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"htf_ret_pct": 0.5, "macd": 1.0, "macd_hist": 0.5},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    htf = by_name["technical_analysis.htf_lf_trend_agreement"]
    assert htf[1] is None
    assert htf[2] == "MISSING_RSI_14_FROM_V2_FEATURES"


def test_htf_lf_trend_agreement_emits_specific_blocker_when_htf_missing() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"rsi_14": 60.0, "macd": 1.0, "macd_hist": 0.5},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    htf = by_name["technical_analysis.htf_lf_trend_agreement"]
    assert htf[1] is None
    assert htf[2] == "MISSING_HTF_RET_PCT_FROM_V2_FEATURES"


def test_htf_lf_trend_agreement_emits_specific_blocker_when_both_missing() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"macd": 1.0, "macd_hist": 0.5},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    htf = by_name["technical_analysis.htf_lf_trend_agreement"]
    assert htf[1] is None
    assert htf[2] == "MISSING_HTF_RET_PCT_AND_RSI_14_FROM_V2_FEATURES"


def test_htf_lf_trend_agreement_emits_freshness_blocker_when_features_stale() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"htf_ret_pct": 0.5, "rsi_14": 60.0, "macd": 1.0, "macd_hist": 0.5},
        "STALE",
    )
    by_name = {r[0]: r for r in rows}
    htf = by_name["technical_analysis.htf_lf_trend_agreement"]
    assert htf[1] is None
    assert htf[2].startswith("BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT")
    assert "STALE" in htf[2]


def test_macd_signal_strength_explicit_blocker_when_macd_is_zero() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"macd": 0.0, "macd_hist": 0.0, "htf_ret_pct": 0.5, "rsi_14": 60.0},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    sig = by_name["technical_analysis.macd_signal_strength"]
    assert sig[1] is None
    assert sig[2] == "MACD_ZERO_RATIO_UNDEFINED"


def test_macd_signal_strength_explicit_blocker_when_macd_missing() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"macd_hist": 0.5, "htf_ret_pct": 0.5, "rsi_14": 60.0},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    sig = by_name["technical_analysis.macd_signal_strength"]
    assert sig[1] is None
    assert sig[2] == "MISSING_MACD_FROM_V2_FEATURES"


def test_macd_signal_strength_computes_correctly_with_valid_inputs() -> None:
    mod = _builder()
    rows = mod._project_technical_analysis(
        {"macd": 2.0, "macd_hist": 1.0, "htf_ret_pct": 0.5, "rsi_14": 60.0},
        "CURRENT",
    )
    by_name = {r[0]: r for r in rows}
    sig = by_name["technical_analysis.macd_signal_strength"]
    assert sig[1] == 0.5
    assert sig[2] == "V2_DERIVED_FROM_FEATURES"


# ---------------------------------------------------------------------------
# Lane 2 — position-history aggregator
# ---------------------------------------------------------------------------

def _sample_paper_state() -> dict:
    return {
        "paper_positions": [
            {
                "intent_id": "i1",
                "symbol": "BTCUSDT",
                "side": "long",
                "generated_utc": "2026-05-18T05:00:00Z",
                "expected_move_after_cost_bps": 100.0,
                "confidence_calibrated": 0.7,
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
            }
        ],
        "paper_intents": [
            {
                "intent_id": "i1",
                "symbol": "BTCUSDT",
                "pre_trade_allowed": True,
                "fee_gate_allowed": True,
                "churn_blocked": False,
                "generated_utc": "2026-05-18T05:00:00Z",
            },
            {
                "intent_id": "i2",
                "symbol": "BTCUSDT",
                "pre_trade_allowed": False,
                "fee_gate_allowed": True,
                "churn_blocked": True,
                "generated_utc": "2026-05-18T05:00:30Z",
            },
        ],
        "paper_intents_held": [
            {
                "intent_id": "h1",
                "symbol": "SOLUSDT",
                "paper_fill_gate_block_reasons": [
                    "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"
                ],
                "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
                "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
            },
        ],
        "paper_ledger": {
            "accepted_count": 1,
            "blocked_count": 0,
            "held_by_paper_fill_gate_count": 1,
            "accepted": [{"intent_id": "i1", "symbol": "BTCUSDT"}],
            "blocked": [],
            "held_by_paper_fill_gate": [
                {
                    "intent_id": "h1",
                    "symbol": "SOLUSDT",
                    "paper_fill_gate_block_reasons": [
                        "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"
                    ],
                    "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
                    "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
                }
            ],
        },
    }


def test_aggregator_returns_per_symbol_history_for_btc_position() -> None:
    mod = _history()
    state = _sample_paper_state()
    h = mod.aggregate_symbol(
        symbol="BTCUSDT",
        paper_positions=state["paper_positions"],
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
    )
    assert h.position_present is True
    assert h.intents_accepted_count == 1
    assert h.intents_blocked_count == 0
    assert h.intents_held_count == 0
    assert h.pre_trade_allowed_rate == 0.5
    assert h.fee_gate_allowed_rate == 1.0
    assert h.churn_blocked_rate == 0.5
    # MFE / MAE / ROE remain MISSING with explicit V2-owned blocker strings.
    assert h.mfe_bps_v2 is None
    assert h.mae_bps_v2 is None
    assert h.roe_bps_v2 is None
    assert "MISSING_V2_OWNED" in h.mfe_source
    assert "MISSING_V2_OWNED" in h.mae_source
    assert "MISSING_V2_OWNED" in h.roe_source


def test_aggregator_does_not_count_shadow_intents_as_accepted() -> None:
    mod = _history()
    h = mod.aggregate_symbol(
        symbol="BTCUSDT",
        paper_positions=[],
        paper_intents=[
            {
                "intent_id": "shadow-1",
                "symbol": "BTCUSDT",
                "paper_fill_allowed": False,
                "counted_as_accepted_position": False,
                "decision": "SHADOW_OBSERVATION_ONLY",
            }
        ],
        paper_intents_held=[],
        paper_ledger={"accepted": [], "blocked": [], "held_by_paper_fill_gate": []},
    )
    assert h.intents_accepted_count == 0


def test_aggregator_returns_none_position_history_for_unknown_symbol() -> None:
    mod = _history()
    state = _sample_paper_state()
    h = mod.aggregate_symbol(
        symbol="XRPUSDT",
        paper_positions=state["paper_positions"],
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
    )
    assert h.position_present is False
    assert h.hold_time_seconds_current is None
    assert h.intents_accepted_count == 0
    assert h.intents_blocked_count == 0
    assert h.intents_held_count == 0
    assert h.pre_trade_allowed_rate is None
    assert h.fee_gate_allowed_rate is None
    assert h.churn_blocked_rate is None
    assert h.mfe_bps_v2 is None
    assert h.mae_bps_v2 is None
    assert h.roe_bps_v2 is None
    assert h.mfe_source == "MISSING_V2_OWNED_POSITION_RECORD"
    assert h.mae_source == "MISSING_V2_OWNED_POSITION_RECORD"
    assert h.roe_source == "MISSING_V2_OWNED_POSITION_RECORD"


def test_aggregator_held_symbol_counts_held_only() -> None:
    mod = _history()
    state = _sample_paper_state()
    h = mod.aggregate_symbol(
        symbol="SOLUSDT",
        paper_positions=state["paper_positions"],
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
    )
    assert h.position_present is False
    assert h.intents_held_count == 1
    assert h.intents_accepted_count == 0
    assert h.intents_blocked_count == 0
    assert h.block_reason_negative_expected_move_count == 1
    assert h.block_reason_checkpoint_required_count == 1
    assert h.block_reason_trainer_malformed_count == 1


def test_aggregator_counts_block_reasons_from_v2_paper_rows() -> None:
    mod = _history()
    state = _sample_paper_state()
    h = mod.aggregate_symbol(
        symbol="SOLUSDT",
        paper_positions=state["paper_positions"],
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
    )
    payload = h.as_payload()
    assert payload["block_reason_negative_expected_move_count"] == 1
    assert payload["block_reason_checkpoint_required_count"] == 1
    assert payload["block_reason_trainer_malformed_count"] == 1
    assert payload["block_reason_edge_below_threshold_count"] == 0
    assert payload["block_reason_feature_freshness_count"] == 0


def test_aggregator_hold_time_is_positive_for_open_position() -> None:
    import datetime as dt
    mod = _history()
    state = _sample_paper_state()
    # Anchor "now" to a deterministic instant 90s past the open time.
    now = dt.datetime(2026, 5, 18, 5, 1, 30, tzinfo=dt.timezone.utc)
    h = mod.aggregate_symbol(
        symbol="BTCUSDT",
        paper_positions=state["paper_positions"],
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
        now=now,
    )
    assert h.hold_time_seconds_current is not None
    assert 89.0 <= h.hold_time_seconds_current <= 91.0


def test_aggregator_never_writes_redis() -> None:
    import inspect
    mod = _history()
    src = inspect.getsource(mod)
    # Module must not write Redis. It must also never call legacy
    # filesystem paths or torch / pickle.
    assert ".set(" not in src or "redis_client.set" not in src
    assert "pickle.load" not in src
    assert "pickle.loads" not in src
    assert "../AI BOT" not in src


def test_aggregator_payload_carries_safety_invariants() -> None:
    mod = _history()
    state = _sample_paper_state()
    histories = mod.aggregate_all(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        paper_positions=state["paper_positions"],
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
    )
    payload = mod.aggregator_payload(histories)
    for field in (
        "schema_version",
        "generated_utc",
        "symbol_count",
        "per_symbol",
        "no_legacy_filesystem_read",
        "no_legacy_redis_read",
        "no_silent_zero_fill",
        "writes_legacy_redis",
        "writes_exchange_orders",
        "credential_in_payload",
        "gate",
        "symbols_real",
        "live_gate",
        "live_symbols",
        "checkpoint_compatibility_claimed",
        "policy_architecture_parity_claimed",
    ):
        assert field in payload
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["no_silent_zero_fill"] is True
    assert payload["gate"] == "blocked_human_only"
    assert payload["symbols_real"] == []
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["symbol_count"] == 3


# ---------------------------------------------------------------------------
# Lane 3 — position_context slice integration
# ---------------------------------------------------------------------------

def test_position_context_slice_grows_with_v2_history_fields() -> None:
    mod = _builder()
    state = _sample_paper_state()
    # NOTE: After the V2_FULL_OBSERVATION_POSITION_HISTORY_TRACKER_ONLY_CONSUMPTION
    # remediation, the tracker-derived position-context fields consume only
    # the tracker payload (``position_history`` arg), not raw paper inputs.
    # We pass an OPEN tracker payload so the field names still appear and
    # are populated by the new strict tracker-only extractor.
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_TRACKING",
        "accepted_intent_count": 1,
        "held_intent_count": 1,
        "block_reason_count": 0,
        "max_favorable_bps": None,
        "max_adverse_bps": None,
        "unrealized_bps": None,
        "hold_time_seconds": 60.0,
    }
    values, names, sources, missing = mod._build_position_context_slice(
        "BTCUSDT",
        state["paper_positions"],
        [],
        {"selected_action": "long", "paper_fill_allowed": True},
        {},
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    name_set = set(names)
    # Newly-wired V2-owned position-history derived fields:
    assert "position_context.v2_position_history_present" in name_set
    assert "position_context.v2_hold_time_seconds_current" in name_set
    assert "position_context.v2_intents_accepted_count" in name_set
    assert "position_context.v2_intents_blocked_count" in name_set
    assert "position_context.v2_intents_held_count" in name_set
    assert "position_context.v2_pre_trade_allowed_rate" in name_set
    assert "position_context.v2_fee_gate_allowed_rate" in name_set
    assert "position_context.v2_churn_blocked_rate" in name_set
    assert "position_context.v2_mfe_bps" in name_set
    assert "position_context.v2_mae_bps" in name_set
    assert "position_context.v2_roe_bps" in name_set
    assert "position_context.v2_position_age_seconds" in name_set
    assert "position_context.v2_hold_time_proxy_seconds" in name_set
    assert "position_context.v2_block_reason_negative_expected_move_count" in name_set
    assert "position_context.v2_block_reason_checkpoint_required_count" in name_set
    assert "position_context.v2_block_reason_trainer_malformed_count" in name_set
    # MFE/MAE/ROE remain null with a tracker-payload-field-missing source —
    # the tracker payload above does not provide them, and we must NOT
    # fabricate them from raw paper inputs.
    by_name = {n: (v, s) for n, v, s in zip(names, values, sources)}
    for fname in (
        "position_context.v2_mfe_bps",
        "position_context.v2_mae_bps",
        "position_context.v2_roe_bps",
    ):
        v, s = by_name[fname]
        assert v is None
        # Source must indicate the tracker payload field is missing —
        # never a claim that the aggregator computed it from raw paper.
        assert "TRACKER" in s and "MISSING" in s


def test_position_context_history_present_flag_is_one_when_tracker_payload_open() -> None:
    mod = _builder()
    state = _sample_paper_state()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_TRACKING",
        "hold_time_seconds": 120.0,
    }
    values, names, sources, missing = mod._build_position_context_slice(
        "BTCUSDT",
        state["paper_positions"],
        [],
        {"selected_action": "long"},
        {},
        paper_intents=state["paper_intents"],
        paper_intents_held=state["paper_intents_held"],
        paper_ledger=state["paper_ledger"],
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by_name = {n: (v, s) for n, v, s in zip(names, values, sources)}
    assert by_name["position_context.v2_position_history_source_available"][0] == 1.0
    assert by_name["position_context.v2_position_history_present"][0] == 1.0


def test_position_context_history_present_flag_is_zero_when_tracker_no_open_position() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "NO_OPEN_POSITION",
        "accepted_intent_count": 0,
        "held_intent_count": 0,
        "block_reason_count": 0,
    }
    values, names, sources, missing = mod._build_position_context_slice(
        "BTCUSDT",
        [],
        [],
        {"selected_action": "hold"},
        {},
        paper_intents=[],
        paper_intents_held=[],
        paper_ledger={},
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by_name = {n: (v, s) for n, v, s in zip(names, values, sources)}
    assert by_name["position_context.v2_position_history_source_available"][0] == 0.0
    assert by_name["position_context.v2_position_history_present"][0] == 0.0


# ---------------------------------------------------------------------------
# Lane 4 — runtime safety invariants
# ---------------------------------------------------------------------------

def test_full_observation_status_still_holds_invariants() -> None:
    mod = _builder()
    s = mod.build_full_observation_status()
    assert s["state"] == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    assert s["checkpoint_compatibility_claimed"] is False
    assert s["policy_architecture_parity_claimed"] is False
    assert s["zero_filled_field_count"] == 0
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["no_legacy_features_consumed_as_current_truth"] is True
    assert s["no_zero_fill_for_unknown_fields"] is True


def test_no_torch_imported_after_burndown_changes() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )
    importlib.import_module(
        "v2.backend.app.services.rl_core.position_history_aggregator"
    )
    assert "torch" not in sys.modules


def test_no_pickle_load_in_aggregator() -> None:
    import inspect
    mod = _history()
    src = inspect.getsource(mod)
    assert "pickle.load" not in src
    assert "pickle.loads" not in src


def test_no_exchange_mutation_surface_in_aggregator_or_builder() -> None:
    import inspect
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for name in (
        "v2.backend.app.services.rl_core.position_history_aggregator",
        "v2.backend.app.services.rl_core.full_observation_builder",
    ):
        mod = importlib.import_module(name)
        src = inspect.getsource(mod)
        for token in forbidden:
            assert token not in src, f"forbidden token in {name}: {token}"
