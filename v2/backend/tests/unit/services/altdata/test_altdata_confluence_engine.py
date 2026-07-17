"""Invariant tests for the alt-data confluence engine.

Santiment was removed from the system by operator directive (2026-07-16):
the engine now fuses CoinGlass + Moralis (+ optional CoinAnk), and the
social/regime outputs are permanently missing-masked.
"""

from __future__ import annotations

from app.services.altdata.altdata_confluence_engine import ProviderInput, build_confluence

NOW = "2026-07-09T00:00:00+00:00"


def _cg(features=None, present=True, stale=False, cutoff="2026-07-09T00:00:00+00:00"):
    return ProviderInput(
        provider="coinglass",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff=cutoff,
    )


def _mo(features=None, present=True, stale=False, cutoff="2026-07-09T00:00:00+00:00"):
    return ProviderInput(
        provider="moralis",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff=cutoff,
    )


def _build(cg=None, mo=None):
    return build_confluence(
        symbol="BTCUSDT",
        timeframe="1m",
        coinglass=cg or _cg(present=False),
        moralis=mo or _mo(present=False),
        generated_utc=NOW,
    )


def test_all_missing_is_masked_not_zero_filled():
    out = _build()
    assert out["actual_payload_present"] is False
    assert out["heartbeat_only"] is True
    assert out["providers_missing"] == ["coinglass", "moralis"]
    for name, value in out["features"].items():
        if name == "altdata_hedge_required_score":
            continue  # fail-safe floor of 0.0 is intentional
        assert value is None, f"{name} must be masked when no provider is present"
    assert "altdata_confluence_long_score" in out["missing_feature_flags"]


def test_santiment_removed_socials_always_masked():
    """The social/regime family lost its only source (Santiment removed);
    those outputs must stay in the schema but always be missing-masked."""
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo({"moralis_smart_wallet_accumulation_score": 0.9}),
    )
    assert out["santiment_removed"] is True
    assert "santiment" not in out["providers_present"]
    assert "santiment" not in out["providers_missing"]
    for name in (
        "altdata_social_attention_score",
        "altdata_social_euphoria_risk_score",
        "altdata_market_regime_score",
    ):
        assert out["features"][name] is None
        assert name in out["missing_feature_flags"]


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


def test_stale_provider_is_flagged_and_excluded():
    out = _build(cg=_cg({"coinglass_funding_rate_zscore": 3.0}, stale=True))
    assert out["providers_stale"] == ["coinglass"]
    assert out["features"]["altdata_derivatives_pressure_score"] is None
    assert "coinglass:ALL" in out["stale_feature_flags"]


def test_exchange_flow_pressure_is_moralis_only():
    out = _build(mo=_mo({"moralis_smart_wallet_accumulation_score": 0.5}))
    assert out["features"]["altdata_exchange_flow_pressure_usd"] is None

    out2 = _build(mo=_mo({
        "moralis_smart_wallet_accumulation_score": 0.5,
        "moralis_net_exchange_flow_usd": 600.0,
    }))
    assert out2["features"]["altdata_exchange_flow_pressure_usd"] == 600.0


def test_feature_cutoff_is_conservative_minimum():
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": 1.0}),
        mo=_mo({"moralis_smart_wallet_accumulation_score": 0.5}, cutoff="2026-06-08T00:00:00+00:00"),
    )
    assert out["feature_cutoff"] == "2026-06-08T00:00:00+00:00"
