"""V2 unified feature tensor builder with explicit masks."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.market_structure.common import (
    bool_num,
    direction_code,
    zone_code,
)
from v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3 import (
    FEATURE_SPEC as ORDERED_FEATURE_SPEC,
)

FEATURE_SPEC: tuple[tuple[str, str], ...] = ORDERED_FEATURE_SPEC

# taf_* model-feature name -> v2:features:ta_full TA-Lib indicator key (WI feature
# expansion). The full talib loop already computes these; this wires them into the
# model_vector. Lossy name sanitisation makes an explicit map necessary.
TA_FULL_FEATURE_MAP: dict[str, str] = {
    "taf_atr_14": "atr_14",
    "taf_bb_width_pct": "bb_width_pct",
    "taf_ema_12": "ema_12",
    "taf_ema_20": "ema_20",
    "taf_ema_21": "ema_21",
    "taf_ema_26": "ema_26",
    "taf_ema_50": "ema_50",
    "taf_ema_9": "ema_9",
    "taf_macd": "macd",
    "taf_macd_hist": "macd_hist",
    "taf_macd_signal": "macd_signal",
    "taf_rsi_14": "rsi_14",
    "taf_sma_12": "sma_12",
    "taf_sma_20": "sma_20",
    "taf_sma_21": "sma_21",
    "taf_sma_26": "sma_26",
    "taf_sma_50": "sma_50",
    "taf_sma_9": "sma_9",
    "taf_ta_ad": "ta_AD",
    "taf_ta_adosc": "ta_ADOSC",
    "taf_ta_adx": "ta_ADX",
    "taf_ta_adxr": "ta_ADXR",
    "taf_ta_apo": "ta_APO",
    "taf_ta_aroonosc": "ta_AROONOSC",
    "taf_ta_aroon_aroondown": "ta_AROON_aroondown",
    "taf_ta_aroon_aroonup": "ta_AROON_aroonup",
    "taf_ta_avgprice": "ta_AVGPRICE",
    "taf_ta_bbands_20_lower": "ta_BBANDS_20_lower",
    "taf_ta_bbands_20_upper": "ta_BBANDS_20_upper",
    "taf_ta_bbands_lowerband": "ta_BBANDS_lowerband",
    "taf_ta_bbands_middleband": "ta_BBANDS_middleband",
    "taf_ta_bbands_upperband": "ta_BBANDS_upperband",
    "taf_ta_beta": "ta_BETA",
    "taf_ta_bop": "ta_BOP",
    "taf_ta_cci": "ta_CCI",
    "taf_ta_cdl2crows_integer": "ta_CDL2CROWS_integer",
    "taf_ta_cdl3blackcrows_integer": "ta_CDL3BLACKCROWS_integer",
    "taf_ta_cdl3inside_integer": "ta_CDL3INSIDE_integer",
    "taf_ta_cdl3linestrike_integer": "ta_CDL3LINESTRIKE_integer",
    "taf_ta_cdl3outside_integer": "ta_CDL3OUTSIDE_integer",
    "taf_ta_cdl3starsinsouth_integer": "ta_CDL3STARSINSOUTH_integer",
    "taf_ta_cdl3whitesoldiers_integer": "ta_CDL3WHITESOLDIERS_integer",
    "taf_ta_cdlabandonedbaby_integer": "ta_CDLABANDONEDBABY_integer",
    "taf_ta_cdladvanceblock_integer": "ta_CDLADVANCEBLOCK_integer",
    "taf_ta_cdlbelthold_integer": "ta_CDLBELTHOLD_integer",
    "taf_ta_cdlbreakaway_integer": "ta_CDLBREAKAWAY_integer",
    "taf_ta_cdlclosingmarubozu_integer": "ta_CDLCLOSINGMARUBOZU_integer",
    "taf_ta_cdlconcealbabyswall_integer": "ta_CDLCONCEALBABYSWALL_integer",
    "taf_ta_cdlcounterattack_integer": "ta_CDLCOUNTERATTACK_integer",
    "taf_ta_cdldarkcloudcover_integer": "ta_CDLDARKCLOUDCOVER_integer",
    "taf_ta_cdldojistar_integer": "ta_CDLDOJISTAR_integer",
    "taf_ta_cdldoji_integer": "ta_CDLDOJI_integer",
    "taf_ta_cdldragonflydoji_integer": "ta_CDLDRAGONFLYDOJI_integer",
    "taf_ta_cdlengulfing_integer": "ta_CDLENGULFING_integer",
    "taf_ta_cdleveningdojistar_integer": "ta_CDLEVENINGDOJISTAR_integer",
    "taf_ta_cdleveningstar_integer": "ta_CDLEVENINGSTAR_integer",
    "taf_ta_cdlgapsidesidewhite_integer": "ta_CDLGAPSIDESIDEWHITE_integer",
    "taf_ta_cdlhammer_integer": "ta_CDLHAMMER_integer",
    "taf_ta_cdlhangingman_integer": "ta_CDLHANGINGMAN_integer",
    "taf_ta_cdlharamicross_integer": "ta_CDLHARAMICROSS_integer",
    "taf_ta_cdlhighwave_integer": "ta_CDLHIGHWAVE_integer",
    "taf_ta_cdlhikkakemod_integer": "ta_CDLHIKKAKEMOD_integer",
    "taf_ta_cdlhikkake_integer": "ta_CDLHIKKAKE_integer",
    "taf_ta_cdlhomingpigeon_integer": "ta_CDLHOMINGPIGEON_integer",
    "taf_ta_cdlidentical3crows_integer": "ta_CDLIDENTICAL3CROWS_integer",
    "taf_ta_cdlinneck_integer": "ta_CDLINNECK_integer",
    "taf_ta_cdlinvertedhammer_integer": "ta_CDLINVERTEDHAMMER_integer",
    "taf_ta_cdlkickingbylength_integer": "ta_CDLKICKINGBYLENGTH_integer",
    "taf_ta_cdlkicking_integer": "ta_CDLKICKING_integer",
    "taf_ta_cdlladderbottom_integer": "ta_CDLLADDERBOTTOM_integer",
    "taf_ta_cdllongline_integer": "ta_CDLLONGLINE_integer",
    "taf_ta_cdlmarubozu_integer": "ta_CDLMARUBOZU_integer",
    "taf_ta_cdlmathold_integer": "ta_CDLMATHOLD_integer",
    "taf_ta_cdlmorningdojistar_integer": "ta_CDLMORNINGDOJISTAR_integer",
    "taf_ta_cdlmorningstar_integer": "ta_CDLMORNINGSTAR_integer",
    "taf_ta_cdlonneck_integer": "ta_CDLONNECK_integer",
    "taf_ta_cdlpiercing_integer": "ta_CDLPIERCING_integer",
    "taf_ta_cdlrickshawman_integer": "ta_CDLRICKSHAWMAN_integer",
    "taf_ta_cdlrisefall3methods_integer": "ta_CDLRISEFALL3METHODS_integer",
    "taf_ta_cdlseparatinglines_integer": "ta_CDLSEPARATINGLINES_integer",
    "taf_ta_cdlshootingstar_integer": "ta_CDLSHOOTINGSTAR_integer",
    "taf_ta_cdlshortline_integer": "ta_CDLSHORTLINE_integer",
    "taf_ta_cdlspinningtop_integer": "ta_CDLSPINNINGTOP_integer",
    "taf_ta_cdlstalledpattern_integer": "ta_CDLSTALLEDPATTERN_integer",
    "taf_ta_cdlsticksandwich_integer": "ta_CDLSTICKSANDWICH_integer",
    "taf_ta_cdltakuri_integer": "ta_CDLTAKURI_integer",
    "taf_ta_cdltasukigap_integer": "ta_CDLTASUKIGAP_integer",
    "taf_ta_cdlthrusting_integer": "ta_CDLTHRUSTING_integer",
    "taf_ta_cdltristar_integer": "ta_CDLTRISTAR_integer",
    "taf_ta_cdlunique3river_integer": "ta_CDLUNIQUE3RIVER_integer",
    "taf_ta_cdlupsidegap2crows_integer": "ta_CDLUPSIDEGAP2CROWS_integer",
    "taf_ta_cdlxsidegap3methods_integer": "ta_CDLXSIDEGAP3METHODS_integer",
    "taf_ta_cmo": "ta_CMO",
    "taf_ta_correl": "ta_CORREL",
    "taf_ta_dema": "ta_DEMA",
    "taf_ta_dx": "ta_DX",
    "taf_ta_ema": "ta_EMA",
    "taf_ta_ht_dcperiod": "ta_HT_DCPERIOD",
    "taf_ta_ht_dcphase": "ta_HT_DCPHASE",
    "taf_ta_ht_phasor_inphase": "ta_HT_PHASOR_inphase",
    "taf_ta_ht_phasor_quadrature": "ta_HT_PHASOR_quadrature",
    "taf_ta_ht_sine_leadsine": "ta_HT_SINE_leadsine",
    "taf_ta_ht_sine_sine": "ta_HT_SINE_sine",
    "taf_ta_ht_trendline": "ta_HT_TRENDLINE",
    "taf_ta_ht_trendmode_integer": "ta_HT_TRENDMODE_integer",
    "taf_ta_kama": "ta_KAMA",
    "taf_ta_linearreg": "ta_LINEARREG",
    "taf_ta_linearreg_angle": "ta_LINEARREG_ANGLE",
    "taf_ta_linearreg_intercept": "ta_LINEARREG_INTERCEPT",
    "taf_ta_linearreg_slope": "ta_LINEARREG_SLOPE",
    "taf_ta_ma": "ta_MA",
    "taf_ta_macdext_macdhist": "ta_MACDEXT_macdhist",
    "taf_ta_macdext_macdsignal": "ta_MACDEXT_macdsignal",
    "taf_ta_macdfix_macd": "ta_MACDFIX_macd",
    "taf_ta_macdfix_macdhist": "ta_MACDFIX_macdhist",
    "taf_ta_macdfix_macdsignal": "ta_MACDFIX_macdsignal",
    "taf_ta_mama_fama": "ta_MAMA_fama",
    "taf_ta_mama_mama": "ta_MAMA_mama",
    "taf_ta_mavp": "ta_MAVP",
    "taf_ta_medprice": "ta_MEDPRICE",
    "taf_ta_mfi": "ta_MFI",
    "taf_ta_midpoint": "ta_MIDPOINT",
    "taf_ta_midprice": "ta_MIDPRICE",
    "taf_ta_minus_di": "ta_MINUS_DI",
    "taf_ta_minus_dm": "ta_MINUS_DM",
    "taf_ta_mom": "ta_MOM",
    "taf_ta_natr": "ta_NATR",
    "taf_ta_obv": "ta_OBV",
    "taf_ta_plus_di": "ta_PLUS_DI",
    "taf_ta_plus_dm": "ta_PLUS_DM",
    "taf_ta_ppo": "ta_PPO",
    "taf_ta_roc": "ta_ROC",
    "taf_ta_rocp": "ta_ROCP",
    "taf_ta_rocr": "ta_ROCR",
    "taf_ta_rocr100": "ta_ROCR100",
    "taf_ta_sar": "ta_SAR",
    "taf_ta_sarext": "ta_SAREXT",
    "taf_ta_stddev": "ta_STDDEV",
    "taf_ta_stochf_fastd": "ta_STOCHF_fastd",
    "taf_ta_stochf_fastk": "ta_STOCHF_fastk",
    "taf_ta_stochrsi_fastd": "ta_STOCHRSI_fastd",
    "taf_ta_stochrsi_fastk": "ta_STOCHRSI_fastk",
    "taf_ta_stoch_slowd": "ta_STOCH_slowd",
    "taf_ta_t3": "ta_T3",
    "taf_ta_tema": "ta_TEMA",
    "taf_ta_trange": "ta_TRANGE",
    "taf_ta_trima": "ta_TRIMA",
    "taf_ta_trix": "ta_TRIX",
    "taf_ta_tsf": "ta_TSF",
    "taf_ta_typprice": "ta_TYPPRICE",
    "taf_ta_ultosc": "ta_ULTOSC",
    "taf_ta_var": "ta_VAR",
    "taf_ta_wclprice": "ta_WCLPRICE",
    "taf_ta_willr": "ta_WILLR",
    "taf_ta_wma": "ta_WMA",
}


@dataclass(frozen=True)
class FeatureTensorRecord:
    tensor_id: str
    symbol: str
    timeframe: str
    feature_snapshot_id: str
    values: tuple[float, ...]
    missing_mask: tuple[int, ...]
    stale_mask: tuple[int, ...]
    source_availability: tuple[int, ...]
    feature_names: tuple[str, ...]
    source_labels: tuple[str, ...]
    missing_feature_names: tuple[str, ...]
    stale_feature_names: tuple[str, ...]
    data_coverage_percent: float
    source_availability_vector: tuple[int, ...]
    decision_time: str | None = None
    source_lineage_hash: str = ""
    temporal_rejection_reasons: tuple[str, ...] = ()

    @property
    def model_vector(self) -> tuple[float, ...]:
        return (
            self.values
            + tuple(float(v) for v in self.missing_mask)
            + tuple(float(v) for v in self.stale_mask)
            + tuple(float(v) for v in self.source_availability)
        )


def _finite_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _dig(payload: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        cur: Any = payload
        for part in key.split("."):
            if not isinstance(cur, Mapping):
                cur = None
                break
            cur = cur.get(part)
        if cur is not None:
            return cur
    return None


def _provider_feature_values(payloads: Mapping[str, Any]) -> dict[str, float]:
    """Extract point-in-time checked provider bridge features supplied by callers."""
    context = payloads.get("provider_feature_context")
    candidate = context.get("provider_features") if isinstance(context, Mapping) else None
    if not isinstance(candidate, Mapping):
        return {}
    out: dict[str, float] = {}
    for name, value in candidate.items():
        parsed = _finite_float(value)
        if parsed is not None:
            out[str(name)] = parsed
    return out


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _strict_utc_datetime(value: Any) -> datetime | None:
    """Parse an unambiguous instant and reject naive wall-clock strings.

    Unix epochs are unambiguous UTC instants. ISO strings and ``datetime``
    values must carry an explicit UTC offset; silently assigning UTC to a
    naive producer clock would make point-in-time validation fictional.
    """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        epoch = float(value)
        if not math.isfinite(epoch):
            return None
        if abs(epoch) >= 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _strict_utc_ms(value: Any) -> int | None:
    parsed = _strict_utc_datetime(value)
    if parsed is None:
        return None
    return int(parsed.timestamp() * 1000)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _kline_close_ms(row: Any) -> int | None:
    if isinstance(row, Mapping):
        return _strict_utc_ms(
            _first_present(
                row.get("close_time"),
                row.get("candle_close_time"),
                row.get("closeTime"),
                row.get("T"),
            )
        )
    if isinstance(row, (list, tuple)) and len(row) >= 7:
        return _strict_utc_ms(row[6])
    return None


def _latest_kline(
    ohlcv: Any,
    *,
    decision_time_ms: int,
) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    """Return the newest candle whose finality is independently provable.

    A producer boolean is only an assertion. It is accepted only together with
    a strict-aware close clock that is not after the observation/decision
    cutoff. Raw Binance arrays carry no explicit finality assertion and are
    therefore never promoted to closed candles in this consumer.
    """

    if isinstance(ohlcv, Mapping):
        candidates: tuple[Any, ...] = (ohlcv,)
    elif isinstance(ohlcv, list):
        candidates = tuple(reversed(ohlcv))
    else:
        candidates = ()
    if not candidates:
        return {}, ()

    reasons: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            reasons.append("OHLCV_FINALITY_UNKNOWN")
            continue
        finality = _first_present(
            candidate.get("closed_candle"),
            candidate.get("is_closed"),
            candidate.get("candle_closed_confirmed"),
        )
        if finality is not True:
            reasons.append("OHLCV_FINALITY_NOT_CONFIRMED")
            continue
        close_time_ms = _kline_close_ms(candidate)
        if close_time_ms is None:
            reasons.append("OHLCV_CLOSE_TIME_NOT_STRICT_UTC")
            continue
        if close_time_ms > decision_time_ms:
            reasons.append("OHLCV_CLOSE_TIME_AFTER_DECISION_TIME")
            continue
        return candidate, tuple(sorted(set(reasons)))
    return {}, tuple(sorted(set(reasons)))


_SOURCE_CLOCK_FIELDS: tuple[str, ...] = (
    "event_time",
    "source_event_time",
    "ingested_at",
    "received_at",
    "source_received_time",
    "available_at",
    "source_available_time",
    "generated_at",
    "generated_utc",
    "feature_cutoff",
    "decision_time",
    "execution_time",
)
_FRESHNESS_FIELDS: tuple[str, ...] = (
    "freshness_state",
    "feature_freshness_state",
    "freshness_flag",
    "is_fresh",
    "fresh",
)

_SOURCE_LABELS_BY_PAYLOAD: dict[str, tuple[str, ...]] = {
    "prices": ("v2:market:prices",),
    "ohlcv": ("v2:market:ohlcv",),
    "orderbook": ("v2:market:orderbook", "v2:orderbook:features"),
    "funding": ("v2:market:funding",),
    "open_interest": ("v2:market:open_interest",),
    "open_interest_hist": ("v2:market:open_interest_hist",),
    "long_short": ("v2:market:long_short",),
    "features_latest": ("v2:features:latest",),
    "features_ta": ("v2:features:ta",),
    "features_ta_full": ("v2:features:ta_full",),
    "ta_full_htf_1h": ("v2:features:ta_full:1h",),
    "technical_analysis": ("v2:features:ta",),
    "liquidations": ("v2:liquidations:events",),
    "liquidations_agg": ("v2:market:liquidations:aggregate",),
    "liquidation_levels": (
        "v2:market:liquidation_levels",
        "v2:liquidations:levels",
    ),
    "liquidity_zones": ("v2:market:liquidity_zones",),
    "fvg": ("v2:market:fvg",),
    "market_structure": ("v2:market:structure",),
    "structure": ("v2:market:structure",),
    "sweep_risk": ("v2:market:sweep_risk",),
    "vwap_features": ("v2:market:vwap",),
    "volume_profile": ("v2:market:volume_profile",),
    "cvd_features": ("v2:market:cvd",),
    "trade_tape": ("v2:market:trade_tape_features",),
    "trade_tape_features": ("v2:market:trade_tape_features",),
    "advanced_trade_tape": ("v2:market:trade_tape_features",),
    "microstructure": (
        "v2:market:microstructure",
        "v2:microstructure:adversarial_features",
        "v2:microstructure:cross_venue_confirmation",
        "v2:microstructure:feed_quality",
        "v2:microstructure:sweep_risk",
        "v2:microstructure:trade_tape_confirmation",
    ),
    "microstructure_trust": ("v2:microstructure:trust_score",),
    "cascade_context": ("v2:microstructure:cascade_context",),
    "symbol_score": ("v2:altdata:symbol_score",),
    "public_intel": ("v2:altdata:public_intel",),
    "whale_walls": ("v2:altdata:whale_walls",),
    "moralis_features": ("v2:features:moralis",),
    "smart_money_signals": ("v2:smart_money:signals",),
    "altdata_confluence": ("v2:altdata:confluence",),
    "provider_feature_context": ("provider_feature_bridge",),
    "paper_positions": ("v2:paper:positions",),
    "risk_decisions": ("v2:risk:decisions",),
    "orchestrator_decisions": ("v2:orchestrator:decisions",),
    "coinank_open_interest": ("latest:coinank:open_interest",),
    "coinank_funding": ("latest:coinank:funding",),
    "coinank_long_short": ("latest:coinank:long_short",),
    "coinank_liquidations": ("latest:coinank:liquidations",),
    "coinank_market_order_flow": ("latest:coinank:market_order_flow",),
}


def _resolve_decision_time(
    payloads: Mapping[str, Any],
    *,
    decision_time: Any,
) -> tuple[datetime, str]:
    latest = payloads.get("features_latest")
    prediction = payloads.get("prediction")
    candidates: tuple[tuple[str, Any], ...] = (
        ("argument.decision_time", decision_time),
        ("payloads.decision_time", payloads.get("decision_time")),
        ("payloads.observation_cutoff", payloads.get("observation_cutoff")),
        ("features_latest.decision_time", _dig(latest, "decision_time")),
        ("features_latest.decision_cutoff", _dig(latest, "decision_cutoff")),
        ("prediction.decision_time", _dig(prediction, "decision_time")),
    )
    for source, raw in candidates:
        if raw in (None, ""):
            continue
        parsed = _strict_utc_datetime(raw)
        if parsed is None:
            raise ValueError(f"{source}_not_strict_utc")
        return parsed, source
    # A live build with no recorded decision clock is an observation at this
    # exact aware instant. Historical/replay producers are expected to carry a
    # durable decision_time, which takes precedence above.
    return datetime.now(tz=timezone.utc), "builder.observed_at"


def _source_temporal_state(
    *,
    payload_name: str,
    payload: Any,
    decision_time: datetime,
    require_available_at: bool = False,
    available_at_override: Any = None,
    _seen_ids: set[int] | None = None,
) -> tuple[int | None, tuple[str, ...]]:
    prefix = payload_name.upper()
    seen_ids = set() if _seen_ids is None else set(_seen_ids)
    if isinstance(payload, (Mapping, list, tuple)):
        payload_id = id(payload)
        if payload_id in seen_ids:
            return None, (f"{payload_name.upper()}_NESTED_PAYLOAD_CYCLE",)
        seen_ids.add(payload_id)

    if isinstance(payload, (list, tuple)):
        if not payload:
            if require_available_at:
                # An empty collection is not evidence that the observed window
                # was genuinely empty. A wrapper clock alone cannot distinguish
                # that state from a failed, truncated, or rate-limited read.
                # Until an authenticated typed-negative receipt is supplied by
                # the canonical resolver, keep every derived value missing.
                return None, (f"{prefix}_EMPTY_COLLECTION_RECEIPT_MISSING",)
            return None, ()
        available_times: list[int] = []
        row_reasons: list[str] = []
        for row in payload:
            if not isinstance(row, (Mapping, list, tuple)):
                row_reasons.append(f"{prefix}_ROW_TYPE_INVALID")
                continue
            available_ms, reasons = _source_temporal_state(
                payload_name=payload_name,
                payload=row,
                decision_time=decision_time,
                require_available_at=require_available_at,
                available_at_override=available_at_override,
                _seen_ids=seen_ids,
            )
            if available_ms is not None:
                available_times.append(available_ms)
            row_reasons.extend(reasons)
        unique = tuple(sorted(set(row_reasons)))
        return (max(available_times) if available_times and not unique else None, unique)
    if not isinstance(payload, Mapping) or not payload:
        return None, ()

    parsed_clocks: dict[str, datetime] = {}
    reasons: list[str] = []
    for field in _SOURCE_CLOCK_FIELDS:
        raw = payload.get(field)
        if raw in (None, ""):
            continue
        parsed = _strict_utc_datetime(raw)
        if parsed is None:
            reasons.append(f"{prefix}_{field.upper()}_NOT_STRICT_UTC")
            continue
        parsed_clocks[field] = parsed
        if parsed > decision_time:
            reasons.append(f"{prefix}_{field.upper()}_AFTER_DECISION_TIME")

    literal_available = parsed_clocks.get("available_at")
    available = literal_available or parsed_clocks.get("source_available_time")
    if available is None and available_at_override not in (None, ""):
        override = _strict_utc_datetime(available_at_override)
        if override is None:
            reasons.append(f"{prefix}_AVAILABLE_AT_OVERRIDE_NOT_STRICT_UTC")
        else:
            available = override
            if override > decision_time:
                reasons.append(f"{prefix}_AVAILABLE_AT_AFTER_DECISION_TIME")
    if require_available_at and available is None:
        reasons.append(f"{prefix}_AVAILABLE_AT_MISSING")

    freshness_asserted = any(field in payload for field in _FRESHNESS_FIELDS)
    if freshness_asserted and available is None:
        reasons.append(f"{prefix}_AVAILABLE_AT_MISSING_FOR_FRESHNESS_FLAG")
    if available is not None and available > decision_time:
        reasons.append(f"{prefix}_AVAILABLE_AT_AFTER_DECISION_TIME")

    event = parsed_clocks.get("event_time") or parsed_clocks.get("source_event_time")
    ingested = parsed_clocks.get("ingested_at") or parsed_clocks.get("received_at")
    if event is not None and ingested is not None and event > ingested:
        reasons.append(f"{prefix}_EVENT_TIME_AFTER_INGESTED_AT")
    if event is not None and available is not None and event > available:
        reasons.append(f"{prefix}_EVENT_TIME_AFTER_AVAILABLE_AT")
    if ingested is not None and available is not None and ingested > available:
        reasons.append(f"{prefix}_INGESTED_AT_AFTER_AVAILABLE_AT")
    generated = parsed_clocks.get("generated_at") or parsed_clocks.get("generated_utc")
    if generated is not None and available is not None and generated > available:
        reasons.append(f"{prefix}_GENERATED_AT_AFTER_AVAILABLE_AT")
    feature_cutoff = parsed_clocks.get("feature_cutoff")
    if feature_cutoff is not None and feature_cutoff > decision_time:
        reasons.append(f"{prefix}_FEATURE_CUTOFF_AFTER_DECISION_TIME")

    # A causal wrapper availability clock is a conservative upper bound for
    # nested values that do not publish their own availability. Nested clocks
    # still have to be strict, causally ordered, and no later than the decision.
    # This closes bridge payloads whose selected row carried a future event_time
    # underneath an otherwise causal top-level wrapper.
    for key, nested in payload.items():
        if key in _SOURCE_CLOCK_FIELDS or key in _FRESHNESS_FIELDS:
            continue
        if not isinstance(nested, (Mapping, list, tuple)):
            continue
        _nested_available_ms, nested_reasons = _source_temporal_state(
            payload_name=payload_name,
            payload=nested,
            decision_time=decision_time,
            require_available_at=require_available_at,
            available_at_override=available,
            _seen_ids=seen_ids,
        )
        reasons.extend(nested_reasons)

    unique = tuple(sorted(set(reasons)))
    return (
        int(available.timestamp() * 1000) if available is not None and not unique else None,
        unique,
    )


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical_json_value(item) for item in value), key=repr)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _is_lineage_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered
        in {
            "source",
            "provider",
            "venue",
            "exchange",
            "schema_version",
            "source_hashes",
            "source_ids",
            "source_lineage",
            "source_availability",
            "provenance",
            "lineage",
            "missing_feature_flags",
            "stale_feature_flags",
            "missing_mask",
            "stale_mask",
        }
        or lowered in _SOURCE_CLOCK_FIELDS
        or lowered in _FRESHNESS_FIELDS
        or lowered.endswith(("_hash", "_sha256", "_id", "_at", "_time", "_utc"))
    )


def _lineage_projection(value: Any) -> Any:
    if isinstance(value, Mapping):
        projected = {
            str(key): _canonical_json_value(item)
            for key, item in value.items()
            if _is_lineage_key(str(key))
        }
        return {
            key: projected[key]
            for key in sorted(projected)
        }
    if isinstance(value, (list, tuple)):
        rows = [_lineage_projection(item) for item in value]
        return [row for row in rows if row]
    return None


def _source_lineage_material(payloads: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for payload_name, payload in payloads.items():
        if str(payload_name).startswith("_"):
            continue
        item = _lineage_projection(payload)
        if item:
            projected[str(payload_name)] = item
    keys = payloads.get("_keys")
    if isinstance(keys, Mapping):
        projected["_keys"] = _canonical_json_value(keys)
    return projected


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        _canonical_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _oi_change_pct(open_interest_hist: Any) -> float | None:
    if isinstance(open_interest_hist, Mapping):
        direct = _finite_float(_dig(open_interest_hist, "change_pct", "oi_change_pct"))
        if direct is not None:
            return direct
        return None
    if not isinstance(open_interest_hist, list) or len(open_interest_hist) < 2:
        return None
    first = open_interest_hist[0]
    last = open_interest_hist[-1]
    if not isinstance(first, Mapping) or not isinstance(last, Mapping):
        return None
    first_oi = _finite_float(_first_present(first.get("sumOpenInterest"), first.get("openInterest"), first.get("open_interest")))
    last_oi = _finite_float(_first_present(last.get("sumOpenInterest"), last.get("openInterest"), last.get("open_interest")))
    if first_oi is None or first_oi == 0.0 or last_oi is None:
        return None
    return (last_oi - first_oi) / first_oi


def _best_book_side(orderbook: Any, side: str) -> tuple[float | None, float | None]:
    if not isinstance(orderbook, Mapping):
        return None, None
    price = _finite_float(_dig(orderbook, f"best_{side}", f"{side}_price", side))
    size = _finite_float(_dig(orderbook, f"best_{side}_size", f"{side}_size", f"{side}_qty"))
    rows = orderbook.get(f"{side}s")
    if price is None and isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, Mapping):
            price = _finite_float(_first_present(first.get("price"), first.get("p")))
            size = _finite_float(_first_present(first.get("qty"), first.get("quantity"), first.get("size"), first.get("q")))
        elif isinstance(first, (list, tuple)) and len(first) >= 2:
            price = _finite_float(first[0])
            size = _finite_float(first[1])
    return price, size


def _book_depth_usd(orderbook: Any) -> float | None:
    if not isinstance(orderbook, Mapping):
        return None
    explicit = _finite_float(
        _first_present(
            _dig(orderbook, "orderbook_depth_usd"),
            _dig(orderbook, "depth_total_usd"),
            _dig(orderbook, "depth_usd"),
        )
    )
    if explicit is not None:
        return explicit
    total = 0.0
    seen = False
    for side in ("bid", "ask"):
        rows = orderbook.get(f"{side}s")
        if not isinstance(rows, list):
            continue
        for row in rows[:25]:
            if isinstance(row, Mapping):
                px = _finite_float(_first_present(row.get("price"), row.get("p")))
                qty = _finite_float(_first_present(row.get("qty"), row.get("quantity"), row.get("size"), row.get("q")))
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                px = _finite_float(row[0])
                qty = _finite_float(row[1])
            else:
                px = None
                qty = None
            if px is not None and qty is not None:
                total += px * qty
                seen = True
    return total if seen else None


def _ta_value(*payloads: Any, names: tuple[str, ...]) -> Any:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        indicators = payload.get("indicators") if isinstance(payload.get("indicators"), Mapping) else None
        features = payload.get("features") if isinstance(payload.get("features"), Mapping) else None
        for source in (indicators, features, payload):
            if not isinstance(source, Mapping):
                continue
            for name in names:
                if name in source:
                    return source[name]
    return None


def _coinank_data(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return None
    data: Any = payload.get("data")
    for _ in range(4):
        if isinstance(data, Mapping) and "data" in data and (
            "success" in data or "code" in data or isinstance(data.get("data"), (Mapping, list))
        ):
            data = data.get("data")
            continue
        break
    return data


def _coinank_last_row(payload: Any) -> Any:
    data = _coinank_data(payload)
    if isinstance(data, list) and data:
        return data[-1]
    return data


def _coinank_last_float(payload: Any, names: tuple[str, ...], indexes: tuple[int, ...] = ()) -> float | None:
    row = _coinank_last_row(payload)
    if isinstance(row, Mapping):
        for name in names:
            value = row.get(name)
            if isinstance(value, list) and value:
                parsed = _finite_float(value[-1])
            else:
                parsed = _finite_float(value)
            if parsed is not None:
                return parsed
    if isinstance(row, (list, tuple)):
        for index in indexes:
            if len(row) > index:
                parsed = _finite_float(row[index])
                if parsed is not None:
                    return parsed
    data = _coinank_data(payload)
    if isinstance(data, Mapping):
        for name in names:
            value = data.get(name)
            if isinstance(value, list) and value:
                parsed = _finite_float(value[-1])
            else:
                parsed = _finite_float(value)
            if parsed is not None:
                return parsed
    return None


def _coinank_oi_change_pct(payload: Any) -> float | None:
    data = _coinank_data(payload)
    if not isinstance(data, list) or len(data) < 2:
        return None
    first = data[0]
    last = data[-1]
    if not isinstance(first, Mapping) or not isinstance(last, Mapping):
        return None
    first_oi = _finite_float(_first_present(first.get("coinValue"), first.get("close"), first.get("volume")))
    last_oi = _finite_float(_first_present(last.get("coinValue"), last.get("close"), last.get("volume")))
    if first_oi in (None, 0.0) or last_oi is None:
        return None
    return (last_oi - float(first_oi)) / float(first_oi)


def _coinank_liquidation_turnover(payload: Any) -> float | None:
    row = _coinank_last_row(payload)
    if not isinstance(row, Mapping):
        return None
    long_turn = _finite_float(row.get("longTurnover"))
    short_turn = _finite_float(row.get("shortTurnover"))
    if long_turn is None and short_turn is None:
        return None
    return float(long_turn or 0.0) + float(short_turn or 0.0)


def _coinank_order_flow_imbalance(payload: Any) -> float | None:
    row = _coinank_last_row(payload)
    buy_value: float | None = None
    sell_value: float | None = None
    if isinstance(row, (list, tuple)) and len(row) >= 3:
        buy_value = _finite_float(row[1])
        sell_value = _finite_float(row[2])
    elif isinstance(row, Mapping):
        buy_value = _finite_float(_first_present(row.get("buy"), row.get("buyValue"), row.get("buyCount")))
        sell_value = _finite_float(_first_present(row.get("sell"), row.get("sellValue"), row.get("sellCount")))
    if buy_value is None or sell_value is None:
        return None
    denom = buy_value + sell_value
    if denom <= 0:
        return None
    return (buy_value - sell_value) / denom


class V2UnifiedFeatureTensorBuilder:
    """Assemble model tensors from V2-owned payloads.

    Missing numeric values are represented as ``0.0`` only with
    ``missing_mask[i] == 1``. Staleness is carried independently.
    """

    feature_spec = FEATURE_SPEC

    def build(
        self,
        *,
        symbol: str,
        timeframe: str,
        payloads: Mapping[str, Any],
        decision_time: Any = None,
    ) -> FeatureTensorRecord:
        resolved_decision_time, decision_time_source = _resolve_decision_time(
            payloads,
            decision_time=decision_time,
        )
        decision_time_ms = int(resolved_decision_time.timestamp() * 1000)
        temporal_reasons: list[str] = []
        invalid_source_labels: set[str] = set()
        invalid_payload_names: set[str] = set()
        source_payloads = payloads

        # Validate every mapped feature-bearing payload before any value is
        # selected. Replacing an invalid payload as a unit prevents a value from
        # escaping through a fallback whose static FEATURE_SPEC label names a
        # different source (for example liquidity_zones -> sweep_risk).
        for payload_name, source_labels in _SOURCE_LABELS_BY_PAYLOAD.items():
            if payload_name in {"ohlcv", "orderbook"}:
                continue
            _available_ms, reasons = _source_temporal_state(
                payload_name=payload_name,
                payload=source_payloads.get(payload_name),
                decision_time=resolved_decision_time,
                require_available_at=True,
            )
            if reasons:
                temporal_reasons.extend(reasons)
                invalid_source_labels.update(source_labels)
                invalid_payload_names.add(payload_name)

        raw_provider_features = source_payloads.get("provider_features")
        if isinstance(raw_provider_features, Mapping) and raw_provider_features:
            # Top-level provider_features has no identity-bound source context
            # and is never an admissible bridge, even if it happens to contain
            # numeric values. Only provider_feature_context is read below.
            temporal_reasons.append("PROVIDER_FEATURES_RAW_CONTEXT_REQUIRED")

        validated_payloads = dict(source_payloads)
        for payload_name in invalid_payload_names:
            validated_payloads[payload_name] = {}

        latest = validated_payloads.get("features_latest")
        latest_features = latest.get("features") if isinstance(latest, Mapping) else None

        ohlcv, candle_reasons = _latest_kline(
            source_payloads.get("ohlcv"),
            decision_time_ms=decision_time_ms,
        )
        temporal_reasons.extend(candle_reasons)
        if candle_reasons and not ohlcv:
            invalid_source_labels.add("v2:market:ohlcv")
        _ohlcv_available_ms, ohlcv_clock_reasons = _source_temporal_state(
            payload_name="ohlcv",
            payload=ohlcv,
            decision_time=resolved_decision_time,
            require_available_at=True,
        )
        if ohlcv_clock_reasons:
            temporal_reasons.extend(ohlcv_clock_reasons)
            invalid_source_labels.add("v2:market:ohlcv")
            ohlcv = {}

        raw_orderbook = source_payloads.get("orderbook")
        orderbook_available_override = None
        if (
            isinstance(raw_orderbook, Mapping)
            and isinstance(latest, Mapping)
            and isinstance(latest_features, Mapping)
            and dict(raw_orderbook) == dict(latest_features)
            and isinstance(latest.get("source_hashes"), Mapping)
            and bool(latest.get("source_hashes"))
        ):
            # Durable replay stores the captured feature vector plus aggregate
            # snapshot availability and immutable source hashes. Only that
            # exact value-equal representation may inherit the snapshot clock.
            orderbook_available_override = latest.get("available_at")
        orderbook_available_ms, orderbook_clock_reasons = _source_temporal_state(
            payload_name="orderbook",
            payload=raw_orderbook,
            decision_time=resolved_decision_time,
            require_available_at=True,
            available_at_override=orderbook_available_override,
        )
        if orderbook_clock_reasons:
            temporal_reasons.extend(orderbook_clock_reasons)
            invalid_source_labels.update(
                {"v2:market:orderbook", "v2:orderbook:features"}
            )
            orderbook: Any = {}
        else:
            orderbook = raw_orderbook

        validated_payloads["ohlcv"] = ohlcv
        validated_payloads["orderbook"] = orderbook
        payloads = validated_payloads

        # All references below are derived only from the sanitized payload map.
        latest = payloads.get("features_latest")
        latest_features = latest.get("features") if isinstance(latest, Mapping) else None
        ta = payloads.get("features_ta")
        ta_indicators = ta.get("indicators") if isinstance(ta, Mapping) else None
        ta_full = payloads.get("features_ta_full")
        technical_analysis = payloads.get("technical_analysis")

        micro = payloads.get("microstructure")
        liquidation_levels = payloads.get("liquidation_levels")
        liquidity_zones = payloads.get("liquidity_zones")
        fvg = payloads.get("fvg")
        market_structure = payloads.get("market_structure") or payloads.get("structure")
        sweep_risk_payload = payloads.get("sweep_risk")
        vwap_features = payloads.get("vwap_features")
        volume_profile = payloads.get("volume_profile")
        cvd_features = payloads.get("cvd_features")
        coinank_oi_payload = payloads.get("coinank_open_interest")
        coinank_funding_payload = payloads.get("coinank_funding")
        coinank_long_short_payload = payloads.get("coinank_long_short")
        coinank_liquidations_payload = payloads.get("coinank_liquidations")
        coinank_flow_payload = payloads.get("coinank_market_order_flow")
        microstructure_trust = payloads.get("microstructure_trust")
        trade_tape = payloads.get("trade_tape")
        trade_tape_features = payloads.get("trade_tape_features")
        advanced_trade_tape = payloads.get("advanced_trade_tape") or trade_tape_features
        paper_positions = payloads.get("paper_positions")
        risk = payloads.get("risk_decisions")
        orchestrator = payloads.get("orchestrator_decisions")
        provider_feature_values = _provider_feature_values(payloads)

        # The live payloads for these sources are LISTS of decision/position
        # rows, not dicts with pre-aggregated fields. Derive the spec features
        # from the rows so internally-owned evidence never reads as missing
        # (this alone was ~5% of the data-coverage gap on every tensor).
        def _rows_of(payload):
            if isinstance(payload, list):
                return [row for row in payload if isinstance(row, dict)]
            return []

        def _allow_rate(payload, *action_fields):
            if isinstance(payload, Mapping):
                winners = payload.get("bucket_winners")
                considered = payload.get("considered_count")
                try:
                    if isinstance(winners, list) and considered and float(considered) > 0:
                        return min(1.0, len(winners) / float(considered))
                except (TypeError, ValueError):
                    pass
            rows = _rows_of(payload)[-200:]
            if not rows:
                return None
            allowed = 0
            for row in rows:
                action = ""
                for field in action_fields:
                    if row.get(field) is not None:
                        action = str(row.get(field)).lower()
                        break
                if action in {"allow", "allowed", "true", "pass"} or row.get("allowed") is True:
                    allowed += 1
            return allowed / len(rows)

        _position_rows = [
            row for row in _rows_of(paper_positions)
            if str(row.get("symbol") or "").upper() == str(symbol).upper()
        ]
        derived_position_present = (
            1.0 if _position_rows else (0.0 if isinstance(paper_positions, list) else None)
        )
        derived_unrealized_bps = None
        if _position_rows:
            derived_unrealized_bps = _finite_float(
                _first_present(
                    _position_rows[0].get("unrealized_pnl_bps"),
                    _position_rows[0].get("unrealized_bps"),
                )
            )
        elif isinstance(paper_positions, list):
            derived_unrealized_bps = 0.0
        derived_risk_allow_rate = _allow_rate(risk, "risk_action", "action", "decision")
        derived_orchestrator_allow_rate = _allow_rate(
            orchestrator, "orchestrator_action", "action", "decision"
        )
        symbol_score = payloads.get("symbol_score")
        public_intel = payloads.get("public_intel")
        whale_walls = payloads.get("whale_walls")
        bid_px, bid_qty = _best_book_side(orderbook, "bid")
        ask_px, ask_qty = _best_book_side(orderbook, "ask")
        mid = None if bid_px is None or ask_px is None else (bid_px + ask_px) / 2.0
        spread_bps = None if bid_px is None or ask_px is None or bid_px <= 0 else ((ask_px - bid_px) / bid_px) * 10000.0
        orderbook_update_age_ms = (
            None
            if orderbook_available_ms is None
            else decision_time_ms - orderbook_available_ms
        )
        sequence_gap_raw = _first_present(
            _dig(micro, "sequence_gap_flag", "book_sequence_gap"),
            _dig(orderbook, "sequence_gap_flag"),
            _dig(orderbook, "sequence_gap"),
        )
        sequence_gap_flag = 1.0 if sequence_gap_raw is True or str(sequence_gap_raw).lower() in {"1", "true", "yes"} else 0.0
        book_imbalance = None
        if bid_qty is not None and ask_qty is not None and (bid_qty + ask_qty) > 0:
            book_imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
        ohlcv_volume = _finite_float(_first_present(_dig(ohlcv, "volume", "v"), _dig(latest_features, "volume")))
        quote_volume = _finite_float(
            _first_present(
                _dig(ohlcv, "quote_volume", "quoteVolume", "quote_asset_volume"),
                _dig(payloads.get("prices"), "ticker_24hr.quoteVolume"),
            )
        )
        taker_buy_base = _finite_float(_dig(ohlcv, "taker_buy_base_vol", "takerBuyBaseVolume", "taker_buy_base_asset_volume"))
        taker_buy_quote = _finite_float(_dig(ohlcv, "taker_buy_quote_vol", "takerBuyQuoteVolume", "taker_buy_quote_asset_volume"))
        taker_sell_base = None if ohlcv_volume is None or taker_buy_base is None else max(0.0, ohlcv_volume - taker_buy_base)
        taker_sell_quote = None if quote_volume is None or taker_buy_quote is None else max(0.0, quote_volume - taker_buy_quote)
        taker_buy_ratio = None
        if ohlcv_volume == 0.0 and taker_buy_base == 0.0:
            taker_buy_ratio = 0.0
        elif ohlcv_volume not in (None, 0.0) and taker_buy_base is not None:
            taker_buy_ratio = taker_buy_base / ohlcv_volume
        taker_sell_ratio = None if taker_buy_ratio is None else max(0.0, 1.0 - taker_buy_ratio)
        if ohlcv_volume == 0.0 and taker_buy_base == 0.0:
            taker_sell_ratio = 0.0
        kline_high = _finite_float(_dig(ohlcv, "high", "h"))
        kline_low = _finite_float(_dig(ohlcv, "low", "l"))
        kline_open = _finite_float(_dig(ohlcv, "open", "o"))
        kline_close = _finite_float(_dig(ohlcv, "close", "c"))
        kline_range_pct = None
        if kline_high is not None and kline_low is not None and kline_close not in (None, 0.0):
            kline_range_pct = (kline_high - kline_low) / float(kline_close)
        kline_body_pct = None
        if kline_open is not None and kline_close not in (None, 0.0):
            kline_body_pct = abs(kline_close - kline_open) / float(kline_close)
        mark_price = _finite_float(_dig(payloads.get("prices"), "funding.markPrice", "mark_price", "markPrice"))
        index_price = _finite_float(_dig(payloads.get("prices"), "funding.indexPrice", "index_price", "indexPrice"))
        basis_pct = None
        if mark_price is not None and index_price not in (None, 0.0):
            basis_pct = (mark_price - float(index_price)) / float(index_price)
        oi_change_pct = _oi_change_pct(payloads.get("open_interest_hist"))
        coinank_open_interest = _coinank_last_float(
            coinank_oi_payload,
            ("open_interest", "openInterest", "sumOpenInterest", "coinValue", "close", "volume"),
            (4, 3, 1),
        )
        coinank_oi_change_pct = _coinank_oi_change_pct(coinank_oi_payload)
        coinank_funding_rate = _coinank_last_float(
            coinank_funding_payload,
            ("fundingRate", "fr", "funding_rate", "rate"),
            (1, 2),
        )
        coinank_long_short_ratio = _coinank_last_float(
            coinank_long_short_payload,
            ("longShortRatio", "long_short_ratio", "longRatio", "ratio", "close"),
            (1,),
        )
        coinank_liquidation_turnover = _coinank_liquidation_turnover(coinank_liquidations_payload)
        coinank_order_flow_imbalance = _coinank_order_flow_imbalance(coinank_flow_payload)
        liq_long_distance = _finite_float(_dig(liquidation_levels, "liquidation_long_distance_pct", "long_distance_pct"))
        liq_short_distance = _finite_float(_dig(liquidation_levels, "liquidation_short_distance_pct", "short_distance_pct"))
        liq_long_distance_bps = _finite_float(
            _first_present(
                _dig(liquidation_levels, "distance_to_long_liq_bps", "long_distance_bps"),
                None if liq_long_distance is None else liq_long_distance * 100.0,
            )
        )
        liq_short_distance_bps = _finite_float(
            _first_present(
                _dig(liquidation_levels, "distance_to_short_liq_bps", "short_distance_bps"),
                None if liq_short_distance is None else liq_short_distance * 100.0,
            )
        )
        liq_distance_candidates = [
            value for value in (liq_long_distance, liq_short_distance) if value is not None
        ]
        liq_nearest_distance = min(liq_distance_candidates) if liq_distance_candidates else None
        liq_long_strength = _finite_float(_dig(liquidation_levels, "liquidation_long_strength", "long_strength"))
        liq_short_strength = _finite_float(_dig(liquidation_levels, "liquidation_short_strength", "short_strength"))
        liq_strength_candidates = [
            value for value in (liq_long_strength, liq_short_strength) if value is not None
        ]
        liq_strength = max(liq_strength_candidates) if liq_strength_candidates else None
        # Per-symbol WSS aggregate (count_1h, notional_1h, direction_bias_1h)
        liquidations_agg = payloads.get("liquidations_agg")

        raw_by_name: dict[str, Any] = {
            "last_price": _dig(payloads.get("prices"), "ticker_24hr.lastPrice", "price", "last", "last_price"),
            "mark_price": mark_price,
            "index_price": index_price,
            "basis_pct": _first_present(_dig(payloads.get("prices"), "basis_pct", "funding.basis_pct"), basis_pct),
            "price_last": _dig(payloads.get("prices"), "ticker_24hr.lastPrice", "price", "last", "last_price"),
            "open": _dig(ohlcv, "open", "o"),
            "high": _dig(ohlcv, "high", "h"),
            "low": _dig(ohlcv, "low", "l"),
            "close": _dig(ohlcv, "close", "c"),
            "ohlcv_close": _dig(ohlcv, "close", "c"),
            "volume": ohlcv_volume,
            "ohlcv_volume": ohlcv_volume,
            "quote_volume": quote_volume,
            "num_trades": _dig(ohlcv, "num_trades", "numberOfTrades", "n"),
            "taker_buy_base_vol": taker_buy_base,
            "taker_buy_quote_vol": taker_buy_quote,
            "taker_sell_base_vol": taker_sell_base,
            "taker_sell_quote_vol": taker_sell_quote,
            "taker_buy_ratio": taker_buy_ratio,
            "taker_sell_ratio": taker_sell_ratio,
            "ob_best_bid": bid_px,
            "ob_best_ask": ask_px,
            "ob_mid_price": mid,
            "bid_ask_mid": _first_present(_dig(orderbook, "bid_ask_mid", "mid", "mid_price"), mid),
            "best_bid_size": _first_present(_dig(orderbook, "best_bid_size", "bid_size"), bid_qty),
            "best_ask_size": _first_present(_dig(orderbook, "best_ask_size", "ask_size"), ask_qty),
            "ob_spread_bps": _first_present(_dig(orderbook, "ob_spread_bps", "spread_bps", "bid_ask_spread_bps"), spread_bps),
            "spread_bps": _first_present(_dig(orderbook, "spread_bps", "bid_ask_spread_bps"), spread_bps),
            "ob_imbalance": _first_present(_dig(orderbook, "ob_imbalance", "depth_imbalance"), book_imbalance),
            "orderbook_depth_usd": _book_depth_usd(orderbook),
            "depth_total_usd": _book_depth_usd(orderbook),
            "depth_usd": _book_depth_usd(orderbook),
            "depth_5_bid_usd": _dig(orderbook, "depth_5_bid_usd"),
            "depth_5_ask_usd": _dig(orderbook, "depth_5_ask_usd"),
            "depth_20_bid_usd": _dig(orderbook, "depth_20_bid_usd"),
            "depth_20_ask_usd": _dig(orderbook, "depth_20_ask_usd"),
            "depth_slope": _dig(orderbook, "depth_slope"),
            "estimated_price_impact_bps": _dig(orderbook, "estimated_price_impact_bps", "price_impact_bps"),
            # Recompute age from immutable clocks. A producer-supplied age may
            # have been measured at a different observation time and must not
            # override point-in-time evidence here.
            "update_age_ms": orderbook_update_age_ms,
            "sequence_gap_flag": sequence_gap_flag,
            "source_latency_ms": _dig(orderbook, "source_latency_ms"),
            "microstructure_trust_score": _first_present(
                _dig(micro, "microstructure_trust_score", "orderbook_trust_score"),
                _dig(microstructure_trust, "composite_trust_score", "trust_score", "microstructure_trust_score"),
                _dig(latest_features, "microstructure_trust_score"),
            ),
            "feed_latency_ms": _dig(micro, "feed_latency_ms", "orderbook_latency_ms", "latency_ms", "local_latency_ms"),
            "spread_instability": _dig(micro, "spread_instability", "spread_expansion_rate"),
            "depth_persistence": _dig(micro, "depth_persistence", "book_depth_persistence_score", "depth_persistence_ms"),
            "cancel_pressure": _dig(micro, "cancel_pressure", "book_cancel_pressure_score", "cancel_burst_score"),
            "book_trade_divergence": _dig(micro, "book_trade_divergence", "book_trade_divergence_score"),
            "cross_venue_confirmation": _dig(micro, "cross_venue_confirmation", "cross_venue_confirmation_score"),
            "sweep_risk": _first_present(
                _dig(micro, "sweep_risk", "sweep_risk_score"),
                _dig(liquidity_zones, "liquidity_sweep_risk"),
                _dig(latest_features, "sweep_risk", "liquidity_sweep_risk"),
            ),
            "post_sweep_reversal_probability": _dig(micro, "post_sweep_reversal_probability"),
            "realized_slippage_error": _dig(micro, "realized_slippage_error", "realized_slippage_error_bps"),
            "depth_vs_tape_divergence": _first_present(
                _dig(micro, "depth_vs_tape_divergence"),
                _dig(trade_tape, "book_trade_divergence_score"),
                _dig(latest_features, "depth_vs_tape_divergence", "book_trade_divergence_score"),
            ),
            "orderbook_spread_bps": _first_present(_dig(orderbook, "spread_bps", "bid_ask_spread_bps"), spread_bps),
            "orderbook_depth_imbalance": _first_present(_dig(orderbook, "depth_imbalance"), book_imbalance),
            "funding_rate": _first_present(
                _dig(payloads.get("funding"), "funding_rate", "rate", "fundingRate", "lastFundingRate"),
                coinank_funding_rate,
            ),
            "open_interest": _first_present(
                _dig(payloads.get("open_interest"), "open_interest", "oi", "openInterest", "sumOpenInterest"),
                coinank_open_interest,
            ),
            "oi_change_pct": _first_present(
                _dig(payloads.get("open_interest_hist"), "change_pct", "oi_change_pct"),
                oi_change_pct,
                coinank_oi_change_pct,
            ),
            "long_short_ratio": _first_present(
                _dig(payloads.get("long_short"), "long_short_ratio", "longShortRatio"),
                _dig(latest_features, "long_short_ratio"),
                coinank_long_short_ratio,
            ),
            "long_account_ratio": _first_present(
                _dig(payloads.get("long_short"), "long_account_ratio", "longAccount"),
                _dig(latest_features, "long_account_ratio"),
            ),
            "short_account_ratio": _first_present(
                _dig(payloads.get("long_short"), "short_account_ratio", "shortAccount"),
                _dig(latest_features, "short_account_ratio"),
            ),
            "open_interest_change_pct": _first_present(
                _dig(payloads.get("open_interest_hist"), "change_pct", "oi_change_pct"),
                oi_change_pct,
                coinank_oi_change_pct,
            ),
            "volatility": _first_present(
                _dig(latest_features, "volatility", "ccxt_volatility_1m", "ccxt_volatility", "true_range_pct"),
                kline_range_pct,
            ),
            "volatility_pct": _first_present(
                _dig(latest_features, "volatility_pct", "true_range_pct", "range_pct"),
                kline_range_pct,
            ),
            "RSI": _ta_value(latest, ta, ta_full, technical_analysis, names=("RSI", "rsi_14", "ta_RSI_14", "ta_RSI")),
            "MACD": _ta_value(latest, ta, ta_full, technical_analysis, names=("MACD", "macd", "ta_MACD_12_26_9_macd", "ta_MACD_macd")),
            "MACD_signal": _ta_value(latest, ta, ta_full, technical_analysis, names=("MACD_signal", "macd_signal", "ta_MACD_12_26_9_signal", "ta_MACD_macdsignal")),
            "MACD_hist": _ta_value(latest, ta, ta_full, technical_analysis, names=("MACD_hist", "macd_hist", "ta_MACD_12_26_9_hist", "ta_MACD_macdhist")),
            "ATR": _ta_value(latest, ta, ta_full, technical_analysis, names=("ATR", "atr_14", "ta_ATR_14", "ta_ATR")),
            "EMA_12": _ta_value(latest, ta, ta_full, technical_analysis, names=("EMA_12", "ema_12", "ta_EMA_12")),
            "EMA_26": _ta_value(latest, ta, ta_full, technical_analysis, names=("EMA_26", "ema_26", "ta_EMA_26")),
            "bollinger_upper": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_upper", "bb_upper", "ta_BBANDS_20_upper", "ta_BBANDS_upperband")),
            "bollinger_middle": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_middle", "bb_middle", "ta_BBANDS_20_middle", "ta_BBANDS_middleband")),
            "bollinger_lower": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_lower", "bb_lower", "ta_BBANDS_20_lower", "ta_BBANDS_lowerband")),
            "bollinger_width_pct": _ta_value(latest, ta, ta_full, technical_analysis, names=("bollinger_width_pct", "bb_width_pct", "bb_width")),
            "liquidation_count_5m": _first_present(
                _dig(liquidation_levels, "liquidation_count_5m"),
                _dig(payloads.get("liquidations"), "count_5m", "event_count"),
                None if coinank_liquidation_turnover is None else (1.0 if coinank_liquidation_turnover > 0 else 0.0),
            ),
            "liquidation_long_level": _dig(liquidation_levels, "long_level", "liquidation_long_level"),
            "liquidation_short_level": _dig(liquidation_levels, "short_level", "liquidation_short_level"),
            "nearest_liquidation_level_above": _first_present(
                _dig(liquidation_levels, "nearest_liquidation_level_above", "level_above"),
            ),
            "nearest_liquidation_level_below": _first_present(
                _dig(liquidation_levels, "nearest_liquidation_level_below", "level_below"),
            ),
            "distance_to_long_liq_bps": liq_long_distance_bps,
            "distance_to_short_liq_bps": liq_short_distance_bps,
            "liquidation_cluster_strength_long": _first_present(
                _dig(liquidation_levels, "liquidation_cluster_strength_long", "long_cluster_strength"),
                liq_long_strength,
            ),
            "liquidation_cluster_strength_short": _first_present(
                _dig(liquidation_levels, "liquidation_cluster_strength_short", "short_cluster_strength"),
                liq_short_strength,
            ),
            "liquidation_distance_pct": _first_present(
                _dig(liquidation_levels, "distance_pct", "liquidation_distance_pct"),
                liq_nearest_distance,
            ),
            "liquidation_strength": _first_present(
                _dig(liquidation_levels, "strength", "liquidation_strength"),
                liq_strength,
            ),
            "liquidation_cascade_risk": _first_present(
                _dig(micro, "liquidation_cascade_risk", "cascade_risk"),
                _dig(liquidation_levels, "liquidation_cascade_risk", "cascade_risk"),
            ),
            "liquidation_pressure_direction": _first_present(
                _dig(liquidation_levels, "liquidation_pressure_direction", "pressure_direction"),
            ),
            "liquidation_sweep_target_long": _dig(liquidation_levels, "liquidation_sweep_target_long", "sweep_target_long"),
            "liquidation_sweep_target_short": _dig(liquidation_levels, "liquidation_sweep_target_short", "sweep_target_short"),
            "liquidation_sweep_target_long_distance_bps": _dig(liquidation_levels, "liquidation_sweep_target_long_distance_bps", "sweep_long_dist_bps"),
            "liquidation_sweep_target_short_distance_bps": _dig(liquidation_levels, "liquidation_sweep_target_short_distance_bps", "sweep_short_dist_bps"),
            "liquidation_zones_long_count": _dig(liquidation_levels, "liquidation_zones_count_long", "zones_count_long"),
            "liquidation_zones_short_count": _dig(liquidation_levels, "liquidation_zones_count_short", "zones_count_short"),
            "liquidation_count_1h": _dig(liquidations_agg, "count_1h"),
            "liquidation_notional_1h": _dig(liquidations_agg, "notional_1h"),
            "liquidation_direction_bias_1h": _dig(liquidations_agg, "direction_bias_1h"),
            "liquidity_zone_above": _dig(liquidity_zones, "liquidity_zone_above", "nearest_liquidity_zone_above", "zone_above"),
            "liquidity_zone_below": _dig(liquidity_zones, "liquidity_zone_below", "nearest_liquidity_zone_below", "zone_below"),
            "distance_to_liquidity_zone_bps": _dig(liquidity_zones, "distance_to_liquidity_zone_bps", "liquidity_distance_bps"),
            "bullish_fvg_present": bool_num(_dig(fvg, "bullish_fvg_present")),
            "bearish_fvg_present": bool_num(_dig(fvg, "bearish_fvg_present")),
            "fvg_size_bps": _dig(fvg, "fvg_size_bps"),
            "distance_to_fvg_bps": _dig(fvg, "distance_to_fvg_bps"),
            "fvg_fill_percent": _dig(fvg, "fvg_fill_percent"),
            "fvg_age_candles": _dig(fvg, "fvg_age_candles"),
            "fvg_retest_confirmed": bool_num(_dig(fvg, "fvg_retest_confirmed")),
            "htf_fvg_alignment": bool_num(_dig(fvg, "htf_fvg_alignment")),
            "fvg_liquidity_confluence": bool_num(_dig(fvg, "fvg_liquidity_confluence")),
            "fvg_orderbook_trust_confluence": _dig(fvg, "fvg_orderbook_trust_confluence"),
            "fvg_trade_tape_confirmation": _dig(fvg, "fvg_trade_tape_confirmation"),
            "fvg_expected_edge_after_cost": _dig(fvg, "fvg_expected_edge_after_cost"),
            "bos_direction_code": _first_present(
                _dig(market_structure, "bos_direction_code"),
                direction_code(_dig(market_structure, "bos_direction")),
            ),
            "choch_direction_code": _first_present(
                _dig(market_structure, "choch_direction_code"),
                direction_code(_dig(market_structure, "choch_direction")),
            ),
            "order_block_strength": _dig(market_structure, "order_block_strength"),
            "breaker_block_active": bool_num(_dig(market_structure, "breaker_block_active")),
            "mitigation_block_active": bool_num(_dig(market_structure, "mitigation_block_active")),
            "equal_highs_distance_bps": _dig(market_structure, "equal_highs_distance_bps"),
            "equal_lows_distance_bps": _dig(market_structure, "equal_lows_distance_bps"),
            "premium_discount_zone_code": _first_present(
                _dig(market_structure, "premium_discount_zone_code"),
                zone_code(_dig(market_structure, "premium_discount_zone")),
            ),
            "session_high_sweep": bool_num(_dig(market_structure, "session_high_sweep")),
            "session_low_sweep": bool_num(_dig(market_structure, "session_low_sweep")),
            "structure_trend_state_code": _first_present(
                _dig(market_structure, "structure_trend_state_code"),
                direction_code(_dig(market_structure, "structure_trend_state")),
            ),
            "nearest_liquidity_above": _dig(liquidity_zones, "nearest_liquidity_above", "nearest_liquidity_zone_above"),
            "nearest_liquidity_below": _dig(liquidity_zones, "nearest_liquidity_below", "nearest_liquidity_zone_below"),
            "distance_to_liquidity_above_bps": _dig(liquidity_zones, "distance_to_liquidity_above_bps", "distance_to_zone_above_bps"),
            "distance_to_liquidity_below_bps": _dig(liquidity_zones, "distance_to_liquidity_below_bps", "distance_to_zone_below_bps"),
            "liquidity_zone_strength": _dig(liquidity_zones, "liquidity_zone_strength"),
            "sweep_risk_long_side": _first_present(
                _dig(sweep_risk_payload, "sweep_risk_long_side"),
                _dig(liquidity_zones, "sweep_risk_long_side"),
            ),
            "sweep_risk_short_side": _first_present(
                _dig(sweep_risk_payload, "sweep_risk_short_side"),
                _dig(liquidity_zones, "sweep_risk_short_side"),
            ),
            "fake_breakout_risk": _first_present(
                _dig(sweep_risk_payload, "fake_breakout_risk"),
                _dig(liquidity_zones, "fake_breakout_risk"),
            ),
            "fake_breakdown_risk": _first_present(
                _dig(sweep_risk_payload, "fake_breakdown_risk"),
                _dig(liquidity_zones, "fake_breakdown_risk"),
            ),
            "cascade_continuation_probability": _first_present(
                _dig(sweep_risk_payload, "cascade_continuation_probability"),
                _dig(liquidity_zones, "cascade_continuation_probability"),
            ),
            "session_vwap": _dig(vwap_features, "session_vwap"),
            "anchored_vwap": _dig(vwap_features, "anchored_vwap"),
            "distance_to_vwap_bps": _dig(vwap_features, "distance_to_vwap_bps"),
            "vwap_slope": _dig(vwap_features, "vwap_slope"),
            "volume_profile_poc": _dig(volume_profile, "volume_profile_poc"),
            "high_volume_node_above": _dig(volume_profile, "high_volume_node_above"),
            "high_volume_node_below": _dig(volume_profile, "high_volume_node_below"),
            "low_volume_node_above": _dig(volume_profile, "low_volume_node_above"),
            "low_volume_node_below": _dig(volume_profile, "low_volume_node_below"),
            "cvd": _dig(cvd_features, "cvd"),
            "cvd_slope": _dig(cvd_features, "cvd_slope"),
            "cvd_divergence": _dig(cvd_features, "cvd_divergence"),
            "trade_imbalance": _first_present(
                _dig(advanced_trade_tape, "trade_imbalance"),
                _dig(trade_tape, "trade_imbalance"),
            ),
            "large_trade_cluster": _first_present(
                _dig(advanced_trade_tape, "large_trade_cluster"),
                _dig(trade_tape, "large_trade_cluster"),
                _dig(advanced_trade_tape, "large_trade_count_5m"),
            ),
            "sweep_prints": _first_present(
                _dig(advanced_trade_tape, "sweep_prints"),
                _dig(trade_tape, "sweep_prints"),
                _dig(liquidity_zones, "sweep_prints"),
            ),
            "orderbook_wall_strength": _first_present(
                _dig(orderbook, "orderbook_wall_strength", "wall_strength"),
                _dig(whale_walls, "whale_wall_strength", "whale_wall_score"),
            ),
            "microstructure_liquidity_depth": _first_present(
                _dig(micro, "microstructure_liquidity_depth", "liquidity_depth", "depth_usd"),
                _book_depth_usd(orderbook),
            ),
            "coinapi_wsds_tape_imbalance": _first_present(
                _dig(micro, "coinapi_wsds_tape_imbalance", "wsds_tape_imbalance"),
                coinank_order_flow_imbalance,
            ),
            "last_liq_bps_24h": _first_present(
                _dig(payloads.get("liquidations"), "last_liq_bps_24h", "liq_bps_24h"),
                _dig(latest_features, "last_liq_bps_24h"),
                _dig(liquidation_levels, "last_liq_bps_proxy"),
                coinank_liquidation_turnover,
            ),
            "liquidation_is_stale": _dig(liquidation_levels, "is_stale", "liquidation_is_stale"),
            "liquidation_level_distance_bps": _first_present(
                _dig(liquidation_levels, "nearest_distance_bps"),
                None if liq_nearest_distance is None else liq_nearest_distance * 100.0,
            ),
            "microprice": _dig(micro, "microprice", "micro_price"),
            "spread": _first_present(_dig(orderbook, "spread", "spread_bps"), spread_bps),
            "micro_volatility": _first_present(
                _dig(micro, "volatility", "micro_volatility"),
                _dig(latest_features, "micro_volatility"),
                kline_range_pct,
            ),
            "toxicity_proxy": _first_present(
                _dig(micro, "toxicity_proxy"),
                None if _finite_float(_dig(micro, "imbalance_5")) is None else abs(float(_dig(micro, "imbalance_5"))),
            ),
            "tape_imbalance": _first_present(
                _dig(micro, "tape_imbalance"),
                _dig(trade_tape, "trade_imbalance"),
                _dig(trade_tape_features, "tape_imbalance_5m"),
                _dig(latest_features, "tape_imbalance", "trade_imbalance"),
                coinank_order_flow_imbalance,
            ),
            "order_flow_imbalance": _first_present(
                _dig(micro, "order_flow_imbalance", "ofi"),
                _dig(trade_tape, "trade_imbalance"),
                _dig(trade_tape_features, "per_minute_delta_5m"),
                coinank_order_flow_imbalance,
            ),
            "paper_position_present": _first_present(
                _dig(paper_positions, "position_present", "paper_position_present"),
                derived_position_present,
            ),
            "paper_unrealized_bps": _first_present(
                _dig(paper_positions, "unrealized_bps", "paper_unrealized_bps"),
                derived_unrealized_bps,
            ),
            "risk_recent_allow_rate": _first_present(
                _dig(risk, "recent_allow_rate", "allow_rate"),
                derived_risk_allow_rate,
            ),
            "orchestrator_recent_allow_rate": _first_present(
                _dig(orchestrator, "recent_allow_rate", "allow_rate"),
                derived_orchestrator_allow_rate,
            ),
            "altdata_symbol_score": _dig(symbol_score, "altdata_symbol_score"),
            "provider_availability_score": _dig(symbol_score, "provider_availability_score"),
            "altdata_freshness_score": _dig(symbol_score, "altdata_freshness_score"),
            "coingecko_discovery_score": _dig(symbol_score, "coingecko_discovery_score"),
            "coingecko_liquidity_score": _dig(symbol_score, "coingecko_liquidity_score"),
            "coingecko_momentum_score": _dig(symbol_score, "coingecko_momentum_score"),
            "surf_market_price_signal_score": _dig(symbol_score, "surf_market_price_signal_score"),
            "coinglass_derivatives_score": _dig(symbol_score, "coinglass_derivatives_score"),
            "public_intel_score": _first_present(_dig(public_intel, "score", "public_intel_score"), _dig(symbol_score, "public_intel_score")),
            "defillama_liquidity_score": _first_present(_dig(public_intel, "defillama_liquidity_score"), _dig(symbol_score, "defillama_liquidity_score")),
            "defillama_tvl_momentum_score": _first_present(_dig(public_intel, "defillama_tvl_momentum_score"), _dig(symbol_score, "defillama_tvl_momentum_score")),
            "news_attention_score": _first_present(_dig(public_intel, "news_attention_score"), _dig(symbol_score, "news_attention_score")),
            "news_sentiment_score": _first_present(_dig(public_intel, "news_sentiment_score"), _dig(symbol_score, "news_sentiment_score")),
            "fear_greed_score": _first_present(_dig(public_intel, "fear_greed_score"), _dig(symbol_score, "fear_greed_score")),
            "btc_mempool_pressure_score": _first_present(_dig(public_intel, "btc_mempool_pressure_score"), _dig(symbol_score, "btc_mempool_pressure_score")),
            "whale_wall_score": _first_present(_dig(whale_walls, "whale_wall_score"), _dig(symbol_score, "whale_wall_score")),
            "whale_bid_pressure_score": _first_present(_dig(whale_walls, "whale_bid_pressure_score"), _dig(symbol_score, "whale_bid_pressure_score")),
            "whale_ask_pressure_score": _first_present(_dig(whale_walls, "whale_ask_pressure_score"), _dig(symbol_score, "whale_ask_pressure_score")),
            "whale_wall_imbalance_score": _first_present(_dig(whale_walls, "whale_wall_imbalance_score"), _dig(symbol_score, "whale_wall_imbalance_score")),
            "whale_wall_count_score": _first_present(_dig(whale_walls, "whale_wall_count_score"), _dig(symbol_score, "whale_wall_count_score")),
            "whale_wall_event_count": _first_present(_dig(whale_walls, "whale_wall_event_count"), _dig(symbol_score, "whale_wall_event_count")),
            "whale_bid_wall_notional_usd": _first_present(_dig(whale_walls, "whale_bid_wall_notional_usd"), _dig(symbol_score, "whale_bid_wall_notional_usd")),
            "whale_ask_wall_notional_usd": _first_present(_dig(whale_walls, "whale_ask_wall_notional_usd"), _dig(symbol_score, "whale_ask_wall_notional_usd")),
            "whale_total_wall_notional_usd": _first_present(_dig(whale_walls, "whale_total_wall_notional_usd"), _dig(symbol_score, "whale_total_wall_notional_usd")),
            "nearest_bid_wall_distance_bps": _first_present(_dig(whale_walls, "nearest_bid_wall_distance_bps"), _dig(symbol_score, "nearest_bid_wall_distance_bps")),
            "nearest_ask_wall_distance_bps": _first_present(_dig(whale_walls, "nearest_ask_wall_distance_bps"), _dig(symbol_score, "nearest_ask_wall_distance_bps")),
            "coingecko_score": _first_present(_dig(symbol_score, "coingecko_score"), _dig(symbol_score, "coingecko_discovery_score")),
            "surf_score": _first_present(_dig(symbol_score, "surf_score"), _dig(symbol_score, "surf_market_price_signal_score")),
            "defillama_score": _first_present(_dig(public_intel, "defillama_score"), _dig(public_intel, "defillama_liquidity_score"), _dig(symbol_score, "defillama_score")),
            "fear_greed_context": _first_present(_dig(public_intel, "fear_greed_context"), _dig(public_intel, "fear_greed_score"), _dig(symbol_score, "fear_greed_score")),
            "mempool_context": _first_present(_dig(public_intel, "mempool_context"), _dig(public_intel, "btc_mempool_pressure_score"), _dig(symbol_score, "btc_mempool_pressure_score")),
        }
        for name, _source in FEATURE_SPEC:
            if name in raw_by_name:
                continue
            raw_by_name[name] = _first_present(
                _dig(latest_features, name),
                _dig(latest, name),
                _dig(ta_indicators, name),
            )
        # WI feature-expansion: populate the taf_* TA features from the full TA-Lib
        # payload (v2:features:ta_full, already computed by v2_full_talib_ta_loop) via
        # the taf_->indicator name map. A missing indicator stays None -> honest
        # missing_mask, exactly like every other source.
        cascade_ctx = payloads.get("cascade_context")
        if isinstance(cascade_ctx, Mapping):
            _sq_dir = str(cascade_ctx.get("fast_squeeze_squeeze_direction") or "").lower()
            for _cc_name, _cc_val in (
                ("cascade_risk_score", cascade_ctx.get("cascade_risk_score")),
                ("cascade_event_component", cascade_ctx.get("cascade_event_component")),
                (
                    "cascade_level_proximity_component",
                    cascade_ctx.get("liquidation_level_proximity_component"),
                ),
                ("fast_squeeze_probability", cascade_ctx.get("fast_squeeze_squeeze_probability")),
                ("fast_squeeze_trap_score", cascade_ctx.get("fast_squeeze_market_maker_trap_score")),
                ("fast_squeeze_direction_code", {"up": 1.0, "down": -1.0}.get(_sq_dir)),
                ("cross_asset_lead_component", cascade_ctx.get("cross_asset_component")),
            ):
                if _cc_val is not None and raw_by_name.get(_cc_name) is None:
                    raw_by_name[_cc_name] = _cc_val
        htf1h = payloads.get("ta_full_htf_1h")
        htf1h_ind = None
        if isinstance(htf1h, Mapping):
            htf1h_ind = htf1h.get("indicators") or htf1h.get("features")
        if isinstance(htf1h_ind, Mapping):
            for _h_name, _h_keys in (
                ("htf1h_taf_rsi", ("rsi_14", "ta_RSI")),
                ("htf1h_taf_adx", ("ta_ADX",)),
                ("htf1h_taf_macd_hist", ("macd_hist", "ta_MACD_macdhist")),
                ("htf1h_taf_atr", ("atr_14", "ta_ATR")),
                ("htf1h_taf_mfi", ("ta_MFI",)),
                ("htf1h_taf_willr", ("ta_WILLR",)),
                ("htf1h_taf_natr", ("ta_NATR",)),
                ("htf1h_taf_cci", ("ta_CCI",)),
            ):
                if raw_by_name.get(_h_name) is None:
                    for _hk in _h_keys:
                        if htf1h_ind.get(_hk) is not None:
                            raw_by_name[_h_name] = htf1h_ind.get(_hk)
                            break
        micro_trust_payload = payloads.get("microstructure_trust")
        if isinstance(micro_trust_payload, Mapping):
            for _m_name, _m_key in (
                ("micro_cancel_pressure_score", "book_cancel_pressure_score"),
                ("micro_depth_persistence_score", "book_depth_persistence_score"),
                ("micro_book_trade_divergence", "book_trade_divergence"),
                ("micro_book_sequence_gap", "book_sequence_gap"),
            ):
                if raw_by_name.get(_m_name) is None and micro_trust_payload.get(_m_key) is not None:
                    raw_by_name[_m_name] = micro_trust_payload.get(_m_key)
        ta_full_indicators = None
        if isinstance(ta_full, Mapping):
            # Real talib payload nests values under "indicators"; the synthetic
            # loader path nests them under "features".
            ta_full_indicators = ta_full.get("indicators") or ta_full.get("features")
        if isinstance(ta_full_indicators, Mapping):
            for taf_name, indicator_name in TA_FULL_FEATURE_MAP.items():
                if raw_by_name.get(taf_name) is None:
                    raw_by_name[taf_name] = ta_full_indicators.get(indicator_name)
        raw_by_name["bid_ask_spread_bps"] = _first_present(
            raw_by_name["bid_ask_spread_bps"],
            raw_by_name["orderbook_spread_bps"],
        )
        raw_by_name["depth_imbalance"] = _first_present(
            raw_by_name["depth_imbalance"],
            raw_by_name["orderbook_depth_imbalance"],
        )
        raw_by_name["micro_price"] = _first_present(
            raw_by_name["micro_price"],
            _dig(micro, "micro_price"),
        )
        raw_by_name["toxicity_proxy"] = _first_present(
            raw_by_name["toxicity_proxy"],
            _dig(latest_features, "toxicity_proxy"),
            _dig(micro, "toxicity_proxy"),
        )
        if raw_by_name.get("range_pct") is None:
            raw_by_name["range_pct"] = kline_range_pct
        if raw_by_name.get("body_pct") is None:
            raw_by_name["body_pct"] = kline_body_pct
        if raw_by_name.get("true_range_pct") is None:
            raw_by_name["true_range_pct"] = kline_range_pct
        if raw_by_name.get("ret_pct") is None and kline_open not in (None, 0.0) and kline_close is not None:
            raw_by_name["ret_pct"] = (kline_close - float(kline_open)) / float(kline_open)
        if raw_by_name.get("log_return") is None and kline_open not in (None, 0.0) and kline_close not in (None, 0.0):
            raw_by_name["log_return"] = math.log(float(kline_close) / float(kline_open))

        feature_spec_names = {field_name for field_name, _source in FEATURE_SPEC}
        provider_sources: dict[str, str] = {}
        for name, value in provider_feature_values.items():
            if name not in feature_spec_names:
                continue
            if raw_by_name.get(name) is None:
                raw_by_name[name] = value
                provider_sources[name] = "provider_feature_bridge"

        # Alt-data bridge payloads (Moralis wallet intelligence + confluence
        # engine scores) publish {"features": {...}} with explicit masks; a
        # None value stays missing here so the mask channels stay honest.
        for bridge_label, bridge_payload in (
            ("v2:features:moralis", payloads.get("moralis_features")),
            ("v2:smart_money:signals", payloads.get("smart_money_signals")),
            ("v2:altdata:confluence", payloads.get("altdata_confluence")),
        ):
            bridge_features = (
                bridge_payload.get("features") if isinstance(bridge_payload, Mapping) else None
            )
            if not isinstance(bridge_features, Mapping):
                continue
            for bridge_name, bridge_value in bridge_features.items():
                name = str(bridge_name)
                if name not in feature_spec_names:
                    continue
                parsed = _finite_float(bridge_value)
                if parsed is not None and raw_by_name.get(name) is None:
                    raw_by_name[name] = parsed
                    provider_sources[name] = bridge_label

        coinank_sources: dict[str, str] = {}
        if coinank_funding_rate is not None and _dig(payloads.get("funding"), "funding_rate", "rate", "fundingRate", "lastFundingRate") is None:
            coinank_sources["funding_rate"] = "latest:coinank:funding"
        if coinank_open_interest is not None and _dig(payloads.get("open_interest"), "open_interest", "oi", "openInterest", "sumOpenInterest") is None:
            coinank_sources["open_interest"] = "latest:coinank:open_interest"
        if coinank_oi_change_pct is not None and _dig(payloads.get("open_interest_hist"), "change_pct", "oi_change_pct") is None and oi_change_pct is None:
            coinank_sources["oi_change_pct"] = "latest:coinank:open_interest"
            coinank_sources["open_interest_change_pct"] = "latest:coinank:open_interest"
        if coinank_long_short_ratio is not None and _dig(payloads.get("long_short"), "long_short_ratio", "longShortRatio") is None and _dig(latest_features, "long_short_ratio") is None:
            coinank_sources["long_short_ratio"] = "latest:coinank:long_short"
        if coinank_liquidation_turnover is not None:
            if _dig(payloads.get("liquidations"), "count_5m", "event_count") is None:
                coinank_sources["liquidation_count_5m"] = "latest:coinank:liquidations"
            if _dig(payloads.get("liquidations"), "last_liq_bps_24h", "liq_bps_24h") is None and _dig(latest_features, "last_liq_bps_24h") is None:
                coinank_sources["last_liq_bps_24h"] = "latest:coinank:liquidations"
        if coinank_order_flow_imbalance is not None:
            if _dig(micro, "tape_imbalance") is None:
                coinank_sources["tape_imbalance"] = "latest:coinank:market_order_flow"
            if _dig(micro, "order_flow_imbalance", "ofi") is None:
                coinank_sources["order_flow_imbalance"] = "latest:coinank:market_order_flow"

        stale_input_flags = set()
        for payload in payloads.values():
            if isinstance(payload, Mapping):
                for flag in payload.get("stale_feature_flags") or payload.get("stale_flags") or ():
                    stale_input_flags.add(str(flag))
        latest_stale_state = str(_dig(latest, "feature_freshness_state", "freshness_state") or "").upper()
        latest_not_current = bool(latest_stale_state and latest_stale_state != "CURRENT")

        values: list[float] = []
        missing_mask: list[int] = []
        stale_mask: list[int] = []
        source_availability: list[int] = []
        missing_names: list[str] = []
        stale_names: list[str] = []
        resolved_source_labels = tuple(
            coinank_sources.get(name)
            or provider_sources.get(name)
            or source
            for name, source in FEATURE_SPEC
        )
        for (name, _source), resolved_source in zip(
            FEATURE_SPEC,
            resolved_source_labels,
            strict=True,
        ):
            val = _finite_float(raw_by_name.get(name))
            temporal_invalid = resolved_source in invalid_source_labels
            missing = val is None or temporal_invalid
            stale = name in stale_input_flags or latest_not_current or temporal_invalid
            values.append(0.0 if missing else float(val))
            missing_mask.append(1 if missing else 0)
            stale_mask.append(1 if stale else 0)
            source_availability.append(0 if missing else 1)
            if missing:
                missing_names.append(name)
            if stale:
                stale_names.append(name)

        available = len(values) - sum(missing_mask)
        coverage = 100.0 * available / max(1, len(values))
        snapshot_id = str(
            _dig(latest, "feature_snapshot_id")
            or _dig(ta, "feature_snapshot_id")
            or f"{symbol}:{timeframe}:no_feature_snapshot"
        )
        normalized_temporal_reasons = tuple(sorted(set(temporal_reasons)))
        source_lineage_material = {
            "schema_version": "v2_feature_tensor_lineage_v2",
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "feature_snapshot_id": snapshot_id,
            "decision_time": _iso_utc(resolved_decision_time),
            "decision_time_source": decision_time_source,
            "source_labels": resolved_source_labels,
            "source_payload_provenance": _source_lineage_material(source_payloads),
            "temporal_rejection_reasons": normalized_temporal_reasons,
        }
        source_lineage_hash = _sha256_json(source_lineage_material)
        tensor_id = "v2_hybrid_tensor_" + _sha256_json(
            {
                "schema_version": "v2_feature_tensor_identity_v2",
                "symbol": str(symbol),
                "timeframe": str(timeframe),
                "feature_snapshot_id": snapshot_id,
                "values": values,
                "missing_mask": missing_mask,
                "stale_mask": stale_mask,
                "source_availability": source_availability,
                "source_lineage_hash": source_lineage_hash,
            }
        )[:32]
        return FeatureTensorRecord(
            tensor_id=tensor_id,
            symbol=symbol,
            timeframe=timeframe,
            feature_snapshot_id=snapshot_id,
            values=tuple(values),
            missing_mask=tuple(missing_mask),
            stale_mask=tuple(stale_mask),
            source_availability=tuple(source_availability),
            feature_names=tuple(name for name, _ in FEATURE_SPEC),
            source_labels=resolved_source_labels,
            missing_feature_names=tuple(missing_names),
            stale_feature_names=tuple(stale_names),
            data_coverage_percent=float(coverage),
            source_availability_vector=tuple(source_availability),
            decision_time=_iso_utc(resolved_decision_time),
            source_lineage_hash=source_lineage_hash,
            temporal_rejection_reasons=normalized_temporal_reasons,
        )
