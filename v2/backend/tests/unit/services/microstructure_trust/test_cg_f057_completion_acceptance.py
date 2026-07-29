"""CG-F057 completion acceptance fixtures (paper-only; live remains BLOCKED).

Codex committed a partial CG-F057 fix in commit 54684ea5e2 ("Split microstructure
integrity from market state"). Two gaps remained open at the time this file was
written and are locked in here as regression fixtures:

GAP 1 -- ``feed_integrity_pass`` (microstructure_trust/trust_score.py:142, carried
as ``source_payload.feed_integrity_pass`` inside the hash-bound
``microstructure_trust_evidence`` envelope) must be a HARD integrity rejection
for EVERY publishable microstructure action (ALLOW / REDUCE_SIZE / SHADOW_ONLY /
NO_TRADE), not only for actions outside
``MICRO_ACTIONS_AUTHENTICATED_MARKET_STATE``. As of this writing,
``v2_paper_provisional_prediction_publisher.microstructure_publication_rejection_reasons``
only inspects ``evidence.get("evidence_valid")`` (envelope hash/schema integrity
via ``ordinary_paper_admission.py:254``), which is a SEPARATE concern from feed
integrity. A well-formed envelope (``evidence_valid is True``) whose
``source_payload.feed_integrity_pass`` is False (the ~0.24 fail_closed
composite-trust cap applied at ``microstructure_trust/trust_score.py:343-348``)
currently produces ZERO rejection reasons and therefore PUBLISHES. This must
become a hard rejection.

GAP 2 -- ``microstructure_continuous_estimates`` (published by the publisher at
``payload["microstructure_continuous_estimates"]``, sourced from
``v2_microstructure_feed_quality_monitor._continuous_microstructure_estimates``
with fields ``fill_probability`` / ``slippage_bps`` / ``market_impact_bps`` /
``adverse_selection_probability``) must be CONSUMED by the typed
``AdaptivePolicyActionV2`` built in
``adaptive_system/adaptive_policy_shadow_v2.py`` (``_policy_action`` /
``build_adaptive_policy_shadow_candidate``), not merely published and ignored.
The required conservative blend, when micro estimates are present, is::

    expected_fill_probability = min(stats_fill_probability, micro.fill_probability)
    expected_slippage         = max(stats_slippage_bps,     micro.slippage_bps)
    expected_market_impact    = max(stats_impact_bps,       micro.market_impact_bps)
    expected_adverse_selection= max(stats_adverse_prob,     micro.adverse_selection_probability)

and the blended slippage/impact bps must flow THROUGH
``ExpectedCostBreakdownV2`` so the ``record.py`` identities continue to hold
(``expected_slippage == expected_cost_breakdown.slippage_bps`` and
``expected_market_impact == expected_cost_breakdown.market_impact_bps``,
domain/adaptive_policy_action_v2/record.py:947-950).

These are ACCEPTANCE fixtures: they encode the REQUIRED post-fix behavior.
Some assertions may already pass against the current working tree (CG-F057 is
being completed incrementally) and some may fail -- a failure here defines the
target Codex must still close, it is not a fixture bug. This file is
paper-only / read-only with respect to production code: it imports and calls
existing production entry points, it does not modify them, and it asserts
nothing that would require live trading (LIVE TRADING remains BLOCKED
throughout: every intent/calibration fixture below sets
``paper_only=True``/``routes_to_live=False``/``places_real_order=False``).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.cli import v2_paper_provisional_prediction_publisher as publisher
from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.adaptive_system import (
    adaptive_hard_validator_v2,
    adaptive_objective_v2,
)
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    build_adaptive_policy_shadow_candidate,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    OBSERVATION_SCHEMA_VERSION,
    CandidateCalibrationObservationV2,
    fit_candidate_outcome_calibration_v2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    _canonical_sha256 as _reseal_calibration_hash,
)

# --------------------------------------------------------------------------- #
# GAP 1 fixtures -- publisher microstructure-integrity gate
# (v2_paper_provisional_prediction_publisher.py).
# --------------------------------------------------------------------------- #

# The four actions that are today accepted as "authenticated market state" by
# the publisher (MICRO_ACTIONS_AUTHENTICATED_MARKET_STATE). Every one of them
# must still be hard-rejected when the feed itself is untrustworthy.
_PUBLISHABLE_ACTIONS = ("ALLOW", "REDUCE_SIZE", "SHADOW_ONLY", "NO_TRADE")


def _tensor() -> SimpleNamespace:
    return SimpleNamespace(
        tensor_id="cg-f057-tensor-1",
        feature_snapshot_id="cg-f057-snapshot-1",
        source_lineage_hash="a" * 64,
        timeframe="5m",
    )


def _micro_source(
    *,
    action: str,
    feed_integrity_pass: bool,
    sweep_direction_uncertain: bool = False,
) -> dict[str, Any]:
    """A well-formed microstructure_trust_score_v2 source payload.

    ``feed_integrity_pass=False`` here models the fail_closed ~0.24 composite
    trust cap (microstructure_trust/trust_score.py:343-348): the feed itself
    could not be authenticated. ``sweep_direction_uncertain=True`` (with
    ``feed_integrity_pass=True``) instead models the OTHER ~0.24 slice: a
    fully-authenticated feed reporting a genuinely adverse/uncertain book. Only
    the former must hard-reject; the latter is honest unfavorable market state
    and must flow downstream.
    """

    return {
        "schema_version": "microstructure_trust_score_v2",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "available_at": "2026-07-27T00:00:00.100Z",
        "decision_time": "2026-07-27T00:00:00.200Z",
        "generated_at": "2026-07-27T00:00:00.300Z",
        "microstructure_trust_score": 0.24 if not feed_integrity_pass or sweep_direction_uncertain else 0.60,
        "composite_microstructure_trust_score": 0.24
        if not feed_integrity_pass or sweep_direction_uncertain
        else 0.60,
        "microstructure_action": action,
        "sweep_risk": 0.20,
        "sweep_risk_score": 0.20,
        "book_sequence_gap": False,
        "sequence_gap_flag": 0,
        "feed_integrity_pass": feed_integrity_pass,
        "latency_within_bound": True,
        "sequence_gap_free": True,
        "sweep_direction_uncertain": sweep_direction_uncertain,
        "missing_components": [],
    }


class _FakeRedisClient:
    """Minimal Redis stand-in mirroring test_v2_paper_provisional_prediction_publisher.py.

    ``build_micro_evidence`` performs a first GET (``payload``) and then a
    mandatory second readback GET; both must return byte-identical JSON for
    ``evidence_valid`` to be True. Passing an iterator of distinct payloads
    lets a single fixture also model a genuine readback mismatch (GAP 3 /
    regression case).
    """

    def __init__(self, *payloads: Mapping[str, Any]) -> None:
        self._reads = iter(payloads if payloads else (None,))

    def get(self, _key: str) -> str | None:
        payload = next(self._reads)
        return json.dumps(payload) if payload is not None else None

    def ttl(self, _key: str) -> int:
        return 60


def _build_evidence(
    source: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    client = _FakeRedisClient(source, source)
    return publisher.build_micro_evidence(
        client,
        symbol="BTCUSDT",
        timeframe="5m",
        tensor=_tensor(),
        decision_time_iso="2026-07-27T00:00:01.000000Z",
    )


@pytest.mark.parametrize("action", _PUBLISHABLE_ACTIONS)
def test_feed_integrity_failed_hard_rejected_for_every_publishable_action(
    action: str,
) -> None:
    """Acceptance rule (GAP 1, the crux): a record whose envelope hash/schema
    integrity is fine (``evidence_valid is True``) but whose
    ``source_payload.feed_integrity_pass`` is False must be HARD-REJECTED
    (non-empty ``reject_reasons``) for every action the publisher otherwise
    treats as authenticated market state, not only for NO_TRADE.

    Currently ``microstructure_publication_rejection_reasons`` keys only on
    ``evidence_valid`` (ordinary_paper_admission.py:254, envelope hash/schema),
    which does not read ``source_payload.feed_integrity_pass``
    (microstructure_trust/trust_score.py:142) at all -- so today this
    assertion FAILS (reasons == []) for every action in
    MICRO_ACTIONS_AUTHENTICATED_MARKET_STATE. Codex must add a feed-integrity
    check (suggested reason code: MICROSTRUCTURE_FEED_INTEGRITY_FAILED or
    similar) to this gate so a degraded feed cannot publish under any
    disposition.
    """

    source = _micro_source(action=action, feed_integrity_pass=False)
    micro_action, evidence = _build_evidence(source)

    assert micro_action == action
    assert evidence is not None
    # The envelope itself (hash/schema/readback) is genuinely valid: only the
    # feed-integrity flag inside source_payload is failing. This isolates GAP 1
    # from the (already-working) envelope-integrity rejection path.
    assert evidence["evidence_valid"] is True
    assert evidence["source_payload"]["feed_integrity_pass"] is False

    reasons = publisher.microstructure_publication_rejection_reasons(
        action=micro_action,
        evidence=evidence,
    )

    assert reasons, (
        f"action={action!r}: feed_integrity_pass=False must hard-reject "
        "publication (evidence_valid alone is not sufficient); got no "
        "rejection reasons, meaning this record would PUBLISH today."
    )


@pytest.mark.parametrize("action", ("SHADOW_ONLY", "NO_TRADE"))
def test_feed_clean_valid_unfavorable_publishes(action: str) -> None:
    """Acceptance rule: a genuinely-adverse-but-honest book (feed_integrity_pass
    True, valid envelope, sweep_direction_uncertain True -- the OTHER ~0.24
    composite-trust slice, distinct from the fail_closed 0.24 slice in the test
    above) must NOT be blocked as an integrity failure. SHADOW_ONLY/NO_TRADE
    here are valid unfavorable market state and must flow downstream carrying
    the raw microstructure_action + continuous estimates.

    This already passes today (regression guard): it documents that the GAP 1
    fix must not become a blanket reject of every unfavorable disposition.
    """

    source = _micro_source(
        action=action,
        feed_integrity_pass=True,
        sweep_direction_uncertain=True,
    )
    micro_action, evidence = _build_evidence(source)

    assert micro_action == action
    assert evidence is not None
    assert evidence["evidence_valid"] is True
    assert evidence["source_payload"]["feed_integrity_pass"] is True

    reasons = publisher.microstructure_publication_rejection_reasons(
        action=micro_action,
        evidence=evidence,
    )

    assert reasons == [], (
        f"action={action!r}: an honest, feed-authenticated adverse book must "
        f"still publish (valid_unfavorable_state); got rejection {reasons!r}"
    )


@pytest.mark.parametrize("action", ("SHADOW_ONLY", "NO_TRADE"))
def test_feed_clean_valid_unfavorable_reaches_allocator_as_continuous_input(
    action: str,
) -> None:
    intent = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "entry_price": 100.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 20.0,
        "market_state_integrity_score": 92.0,
        "strategy_regime_labels": ["ORDINARY_PAPER_CONTINUOUS"],
        "strategy_router_selected_mode": "ordinary_paper_continuous_mode",
        "strategy_temporal_contract_status": "PASS",
        "strategy_feature_snapshot_status": "ATTACHED_PIT_VALID_FEATURE_SNAPSHOT",
        "strategy_feature_snapshot_id": "cg-f057-regime-snapshot",
        "strategy_feature_snapshot_available_at": "2026-07-27T00:00:00.100Z",
        "strategy_feature_snapshot_feature_cutoff": "2026-07-26T23:55:00.000Z",
        "strategy_feature_snapshot_candle_closed_confirmed": True,
        "strategy_feature_snapshot_latest_unclosed_kline_excluded": True,
        "strategy_decision_time": "2026-07-27T00:00:01.000Z",
    }
    allocation_input = paper_loop._build_allocation_input(  # noqa: SLF001
        intent=intent,
        signal={
            "timeframe": "5m",
            "price_target": 100.0,
            "expected_funding_bps": 0.5,
        },
        prediction={"features": {}},
        portfolio_context={
            "equity": 3_000.0,
            "available_margin": 3_000.0,
            "wallet_balance": 3_000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure={
            "liquidity_score": 0.8,
            "bid_ask_spread_bps": 1.2,
            "orderbook_depth_usd": 100_000.0,
            "microstructure_trust_score": 0.24,
            "microstructure_adaptive_minimum": 0.70,
            "microstructure_action": action,
            "feed_integrity_pass": True,
        },
        correlation_contexts_by_symbol={
            "BTCUSDT": {
                "correlation_exposure_pct": 0.0,
                "correlation_input_status": "NO_OPEN_POSITIONS",
                "correlation_input_source": "NO_OPEN_POSITIONS",
                "correlation_pair_count": 0,
                "correlation_required_pair_count": 0,
                "correlation_unresolved_open_symbols": [],
            }
        },
    )

    assert allocation_input.risk_veto is False
    assert allocation_input.liquidity_score == pytest.approx(0.8)
    assert intent["allocator_microstructure_continuous_policy_input_required"] is True
    assert intent["allocator_microstructure_trust_gate_status"] == (
        "VALID_UNFAVORABLE_CONTINUOUS_ADAPTIVE_POLICY_INPUT"
    )


def test_integrity_none_or_invalid_still_hard_rejected() -> None:
    """Regression guard on the already-working part of GAP 1: missing evidence
    and a genuinely invalid envelope (readback mismatch -- the mutable Redis
    record changed between observation and evidence sealing) must remain hard
    rejections regardless of how the feed-integrity check is added.
    """

    # Sub-case A: no evidence could be built at all (e.g. no fresh Redis key).
    reasons_missing = publisher.microstructure_publication_rejection_reasons(
        action="SHADOW_ONLY",
        evidence=None,
    )
    assert reasons_missing == ["MICROSTRUCTURE_EVIDENCE_MISSING"]

    # Sub-case B: the source payload mutated between the two mandatory reads,
    # so evidence_valid is False even though feed_integrity_pass was True on
    # both individual reads.
    loaded = _micro_source(action="SHADOW_ONLY", feed_integrity_pass=True)
    changed = {**loaded, "microstructure_trust_score": 0.61}
    client = _FakeRedisClient(loaded, changed)
    micro_action, evidence = publisher.build_micro_evidence(
        client,
        symbol="BTCUSDT",
        timeframe="5m",
        tensor=_tensor(),
        decision_time_iso="2026-07-27T00:00:01.000000Z",
    )

    assert evidence is not None
    assert evidence["evidence_valid"] is False
    reasons_invalid = publisher.microstructure_publication_rejection_reasons(
        action=micro_action,
        evidence=evidence,
    )
    assert reasons_invalid, "an invalidated envelope must remain hard-rejected"


def test_close_or_reduce_only_hard_blocks_new_entry() -> None:
    """Regression guard: CLOSE_OR_REDUCE_ONLY must remain a hard block for a
    new entry regardless of feed integrity (already-working behavior via
    MICRO_ACTIONS_NEW_ENTRY_RESTRICTED).
    """

    source = _micro_source(action="CLOSE_OR_REDUCE_ONLY", feed_integrity_pass=True)
    micro_action, evidence = _build_evidence(source)

    reasons = publisher.microstructure_publication_rejection_reasons(
        action=micro_action,
        evidence=evidence,
    )

    assert reasons == ["MICROSTRUCTURE_CLOSE_OR_REDUCE_ONLY_NEW_ENTRY_RESTRICTED"]


# --------------------------------------------------------------------------- #
# GAP 2 fixtures -- typed AdaptivePolicyActionV2 must consume
# microstructure_continuous_estimates (adaptive_system/adaptive_policy_shadow_v2.py).
# --------------------------------------------------------------------------- #

_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"cg-f057-completion-acceptance-validator").digest()
)
_VALIDATOR_SEED = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption(),
)
_VALIDATOR_PUBLIC_HEX = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
).hex()


def _sha(character: str) -> str:
    return character * 64


@pytest.fixture(autouse=True)
def _validator_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adaptive_objective_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _VALIDATOR_PUBLIC_HEX,
    )
    monkeypatch.setattr(
        adaptive_hard_validator_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _VALIDATOR_PUBLIC_HEX,
    )


def _observation(index: int) -> CandidateCalibrationObservationV2:
    """Deterministic synthetic candidate-outcome observation, shaped like the
    shared adaptive_system test helper (test_candidate_outcome_calibration_v2._observation),
    duplicated here so this acceptance file stays self-contained and does not
    depend on a test module Codex may still be actively editing."""

    after_cost = float((index % 11) - 5)
    realized = index % 10 == 0
    return CandidateCalibrationObservationV2(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        candidate_id=f"cg-f057-candidate-{index:03d}",
        decision_time_ms=1_000_000 + index * 1_000,
        label_record_available_at_ms=2_000_000 + index * 1_000,
        checkpoint_generation=3,
        checkpoint_id="checkpoint-3",
        checkpoint_sha256="a" * 64,
        symbol="BTCUSDT",
        timeframe="5m" if index % 2 else "15m",
        side="LONG" if index % 2 else "SHORT",
        decision_disposition="REJECTED" if index % 3 else "INFEASIBLE",
        realized_execution_outcome=realized,
        actual_fill_id=(f"fill-{index:03d}" if realized else None),
        actual_close_id=(f"close-{index:03d}" if realized else None),
        actual_fill_execution_time_ms=(1_000_100 + index * 1_000 if realized else None),
        actual_close_execution_time_ms=(1_000_500 + index * 1_000 if realized else None),
        policy_mode="champion_exploitation",
        cohort_id="cohort-3",
        regime_bucket="REGIME_EVIDENCE_UNAVAILABLE",
        confidence_raw_source=(index % 10) / 10.0,
        calibrated_confidence_source=(index % 10) / 10.0,
        predicted_loss_probability_source=(10 - index % 10) / 10.0,
        exit_feasibility_source=(index % 5) / 5.0,
        expected_move_after_cost_source_bps=float(index % 7),
        final_gross_return_bps=after_cost + 2.0,
        final_after_cost_return_bps=after_cost,
        max_favorable_excursion_bps=float(index % 20),
        max_adverse_excursion_bps=-float(index % 15),
        realized_volatility_bps=float(index % 9),
        transaction_cost_bps=2.0,
        slippage_bps=0.5,
        market_impact_bps=0.25,
        funding_bps=0.1,
        profitable=after_cost > 0.0,
        loss=after_cost < 0.0,
        stop_hit=index % 4 == 0,
        profit_target_hit=index % 5 == 0,
        short_horizon_reversal=index % 6 == 0,
        slippage_failure=index % 7 == 0,
        missed_tp_then_stop=index % 20 == 0,
        infeasible=index % 3 == 0,
        label_receipts_sha256="b" * 64,
    )


def _base_calibration() -> dict[str, Any]:
    # Produces exactly two side:timeframe buckets: "SHORT:15m" and "LONG:5m".
    return fit_candidate_outcome_calibration_v2(
        [_observation(index) for index in range(100)],
        generated_at_ms=3_000_000,
        source_archive_chain_sha256=_sha("c"),
    )


def _reseal(calibration: dict[str, Any]) -> dict[str, Any]:
    resealed = dict(calibration)
    resealed.pop("calibration_sha256", None)
    resealed["calibration_sha256"] = _reseal_calibration_hash(resealed)
    return resealed


def _tuned_calibration(
    *,
    bucket: str,
    stats_fill_probability: float,
    stats_slippage_bps: float,
    stats_market_impact_bps: float,
    stats_adverse_selection_probability: float,
) -> dict[str, Any]:
    """A hash-valid calibration artifact whose ``bucket`` (side:timeframe)
    statistics are overridden to an unambiguously profitable, low-risk
    scenario so the objective genuinely selects a directional trade (not
    remain_flat), with the exact stats-side blend inputs under test control."""

    calibration = _base_calibration()
    stats = calibration["side_timeframe_statistics"][bucket]
    stats["after_cost_expectancy_bps"] = 50.0
    stats["loss_probability"] = 0.01
    stats["venue_infeasible_probability"] = 1.0 - stats_fill_probability
    stats["slippage_failure_probability"] = stats_adverse_selection_probability
    stats["stop_out_probability"] = 0.0
    stats["mae_bps_quantiles"] = {"0.1": -2.0, "0.5": -1.0, "0.9": -0.5}
    stats["tail_loss_bps_quantiles"] = {"0.1": 0.0, "0.5": 0.5, "0.9": 1.0}
    stats["market_impact_bps_quantiles"] = {
        "0.1": stats_market_impact_bps,
        "0.5": stats_market_impact_bps,
        "0.9": stats_market_impact_bps,
    }
    stats["slippage_bps_quantiles"] = {
        "0.1": stats_slippage_bps,
        "0.5": stats_slippage_bps,
        "0.9": stats_slippage_bps,
    }
    stats["return_bps_quantiles"] = {"0.1": 40.0, "0.5": 50.0, "0.9": 60.0}
    stats["posterior_uncertainty"] = 0.01
    return _reseal(calibration)


def _registry() -> dict[str, Any]:
    return {
        "schema_version": "model_registry_active_v2",
        "registry_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "checkpoint_bundle_sha256": _sha("a"),
        "checkpoint_bundle": {
            "feature_abi_sha256": _sha("7"),
            "serving_feature_builder_sha": _sha("6"),
        },
        "paper_only": True,
        "live_eligible": False,
    }


def _feature_snapshot() -> dict[str, Any]:
    return {
        "feature_snapshot_id": "feature-snapshot-1",
        "feature_cutoff": "1970-01-01T00:16:40.000Z",
        "available_at": "1970-01-01T00:18:20.000Z",
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1",
        "latest_unclosed_exclusion_decision_time_ms": 1_100_000,
        "latest_closed_kline_close_time_ms": 999_999,
        "trainer_consumable": True,
        "content_sha256": _sha("5"),
    }


def _micro_continuous_estimates(
    *,
    fill_probability: float,
    slippage_bps: float,
    market_impact_bps: float,
    adverse_selection_probability: float,
) -> dict[str, Any]:
    """Shape mirrors the REAL current producer
    (v2_microstructure_feed_quality_monitor._continuous_microstructure_estimates,
    schema microstructure_continuous_estimates_v1) as forwarded verbatim by the
    publisher into payload["microstructure_continuous_estimates"]. Field names
    are fill_probability / slippage_bps / market_impact_bps /
    adverse_selection_probability -- NOT an "expected_"-prefixed alias -- this
    is the exact schema verified against raw source, not a guess."""

    return {
        "schema_version": "microstructure_continuous_estimates_v1",
        "status": "PASS_CALIBRATED_CONTINUOUS_ESTIMATES",
        "complete": True,
        "fill_probability": fill_probability,
        "slippage_bps": slippage_bps,
        "market_impact_bps": market_impact_bps,
        "adverse_selection_probability": adverse_selection_probability,
        "available_liquidity_capacity_usd": 100_000.0,
        "sweep_risk": 0.2,
    }


def _intent(
    *,
    side: str,
    timeframe: str,
    feed_integrity_pass: bool = True,
    microstructure_action: str = "SHADOW_ONLY",
    micro_estimates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reservation_hash = _sha("3")
    intent: dict[str, Any] = {
        "prediction_id": "prediction-1",
        "preemptive_decision_id": "preemptive-1",
        "preemptive_decision": "NO_TRADE",
        "preemptive_decision_reasons": ["STATIC_COMPARATOR_ONLY"],
        "policy_id": "production-policy-1",
        "policy_fingerprint": _sha("4"),
        "symbol": "BTCUSDT",
        "timeframe": timeframe,
        "side": side,
        "entry_price": 100.0,
        "fee_bps": 1.0,
        "observed_spread_bps": 1.0,
        "expected_slippage_bps": 1.0,
        "expected_funding_bps": 0.0,
        "depth_derived_price_impact_bps": 1.0,
        "cost_source_timestamp": "1970-01-01T00:18:20.000Z",
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "runtime_cost_capture_source": "V2_PAPER_RUNTIME_DECISION_TIME_COST_CAPTURE",
        "runtime_cost_capture_missing_fields": [],
        "runtime_cost_capture_unexplained_missing_fields": [],
        "runtime_cost_capture_temporal_reject_reasons": [],
        "production_grade_cost_flag": True,
        "fallback_cost_flag": False,
        "feed_integrity_pass": feed_integrity_pass,
        "microstructure_action": microstructure_action,
        "paper_fill_allowed": False,
        "allocator_decision": "BLOCK_STATIC_CATEGORY_E",
        "paper_fill_block_reason": "STATIC_COMPARATOR_ONLY",
        "paper_exchange_filter_snapshot_hash": _sha("1"),
        "paper_cycle_base_resource_evidence_hash": _sha("2"),
        "paper_cycle_reservation_snapshot_hash": reservation_hash,
        "paper_dynamic_envelope_reservation_evidence_hash": _sha("8"),
        "paper_exchange_filter_snapshot": {
            "status": "READY",
            "rejection_reasons": [],
            "tick_size": 0.01,
            "step_size": 0.001,
            "min_qty": 0.001,
            "max_qty": 1000.0,
            "min_notional": 5.0,
        },
        "paper_cycle_base_resource_evidence": {"available_margin_usd": 1000.0},
        "paper_cycle_reservation_snapshot": {
            "status": "PASS",
            "rejection_reasons": [],
            "cycle_identity": "cycle-1",
            "snapshot_hash": reservation_hash,
            "inputs": {"base_equity_usd": 1000.0},
            "derived": {
                "remaining_total_notional_usd": 500.0,
                "remaining_symbol_notional_usd": 200.0,
                "remaining_margin_after_buffer_usd": 800.0,
                "remaining_projected_stress_loss_usd": 50.0,
                "remaining_per_candidate_risk_budget_usd": 20.0,
                "prior_reserved_margin_usd": 0.0,
            },
        },
        "paper_allocator_economic_contract": {
            "material": {
                "model_inputs": {
                    "max_qty": 1000.0,
                    "risk_envelope": {"max_effective_leverage": 1.0},
                }
            }
        },
        "entry_prediction_snapshot": {
            "prediction_id": "prediction-1",
            "feature_snapshot_id": "feature-snapshot-1",
            "mtf_snapshot_id": "market-state-1",
            "feature_cutoff": "1970-01-01T00:16:40.000Z",
            "available_at": "1970-01-01T00:18:20.000Z",
            "source_hashes": {"feature_vector_hash": _sha("9")},
        },
        "market_state_id": "market-state-1",
        "entry_feature_latest_unclosed_kline_excluded": True,
        "entry_feature_latest_unclosed_exclusion_method": (
            "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1"
        ),
        "entry_feature_latest_closed_kline_close_time_ms": 999_999,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    if micro_estimates is not None:
        intent["microstructure_continuous_estimates_complete"] = True
        intent["microstructure_continuous_estimates"] = dict(micro_estimates)
    return intent


# side -> (side_timeframe_statistics bucket key, timeframe) produced by
# _base_calibration()'s synthetic 100-row fit.
_SIDE_BUCKETS = {"short": ("SHORT:15m", "15m"), "long": ("LONG:5m", "5m")}


def _build_directional_candidate(
    *,
    side: str,
    stats: Mapping[str, float],
    micro: Mapping[str, float] | None,
):
    bucket, timeframe = _SIDE_BUCKETS[side]
    calibration = _tuned_calibration(
        bucket=bucket,
        stats_fill_probability=stats["fill_probability"],
        stats_slippage_bps=stats["slippage_bps"],
        stats_market_impact_bps=stats["market_impact_bps"],
        stats_adverse_selection_probability=stats["adverse_selection_probability"],
    )
    intent = _intent(
        side=side,
        timeframe=timeframe,
        micro_estimates=(
            _micro_continuous_estimates(**micro) if micro is not None else None
        ),
    )
    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=calibration,
        registry=_registry(),
        validator_seed=_VALIDATOR_SEED,
        generated_at_ms=4_000_000,
    )
    assert result.selected_adaptive_action.selected_action == "directional_trade", (
        "fixture setup must genuinely select a directional trade (not "
        "remain_flat) so the cost/fill/adverse fields under test are not the "
        "trivial flat defaults"
    )
    assert result.paper_only is True
    assert result.routes_to_live is False
    assert result.places_real_order is False
    assert result.exchange_action_taken is False
    return result


_FAVORABLE_STATS = {
    "fill_probability": 0.95,
    "slippage_bps": 5.0,
    "market_impact_bps": 3.0,
    "adverse_selection_probability": 0.05,
}
_ADVERSE_MICRO = {
    "fill_probability": 0.40,
    "slippage_bps": 30.0,
    "market_impact_bps": 12.0,
    "adverse_selection_probability": 0.35,
}


def test_continuous_estimates_consumed_by_typed_policy() -> None:
    """Acceptance rule (GAP 2, the crux): when
    microstructure_continuous_estimates are present on the intent, the
    constructed AdaptivePolicyActionV2 must blend them conservatively against
    the calibrated statistics::

        expected_fill_probability  == min(stats_fill, micro.fill_probability)
        expected_slippage          == max(stats_slippage, micro.slippage_bps)
        expected_market_impact     == max(stats_impact, micro.market_impact_bps)
        expected_adverse_selection == max(stats_adverse, micro.adverse_selection_probability)

    Built via the real build_adaptive_policy_shadow_candidate entry point
    (not a private helper), with the calibration statistics under direct test
    control so the expected blend can be computed independently rather than
    diffed against a second run.
    """

    result = _build_directional_candidate(
        side="short", stats=_FAVORABLE_STATS, micro=_ADVERSE_MICRO
    )
    action = result.selected_adaptive_action

    assert action.expected_fill_probability == pytest.approx(
        min(_FAVORABLE_STATS["fill_probability"], _ADVERSE_MICRO["fill_probability"])
    )
    assert action.expected_slippage == pytest.approx(
        max(_FAVORABLE_STATS["slippage_bps"], _ADVERSE_MICRO["slippage_bps"])
    )
    assert action.expected_market_impact == pytest.approx(
        max(
            _FAVORABLE_STATS["market_impact_bps"],
            _ADVERSE_MICRO["market_impact_bps"],
        )
    )
    assert action.expected_adverse_selection == pytest.approx(
        max(
            _FAVORABLE_STATS["adverse_selection_probability"],
            _ADVERSE_MICRO["adverse_selection_probability"],
        )
    )


def test_cost_identity_preserved_after_micro_blend() -> None:
    """Regression guard: after the micro-estimate blend, the typed action must
    still satisfy the record.py identities (domain/adaptive_policy_action_v2/
    record.py:947-950) -- expected_slippage/expected_market_impact must equal
    the corresponding ExpectedCostBreakdownV2 fields, the cost breakdown's
    total must equal the sum of its components, and before-cost minus total
    cost must equal after-cost. The blend must not be able to desynchronize
    the typed action from its own cost breakdown.
    """

    result = _build_directional_candidate(
        side="short", stats=_FAVORABLE_STATS, micro=_ADVERSE_MICRO
    )
    action = result.selected_adaptive_action
    costs = action.expected_cost_breakdown

    assert action.expected_slippage == costs.slippage_bps
    assert action.expected_market_impact == costs.market_impact_bps
    assert costs.total_cost_bps == pytest.approx(
        costs.fee_bps
        + costs.spread_bps
        + costs.slippage_bps
        + costs.market_impact_bps
        + costs.funding_bps
    )
    assert action.expected_before_cost_return - costs.total_cost_bps == pytest.approx(
        action.expected_after_cost_return
    )


@pytest.mark.parametrize(
    ("stats", "micro", "expected"),
    (
        pytest.param(
            _FAVORABLE_STATS,
            _ADVERSE_MICRO,
            _ADVERSE_MICRO,
            id="favorable_stats_adverse_micro_micro_wins",
        ),
        pytest.param(
            _ADVERSE_MICRO,
            _FAVORABLE_STATS,
            _ADVERSE_MICRO,
            id="adverse_stats_favorable_micro_stats_wins",
        ),
    ),
)
def test_micro_estimates_are_conservative_only(
    stats: Mapping[str, float],
    micro: Mapping[str, float],
    expected: Mapping[str, float],
) -> None:
    """Acceptance rule: the blend NEVER lowers cost or raises fill probability
    beyond whichever input (stats or micro) is worse. Fed
    favorable-stats + adverse-micro, the adverse (micro) side must win. Fed
    adverse-stats + favorable-micro, the conservative (stats) side must be
    left unchanged -- a favorable micro estimate can never rescue an already
    bad statistical read. In both parametrizations here the numerically
    "worse" values live in ``expected`` (== _ADVERSE_MICRO), so the assertion
    is identical either way: the result must match the worse of the two
    inputs, never something better than both.
    """

    result = _build_directional_candidate(side="short", stats=stats, micro=micro)
    action = result.selected_adaptive_action

    assert action.expected_fill_probability == pytest.approx(expected["fill_probability"])
    assert action.expected_slippage == pytest.approx(expected["slippage_bps"])
    assert action.expected_market_impact == pytest.approx(expected["market_impact_bps"])
    assert action.expected_adverse_selection == pytest.approx(
        expected["adverse_selection_probability"]
    )


@pytest.mark.parametrize("side", ("long", "short"))
def test_long_short_symmetry(side: str) -> None:
    """Acceptance rule: both GAP 1's hard-integrity rejection and GAP 2's
    conservative blend are side-agnostic.

    GAP 1: microstructure_publication_rejection_reasons takes no side/symbol
    parameter at all -- feed integrity is a source-authentication boundary,
    not a directional preference -- so the same feed-integrity-false evidence
    must be rejected identically regardless of which side the signal would
    have opened.

    GAP 2: the conservative blend formula must produce the same relationship
    (worse-of-stats-and-micro) whether the selected disposition is a long or a
    short directional trade.
    """

    # GAP 1 half: side is not even a parameter of the gate -- assert the
    # rejection is identical for the same evidence regardless of the
    # long/short entry context the caller intends.
    source = _micro_source(action="SHADOW_ONLY", feed_integrity_pass=False)
    reasons_a = publisher.microstructure_publication_rejection_reasons(
        action="SHADOW_ONLY", evidence=_build_evidence(source)[1]
    )
    reasons_b = publisher.microstructure_publication_rejection_reasons(
        action="SHADOW_ONLY", evidence=_build_evidence(source)[1]
    )
    assert reasons_a == reasons_b
    assert reasons_a, "feed-integrity-false must hard-reject regardless of side"

    # GAP 2 half: the blend must hold for both a long and a short directional
    # candidate.
    result = _build_directional_candidate(
        side=side, stats=_FAVORABLE_STATS, micro=_ADVERSE_MICRO
    )
    action = result.selected_adaptive_action
    assert action.primary_side == side

    assert action.expected_fill_probability == pytest.approx(
        min(_FAVORABLE_STATS["fill_probability"], _ADVERSE_MICRO["fill_probability"])
    )
    assert action.expected_slippage == pytest.approx(
        max(_FAVORABLE_STATS["slippage_bps"], _ADVERSE_MICRO["slippage_bps"])
    )
    assert action.expected_market_impact == pytest.approx(
        max(
            _FAVORABLE_STATS["market_impact_bps"],
            _ADVERSE_MICRO["market_impact_bps"],
        )
    )
    assert action.expected_adverse_selection == pytest.approx(
        max(
            _FAVORABLE_STATS["adverse_selection_probability"],
            _ADVERSE_MICRO["adverse_selection_probability"],
        )
    )
