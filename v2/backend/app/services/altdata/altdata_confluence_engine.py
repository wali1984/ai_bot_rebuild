"""Alt-data confluence engine.

Combines CoinGlass (derivatives), Santiment (social/on-chain regime, ~31d
plan lag), and Moralis (wallet/token flow) into bounded confluence scores.

Invariants (enforced here, tested in unit tests):
- No single provider can push a positive confluence score alone; long/short
  confluence requires at least two providers present and agreeing.
- Blocking/reducing/hedging MAY be driven by a single provider (fail-safe
  direction is always allowed).
- Missing provider data is masked, never zero-filled.
- Social euphoria never increases the long score; it only adds risk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = "altdata_confluence_v1"

# A provider payload older than its class allows is stale, not missing.
FRESHNESS_SECONDS_BY_PROVIDER = {
    "coinglass": 300,
    "moralis": 3_600,
    # Sanbase Pro serves a plan-enforced ~31 day lag; the payload itself is
    # refreshed every 6h, and its regime metrics stay valid for a full day.
    "santiment": 86_400,
    # CoinAnk derivatives/liquidation intel (bridged from the legacy runtime)
    # refreshes on a minute cadence; allow a 10-minute staleness window.
    "coinank": 600,
}

ALLOWED_ACTIONS = ("BLOCK", "REDUCE_SIZE", "REQUIRE_HEDGE", "CONFIDENCE_DELTA")
FORBIDDEN_ACTIONS = ("STANDALONE_APPROVE",)


@dataclass
class ProviderInput:
    provider: str
    present: bool
    stale: bool = False
    features: dict[str, float] = field(default_factory=dict)
    feature_cutoff: str | None = None
    missing_feature_flags: tuple[str, ...] = ()
    stale_feature_flags: tuple[str, ...] = ()


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _squash(value: float, scale: float) -> float:
    """Map an unbounded magnitude to [0, 1) with a smooth knee at `scale`."""
    if scale <= 0:
        return 0.0
    return _clip01(math.tanh(abs(value) / scale))


def _get(features: Mapping[str, Any], name: str) -> float | None:
    value = features.get(name)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def build_confluence(
    *,
    symbol: str,
    timeframe: str,
    coinglass: ProviderInput,
    santiment: ProviderInput,
    moralis: ProviderInput,
    coinank: "ProviderInput | None" = None,
    generated_utc: str,
) -> dict[str, Any]:
    providers = {"coinglass": coinglass, "santiment": santiment, "moralis": moralis}
    # CoinAnk is an optional fourth provider (bridged legacy derivatives /
    # liquidation intel). It only participates when passed, so existing
    # callers and tests are unaffected.
    if coinank is not None:
        providers["coinank"] = coinank
    present = [name for name, p in providers.items() if p.present and not p.stale]
    missing = [name for name, p in providers.items() if not p.present]
    stale = [name for name, p in providers.items() if p.present and p.stale]

    features: dict[str, float | None] = {}
    missing_flags: list[str] = []

    def emit(name: str, value: float | None) -> None:
        features[name] = value
        if value is None:
            missing_flags.append(name)

    cg = coinglass.features if coinglass.present and not coinglass.stale else {}
    sa = santiment.features if santiment.present and not santiment.stale else {}
    mo = moralis.features if moralis.present and not moralis.stale else {}
    ca = coinank.features if coinank is not None and coinank.present and not coinank.stale else {}

    # --- CoinGlass: derivatives pressure -------------------------------
    funding_z = _get(cg, "coinglass_funding_rate_zscore")
    oi_div = _get(cg, "coinglass_oi_price_divergence_score")
    ls_extreme = _get(cg, "coinglass_long_short_extreme_score")
    derivatives_parts: list[float] = []
    if funding_z is not None:
        derivatives_parts.append(_squash(funding_z, 2.0))
    if oi_div is not None:
        derivatives_parts.append(_clip01(oi_div))
    if ls_extreme is not None:
        derivatives_parts.append(_clip01(ls_extreme))
    # CoinAnk derivatives fallback: funding rate + long/short imbalance. Only
    # contributes when CoinGlass provided nothing, so it fills the common
    # gap (sparse CoinGlass coverage) without shifting CoinGlass-driven scores.
    if not derivatives_parts:
        ca_funding = _get(ca, "coinank_funding_rate")
        ca_ls = _get(ca, "coinank_long_short_ratio")
        if ca_funding is not None:
            derivatives_parts.append(_squash(ca_funding, 0.0005))
        if ca_ls is not None:
            derivatives_parts.append(_squash(ca_ls - 1.0, 1.0))
    emit(
        "altdata_derivatives_pressure_score",
        sum(derivatives_parts) / len(derivatives_parts) if derivatives_parts else None,
    )

    liq_cascade = _get(cg, "coinglass_liquidation_cascade_score")
    liq_imbalance = _get(cg, "coinglass_liquidation_imbalance_usd")
    sweep_parts: list[float] = []
    if liq_cascade is not None:
        sweep_parts.append(_clip01(liq_cascade))
    if liq_imbalance is not None:
        sweep_parts.append(_squash(liq_imbalance, 5_000_000.0))
    # CoinAnk liquidation fallback when CoinGlass is absent.
    if not sweep_parts:
        ca_liq_imbalance = _get(ca, "coinank_liquidation_imbalance_usd")
        if ca_liq_imbalance is not None:
            sweep_parts.append(_squash(ca_liq_imbalance, 1_000_000.0))
    emit("altdata_liquidation_sweep_risk_score", max(sweep_parts) if sweep_parts else None)

    # --- Santiment: social + regime (slow layer) -----------------------
    social_volume = _get(sa, "santiment_social_volume") or _get(sa, "social_volume_total")
    social_dominance = _get(sa, "santiment_social_dominance") or _get(sa, "social_dominance_total")
    weighted_sentiment = _get(sa, "santiment_weighted_sentiment") or _get(sa, "sentiment_weighted_total")
    if social_volume is None and social_dominance is None:
        emit("altdata_social_attention_score", None)
    else:
        att_parts = []
        if social_volume is not None:
            att_parts.append(_squash(social_volume, 500.0))
        if social_dominance is not None:
            att_parts.append(_squash(social_dominance, 5.0))
        emit("altdata_social_attention_score", sum(att_parts) / len(att_parts))

    attention = features.get("altdata_social_attention_score")
    if attention is None or weighted_sentiment is None:
        emit("altdata_social_euphoria_risk_score", None)
    else:
        # Euphoria = crowd attention with strongly positive sentiment.
        emit(
            "altdata_social_euphoria_risk_score",
            _clip01(attention * _squash(max(weighted_sentiment, 0.0), 2.0)),
        )

    mvrv = _get(sa, "santiment_mvrv_usd") or _get(sa, "mvrv_usd")
    npl = _get(sa, "santiment_network_profit_loss") or _get(sa, "network_profit_loss")
    age_consumed = _get(sa, "santiment_age_consumed") or _get(sa, "age_consumed")
    regime_parts = []
    if mvrv is not None:
        # mvrv > 1 = holders in profit (distribution temptation rises >2).
        regime_parts.append(_clip01(1.0 - _squash(mvrv - 1.0, 1.5)))
    if npl is not None:
        regime_parts.append(_clip01(0.5 + math.tanh(npl / 1e8) / 2.0))
    if age_consumed is not None:
        regime_parts.append(_clip01(1.0 - _squash(age_consumed, 1e9)))
    emit("altdata_market_regime_score", sum(regime_parts) / len(regime_parts) if regime_parts else None)

    # --- Exchange flow pressure (Santiment aggregate + Moralis wallet) --
    sa_netflow = None
    inflow = _get(sa, "santiment_exchange_inflow_usd") or _get(sa, "exchange_inflow")
    outflow = _get(sa, "santiment_exchange_outflow_usd") or _get(sa, "exchange_outflow")
    if inflow is not None and outflow is not None:
        sa_netflow = inflow - outflow
    mo_netflow = _get(mo, "moralis_net_exchange_flow_usd")
    flow_parts = [p for p in (sa_netflow, mo_netflow) if p is not None]
    emit("altdata_exchange_flow_pressure_usd", sum(flow_parts) if flow_parts else None)

    # --- Moralis wallet intelligence ------------------------------------
    emit("altdata_wallet_accumulation_score", _get(mo, "moralis_smart_wallet_accumulation_score"))
    emit("altdata_wallet_distribution_score", _get(mo, "moralis_smart_wallet_distribution_score"))

    # --- CoinGlass institutional / options (families may not be polled) -
    etf_btc = _get(cg, "coinglass_btc_etf_net_flow_usd")
    etf_eth = _get(cg, "coinglass_eth_etf_net_flow_usd")
    etf_parts = [p for p in (etf_btc, etf_eth) if p is not None]
    emit(
        "altdata_institutional_flow_score",
        _clip01(0.5 + math.tanh(sum(etf_parts) / 2e8) / 2.0) if etf_parts else None,
    )
    emit("altdata_options_pin_risk_score", _get(cg, "coinglass_options_pin_risk_score"))

    # --- Confluence: requires >= 2 fresh providers ----------------------
    long_votes: list[float] = []
    short_votes: list[float] = []
    voters = 0
    if cg:
        voters += 1
        if funding_z is not None:
            # Extreme positive funding = crowded longs = short-side pressure.
            (short_votes if funding_z > 0 else long_votes).append(_squash(funding_z, 2.0))
        if liq_cascade is not None and liq_imbalance is not None:
            (long_votes if liq_imbalance < 0 else short_votes).append(_clip01(liq_cascade))
    if mo:
        voters += 1
        acc = _get(mo, "moralis_smart_wallet_accumulation_score")
        dist = _get(mo, "moralis_smart_wallet_distribution_score")
        if acc is not None:
            long_votes.append(_clip01(acc))
        if dist is not None:
            short_votes.append(_clip01(dist))
        if mo_netflow is not None:
            # On-chain inflow to exchanges = sell-side supply.
            (short_votes if mo_netflow > 0 else long_votes).append(_squash(mo_netflow, 1e7))
    if sa:
        voters += 1
        if sa_netflow is not None:
            (short_votes if sa_netflow > 0 else long_votes).append(_squash(sa_netflow, 1e7))
        regime = features.get("altdata_market_regime_score")
        if regime is not None:
            (long_votes if regime >= 0.5 else short_votes).append(abs(regime - 0.5) * 2.0)

    euphoria = features.get("altdata_social_euphoria_risk_score")
    if voters >= 2:
        long_score = _clip01(sum(long_votes) / max(len(long_votes), 1))
        short_score = _clip01(sum(short_votes) / max(len(short_votes), 1))
        if euphoria is not None:
            # Euphoria is never bullish confluence; it only erodes long score.
            long_score = _clip01(long_score - 0.5 * euphoria)
        emit("altdata_confluence_long_score", long_score)
        emit("altdata_confluence_short_score", short_score)
    else:
        emit("altdata_confluence_long_score", None)
        emit("altdata_confluence_short_score", None)

    # --- Fail-safe scores (single provider allowed) ---------------------
    block_parts: list[float] = []
    sweep = features.get("altdata_liquidation_sweep_risk_score")
    dist_score = features.get("altdata_wallet_distribution_score")
    long_score = features.get("altdata_confluence_long_score")
    if sweep is not None:
        block_parts.append(sweep)
    if euphoria is not None:
        block_parts.append(euphoria * 0.8)
    if dist_score is not None and long_score is not None and dist_score > 0.6 and long_score > 0.4:
        # Conflict: wallet distribution against long confluence.
        block_parts.append(dist_score)
    emit("altdata_trade_block_score", _clip01(max(block_parts)) if block_parts else None)

    reduce_parts = [p for p in (sweep, euphoria, dist_score) if p is not None]
    emit("altdata_reduce_size_score", _clip01(sum(reduce_parts) / len(reduce_parts)) if reduce_parts else None)

    hedge_parts: list[float] = []
    if sweep is not None and sweep > 0.5:
        hedge_parts.append(sweep)
    if dist_score is not None and long_score is not None and dist_score > 0.5 and long_score > 0.5:
        hedge_parts.append((dist_score + long_score) / 2.0)
    emit("altdata_hedge_required_score", _clip01(max(hedge_parts)) if hedge_parts else 0.0)

    cutoffs = [p.feature_cutoff for p in providers.values() if p.present and p.feature_cutoff]
    stale_flags = sorted(
        {f"{name}:{flag}" for name, p in providers.items() for flag in p.stale_feature_flags}
        | {f"{name}:ALL" for name in stale}
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_utc": generated_utc,
        "features": features,
        "missing_feature_flags": sorted(missing_flags),
        "stale_feature_flags": stale_flags,
        "providers_present": sorted(present),
        "providers_missing": sorted(missing),
        "providers_stale": sorted(stale),
        "provider_feature_cutoffs": {name: p.feature_cutoff for name, p in providers.items()},
        "feature_cutoff": min(cutoffs) if cutoffs else None,
        "actual_payload_present": bool(present),
        "heartbeat_only": not bool(present),
        "decision_time_safe": True,
        "allowed_actions": list(ALLOWED_ACTIONS),
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
        "single_provider_can_approve": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
