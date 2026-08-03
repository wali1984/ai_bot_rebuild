"""Edge hypothesis generator (strategy supply engine).

Evaluates rule-based strategy families per symbol/timeframe from live Redis
context and prices every hypothesis in USD after conservative costs. USD is
the primary metric; bps appear only as debug telemetry.

Every hypothesis carries `why_rejected` when it fails its own economics, and
positive hypotheses are published for the A+ inventory to evaluate through
the full preemptive/risk/allocator chain — this module never approves.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.altdata.canonical_confluence_consumer import (
    CanonicalConfluenceContractError,
    rebuild_canonical_confluence,
)
from v2.backend.app.services.altdata.provider_feature_bridge import (
    load_coinglass_input,
    load_moralis_input,
)
from v2.backend.app.services.market_data.current_price_resolver import resolve_current_price

HYPOTHESIS_KEY = "v2:strategy_supply:hypotheses:{symbol}:{timeframe}"
POSITIVE_HYPOTHESIS_KEY = "v2:strategy_supply:positive_hypotheses:{symbol}:{timeframe}"
GATE_CLEAN_POSITIVE_HYPOTHESIS_KEY = (
    "v2:strategy_supply:gate_clean_positive_hypotheses:{symbol}:{timeframe}"
)
HYPOTHESIS_TTL_SECONDS = 900
STATUS_KEY = "v2:strategy_supply:status"
LATEST_POSITIVE_SUMMARY_KEY = "v2:strategy_supply:latest_positive_summary"
LATEST_ERROR_SUMMARY_KEY = "v2:strategy_supply:latest_error_summary"

REFERENCE_NOTIONAL_USD = 200.0
ROUND_TRIP_COST_BPS = 9.4  # spread + taker fees both ways + slippage reserve
LATENCY_RESERVE_BPS = 0.6
MIN_REWARD_TO_RISK = 1.0
ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE = 70.0
MIN_TRADE_TAPE_CONFIRMATION_SCORE = 0.55
MIN_COINANK_CONTEXT_REQUIRED = True
FRESH_NO_EVENT_LIQUIDATION_MAX_AGE_MS = 10 * 60 * 1000
FRESH_RECOMPUTED_LIQUIDATION_MAX_AGE_MS = 10 * 60 * 1000
MAX_AGED_LIQUIDATION_LEVEL_AGE_MS = 24 * 60 * 60 * 1000

STRATEGY_FAMILIES = (
    "trend_continuation",
    "pullback_continuation",
    "fvg_retest",
    "liquidity_sweep_reversal",
    "range_mean_reversion",
    "breakout_after_compression",
    "funding_squeeze",
    "long_short_imbalance_squeeze",
    "liquidation_cluster_magnet",
    "orderbook_absorption",
    "microstructure_momentum",
    "smart_money_accumulation",
    "smart_money_distribution",
    "exchange_inflow_risk",
    "social_euphoria_fade",
    "volatility_expansion",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _utc_epoch(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int | float):
        parsed = float(value)
        if parsed != parsed or abs(parsed) == float("inf"):
            return None
        return parsed / 1000.0 if abs(parsed) >= 10_000_000_000 else parsed
    if not isinstance(value, str):
        return None
    try:
        parsed_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_dt.tzinfo is None or parsed_dt.utcoffset() != timezone.utc.utcoffset(parsed_dt):
        return None
    return parsed_dt.timestamp()


def _utc_iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _closed_ta_point_in_time_evidence(
    payload: Any,
    *,
    symbol: str,
    timeframe: str,
    decision_time: str,
) -> dict[str, Any]:
    """Validate the mandatory closed-candle TA source without restamping it."""

    base = {
        "valid": False,
        "reason": "TA_CLOSED_POINT_IN_TIME_EVIDENCE_INVALID",
        "source_key": f"v2:features:ta_closed:{symbol}:{timeframe}",
        "feature_cutoff": None,
        "source_generated_at": None,
        "source_available_at": None,
        "latest_closed_kline_close_time_ms": None,
    }
    if not isinstance(payload, Mapping):
        return {**base, "reason": "TA_CLOSED_SOURCE_MISSING"}
    if payload.get("schema_version") != "v2_full_talib_ta_closed_candidate_v1":
        return {**base, "reason": "TA_CLOSED_SCHEMA_INVALID"}
    if str(payload.get("symbol") or "").upper() != symbol:
        return {**base, "reason": "TA_CLOSED_SYMBOL_MISMATCH"}
    if str(payload.get("timeframe") or "") != timeframe:
        return {**base, "reason": "TA_CLOSED_TIMEFRAME_MISMATCH"}
    if payload.get("candle_closed_confirmed") is not True:
        return {**base, "reason": "TA_CLOSED_FINALITY_UNPROVEN"}
    if not isinstance(payload.get("indicators"), Mapping) or not payload.get(
        "indicators"
    ):
        return {**base, "reason": "TA_CLOSED_INDICATORS_MISSING"}

    cutoff = payload.get("feature_cutoff")
    source_generated = payload.get("generated_at")
    source_available = payload.get("available_at")
    cutoff_epoch = _utc_epoch(cutoff)
    generated_epoch = _utc_epoch(source_generated)
    available_epoch = _utc_epoch(source_available)
    decision_epoch = _utc_epoch(decision_time)
    if None in {cutoff_epoch, generated_epoch, available_epoch, decision_epoch}:
        return {**base, "reason": "TA_CLOSED_CLOCK_MISSING_OR_INVALID"}
    if not (
        cutoff_epoch <= generated_epoch
        and generated_epoch <= available_epoch
        and available_epoch <= decision_epoch
    ):
        return {**base, "reason": "TA_CLOSED_CLOCK_ORDER_INVALID"}

    close_time_ms = payload.get("last_closed_candle_close_ts_ms")
    close_epoch = _utc_epoch(close_time_ms)
    if close_epoch is None:
        return {**base, "reason": "TA_CLOSED_FINALITY_CLOCK_MISSING_OR_INVALID"}
    if close_epoch > cutoff_epoch:
        return {**base, "reason": "TA_CLOSED_CLOSE_AFTER_FEATURE_CUTOFF"}
    return {
        **base,
        "valid": True,
        "reason": None,
        "feature_cutoff": (
            cutoff if isinstance(cutoff, str) else _utc_iso_from_epoch(cutoff_epoch)
        ),
        "source_generated_at": (
            source_generated
            if isinstance(source_generated, str)
            else _utc_iso_from_epoch(generated_epoch)
        ),
        "source_available_at": (
            source_available
            if isinstance(source_available, str)
            else _utc_iso_from_epoch(available_epoch)
        ),
        "latest_closed_kline_close_time_ms": int(round(close_epoch * 1000.0)),
    }


def _read_json(client: Any, key: str) -> Any:
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _read_first_json(client: Any, keys: list[str]) -> tuple[Any, str | None]:
    for key in keys:
        payload = _read_json(client, key)
        if isinstance(payload, Mapping):
            return payload, key
    return None, None


def _dig(payload: Any, *names: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    for name in names:
        if payload.get(name) is not None:
            return payload.get(name)
    features = payload.get("features")
    if isinstance(features, Mapping):
        for name in names:
            if features.get(name) is not None:
                return features.get(name)
    return None


def _context(client: Any, symbol: str, timeframe: str) -> dict[str, Any]:
    trust_timeframes = [timeframe, "1m", "5m", "15m"]
    trust_payload = None
    trust_source = None
    for tf in dict.fromkeys(tf for tf in trust_timeframes if tf in {"1m", "5m", "15m", "1h", "4h"}):
        key = f"v2:microstructure:trust_score:{symbol}:{tf}"
        trust_payload = _read_json(client, key)
        if isinstance(trust_payload, Mapping):
            trust_source = key
            break
    liquidation_context, liquidation_context_source = _read_first_json(
        client,
        [
            f"v2:liquidations:levels:{symbol}:{timeframe}",
            f"v2:market:liquidations:aggregate:{symbol}",
            f"v2:coinank:liquidations:{symbol}",
            f"v2:market:coinank:liquidation_levels:{symbol}:{timeframe}",
            f"v2:market:coinank:liquidation_levels:{symbol}",
            f"v2:market:liquidation_levels:{symbol}",
        ],
    )
    # Only a confirmed-closed-candle TA payload may create a strategy
    # hypothesis. A live/in-progress TA candle is diagnostic input, never a
    # fallback feature source for positive or gate-clean paper supply.
    ta_closed = _read_json(client, f"v2:features:ta_closed:{symbol}:{timeframe}")
    # Moralis is a receipt-gated optional input.  Reading the raw Redis
    # envelope here previously bypassed the canonical consumer boundary and
    # allowed a legacy or forged ``features`` map to create paper hypotheses.
    # The loader currently returns absent until an authenticated post-commit
    # receipt verifier is implemented; when that boundary is released, this
    # consumer will automatically receive only validated, fresh features.
    moralis_input = load_moralis_input(client, symbol, "1m")
    moralis_features = (
        dict(moralis_input.features)
        if moralis_input.present and not moralis_input.stale
        else None
    )
    # CoinGlass uses the same fail-closed provider boundary.  The deployed v1
    # aggregate lacks the exact schema and temporal contract required by this
    # loader, so it remains optional/missing instead of creating hypotheses
    # directly from unverified Redis bytes.  A fresh v2 payload carries its
    # validated clocks into the feature hash for future causal audit.
    coinglass_input = load_coinglass_input(client, symbol, "1m")
    coinglass_context = (
        {
            "schema_version": "validated_provider_input_v1",
            "provider": "coinglass",
            "symbol": symbol,
            "timeframe": "1m",
            "feature_cutoff": coinglass_input.feature_cutoff,
            "available_at": coinglass_input.available_at,
            "generated_at": coinglass_input.generated_at,
            "features": dict(coinglass_input.features),
        }
        if coinglass_input.present and not coinglass_input.stale
        else None
    )
    # Never trust the cached composite envelope as an input to a paper-facing
    # hypothesis.  Reconstruct it from the canonical provider loaders in this
    # process so a writer that can mutate ``v2:altdata:confluence:*`` cannot
    # manufacture a social/provider signal.  Optional provider absence is not
    # a generator failure: the composite remains explicitly masked.
    try:
        rebuilt_confluence = rebuild_canonical_confluence(
            client,
            symbol=symbol,
            timeframe="1m",
        )
    except CanonicalConfluenceContractError:
        rebuilt_confluence = None
    confluence_context = (
        rebuilt_confluence
        if isinstance(rebuilt_confluence, Mapping)
        and rebuilt_confluence.get("actual_payload_present") is True
        and rebuilt_confluence.get("decision_time_safe") is True
        and rebuilt_confluence.get("reconstructed_from_canonical_provider_inputs")
        is True
        and rebuilt_confluence.get("cached_confluence_consumed") is False
        else None
    )
    return {
        "price": resolve_current_price(client, symbol),
        # Preserve the raw closed-lane candidate for exact fail-closed
        # attribution; generate_hypotheses validates it before consuming any
        # indicator. The live TA key is never read.
        "ta": ta_closed if isinstance(ta_closed, Mapping) else None,
        "ta_closed": ta_closed if isinstance(ta_closed, Mapping) else None,
        "ta_source_key": f"v2:features:ta_closed:{symbol}:{timeframe}",
        # The generic latest-feature lane may contain a partially formed
        # higher-timeframe candle. Closed TA is the only candle/ATR source.
        "latest": None,
        "fvg": _read_json(client, f"v2:market:fvg:{symbol}:{timeframe}"),
        "liquidity_zones": _read_json(client, f"v2:market:liquidity_zones:{symbol}"),
        "liquidation_levels": liquidation_context,
        "liquidation_levels_source": liquidation_context_source,
        "sweep_risk": _read_json(client, f"v2:market:sweep_risk:{symbol}:{timeframe}"),
        "coinglass": coinglass_context,
        "confluence": confluence_context,
        "moralis": moralis_features,
        "microstructure": _read_json(client, f"v2:market:microstructure:{symbol}"),
        "microstructure_trust": trust_payload,
        "microstructure_trust_source": trust_source,
        "orderbook": _read_json(client, f"v2:orderbook:features:binance:{symbol}"),
        "orderbook_top": _read_json(client, f"v2:orderbook:top:binance:{symbol}"),
        "orderbook_rest": _read_json(client, f"v2:market:orderbook:binance:{symbol}"),
        "trade_tape": _read_json(client, f"v2:market:trade_tape_features:{symbol}"),
        "trade_tape_confirmation": _read_json(client, f"v2:microstructure:trade_tape_confirmation:{symbol}"),
    }


def _hypothesis_id(symbol: str, timeframe: str, family: str, side: str) -> str:
    digest = hashlib.sha256(f"{symbol}|{timeframe}|{family}|{side}|{_utc_now()[:16]}".encode()).hexdigest()[:16]
    return f"hyp_{digest}"


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _provider_feature_hashes(ctx: Mapping[str, Any]) -> dict[str, str]:
    sources = {
        "ta": ctx.get("ta"),
        "latest": ctx.get("latest"),
        "fvg": ctx.get("fvg"),
        "liquidity_zones": ctx.get("liquidity_zones"),
        "liquidation_levels": ctx.get("liquidation_levels"),
        "sweep_risk": ctx.get("sweep_risk"),
        "coinglass": ctx.get("coinglass"),
        "altdata_confluence": ctx.get("confluence"),
        "moralis": ctx.get("moralis"),
        "microstructure": ctx.get("microstructure"),
        "microstructure_trust": ctx.get("microstructure_trust"),
        "orderbook": ctx.get("orderbook"),
        "orderbook_top": ctx.get("orderbook_top"),
        "orderbook_rest": ctx.get("orderbook_rest"),
        "trade_tape": ctx.get("trade_tape"),
        "trade_tape_confirmation": ctx.get("trade_tape_confirmation"),
    }
    return {
        name: _hash_payload(payload)
        for name, payload in sources.items()
        if payload not in (None, "", [], {})
    }


def _provider_features_used(ctx: Mapping[str, Any], *, signal_context: Any = None) -> list[str]:
    labels: list[str] = []
    if signal_context not in (None, ""):
        labels.append(str(signal_context))
    for label, key in (
        ("ta", "ta"),
        ("latest_features", "latest"),
        ("fvg", "fvg"),
        ("liquidity_zones", "liquidity_zones"),
        ("coinank_liquidations", "liquidation_levels"),
        ("sweep_risk", "sweep_risk"),
        ("coinglass", "coinglass"),
        ("altdata_confluence", "confluence"),
        ("moralis", "moralis"),
        ("microstructure", "microstructure"),
        ("microstructure_trust", "microstructure_trust"),
        ("orderbook", "orderbook"),
        ("orderbook_top", "orderbook_top"),
        ("trade_tape", "trade_tape"),
        ("trade_tape_confirmation", "trade_tape_confirmation"),
    ):
        if ctx.get(key) not in (None, "", [], {}):
            labels.append(label)
    return list(dict.fromkeys(labels))


def _feature_vector_hash(
    *,
    symbol: str,
    timeframe: str,
    strategy_family: str | None,
    side: str | None,
    provider_feature_hashes: Mapping[str, str],
    generated: str,
) -> str:
    digest = _hash_payload(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_family": strategy_family,
            "side": side,
            "provider_feature_hashes": provider_feature_hashes,
            "generated_minute": generated[:16],
        }
    )[:32]
    return f"strategy_supply_{digest}"


def _contract_base(
    *,
    ctx: Mapping[str, Any],
    symbol: str,
    timeframe: str,
    strategy_family: str | None,
    strategy_subtype: str | None,
    side: str | None,
    generated: str,
    current_price: float | None,
    price_payload: Mapping[str, Any] | None,
    reason_if_rejected: str | None,
    signal_context: Any = None,
) -> dict[str, Any]:
    provider_hashes = _provider_feature_hashes(ctx)
    hypothesis_id = _hypothesis_id(symbol, timeframe, strategy_family or "no_data", side or "none")
    feature_hash = _feature_vector_hash(
        symbol=symbol,
        timeframe=timeframe,
        strategy_family=strategy_family,
        side=side,
        provider_feature_hashes=provider_hashes,
        generated=generated,
    )
    ta_ctx = ctx.get("ta") if isinstance(ctx.get("ta"), Mapping) else {}
    candle_closed_confirmed = ta_ctx.get("candle_closed_confirmed") is True
    ta_evidence = _closed_ta_point_in_time_evidence(
        ta_ctx,
        symbol=symbol,
        timeframe=timeframe,
        decision_time=generated,
    )
    decision_epoch = _utc_epoch(generated)
    return {
        "schema_version": "edge_hypothesis_v1",
        "hypothesis_id": hypothesis_id,
        "strategy_id": hypothesis_id,
        "strategy_family": strategy_family,
        "strategy_subtype": strategy_subtype,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "generated_utc": generated,
        "generated_at": generated,
        "producer_generated_at": generated,
        "record_available_at": generated,
        "feature_cutoff": ta_evidence["feature_cutoff"],
        "decision_time": generated,
        "available_at": generated,
        "source_generated_at": ta_evidence["source_generated_at"],
        "source_available_at": ta_evidence["source_available_at"],
        "feature_point_in_time_evidence_valid": ta_evidence["valid"],
        "feature_point_in_time_rejection_reason": ta_evidence["reason"],
        "latest_unclosed_kline_excluded": ta_evidence["valid"],
        "latest_unclosed_exclusion_method": (
            "CONFIRMED_CLOSED_TA_SOURCE_KEY" if ta_evidence["valid"] else None
        ),
        "latest_unclosed_exclusion_decision_time_ms": (
            int(round(decision_epoch * 1000.0))
            if decision_epoch is not None
            else None
        ),
        "entry_feature_candle_closed_confirmed": candle_closed_confirmed,
        "candle_closed_confirmed": candle_closed_confirmed,
        "last_closed_candle_open_ts_ms": ta_ctx.get("last_closed_candle_open_ts_ms"),
        "last_closed_candle_close_ts_ms": ta_evidence[
            "latest_closed_kline_close_time_ms"
        ],
        "latest_closed_kline_close_time_ms": ta_evidence[
            "latest_closed_kline_close_time_ms"
        ],
        "ta_source_key": ctx.get("ta_source_key"),
        "current_price": current_price,
        "price_source": (price_payload or {}).get("source"),
        "price_available_at": (price_payload or {}).get("available_at"),
        "feature_vector_hash": feature_hash,
        "provider_features_used": _provider_features_used(ctx, signal_context=signal_context),
        "provider_feature_hashes": provider_hashes,
        "reason_if_rejected": reason_if_rejected,
        "why_rejected": reason_if_rejected,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "counts_as_final_a_plus": False,
        "routes_to_live": False,
        "places_real_order": False,
        "paper_only": True,
    }


def _risk_profile_reference_notional_usd(client: Any) -> tuple[float, str]:
    payload = _read_json(client, "v2:live_gate:state")
    fields = {}
    if isinstance(payload, Mapping):
        profile = payload.get("risk_profile")
        if isinstance(profile, Mapping) and isinstance(profile.get("fields"), Mapping):
            fields = dict(profile.get("fields") or {})
    caps = [
        _float(fields.get("max_notional_per_trade")),
        _float(fields.get("max_symbol_exposure")),
    ]
    positive_caps = [value for value in caps if value is not None and value > 0.0]
    if not positive_caps:
        return REFERENCE_NOTIONAL_USD, "static_reference_notional_no_live_risk_cap"
    return min(REFERENCE_NOTIONAL_USD, min(positive_caps)), "live_gate_risk_profile_notional_cap"


def _economics(
    *,
    price: float,
    side: str,
    target_move_bps: float,
    stop_move_bps: float,
    loss_probability: float,
    reference_notional_usd: float,
) -> dict[str, Any]:
    """Conservative USD economics at reference notional."""
    notional = reference_notional_usd
    cost_bps = ROUND_TRIP_COST_BPS + LATENCY_RESERVE_BPS
    normalized_side = str(side or "").strip().lower()
    selected_net_edge_bps = target_move_bps - cost_bps
    signed_expected_move_bps = (
        -target_move_bps if normalized_side == "short" else target_move_bps
    )
    signed_expected_move_after_cost_bps = (
        -selected_net_edge_bps if normalized_side == "short" else selected_net_edge_bps
    )
    gross_usd = notional * target_move_bps / 10_000.0
    cost_usd = notional * cost_bps / 10_000.0
    max_loss_usd = notional * (stop_move_bps + cost_bps) / 10_000.0
    win_probability = max(0.0, 1.0 - loss_probability)
    expected_net_usd = win_probability * (gross_usd - cost_usd) - loss_probability * max_loss_usd
    reward_to_risk = (gross_usd - cost_usd) / max_loss_usd if max_loss_usd > 0 else 0.0
    return {
        "reference_notional_usd": notional,
        "expected_gross_pnl_usd": round(gross_usd, 6),
        "expected_cost_usd": round(cost_usd, 6),
        "fees_usd": round(notional * 4.0 / 10_000.0, 6),
        "slippage_usd": round(notional * 5.4 / 10_000.0, 6),
        "funding_usd": 0.0,
        "latency_reserve_usd": round(notional * LATENCY_RESERVE_BPS / 10_000.0, 6),
        "expected_net_pnl_usd": round(expected_net_usd, 6),
        "expected_max_loss_usd": round(max_loss_usd, 6),
        "expected_move_bps": round(signed_expected_move_bps, 6),
        "expected_move_after_cost_bps": round(signed_expected_move_after_cost_bps, 6),
        "selected_side_expected_net_edge_bps": round(selected_net_edge_bps, 6),
        "expected_long_net_edge_bps": (
            round(selected_net_edge_bps, 6) if normalized_side == "long" else None
        ),
        "expected_short_net_edge_bps": (
            round(selected_net_edge_bps, 6) if normalized_side == "short" else None
        ),
        "long_expected_net_pnl_usd": (
            round(expected_net_usd, 6) if normalized_side == "long" else None
        ),
        "short_expected_net_pnl_usd": (
            round(expected_net_usd, 6) if normalized_side == "short" else None
        ),
        "reward_to_risk_usd": round(reward_to_risk, 4),
        "loss_probability": round(loss_probability, 4),
        "debug_target_move_bps": target_move_bps,
        "debug_stop_move_bps": stop_move_bps,
        "debug_cost_bps": cost_bps,
        "debug_fee_bps": 4.0,
        "debug_slippage_bps": 5.4,
        "debug_funding_bps": 0.0,
        "debug_latency_reserve_bps": LATENCY_RESERVE_BPS,
    }


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _evidence_adjusted_loss_probability(
    *,
    signal: Mapping[str, Any],
    target_move_bps: float,
    stop_move_bps: float,
    trust_score: float | None,
    tape_score: float | None,
    exit_depth_usd: float | None,
    coinank_context_present: bool,
    reference_notional_usd: float,
) -> tuple[float, dict[str, Any]]:
    strength = _float(signal.get("strength")) or 0.0
    base_loss = max(0.35, 0.65 - 0.25 * _clamp(strength, 0.0, 1.0))
    total_cost_bps = ROUND_TRIP_COST_BPS + LATENCY_RESERVE_BPS
    reward_to_risk_proxy = (
        max(0.0, target_move_bps - total_cost_bps) / max(stop_move_bps + total_cost_bps, 1e-9)
    )
    reductions: dict[str, float] = {}
    penalties: dict[str, float] = {}

    if trust_score is None:
        penalties["microstructure_trust_missing"] = 0.10
    elif trust_score >= 0.70:
        reductions["allocator_grade_microstructure_trust"] = min(
            0.08,
            0.025 + (trust_score - 0.70) * 0.18,
        )
    else:
        penalties["microstructure_trust_below_allocator_minimum"] = min(
            0.18,
            0.04 + (0.70 - trust_score) * 0.25,
        )

    if tape_score is None:
        penalties["trade_tape_missing"] = 0.06
    elif tape_score >= 0.60:
        reductions["trade_tape_confirmation"] = min(
            0.05,
            0.01 + (tape_score - 0.60) * 0.12,
        )
    else:
        penalties["trade_tape_weak"] = min(0.08, 0.02 + (0.60 - tape_score) * 0.10)

    if reward_to_risk_proxy >= 1.15:
        reductions["reward_to_risk_margin"] = min(
            0.05,
            0.01 + (reward_to_risk_proxy - 1.15) * 0.08,
        )
    elif reward_to_risk_proxy < 1.0:
        penalties["reward_to_risk_below_one"] = 0.12

    if exit_depth_usd is not None and exit_depth_usd >= reference_notional_usd * 10.0:
        reductions["exit_depth_capacity"] = 0.01
    elif exit_depth_usd is not None and exit_depth_usd < reference_notional_usd * 2.0:
        penalties["exit_depth_insufficient"] = 0.08

    if coinank_context_present:
        reductions["coinank_liquidation_context"] = 0.01
    else:
        penalties["coinank_liquidation_context_missing"] = 0.04

    if strength >= 0.80:
        reductions["strong_strategy_signal"] = 0.02

    evidence_floor = 0.45
    if (
        trust_score is not None
        and trust_score >= 0.75
        and tape_score is not None
        and tape_score >= 0.65
        and reward_to_risk_proxy >= 1.20
        and coinank_context_present
    ):
        evidence_floor = 0.28
    elif (
        trust_score is not None
        and trust_score >= 0.70
        and tape_score is not None
        and tape_score >= 0.60
    ):
        evidence_floor = 0.40

    adjusted = base_loss - sum(reductions.values()) + sum(penalties.values())
    loss_probability = round(_clamp(adjusted, evidence_floor, 0.90), 4)
    return loss_probability, {
        "base_loss_probability": round(base_loss, 6),
        "adjusted_loss_probability": loss_probability,
        "evidence_floor": evidence_floor,
        "signal_strength": round(strength, 6),
        "reward_to_risk_proxy": round(reward_to_risk_proxy, 6),
        "reductions": {key: round(value, 6) for key, value in reductions.items()},
        "penalties": {key: round(value, 6) for key, value in penalties.items()},
        "allocator_grade_microstructure_required": ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE,
        "trade_tape_confirmation_required": MIN_TRADE_TAPE_CONFIRMATION_SCORE,
        "coinank_context_required": MIN_COINANK_CONTEXT_REQUIRED,
    }


def _ta_indicators(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    ta = ctx.get("ta")
    if isinstance(ta, Mapping) and isinstance(ta.get("indicators"), Mapping):
        return ta["indicators"]
    return ta if isinstance(ta, Mapping) else {}


def _atr_bps(ctx: Mapping[str, Any], price: float | None) -> float | None:
    indicators = _ta_indicators(ctx)
    # NATR is percent of price -> bps = pct * 100
    natr = _float(indicators.get("ta_NATR"))
    if natr is not None and natr > 0:
        return natr * 100.0
    atr_abs = (
        _float(indicators.get("ta_ATR_14"))
        or _float(indicators.get("ta_ATR"))
        or _float(indicators.get("atr_14"))
    )
    if atr_abs is not None and atr_abs > 0 and price and price > 0:
        return atr_abs / price * 10_000.0
    return None


def _family_signals(ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive (family, side, strength, target/stop in ATR multiples)."""
    signals: list[dict[str, Any]] = []
    cg = ctx.get("coinglass")
    conf = ctx.get("confluence")
    mo = ctx.get("moralis")
    ta = ctx.get("ta")

    funding_z = _float(_dig(cg, "coinglass_funding_rate_zscore"))
    if funding_z is not None and abs(funding_z) >= 1.5:
        signals.append({
            "family": "funding_squeeze",
            "side": "short" if funding_z > 0 else "long",
            "strength": min(abs(funding_z) / 3.0, 1.0),
            "target_atr": 1.6, "stop_atr": 1.0,
            "context_field": f"funding_z={funding_z:.2f}",
        })

    ls_extreme = _float(_dig(cg, "coinglass_long_short_extreme_score"))
    long_ratio = _float(_dig(cg, "coinglass_long_ratio"))
    if ls_extreme is not None and ls_extreme >= 0.6 and long_ratio is not None:
        signals.append({
            "family": "long_short_imbalance_squeeze",
            "side": "short" if long_ratio > 0.5 else "long",
            "strength": ls_extreme,
            "target_atr": 1.4, "stop_atr": 1.0,
            "context_field": f"ls_extreme={ls_extreme:.2f}",
        })

    cascade = _float(_dig(cg, "coinglass_liquidation_cascade_score"))
    liq_imbalance = _float(_dig(cg, "coinglass_liquidation_imbalance_usd"))
    if cascade is not None and cascade >= 0.5 and liq_imbalance is not None:
        signals.append({
            "family": "liquidation_cluster_magnet",
            "side": "long" if liq_imbalance < 0 else "short",
            "strength": cascade,
            "target_atr": 1.8, "stop_atr": 1.1,
            "context_field": f"cascade={cascade:.2f}",
        })

    acc = _float(_dig(mo, "moralis_smart_wallet_accumulation_score"))
    if acc is not None and acc >= 0.6:
        signals.append({
            "family": "smart_money_accumulation", "side": "long",
            "strength": acc, "target_atr": 2.0, "stop_atr": 1.2,
            "context_field": f"accumulation={acc:.2f}",
        })
    dist = _float(_dig(mo, "moralis_smart_wallet_distribution_score"))
    if dist is not None and dist >= 0.6:
        signals.append({
            "family": "smart_money_distribution", "side": "short",
            "strength": dist, "target_atr": 2.0, "stop_atr": 1.2,
            "context_field": f"distribution={dist:.2f}",
        })
    inflow = _float(_dig(mo, "moralis_net_exchange_flow_usd"))
    if inflow is not None and inflow > 0:
        signals.append({
            "family": "exchange_inflow_risk", "side": "short",
            "strength": min(abs(inflow) / 1e7, 1.0),
            "target_atr": 1.3, "stop_atr": 1.0,
            "context_field": f"net_inflow_usd={inflow:.0f}",
        })

    euphoria = _float(_dig(conf, "altdata_social_euphoria_risk_score"))
    if euphoria is not None and euphoria >= 0.6:
        signals.append({
            "family": "social_euphoria_fade", "side": "short",
            "strength": euphoria, "target_atr": 1.5, "stop_atr": 1.0,
            "context_field": f"euphoria={euphoria:.2f}",
        })

    indicators = _ta_indicators(ctx)
    adx = _float(indicators.get("ta_ADX") or indicators.get("adx") or _dig(ta, "adx", "adx_14"))
    ema_fast = _float(indicators.get("ema_20"))
    ema_slow = _float(indicators.get("ema_50"))
    ema_trend = _float(_dig(ta, "ema_trend", "ema_slope", "trend_score"))
    if ema_trend is None and ema_fast is not None and ema_slow is not None and ema_slow > 0:
        ema_trend = (ema_fast - ema_slow) / ema_slow
    if adx is not None and adx >= 22 and ema_trend is not None and ema_trend != 0:
        signals.append({
            "family": "trend_continuation",
            "side": "long" if ema_trend > 0 else "short",
            "strength": min(adx / 40.0, 1.0),
            "target_atr": 1.8, "stop_atr": 1.1,
            "context_field": f"adx={adx:.1f},trend={ema_trend:.3f}",
        })

    rsi = _float(indicators.get("rsi_14") or indicators.get("ta_RSI") or _dig(ta, "rsi", "rsi_14"))
    bb_width_pct = _float(indicators.get("bb_width_pct"))
    bb_width = _float(_dig(ta, "bb_width", "bollinger_width_bps"))
    if bb_width is None and bb_width_pct is not None:
        bb_width = bb_width_pct * 10_000.0  # pct-of-price fraction -> bps
    if rsi is not None and (rsi <= 28 or rsi >= 72):
        signals.append({
            "family": "range_mean_reversion",
            "side": "long" if rsi <= 28 else "short",
            "strength": min(abs(rsi - 50.0) / 35.0, 1.0),
            "target_atr": 1.2, "stop_atr": 0.9,
            "context_field": f"rsi={rsi:.1f}",
        })
    if bb_width is not None and bb_width > 0 and bb_width < 25.0:
        signals.append({
            "family": "breakout_after_compression",
            "side": "long" if (ema_trend or 0) >= 0 else "short",
            "strength": min(25.0 / max(bb_width, 1.0) / 5.0, 1.0),
            "target_atr": 2.2, "stop_atr": 1.2,
            "context_field": f"bb_width={bb_width:.1f}",
        })

    fvg = ctx.get("fvg")
    bullish_fvg = _dig(fvg, "bullish_fvg_present", "has_bullish_fvg")
    bearish_fvg = _dig(fvg, "bearish_fvg_present", "has_bearish_fvg")
    if bullish_fvg is True:
        signals.append({
            "family": "fvg_retest", "side": "long", "strength": 0.6,
            "target_atr": 1.7, "stop_atr": 1.0, "context_field": "bullish_fvg",
        })
    if bearish_fvg is True:
        signals.append({
            "family": "fvg_retest", "side": "short", "strength": 0.6,
            "target_atr": 1.7, "stop_atr": 1.0, "context_field": "bearish_fvg",
        })

    sweep = ctx.get("sweep_risk")
    sweep_long = _float(_dig(sweep, "sweep_risk_long_side"))
    sweep_short = _float(_dig(sweep, "sweep_risk_short_side"))
    if sweep_long is not None and sweep_long >= 0.6:
        signals.append({
            "family": "liquidity_sweep_reversal", "side": "long",
            "strength": sweep_long, "target_atr": 1.6, "stop_atr": 0.9,
            "context_field": f"sweep_long={sweep_long:.2f}",
        })
    if sweep_short is not None and sweep_short >= 0.6:
        signals.append({
            "family": "liquidity_sweep_reversal", "side": "short",
            "strength": sweep_short, "target_atr": 1.6, "stop_atr": 0.9,
            "context_field": f"sweep_short={sweep_short:.2f}",
        })

    ob = ctx.get("orderbook")
    depth_imbalance = (
        _float(_dig(ob, "depth_imbalance", "orderbook_depth_imbalance"))
        or _top_book_imbalance(ctx.get("orderbook_top"))
        or _top_book_imbalance(ctx.get("orderbook_rest"))
    )
    if depth_imbalance is not None and abs(depth_imbalance) >= 0.35:
        signals.append({
            "family": "orderbook_absorption",
            "side": "long" if depth_imbalance > 0 else "short",
            "strength": min(abs(depth_imbalance), 1.0),
            "target_atr": 1.2, "stop_atr": 0.9,
            "context_field": f"depth_imbalance={depth_imbalance:.2f}",
        })

    micro = ctx.get("microstructure")
    tape = (
        _float(_dig(micro, "tape_imbalance", "order_flow_imbalance"))
        or _float(_dig(ctx.get("trade_tape"), "trade_imbalance", "tape_imbalance", "order_flow_imbalance"))
        or _float(_dig(ctx.get("trade_tape_confirmation"), "trade_imbalance", "tape_imbalance", "order_flow_imbalance"))
    )
    if tape is not None and abs(tape) >= 0.4:
        signals.append({
            "family": "microstructure_momentum",
            "side": "long" if tape > 0 else "short",
            "strength": min(abs(tape), 1.0),
            "target_atr": 1.1, "stop_atr": 0.8,
            "context_field": f"tape={tape:.2f}",
        })

    return signals


def _level_price_qty(level: Any) -> tuple[float | None, float | None]:
    if isinstance(level, Mapping):
        return (
            _float(level.get("price") or level.get("bid") or level.get("ask")),
            _float(level.get("qty") or level.get("quantity") or level.get("size")),
        )
    if isinstance(level, list | tuple) and len(level) >= 2:
        return _float(level[0]), _float(level[1])
    return None, None


def _top_book_fields(payload: Any) -> tuple[float | None, float | None, float | None, float | None]:
    if not isinstance(payload, Mapping):
        return None, None, None, None
    bid = _float(_dig(payload, "best_bid", "bid", "bid_price", "bestBid"))
    ask = _float(_dig(payload, "best_ask", "ask", "ask_price", "bestAsk"))
    bid_qty = _float(_dig(payload, "best_bid_size", "bid_size", "bid_qty", "bidQty"))
    ask_qty = _float(_dig(payload, "best_ask_size", "ask_size", "ask_qty", "askQty"))
    bids = payload.get("bids")
    asks = payload.get("asks")
    if bid is None and isinstance(bids, list) and bids:
        bid, bid_qty = _level_price_qty(bids[0])
    if ask is None and isinstance(asks, list) and asks:
        ask, ask_qty = _level_price_qty(asks[0])
    return bid, ask, bid_qty, ask_qty


def _top_book_depth_usd(payload: Any) -> float | None:
    direct = _float(_dig(payload, "top_of_book_depth_usd", "orderbook_depth_usd", "depth_usd", "depth_total_usd"))
    if direct is not None and direct > 0:
        return direct
    bid, ask, bid_qty, ask_qty = _top_book_fields(payload)
    if bid is None or ask is None or bid_qty is None or ask_qty is None:
        return None
    if bid <= 0 or ask <= 0 or bid_qty <= 0 or ask_qty <= 0:
        return None
    return min(bid * bid_qty, ask * ask_qty)


def _top_book_imbalance(payload: Any) -> float | None:
    direct = _float(_dig(payload, "depth_imbalance", "orderbook_depth_imbalance", "ob_imbalance"))
    if direct is not None:
        return max(-1.0, min(1.0, direct))
    bid, ask, bid_qty, ask_qty = _top_book_fields(payload)
    if bid is None or ask is None or bid_qty is None or ask_qty is None:
        return None
    bid_depth = bid * bid_qty
    ask_depth = ask * ask_qty
    total = bid_depth + ask_depth
    if total <= 0:
        return None
    return max(-1.0, min(1.0, (bid_depth - ask_depth) / total))


def _execution_grade_microstructure_trust(ctx: Mapping[str, Any]) -> float | None:
    trust = ctx.get("microstructure_trust")
    orderbook = ctx.get("orderbook")
    top = ctx.get("orderbook_top")
    if not isinstance(trust, Mapping):
        return None
    if trust.get("feed_quality_fail_closed") is True:
        return None
    if trust.get("real_spread_depth_cost_evidence_pass") is not True:
        return None
    if trust.get("trade_tape_confirmation_pass") is not True:
        return None
    availability = trust.get("source_availability")
    if isinstance(availability, Mapping) and availability.get("direct_binance_or_kucoin") is not True:
        return None
    tape_score = _float(_dig(trust, "trade_tape_confirmation_score"))
    if tape_score is None or tape_score < 0.65:
        return None
    cross_venue = _float(_dig(trust, "cross_venue_confirmation_score"))
    sources = trust.get("usable_source_exchanges") or trust.get("direct_orderbook_sources") or []
    source_count = len(sources) if isinstance(sources, list) else 0
    if (cross_venue is None or cross_venue < 0.55) and source_count < 2:
        return None
    depth = (
        _float(_dig(orderbook, "orderbook_depth_usd", "book_depth_usd", "depth_usd", "depth_total_usd"))
        or _top_book_depth_usd(top)
        or _top_book_depth_usd(ctx.get("orderbook_rest"))
    )
    if depth is None or depth < REFERENCE_NOTIONAL_USD * 25.0:
        return None
    spread_bps = (
        _float(_dig(orderbook, "spread_bps", "bid_ask_spread_bps"))
        or _float(_dig(top, "spread_bps", "bid_ask_spread_bps"))
    )
    if spread_bps is None or spread_bps > 8.0:
        return None
    imbalance = (
        _float(_dig(orderbook, "depth_imbalance", "orderbook_imbalance", "orderbook_depth_imbalance"))
        or _top_book_imbalance(top)
        or 0.0
    )
    if abs(imbalance) >= 0.80:
        return None

    depth_score = min(0.08, depth / (REFERENCE_NOTIONAL_USD * 250.0) * 0.08)
    spread_score = 0.06 if spread_bps <= 2.0 else 0.025
    tape_score_component = min(0.10, max(0.0, tape_score - 0.60) * 0.35)
    cross_component = min(0.08, max(0.0, (cross_venue or 0.55) - 0.50) * 0.35)
    source_component = 0.04 if source_count >= 2 else 0.015
    imbalance_penalty = min(0.08, abs(imbalance) * 0.08)
    score = (
        0.60
        + depth_score
        + spread_score
        + tape_score_component
        + cross_component
        + source_component
        - imbalance_penalty
    )
    return round(max(0.0, min(1.0, score)), 8)


def _microstructure_trust(ctx: Mapping[str, Any]) -> float | None:
    micro = ctx.get("microstructure")
    trust = ctx.get("microstructure_trust")
    orderbook = ctx.get("orderbook")
    top = ctx.get("orderbook_top")
    rest_book = ctx.get("orderbook_rest")
    explicit = (
        _float(_dig(trust, "composite_microstructure_trust_score", "microstructure_trust_score"))
        or _float(_dig(trust, "public_orderbook_trust_score", "orderbook_trust_score"))
        or _float(_dig(trust, "trade_tape_confirmation_score"))
        or _float(_dig(micro, "microstructure_trust_score", "composite_microstructure_trust_score"))
        or _float(_dig(orderbook, "microstructure_trust_score", "orderbook_trust_score"))
    )
    execution_grade = _execution_grade_microstructure_trust(ctx)
    if explicit is not None:
        explicit = max(0.0, min(1.0, explicit))
        return max(explicit, execution_grade) if execution_grade is not None else explicit
    if execution_grade is not None:
        return execution_grade
    depth = (
        _float(_dig(orderbook, "book_depth_usd", "depth_usd", "orderbook_depth_usd", "top_of_book_depth_usd"))
        or _top_book_depth_usd(top)
        or _top_book_depth_usd(rest_book)
    )
    imbalance = (
        _float(_dig(orderbook, "depth_imbalance", "orderbook_depth_imbalance", "ob_imbalance"))
        or _top_book_imbalance(top)
        or _top_book_imbalance(rest_book)
    )
    if depth is None or depth <= 0 or imbalance is None:
        return None
    depth_score = max(0.0, min(0.4, depth / (REFERENCE_NOTIONAL_USD * 10.0) * 0.4))
    balance_score = max(0.0, min(0.4, (1.0 - min(abs(imbalance), 1.0)) * 0.4))
    return round(0.2 + depth_score + balance_score, 4)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "stale"}


def _epoch_ms_now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _liquidation_no_events_observed(payload: Mapping[str, Any]) -> bool:
    if _truthy(payload.get("liquidation_no_events")):
        return True
    levels_json = payload.get("liquidation_levels_json")
    if isinstance(levels_json, str) and levels_json:
        try:
            parsed = json.loads(levels_json)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, Mapping):
            return parsed.get("no_events_reason") == "no_liquidation_events_in_window"
    return False


def _timeframe_ms_from_source_key(source_key: Any) -> int | None:
    if not isinstance(source_key, str) or ":" not in source_key:
        return None
    token = source_key.rsplit(":", 1)[-1]
    try:
        if token.endswith("m"):
            return int(token[:-1]) * 60 * 1000
        if token.endswith("h"):
            return int(token[:-1]) * 60 * 60 * 1000
        if token.endswith("d"):
            return int(token[:-1]) * 24 * 60 * 60 * 1000
    except ValueError:
        return None
    return None


def _aged_liquidation_levels_still_actionable(
    ctx: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    now_ms = _epoch_ms_now()
    updated_ts = _float(payload.get("liquidation_updated_ts") or payload.get("updated_ts"))
    current_price = _float(payload.get("liquidation_current_price") or payload.get("current_price"))
    last_event_ts = _float(payload.get("liquidation_last_event_ts") or payload.get("last_event_ts"))
    published_staleness_ms = _float(payload.get("liquidation_staleness_ms") or payload.get("staleness_ms"))
    levels_count = int(
        (_float(payload.get("liquidation_levels_count_long")) or 0)
        + (_float(payload.get("liquidation_levels_count_short")) or 0)
    )
    source_key = str(ctx.get("liquidation_levels_source") or "")
    timeframe_ms = _timeframe_ms_from_source_key(source_key)
    retention_ms = min(
        MAX_AGED_LIQUIDATION_LEVEL_AGE_MS,
        max((timeframe_ms or 0) * 20, 2 * 60 * 60 * 1000),
    )
    updated_age_ms = (_epoch_ms_now() - int(updated_ts)) if updated_ts is not None else None
    event_age_ms = (
        int(published_staleness_ms)
        if published_staleness_ms is not None and published_staleness_ms >= 0
        else (now_ms - int(last_event_ts)) if last_event_ts is not None and last_event_ts > 0 else None
    )
    trust = ctx.get("microstructure_trust")
    sweep_ok = isinstance(trust, Mapping) and trust.get("liquidation_sweep_risk_acceptable") is True
    details = {
        "liquidation_levels_count": levels_count,
        "liquidation_updated_age_ms": updated_age_ms,
        "liquidation_event_age_ms": event_age_ms,
        "liquidation_retention_ms": retention_ms,
        "sweep_detector_accepted": bool(sweep_ok),
    }
    return (
        levels_count > 0
        and current_price is not None
        and current_price > 0
        and updated_age_ms is not None
        and 0 <= updated_age_ms <= FRESH_RECOMPUTED_LIQUIDATION_MAX_AGE_MS
        and event_age_ms is not None
        and 0 <= event_age_ms <= retention_ms
        and sweep_ok
    ), details


def _fresh_liquidation_context(ctx: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    payload = ctx.get("liquidation_levels")
    if not isinstance(payload, Mapping):
        return None, "LIQUIDATION_CONTEXT_MISSING"
    if _truthy(payload.get("liquidation_is_stale") or payload.get("is_stale") or payload.get("stale")):
        no_events_observed = _liquidation_no_events_observed(payload)
        updated_ts = _float(payload.get("liquidation_updated_ts") or payload.get("updated_ts"))
        current_price = _float(payload.get("liquidation_current_price") or payload.get("current_price"))
        updated_age_ms = (_epoch_ms_now() - int(updated_ts)) if updated_ts is not None else None
        if not no_events_observed:
            aged_levels_ok, aged_details = _aged_liquidation_levels_still_actionable(ctx, payload)
            if aged_levels_ok:
                out = dict(payload)
                out["source_key"] = str(ctx.get("liquidation_levels_source") or "")
                out["provider_family"] = "coinank_or_liquidation_bridge"
                out["liquidation_context_status"] = "FRESHLY_RECOMPUTED_AGED_LEVELS_SWEEP_ACCEPTED"
                out.update(aged_details)
                return out, None
            if aged_details.get("liquidation_levels_count", 0) > 0 and not aged_details.get("sweep_detector_accepted"):
                return None, "LIQUIDATION_CONTEXT_STALE_SWEEP_DETECTOR_NOT_ACCEPTED"
            return None, "LIQUIDATION_CONTEXT_STALE"
        if updated_age_ms is None or updated_age_ms < 0 or updated_age_ms > FRESH_NO_EVENT_LIQUIDATION_MAX_AGE_MS:
            return None, "LIQUIDATION_CONTEXT_STALE_NO_EVENTS_OBSERVATION_EXPIRED"
        if current_price is None or current_price <= 0:
            return None, "LIQUIDATION_CONTEXT_STALE_NO_EVENTS_PRICE_MISSING"
        out = dict(payload)
        out["source_key"] = str(ctx.get("liquidation_levels_source") or "")
        out["provider_family"] = "coinank_or_liquidation_bridge"
        out["liquidation_context_status"] = "FRESH_NO_LIQUIDATION_EVENTS_IN_WINDOW"
        out["liquidation_no_events_updated_age_ms"] = updated_age_ms
        return out, None
    out = dict(payload)
    out["source_key"] = str(ctx.get("liquidation_levels_source") or "")
    out["provider_family"] = "coinank_or_liquidation_bridge"
    return out, None


def _strategy_market_regime(signal: Mapping[str, Any]) -> str:
    family = str(signal.get("family") or "").lower()
    if family in {"range_mean_reversion"}:
        return "RANGE_MEAN_REVERSION"
    if family in {"funding_squeeze", "long_short_imbalance_squeeze", "liquidation_cluster_magnet"}:
        return "DERIVATIVES_STRESS"
    if family in {"liquidity_sweep_reversal"}:
        return "LIQUIDITY_SWEEP_REVERSAL"
    if family in {"breakout_after_compression", "volatility_expansion"}:
        return "BREAKOUT_EXPANSION"
    if family in {"trend_continuation", "pullback_continuation", "fvg_retest"}:
        return "TREND_CONTINUATION"
    if family in {"orderbook_absorption", "microstructure_momentum"}:
        return "MICROSTRUCTURE_MOMENTUM"
    return "STRUCTURAL_HYPOTHESIS"


def _trade_tape_confirmation(ctx: Mapping[str, Any]) -> float | None:
    micro = ctx.get("microstructure")
    trust = ctx.get("microstructure_trust")
    orderbook = ctx.get("orderbook")
    tape_payload = ctx.get("trade_tape")
    tape_confirm = ctx.get("trade_tape_confirmation")
    explicit = (
        _float(_dig(trust, "trade_tape_confirmation_score"))
        or _float(_dig(tape_payload, "trade_tape_confirmation_score"))
        or _float(_dig(tape_confirm, "trade_tape_confirmation_score"))
        or _float(_dig(micro, "trade_tape_confirmation_score", "tape_confirmation_score"))
        or _float(_dig(orderbook, "trade_tape_confirmation_score"))
    )
    if explicit is not None:
        return max(0.0, min(1.0, explicit))
    tape = (
        _float(_dig(micro, "tape_imbalance", "order_flow_imbalance"))
        or _float(_dig(tape_payload, "trade_imbalance", "tape_imbalance", "order_flow_imbalance"))
        or _float(_dig(tape_confirm, "trade_imbalance", "tape_imbalance", "order_flow_imbalance"))
    )
    if tape is None:
        return None
    return round(max(0.0, min(1.0, 0.5 + abs(tape) * 0.5)), 4)


def _advanced_indicator_context(
    ctx: Mapping[str, Any],
    *,
    signal: Mapping[str, Any],
    side: str,
    expected_edge_after_cost_bps: float | None,
    trust_score: float | None,
    tape_score: float | None,
) -> dict[str, Any]:
    fvg = ctx.get("fvg")
    sweep = ctx.get("sweep_risk")
    context: dict[str, Any] = {}
    bullish = _dig(fvg, "bullish_fvg_present", "has_bullish_fvg")
    bearish = _dig(fvg, "bearish_fvg_present", "has_bearish_fvg")
    if bullish is not None:
        context["bullish_fvg_present"] = bool(bullish)
    if bearish is not None:
        context["bearish_fvg_present"] = bool(bearish)
    sweep_long = _float(_dig(sweep, "sweep_risk_long_side"))
    sweep_short = _float(_dig(sweep, "sweep_risk_short_side"))
    if sweep_long is not None:
        context["sweep_risk_long_side"] = sweep_long
    if sweep_short is not None:
        context["sweep_risk_short_side"] = sweep_short
    if trust_score is not None:
        context["fvg_orderbook_trust_confluence"] = trust_score
    if tape_score is not None:
        context["fvg_trade_tape_confirmation"] = tape_score
        context["trade_tape_confirmation_score"] = tape_score
    if expected_edge_after_cost_bps is not None:
        context["fvg_expected_edge_after_cost"] = expected_edge_after_cost_bps
    family = str(signal.get("family") or "")
    if not context and family in {"fvg_retest", "liquidity_sweep_reversal", "orderbook_absorption", "microstructure_momentum"}:
        context["structure_trend_state"] = "hypothesis_context_present"
    if side == "long":
        context.setdefault("bos_direction", "up")
    elif side == "short":
        context.setdefault("bos_direction", "down")
    return context


def generate_hypotheses(client: Any, symbol: str, timeframe: str) -> list[dict[str, Any]]:
    symbol = str(symbol or "").upper()
    ctx = _context(client, symbol, timeframe)
    price_payload = ctx["price"]
    price = _float(price_payload.get("price")) if isinstance(price_payload, Mapping) else None
    generated = _utc_now()
    rows: list[dict[str, Any]] = []

    if price is None or price <= 0:
        reason = f"PRICE_MISSING:{(price_payload or {}).get('reason_if_missing') or 'NO_EXCHANGE_MARKET'}"
        return [{
            **_contract_base(
                ctx=ctx,
                symbol=symbol,
                timeframe=timeframe,
                strategy_family=None,
                strategy_subtype="degraded_no_price",
                side=None,
                generated=generated,
                current_price=None,
                price_payload=price_payload if isinstance(price_payload, Mapping) else {},
                reason_if_rejected=reason,
            ),
            "expected_gross_pnl_usd": None,
            "expected_cost_usd": None,
            "expected_net_pnl_usd": None,
            "expected_max_loss_usd": None,
            "reward_to_risk": None,
            "loss_probability": None,
            "microstructure_trust": None,
            "squeeze_risk": None,
            "liquidation_cluster_distance_usd": None,
            "hedge_required": False,
            "exit_plan": {"status": "NO_EXIT_PLAN", "reason": reason},
        }]

    ta_evidence = _closed_ta_point_in_time_evidence(
        ctx.get("ta"),
        symbol=symbol,
        timeframe=timeframe,
        decision_time=generated,
    )
    if ta_evidence["valid"] is not True:
        reason = str(ta_evidence["reason"])
        return [{
            **_contract_base(
                ctx=ctx,
                symbol=symbol,
                timeframe=timeframe,
                strategy_family=None,
                strategy_subtype="degraded_closed_feature_evidence_invalid",
                side=None,
                generated=generated,
                current_price=price,
                price_payload=price_payload if isinstance(price_payload, Mapping) else {},
                reason_if_rejected=reason,
            ),
            "expected_gross_pnl_usd": None,
            "expected_cost_usd": None,
            "expected_net_pnl_usd": None,
            "expected_max_loss_usd": None,
            "reward_to_risk": None,
            "loss_probability": None,
            "microstructure_trust": None,
            "squeeze_risk": None,
            "liquidation_cluster_distance_usd": None,
            "hedge_required": False,
            "exit_plan": {"status": "NO_EXIT_PLAN", "reason": reason},
        }]

    atr = _atr_bps(ctx, price)
    if atr is None or atr <= 0:
        reason = "ATR_NOISE_MISSING_NO_STOP_BASIS"
        return [{
            **_contract_base(
                ctx=ctx,
                symbol=symbol,
                timeframe=timeframe,
                strategy_family=None,
                strategy_subtype="degraded_input_missing",
                side=None,
                generated=generated,
                current_price=price,
                price_payload=price_payload if isinstance(price_payload, Mapping) else {},
                reason_if_rejected=reason,
            ),
            "expected_gross_pnl_usd": None,
            "expected_cost_usd": None,
            "expected_net_pnl_usd": None,
            "expected_max_loss_usd": None,
            "reward_to_risk": None,
            "loss_probability": None,
            "microstructure_trust": None,
            "squeeze_risk": None,
            "liquidation_cluster_distance_usd": None,
            "hedge_required": False,
            "exit_plan": {"status": "NO_EXIT_PLAN", "reason": reason},
        }]

    signals = _family_signals(ctx)
    if not signals:
        reason = "NO_STRUCTURE_SIGNAL_IN_ANY_FAMILY"
        return [{
            **_contract_base(
                ctx=ctx,
                symbol=symbol,
                timeframe=timeframe,
                strategy_family=None,
                strategy_subtype="degraded_true_no_edge",
                side=None,
                generated=generated,
                current_price=price,
                price_payload=price_payload if isinstance(price_payload, Mapping) else {},
                reason_if_rejected=reason,
            ),
            "expected_gross_pnl_usd": None,
            "expected_cost_usd": None,
            "expected_net_pnl_usd": None,
            "expected_max_loss_usd": None,
            "reward_to_risk": None,
            "loss_probability": None,
            "microstructure_trust": None,
            "squeeze_risk": None,
            "liquidation_cluster_distance_usd": None,
            "hedge_required": False,
            "exit_plan": {"status": "NO_EXIT_PLAN", "reason": reason},
        }]

    reference_notional_usd, reference_notional_source = _risk_profile_reference_notional_usd(client)

    for signal in signals:
        side = signal["side"]
        target_bps = atr * signal["target_atr"]
        stop_bps = atr * signal["stop_atr"]
        expected_edge_after_cost_bps = target_bps - (ROUND_TRIP_COST_BPS + LATENCY_RESERVE_BPS)
        stop_price = price * (1 - stop_bps / 10_000.0) if side == "long" else price * (1 + stop_bps / 10_000.0)
        target_price = price * (1 + target_bps / 10_000.0) if side == "long" else price * (1 - target_bps / 10_000.0)
        liquidation_buffer_bps = max(stop_bps * 3.0, stop_bps + 150.0)
        liquidation_buffer_usd = reference_notional_usd * liquidation_buffer_bps / 10_000.0
        exit_depth = (
            _float(_dig(ctx.get("orderbook"), "book_depth_usd", "depth_usd", "orderbook_depth_usd", "top_of_book_depth_usd"))
            or _top_book_depth_usd(ctx.get("orderbook_top"))
            or _top_book_depth_usd(ctx.get("orderbook_rest"))
        )
        exit_feasible = exit_depth is None or exit_depth >= reference_notional_usd * 2
        trust_score = _microstructure_trust(ctx)
        market_state_integrity_score = (
            round(trust_score * 100.0, 8)
            if trust_score is not None and trust_score <= 1.0
            else trust_score
        )
        tape_score = _trade_tape_confirmation(ctx)
        coinank_context, coinank_missing_reason = _fresh_liquidation_context(ctx)
        loss_probability, loss_components = _evidence_adjusted_loss_probability(
            signal=signal,
            target_move_bps=target_bps,
            stop_move_bps=stop_bps,
            trust_score=trust_score,
            tape_score=tape_score,
            exit_depth_usd=exit_depth,
            coinank_context_present=coinank_context is not None,
            reference_notional_usd=reference_notional_usd,
        )
        econ = _economics(
            price=price, side=side,
            target_move_bps=target_bps, stop_move_bps=stop_bps,
            loss_probability=loss_probability,
            reference_notional_usd=reference_notional_usd,
        )
        regime = _strategy_market_regime(signal)
        advanced_context = _advanced_indicator_context(
            ctx,
            signal=signal,
            side=side,
            expected_edge_after_cost_bps=expected_edge_after_cost_bps,
            trust_score=trust_score,
            tape_score=tape_score,
        )
        why_rejected = None
        if trust_score is None:
            why_rejected = "MICROSTRUCTURE_TRUST_MISSING"
        elif market_state_integrity_score is None or market_state_integrity_score < ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE:
            why_rejected = "MICROSTRUCTURE_TRUST_BELOW_ALLOCATOR_MINIMUM"
        elif tape_score is None:
            why_rejected = "TRADE_TAPE_CONFIRMATION_MISSING"
        elif tape_score < MIN_TRADE_TAPE_CONFIRMATION_SCORE:
            why_rejected = "TRADE_TAPE_CONFIRMATION_WEAK"
        elif MIN_COINANK_CONTEXT_REQUIRED and coinank_context is None:
            why_rejected = str(coinank_missing_reason or "COINANK_LIQUIDATION_CONTEXT_MISSING")
        elif econ["expected_net_pnl_usd"] <= 0:
            why_rejected = "EXPECTED_NET_PNL_USD_NON_POSITIVE_AT_CONSERVATIVE_LOSS_PROBABILITY"
        elif econ["reward_to_risk_usd"] < MIN_REWARD_TO_RISK:
            why_rejected = "REWARD_TO_RISK_BELOW_1"
        elif not exit_feasible:
            why_rejected = "EXIT_DEPTH_INSUFFICIENT"
        entry_available_at = (price_payload or {}).get("available_at")
        rows.append({
            **_contract_base(
                ctx=ctx,
                symbol=symbol,
                timeframe=timeframe,
                strategy_family=signal["family"],
                strategy_subtype=str(signal.get("context_field") or signal["family"]),
                side=side,
                generated=generated,
                current_price=price,
                price_payload=price_payload if isinstance(price_payload, Mapping) else {},
                reason_if_rejected=why_rejected,
                signal_context=signal.get("context_field"),
            ),
            "entry_zone": {"price": price, "source": price_payload.get("source"), "available_at": entry_available_at},
            "invalidation_price": round(stop_price, 10),
            "target_zone": {"price": round(target_price, 10)},
            **econ,
            "reward_to_risk": econ["reward_to_risk_usd"],
            "reference_notional_source": reference_notional_source,
            "confidence_raw": round(1.0 - float(loss_components["base_loss_probability"]), 6),
            "confidence_calibrated": round(1.0 - loss_probability, 6),
            "loss_probability_calibration": loss_components,
            "debug_atr_bps": atr,
            "expected_liquidation_buffer_usd": round(liquidation_buffer_usd, 6),
            "liquidation_buffer_usd": round(liquidation_buffer_usd, 6),
            "liquidation_buffer_bps": round(liquidation_buffer_bps, 6),
            "liquidation_buffer_source": "paper_strategy_stop_distance_proxy_not_signed_cross_margin",
            "liquidation_buffer_signed_read_verified": False,
            "live_liquidation_buffer_requires_signed_read": True,
            "expected_exit_depth_usd": exit_depth,
            "microstructure_trust": trust_score,
            "microstructure_trust_score": trust_score,
            "composite_microstructure_trust_score": trust_score,
            "microstructure_trust_source": ctx.get("microstructure_trust_source"),
            "market_state_integrity_score": market_state_integrity_score,
            "market_state_integrity_minimum_score": ALLOCATOR_MARKET_STATE_INTEGRITY_MIN_SCORE,
            "market_state_integrity_source": (
                ctx.get("microstructure_trust_source")
                or "derived_from_websocket_microstructure_trust"
                if market_state_integrity_score is not None
                else None
            ),
            "orderbook_depth_usd": exit_depth,
            "top_of_book_depth_usd": _top_book_depth_usd(ctx.get("orderbook_top")),
            "trade_tape_confirmation_score": tape_score,
            "market_regime": regime,
            "market_regime_at_entry": regime,
            "strategy_market_regime": regime,
            "coinank_context": coinank_context,
            "coinank_context_missing_reason": coinank_missing_reason,
            "liquidation_context_source": ctx.get("liquidation_levels_source"),
            "squeeze_risk": _float(_dig(ctx.get("sweep_risk"), "squeeze_risk", "liquidation_sweep_risk")),
            "liquidation_cluster_distance_usd": _float(
                _dig(ctx.get("liquidation_levels"), "liquidation_cluster_distance_usd")
            ),
            "advanced_indicator_context": advanced_context,
            "exit_feasible": exit_feasible,
            "exit_plan": {
                "status": "PAPER_HYPOTHESIS_EXIT_PLAN",
                "target_price": round(target_price, 10),
                "invalidation_price": round(stop_price, 10),
                "exit_feasible": exit_feasible,
            },
            "hedge_required": False,
            "signal_strength": signal["strength"],
            "fvg_context": bool(ctx.get("fvg")),
            "liquidity_context": bool(ctx.get("liquidity_zones")),
            "microstructure_context": bool(ctx.get("microstructure") or ctx.get("microstructure_trust")),
            "orderbook_context": bool(ctx.get("orderbook")),
            "top_of_book_context": bool(ctx.get("orderbook_top")),
            "trade_tape_context": bool(ctx.get("trade_tape") or ctx.get("trade_tape_confirmation")),
            "altdata_context": bool(ctx.get("confluence")),
            "coinank_context_present": bool(coinank_context),
            "coinglass_context": bool(ctx.get("coinglass")),
            "moralis_context": bool(ctx.get("moralis")),
            "ta_context": bool(ctx.get("ta") or ctx.get("latest")),
            "approves_trade_alone": False,
            "must_pass_gates": ["preemptive", "risk", "orchestrator", "allocator"],
        })
    return rows
