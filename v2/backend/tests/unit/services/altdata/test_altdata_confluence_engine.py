"""Invariant tests for the alt-data confluence engine.

Santiment was removed from the system by operator directive (2026-07-16):
the engine now fuses CoinGlass + Moralis (+ optional CoinAnk), and the
social/regime outputs are permanently missing-masked.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.services.altdata import altdata_confluence_engine as confluence_engine
from app.services.altdata.altdata_confluence_engine import ProviderInput, build_confluence

NOW = "2026-07-09T00:00:00+00:00"
FROZEN_NOW = datetime(2026, 7, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _freeze_engine_generated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confluence_engine, "_utc_now", lambda: FROZEN_NOW)


def _cg(features=None, present=True, stale=False, cutoff="2026-07-09T00:00:00+00:00"):
    return ProviderInput(
        provider="coinglass",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff=cutoff if present else None,
        available_at=cutoff if present else None,
        generated_at=cutoff if present else None,
    )


def _mo(features=None, present=True, stale=False, cutoff="2026-07-09T00:00:00+00:00"):
    return ProviderInput(
        provider="moralis",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff=cutoff if present else None,
        available_at=cutoff if present else None,
        generated_at=cutoff if present else None,
    )


def _ca(features=None, present=True, stale=False, cutoff="2026-07-09T00:00:00+00:00"):
    return ProviderInput(
        provider="coinank",
        present=present,
        stale=stale,
        features=features or {},
        feature_cutoff=cutoff if present else None,
        available_at=cutoff if present else None,
        generated_at=cutoff if present else None,
    )


def _build(cg=None, mo=None, ca=None, *, generated_utc=NOW):
    return build_confluence(
        symbol="BTCUSDT",
        timeframe="1m",
        coinglass=cg or _cg(present=False),
        moralis=mo or _mo(present=False),
        coinank=ca,
        generated_utc=generated_utc,
    )


def test_all_missing_is_masked_not_zero_filled():
    out = _build()
    assert out["actual_payload_present"] is False
    assert out["heartbeat_only"] is True
    assert out["decision_time_safe"] is False
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
    out = _build(
        cg=_cg(
            {
                "coinglass_liquidation_cascade_score": 0.9,
                "coinglass_liquidation_imbalance_usd": 20_000_000.0,
            }
        )
    )
    assert out["features"]["altdata_liquidation_sweep_risk_score"] is not None
    assert out["features"]["altdata_trade_block_score"] >= 0.9
    assert out["features"]["altdata_confluence_long_score"] is None


def test_two_providers_agreeing_produce_confluence():
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo(
            {
                "moralis_smart_wallet_accumulation_score": 0.8,
                "moralis_net_exchange_flow_usd": -5_000_000.0,
            }
        ),
    )
    long_score = out["features"]["altdata_confluence_long_score"]
    short_score = out["features"]["altdata_confluence_short_score"]
    assert long_score is not None and long_score > 0.3
    assert short_score is None
    assert out["directional_long_agreeing_provider_count"] == 2


def test_distribution_conflict_raises_block_and_hedge():
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo(
            {
                "moralis_smart_wallet_accumulation_score": 0.9,
                "moralis_smart_wallet_distribution_score": 0.7,
            }
        ),
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

    out2 = _build(
        mo=_mo(
            {
                "moralis_smart_wallet_accumulation_score": 0.5,
                "moralis_net_exchange_flow_usd": 600.0,
            }
        )
    )
    assert out2["features"]["altdata_exchange_flow_pressure_usd"] == 600.0


def test_feature_cutoff_is_latest_contributing_dependency():
    out = _build(
        cg=_cg(
            {"coinglass_funding_rate_zscore": 1.0},
            cutoff="2026-07-08T23:59:59.900000Z",
        ),
        mo=_mo(
            {"moralis_smart_wallet_accumulation_score": 0.5},
            cutoff="2026-07-08T23:59:59+00:00",
        ),
    )
    assert out["feature_cutoff"] == "2026-07-08T23:59:59.900000Z"
    assert out["cycle_started_at"] == NOW
    assert datetime.fromisoformat(out["feature_cutoff"].replace("Z", "+00:00")) <= (
        datetime.fromisoformat(out["generated_at"].replace("Z", "+00:00"))
    )


def test_stale_provider_cutoff_is_not_a_contributing_dependency():
    out = _build(
        cg=_cg(
            {"coinglass_funding_rate_zscore": 1.0},
            stale=True,
            cutoff="2026-07-08T23:59:59Z",
        ),
        mo=_mo(
            {"moralis_smart_wallet_accumulation_score": 0.5},
            cutoff="2026-07-08T23:59:58Z",
        ),
    )

    assert out["feature_cutoff"] == "2026-07-08T23:59:58Z"


def test_direct_forged_provider_string_numeric_and_future_clock_fail_closed() -> None:
    forged = ProviderInput(
        provider="forged",
        present=True,
        features={"coinglass_liquidation_imbalance_usd": "20000000"},  # type: ignore[dict-item]
        feature_cutoff="2099-01-01T00:00:00Z",
        available_at="2099-01-01T00:00:00Z",
        generated_at="2099-01-01T00:00:00Z",
    )

    out = _build(cg=forged)

    assert out["actual_payload_present"] is False
    assert out["decision_time_safe"] is False
    assert out["features"]["altdata_trade_block_score"] is None
    assert out["providers_invalid"] == ["coinglass"]


@pytest.mark.parametrize("value", [True, "2.0", float("nan"), float("inf"), 10**400])
def test_direct_provider_rejects_coerced_nonfinite_or_overflowing_numeric(value: object) -> None:
    invalid = _cg({"coinglass_funding_rate_zscore": value})

    out = _build(cg=invalid)

    assert out["decision_time_safe"] is False
    assert out["actual_payload_present"] is False
    assert out["provider_input_rejection_reasons"]["coinglass"] in {
        "provider_feature_field_invalid",
        "provider_feature_value_invalid",
    }


def test_direct_future_clock_on_correct_provider_is_excluded_and_unsafe() -> None:
    future = _cg(
        {"coinglass_liquidation_cascade_score": 0.99},
        cutoff="2099-01-01T00:00:00Z",
    )

    out = _build(cg=future)

    assert out["actual_payload_present"] is False
    assert out["decision_time_safe"] is False
    assert out["features"]["altdata_trade_block_score"] is None
    assert out["provider_input_rejection_reasons"]["coinglass"] == (
        "provider_causal_clock_order_invalid"
    )


def test_direct_stale_false_is_overridden_by_provider_freshness_age() -> None:
    out = _build(
        cg=_cg(
            {"coinglass_funding_rate_zscore": -2.0},
            stale=False,
            cutoff="2026-07-08T23:50:00Z",
        ),
        mo=_mo(
            {"moralis_smart_wallet_accumulation_score": 0.9},
            stale=False,
            cutoff="2026-07-08T22:00:00Z",
        ),
    )

    assert out["providers_stale"] == ["coinglass", "moralis"]
    assert out["providers_present"] == []
    assert out["actual_payload_present"] is False
    assert out["decision_time_safe"] is False
    assert out["feature_cutoff"] is None
    assert out["features"]["altdata_confluence_long_score"] is None


def test_direct_cutoff_after_available_at_is_excluded_and_unsafe() -> None:
    invalid = _cg(
        {"coinglass_funding_rate_zscore": -2.0},
        cutoff="2026-07-09T00:00:01Z",
    )
    invalid.available_at = "2026-07-09T00:00:00Z"
    invalid.generated_at = "2026-07-09T00:00:02Z"

    out = _build(cg=invalid)

    assert out["decision_time_safe"] is False
    assert out["actual_payload_present"] is False
    assert out["provider_input_rejection_reasons"]["coinglass"] == (
        "provider_causal_clock_order_invalid"
    )


def test_unknown_second_provider_neither_votes_nor_controls_cutoff() -> None:
    out = _build(
        cg=_cg(
            {"coinglass_funding_rate_zscore": -2.0},
            cutoff="2026-07-08T23:59:58Z",
        ),
        mo=_mo(
            {"moralis_unknown_numeric_feature": 0.9},
            cutoff="2026-07-08T23:59:59Z",
        ),
    )

    assert out["features"]["altdata_confluence_long_score"] is None
    assert out["directional_long_agreeing_provider_count"] == 1
    assert out["providers_noncontributing"] == ["moralis"]
    assert out["feature_cutoff"] == "2026-07-08T23:59:58Z"


def test_recognized_directional_disagreement_emits_no_actionable_score() -> None:
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        mo=_mo({"moralis_smart_wallet_distribution_score": 0.9}),
    )

    assert out["provider_direction_votes"]["coinglass"]["direction"] == "LONG"
    assert out["provider_direction_votes"]["moralis"]["direction"] == "SHORT"
    assert out["features"]["altdata_confluence_long_score"] is None
    assert out["features"]["altdata_confluence_short_score"] is None


def test_coinank_can_be_second_recognized_agreeing_provider() -> None:
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        ca=_ca({"coinank_funding_rate": -0.0005}),
    )

    assert out["features"]["altdata_confluence_long_score"] is not None
    assert out["directional_long_agreeing_provider_count"] == 2


def test_direct_feature_missing_mask_overlap_is_rejected() -> None:
    overlapping = _cg({"coinglass_funding_rate_zscore": -2.0})
    overlapping.missing_feature_flags = ("coinglass_funding_rate_zscore",)

    out = _build(cg=overlapping)

    assert out["decision_time_safe"] is False
    assert out["provider_input_rejection_reasons"]["coinglass"] == (
        "provider_feature_missing_mask_overlap"
    )


def test_direct_feature_stale_mask_overlap_is_rejected() -> None:
    overlapping = _cg({"coinglass_funding_rate_zscore": -2.0})
    overlapping.stale_feature_flags = ("coinglass_funding_rate_zscore",)

    out = _build(cg=overlapping)

    assert out["decision_time_safe"] is False
    assert out["provider_input_rejection_reasons"]["coinglass"] == (
        "provider_feature_stale_mask_overlap"
    )


@pytest.mark.parametrize(
    "generated_utc",
    ["2026-07-09 00:00:00Z", "2099-01-01T00:00:00Z", 1_753_011_200],
)
def test_invalid_cycle_clock_never_reports_decision_time_safe(generated_utc: object) -> None:
    out = _build(
        cg=_cg({"coinglass_funding_rate_zscore": -2.0}),
        generated_utc=generated_utc,  # type: ignore[arg-type]
    )

    assert out["decision_time_safe"] is False
    assert "cycle_started_at_invalid" in out["envelope_rejection_reasons"]


def test_generated_at_is_captured_after_inputs_and_before_publication() -> None:
    out = _build(cg=_cg({"coinglass_funding_rate_zscore": -2.0}))

    captured = datetime.fromisoformat(out["generated_at"].replace("Z", "+00:00"))
    assert captured == FROZEN_NOW
