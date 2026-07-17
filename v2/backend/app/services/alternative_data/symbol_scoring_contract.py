"""Symbol scoring contract for V2 alternative data.

Consumes V2 paper/shadow alternative-data payloads already written by
provider clients. This module never calls provider APIs, never writes
Redis, and cannot override trading gates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

OK_SOURCE_STATUSES = frozenset({"API_OK", "CACHE_HIT", "DERIVED_OK"})
SUPPORTED_PROVIDERS = (
    "coingecko",
    "surf",
    "coinglass",
    "public_intel",
    "whale_walls",
)
DEFAULT_MAX_PROVIDER_AGE_SECONDS = 1_800


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _round_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _payload_age_seconds(payload: Mapping[str, Any], generated_utc: str) -> int | None:
    provider_freshness = _coerce_float(payload.get("provider_freshness_seconds"))
    if provider_freshness is not None:
        return max(0, int(provider_freshness))
    return _payload_publication_age_seconds(payload, generated_utc)


def _payload_publication_age_seconds(
    payload: Mapping[str, Any], generated_utc: str
) -> int | None:
    generated = _parse_utc(payload.get("generated_utc"))
    now = _parse_utc(generated_utc)
    if generated is None or now is None:
        return None
    return max(0, int((now - generated).total_seconds()))


def _provider_freshness_score(age_seconds: int | None, max_age_seconds: int) -> float:
    if age_seconds is None:
        return 0.0
    if max_age_seconds <= 0:
        return 0.0
    return _clamp01(1.0 - (float(age_seconds) / float(max_age_seconds)))


def _source_status(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return "MISSING_PAYLOAD"
    status = payload.get("source_status")
    return str(status) if status else "MISSING_SOURCE_STATUS"


def _is_provider_available(
    payload: Mapping[str, Any] | None,
    *,
    generated_utc: str,
    max_provider_age_seconds: int,
) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if _source_status(payload) not in OK_SOURCE_STATUSES:
        return False
    age = _payload_age_seconds(payload, generated_utc)
    if age is None:
        return True
    return age <= max_provider_age_seconds


def _extract_coingecko(coingecko_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(coingecko_payload, Mapping):
        return {
            "coingecko_discovery_score": None,
            "coingecko_liquidity_score": None,
            "coingecko_momentum_score": None,
            "coingecko_trend_score": None,
        }
    discovery = _coerce_float(coingecko_payload.get("coingecko_discovery_score"))
    liquidity = _coerce_float(coingecko_payload.get("coingecko_liquidity_score"))
    momentum = _coerce_float(coingecko_payload.get("coingecko_momentum_score"))
    trend = _coerce_float(coingecko_payload.get("coingecko_trend_score"))
    return {
        "coingecko_discovery_score": (
            _clamp01(discovery) if discovery is not None else None
        ),
        "coingecko_liquidity_score": (
            _clamp01(liquidity) if liquidity is not None else None
        ),
        "coingecko_momentum_score": (
            _clamp01(momentum) if momentum is not None else None
        ),
        "coingecko_trend_score": _clamp01(trend) if trend is not None else None,
    }


def _extract_surf(surf_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(surf_payload, Mapping):
        return {
            "surf_market_price_signal_score": None,
            "surf_price_observation_count": None,
        }
    score = _coerce_float(surf_payload.get("surf_market_price_signal_score"))
    count = _coerce_float(surf_payload.get("surf_price_observation_count"))
    return {
        "surf_market_price_signal_score": (
            _clamp01(score) if score is not None else None
        ),
        "surf_price_observation_count": count,
    }


def _extract_coinglass(coinglass_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(coinglass_payload, Mapping):
        return {"coinglass_derivatives_score": None}
    score = _coerce_float(coinglass_payload.get("coinglass_derivatives_score"))
    return {
        "coinglass_derivatives_score": (
            _clamp01(score) if score is not None else None
        )
    }


def _extract_public_intel(public_intel_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(public_intel_payload, Mapping):
        return {
            "public_intel_score": None,
            "defillama_liquidity_score": None,
            "defillama_tvl_momentum_score": None,
            "news_attention_score": None,
            "news_sentiment_score": None,
            "fear_greed_score": None,
            "btc_mempool_pressure_score": None,
        }
    public_score = _coerce_float(public_intel_payload.get("public_intel_score"))
    defillama_liquidity = _coerce_float(
        public_intel_payload.get("defillama_liquidity_score")
    )
    defillama_momentum = _coerce_float(
        public_intel_payload.get("defillama_tvl_momentum_score")
    )
    news_attention = _coerce_float(public_intel_payload.get("news_attention_score"))
    news_sentiment = _coerce_float(public_intel_payload.get("news_sentiment_score"))
    fear_greed = _coerce_float(public_intel_payload.get("fear_greed_score"))
    mempool_pressure = _coerce_float(
        public_intel_payload.get("btc_mempool_pressure_score")
    )
    return {
        "public_intel_score": _clamp01(public_score) if public_score is not None else None,
        "defillama_liquidity_score": (
            _clamp01(defillama_liquidity)
            if defillama_liquidity is not None
            else None
        ),
        "defillama_tvl_momentum_score": (
            _clamp01(defillama_momentum)
            if defillama_momentum is not None
            else None
        ),
        "news_attention_score": (
            _clamp01(news_attention) if news_attention is not None else None
        ),
        "news_sentiment_score": (
            _clamp(news_sentiment, -1.0, 1.0)
            if news_sentiment is not None
            else None
        ),
        "fear_greed_score": _clamp01(fear_greed) if fear_greed is not None else None,
        "btc_mempool_pressure_score": (
            _clamp01(mempool_pressure) if mempool_pressure is not None else None
        ),
    }


def _extract_whale_walls(whale_walls_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(whale_walls_payload, Mapping):
        return {
            "whale_wall_score": None,
            "whale_bid_pressure_score": None,
            "whale_ask_pressure_score": None,
            "whale_wall_imbalance_score": None,
            "whale_wall_count_score": None,
            "whale_wall_event_count": None,
            "whale_bid_wall_notional_usd": None,
            "whale_ask_wall_notional_usd": None,
            "whale_total_wall_notional_usd": None,
            "nearest_bid_wall_distance_bps": None,
            "nearest_ask_wall_distance_bps": None,
        }
    imbalance = _coerce_float(whale_walls_payload.get("whale_wall_imbalance_score"))
    return {
        "whale_wall_score": (
            _clamp01(score)
            if (score := _coerce_float(whale_walls_payload.get("whale_wall_score"))) is not None
            else None
        ),
        "whale_bid_pressure_score": (
            _clamp01(score)
            if (score := _coerce_float(whale_walls_payload.get("whale_bid_pressure_score"))) is not None
            else None
        ),
        "whale_ask_pressure_score": (
            _clamp01(score)
            if (score := _coerce_float(whale_walls_payload.get("whale_ask_pressure_score"))) is not None
            else None
        ),
        "whale_wall_imbalance_score": (
            _clamp(imbalance, -1.0, 1.0) if imbalance is not None else None
        ),
        "whale_wall_count_score": (
            _clamp01(score)
            if (score := _coerce_float(whale_walls_payload.get("whale_wall_count_score"))) is not None
            else None
        ),
        "whale_wall_event_count": _coerce_float(
            whale_walls_payload.get("whale_wall_event_count")
        ),
        "whale_bid_wall_notional_usd": _coerce_float(
            whale_walls_payload.get("whale_bid_wall_notional_usd")
        ),
        "whale_ask_wall_notional_usd": _coerce_float(
            whale_walls_payload.get("whale_ask_wall_notional_usd")
        ),
        "whale_total_wall_notional_usd": _coerce_float(
            whale_walls_payload.get("whale_total_wall_notional_usd")
        ),
        "nearest_bid_wall_distance_bps": _coerce_float(
            whale_walls_payload.get("nearest_bid_wall_distance_bps")
        ),
        "nearest_ask_wall_distance_bps": _coerce_float(
            whale_walls_payload.get("nearest_ask_wall_distance_bps")
        ),
    }


def _combine_weighted(components: Sequence[tuple[float | None, float]]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for value, weight in components:
        if value is None:
            continue
        numerator += float(value) * float(weight)
        denominator += float(weight)
    if denominator <= 0.0:
        return None
    return _clamp01(numerator / denominator)


def build_symbol_score_payload(
    symbol: str,
    *,
    coingecko_payload: Mapping[str, Any] | None = None,
    surf_payload: Mapping[str, Any] | None = None,
    coinglass_payload: Mapping[str, Any] | None = None,
    public_intel_payload: Mapping[str, Any] | None = None,
    whale_walls_payload: Mapping[str, Any] | None = None,
    market_payloads: Mapping[str, Any] | None = None,
    feature_payloads: Mapping[str, Any] | None = None,
    generated_utc: str | None = None,
    max_provider_age_seconds: int = DEFAULT_MAX_PROVIDER_AGE_SECONDS,
) -> dict[str, Any]:
    """Build one symbol's paper/shadow alt-data score payload.

    Missing provider signals stay missing. The aggregate score is only
    produced when at least one real provider signal is available.

    Input boundary (Codex regression
    ``SCORING_INPUT_BOUNDARY_INCLUDES_V2_PAPER_AND_RISK_CONTEXT``):
    this function accepts ONLY V2 alt-data provider payloads
    (CoinGecko/Surf/CoinGlass/PublicIntel/WhaleWalls),
    ``market_payloads``, and ``feature_payloads``. It must NOT accept
    ``paper_*`` or ``risk_*``
    payloads; the caller must never pass them.
    Any paper/risk overlay belongs to a separately reviewed lane
    (``V2_SYMBOL_UNIVERSE_PAPER_RISK_CONTEXT_OVERLAY``).
    """
    now = generated_utc or utc_iso()
    symbol = symbol.upper()
    moralis_bridge = _extract_moralis_feature_bridge(feature_payloads)
    coinank_bridge = _extract_coinank_feature_bridge(feature_payloads)
    coingecko = _extract_coingecko(coingecko_payload)
    surf = _extract_surf(surf_payload)
    coinglass = _extract_coinglass(coinglass_payload)
    public_intel = _extract_public_intel(public_intel_payload)
    whale_walls = _extract_whale_walls(whale_walls_payload)

    coingecko_signal_present = any(value is not None for value in coingecko.values())
    surf_signal_present = surf["surf_market_price_signal_score"] is not None
    coinglass_signal_present = coinglass["coinglass_derivatives_score"] is not None
    public_intel_signal_present = any(
        value is not None for value in public_intel.values()
    )
    whale_walls_signal_present = whale_walls["whale_wall_score"] is not None

    provider_available: dict[str, bool] = {}
    if isinstance(coingecko_payload, Mapping):
        provider_available["coingecko"] = coingecko_signal_present and _is_provider_available(
            coingecko_payload,
            generated_utc=now,
            max_provider_age_seconds=max_provider_age_seconds,
        )
    if isinstance(surf_payload, Mapping):
        provider_available["surf"] = surf_signal_present and _is_provider_available(
            surf_payload,
            generated_utc=now,
            max_provider_age_seconds=max_provider_age_seconds,
        )
    if isinstance(coinglass_payload, Mapping):
        provider_available["coinglass"] = coinglass_signal_present and _is_provider_available(
            coinglass_payload,
            generated_utc=now,
            max_provider_age_seconds=max_provider_age_seconds,
        )
    if isinstance(public_intel_payload, Mapping):
        provider_available["public_intel"] = public_intel_signal_present and _is_provider_available(
            public_intel_payload,
            generated_utc=now,
            max_provider_age_seconds=max_provider_age_seconds,
        )
    if isinstance(whale_walls_payload, Mapping):
        provider_available["whale_walls"] = whale_walls_signal_present and _is_provider_available(
            whale_walls_payload,
            generated_utc=now,
            max_provider_age_seconds=max_provider_age_seconds,
        )
    providers_consulted = [
        provider for provider, available in provider_available.items() if available
    ]

    coingecko_age = (
        _payload_age_seconds(coingecko_payload, now)
        if isinstance(coingecko_payload, Mapping)
        else None
    )
    surf_age = (
        _payload_age_seconds(surf_payload, now)
        if isinstance(surf_payload, Mapping)
        else None
    )
    coinglass_age = (
        _payload_age_seconds(coinglass_payload, now)
        if isinstance(coinglass_payload, Mapping)
        else None
    )
    public_intel_age = (
        _payload_age_seconds(public_intel_payload, now)
        if isinstance(public_intel_payload, Mapping)
        else None
    )
    whale_walls_age = (
        _payload_age_seconds(whale_walls_payload, now)
        if isinstance(whale_walls_payload, Mapping)
        else None
    )
    provider_freshness_scores: dict[str, float] = {}
    if "coingecko" in provider_available:
        provider_freshness_scores["coingecko"] = (
            _provider_freshness_score(coingecko_age, max_provider_age_seconds)
            if provider_available["coingecko"]
            else 0.0
        )
    if "surf" in provider_available:
        provider_freshness_scores["surf"] = (
            _provider_freshness_score(surf_age, max_provider_age_seconds)
            if provider_available["surf"]
            else 0.0
        )
    if "coinglass" in provider_available:
        provider_freshness_scores["coinglass"] = (
            _provider_freshness_score(coinglass_age, max_provider_age_seconds)
            if provider_available["coinglass"]
            else 0.0
        )
    if "public_intel" in provider_available:
        provider_freshness_scores["public_intel"] = (
            _provider_freshness_score(public_intel_age, max_provider_age_seconds)
            if provider_available["public_intel"]
            else 0.0
        )
    if "whale_walls" in provider_available:
        provider_freshness_scores["whale_walls"] = (
            _provider_freshness_score(whale_walls_age, max_provider_age_seconds)
            if provider_available["whale_walls"]
            else 0.0
        )
    provider_availability_score = sum(provider_available.values()) / max(
        1, len(provider_available)
    )
    altdata_freshness_score = (
        sum(provider_freshness_scores[p] for p in providers_consulted)
        / len(providers_consulted)
        if providers_consulted
        else 0.0
    )

    missing_flags: list[str] = []
    stale_flags: list[str] = []
    coingecko_status = _source_status(coingecko_payload)
    surf_status = _source_status(surf_payload)
    coinglass_status = _source_status(coinglass_payload)
    public_intel_status = _source_status(public_intel_payload)
    whale_walls_status = _source_status(whale_walls_payload)
    if isinstance(coingecko_payload, Mapping) and coingecko_status not in OK_SOURCE_STATUSES:
        missing_flags.append(f"coingecko_source_status_{coingecko_status}")
    if isinstance(surf_payload, Mapping) and surf_status not in OK_SOURCE_STATUSES:
        missing_flags.append(f"surf_source_status_{surf_status}")
    if isinstance(coinglass_payload, Mapping) and coinglass_status not in OK_SOURCE_STATUSES:
        missing_flags.append(f"coinglass_source_status_{coinglass_status}")
    if isinstance(public_intel_payload, Mapping) and public_intel_status not in OK_SOURCE_STATUSES:
        missing_flags.append(f"public_intel_source_status_{public_intel_status}")
    if isinstance(whale_walls_payload, Mapping) and whale_walls_status not in OK_SOURCE_STATUSES:
        missing_flags.append(f"whale_walls_source_status_{whale_walls_status}")

    if isinstance(coingecko_payload, Mapping):
        for field, value in coingecko.items():
            if value is None:
                missing_flags.append(f"coingecko_{field}_missing")
    if isinstance(surf_payload, Mapping):
        for field, value in surf.items():
            if value is None:
                missing_flags.append(f"surf_{field}_missing")
    if isinstance(coinglass_payload, Mapping):
        for field, value in coinglass.items():
            if value is None:
                missing_flags.append(f"coinglass_{field}_missing")
    if isinstance(public_intel_payload, Mapping):
        for field, value in public_intel.items():
            if value is None:
                missing_flags.append(f"public_intel_{field}_missing")
    if isinstance(whale_walls_payload, Mapping):
        for field, value in whale_walls.items():
            if value is None:
                missing_flags.append(f"whale_walls_{field}_missing")

    if coingecko_age is not None and coingecko_age > max_provider_age_seconds:
        stale_flags.append("coingecko_payload_stale")
    if surf_age is not None and surf_age > max_provider_age_seconds:
        stale_flags.append("surf_payload_stale")
    if coinglass_age is not None and coinglass_age > max_provider_age_seconds:
        stale_flags.append("coinglass_payload_stale")
    if public_intel_age is not None and public_intel_age > max_provider_age_seconds:
        stale_flags.append("public_intel_payload_stale")
    if whale_walls_age is not None and whale_walls_age > max_provider_age_seconds:
        stale_flags.append("whale_walls_payload_stale")
    for provider_name, provider_payload in (
        ("coingecko", coingecko_payload),
        ("surf", surf_payload),
        ("coinglass", coinglass_payload),
        ("public_intel", public_intel_payload),
        ("whale_walls", whale_walls_payload),
    ):
        if isinstance(provider_payload, Mapping):
            for flag in provider_payload.get("stale_feature_flags") or []:
                stale_flags.append(f"{provider_name}_{flag}")

    coingecko_component = coingecko["coingecko_discovery_score"]
    coingecko_momentum_component = coingecko["coingecko_momentum_score"]
    surf_component = surf["surf_market_price_signal_score"]
    coinglass_component = coinglass["coinglass_derivatives_score"]
    public_intel_component = public_intel["public_intel_score"]
    whale_walls_component = whale_walls["whale_wall_score"]

    # Four retired alt-data providers removed (operator directive
    # 2026-07-16). _combine_weighted normalizes over the weights of the
    # PRESENT components, so dropping the dead inputs renormalizes the
    # surviving weights honestly (no zero-filling of removed providers).
    signal_component = _combine_weighted(
        (
            (
                coingecko_component if provider_available.get("coingecko") else None,
                0.23,
            ),
            (
                coingecko_momentum_component
                if provider_available.get("coingecko")
                else None,
                0.05,
            ),
            (surf_component if provider_available.get("surf") else None, 0.05),
            (
                coinglass_component if provider_available.get("coinglass") else None,
                0.03,
            ),
            (
                public_intel_component
                if provider_available.get("public_intel")
                else None,
                0.12,
            ),
            (
                whale_walls_component
                if provider_available.get("whale_walls")
                else None,
                0.07,
            ),
            (altdata_freshness_score if providers_consulted else None, 0.01),
            (provider_availability_score if providers_consulted else None, 0.01),
        )
    )

    return {
        "schema_version": "v2_alternative_data_symbol_score_v2",
        "generated_utc": now,
        "symbol": symbol,
        "altdata_symbol_score": _round_score(signal_component),
        "coingecko_discovery_score": _round_score(
            coingecko["coingecko_discovery_score"]
        ),
        "coingecko_liquidity_score": _round_score(
            coingecko["coingecko_liquidity_score"]
        ),
        "coingecko_momentum_score": _round_score(
            coingecko["coingecko_momentum_score"]
        ),
        "coingecko_trend_score": _round_score(coingecko["coingecko_trend_score"]),
        "surf_market_price_signal_score": _round_score(
            surf["surf_market_price_signal_score"]
        ),
        "surf_price_observation_count": _round_score(
            surf["surf_price_observation_count"]
        ),
        "coinglass_derivatives_score": _round_score(
            coinglass["coinglass_derivatives_score"]
        ),
        "public_intel_score": _round_score(public_intel["public_intel_score"]),
        "defillama_liquidity_score": _round_score(
            public_intel["defillama_liquidity_score"]
        ),
        "defillama_tvl_momentum_score": _round_score(
            public_intel["defillama_tvl_momentum_score"]
        ),
        "news_attention_score": _round_score(public_intel["news_attention_score"]),
        "news_sentiment_score": _round_score(public_intel["news_sentiment_score"]),
        "fear_greed_score": _round_score(public_intel["fear_greed_score"]),
        "btc_mempool_pressure_score": _round_score(
            public_intel["btc_mempool_pressure_score"]
        ),
        "whale_wall_score": _round_score(whale_walls["whale_wall_score"]),
        "whale_bid_pressure_score": _round_score(
            whale_walls["whale_bid_pressure_score"]
        ),
        "whale_ask_pressure_score": _round_score(
            whale_walls["whale_ask_pressure_score"]
        ),
        "whale_wall_imbalance_score": _round_score(
            whale_walls["whale_wall_imbalance_score"]
        ),
        "whale_wall_count_score": _round_score(
            whale_walls["whale_wall_count_score"]
        ),
        "whale_wall_event_count": _round_score(
            whale_walls["whale_wall_event_count"]
        ),
        "whale_bid_wall_notional_usd": _round_score(
            whale_walls["whale_bid_wall_notional_usd"]
        ),
        "whale_ask_wall_notional_usd": _round_score(
            whale_walls["whale_ask_wall_notional_usd"]
        ),
        "whale_total_wall_notional_usd": _round_score(
            whale_walls["whale_total_wall_notional_usd"]
        ),
        "nearest_bid_wall_distance_bps": _round_score(
            whale_walls["nearest_bid_wall_distance_bps"]
        ),
        "nearest_ask_wall_distance_bps": _round_score(
            whale_walls["nearest_ask_wall_distance_bps"]
        ),
        "altdata_freshness_score": _round_score(altdata_freshness_score),
        "provider_availability_score": _round_score(provider_availability_score),
        "provider_available": provider_available,
        "provider_source_status": {
            **({"coingecko": coingecko_status} if isinstance(coingecko_payload, Mapping) else {}),
            **({"surf": surf_status} if isinstance(surf_payload, Mapping) else {}),
            **({"coinglass": coinglass_status} if isinstance(coinglass_payload, Mapping) else {}),
            **({"public_intel": public_intel_status} if isinstance(public_intel_payload, Mapping) else {}),
            **({"whale_walls": whale_walls_status} if isinstance(whale_walls_payload, Mapping) else {}),
        },
        "provider_age_seconds": {
            **({"coingecko": coingecko_age} if isinstance(coingecko_payload, Mapping) else {}),
            **({"surf": surf_age} if isinstance(surf_payload, Mapping) else {}),
            **({"coinglass": coinglass_age} if isinstance(coinglass_payload, Mapping) else {}),
            **({"public_intel": public_intel_age} if isinstance(public_intel_payload, Mapping) else {}),
            **({"whale_walls": whale_walls_age} if isinstance(whale_walls_payload, Mapping) else {}),
        },
        "providers_consulted": providers_consulted,
        "missing_signal": bool(missing_flags),
        "stale_signal": bool(stale_flags),
        "missing_reasons": sorted(set(missing_flags)),
        "stale_reasons": sorted(set(stale_flags)),
        # Aliases matching the V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY
        # field-name contract (operator dashboards key off these
        # names). Same content as ``missing_reasons``/``stale_reasons``.
        "missing_provider_flags": sorted(set(missing_flags)),
        "stale_provider_flags": sorted(set(stale_flags)),
        # Rank is filled in by the universe-candidates pass after
        # sorting. The per-symbol score payload starts with rank=None
        # and is updated by ``build_symbol_universe_candidates`` so
        # callers that consume the symbol_score key alone still see
        # the rank.
        "altdata_symbol_rank": None,
        "input_presence": {
            "coingecko": isinstance(coingecko_payload, Mapping),
            "surf": isinstance(surf_payload, Mapping),
            "coinglass": isinstance(coinglass_payload, Mapping),
            "public_intel": isinstance(public_intel_payload, Mapping),
            "whale_walls": isinstance(whale_walls_payload, Mapping),
            "market": bool(market_payloads),
            "features": bool(feature_payloads),
            "moralis_feature_bridge": bool(moralis_bridge),
            "coinank_feature_bridge": bool(coinank_bridge),
        },
        "coinank_feature_bridge": coinank_bridge,
        "coinank_derivatives_score": coinank_bridge.get("coinank_derivatives_score"),
        "coinank_funding_rate": coinank_bridge.get("coinank_funding_rate"),
        "coinank_long_short_ratio": coinank_bridge.get("coinank_long_short_ratio"),
        "coinank_liquidation_imbalance_usd": coinank_bridge.get(
            "coinank_liquidation_imbalance_usd"
        ),
        "coinank_signal_present": coinank_bridge.get("coinank_derivatives_score")
        is not None,
        "moralis_feature_bridge": moralis_bridge,
        "moralis_feature_bridge_ready": moralis_bridge.get("feature_bridge_ready"),
        "moralis_feature_bridge_status": moralis_bridge.get("status"),
        "moralis_dashboard_color": moralis_bridge.get("dashboard_color"),
        "moralis_feature_count": moralis_bridge.get("feature_count"),
        "moralis_required_feature_count": moralis_bridge.get("required_feature_count"),
        "moralis_missing_feature_flags": moralis_bridge.get("missing_feature_flags", []),
        "moralis_stale_feature_flags": moralis_bridge.get("stale_feature_flags", []),
        "moralis_missing_mask_true": moralis_bridge.get("missing_mask_true"),
        "moralis_stale_mask_true": moralis_bridge.get("stale_mask_true"),
        "moralis_actual_payload_present": moralis_bridge.get("actual_payload_present"),
        "moralis_heartbeat_only": moralis_bridge.get("heartbeat_only"),
        "moralis_token_map_count": moralis_bridge.get("token_map_count"),
        "moralis_wallet_watchlist_count": moralis_bridge.get("wallet_watchlist_count"),
        "moralis_feature_available_at": moralis_bridge.get("available_at"),
        "moralis_feature_cutoff": moralis_bridge.get("feature_cutoff"),
        "moralis_decision_time_safe": moralis_bridge.get("decision_time_safe"),
        "moralis_raw_key_exposed": moralis_bridge.get("raw_key_exposed", False),
        "moralis_core_system_blocked": moralis_bridge.get("core_system_blocked", False),
        "network_call_attempted": False,
        "paper_shadow_only": True,
        "may_not_override_strict_paper_fill_gate": True,
        "may_not_authorize_live_or_canary": True,
        "may_not_place_orders": True,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": False,
        "exchange_mutation": False,
    }


def _extract_moralis_feature_bridge(feature_payloads: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(feature_payloads, Mapping):
        return {}
    payload = feature_payloads.get("moralis")
    if not isinstance(payload, Mapping):
        return {}
    return {
        "schema_version": payload.get("schema_version"),
        "provider": payload.get("provider"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "generated_at": payload.get("generated_at"),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "decision_time_safe": payload.get("decision_time_safe"),
        "status": payload.get("status"),
        "dashboard_color": payload.get("dashboard_color"),
        "feature_bridge_ready": payload.get("feature_bridge_ready"),
        "feature_count": payload.get("feature_count"),
        "required_feature_count": payload.get("required_feature_count"),
        "missing_feature_flags": list(payload.get("missing_feature_flags") or []),
        "stale_feature_flags": list(payload.get("stale_feature_flags") or []),
        "missing_mask_true": payload.get("missing_mask_true"),
        "stale_mask_true": payload.get("stale_mask_true"),
        "actual_payload_present": payload.get("actual_payload_present"),
        "heartbeat_only": payload.get("heartbeat_only"),
        "token_map_count": payload.get("token_map_count"),
        "wallet_watchlist_count": payload.get("wallet_watchlist_count"),
        "raw_key_exposed": bool(payload.get("raw_key_exposed", False)),
        "core_system_blocked": bool(payload.get("core_system_blocked", False)),
    }


def _extract_coinank_feature_bridge(feature_payloads: Mapping[str, Any] | None) -> dict[str, Any]:
    """CoinAnk derivatives/liquidation intel bridged from the legacy runtime.

    Reads ``feature_payloads['coinank']`` (``v2:features:coinank:*`` /
    ``v2:coinank:symbol:*`` produced by v2_coinank_intel_bridge). Exposes the
    CoinAnk-derived sub-scores in the symbol score output; it does not alter
    the weighted aggregate ``altdata_symbol_score``.
    """
    if not isinstance(feature_payloads, Mapping):
        return {}
    payload = feature_payloads.get("coinank")
    if not isinstance(payload, Mapping):
        return {}
    feats = payload.get("features") if isinstance(payload.get("features"), Mapping) else {}
    return {
        "provider": payload.get("provider") or "coinank",
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "generated_utc": payload.get("generated_utc"),
        "source_freshness_seconds": payload.get("source_freshness_seconds"),
        "actual_payload_present": bool(payload.get("actual_payload_present")),
        "coinank_derivatives_score": _round_score(
            _coerce_float(payload.get("coinank_derivatives_score"))
        ),
        "coinank_funding_rate": _coerce_float(feats.get("coinank_funding_rate")),
        "coinank_long_short_ratio": _coerce_float(feats.get("coinank_long_short_ratio")),
        "coinank_liquidation_imbalance_usd": _coerce_float(
            feats.get("coinank_liquidation_imbalance_usd")
        ),
    }


def build_symbol_universe_candidates(
    symbols: Sequence[str],
    *,
    symbol_scores: Mapping[str, Mapping[str, Any]] | None = None,
    existing_paper_symbols: Sequence[str] = (),
    generated_utc: str | None = None,
) -> dict[str, Any]:
    now = generated_utc or utc_iso()
    normalized_symbols = tuple(sorted({str(symbol).upper() for symbol in symbols}))
    scores = dict(symbol_scores or {})
    rows: list[dict[str, Any]] = []
    for symbol in normalized_symbols:
        payload = scores.get(symbol)
        score = (
            _coerce_float(payload.get("altdata_symbol_score"))
            if isinstance(payload, Mapping)
            else None
        )
        rows.append(
            {
                "symbol": symbol,
                "altdata_symbol_score": _round_score(score),
                "provider_availability_score": _round_score(
                    _coerce_float(payload.get("provider_availability_score"))
                    if isinstance(payload, Mapping)
                    else 0.0
                ),
                "altdata_freshness_score": _round_score(
                    _coerce_float(payload.get("altdata_freshness_score"))
                    if isinstance(payload, Mapping)
                    else 0.0
                ),
                "providers_consulted": list(
                    payload.get("providers_consulted") or []
                )
                if isinstance(payload, Mapping)
                else [],
                "missing_signal": bool(payload.get("missing_signal"))
                if isinstance(payload, Mapping)
                else True,
                "stale_signal": bool(payload.get("stale_signal"))
                if isinstance(payload, Mapping)
                else False,
            }
        )
    # Operator preference 2026-07-14: BTC/ETH/SOL are the preferred majors for
    # the full pipeline. Soft ranking WEIGHT only (score bonus, no exclusivity,
    # no gate changes) so selection stays market-driven per the symbol-universe
    # policy: a clearly stronger alt still outranks a weak major.
    preferred_majors = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    majors_rank_bonus = 0.05

    def _ranking_score(row: dict) -> float:
        score = row["altdata_symbol_score"] or 0.0
        if str(row.get("symbol") or "").upper() in preferred_majors:
            score += majors_rank_bonus
        return score

    rows.sort(
        key=lambda row: (
            row["altdata_symbol_score"] is None,
            -_ranking_score(row),
            -(row["provider_availability_score"] or 0.0),
            -(row["altdata_freshness_score"] or 0.0),
            row["symbol"],
        )
    )
    # Stamp the post-sort rank onto candidate rows AND back-fill the
    # per-symbol score payloads that were passed in. Rank is 1-based.
    altdata_symbol_rank_per_candidate: dict[str, int] = {}
    for rank, row in enumerate(rows, start=1):
        row["altdata_symbol_rank"] = rank
        altdata_symbol_rank_per_candidate[row["symbol"]] = rank
        score_payload = scores.get(row["symbol"])
        if isinstance(score_payload, dict):
            score_payload["altdata_symbol_rank"] = rank
    candidate_symbols = [row["symbol"] for row in rows]
    return {
        "schema_version": "v2_alternative_data_symbol_universe_candidates_v2",
        "generated_utc": now,
        "candidate_symbol_list": candidate_symbols,
        "candidate_count": len(candidate_symbols),
        "candidate_rows": rows,
        "ranking_source": "V2_ALT_DATA_COINGECKO_SURF_COINGLASS_PAPER_SHADOW",
        "altdata_symbol_score_per_candidate": {
            row["symbol"]: row["altdata_symbol_score"] for row in rows
        },
        "altdata_symbol_rank_per_candidate": altdata_symbol_rank_per_candidate,
        "providers_consulted_per_candidate": {
            row["symbol"]: row["providers_consulted"] for row in rows
        },
        "missing_signal_per_candidate": {
            row["symbol"]: row["missing_signal"] for row in rows
        },
        "stale_signal_per_candidate": {
            row["symbol"]: row["stale_signal"] for row in rows
        },
        "paper_symbols_continued": [
            str(symbol).upper() for symbol in existing_paper_symbols
        ],
        "paper_symbols_expanded": False,
        "paper_symbol_expansion_blocked_reason": (
            "ALT_DATA_SCORING_CANNOT_EXPAND_PAPER_SYMBOLS_WITHOUT_EXISTING_SYMBOL_UNIVERSE_SAFEGUARDS"
        ),
        "live_symbols": [],
        "live_symbols_continued": [],
        "paper_shadow_only": True,
        "network_call_attempted": False,
        "may_not_override_strict_paper_fill_gate": True,
        "may_not_authorize_live_or_canary": True,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": False,
        "exchange_mutation": False,
    }
