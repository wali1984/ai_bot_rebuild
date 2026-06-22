"""Regression tests for the V2 full-observation unified-features
burndown packet.

This packet expands the ``coinank`` subfamily projector from 16
sourced fields per symbol to 22 (full subfamily target), using
strictly V2-native data already published in
``v2:market:funding:{symbol}`` and ``v2:market:open_interest:{symbol}``.
No new Redis read. No paid aggregator. No legacy source. No silent
zero-fill.

Invariants pinned by these tests:

1. The six new field NAMES exist in the coinank projector output.
2. Each new field carries an explicit V2-native source attribution
   when the underlying market payload is present.
3. Missing inputs propagate to ``None`` with a specific
   ``MISSING_FROM_V2_*`` source label (never silently zeroed).
4. ``zero_filled_field_count`` aggregate remains 0.
5. ``checkpoint_compatibility_claimed`` and
   ``policy_architecture_parity_claimed`` remain ``false``.
6. ``compact_observation_v1`` slice dim remains 26.
7. ``TARGET_FULL_DIM`` remains 1911 and the SLICE_SIZES sum still
   matches it.
8. The ``coinank`` subfamily target remains 22 (no resizing).
9. The token_metrics / onchain_btc / onchain_eth / ccxt_ohlcv
   subfamilies remain explicitly missing — this packet must not
   change those source attributions.
"""
from __future__ import annotations

import importlib


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


SIX_NEW_COINANK_FIELDS: tuple[str, ...] = (
    "coinank.seconds_until_next_funding",
    "coinank.funding_payload_age_seconds",
    "coinank.oi_payload_age_seconds",
    "coinank.funding_oi_direction_agreement",
    "coinank.funding_rate_bps",
    "coinank.mark_premium_to_index_bps",
)


def _coinank_field_dict(projector_out: list[tuple[str, float | None, str]]) -> dict:
    return {name: (value, source) for name, value, source in projector_out}


def test_six_new_coinank_field_names_present_with_v2_sources() -> None:
    b = _builder()
    out = b._project_coinank(
        market_funding={
            "lastFundingRate": 0.0001,
            "markPrice": 50000.0,
            "indexPrice": 49999.0,
            "interestRate": 0.0001,
            "estimatedSettlePrice": 50000.0,
            "time": 1700000000000,
            "nextFundingTime": 1700028800000,
        },
        market_open_interest={"openInterest": 1234567.0, "time": 1700000000000},
        market_price={"ticker_24hr": {"lastPrice": 50000.0}},
        v2_features={"funding_rate": 0.0001, "oi_change_pct": 0.005},
    )
    fields = _coinank_field_dict(out)
    for name in SIX_NEW_COINANK_FIELDS:
        assert name in fields, (
            f"New coinank field {name!r} not emitted; got keys: "
            f"{sorted(fields)}"
        )
        value, source = fields[name]
        # Each new field must carry a V2-native source label when its
        # input is present.
        assert source.startswith("V2_DERIVED_FROM_") or source.startswith(
            "V2_MARKET_"
        ), (
            f"Field {name!r} source must be a V2-native label; "
            f"got {source!r}"
        )
        # Each new field must carry a numeric (not None) value when
        # the synthetic inputs above are populated.
        assert value is not None, (
            f"Field {name!r} value must be sourced from V2 inputs; got None"
        )


def test_seconds_until_next_funding_correctly_derived() -> None:
    b = _builder()
    # funding.time = 1700000000000 ms, nextFundingTime = 1700028800000 ms
    # delta = 28_800_000 ms = 28800 s (8h, typical funding interval).
    out = b._project_coinank(
        market_funding={
            "time": 1700000000000,
            "nextFundingTime": 1700028800000,
        },
        market_open_interest=None,
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.seconds_until_next_funding"]
    assert value == 28800.0
    assert source == "V2_DERIVED_FROM_FUNDING"


def test_seconds_until_next_funding_missing_when_inputs_absent() -> None:
    """Missing nextFundingTime or funding.time → None with
    MISSING_FROM_V2_FUNDING. Never silently 0."""
    b = _builder()
    # Missing nextFundingTime
    out = b._project_coinank(
        market_funding={"time": 1700000000000},  # no nextFundingTime
        market_open_interest=None,
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.seconds_until_next_funding"]
    assert value is None
    assert source == "MISSING_FROM_V2_FUNDING"
    # Both missing
    out = b._project_coinank(
        market_funding={},
        market_open_interest=None,
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.seconds_until_next_funding"]
    assert value is None
    assert source == "MISSING_FROM_V2_FUNDING"


def test_funding_oi_direction_agreement_logic() -> None:
    b = _builder()
    # Same direction (both positive) → 1.0
    out = b._project_coinank(
        market_funding={"lastFundingRate": 0.0001},
        market_open_interest=None,
        market_price=None,
        v2_features={"oi_change_pct": 0.005},
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.funding_oi_direction_agreement"]
    assert value == 1.0
    assert source == "V2_DERIVED_FROM_FUNDING_AND_FEATURES"
    # Opposite direction → 0.0
    out = b._project_coinank(
        market_funding={"lastFundingRate": 0.0001},
        market_open_interest=None,
        market_price=None,
        v2_features={"oi_change_pct": -0.005},
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.funding_oi_direction_agreement"]
    assert value == 0.0
    # Missing funding → MISSING_FROM_V2_FUNDING
    out = b._project_coinank(
        market_funding={},
        market_open_interest=None,
        market_price=None,
        v2_features={"oi_change_pct": 0.005},
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.funding_oi_direction_agreement"]
    assert value is None
    assert source == "MISSING_FROM_V2_FUNDING"
    # Missing oi_change → MISSING_FROM_V2_FEATURES
    out = b._project_coinank(
        market_funding={"lastFundingRate": 0.0001},
        market_open_interest=None,
        market_price=None,
        v2_features={},
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.funding_oi_direction_agreement"]
    assert value is None
    assert source == "MISSING_FROM_V2_FEATURES"


def test_funding_rate_bps_is_unit_conversion_of_last_funding() -> None:
    b = _builder()
    out = b._project_coinank(
        market_funding={"lastFundingRate": 0.0001},
        market_open_interest=None,
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.funding_rate_bps"]
    assert value == 1.0  # 0.0001 * 10000 = 1 bp
    assert source == "V2_DERIVED_FROM_FUNDING"


def test_mark_premium_to_index_bps_is_unit_conversion_of_basis_pct() -> None:
    b = _builder()
    # mark=50050, index=50000 → basis_pct=0.001, bps=10.0
    out = b._project_coinank(
        market_funding={"markPrice": 50050.0, "indexPrice": 50000.0},
        market_open_interest=None,
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    value, source = fields["coinank.mark_premium_to_index_bps"]
    assert value == 10.0
    assert source == "V2_DERIVED_FROM_FUNDING"


def test_funding_and_oi_payload_age_non_negative() -> None:
    """Payload age fields must be non-negative real seconds, sourced
    from the payload's own timestamp."""
    b = _builder()
    # Use a very-old timestamp so age is clearly positive.
    out = b._project_coinank(
        market_funding={"time": 1700000000000},
        market_open_interest={"time": 1700000000000},
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    funding_age, funding_age_src = fields["coinank.funding_payload_age_seconds"]
    oi_age, oi_age_src = fields["coinank.oi_payload_age_seconds"]
    assert funding_age is not None and funding_age >= 0.0
    assert oi_age is not None and oi_age >= 0.0
    assert funding_age_src == "V2_DERIVED_FROM_FUNDING_TIMESTAMP"
    assert oi_age_src == "V2_DERIVED_FROM_OPEN_INTEREST_TIMESTAMP"


def test_payload_age_missing_when_timestamp_absent() -> None:
    b = _builder()
    out = b._project_coinank(
        market_funding={},  # no 'time'
        market_open_interest={},
        market_price=None,
        v2_features=None,
    )
    fields = _coinank_field_dict(out)
    assert fields["coinank.funding_payload_age_seconds"] == (
        None, "MISSING_FROM_V2_FUNDING"
    )
    assert fields["coinank.oi_payload_age_seconds"] == (
        None, "MISSING_FROM_V2_OI"
    )


def test_coinank_projector_output_has_exactly_22_slots() -> None:
    """Subfamily size budget must remain at 22."""
    b = _builder()
    out = b._project_coinank(None, None, None, None)
    assert len(out) == 22
    # All 22 entries are (name, value, source) triples.
    for entry in out:
        assert isinstance(entry, tuple) and len(entry) == 3
        name, value, source = entry
        assert isinstance(name, str)
        assert value is None or isinstance(value, (int, float))
        assert isinstance(source, str)


def test_coinank_projector_when_all_inputs_missing() -> None:
    """No fabrication: missing inputs → every data slot is None with
    a missing-source label. The single probe-flag slot
    (``v2_coinank_aggregator_source_available``) intentionally emits
    ``0.0`` with a V2_PROBE_FLAG_* source attribution — that is
    honest evidence that no V2 coinank aggregator is present, not
    fabricated data."""
    b = _builder()
    out = b._project_coinank(None, None, None, None)
    PROBE_FLAGS = {"coinank.v2_coinank_aggregator_source_available"}
    for name, value, source in out:
        if name in PROBE_FLAGS:
            # Probe flag: explicit 0.0 with V2_PROBE_FLAG_* source.
            assert value == 0.0, (
                f"Probe flag {name!r} must emit 0.0 to indicate "
                f"explicit no-source state; got {value!r}"
            )
            assert source.startswith("V2_PROBE_FLAG_"), (
                f"Probe flag {name!r} source must start with "
                f"V2_PROBE_FLAG_; got {source!r}"
            )
            continue
        assert value is None, (
            f"Slot {name!r} must be None when all inputs absent; got {value!r}"
        )
        assert source.startswith("MISSING_FROM_"), (
            f"Slot {name!r} must carry an explicit MISSING_FROM_* source; "
            f"got {source!r}"
        )


def test_target_full_dim_and_slice_sizes_unchanged() -> None:
    b = _builder()
    assert b.TARGET_FULL_DIM == 1911
    assert b.SLICE_SIZES == {
        "unified_features": 1430,
        "portfolio_state": 401,
        "onchain_btc": 15,
        "onchain_eth": 15,
        "position_context": 50,
    }
    total = sum(b.SLICE_SIZES.values())
    assert total == 1911


def test_compact_observation_v1_dim_still_26() -> None:
    """Existing runtime policy input dim must not change."""
    b = _builder()
    res = b.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
    )
    assert res.compact_observation_dim == 26


def test_token_metrics_and_onchain_remain_explicit_missing() -> None:
    """The packet must not touch the EXTERNAL_SOURCE_REQUIRED
    subfamilies. Their source labels must remain unchanged."""
    b = _builder()
    # Token metrics: 18 slots, all carry the external-required label.
    tm = b._project_token_metrics()
    assert len(tm) == 18
    for _, value, source in tm:
        assert value is None
        assert source == "EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS"
    # Onchain BTC + ETH slices: 15 slots each, all carry the
    # ONCHAIN_FEATURE_SOURCE_MISSING label.
    btc_values, _, btc_sources, btc_missing = b._build_onchain_slice("onchain_btc")
    eth_values, _, eth_sources, eth_missing = b._build_onchain_slice("onchain_eth")
    assert len(btc_values) == 15 and all(v is None for v in btc_values)
    assert len(eth_values) == 15 and all(v is None for v in eth_values)
    assert all(s == "ONCHAIN_FEATURE_SOURCE_MISSING" for s in btc_sources)
    assert all(s == "ONCHAIN_FEATURE_SOURCE_MISSING" for s in eth_sources)


def test_aggregate_zero_filled_field_count_remains_zero() -> None:
    """End-to-end: zero_filled_field_count must remain 0 across all
    code paths (open / no-open / blocked gate). Builder must never
    silently zero-fill an unknown field."""
    b = _builder()
    res = b.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_funding={
            "lastFundingRate": 0.0001,
            "markPrice": 50000.0,
            "indexPrice": 49999.0,
            "time": 1700000000000,
            "nextFundingTime": 1700028800000,
        },
        market_open_interest={"openInterest": 1234567.0, "time": 1700000000000},
        market_price={"ticker_24hr": {"lastPrice": 50000.0}},
    )
    assert res.zero_filled_field_count == 0


def test_no_checkpoint_or_parity_claim_in_builder_result() -> None:
    """Per-symbol result must never claim checkpoint compatibility
    or policy-architecture parity."""
    b = _builder()
    res = b.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
    )
    # state must not be COMPLETE
    assert res.state != "FULL_OBSERVATION_BUILDER_COMPLETE"
    # No completion claim on a partial vector.
    assert res.generated_full_observation_dim < b.TARGET_FULL_DIM


def test_status_payload_pins_safety_envelope_and_subfamily_layout() -> None:
    """End-to-end build_full_observation_status must pin
    checkpoint_compatibility_claimed=false,
    policy_architecture_parity_claimed=false,
    zero_filled_field_count aggregate=0, and the coinank subfamily
    target=22."""
    b = _builder()
    status = b.build_full_observation_status()
    assert status["checkpoint_compatibility_claimed"] is False
    assert status["policy_architecture_parity_claimed"] is False
    assert status["zero_filled_field_count"] == 0
    assert status["target_full_observation_dim"] == 1911
    assert status["compact_observation_v1"]["dim"] == 26
    # Coinank subfamily target unchanged.
    coinank_target = status["subfamily_target_counts_total"]["coinank"]
    assert coinank_target == 22
    # token_metrics / onchain_btc / onchain_eth / ccxt_ohlcv stay
    # blocked as EXTERNAL_SOURCE_REQUIRED / OPERATOR_DECISION_REQUIRED.
    assert "unified_feature_family.token_metrics" in status["external_source_required_families"]
    assert "onchain_btc" in status["external_source_required_families"]
    assert "onchain_eth" in status["external_source_required_families"]
    assert "unified_feature_family.ccxt_ohlcv" in status["operator_decision_required_families"]
    # Live gate must stay blocked.
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["approves_canary"] is False
    assert status["approves_legacy_shutdown"] is False
    assert status["approves_redis_trim"] is False
