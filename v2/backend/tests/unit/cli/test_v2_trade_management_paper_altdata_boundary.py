"""Paper-loop authority tests for canonical alt-data reconstruction."""

from __future__ import annotations

import ast
import copy
import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.paper_trade_management import canonical_altdata_authority
from v2.backend.app.services.preemptive_edge_control import decision as decision_module


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str | bytes] = {}
        self.read_keys: list[str] = []

    def get(self, key: str) -> str | bytes | None:
        self.read_keys.append(key)
        return self.data.get(key)

    def set_payload(self, key: str, payload: dict[str, Any]) -> None:
        self.data[key] = json.dumps(payload)


def _utc(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clocks(base: datetime, *, available_age_seconds: float = 2.0) -> dict[str, str]:
    available_at = base - timedelta(seconds=available_age_seconds)
    return {
        "feature_cutoff": _utc(available_at - timedelta(seconds=1)),
        "available_at": _utc(available_at),
        "generated_at": _utc(available_at + timedelta(milliseconds=500)),
    }


def _coinglass_payload(
    base: datetime,
    *,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "provider": "coinglass",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(base),
        "actual_payload_present": True,
        "provider_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "features": features or {"coinglass_funding_rate_zscore": -1.25},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _candidate() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "strategy_selected_mode": "trend_mode",
        "market_regime_at_entry": "TREND",
        "confidence_calibrated": 0.72,
        "expected_move_bps": 55.0,
        "expected_move_after_cost_bps": 45.0,
        "pre_trade_fee_bps": 4.0,
        "expected_slippage_bps": 2.0,
        "observed_spread_bps": 1.5,
        "stop_distance_bps": 70.0,
        "entry_atr_bps": 80.0,
        "atr_bps": 80.0,
        "target_notional_usd": 200.0,
        "allocated_margin_usd": 100.0,
        "orderbook_depth_usd": 5_000.0,
        "composite_microstructure_trust_score": 0.72,
        "trade_tape_confirmation_score": 0.7,
        "cross_venue_confirmation_score": 0.7,
        "risk_budget_usd": 2.0,
        "advanced_indicator_context": {
            "bullish_fvg_present": False,
            "bearish_fvg_present": False,
            "sweep_risk_long_side": 0.15,
            "trade_tape_confirmation_score": 0.72,
            "fvg_orderbook_trust_confluence": 0.72,
            "fvg_expected_edge_after_cost": 45.0,
            "distance_to_vwap_bps": 4.0,
            "cvd_slope": 0.2,
        },
    }


def _winning_history() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "strategy_selected_mode": "trend_mode",
            "market_regime_at_entry": "TREND",
            "confidence_calibrated": 0.72,
            "realized_pnl_bps": 50.0,
            "realized_net_pnl_usd": 1.0,
            "gross_notional_usd": 200.0,
            "exit_reason": "TIER_2_TRAILING_STOP",
        }
        for _ in range(5)
    ]


def _decision(altdata: dict[str, Any] | None) -> dict[str, Any]:
    return decision_module.evaluate_candidate(
        _candidate(),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate={
            "status": "ACTIVE",
            "a_grade_new_entries_allowed": True,
            "new_entries_allowed": True,
        },
        altdata_confluence=altdata,
        adaptive_tuning_state={
            "schema_version": "adaptive_gate_tuning_v2",
            "adaptive_loss_probability_threshold": 0.80,
            "adaptive_microstructure_trust_threshold": 0.50,
        },
    )


def _admission_intent(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        **decision,
        "paper_opportunity_tier": paper_loop.PAPER_TIER_A_GRADE_EXECUTION,
        "preemptive_edge_control": decision,
        "pre_trade_loss_probability": decision["pre_trade_loss_probability"],
    }


def _binding_intent(decision: dict[str, Any] | None = None) -> dict[str, Any]:
    preemptive = copy.deepcopy(decision or _decision(None))
    return {
        **_admission_intent(preemptive),
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "confidence_calibrated": 0.99,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "paper_fill_allowed": True,
        "paper_sizing_complete": True,
        "paper_directional_collapse_guard": {"allowed": True},
        "notional": 50.0,
    }


def test_forged_cached_confluence_and_raw_provider_bytes_never_gain_authority() -> None:
    redis = FakeRedis()
    redis.set_payload(
        "v2:altdata:confluence:BTCUSDT:1m",
        {
            "schema_version": "altdata_confluence_v1",
            "actual_payload_present": True,
            "decision_time_safe": True,
            "features": {"altdata_trade_block_score": 1.0},
        },
    )
    redis.data["v2:features:coinglass:BTCUSDT:1m"] = b'{"features":{"x":1}}'
    redis.data["v2:features:moralis:BTCUSDT:1m"] = b'{"features":{"x":1}}'
    redis.data["v2:features:santiment:BTCUSDT:1h"] = (
        b'{"features":{"altdata_trade_block_score":1}}'
    )

    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)

    assert altdata is None
    assert "v2:altdata:confluence:BTCUSDT:1m" not in redis.read_keys
    assert "v2:features:santiment:BTCUSDT:1h" not in redis.read_keys
    assert lineage["altdata_raw_provider_fallback_consumed"] is False
    assert lineage["altdata_cached_confluence_consumed"] is False
    assert lineage["altdata_canonical_reconstruction_admitted"] is False
    assert lineage["provider_features_used"] == []
    assert decision["preemptive_decision"] == "ALLOW"
    assert decision["altdata_confluence_present"] is False
    assert (
        paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
            _admission_intent(decision)
        )
        == []
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload, base: payload.update(
            **_clocks(base, available_age_seconds=601.0)
        ),
        lambda payload, base: payload.update(
            feature_cutoff=_utc(base + timedelta(hours=1)),
            available_at=_utc(base + timedelta(hours=1, seconds=1)),
            generated_at=_utc(base + timedelta(hours=1, seconds=2)),
        ),
        lambda payload, base: payload.update(provider="forged"),
        lambda payload, base: payload.update(symbol="ETHUSDT"),
        lambda payload, base: payload.update(
            features={"coinglass_funding_rate_zscore": float("nan")}
        ),
        lambda payload, base: payload.update(decision_time_safe=1),
        lambda payload, base: payload.update(schema_version="coinglass_legacy_v1"),
    ],
    ids=("stale", "future", "provider", "symbol", "nan", "bool", "schema"),
)
def test_stale_future_identity_nan_and_malformed_sources_are_explicitly_masked(
    mutate: Callable[[dict[str, Any], datetime], None],
) -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    payload = _coinglass_payload(base)
    mutate(payload, base)
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)

    assert altdata is None
    assert lineage["altdata_canonical_reconstruction_valid"] is True
    assert lineage["altdata_canonical_reconstruction_admitted"] is False
    assert lineage["altdata_actual_payload_present"] is False
    assert lineage["altdata_reconstruction_mask_reason"] == (
        "no_fresh_contributing_provider"
    )
    assert lineage["provider_features_used"] == []
    assert decision["preemptive_decision"] == "ALLOW"
    assert decision["altdata_confluence_present"] is False
    assert (
        paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
            _admission_intent(decision)
        )
        == []
    )


def test_boundary_exception_masks_altdata_without_reading_any_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    redis.set_payload(
        "v2:altdata:confluence:BTCUSDT:1m",
        {
            "actual_payload_present": True,
            "features": {"altdata_trade_block_score": 1.0},
        },
    )

    def fail_boundary(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise canonical_altdata_authority.CanonicalConfluenceContractError(
            "forged boundary"
        )

    monkeypatch.setattr(
        canonical_altdata_authority,
        "rebuild_canonical_confluence",
        fail_boundary,
    )
    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert altdata is None
    assert redis.read_keys == []
    assert lineage["altdata_boundary_error_masked"] is True
    assert lineage["altdata_canonical_reconstruction_valid"] is False
    assert lineage["altdata_raw_provider_fallback_consumed"] is False
    assert lineage["altdata_reconstruction_mask_reason"] == (
        "canonical_confluence_contract_error_masked"
    )


def test_fresh_canonical_confluence_carries_causal_non_authoritative_lineage() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base))

    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)
    paper_loop._stamp_paper_runtime_preemptive_decision_time(decision)  # noqa: SLF001

    assert altdata is not None
    assert decision["altdata_confluence_present"] is True
    assert decision["preemptive_decision"] == "ALLOW"
    assert lineage["altdata_canonical_reconstruction_admitted"] is True
    assert lineage["altdata_provider_hash_source"] == (
        "canonical_confluence_boundary_non_authoritative_content_identity"
    )
    identity = lineage["altdata_content_identity"]
    assert identity["authenticates_source"] is False
    assert identity["authorizes_consumption"] is False
    assert identity["is_cryptographic_proof"] is False
    assert identity["is_signature"] is False
    clocks = [
        _parse(lineage[field])
        for field in (
            "altdata_feature_cutoff",
            "altdata_observed_at",
            "altdata_confluence_engine_generated_at",
            "altdata_generated_at",
            "altdata_available_at",
        )
    ]
    assert clocks == sorted(clocks)
    assert clocks[-1] <= _parse(decision["preemptive_decision_time"])
    assert (
        paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
            decision
        )
        == []
    )
    assert (
        paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
            _admission_intent(decision)
        )
        == []
    )


def test_runtime_revalidation_never_reuses_a_pre_altdata_candidate_clock() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base))
    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    candidate = _candidate()
    candidate["decision_time"] = _utc(base - timedelta(hours=1))
    decision = decision_module.evaluate_candidate(
        candidate,
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate={
            "status": "ACTIVE",
            "a_grade_new_entries_allowed": True,
            "new_entries_allowed": True,
        },
        altdata_confluence=altdata,
    )
    decision.update(lineage)

    reasons = paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
        decision
    )
    assert "ALTDATA_AVAILABLE_AFTER_PREEMPTIVE_DECISION" not in reasons
    assert _parse(decision["preemptive_decision_time"]) > _parse(
        candidate["decision_time"]
    )

    paper_loop._stamp_paper_runtime_preemptive_decision_time(decision)  # noqa: SLF001

    assert _parse(decision["altdata_available_at"]) <= _parse(
        decision["preemptive_decision_time"]
    )
    assert (
        paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
            decision
        )
        == []
    )


def test_valid_canonical_risk_can_demote_but_forged_cache_cannot() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload(
        "v2:features:coinglass:BTCUSDT:1m",
        _coinglass_payload(
            base,
            features={
                "coinglass_liquidation_cascade_score": 0.99,
                "coinglass_liquidation_imbalance_usd": 20_000_000.0,
            },
        ),
    )
    redis.set_payload(
        "v2:altdata:confluence:BTCUSDT:1m",
        {"actual_payload_present": False, "features": {}},
    )

    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)

    assert "v2:altdata:confluence:BTCUSDT:1m" not in redis.read_keys
    assert decision["altdata_confluence_present"] is True
    assert decision["preemptive_decision"] == "NO_TRADE"
    assert "ALTDATA_TRADE_BLOCK_SCORE_HIGH" in decision["preemptive_decision_reasons"]


def test_admission_rejects_bad_clock_order_only_when_altdata_is_present() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base))
    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)
    forged = copy.deepcopy(decision)
    forged["altdata_observed_at"] = decision["altdata_available_at"]
    forged["altdata_available_at"] = decision["altdata_feature_cutoff"]

    assert "ALTDATA_CANONICAL_CLOCK_ORDER_INVALID" in (
        paper_loop._paper_altdata_admission_rejection_reasons(forged)  # noqa: SLF001
    )
    forged["altdata_confluence_present"] = False
    assert (
        paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
            forged
        )
        == []
    )


def test_admission_rejects_noncanonical_and_missing_runtime_decision_clocks() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base))
    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)
    paper_loop._stamp_paper_runtime_preemptive_decision_time(decision)  # noqa: SLF001

    malformed = copy.deepcopy(decision)
    malformed["altdata_observed_at"] = malformed["altdata_observed_at"].replace(
        "T",
        " ",
        1,
    )
    assert "ALTDATA_CANONICAL_CLOCK_MISSING_OR_INVALID" in (
        paper_loop._paper_altdata_admission_rejection_reasons(malformed)  # noqa: SLF001
    )

    missing_decision_time = copy.deepcopy(decision)
    missing_decision_time.pop("preemptive_decision_time")
    assert "ALTDATA_PREEMPTIVE_DECISION_TIME_MISSING_OR_INVALID" in (
        paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
            missing_decision_time
        )
    )


def test_plain_sha_identity_is_observational_not_authentication() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base))
    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)
    paper_loop._stamp_paper_runtime_preemptive_decision_time(decision)  # noqa: SLF001

    observational = copy.deepcopy(decision)
    observational["altdata_content_identity"]["digest"] = "0" * 64
    observational["altdata_confluence_hash"] = "0" * 64
    assert (
        paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
            observational
        )
        == []
    )

    falsely_authoritative = copy.deepcopy(decision)
    falsely_authoritative["altdata_content_identity"]["authenticates_source"] = True
    assert "ALTDATA_CONFLUENCE_IDENTITY_AUTHORITY_SEMANTICS_INVALID" in (
        paper_loop._paper_altdata_admission_rejection_reasons(  # noqa: SLF001
            falsely_authoritative
        )
    )


@pytest.mark.parametrize("block_action", ["BLOCK", "BLOCK_NO_EDGE"])
def test_preemptive_block_action_is_binding_for_every_paper_tier(
    block_action: str,
) -> None:
    intent = _binding_intent()
    preemptive = intent["preemptive_edge_control"]
    preemptive["preemptive_decision"] = "NO_TRADE"
    preemptive["preemptive_action"] = block_action
    intent["preemptive_decision"] = "NO_TRADE"
    intent["preemptive_action"] = block_action
    intent["paper_opportunity_tier"] = (
        paper_loop.PAPER_TIER_RISK_CONTROLLER_EXPLORATION
    )
    intent["paper_risk_controller_exploration_eligible"] = True

    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        intent
    )

    assert f"PREEMPTIVE_BLOCK_ACTION_BINDING:{block_action}" in reasons


def test_reduce_size_action_requires_proven_adaptive_economic_haircut() -> None:
    intent = _binding_intent()
    preemptive = intent["preemptive_edge_control"]
    preemptive["preemptive_decision"] = "REDUCE_SIZE_PAPER_ONLY"
    preemptive["preemptive_action"] = "ALLOW_REDUCE_SIZE_PAPER"
    intent.update(
        {
            "preemptive_decision": "REDUCE_SIZE_PAPER_ONLY",
            "preemptive_action": "ALLOW_REDUCE_SIZE_PAPER",
            "paper_opportunity_tier": (
                paper_loop.PAPER_TIER_RISK_CONTROLLER_EXPLORATION
            ),
            "mandatory_size_haircut": True,
            "risk_budget_fraction_of_normal_adaptive": 0.05,
            "normal_adaptive_target_notional_usdt": 1_000.0,
            "notional": 50.0,
            "target_notional_usd": 50.0,
        }
    )

    assert (
        paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
            intent
        )
        == []
    )

    unproven = copy.deepcopy(intent)
    unproven.pop("normal_adaptive_target_notional_usdt")
    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        unproven
    )
    assert "PREEMPTIVE_REDUCE_SIZE_NORMAL_NOTIONAL_MISSING" in reasons

    inconsistent = copy.deepcopy(intent)
    inconsistent["gross_notional_usd"] = 1_000.0
    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        inconsistent
    )
    assert "PREEMPTIVE_REDUCE_SIZE_ACTUAL_NOTIONAL_ALIASES_INCONSISTENT" in reasons
    assert "PREEMPTIVE_REDUCE_SIZE_NOTIONAL_EXCEEDS_ADAPTIVE_CAP" in reasons

    direct_action = copy.deepcopy(intent)
    direct_action["preemptive_decision"] = "ALLOW"
    direct_action["preemptive_action"] = "REDUCE_SIZE"
    direct_action["preemptive_edge_control"]["preemptive_decision"] = "ALLOW"
    direct_action["preemptive_edge_control"]["preemptive_action"] = "REDUCE_SIZE"
    assert (
        paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
            direct_action
        )
        == []
    )


def test_require_hedge_blocks_entry_until_a_binding_executor_exists() -> None:
    base = datetime.now(UTC)
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base))
    altdata, lineage = paper_loop._paper_canonical_altdata_context(  # noqa: SLF001
        redis,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    decision = _decision(altdata)
    decision.update(lineage)
    decision["altdata_hedge_required"] = True
    decision["preemptive_action"] = "REQUIRE_HEDGE"
    decision["preemptive_decision_reasons"] = ["ALTDATA_HEDGE_REQUIRED"]
    paper_loop._stamp_paper_runtime_preemptive_decision_time(decision)  # noqa: SLF001
    intent = _binding_intent(decision)

    reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        intent
    )
    assert "ALTDATA_REQUIRE_HEDGE_BINDING_EXECUTOR_UNAVAILABLE" in reasons
    paper_loop._apply_preemptive_admission_block(intent, reasons)  # noqa: SLF001
    feedback, _status = (  # noqa: SLF001
        paper_loop._build_preemptive_blocked_counterfactual_feedback(
            [intent],
            paper_session_id="paper-session-1",
            generated_utc=_utc(base),
        )
    )
    assert feedback["row_count"] == 1
    assert feedback["rows"][0]["reason_blocked"] == (
        "ALTDATA_REQUIRE_HEDGE_BINDING_EXECUTOR_UNAVAILABLE"
    )

    protective = copy.deepcopy(intent)
    protective.update(
        {
            "paper_hedge_fill": True,
            "hedge_intent": True,
            "hedge_parent_id": "paper-parent-1",
        }
    )
    protective_reasons = paper_loop._paper_preemptive_admission_rejection_reasons(  # noqa: SLF001
        protective,
        protective_hedge_fill=True,
    )
    assert "ALTDATA_REQUIRE_HEDGE_BINDING_EXECUTOR_UNAVAILABLE" not in (
        protective_reasons
    )


def test_single_binding_append_path_blocks_freeze_sizing_and_write_bypasses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = inspect.getsource(paper_loop)
    tree = ast.parse(source)
    accepted_appends = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "append"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "accepted"
    ]
    assert len(accepted_appends) == 1
    assert paper_loop.LEGACY_HIGH_CONFIDENCE_PAPER_FAST_PATH_ENABLED is False

    monkeypatch.setattr(
        paper_loop,
        "validate_paper_fill_write_invariant",
        lambda *_args, **_kwargs: {"valid": True, "reasons": []},
    )
    frozen = _binding_intent()
    accepted: list[dict[str, Any]] = []
    reasons = paper_loop._admit_and_append_paper_fill(  # noqa: SLF001
        accepted,
        frozen,
        paper_entry_freeze={
            "paper_new_entries_halted": True,
            "reason": "PORTFOLIO_TRUTH_UNTRUSTED",
        },
    )
    assert accepted == []
    assert "PAPER_NEW_ENTRIES_HALTED_BY_PORTFOLIO_TRUTH_FREEZE" in reasons

    incomplete = _binding_intent()
    incomplete["paper_sizing_complete"] = False
    reasons = paper_loop._admit_and_append_paper_fill(  # noqa: SLF001
        accepted,
        incomplete,
        paper_entry_freeze={"paper_new_entries_halted": False},
    )
    assert accepted == []
    assert "PAPER_ACCEPTANCE_SIZING_INCOMPLETE" in reasons

    invalid_write = _binding_intent()
    monkeypatch.setattr(
        paper_loop,
        "validate_paper_fill_write_invariant",
        lambda *_args, **_kwargs: {
            "valid": False,
            "reasons": ["MISSING_RISK_DECISION_ID"],
        },
    )
    reasons = paper_loop._admit_and_append_paper_fill(  # noqa: SLF001
        accepted,
        invalid_write,
        paper_entry_freeze={"paper_new_entries_halted": False},
    )
    assert accepted == []
    assert "PAPER_FILL_WRITE_INVARIANT_BLOCKED" in reasons
    assert "PAPER_FILL_WRITE_INVARIANT:MISSING_RISK_DECISION_ID" in reasons


def test_single_binding_append_path_rechecks_canonical_lineage_and_can_admit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        paper_loop,
        "validate_paper_fill_write_invariant",
        lambda *_args, **_kwargs: {"valid": True, "reasons": []},
    )
    accepted: list[dict[str, Any]] = []
    forged = _binding_intent()
    forged["altdata_confluence_present"] = True
    forged["preemptive_edge_control"]["altdata_confluence_present"] = True
    reasons = paper_loop._admit_and_append_paper_fill(  # noqa: SLF001
        accepted,
        forged,
        paper_entry_freeze={"paper_new_entries_halted": False},
    )
    assert accepted == []
    assert "ALTDATA_CANONICAL_RECONSTRUCTION_ADMITTED_NOT_TRUE" in reasons

    valid = _binding_intent()
    reasons = paper_loop._admit_and_append_paper_fill(  # noqa: SLF001
        accepted,
        valid,
        paper_entry_freeze={"paper_new_entries_halted": False},
    )
    assert reasons == []
    assert accepted == [valid]
    assert valid["paper_binding_admission_passed"] is True
    assert valid["paper_binding_admission_path"] == (
        "CANONICAL_PREEMPTIVE_NEW_ENTRY_WRITE_BOUNDARY"
    )
