"""Point-in-time trusted replay row construction.

Replay rows are outcome-supervised examples built from archived feature
snapshots and later finalized candles. They are intentionally not PPO rows.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_candle_id,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    content_sha256 as archive_content_sha256,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mValidationError,
    validate_canonical_finalized_5m_candle,
)


HORIZON_SECONDS: dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}
TRUSTED_REPLAY_LABEL_BASE_TIMEFRAME = "5m"
TRUSTED_REPLAY_LABEL_BASE_MILLISECONDS = 5 * 60 * 1000
TRUSTED_REPLAY_LABEL_CANDLE_CONTRACT_VERSION = (
    "v2_trusted_replay_canonical_finalized_5m_label_path_v2"
)
TRUSTED_REPLAY_LABEL_CANDLE_SOURCE_KEY_TEMPLATE = (
    "v2:market:ohlcv_closed:binance:{symbol}:5m"
)
TRUSTED_REPLAY_LABEL_CANDLE_SOURCES = frozenset(
    {
        "binance_wss",
        "binance_rest",
        "v2_closed_candle_resampler:1m",
    }
)
FUTURE_LABEL_PREFIXES = (
    "future_return",
    "future_",
    "label_",
    "target_",
    "realized_",
)
PIT_SAFE_REALIZED_FEATURES = {"realized_slippage_error"}
TRUSTED_REPLAY_COST_EVIDENCE_SCHEMA_VERSION = (
    "v2_trusted_replay_pit_cost_evidence_v1"
)
TRUSTED_REPLAY_LABEL_POLICY_VERSION = (
    "v2_trusted_replay_adaptive_after_cost_action_v1"
)
TRUSTED_REPLAY_COUNTERFACTUAL_ECONOMICS_SCHEMA_VERSION = (
    "v2_trusted_replay_standardized_counterfactual_economics_v1"
)
# These are evidence aliases, not fallback values.  A replay row is rejected
# unless one explicit, finite field exists for every component in the archived
# decision-time snapshot.
COST_COMPONENT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "fee": ("fee_bps", "expected_fee_bps", "taker_fee_bps"),
    "spread": (
        "actual_observed_spread_entry_bps",
        "observed_bid_ask_spread_bps",
        "bid_ask_spread_bps",
        "spread_bps",
    ),
    "slippage": (
        "expected_slippage_bps",
        "actual_observed_slippage_bps",
        "slippage_bps",
    ),
    "funding": (
        "expected_funding_bps",
        "funding_bps",
        "funding_rate_bps",
    ),
}
# Canonical archived fee and expected-slippage fields are per-side. A complete
# entry/exit replay therefore charges both twice. The observed full bid/ask
# spread is crossed as one full spread over the round trip; expected funding is
# a horizon drag rather than an execution-side charge.
COST_COMPONENT_ROUND_TRIP_MULTIPLIERS: dict[str, float] = {
    "fee": 2.0,
    "spread": 1.0,
    "slippage": 2.0,
    "funding": 1.0,
}


def _future_label_feature_name(name: Any) -> bool:
    lowered = str(name).lower()
    if lowered in PIT_SAFE_REALIZED_FEATURES:
        return False
    return lowered.startswith(FUTURE_LABEL_PREFIXES)


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if epoch > 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_utc_exact(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def timeframe_seconds(timeframe: str) -> int:
    unit = timeframe[-1:].lower()
    try:
        number = int(timeframe[:-1])
    except ValueError:
        return 60
    if unit == "m":
        return number * 60
    if unit == "h":
        return number * 60 * 60
    if unit == "d":
        return number * 24 * 60 * 60
    return 60


def snapshot_to_final_candle(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    symbol = str(snapshot.get("symbol") or "").upper()
    timeframe = str(snapshot.get("timeframe") or "")
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at") or snapshot.get("source_available_time"))
    if not symbol:
        reasons.append("SYMBOL_MISSING")
    if not timeframe:
        reasons.append("TIMEFRAME_MISSING")
    if not features:
        reasons.append("FEATURES_EMPTY")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING")
    if (
        feature_cutoff is not None
        and available_at is not None
        and feature_cutoff > available_at
    ):
        reasons.append("FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    close_price = finite_float(
        features.get("close")
        or features.get("last_price")
        or features.get("price_last")
        or features.get("ohlcv_close")
    )
    if close_price is None or close_price <= 0.0:
        reasons.append("CLOSE_PRICE_MISSING")
    if reasons:
        return None, sorted(set(reasons))
    assert feature_cutoff is not None and available_at is not None and close_price is not None
    open_time = feature_cutoff - timedelta(seconds=timeframe_seconds(timeframe))
    raw_payload_hash = (
        str(snapshot.get("content_sha256"))
        if snapshot.get("content_sha256")
        else hashlib.sha256(
            json.dumps(
                {
                    "snapshot_id": snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id"),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "feature_cutoff": iso_utc(feature_cutoff),
                    "available_at": iso_utc(available_at),
                    "features": {
                        name: features.get(name)
                        for name in ("open", "high", "low", "close", "last_price", "price_last")
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_open_time": iso_utc(open_time),
        "candle_close_time": iso_utc(feature_cutoff),
        "event_time": iso_utc(feature_cutoff),
        "available_at": iso_utc(available_at),
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "source": "v2_feature_snapshot_archive",
        "raw_payload_hash": raw_payload_hash,
        "open": finite_float(features.get("open")) or close_price,
        "high": finite_float(features.get("high")) or close_price,
        "low": finite_float(features.get("low")) or close_price,
        "close": close_price,
        "volume": finite_float(features.get("volume")) or 0.0,
        "source_snapshot_id": snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id"),
    }, []


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _candle_price(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = finite_float(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _timestamp_epoch_us(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value * (1_000 if abs(value) > 10_000_000_000 else 1_000_000)
    parsed = value if isinstance(value, datetime) else parse_utc(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    normalized = parsed.astimezone(timezone.utc)
    delta = normalized - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        (delta.days * 86_400 + delta.seconds) * 1_000_000
        + delta.microseconds
    )


def _canonical_timestamp_ms(value: Any) -> int | None:
    epoch_us = _timestamp_epoch_us(value)
    if epoch_us is None or epoch_us % 1_000 != 0:
        return None
    return epoch_us // 1_000


def _canonical_5m_label_candle(
    row: Mapping[str, Any],
    *,
    symbol: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one exact CanonicalCandle used as outcome evidence."""

    try:
        strict_canonical = validate_canonical_finalized_5m_candle(
            row,
            expected_symbol=str(symbol).upper(),
        )
    except Canonical5mValidationError as exc:
        return None, list(exc.reasons)
    reasons: list[str] = []
    expected_symbol = str(symbol).upper()
    if str(row.get("symbol") or "").upper() != expected_symbol:
        reasons.append("LABEL_CANDLE_SYMBOL_MISMATCH")
    if str(row.get("exchange") or "").lower() != "binance":
        reasons.append("LABEL_CANDLE_EXCHANGE_MISMATCH")
    if str(row.get("timeframe") or "") != TRUSTED_REPLAY_LABEL_BASE_TIMEFRAME:
        reasons.append("LABEL_CANDLE_NOT_CANONICAL_5M")
    if row.get("is_closed") is not True:
        reasons.append("LABEL_CANDLE_NOT_FINAL")
    if row.get("closed_candle") is not True:
        reasons.append("LABEL_CANDLE_CLOSED_FLAG_MISSING")
    if row.get("candle_closed_confirmed") is not True:
        reasons.append("LABEL_CANDLE_FINALITY_CONFIRMATION_MISSING")
    if row.get("feature_eligible") is not True:
        reasons.append("LABEL_CANDLE_FEATURE_ELIGIBILITY_UNPROVEN")
    if not isinstance(row.get("is_backfilled"), bool):
        reasons.append("LABEL_CANDLE_BACKFILL_STATE_MISSING")
    if str(row.get("source") or "") not in TRUSTED_REPLAY_LABEL_CANDLE_SOURCES:
        reasons.append("LABEL_CANDLE_SOURCE_NOT_CANONICAL")
    if row.get("source_sequence_id") in (None, ""):
        reasons.append("LABEL_CANDLE_SOURCE_SEQUENCE_ID_MISSING")

    open_ms = _canonical_timestamp_ms(
        row.get("candle_open_time") or row.get("open_time")
    )
    close_ms = _canonical_timestamp_ms(
        row.get("candle_close_time") or row.get("close_time")
    )
    event_ms = _canonical_timestamp_ms(row.get("event_time"))
    ingested_ms = _canonical_timestamp_ms(row.get("ingested_at"))
    available_ms = _canonical_timestamp_ms(row.get("available_at"))
    if open_ms is None:
        reasons.append("LABEL_CANDLE_OPEN_TIME_MISSING_OR_INVALID")
    if close_ms is None:
        reasons.append("LABEL_CANDLE_CLOSE_TIME_MISSING_OR_INVALID")
    if event_ms is None:
        reasons.append("LABEL_CANDLE_EVENT_TIME_MISSING_OR_INVALID")
    if ingested_ms is None:
        reasons.append("LABEL_CANDLE_INGESTED_AT_MISSING_OR_INVALID")
    if available_ms is None:
        reasons.append("LABEL_CANDLE_AVAILABLE_AT_MISSING_OR_INVALID")
    if open_ms is not None and close_ms is not None:
        if close_ms - open_ms != TRUSTED_REPLAY_LABEL_BASE_MILLISECONDS - 1:
            reasons.append("LABEL_CANDLE_5M_SLOT_BOUNDS_INVALID")
    if close_ms is not None and event_ms is not None and event_ms < close_ms:
        reasons.append("LABEL_CANDLE_EVENT_BEFORE_CLOSE")
    if (
        close_ms is not None
        and event_ms is not None
        and ingested_ms is not None
        and available_ms is not None
        and available_ms != max(close_ms, event_ms, ingested_ms)
    ):
        reasons.append("LABEL_CANDLE_AVAILABLE_AT_NOT_CANONICAL_MAX_CLOCK")

    prices: dict[str, float] = {}
    nested_ohlcv = row.get("ohlcv")
    if not isinstance(nested_ohlcv, Mapping):
        reasons.append("LABEL_CANDLE_CANONICAL_OHLCV_MISSING")
        nested_ohlcv = {}
    for field in ("open", "high", "low", "close"):
        top_value = finite_float(row.get(field))
        nested_value = finite_float(nested_ohlcv.get(field))
        if top_value is None or top_value <= 0.0:
            reasons.append(f"LABEL_CANDLE_{field.upper()}_MISSING_OR_INVALID")
            continue
        if nested_value is None or nested_value != top_value:
            reasons.append(
                f"LABEL_CANDLE_{field.upper()}_CANONICAL_COPY_MISMATCH"
            )
            continue
        prices[field] = top_value
    top_volume = finite_float(row.get("volume"))
    nested_volume = finite_float(nested_ohlcv.get("volume"))
    if top_volume is None or top_volume < 0.0:
        reasons.append("LABEL_CANDLE_VOLUME_MISSING_OR_INVALID")
    elif nested_volume is None or nested_volume != top_volume:
        reasons.append("LABEL_CANDLE_VOLUME_CANONICAL_COPY_MISMATCH")
    else:
        prices["volume"] = top_volume
    if all(field in prices for field in ("open", "high", "low", "close")):
        if prices["high"] < max(prices["open"], prices["close"]):
            reasons.append("LABEL_CANDLE_HIGH_BELOW_OPEN_OR_CLOSE")
        if prices["low"] > min(prices["open"], prices["close"]):
            reasons.append("LABEL_CANDLE_LOW_ABOVE_OPEN_OR_CLOSE")
        if prices["high"] < prices["low"]:
            reasons.append("LABEL_CANDLE_HIGH_BELOW_LOW")

    raw_payload_hash = _valid_sha256(row.get("raw_payload_hash"))
    if raw_payload_hash is None:
        reasons.append("LABEL_CANDLE_RAW_PAYLOAD_HASH_MISSING_OR_INVALID")
    candle_id = str(row.get("candle_id") or "").strip()
    if not candle_id:
        reasons.append("LABEL_CANDLE_ID_MISSING")
    elif candle_id != canonical_candle_id(row):
        reasons.append("LABEL_CANDLE_ID_MISMATCH")
    if reasons:
        return None, sorted(set(reasons))
    assert open_ms is not None
    assert close_ms is not None
    assert event_ms is not None
    assert ingested_ms is not None
    assert available_ms is not None
    assert raw_payload_hash is not None
    content_hash = str(strict_canonical["content_sha256"])
    return {
        **dict(row),
        "_open_ms": open_ms,
        "_close_ms": close_ms,
        "_event_ms": event_ms,
        "_ingested_ms": ingested_ms,
        "_available_ms": available_ms,
        "_canonical_label_content_sha256": content_hash,
    }, []


def canonical_5m_label_evidence(
    *,
    candles: Iterable[Mapping[str, Any]],
    symbol: str,
    decision_time: datetime,
    training_observed_at: datetime,
    source_key: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve an exact, contiguous, PIT-observed 5m outcome path."""

    reasons: list[str] = []
    by_close: dict[int, dict[str, Any]] = {}
    for raw in candles:
        if not isinstance(raw, Mapping):
            reasons.append("LABEL_CANDLE_ROW_NOT_OBJECT")
            continue
        candle, candle_reasons = _canonical_5m_label_candle(
            raw,
            symbol=symbol,
        )
        reasons.extend(candle_reasons)
        if candle is None:
            continue
        close_ms = int(candle["_close_ms"])
        prior = by_close.get(close_ms)
        if prior is not None:
            if (
                prior["_canonical_label_content_sha256"]
                != candle["_canonical_label_content_sha256"]
            ):
                reasons.append("CANONICAL_5M_DUPLICATE_CLOSE_CONFLICT")
            continue
        by_close[close_ms] = candle
    if reasons:
        return None, sorted(set(reasons))
    decision_us = _timestamp_epoch_us(decision_time)
    observed_us = _timestamp_epoch_us(training_observed_at)
    if decision_us is None or observed_us is None:
        return None, ["TRAINING_OR_DECISION_TIME_MISSING_OR_INVALID"]
    decision_floor_ms = decision_us // 1_000
    observed_floor_ms = observed_us // 1_000
    if observed_us <= decision_us:
        return None, ["TRAINING_OBSERVED_AT_NOT_AFTER_DECISION_TIME"]
    ordered = [by_close[key] for key in sorted(by_close)]
    future = [
        row
        for row in ordered
        if int(row["_close_ms"]) * 1_000 > decision_us
    ]
    if not future:
        return None, ["NO_CANONICAL_5M_LABEL_CANDLES_AFTER_DECISION"]

    horizon_candles: dict[str, dict[str, Any]] = {}
    horizon_lateness_ms: dict[str, int] = {}
    horizon_lateness_us: dict[str, int] = {}
    horizon_target_epoch_us: dict[str, int] = {}
    for horizon, seconds in HORIZON_SECONDS.items():
        target_us = decision_us + seconds * 1_000_000
        horizon_target_epoch_us[horizon] = target_us
        selected = next(
            (
                row
                for row in future
                if int(row["_close_ms"]) * 1_000 >= target_us
            ),
            None,
        )
        if selected is None:
            reasons.append(
                f"CANONICAL_5M_HORIZON_MISSING_{horizon.upper()}"
            )
            continue
        lateness_us = int(selected["_close_ms"]) * 1_000 - target_us
        if lateness_us >= TRUSTED_REPLAY_LABEL_BASE_MILLISECONDS * 1_000:
            reasons.append(
                f"CANONICAL_5M_HORIZON_LATE_{horizon.upper()}"
            )
            continue
        horizon_candles[horizon] = selected
        horizon_lateness_us[horizon] = lateness_us
        horizon_lateness_ms[horizon] = lateness_us // 1_000
    if reasons:
        return None, sorted(set(reasons))

    path_end_ms = int(horizon_candles["4h"]["_close_ms"])
    path = [
        row
        for row in future
        if int(row["_close_ms"]) <= path_end_ms
    ]
    if not path:
        return None, ["CANONICAL_5M_LABEL_PATH_EMPTY"]
    first = path[0]
    expected_first_close_ms = (
        ((decision_floor_ms + 1) // TRUSTED_REPLAY_LABEL_BASE_MILLISECONDS + 1)
        * TRUSTED_REPLAY_LABEL_BASE_MILLISECONDS
        - 1
    )
    if not (
        int(first["_close_ms"]) == expected_first_close_ms
        and int(first["_open_ms"]) * 1_000 <= decision_us + 1_000
        and int(first["_close_ms"]) * 1_000 > decision_us
    ):
        reasons.append("CANONICAL_5M_LABEL_PATH_START_GAP")
    for prior, current in zip(path, path[1:]):
        if int(current["_open_ms"]) != int(prior["_close_ms"]) + 1:
            reasons.append("CANONICAL_5M_LABEL_PATH_GAP")
            break
    future_available = [
        row
        for row in path
        if int(row["_available_ms"]) * 1_000 > observed_us
    ]
    if future_available:
        reasons.append(
            "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT"
        )
    if reasons:
        return None, sorted(set(reasons))
    excursion_path = [
        row
        for row in path
        if int(row["_open_ms"]) * 1_000 >= decision_us
    ]
    excluded_overlapping_candles = [
        row
        for row in path
        if (
            int(row["_open_ms"]) * 1_000
            < decision_us
            < int(row["_close_ms"]) * 1_000
        )
    ]
    if not excursion_path:
        return None, ["CANONICAL_5M_POST_DECISION_EXCURSION_PATH_EMPTY"]
    label_available_ms = max(int(row["_available_ms"]) for row in path)
    label_available_at = datetime.fromtimestamp(
        label_available_ms / 1000.0,
        tz=timezone.utc,
    )
    evidence_material = {
        "contract_version": TRUSTED_REPLAY_LABEL_CANDLE_CONTRACT_VERSION,
        "source_key": (
            str(source_key).strip()
            if source_key is not None and str(source_key).strip()
            else TRUSTED_REPLAY_LABEL_CANDLE_SOURCE_KEY_TEMPLATE.format(
                symbol=str(symbol).upper()
            )
        ),
        "symbol": str(symbol).upper(),
        "decision_time": iso_utc_exact(decision_time),
        "decision_time_epoch_us": decision_us,
        "decision_time_floor_ms": decision_floor_ms,
        "training_observed_at": iso_utc_exact(training_observed_at),
        "training_observed_at_epoch_us": observed_us,
        "training_observed_at_floor_ms": observed_floor_ms,
        "label_available_at": iso_utc_exact(label_available_at),
        "path_candles": [
            {
                "candle_id": row["candle_id"],
                "candle_open_time_ms": row["_open_ms"],
                "candle_close_time_ms": row["_close_ms"],
                "available_at_ms": row["_available_ms"],
                "raw_payload_hash": row["raw_payload_hash"],
                "canonical_label_content_sha256": row[
                    "_canonical_label_content_sha256"
                ],
            }
            for row in path
        ],
        "horizon_candle_ids": {
            horizon: row["candle_id"]
            for horizon, row in sorted(horizon_candles.items())
        },
        "horizon_lateness_ms": dict(sorted(horizon_lateness_ms.items())),
        "horizon_lateness_us": dict(sorted(horizon_lateness_us.items())),
        "horizon_target_epoch_us": dict(
            sorted(horizon_target_epoch_us.items())
        ),
        "excursion_scope": (
            "FULL_FINALIZED_5M_CANDLES_OPENING_AT_OR_AFTER_DECISION_TIME"
        ),
        "excursion_candle_ids": [row["candle_id"] for row in excursion_path],
        "excursion_excluded_overlapping_decision_candle_ids": [
            row["candle_id"] for row in excluded_overlapping_candles
        ],
        "excursion_predecision_overlap_excluded": True,
    }
    evidence_hash = hashlib.sha256(
        json.dumps(
            evidence_material,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        **evidence_material,
        "label_candle_evidence_sha256": evidence_hash,
        "horizon_candles": horizon_candles,
        "path_candles": path,
        "excursion_path_candles": excursion_path,
        "label_available_at_datetime": label_available_at,
        "path_contiguous_verified": True,
        "duplicate_close_conflict": False,
        "future_available_candle_used": False,
    }, []


def _directional_outcome(value_bps: float) -> str:
    if value_bps > 0:
        return "UP"
    if value_bps < 0:
        return "DOWN"
    return "FLAT"


def _trade_outcome(value_bps: float) -> str:
    if abs(value_bps) < 1e-9:
        return "BREAKEVEN"
    return "WIN" if value_bps > 0 else "LOSS"


def target_action_from_net_edges(
    *,
    long_net_bps: float,
    short_net_bps: float,
) -> str:
    """Choose only a direction whose own after-cost PnL is positive.

    Costs are subtracted from both counterfactual sides. They must never be
    added to a negative raw market return, which can flip a small down move into
    a fabricated profitable long label.  There is no market-static action band:
    the explicit PIT cost envelope itself is the decision-time dead zone.
    """
    best_net = max(long_net_bps, short_net_bps)
    if best_net <= 0.0:
        return "hold"
    return "long" if long_net_bps >= short_net_bps else "short"


def target_action_index(action: Any) -> int | None:
    normalized = _normalized_action(action)
    if normalized is None:
        return None
    return {"hold": 0, "long": 1, "short": 2}[normalized]


def counterfactual_excursion_bps(
    *,
    entry_price: float,
    target_action: Any,
    highs: Iterable[float],
    lows: Iterable[float],
) -> tuple[float, float] | None:
    """Return side-aware gross MFE/MAE for the selected replay action.

    A falling price is favorable to SHORT and adverse to LONG.  Keeping the
    raw-price sign convention for both sides silently swaps SHORT MFE/MAE, so
    excursion is normalized to the counterfactual action before publication.
    HOLD has no position and therefore no price-path excursion.
    """

    normalized = _normalized_action(target_action)
    parsed_entry = finite_float(entry_price)
    parsed_highs = [finite_float(value) for value in highs]
    parsed_lows = [finite_float(value) for value in lows]
    if (
        normalized is None
        or parsed_entry is None
        or parsed_entry <= 0.0
        or not parsed_highs
        or not parsed_lows
        or any(value is None or value <= 0.0 for value in parsed_highs)
        or any(value is None or value <= 0.0 for value in parsed_lows)
    ):
        return None
    if normalized == "hold":
        return 0.0, 0.0
    high_excursion = (
        (max(value for value in parsed_highs if value is not None) - parsed_entry)
        / parsed_entry
    ) * 10_000.0
    low_excursion = (
        (min(value for value in parsed_lows if value is not None) - parsed_entry)
        / parsed_entry
    ) * 10_000.0
    if normalized == "long":
        return max(0.0, high_excursion), min(0.0, low_excursion)
    return max(0.0, -low_excursion), min(0.0, -high_excursion)


def signed_after_cost_move_for_action(
    *,
    raw_return_bps: float,
    action: Any,
    action_dead_zone_bps: float,
) -> float | None:
    """Return the replay label's signed convention for one explicit action."""

    normalized = _normalized_action(action)
    if normalized is None:
        return None
    dead_zone = finite_float(action_dead_zone_bps)
    raw_return = finite_float(raw_return_bps)
    if dead_zone is None or dead_zone < 0.0 or raw_return is None:
        return None
    if normalized == "long":
        return raw_return - dead_zone
    if normalized == "short":
        return raw_return + dead_zone
    return 0.0


def _normalized_action(value: Any) -> str | None:
    action = str(value or "").strip().lower()
    return action if action in {"long", "short", "hold"} else None


def _valid_sha256(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def _cost_component_evidence(
    snapshot: Mapping[str, Any],
    *,
    component: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    missing_mask = snapshot.get("missing_mask") if isinstance(snapshot.get("missing_mask"), Mapping) else {}
    stale_mask = snapshot.get("stale_mask") if isinstance(snapshot.get("stale_mask"), Mapping) else {}
    aliases = COST_COMPONENT_FIELD_ALIASES[component]
    selected_field: str | None = None
    selected_value: float | None = None
    payload_name: str | None = None
    raw_value: Any = None
    for payload, prefix in ((features, "features"), (snapshot, "snapshot")):
        for field_name in aliases:
            if field_name not in payload:
                continue
            selected_field = field_name
            payload_name = prefix
            raw_value = payload.get(field_name)
            selected_value = finite_float(raw_value)
            break
        if selected_field is not None:
            break
    reason_prefix = f"COST_EVIDENCE_{component.upper()}"
    if selected_field is None:
        return None, [f"{reason_prefix}_MISSING"]
    if selected_value is None:
        return None, [f"{reason_prefix}_NONFINITE_OR_INVALID"]
    if component != "funding" and selected_value < 0.0:
        return None, [f"{reason_prefix}_NEGATIVE"]
    if bool(missing_mask.get(selected_field)):
        return None, [f"{reason_prefix}_FLAGGED_MISSING"]
    if bool(stale_mask.get(selected_field)):
        return None, [f"{reason_prefix}_FLAGGED_STALE"]

    source_fields = (
        snapshot.get("market_cost_evidence_source_fields")
        if isinstance(snapshot.get("market_cost_evidence_source_fields"), Mapping)
        else {}
    )
    source = source_fields.get(selected_field)
    if source in (None, ""):
        source = f"{payload_name}.{selected_field}"
    round_trip_multiplier = COST_COMPONENT_ROUND_TRIP_MULTIPLIERS[component]
    absolute_or_positive_bps = (
        abs(float(selected_value))
        if component == "funding"
        else float(selected_value)
    )
    return {
        "component": component,
        "field": selected_field,
        "source": str(source),
        "signed_bps": float(selected_value),
        "round_trip_multiplier": round_trip_multiplier,
        "cost_drag_bps": absolute_or_positive_bps * round_trip_multiplier,
        "raw_value": raw_value,
    }, []


def trusted_replay_cost_evidence(
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Resolve a hash-bound PIT cost envelope without a flat fallback.

    Every component is read from the immutable archived snapshot and inherits
    that snapshot's feature/availability/decision clocks.  Missing, stale,
    future, non-finite, or negative non-funding evidence fails closed.
    """

    decision_time = parse_utc(snapshot.get("decision_time"))
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at"))
    reasons: list[str] = []
    if decision_time is None:
        reasons.append("COST_EVIDENCE_DECISION_TIME_MISSING_OR_INVALID")
    if feature_cutoff is None:
        reasons.append("COST_EVIDENCE_FEATURE_CUTOFF_MISSING_OR_INVALID")
    if available_at is None:
        reasons.append("COST_EVIDENCE_AVAILABLE_AT_MISSING_OR_INVALID")
    if (
        feature_cutoff is not None
        and available_at is not None
        and feature_cutoff > available_at
    ):
        reasons.append("COST_EVIDENCE_FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if (
        available_at is not None
        and decision_time is not None
        and available_at > decision_time
    ):
        reasons.append("COST_EVIDENCE_AVAILABLE_AT_AFTER_DECISION_TIME")
    snapshot_hash = _valid_sha256(snapshot.get("content_sha256"))
    if snapshot_hash is None:
        reasons.append("COST_EVIDENCE_SNAPSHOT_CONTENT_SHA256_MISSING_OR_INVALID")
    else:
        try:
            if archive_content_sha256(snapshot) != snapshot_hash:
                reasons.append("COST_EVIDENCE_SNAPSHOT_CONTENT_SHA256_MISMATCH")
        except (TypeError, ValueError):
            reasons.append("COST_EVIDENCE_SNAPSHOT_CONTENT_SHA256_UNVERIFIABLE")

    components: dict[str, dict[str, Any]] = {}
    for component in COST_COMPONENT_FIELD_ALIASES:
        evidence, component_reasons = _cost_component_evidence(
            snapshot,
            component=component,
        )
        reasons.extend(component_reasons)
        if evidence is not None:
            components[component] = evidence
    if reasons:
        return None, sorted(set(reasons))

    assert decision_time is not None
    assert feature_cutoff is not None
    assert available_at is not None
    assert snapshot_hash is not None
    total_cost_bps = sum(
        float(component["cost_drag_bps"])
        for component in components.values()
    )
    if not math.isfinite(total_cost_bps) or total_cost_bps < 0.0:
        return None, ["COST_EVIDENCE_TOTAL_NONFINITE_OR_NEGATIVE"]
    material = {
        "schema_version": TRUSTED_REPLAY_COST_EVIDENCE_SCHEMA_VERSION,
        "snapshot_content_sha256": snapshot_hash,
        "feature_cutoff": iso_utc(feature_cutoff),
        "available_at": iso_utc(available_at),
        "decision_time": iso_utc(decision_time),
        "components": {
            name: {
                "field": component["field"],
                "source": component["source"],
                "signed_bps": component["signed_bps"],
                "round_trip_multiplier": component[
                    "round_trip_multiplier"
                ],
                "cost_drag_bps": component["cost_drag_bps"],
            }
            for name, component in sorted(components.items())
        },
        "total_cost_bps": total_cost_bps,
    }
    evidence_hash = hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        **material,
        "cost_evidence_hash": evidence_hash,
        "cost_evidence_source": "+".join(
            str(components[name]["source"])
            for name in sorted(components)
        ),
        "flat_round_trip_cost_fallback_used": False,
        "action_dead_zone_bps": total_cost_bps,
        "action_dead_zone_source": "EXPLICIT_PIT_COMPONENT_SUM_NO_STATIC_ACTION_THRESHOLD",
    }, []


def replay_rejection_reasons(
    snapshot: Mapping[str, Any],
    *,
    candles: Iterable[Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    decision_time = parse_utc(snapshot.get("decision_time"))
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at"))
    if not features:
        reasons.append("FEATURES_EMPTY")
    if any(_future_label_feature_name(name) for name in features):
        reasons.append("FUTURE_LABEL_PRESENT_IN_FEATURES")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if decision_time is None:
        reasons.append("DECISION_TIME_MISSING")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING")
    if feature_cutoff is not None and available_at is not None and feature_cutoff > available_at:
        reasons.append("FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    if snapshot.get("mtf_snapshot_id") in (None, ""):
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    # Outcome-candle semantics are validated by canonical_5m_label_evidence;
    # merely finding a later row is not proof of the required base-candle path.
    _ = candles
    return sorted(set(reasons))


def build_trusted_replay_row(
    snapshot: Mapping[str, Any],
    *,
    candles: Iterable[Mapping[str, Any]],
    training_observed_at: datetime | str | None = None,
    label_candle_source_key: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    candle_rows = [row for row in candles if isinstance(row, Mapping)]
    reasons = replay_rejection_reasons(snapshot, candles=candle_rows)
    if reasons:
        return None, reasons
    cost_evidence, cost_reasons = trusted_replay_cost_evidence(snapshot)
    if cost_evidence is None:
        return None, cost_reasons
    decision_time = parse_utc(snapshot.get("decision_time"))
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at"))
    assert decision_time is not None and feature_cutoff is not None and available_at is not None
    observed_at = (
        training_observed_at
        if isinstance(training_observed_at, datetime)
        else parse_utc(training_observed_at)
    )
    if (
        observed_at is None
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        return None, ["TRAINING_OBSERVED_AT_MISSING_OR_INVALID"]
    observed_at = observed_at.astimezone(timezone.utc)
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    entry_price = finite_float(
        features.get("close")
        or features.get("last_price")
        or features.get("price_last")
        or features.get("ohlcv_close")
    )
    if entry_price is None or entry_price <= 0.0:
        return None, ["ENTRY_PRICE_MISSING"]

    label_evidence, label_reasons = canonical_5m_label_evidence(
        candles=candle_rows,
        symbol=str(snapshot.get("symbol") or "").upper(),
        decision_time=decision_time,
        training_observed_at=observed_at,
        source_key=label_candle_source_key,
    )
    if label_evidence is None:
        return None, label_reasons
    horizon_candles = label_evidence["horizon_candles"]
    label_path_candles = label_evidence["path_candles"]
    excursion_path_candles = label_evidence["excursion_path_candles"]
    returns: dict[str, float] = {}
    for horizon, candle in horizon_candles.items():
        close_price = _candle_price(candle, "close", "close_price", "c")
        if close_price is None or close_price <= 0.0:
            return None, [
                f"CANONICAL_5M_HORIZON_CLOSE_INVALID_{horizon.upper()}"
            ]
        returns[horizon] = (
            (close_price - entry_price) / entry_price
        ) * 10_000.0

    raw_return_15m_bps = returns["15m"]
    costs_bps = float(cost_evidence["total_cost_bps"])
    action_dead_zone_bps = float(cost_evidence["action_dead_zone_bps"])
    long_net_bps = raw_return_15m_bps - costs_bps
    short_net_bps = -raw_return_15m_bps - costs_bps
    target_action = target_action_from_net_edges(
        long_net_bps=long_net_bps,
        short_net_bps=short_net_bps,
    )
    counterfactual_target_net_bps = (
        long_net_bps
        if target_action == "long"
        else short_net_bps
        if target_action == "short"
        else 0.0
    )
    # Compatibility label: signed by the observed market direction, but only
    # non-zero when that direction is profitable after costs. This preserves
    # DOWN as negative and UP as positive without allowing costs to flip sign.
    after_cost = (
        counterfactual_target_net_bps
        if target_action == "long"
        else -counterfactual_target_net_bps
        if target_action == "short"
        else 0.0
    )
    selected_action = _normalized_action(snapshot.get("selected_action"))
    actual_behavior_net_bps = (
        long_net_bps
        if selected_action == "long"
        else short_net_bps
        if selected_action == "short"
        else 0.0
        if selected_action == "hold"
        else None
    )
    label_available_at = label_evidence["label_available_at_datetime"]
    label_available_epoch_us = _timestamp_epoch_us(label_available_at)
    assert label_available_epoch_us is not None
    label_available_ms = label_available_epoch_us // 1_000
    if label_available_at <= decision_time:
        return None, ["LABEL_AVAILABLE_AT_NOT_AFTER_DECISION_TIME"]
    label_horizon_seconds = (label_available_at - decision_time).total_seconds()
    if not math.isfinite(label_horizon_seconds) or label_horizon_seconds <= 0.0:
        return None, ["LABEL_HORIZON_SECONDS_INVALID"]
    highs = [
        _candle_price(candle, "high", "high_price", "h")
        for candle in excursion_path_candles
    ]
    lows = [
        _candle_price(candle, "low", "low_price", "l")
        for candle in excursion_path_candles
    ]
    excursion = counterfactual_excursion_bps(
        entry_price=entry_price,
        target_action=target_action,
        highs=(value for value in highs if value is not None),
        lows=(value for value in lows if value is not None),
    )
    if excursion is None or any(value is None for value in [*highs, *lows]):
        return None, ["LABEL_PATH_HIGH_OR_LOW_MISSING_OR_INVALID"]
    mfe, mae = excursion
    directional = _directional_outcome(raw_return_15m_bps)
    trade_outcome = _trade_outcome(counterfactual_target_net_bps)
    actual_behavior_trade_outcome = (
        _trade_outcome(actual_behavior_net_bps)
        if actual_behavior_net_bps is not None
        else None
    )
    value_baseline = finite_float(snapshot.get("policy_value") or snapshot.get("value_baseline")) or 0.0
    reward = after_cost / 100.0
    feature_names = sorted(str(name) for name in features.keys())
    missing_mask = snapshot.get("missing_mask") if isinstance(snapshot.get("missing_mask"), Mapping) else {}
    stale_mask = snapshot.get("stale_mask") if isinstance(snapshot.get("stale_mask"), Mapping) else {}
    missing_names = [name for name in feature_names if bool(missing_mask.get(name))]
    stale_names = [name for name in feature_names if bool(stale_mask.get(name))]
    cost_components = cost_evidence["components"]
    fee_bps = float(cost_components["fee"]["signed_bps"])
    spread_bps = float(cost_components["spread"]["signed_bps"])
    slippage_bps = float(cost_components["slippage"]["signed_bps"])
    funding_bps = float(cost_components["funding"]["signed_bps"])
    round_trip_fee_drag_bps = float(
        cost_components["fee"]["cost_drag_bps"]
    )
    round_trip_spread_drag_bps = float(
        cost_components["spread"]["cost_drag_bps"]
    )
    round_trip_slippage_drag_bps = float(
        cost_components["slippage"]["cost_drag_bps"]
    )
    round_trip_funding_drag_bps = float(
        cost_components["funding"]["cost_drag_bps"]
    )
    target_exit_price = _candle_price(
        horizon_candles["15m"],
        "close",
        "close_price",
        "c",
    )
    assert target_exit_price is not None
    standardized_notional_usd = 1.0
    standardized_costs_usd = {
        "fee_usd": round_trip_fee_drag_bps / 10_000.0,
        "spread_usd": round_trip_spread_drag_bps / 10_000.0,
        "slippage_usd": round_trip_slippage_drag_bps / 10_000.0,
        "funding_drag_usd": round_trip_funding_drag_bps / 10_000.0,
    }
    standardized_economics = {
        "schema_version": TRUSTED_REPLAY_COUNTERFACTUAL_ECONOMICS_SCHEMA_VERSION,
        "basis": "ONE_USD_ENTRY_NOTIONAL_BPS_NORMALIZATION",
        "standardized_entry_notional_usd": standardized_notional_usd,
        "entry_price": entry_price,
        "exit_price": target_exit_price,
        "closed_quantity_per_one_usd_notional": standardized_notional_usd / entry_price,
        "cost_evidence_hash": cost_evidence["cost_evidence_hash"],
        "cost_scope": "DECISION_TIME_EXPECTED_COUNTERFACTUAL_NOT_EXACT_PAPER_CLOSE_LEDGER",
        "component_costs_usd": standardized_costs_usd,
        "long": {
            "gross_pnl_bps": raw_return_15m_bps,
            "net_pnl_bps": long_net_bps,
            "gross_pnl_usd": raw_return_15m_bps / 10_000.0,
            "net_pnl_usd": long_net_bps / 10_000.0,
        },
        "short": {
            "gross_pnl_bps": -raw_return_15m_bps,
            "net_pnl_bps": short_net_bps,
            "gross_pnl_usd": -raw_return_15m_bps / 10_000.0,
            "net_pnl_usd": short_net_bps / 10_000.0,
        },
        "hold": {
            "gross_pnl_bps": 0.0,
            "net_pnl_bps": 0.0,
            "gross_pnl_usd": 0.0,
            "net_pnl_usd": 0.0,
        },
        "net_formula": (
            "directional_gross_bps-(2*fee_bps)-spread_bps-"
            "(2*slippage_bps)-abs(funding_bps)"
        ),
        "confidence_exact_close_contract_claimed": False,
    }
    confidence_exact_close_blockers = [
        "DECISION_TIME_EXPECTED_COSTS_ARE_NOT_EXACT_ENTRY_EXIT_LEDGER_COSTS",
        "EXACT_ENTRY_EXIT_FEE_SLIPPAGE_FUNDING_USD_EVIDENCE_MISSING",
        "EXACT_CLOSED_QUANTITY_AND_CLOSE_EVENT_EVIDENCE_MISSING",
    ]
    if selected_action is None:
        confidence_exact_close_blockers.append(
            "ACTUAL_SELECTED_BEHAVIOR_ACTION_MISSING"
        )
    row = {
        "sample_id": f"trusted_replay:{snapshot.get('snapshot_id')}",
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "trainer_feedback_source": "V2_DURABLE_FEATURE_SNAPSHOT_TRUSTED_REPLAY",
        "learning_mode": "outcome_supervised",
        "update_lane": "OUTCOME_SUPERVISED_TRUSTED_REPLAY",
        "prediction_id": snapshot.get("prediction_id") or f"trusted_replay_pred:{snapshot.get('snapshot_id')}",
        "signal_id": snapshot.get("signal_id") or f"trusted_replay_sig:{snapshot.get('snapshot_id')}",
        "decision_id": snapshot.get("decision_id") or f"trusted_replay_decision:{snapshot.get('snapshot_id')}",
        "feature_snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "entry_feature_snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "mtf_snapshot_id": snapshot.get("mtf_snapshot_id"),
        "replay_snapshot_id": snapshot.get("replay_snapshot_id") or f"trusted_replay:{snapshot.get('snapshot_id')}",
        "replay_snapshot_key": snapshot.get("replay_snapshot_key") or f"durable_feature_snapshot_archive:{snapshot.get('snapshot_id')}",
        "mtf_snapshot_valid": True,
        "mtf_snapshot_reject_reasons": [],
        "symbol": str(snapshot.get("symbol") or "").upper(),
        "timeframe": str(snapshot.get("timeframe") or ""),
        "feature_cutoff": iso_utc_exact(feature_cutoff),
        "decision_time": iso_utc_exact(decision_time),
        "decision_time_epoch_us": label_evidence["decision_time_epoch_us"],
        "decision_time_est": iso_utc_exact(decision_time),
        "decision_cutoff_time_est": iso_utc_exact(decision_time),
        "generated_at": iso_utc_exact(decision_time),
        "generated_utc": iso_utc_exact(decision_time),
        "available_at": iso_utc_exact(available_at),
        "source_available_time": iso_utc_exact(available_at),
        "source_event_time_est": iso_utc_exact(feature_cutoff),
        "source_received_time_est": iso_utc_exact(available_at),
        "latency_ms": 0,
        "candle_closed_confirmed": True,
        "candle_open_time": iso_utc_exact(feature_cutoff - timedelta(seconds=timeframe_seconds(str(snapshot.get("timeframe") or "1m")))),
        "candle_close_time": iso_utc_exact(feature_cutoff),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "accepted_for_training": True,
        "valid_for_training": True,
        "row_classification": "TRAINABLE",
        "missing_feature_names": missing_names,
        "missing_feature_count": len(missing_names),
        "stale_feature_names": stale_names,
        "stale_feature_count": len(stale_names),
        "features": dict(features),
        "source_hashes": dict(snapshot.get("source_hashes") or {}),
        "model_version": snapshot.get("model_version") or "trusted_replay_labeler_v1",
        "checkpoint_id": snapshot.get("checkpoint_id") or "trusted_replay_no_prior_checkpoint",
        "selected_action": selected_action,
        "selected_action_raw": snapshot.get("selected_action"),
        "target_action": target_action,
        "target_action_index": target_action_index(target_action),
        "trusted_replay_label_policy_version": TRUSTED_REPLAY_LABEL_POLICY_VERSION,
        "trusted_replay_label_candle_contract_version": (
            TRUSTED_REPLAY_LABEL_CANDLE_CONTRACT_VERSION
        ),
        "trusted_replay_label_base_timeframe": (
            TRUSTED_REPLAY_LABEL_BASE_TIMEFRAME
        ),
        "trusted_replay_label_candle_source_key": label_evidence[
            "source_key"
        ],
        "trusted_replay_label_candle_evidence_sha256": label_evidence[
            "label_candle_evidence_sha256"
        ],
        "trusted_replay_label_path_candle_count": len(label_path_candles),
        "trusted_replay_label_path_contiguous_verified": label_evidence[
            "path_contiguous_verified"
        ],
        "trusted_replay_label_duplicate_close_conflict": label_evidence[
            "duplicate_close_conflict"
        ],
        "trusted_replay_label_future_available_candle_used": label_evidence[
            "future_available_candle_used"
        ],
        "trusted_replay_label_horizon_candle_ids": dict(
            label_evidence["horizon_candle_ids"]
        ),
        "trusted_replay_label_horizon_lateness_ms": dict(
            label_evidence["horizon_lateness_ms"]
        ),
        "trusted_replay_label_horizon_lateness_us": dict(
            label_evidence["horizon_lateness_us"]
        ),
        "trusted_replay_label_horizon_target_epoch_us": dict(
            label_evidence["horizon_target_epoch_us"]
        ),
        "trusted_replay_excursion_scope": label_evidence[
            "excursion_scope"
        ],
        "trusted_replay_excursion_candle_count": len(
            excursion_path_candles
        ),
        "trusted_replay_excursion_candle_ids": list(
            label_evidence["excursion_candle_ids"]
        ),
        "trusted_replay_excursion_excluded_overlapping_decision_candle_ids": (
            list(
                label_evidence[
                    "excursion_excluded_overlapping_decision_candle_ids"
                ]
            )
        ),
        "trusted_replay_excursion_predecision_overlap_excluded": (
            label_evidence["excursion_predecision_overlap_excluded"]
        ),
        "training_observed_at": iso_utc_exact(observed_at),
        "training_observed_at_epoch_us": label_evidence[
            "training_observed_at_epoch_us"
        ],
        "label_available_at": iso_utc_exact(label_available_at),
        "label_available_at_epoch_ms": label_available_ms,
        "outcome_available_at": iso_utc_exact(label_available_at),
        "label_horizon_seconds": label_horizon_seconds,
        "outcome_horizon_seconds": label_horizon_seconds,
        "future_return_5m_bps": returns["5m"],
        "future_return_15m_bps": returns["15m"],
        "future_return_1h_bps": returns["1h"],
        "future_return_4h_bps": returns["4h"],
        "raw_future_return_15m_bps": raw_return_15m_bps,
        "round_trip_cost_bps": costs_bps,
        "fee_bps": fee_bps,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "funding_bps": funding_bps,
        "round_trip_fee_drag_bps": round_trip_fee_drag_bps,
        "round_trip_spread_drag_bps": round_trip_spread_drag_bps,
        "round_trip_slippage_drag_bps": round_trip_slippage_drag_bps,
        "round_trip_funding_drag_bps": round_trip_funding_drag_bps,
        "action_dead_zone_bps": action_dead_zone_bps,
        "action_dead_zone_source": cost_evidence["action_dead_zone_source"],
        "cost_evidence_schema_version": cost_evidence["schema_version"],
        "cost_evidence_hash": cost_evidence["cost_evidence_hash"],
        "cost_evidence_source": cost_evidence["cost_evidence_source"],
        "cost_evidence_available_at": cost_evidence["available_at"],
        "cost_evidence_components": dict(cost_components),
        "flat_round_trip_cost_fallback_used": False,
        "static_action_threshold_used": False,
        "counterfactual_long_net_pnl_bps": long_net_bps,
        "counterfactual_short_net_pnl_bps": short_net_bps,
        "counterfactual_target_net_pnl_bps": counterfactual_target_net_bps,
        "counterfactual_action_was_profitable": counterfactual_target_net_bps > 0.0,
        "counterfactual_trade_outcome": trade_outcome,
        "counterfactual_label_source": "FINALIZED_CANDLES_BEST_AFTER_COST_SIDE",
        "actual_behavior_net_pnl_bps": actual_behavior_net_bps,
        "actual_behavior_trade_outcome": actual_behavior_trade_outcome,
        "actual_behavior_outcome_available": selected_action is not None,
        "actual_behavior_action_was_profitable": (
            actual_behavior_net_bps > 0.0
            if actual_behavior_net_bps is not None
            else None
        ),
        "future_return_after_cost_bps": after_cost,
        "standardized_counterfactual_economics": standardized_economics,
        "confidence_exact_close_contract_eligible": False,
        "confidence_exact_close_contract_blockers": (
            confidence_exact_close_blockers
        ),
        "confidence_target_action_not_substituted_from_hindsight": True,
        "directional_outcome": directional,
        "trade_outcome": trade_outcome,
        "maximum_favorable_excursion_bps": mfe,
        "maximum_adverse_excursion_bps": mae,
        "counterfactual_excursion_action": target_action,
        "counterfactual_excursion_scope": label_evidence[
            "excursion_scope"
        ],
        "realized_after_cost_reward": reward,
        "value_baseline": value_baseline,
        "advantage": reward - value_baseline,
        "advantage_source": "realized_after_cost_reward_minus_value_baseline",
        "realized_reward_source": "counterfactual_target_after_cost_from_finalized_candles",
        "uses_expected_move_as_realized_reward": False,
        "future_labels_not_in_feature_tensor": True,
        "outcome_targets": {
            "realized_net_pnl_bps": after_cost,
            "realized_net_pnl_usd": None,
            "directional_outcome": directional,
            "trade_outcome": trade_outcome,
            "selected_action": selected_action,
            "target_action": target_action,
            "action_was_profitable": counterfactual_target_net_bps > 0.0,
            "outcome_target_type": "COUNTERFACTUAL_BEST_ACTION",
            "counterfactual_long_net_pnl_bps": long_net_bps,
            "counterfactual_short_net_pnl_bps": short_net_bps,
            "counterfactual_target_net_pnl_bps": counterfactual_target_net_bps,
            "counterfactual_label_source": "FINALIZED_CANDLES_BEST_AFTER_COST_SIDE",
            "actual_behavior_net_pnl_bps": actual_behavior_net_bps,
            "actual_behavior_trade_outcome": actual_behavior_trade_outcome,
            "actual_behavior_outcome_available": selected_action is not None,
            "actual_behavior_action_was_profitable": (
                actual_behavior_net_bps > 0.0
                if actual_behavior_net_bps is not None
                else None
            ),
            "holding_period": HORIZON_SECONDS["15m"],
            "label_available_at": iso_utc_exact(label_available_at),
            "label_available_at_epoch_ms": label_available_ms,
            "outcome_available_at": iso_utc_exact(label_available_at),
            "label_horizon_seconds": label_horizon_seconds,
            "label_candle_contract_version": (
                TRUSTED_REPLAY_LABEL_CANDLE_CONTRACT_VERSION
            ),
            "label_base_timeframe": TRUSTED_REPLAY_LABEL_BASE_TIMEFRAME,
            "label_candle_evidence_sha256": label_evidence[
                "label_candle_evidence_sha256"
            ],
            "label_path_contiguous_verified": True,
            "label_future_available_candle_used": False,
            "fees": None,
            "fees_bps": fee_bps,
            "spread_bps": spread_bps,
            "slippage": None,
            "slippage_bps": slippage_bps,
            "funding": None,
            "funding_bps": funding_bps,
            "round_trip_fee_drag_bps": round_trip_fee_drag_bps,
            "round_trip_spread_drag_bps": round_trip_spread_drag_bps,
            "round_trip_slippage_drag_bps": round_trip_slippage_drag_bps,
            "round_trip_funding_drag_bps": round_trip_funding_drag_bps,
            "round_trip_cost_bps": costs_bps,
            "action_dead_zone_bps": action_dead_zone_bps,
            "cost_evidence_hash": cost_evidence["cost_evidence_hash"],
            "cost_evidence_schema_version": cost_evidence["schema_version"],
            "MFE": mfe,
            "MAE": mae,
            "counterfactual_excursion_scope": label_evidence[
                "excursion_scope"
            ],
            "counterfactual_excursion_candle_ids": list(
                label_evidence["excursion_candle_ids"]
            ),
            "counterfactual_excursion_predecision_overlap_excluded": (
                label_evidence[
                    "excursion_predecision_overlap_excluded"
                ]
            ),
            "exit_reason": "TRUSTED_REPLAY_FUTURE_FINALIZED_CANDLE_HORIZON",
            "realized_after_cost_reward": reward,
            "value_baseline": value_baseline,
            "advantage": reward - value_baseline,
        },
    }
    return row, []
