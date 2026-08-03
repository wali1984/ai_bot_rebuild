"""Alt-data confluence engine.

Combines CoinGlass (derivatives) and Moralis (wallet/token flow) into bounded
confluence scores. Santiment was removed from the system by operator directive
(2026-07-16); social/regime outputs are emitted as missing-masked (None) so the
output schema stays stable and downstream consumers see honest absence.

Invariants (enforced here, tested in unit tests):
- No single provider can push a directional confluence score alone; each
  directional score requires at least two *recognized* provider votes that
  agree on that direction.
- Blocking/reducing/hedging MAY be driven by a single provider (fail-safe
  direction is always allowed).
- Missing provider data is masked, never zero-filled.
- Social euphoria never increases the long score; it only adds risk.
- Direct ``ProviderInput`` callers are validated just as strictly as Redis
  bridge callers.  Invalid identity, types, numbers, or causal clocks are
  excluded and force ``decision_time_safe=false``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

SCHEMA_VERSION = "altdata_confluence_v1"

# A provider payload older than its class allows is stale, not missing.
FRESHNESS_SECONDS_BY_PROVIDER = {
    "coinglass": 300,
    "moralis": 3_600,
    # CoinAnk derivatives/liquidation intel (bridged from the legacy runtime)
    # refreshes on a minute cadence; allow a 10-minute staleness window.
    "coinank": 600,
}

ALLOWED_ACTIONS = ("BLOCK", "REDUCE_SIZE", "REQUIRE_HEDGE", "CONFIDENCE_DELTA")
FORBIDDEN_ACTIONS = ("STANDALONE_APPROVE",)
_STRICT_UTC_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}" r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)$",
    re.ASCII,
)


@dataclass
class ProviderInput:
    provider: str
    present: bool
    stale: bool = False
    features: dict[str, float] = field(default_factory=dict)
    feature_cutoff: str | None = None
    available_at: str | None = None
    generated_at: str | None = None
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
    if type(value) not in (int, float):
        return None
    try:
        out = float(cast("int | float", value))
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _parse_strict_utc(value: object) -> datetime | None:
    if type(value) is not str or not _STRICT_UTC_RFC3339.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed.astimezone(UTC)


def _utc_now() -> datetime:
    """Capture a wall-clock boundary after Python evaluated all input reads."""

    return datetime.now(UTC)


def _canonical_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _provider_validation_error(
    *,
    expected_provider: str,
    value: object,
    composite_generated_at: datetime,
) -> tuple[ProviderInput | None, str | None]:
    """Validate and normalize one direct provider input without raising.

    The function deliberately accepts ``object``.  ``build_confluence`` is a
    runtime boundary, so annotations alone must not be treated as validation.
    """

    if type(value) is not ProviderInput:
        return None, "provider_input_type_invalid"
    if type(value.provider) is not str or value.provider != expected_provider:
        return None, "provider_identity_invalid"
    if type(value.present) is not bool or type(value.stale) is not bool:
        return None, "provider_presence_type_invalid"
    if type(value.features) is not dict:
        return None, "provider_features_type_invalid"
    if (
        type(value.missing_feature_flags) is not tuple
        or type(value.stale_feature_flags) is not tuple
    ):
        return None, "provider_feature_flags_type_invalid"
    all_flags = value.missing_feature_flags + value.stale_feature_flags
    if any(type(flag) is not str or not flag for flag in all_flags):
        return None, "provider_feature_flag_invalid"
    if len(set(value.missing_feature_flags)) != len(value.missing_feature_flags):
        return None, "provider_missing_feature_flags_duplicate"
    if len(set(value.stale_feature_flags)) != len(value.stale_feature_flags):
        return None, "provider_stale_feature_flags_duplicate"

    if value.present is False:
        if (
            value.stale is not False
            or value.features
            or value.feature_cutoff is not None
            or value.available_at is not None
            or value.generated_at is not None
        ):
            return None, "absent_provider_payload_invalid"
        return ProviderInput(provider=expected_provider, present=False), None

    if not value.features:
        return None, "provider_features_empty"
    normalized_features: dict[str, float] = {}
    for name, raw in value.features.items():
        if type(name) is not str or not name or type(raw) not in (int, float):
            return None, "provider_feature_field_invalid"
        try:
            parsed = float(raw)
        except (OverflowError, TypeError, ValueError):
            return None, "provider_feature_value_invalid"
        if not math.isfinite(parsed):
            return None, "provider_feature_value_invalid"
        normalized_features[name] = parsed
    if set(normalized_features).intersection(value.missing_feature_flags):
        return None, "provider_feature_missing_mask_overlap"
    if set(normalized_features).intersection(value.stale_feature_flags):
        return None, "provider_feature_stale_mask_overlap"

    cutoff = _parse_strict_utc(value.feature_cutoff)
    available_at = _parse_strict_utc(value.available_at)
    generated_at = _parse_strict_utc(value.generated_at)
    if cutoff is None or available_at is None or generated_at is None:
        return None, "provider_clock_invalid"
    if not cutoff <= available_at <= generated_at <= composite_generated_at:
        return None, "provider_causal_clock_order_invalid"
    freshness_seconds = FRESHNESS_SECONDS_BY_PROVIDER.get(expected_provider, 3_600)
    age_seconds = (composite_generated_at - available_at).total_seconds()
    effective_stale = bool(value.stale or age_seconds < 0.0 or age_seconds > freshness_seconds)

    return (
        ProviderInput(
            provider=expected_provider,
            present=True,
            stale=effective_stale,
            features=normalized_features,
            feature_cutoff=value.feature_cutoff,
            available_at=value.available_at,
            generated_at=value.generated_at,
            missing_feature_flags=value.missing_feature_flags,
            stale_feature_flags=value.stale_feature_flags,
        ),
        None,
    )


def _latest_feature_cutoff(
    providers: Mapping[str, ProviderInput],
    *,
    contributing_providers: set[str],
) -> str | None:
    """Return the latest cutoff among providers that actually affected output."""

    candidates: list[tuple[datetime, str]] = []
    for name, provider in providers.items():
        raw = provider.feature_cutoff
        if name not in contributing_providers or not provider.present or provider.stale:
            continue
        parsed = _parse_strict_utc(raw)
        if parsed is None or not isinstance(raw, str):
            continue
        candidates.append((parsed, raw))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _direction_vote(
    long_parts: list[float],
    short_parts: list[float],
) -> tuple[str, float] | None:
    """Collapse one provider's recognized signals to one non-conflicting vote."""

    long_strength = sum(long_parts) / len(long_parts) if long_parts else 0.0
    short_strength = sum(short_parts) / len(short_parts) if short_parts else 0.0
    if long_strength > short_strength and long_strength > 0.0:
        return "LONG", _clip01(long_strength)
    if short_strength > long_strength and short_strength > 0.0:
        return "SHORT", _clip01(short_strength)
    return None


def build_confluence(
    *,
    symbol: str,
    timeframe: str,
    coinglass: ProviderInput,
    moralis: ProviderInput,
    coinank: ProviderInput | None = None,
    generated_utc: str,
) -> dict[str, Any]:
    # Function arguments (including the three provider reads in the real CLI)
    # are evaluated before the function body.  Capturing here therefore gives
    # the composite an honest generated-at boundary after those reads.
    composite_generated_at = _utc_now()
    composite_generated_text = _canonical_utc(composite_generated_at)
    cycle_started_at = _parse_strict_utc(generated_utc)
    envelope_rejection_reasons: list[str] = []
    if type(symbol) is not str or not symbol:
        envelope_rejection_reasons.append("symbol_invalid")
    if type(timeframe) is not str or not timeframe:
        envelope_rejection_reasons.append("timeframe_invalid")
    if cycle_started_at is None or cycle_started_at > composite_generated_at:
        envelope_rejection_reasons.append("cycle_started_at_invalid")

    raw_providers: dict[str, object] = {
        "coinglass": coinglass,
        "moralis": moralis,
    }
    # CoinAnk is an optional fourth provider (bridged legacy derivatives /
    # liquidation intel). It only participates when passed, so existing
    # callers and tests are unaffected.
    if coinank is not None:
        raw_providers["coinank"] = coinank

    providers: dict[str, ProviderInput] = {}
    provider_input_rejection_reasons: dict[str, str] = {}
    for expected_provider, raw_provider in raw_providers.items():
        normalized, rejection = _provider_validation_error(
            expected_provider=expected_provider,
            value=raw_provider,
            composite_generated_at=composite_generated_at,
        )
        if normalized is None:
            providers[expected_provider] = ProviderInput(
                provider=expected_provider,
                present=False,
            )
            provider_input_rejection_reasons[expected_provider] = rejection or (
                "provider_input_invalid"
            )
        else:
            providers[expected_provider] = normalized

    coinglass = providers["coinglass"]
    moralis = providers["moralis"]
    coinank = providers.get("coinank")
    loaded_fresh = [name for name, p in providers.items() if p.present and not p.stale]
    missing = [name for name, p in providers.items() if not p.present]
    stale = [name for name, p in providers.items() if p.present and p.stale]
    contributing_providers: set[str] = set()

    features: dict[str, float | None] = {}
    missing_flags: list[str] = []

    def emit(name: str, value: float | None) -> None:
        features[name] = value
        if value is None:
            missing_flags.append(name)

    cg = coinglass.features if coinglass.present and not coinglass.stale else {}
    mo = moralis.features if moralis.present and not moralis.stale else {}
    ca = coinank.features if coinank is not None and coinank.present and not coinank.stale else {}

    # --- CoinGlass: derivatives pressure -------------------------------
    funding_z = _get(cg, "coinglass_funding_rate_zscore")
    oi_div = _get(cg, "coinglass_oi_price_divergence_score")
    ls_extreme = _get(cg, "coinglass_long_short_extreme_score")
    derivatives_parts: list[float] = []
    if funding_z is not None:
        derivatives_parts.append(_squash(funding_z, 2.0))
        contributing_providers.add("coinglass")
    if oi_div is not None:
        derivatives_parts.append(_clip01(oi_div))
        contributing_providers.add("coinglass")
    if ls_extreme is not None:
        derivatives_parts.append(_clip01(ls_extreme))
        contributing_providers.add("coinglass")
    # CoinAnk derivatives fallback: funding rate + long/short imbalance. Only
    # contributes when CoinGlass provided nothing, so it fills the common
    # gap (sparse CoinGlass coverage) without shifting CoinGlass-driven scores.
    if not derivatives_parts:
        ca_funding = _get(ca, "coinank_funding_rate")
        ca_ls = _get(ca, "coinank_long_short_ratio")
        if ca_funding is not None:
            derivatives_parts.append(_squash(ca_funding, 0.0005))
            contributing_providers.add("coinank")
        if ca_ls is not None:
            derivatives_parts.append(_squash(ca_ls - 1.0, 1.0))
            contributing_providers.add("coinank")
    emit(
        "altdata_derivatives_pressure_score",
        sum(derivatives_parts) / len(derivatives_parts) if derivatives_parts else None,
    )

    liq_cascade = _get(cg, "coinglass_liquidation_cascade_score")
    liq_imbalance = _get(cg, "coinglass_liquidation_imbalance_usd")
    sweep_parts: list[float] = []
    if liq_cascade is not None:
        sweep_parts.append(_clip01(liq_cascade))
        contributing_providers.add("coinglass")
    if liq_imbalance is not None:
        sweep_parts.append(_squash(liq_imbalance, 5_000_000.0))
        contributing_providers.add("coinglass")
    # CoinAnk liquidation fallback when CoinGlass is absent.
    if not sweep_parts:
        ca_liq_imbalance = _get(ca, "coinank_liquidation_imbalance_usd")
        if ca_liq_imbalance is not None:
            sweep_parts.append(_squash(ca_liq_imbalance, 1_000_000.0))
            contributing_providers.add("coinank")
    emit("altdata_liquidation_sweep_risk_score", max(sweep_parts) if sweep_parts else None)

    # --- Social + regime (source removed) --------------------------------
    # Santiment (the sole social/on-chain regime source) was removed from the
    # system by operator directive. These outputs stay in the schema but are
    # honestly missing-masked (None) — never zero-filled, never guessed.
    emit("altdata_social_attention_score", None)
    emit("altdata_social_euphoria_risk_score", None)
    emit("altdata_market_regime_score", None)

    # --- Exchange flow pressure (Moralis wallet flow only) ---------------
    # Weight renormalization is honest by construction: pressure is the sum
    # of present flow parts, and the only remaining flow source is Moralis.
    mo_netflow = _get(mo, "moralis_net_exchange_flow_usd")
    if mo_netflow is not None:
        contributing_providers.add("moralis")
    emit("altdata_exchange_flow_pressure_usd", mo_netflow)

    # --- Moralis wallet intelligence ------------------------------------
    accumulation = _get(mo, "moralis_smart_wallet_accumulation_score")
    distribution = _get(mo, "moralis_smart_wallet_distribution_score")
    if accumulation is not None or distribution is not None:
        contributing_providers.add("moralis")
    emit("altdata_wallet_accumulation_score", accumulation)
    emit("altdata_wallet_distribution_score", distribution)

    # --- CoinGlass institutional / options (families may not be polled) -
    etf_btc = _get(cg, "coinglass_btc_etf_net_flow_usd")
    etf_eth = _get(cg, "coinglass_eth_etf_net_flow_usd")
    etf_parts = [p for p in (etf_btc, etf_eth) if p is not None]
    if etf_parts:
        contributing_providers.add("coinglass")
    emit(
        "altdata_institutional_flow_score",
        (
            _clip01(0.5 + math.tanh(math.fsum(part / 2e8 for part in etf_parts)) / 2.0)
            if etf_parts
            else None
        ),
    )
    options_pin = _get(cg, "coinglass_options_pin_risk_score")
    if options_pin is not None:
        contributing_providers.add("coinglass")
    emit("altdata_options_pin_risk_score", options_pin)

    # --- Directional confluence: >=2 agreeing recognized providers -----
    direction_votes: dict[str, tuple[str, float]] = {}
    if cg:
        cg_long: list[float] = []
        cg_short: list[float] = []
        if funding_z is not None and funding_z != 0.0:
            # Extreme positive funding = crowded longs = short-side pressure.
            (cg_short if funding_z > 0 else cg_long).append(_squash(funding_z, 2.0))
        if (
            liq_cascade is not None
            and liq_cascade > 0.0
            and liq_imbalance is not None
            and liq_imbalance != 0.0
        ):
            (cg_long if liq_imbalance < 0 else cg_short).append(_clip01(liq_cascade))
        vote = _direction_vote(cg_long, cg_short)
        if vote is not None:
            direction_votes["coinglass"] = vote
    if mo:
        mo_long: list[float] = []
        mo_short: list[float] = []
        if accumulation is not None and accumulation > 0.0:
            mo_long.append(_clip01(accumulation))
        if distribution is not None and distribution > 0.0:
            mo_short.append(_clip01(distribution))
        if mo_netflow is not None and mo_netflow != 0.0:
            # On-chain inflow to exchanges = sell-side supply.
            (mo_short if mo_netflow > 0 else mo_long).append(_squash(mo_netflow, 1e7))
        vote = _direction_vote(mo_long, mo_short)
        if vote is not None:
            direction_votes["moralis"] = vote
    if ca:
        ca_long: list[float] = []
        ca_short: list[float] = []
        ca_funding_vote = _get(ca, "coinank_funding_rate")
        ca_long_short_vote = _get(ca, "coinank_long_short_ratio")
        ca_liquidation_vote = _get(ca, "coinank_liquidation_imbalance_usd")
        if ca_funding_vote is not None and ca_funding_vote != 0.0:
            (ca_short if ca_funding_vote > 0 else ca_long).append(_squash(ca_funding_vote, 0.0005))
        if ca_long_short_vote is not None and ca_long_short_vote != 1.0:
            # A long-heavy ratio is crowding risk (short-side pressure).
            (ca_short if ca_long_short_vote > 1.0 else ca_long).append(
                _squash(ca_long_short_vote - 1.0, 1.0)
            )
        if ca_liquidation_vote is not None and ca_liquidation_vote != 0.0:
            (ca_short if ca_liquidation_vote > 0 else ca_long).append(
                _squash(ca_liquidation_vote, 1_000_000.0)
            )
        vote = _direction_vote(ca_long, ca_short)
        if vote is not None:
            direction_votes["coinank"] = vote

    euphoria = features.get("altdata_social_euphoria_risk_score")
    long_votes = {
        provider: strength
        for provider, (direction, strength) in direction_votes.items()
        if direction == "LONG"
    }
    short_votes = {
        provider: strength
        for provider, (direction, strength) in direction_votes.items()
        if direction == "SHORT"
    }
    long_score: float | None = None
    if len(long_votes) >= 2:
        long_score_value = _clip01(sum(long_votes.values()) / len(long_votes))
        if euphoria is not None:
            # Euphoria is never bullish confluence; it only erodes long score.
            long_score_value = _clip01(long_score_value - 0.5 * euphoria)
        long_score = long_score_value
        contributing_providers.update(long_votes)
    short_score: float | None = None
    if len(short_votes) >= 2:
        short_score = _clip01(sum(short_votes.values()) / len(short_votes))
        contributing_providers.update(short_votes)
    emit("altdata_confluence_long_score", long_score)
    emit("altdata_confluence_short_score", short_score)

    # --- Fail-safe scores (single provider allowed) ---------------------
    block_parts: list[float] = []
    sweep = features.get("altdata_liquidation_sweep_risk_score")
    dist_score = features.get("altdata_wallet_distribution_score")
    confluence_long_score = features.get("altdata_confluence_long_score")
    if sweep is not None:
        block_parts.append(sweep)
    if euphoria is not None:
        block_parts.append(euphoria * 0.8)
    if (
        dist_score is not None
        and confluence_long_score is not None
        and dist_score > 0.6
        and confluence_long_score > 0.4
    ):
        # Conflict: wallet distribution against long confluence.
        block_parts.append(dist_score)
    emit("altdata_trade_block_score", _clip01(max(block_parts)) if block_parts else None)

    reduce_parts = [p for p in (sweep, euphoria, dist_score) if p is not None]
    emit(
        "altdata_reduce_size_score",
        _clip01(sum(reduce_parts) / len(reduce_parts)) if reduce_parts else None,
    )

    hedge_parts: list[float] = []
    if sweep is not None and sweep > 0.5:
        hedge_parts.append(sweep)
    if (
        dist_score is not None
        and confluence_long_score is not None
        and dist_score > 0.5
        and confluence_long_score > 0.5
    ):
        hedge_parts.append((dist_score + confluence_long_score) / 2.0)
    emit("altdata_hedge_required_score", _clip01(max(hedge_parts)) if hedge_parts else 0.0)

    stale_flags = sorted(
        {f"{name}:{flag}" for name, p in providers.items() for flag in p.stale_feature_flags}
        | {f"{name}:ALL" for name in stale}
    )
    contributing = sorted(contributing_providers)
    noncontributing = sorted(set(loaded_fresh).difference(contributing_providers))
    feature_cutoff = _latest_feature_cutoff(
        providers,
        contributing_providers=contributing_providers,
    )
    decision_time_safe = bool(
        contributing
        and feature_cutoff is not None
        and not envelope_rejection_reasons
        and not provider_input_rejection_reasons
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol if type(symbol) is str else "",
        "timeframe": timeframe if type(timeframe) is str else "",
        "cycle_started_at": generated_utc if cycle_started_at is not None else None,
        "generated_utc": composite_generated_text,
        "generated_at": composite_generated_text,
        "features": features,
        "missing_feature_flags": sorted(missing_flags),
        "stale_feature_flags": stale_flags,
        "providers_present": contributing,
        "providers_loaded_fresh": sorted(loaded_fresh),
        "providers_noncontributing": noncontributing,
        "providers_missing": sorted(missing),
        "providers_stale": sorted(stale),
        "providers_invalid": sorted(provider_input_rejection_reasons),
        "provider_input_rejection_reasons": dict(sorted(provider_input_rejection_reasons.items())),
        "envelope_rejection_reasons": sorted(envelope_rejection_reasons),
        "provider_feature_cutoffs": {name: p.feature_cutoff for name, p in providers.items()},
        "feature_cutoff": feature_cutoff,
        "actual_payload_present": bool(contributing),
        "heartbeat_only": not bool(contributing),
        "decision_time_safe": decision_time_safe,
        "provider_direction_votes": {
            name: {"direction": direction, "strength": strength}
            for name, (direction, strength) in sorted(direction_votes.items())
        },
        "directional_long_agreeing_provider_count": len(long_votes),
        "directional_short_agreeing_provider_count": len(short_votes),
        "allowed_actions": list(ALLOWED_ACTIONS),
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
        "single_provider_can_approve": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
        # Operator directive 2026-07-16: Santiment removed from the system.
        # Social/regime outputs above are missing-masked, and the >=2-provider
        # confluence invariant now runs over recognized, agreeing votes from
        # CoinGlass/Moralis and optional same-timeframe CoinAnk.
        "santiment_removed": True,
    }
