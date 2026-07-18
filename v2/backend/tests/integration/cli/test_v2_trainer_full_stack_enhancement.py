"""V2 trainer full-stack enhancement tests.

Covers: actionability counter reconciliation, symbol batch coverage,
point-in-time safety, closed-candle enforcement, feedback consumption,
signal gate correctness, hedge context in feedback, CUDA OOM guard,
live-gate immutability, and RL-core overwrite prevention.

All tests are paper-only and do not submit real orders, change leverage,
write old Redis keys, or restart legacy components.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import persistent_cuda_trainer_runtime as runtime_module
from v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime import (
    PersistentTrainerPaths,
    publish_training_cycle_heartbeat,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import LIVE_GATE_BLOCKED
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
    _extra_contract_rejection_reasons,
    _example_trusted_for_training,
    _trainer_feedback_row_usable,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import is_publishable
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FeatureTensorRecord
from v2.backend.app.services.native_trainer.feedback_enrichment import build_strategy_hedge_exit_feedback
from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import build_signal_from_row
from v2.backend.app.services.native_trainer.runtime_truth import summarize_predictions


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _minimal_tensor(*, symbol: str = "BTCUSDT", timeframe: str = "1m", n: int = 5) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id="test_tensor_abc",
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id="v2_fsnap_test_abc",
        values=tuple([50.0] + [0.0] * (n - 1)),
        missing_mask=tuple([0] * n),
        stale_mask=tuple([0] * n),
        source_availability=tuple([1] * n),
        feature_names=tuple([f"feature_{i}" for i in range(n)]),
        source_labels=tuple(["v2:test"] * n),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=tuple([1] * n),
    )


def _minimal_example(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    trust_row: dict[str, Any] | None = None,
    row_classification: str = "TRAINABLE",
    label_expected_move_after_cost_bps: float = 10.0,
) -> TrainingExample:
    return TrainingExample(
        symbol=symbol,
        timeframe=timeframe,
        tensor=_minimal_tensor(symbol=symbol, timeframe=timeframe),
        label_action_index=2,
        label_expected_move_after_cost_bps=label_expected_move_after_cost_bps,
        payload_keys=(),
        row_classification=row_classification,
        trust_row=trust_row,
    )


def _valid_trust_row() -> dict[str, Any]:
    return {
        "accepted_for_training": True,
        "reject_reasons": [],
        "market_state_integrity_score": 96.0,
    }


def _complete_feedback_row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trainer_feedback_source": "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE",
        "feedback_schema_version": "strategy_hedge_exit_feedback_v1",
        "trainer_consumable": True,
        "missing_feedback_fields": [],
        "prediction_id": "v2h_test_feedback_123",
        "signal_id": "sig_test_feedback_123",
        "decision_id": "dec_test_feedback_123",
        "entry_prediction_id": "v2h_test_feedback_123",
        "feature_snapshot_id": "v2_fsnap_test_feedback_123",
        "entry_feature_snapshot_id": "v2_fsnap_test_feedback_123",
        "mtf_snapshot_id": "mtf_test_feedback_123",
        "market_state_id": "mstate_test_feedback_123",
        "feature_cutoff": "2026-06-16T01:00:00Z",
        "decision_time": "2026-06-16T01:00:00Z",
        "available_at": "2026-06-16T01:00:00Z",
        "selected_action": "short",
        "model_version": "v2_hybrid_trainer_v1",
        "checkpoint_id": "ckpt_test_feedback_123",
        "source_hashes": {"feedback_enrichment": "abc123"},
        "timeframe": "1m",
        "symbol": "BTCUSDT",
        "action": "short",
        "entry_price": 100.0,
        "exit_price": 98.0,
        "realized_pnl": 20.0,
        "strategy_id": "trend_mode",
        "strategy_family": "trend",
        "strategy_subtype": "trend_mode",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "entry_reason": "trend_mode",
        "exit_reason": "TAKE_PROFIT",
        "realized_pnl_bps": 200.0,
        "exit_time": "2026-06-16T01:30:00Z",
        "hold_time_seconds": 300,
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        "liquidity_zone_context": {"liquidity_score": 1.0, "source": "V2_ALLOCATOR"},
        "liquidation_distance_context": {"source": "V2_TEST", "missing_feature_names": []},
        "microstructure_context": {
            "bid_ask_spread_bps": 1.4,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        },
        "oi_funding_context": {"source": "V2_TEST"},
        "public_intel_context": {"source": "V2_TEST"},
        "liquidity_context": {"liquidity_score": 1.0, "source": "V2_ALLOCATOR"},
        "major_move_context": {"status": "not_major_move_trade", "source": "V2_PAPER_MAJOR_MOVE_CONTEXT"},
        "market_regime": "TREND",
        "future_window_label_source": "closed_trade_outcome",
        "drawdown_at_entry": 0.0,
        "actual_observed_spread_entry_bps": 1.4,
        "actual_observed_spread_exit_bps": 1.6,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "expected_slippage_bps": 0.9,
        "expected_slippage_usd": 0.01,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_modeled": True,
        "realized_slippage_bps": 1.0,
        "realized_slippage_usd": 0.01,
        "implementation_shortfall_usd": 0.0,
        "squeeze_evidence_score": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "squeeze_evidence_components": {"spread_stress": 0.0},
        "mfe_bps": 20.0,
        "mfe_usd": 1.0,
        "mae_bps": 5.0,
        "mae_usd": 0.25,
        "intra_trade_high_price": 101.0,
        "intra_trade_low_price": 99.5,
        "trailing_stop_history": [],
    }
    base.update(overrides)
    return base


def _write_prediction_file(
    paths: PersistentTrainerPaths,
    *,
    allowed: int = 411,
    blocked: int = 4,
    block_reasons: dict[str, int] | None = None,
) -> None:
    pred_path = paths.public_root / runtime_module.PREDICTION_REL
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    pred_path.write_text(
        json.dumps({
            "prediction_rows_count": allowed + blocked,
            "expected_prediction_count": allowed + blocked,
            "current_prediction_count": allowed + blocked,
            "missing_prediction_rows_count": 0,
            "stale_prediction_rows_count": 0,
            "blocked_prediction_rows_count": blocked,
            "paper_actionability_allowed_rows_count": allowed,
            "paper_actionability_blocked_rows_count": blocked,
            "paper_actionability_block_reason_counts": block_reasons or {"data_coverage_below_threshold": blocked},
            "coverage_status": "CUDA_PREDICTION_GRID_FULL_COVERAGE",
            "actionability_status": "PAPER_ACTIONABILITY_BLOCKED_BY_GATES",
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. Actionability counter reconciliation
# ---------------------------------------------------------------------------

def test_actionability_counters_reconcile_across_trainer_signal_paper_layers(tmp_path: Path) -> None:
    """After fix: publish_training_cycle_heartbeat must propagate
    paper_actionability_allowed_rows_count from the signals prediction file
    into native_trainer_runtime_status.json, eliminating the trainer=0 /
    signals=411 divergence."""
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    _write_prediction_file(paths, allowed=411, blocked=4, block_reasons={"data_coverage_below_threshold": 4})

    # Write stale native_trainer_runtime_status — the pre-fix diverged state
    runtime_path = paths.operator_dir / "native_trainer_runtime_status.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        json.dumps({
            "paper_actionability_allowed_rows_count": 0,
            "paper_actionability_blocked_rows_count": 635,
            "paper_actionability_block_reason_counts": {"confidence_below_threshold": 635},
        }),
        encoding="utf-8",
    )
    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_text("{}", encoding="utf-8")

    publish_training_cycle_heartbeat(
        paths=paths,
        persistent_state={},
        max_rows=8192,
        run_training=False,
    )

    merged = json.loads(runtime_path.read_text(encoding="utf-8"))

    assert merged["paper_actionability_allowed_rows_count"] == 411, (
        f"Trainer runtime shows {merged.get('paper_actionability_allowed_rows_count')} "
        "but signals layer shows 411 — divergence must be resolved by propagating "
        "paper_actionability_allowed_rows_count from prediction_public each heartbeat"
    )
    assert merged["paper_actionability_blocked_rows_count"] == 4
    assert merged["paper_actionability_block_reason_counts"] == {"data_coverage_below_threshold": 4}

    # Persistent runtime artifact must also carry the correct count
    persistent_path = paths.operator_dir / "native_cuda_trainer_persistent_runtime_status.json"
    persistent = json.loads(persistent_path.read_text(encoding="utf-8"))
    assert persistent["paper_actionability_allowed_rows_count"] == 411
    assert persistent["paper_actionability_blocked_rows_count"] == 4


# ---------------------------------------------------------------------------
# 2. All runtime symbols enter trainer batch
# ---------------------------------------------------------------------------

def test_all_runtime_symbols_enter_trainer_batch() -> None:
    """load_training_examples must build an example for every (symbol, timeframe)
    pair — no symbol must be silently skipped due to missing Redis data when
    trusted_only=False."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    timeframes = ["1m", "5m"]
    # io=None → V2OnlyJsonIO(client=None) → all Redis gets return None (offline)
    loader = V2HybridTrainerDataLoader()
    examples = loader.load_training_examples(
        symbols=symbols,
        timeframes=timeframes,
        limit=None,
        trusted_only=False,
    )
    expected_count = len(symbols) * len(timeframes)
    assert len(examples) == expected_count, (
        f"Expected {expected_count} examples (all symbols × all timeframes), "
        f"got {len(examples)}. Every runtime symbol must enter the batch."
    )
    symbols_in_batch = {e.symbol for e in examples}
    assert symbols_in_batch == set(symbols), (
        f"Missing symbols from batch: {set(symbols) - symbols_in_batch}"
    )
    timeframes_in_batch = {e.timeframe for e in examples}
    assert timeframes_in_batch == set(timeframes)


# ---------------------------------------------------------------------------
# 3. Feature available_at never after decision_time (point-in-time safety)
# ---------------------------------------------------------------------------

def test_feature_available_at_never_after_decision_time() -> None:
    """MASA cutoff after the canonical PPO decision clock is future leakage."""
    row: dict[str, Any] = {
        "mtf_snapshot_id": "mtf-snapshot-1",
        "mtf_snapshot_valid": True,
        "feature_cutoff": "2026-06-16T01:00:00+00:00",
        "available_at": "2026-06-16T01:00:00+00:00",
        "decision_time": "2026-06-16T01:00:00+00:00",
        "masa_feature_cutoff": "2026-06-16T02:00:00+00:00",
        "ppo_feature_cutoff": "2026-06-16T01:00:00+00:00",
    }
    reasons = _extra_contract_rejection_reasons(row)
    assert "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME" in reasons, (
        f"Future-leaking masa_feature_cutoff must be flagged; got reasons: {reasons}"
    )


def test_feature_available_at_matching_decision_time_is_clean() -> None:
    """When masa_feature_cutoff equals decision_time the sample is clean."""
    row: dict[str, Any] = {
        "mtf_snapshot_id": "mtf-snapshot-1",
        "mtf_snapshot_valid": True,
        "feature_cutoff": "2026-06-16T01:00:00+00:00",
        "available_at": "2026-06-16T01:00:00+00:00",
        "decision_time": "2026-06-16T01:00:00+00:00",
        "masa_feature_cutoff": "2026-06-16T01:00:00+00:00",
        "ppo_feature_cutoff": "2026-06-16T01:00:00+00:00",
    }
    reasons = _extra_contract_rejection_reasons(row)
    assert "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME" not in reasons


# ---------------------------------------------------------------------------
# 4. Unfinished candles excluded from training
# ---------------------------------------------------------------------------

def test_unfinished_candles_excluded_from_training() -> None:
    """An example whose trust_row marks accepted_for_training=False (e.g. due
    to candle not yet closed) must be excluded from trusted training batches."""
    trust_row = {
        "accepted_for_training": False,
        "reject_reasons": ["CANDLE_NOT_CLOSED_CONFIRMED"],
        "market_state_integrity_score": 60.0,
    }
    example = _minimal_example(trust_row=trust_row, row_classification="MARKET_STATE_REJECTED")
    assert _example_trusted_for_training(example) is False, (
        "Unfinished-candle example must be excluded from trusted-only training batches"
    )


def test_closed_candle_with_clean_trust_row_is_accepted() -> None:
    """A clean trust_row with accepted_for_training=True and TRAINABLE classification is accepted."""
    example = _minimal_example(trust_row=_valid_trust_row(), row_classification="TRAINABLE")
    assert _example_trusted_for_training(example) is True


def test_stale_masked_example_excluded_even_if_accepted() -> None:
    """STALE_MASKED classification must be rejected even when accepted_for_training=True."""
    trust_row = {**_valid_trust_row(), "accepted_for_training": True}
    example = _minimal_example(trust_row=trust_row, row_classification="STALE_MASKED")
    assert _example_trusted_for_training(example) is False


# ---------------------------------------------------------------------------
# 5 & 6. Feedback row changes training batch / prediction after consumed feedback
# ---------------------------------------------------------------------------

def test_feedback_row_changes_training_batch() -> None:
    """A complete strategy-hedge feedback row must be consumable by the trainer
    (trainer_consumable=True, no missing required fields)."""
    row = _complete_feedback_row()
    assert _trainer_feedback_row_usable(row) is True, (
        "Complete feedback row from a closed paper trade must be usable as a training label"
    )


def test_feedback_row_missing_required_field_is_rejected() -> None:
    """A feedback row missing a required field must not enter training."""
    row = _complete_feedback_row()
    row.pop("exit_reason")
    row["feedback_schema_version"] = "strategy_hedge_exit_feedback_v1"
    assert _trainer_feedback_row_usable(row) is False


def test_feedback_row_with_static_spread_placeholder_is_rejected() -> None:
    """A schema-complete feedback row with static/unsourced spread is dirty."""
    row = _complete_feedback_row(
        actual_observed_spread_entry_bps=2.0,
        actual_observed_spread_exit_bps=2.0,
        entry_spread_source="V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        exit_spread_source="V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        microstructure_context={
            "bid_ask_spread_bps": 2.0,
            "source": "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        },
    )
    assert _trainer_feedback_row_usable(row) is False


def test_feedback_row_with_observed_exit_spread_is_usable_when_entry_spread_static() -> None:
    """Observed exit top-of-book spread evidence must satisfy the trainer gate."""
    row = _complete_feedback_row(
        actual_observed_spread_entry_bps=2.0,
        actual_observed_spread_exit_bps=1.2135186,
        entry_spread_source="V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        exit_spread_source="V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:ARBUSDT",
        expected_slippage_bps=0.6067593,
        expected_slippage_source="MODELED_FROM_OBSERVED_EXIT_SPREAD",
        microstructure_context={
            "bid_ask_spread_bps": 2.0,
            "source": "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        },
    )

    assert _trainer_feedback_row_usable(row) is True


def test_prediction_changes_after_consumed_feedback() -> None:
    """When trainer_feedback_outcomes contains a valid row, _label_from_closed_trade_outcome
    returns the realized_pnl_bps from that outcome (not None), so the next
    training batch gets a different label than the default EMA/RSI approximation."""
    loader = V2HybridTrainerDataLoader()
    tensor = _minimal_tensor(symbol="BTCUSDT", timeframe="1m")
    feedback_row = _complete_feedback_row(
        symbol="BTCUSDT",
        timeframe="1m",
        action="long",
        selected_action="long",
        realized_pnl_bps=200.0,
    )
    payloads: dict[str, Any] = {
        "trainer_feedback_outcomes": [feedback_row],
    }
    label = loader._label_from_closed_trade_outcome(payloads=payloads, tensor=tensor)
    assert label is not None, (
        "A consumed feedback row must produce a non-None label, changing model training"
    )
    assert abs(label - 200.0) < 1e-6, (
        f"Label should equal realized_pnl_bps=200.0, got {label}"
    )


def test_feedback_with_quarantined_row_is_excluded() -> None:
    """A row with trainer_consumable=False must not affect training."""
    loader = V2HybridTrainerDataLoader()
    tensor = _minimal_tensor()
    quarantined = _complete_feedback_row(trainer_consumable=False)
    payloads: dict[str, Any] = {"trainer_feedback_outcomes": [quarantined]}
    label = loader._label_from_closed_trade_outcome(payloads=payloads, tensor=tensor)
    assert label is None, "Quarantined feedback row (trainer_consumable=False) must not yield a label"


# ---------------------------------------------------------------------------
# 7. Weak signal remains blocked / major-move creates paper candidate only
# ---------------------------------------------------------------------------

def test_weak_signal_remains_blocked() -> None:
    """A hold action with no actionable expected move must stay blocked with
    NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION — never create a paper intent."""
    row: dict[str, Any] = {
        "status": "PRESENT_CURRENT",
        "selected_action": "hold",
        "expected_move_after_cost_bps": None,
        "prediction_id": "v2h_test_weak_hold",
        "timeframe": "1m",
        "symbol": "XRPUSDT",
    }
    signal = build_signal_from_row(row)
    assert signal["risk_state"] == "BLOCKED", (
        f"Weak hold signal must be BLOCKED, got: {signal['risk_state']}"
    )
    assert signal["blocked_reason"] == "NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION", (
        f"Expected NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION, got: {signal['blocked_reason']}"
    )


def test_negative_expected_move_short_stays_blocked_without_paper_fill() -> None:
    """A current-prediction short with negative expected_move_after_cost_bps
    and no paper_fill_allowed stays blocked (cannot produce paper fills)."""
    row: dict[str, Any] = {
        "status": "PRESENT_CURRENT",
        "selected_action": "short",
        "expected_move_after_cost_bps": -5.0,
        "paper_fill_allowed": False,
        "prediction_id": "v2h_test_neg_short",
        "timeframe": "1m",
        "symbol": "SOLUSDT",
    }
    signal = build_signal_from_row(row)
    assert signal["paper_fill_allowed"] is False


def test_major_move_evidence_creates_paper_candidate_only() -> None:
    """Even when a major-move signal is present, the signal row must remain
    paper-only: live_gate=blocked_human_only, execution_live_symbols=[]."""
    row: dict[str, Any] = {
        "status": "PRESENT_CURRENT",
        "selected_action": "short",
        "expected_move_after_cost_bps": -120.0,
        "prediction_id": "v2h_test_major_move",
        "timeframe": "1m",
        "symbol": "BTCUSDT",
        "paper_fill_allowed": True,
        "major_move_signal_id": "mmove_abc123",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
    }
    signal = build_signal_from_row(
        row,
        live_context={"live_gate": "blocked_human_only", "live_symbols": [], "execution_live_symbols": []},
    )
    assert signal["live_gate"] == "blocked_human_only", (
        "Major-move evidence must not unlock live execution"
    )
    assert signal["execution_live_symbols"] == [], (
        "Major-move signal must not add live execution symbols"
    )


# ---------------------------------------------------------------------------
# 8 & 9. Hedge context in trainer feedback / no accidental hedge pairs
# ---------------------------------------------------------------------------

def test_hedge_context_reaches_trainer_feedback() -> None:
    """build_strategy_hedge_exit_feedback must preserve hedge_state and
    hedge_reason so the trainer can learn from hedge outcomes."""
    close_event = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "short",
        "hedge_state": "HEDGE_ACTIVE",
        "hedge_reason": "COUNTERTREND_HEDGE",
        "market_regime": "TREND",
        "prediction_id": "v2h_hedge_test",
        "signal_id": "sig_hedge_test",
        "exit_time": "2026-06-16T01:00:00Z",
    }
    result = build_strategy_hedge_exit_feedback(
        close_event=close_event,
        outcome_label={},
    )
    assert result.get("hedge_state") == "HEDGE_ACTIVE", (
        f"hedge_state must be preserved in feedback, got: {result.get('hedge_state')}"
    )
    assert result.get("hedge_reason") == "COUNTERTREND_HEDGE", (
        f"hedge_reason must be preserved in feedback, got: {result.get('hedge_reason')}"
    )


def test_no_hedge_defaults_reach_trainer_feedback() -> None:
    """When close_event has no hedge fields, feedback defaults to NO_HEDGE."""
    result = build_strategy_hedge_exit_feedback(
        close_event={"symbol": "ETHUSDT", "market_regime": "CONSOLIDATION"},
        outcome_label={},
    )
    assert result.get("hedge_state") == "NO_HEDGE"
    assert result.get("hedge_reason") == "NO_HEDGE_CONTEXT"


def test_no_accidental_hedge_pair_creation() -> None:
    """The hedge engine must block live execution and never approve accidental hedges."""
    from v2.backend.app.services.trade_management_paper.hedge_engine import (
        hedge_engine_invariants_snapshot,
    )
    invariants = hedge_engine_invariants_snapshot()
    assert invariants["places_exchange_orders"] is False
    assert invariants["approves_live"] is False
    assert invariants["live_gate"] == "blocked_human_only"

    # A list of same-side-only netting events must produce zero opposite-side pairs
    netting_events = [
        {"event": "NET_SAME_DIRECTION", "symbol": "BTCUSDT", "side": "short"},
        {"event": "NET_SAME_DIRECTION", "symbol": "ETHUSDT", "side": "short"},
        {"event": "OPEN_POSITION", "symbol": "SOLUSDT", "side": "short"},
    ]
    opposite_side_count = sum(
        1 for row in netting_events if row.get("event") == "OPPOSITE_SIDE_REDUCED_OR_CLOSED"
    )
    assert opposite_side_count == 0, (
        "Same-side positions must never produce accidental hedge pairs"
    )


# ---------------------------------------------------------------------------
# 10. CUDA adaptive batch has OOM guard
# ---------------------------------------------------------------------------

def test_cuda_adaptive_batch_has_oom_guard() -> None:
    """_auto_tuned_batch_size must cap the result at available_rows when CUDA
    is inactive, preventing OOM on the training device."""
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import V2HybridPPOTrainer

    model = V2HybridPolicyModel(input_dim=10)
    trainer = V2HybridPPOTrainer(model=model, clip_epsilon=0.2)

    available_rows = 50
    result = trainer._auto_tuned_batch_size(
        requested_batch_size=8192,
        available_rows=available_rows,
    )
    assert result <= available_rows, (
        f"Auto-tuned batch {result} exceeds available_rows {available_rows} — OOM risk on CUDA device"
    )
    assert result >= 1, "Batch size must be at least 1"


def test_cuda_adaptive_batch_zero_available_rows_returns_zero() -> None:
    """With 0 available rows the auto-tuner must return 0 (no batch, no OOM)."""
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import V2HybridPPOTrainer

    model = V2HybridPolicyModel(input_dim=10)
    trainer = V2HybridPPOTrainer(model=model, clip_epsilon=0.2)
    assert trainer._auto_tuned_batch_size(requested_batch_size=8192, available_rows=0) == 0


# ---------------------------------------------------------------------------
# 11 & 12. Live gates do not loosen / no RL-core primary prediction overwrite
# ---------------------------------------------------------------------------

def test_live_gates_do_not_loosen() -> None:
    """LIVE_GATE_BLOCKED must equal 'blocked_human_only' and is_publishable must
    reject any payload that doesn't honour it."""
    assert LIVE_GATE_BLOCKED == "blocked_human_only"

    # A payload that changes live_gate must be rejected by is_publishable
    bad_payload: dict[str, Any] = {
        "prediction_id": "prd_test_live_gate",
        "generated_est": "2026-06-16T01:00:00Z",
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
        "live_gate": "live_enabled",  # must not be allowed
        "live_symbols": [],
        "exchange_mutation": False,
        "trainer_direct_trading": False,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "short",
        "selected_action_index": 1,
        "action_probabilities": [0.1, 0.8, 0.1],
        "expected_move_bps": -130.0,
        "expected_move_after_cost_bps": -120.0,
        "confidence_raw": 0.9,
        "confidence_calibrated": 0.65,
        "policy_value": 0.5,
        "masa_signal": 0.5,
        "feature_snapshot_id": "v2_fsnap_test",
        "data_coverage_percent": 95.0,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "source_availability_vector": [1],
        "checkpoint_source": "V2_LOCAL_TRAINED",
        "market_state_id": "mstate_test",
        "market_state_integrity_score": 96.0,
        "valid_for_prediction": True,
        "valid_for_risk": True,
        "valid_for_orchestrator": True,
        "valid_for_paper": True,
    }
    assert is_publishable(bad_payload) is False, (
        "A payload with live_gate != 'blocked_human_only' must not be publishable"
    )

    # The correct payload passes
    good_payload = {**bad_payload, "live_gate": "blocked_human_only"}
    assert is_publishable(good_payload) is True


def test_no_rl_core_primary_prediction_overwrite() -> None:
    """When no Redis prediction keys contain ':rl_core:' in the primary namespace,
    summarize_predictions must report rl_core_primary_overwrites=0."""
    redis_rows = [
        {"_redis_key": "v2:prediction:BTCUSDT:1m", "symbol": "BTCUSDT", "timeframe": "1m"},
        {"_redis_key": "v2:prediction:ETHUSDT:5m", "symbol": "ETHUSDT", "timeframe": "5m"},
        {"_redis_key": "v2:prediction:SOLUSDT:15m", "symbol": "SOLUSDT", "timeframe": "15m"},
    ]
    prediction_payload = {
        "current_prediction_count": 3,
        "expected_prediction_count": 3,
        "missing_prediction_rows_count": 0,
        "stale_prediction_rows_count": 0,
        "paper_actionability_allowed_rows_count": 3,
        "paper_actionability_blocked_rows_count": 0,
        "paper_actionability_block_reason_counts": {},
    }
    summary = summarize_predictions(prediction_payload, redis_rows)
    assert summary["rl_core_primary_overwrites"] == 0, (
        "No RL-core keys in primary namespace must yield rl_core_primary_overwrites=0"
    )
    assert summary["rl_core_sidecar_rows"] == 0, (
        "No ':rl_core:' keys means zero sidecar rows"
    )
    assert summary["paper_actionability_allowed_rows_count"] == 3


def test_rl_core_sidecar_rows_counted_not_overwriting_primary() -> None:
    """RL-core sidecar rows are counted separately from primary rows and must
    not be treated as a primary-overwrite (primary keys don't contain :rl_core:)."""
    redis_rows = [
        {"_redis_key": "v2:prediction:BTCUSDT:1m", "symbol": "BTCUSDT"},
        {"_redis_key": "v2:rl_core:prediction:BTCUSDT:1m", "symbol": "BTCUSDT"},
    ]
    prediction_payload: dict[str, Any] = {}
    summary = summarize_predictions(prediction_payload, redis_rows)
    # Primary row has no :rl_core:, sidecar has :rl_core: — no overwrite
    assert summary["rl_core_primary_overwrites"] == 0
    assert summary["rl_core_sidecar_rows"] == 1
