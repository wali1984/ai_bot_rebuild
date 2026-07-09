"""Invariant tests for the alt-data confluence engine."""

from __future__ import annotations

from app.services.altdata.altdata_confluence_engine import ProviderInput, build_confluence

NOW = "2026-07-09T00:00:00+00:00"


def _cg(features=None, present=True, stale=False):
    return ProviderInput(
        provider="coinglass",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff="2026-07-09T00:00:00+00:00",
    )


def _sa(features=None, present=True, stale=False):
    return ProviderInput(
        provider="santiment",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff="2026-06-08T00:00:00+00:00",
    )


def _mo(features=None, present=True, stale=False):
    return ProviderInput(
        provider="moralis",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff="2026-07-09T00:00:00+00:00",
    )


def _build(cg=None, sa=None, mo=None):
    return build_confluence(
        symbol="BTCUSDT",
        timeframe="1m",
        coinglass=cg or _cg(present=False),
        santiment=sa or _sa(present=False),
        moralis=mo or _mo(present=False),
        generated_utc=NOW,
    )


def test_all_missing_is_masked_not_zero_filled():
    out = _build()
    assert out["actual_payload_present"] is False
    assert out["heartbeat_only"] is True
    assert out["providers_missing"] == ["coinglass", "moralis", "santiment"]
    for name, value in out["features"].items():
        if name == "altdata_hedge_required_score":
            continue  # fail-safe floor of 0.0 is intentional
        assert value is None, f"{name} must be masked when no provider is present"
    assert "altdata_confluence_long_score" in out["missing_feature_flags"]


def test_single_provider_cannot_produce_confluence_scores():
    out = _build(cg=_cg({"coinglass_funding_rate_zscore": -2.5}))
    assert out["features"]["altdata_confluence_long_score"] is None
    assert out["features"]["altdata_confluence_short_score"] is None
    assert out["single_provider_can_approve"] is False
    assert "STANDALONE_APPROVE" in out["forbidden_actions"]


def test_single_provider_can_still_block():
    out = _build(cg=_cg({
        "coinglass_liquidation_cascade_score": 0.9,
        "coinglass_liquidation_imbalance_usd": 20_000_000.0,
    }))
    assert out["features"]["altdata_liquidation_sweep_risk_score"] is not None
    assert out["features"]["altdata_trade_block_score"] >= 0.9
    assert out["features"]["altdata_confluence_long_score"] is None


def test_two_providers_agreeing_produce_confluence():
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo({
            "moralis_smart_wallet_accumulation_score": 0.8,
            "moralis_net_exchange_flow_usd": -5_000_000.0,
        }),
    )
    long_score = out["features"]["altdata_confluence_long_score"]
    short_score = out["features"]["altdata_confluence_short_score"]
    assert long_score is not None and long_score > 0.3
    assert short_score is not None and short_score <= long_score


def test_distribution_conflict_raises_block_and_hedge():
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo({
            "moralis_smart_wallet_accumulation_score": 0.7,
            "moralis_smart_wallet_distribution_score": 0.9,
        }),
    )
    assert out["features"]["altdata_trade_block_score"] is not None
    assert out["features"]["altdata_trade_block_score"] >= 0.5
    assert out["features"]["altdata_reduce_size_score"] > 0.0
    assert out["features"]["altdata_hedge_required_score"] > 0.0


def test_euphoria_never_increases_long_score():
    base = dict(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo({"moralis_smart_wallet_accumulation_score": 0.9}),
    )
    calm = _build(**base)
    euphoric = _build(
        sa=_sa({
            "social_volume_total": 5_000.0,
            "social_dominance_total": 20.0,
            "sentiment_weighted_total": 3.0,
        }),
        **base,
    )
    assert euphoric["features"]["altdata_social_euphoria_risk_score"] > 0.5
    assert (
        euphoric["features"]["altdata_confluence_long_score"]
        <= calm["features"]["altdata_confluence_long_score"]
    )


def test_stale_provider_is_flagged_and_excluded():
    out = _build(cg=_cg({"coinglass_funding_rate_zscore": 3.0}, stale=True))
    assert out["providers_stale"] == ["coinglass"]
    assert out["features"]["altdata_derivatives_pressure_score"] is None
    assert "coinglass:ALL" in out["stale_feature_flags"]


def test_exchange_netflow_requires_both_directions():
    out = _build(sa=_sa({"exchange_inflow": 1_000.0}), mo=_mo({"moralis_smart_wallet_accumulation_score": 0.5}))
    assert out["features"]["altdata_exchange_flow_pressure_usd"] is None

    out2 = _build(
        sa=_sa({"exchange_inflow": 1_000.0, "exchange_outflow": 400.0}),
        mo=_mo({"moralis_smart_wallet_accumulation_score": 0.5}),
    )
    assert out2["features"]["altdata_exchange_flow_pressure_usd"] == 600.0


def test_feature_cutoff_is_conservative_minimum():
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": 1.0}),
        sa=_sa({"mvrv_usd": 1.2}),
    )
    assert out["feature_cutoff"] == "2026-06-08T00:00:00+00:00"
