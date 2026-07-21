"""Pure scheduling helpers for bounded CoinAnk Standard-plan ingestion.

The legacy producer is a persistent process, but its endpoint cursor must also
survive restarts. These helpers keep selection deterministic from an explicit
persisted cursor and a per-parameter last-success ledger; they perform no I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

DEFAULT_PREFERRED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_TIMEFRAME_PRIORITY = ("1h", "15m", "5m", "30m", "4h", "1d")
TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
    "2h": 7_200,
    "4h": 14_400,
    "6h": 21_600,
    "8h": 28_800,
    "12h": 43_200,
    "1d": 86_400,
    "1w": 604_800,
    "1M": 2_592_000,
}


def aligned_current_end_time_ms(now_ms: int, timeframe: str) -> int:
    interval_seconds = TIMEFRAME_SECONDS.get(str(timeframe))
    if interval_seconds is None:
        raise ValueError(f"unsupported CoinAnk timeframe: {timeframe!r}")
    interval_ms = interval_seconds * 1000
    return (int(now_ms) // interval_ms) * interval_ms


def canonical_usdt_symbol(value: Any) -> str:
    """Canonicalize common USD aliases and repeated USDT suffixes."""
    base = str(value).strip().upper()
    while base.endswith("USDT"):
        base = base[:-4]
    for suffix in ("BUSD", "USDC", "USD"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if not base:
        raise ValueError(f"invalid CoinAnk symbol: {value!r}")
    return f"{base}USDT"


def canonical_param_symbol(params: Mapping[str, Any]) -> str | None:
    value = params.get("symbol") or params.get("baseCoin")
    if value in (None, ""):
        return None
    return canonical_usdt_symbol(value)


def parameter_identity(endpoint: str, params: Mapping[str, Any]) -> str:
    stable = {
        key: params[key]
        for key in (
            "exchange",
            "exchanges",
            "symbol",
            "baseCoin",
            "interval",
            "timeframe",
            "productType",
            "type",
        )
        if key in params
    }
    digest = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:16]
    return f"{endpoint}:{digest}"


def derive_critical_call_budget(
    params_list: Sequence[Mapping[str, Any]],
    *,
    endpoint_interval_seconds: float,
    freshness_sla_seconds: float,
    rpm_share: float,
    hard_call_cap: int = 50,
    preferred_symbols: Sequence[str] = DEFAULT_PREFERRED_SYMBOLS,
) -> dict[str, Any]:
    """Derive a per-tick batch that meets the SLA without exceeding RPM share."""
    interval = max(0.001, float(endpoint_interval_seconds))
    sla = max(interval, float(freshness_sla_seconds))
    preferred = {str(symbol).upper() for symbol in preferred_symbols}
    preferred_counts: dict[str, int] = {}
    rotating_count = 0
    for params in params_list:
        symbol = canonical_param_symbol(params)
        if symbol in preferred:
            preferred_counts[symbol] = preferred_counts.get(symbol, 0) + 1
        else:
            rotating_count += 1
    max_ticks_within_sla = max(1, math.floor(sla / interval))
    preferred_required = sum(
        max(1, math.ceil(count / max_ticks_within_sla))
        for count in preferred_counts.values()
    )
    rotating_required = math.ceil(rotating_count / max_ticks_within_sla)
    required_calls = min(
        len(params_list), preferred_required + rotating_required
    )
    rpm_limited_calls = max(1, math.floor(float(rpm_share) * interval / 60.0))
    call_budget = min(
        len(params_list),
        required_calls,
        max(1, int(hard_call_cap)),
        rpm_limited_calls,
    )
    return {
        "call_budget": call_budget,
        "required_calls_for_sla": required_calls,
        "preferred_required_calls": preferred_required,
        "rotating_required_calls": rotating_required,
        "rpm_limited_calls": rpm_limited_calls,
        "rpm_share": float(rpm_share),
        "capacity_satisfies_sla": call_budget >= required_calls,
    }


def effective_capacity_satisfies_sla(
    *,
    planned_capacity_satisfies_sla: bool,
    call_budget: int,
    attempted_calls: int,
) -> bool:
    """Fail closed when the runtime cannot spend its planned per-tick budget."""
    return bool(
        planned_capacity_satisfies_sla
        and int(attempted_calls) >= max(1, int(call_budget))
    )


def select_due_critical_endpoint(
    endpoint_order: Sequence[str],
    *,
    last_started_ms: Mapping[str, int],
    now_ms: int,
    target_visit_interval_seconds: float,
    minimum_visit_interval_seconds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Select the oldest due critical endpoint before generic endpoint work."""
    minimums = dict(minimum_visit_interval_seconds or {})
    records = []
    for order, endpoint in enumerate(endpoint_order):
        endpoint_interval_seconds = max(
            float(target_visit_interval_seconds),
            float(minimums.get(str(endpoint), 0.0) or 0.0),
        )
        interval_ms = max(1, int(endpoint_interval_seconds * 1000))
        started_ms = max(0, int(last_started_ms.get(str(endpoint), 0) or 0))
        due_at_ms = started_ms + interval_ms if started_ms else 0
        records.append({
            "endpoint": str(endpoint),
            "order": order,
            "started_ms": started_ms,
            "due_at_ms": due_at_ms,
            "visit_interval_seconds": endpoint_interval_seconds,
        })

    due = [record for record in records if record["due_at_ms"] <= int(now_ms)]
    due.sort(key=lambda record: (record["started_ms"], record["order"]))
    next_due_ms = min(
        (record["due_at_ms"] for record in records if record["due_at_ms"] > now_ms),
        default=None,
    )
    return {
        "endpoint": due[0]["endpoint"] if due else None,
        "seconds_until_next": (
            max(0.0, (int(next_due_ms) - int(now_ms)) / 1000.0)
            if next_due_ms is not None
            else 0.0
        ),
    }


def effective_visit_interval_seconds(
    *,
    target_visit_interval_seconds: float,
    previous_started_ms: int | None,
    current_started_ms: int,
) -> float:
    """Use measured start-to-start cadence, never a more optimistic target."""
    target = max(0.001, float(target_visit_interval_seconds))
    if not previous_started_ms or int(previous_started_ms) >= int(current_started_ms):
        return target
    measured = (int(current_started_ms) - int(previous_started_ms)) / 1000.0
    return max(target, measured)


def derive_critical_spend_budget_seconds(
    *,
    generic_spend_budget_seconds: float,
    call_budget: int,
    per_call_budget_seconds: float,
) -> float:
    """Give a bounded critical batch enough wall time to attempt its call budget."""
    return max(
        max(0.0, float(generic_spend_budget_seconds)),
        max(1, int(call_budget)) * max(0.001, float(per_call_budget_seconds)),
    )


def select_parameter_batch(
    endpoint: str,
    params_list: Sequence[Mapping[str, Any]],
    *,
    cursor: int,
    max_calls: int,
    now_ms: int,
    last_success_ms: Mapping[str, int] | None = None,
    preferred_symbols: Sequence[str] = DEFAULT_PREFERRED_SYMBOLS,
    timeframe_priority: Sequence[str] = DEFAULT_TIMEFRAME_PRIORITY,
    endpoint_interval_seconds: float = 60.0,
    freshness_sla_seconds: float = 600.0,
) -> dict[str, Any]:
    """Pin one most-overdue lane per major, then fairly rotate the remainder."""
    budget = max(1, int(max_calls))
    successes = dict(last_success_ms or {})
    preferred = tuple(str(symbol).upper() for symbol in preferred_symbols)
    tf_rank = {str(tf): index for index, tf in enumerate(timeframe_priority)}
    records = [
        {
            "params": dict(params),
            "identity": parameter_identity(endpoint, params),
            "symbol": canonical_param_symbol(params),
            "timeframe": str(params.get("interval") or params.get("timeframe") or ""),
            "original_index": index,
        }
        for index, params in enumerate(params_list)
    ]
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    preferred_revisit_estimates: list[float] = []
    for symbol in preferred:
        candidates = [record for record in records if record["symbol"] == symbol]
        if not candidates or len(selected) >= budget:
            continue

        def due_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
            last_ms = successes.get(str(record["identity"]))
            return (
                0 if last_ms is None else 1,
                int(last_ms or 0),
                tf_rank.get(str(record["timeframe"]), len(tf_rank)),
                int(record["original_index"]),
            )

        max_ticks_within_sla = max(
            1, math.floor(freshness_sla_seconds / endpoint_interval_seconds)
        )
        calls_for_symbol = max(
            1, math.ceil(len(candidates) / max_ticks_within_sla)
        )
        preferred_revisit_estimates.append(
            math.ceil(len(candidates) / calls_for_symbol) * endpoint_interval_seconds
        )
        for chosen in sorted(candidates, key=due_key)[:calls_for_symbol]:
            if len(selected) >= budget:
                break
            selected.append({**chosen, "selection_class": "preferred_major"})
            selected_ids.add(str(chosen["identity"]))

    rotating_pool = [
        record for record in records if record["symbol"] not in preferred
    ]
    rotation_capacity = max(0, budget - len(selected))
    normalized_cursor = int(cursor) % len(rotating_pool) if rotating_pool else 0
    rotating_selected: list[dict[str, Any]] = []
    for offset in range(min(rotation_capacity, len(rotating_pool))):
        record = rotating_pool[(normalized_cursor + offset) % len(rotating_pool)]
        rotating_selected.append({**record, "selection_class": "rotating"})
        selected_ids.add(str(record["identity"]))
    selected.extend(rotating_selected)

    # If the universe contains only preferred symbols, use remaining capacity
    # for their next most-overdue lanes without duplicating a request.
    if len(selected) < budget:
        unselected_preferred = [
            record
            for record in records
            if record["symbol"] in preferred
            and str(record["identity"]) not in selected_ids
        ]
        unselected_preferred.sort(
            key=lambda record: (
                0
                if successes.get(str(record["identity"])) is None
                else 1,
                int(successes.get(str(record["identity"])) or 0),
                tf_rank.get(str(record["timeframe"]), len(tf_rank)),
                int(record["original_index"]),
            )
        )
        for record in unselected_preferred[: budget - len(selected)]:
            selected.append({**record, "selection_class": "preferred_overflow"})

    preferred_lane_count = sum(
        1 for record in records if record["symbol"] in preferred
    )
    preferred_symbols_present = len(
        {record["symbol"] for record in records if record["symbol"] in preferred}
    )
    preferred_revisit_seconds = (
        max(preferred_revisit_estimates) if preferred_revisit_estimates else 0.0
    )
    rotating_revisit_seconds = (
        math.ceil(len(rotating_pool) / rotation_capacity) * endpoint_interval_seconds
        if rotating_pool and rotation_capacity > 0
        else (None if rotating_pool else 0.0)
    )
    record_identities = {str(record["identity"]) for record in records}
    known_ages = [
        max(0.0, (now_ms - int(value)) / 1000.0)
        for identity, value in successes.items()
        if any(record["identity"] == identity for record in records)
    ]
    return {
        "selection": selected,
        "cursor": normalized_cursor,
        "rotating_pool_size": len(rotating_pool),
        "planned_rotating_attempts": len(rotating_selected),
        "preferred_lane_count": preferred_lane_count,
        "preferred_symbols_present": preferred_symbols_present,
        "preferred_estimated_revisit_seconds": preferred_revisit_seconds,
        "rotating_estimated_revisit_seconds": rotating_revisit_seconds,
        "freshness_sla_seconds": float(freshness_sla_seconds),
        "measured_max_success_age_seconds": max(known_ages) if known_ages else None,
        "coverage_partial": bool(
            preferred_revisit_seconds > freshness_sla_seconds
            or rotating_revisit_seconds is None
            or rotating_revisit_seconds > freshness_sla_seconds
            or len(record_identities.intersection(successes)) < len(record_identities)
        ),
    }


def advance_cursor(
    cursor: int, *, rotating_pool_size: int, rotating_attempts: int
) -> int:
    if rotating_pool_size <= 0:
        return 0
    return (int(cursor) + max(0, int(rotating_attempts))) % int(rotating_pool_size)


_SEMANTIC_ENDPOINTS = frozenset(
    {
        "openInterest_kline",
        "marketOrder_getBuySellValue",
        "liquidation_history",
        "fundingRate_kline",
        "ls_global_account_ratio",
    }
)


def _semantic_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _semantic_epoch_ms(value: Any) -> int | None:
    parsed = _semantic_number(value)
    if parsed is None or parsed <= 0:
        return None
    # CoinAnk documents milliseconds, but tolerate a conventional epoch-second
    # value without weakening finality checks.
    if parsed < 10_000_000_000:
        parsed *= 1000
    return int(parsed)


def _explicit_success(envelope: Any) -> bool:
    return bool(
        isinstance(envelope, Mapping)
        and envelope.get("success") is True
        and str(envelope.get("code")) == "1"
    )


def _row_open_time_ms(row: Any) -> int | None:
    if isinstance(row, Mapping):
        for field in ("begin", "ts", "time", "timestamp"):
            if field in row:
                return _semantic_epoch_ms(row.get(field))
        return None
    if isinstance(row, list | tuple) and row:
        return _semantic_epoch_ms(row[0])
    return None


def _recent_finalized_row(
    rows: Any, *, interval_ms: int, available_at_ms: int
) -> tuple[Any, int] | None:
    if not isinstance(rows, list):
        return None
    candidates: list[tuple[int, Any]] = []
    for row in rows:
        open_ms = _row_open_time_ms(row)
        if open_ms is None:
            continue
        cutoff_ms = open_ms + interval_ms
        age_ms = available_at_ms - cutoff_ms
        if 0 <= age_ms <= interval_ms:
            candidates.append((open_ms, row))
    if not candidates:
        return None
    open_ms, row = max(candidates, key=lambda item: item[0])
    return row, open_ms


def _validated_ohlc(
    row: Any, *, nonnegative: bool, max_abs: float | None = None
) -> dict[str, float] | None:
    if not isinstance(row, Mapping):
        return None
    values = {
        field: _semantic_number(row.get(field))
        for field in ("open", "close", "low", "high")
    }
    if any(value is None for value in values.values()):
        return None
    numeric = {
        field: float(value)
        for field, value in values.items()
        if value is not None
    }
    if nonnegative and any(value < 0 for value in numeric.values()):
        return None
    if max_abs is not None and any(abs(value) > max_abs for value in numeric.values()):
        return None
    if (
        numeric["low"] > min(numeric["open"], numeric["close"])
        or numeric["high"] < max(numeric["open"], numeric["close"])
        or numeric["low"] > numeric["high"]
    ):
        return None
    return numeric


def validate_critical_response(
    endpoint: str,
    response: Any,
    *,
    timeframe: str,
    available_at_ms: int,
) -> dict[str, Any]:
    """Validate whether a raw CoinAnk response is fresh and feature-usable.

    ``available_at_ms`` is the local response-receipt clock. A successful
    result always identifies one finalized observation whose cutoff is no more
    than one requested timeframe behind that receipt.
    """
    endpoint_name = str(endpoint)
    base = {"valid": False, "endpoint": endpoint_name}
    if endpoint_name not in _SEMANTIC_ENDPOINTS:
        return {**base, "reason": "unsupported_endpoint"}
    interval_seconds = TIMEFRAME_SECONDS.get(str(timeframe))
    if interval_seconds is None:
        return {**base, "reason": "unsupported_timeframe"}
    receipt_ms = _semantic_epoch_ms(available_at_ms)
    if receipt_ms is None:
        return {**base, "reason": "available_at_invalid"}
    if not _explicit_success(response):
        return {**base, "reason": "api_success_not_explicit"}

    data: Any = response.get("data")
    if endpoint_name == "marketOrder_getBuySellValue":
        if not _explicit_success(data):
            return {**base, "reason": "nested_api_success_not_explicit"}
        data = data.get("data")

    interval_ms = interval_seconds * 1000
    if endpoint_name == "ls_global_account_ratio":
        if not isinstance(data, Mapping):
            return {**base, "reason": "data_shape_invalid"}
        timestamps = data.get("tss") or data.get("timestamps") or data.get("times")
        ratios = data.get("longShortRatio") or data.get("longShortRatios")
        if not isinstance(timestamps, list) or not isinstance(ratios, list):
            return {**base, "reason": "data_shape_invalid"}
        temporal_candidates: list[tuple[int, int]] = []
        for index, timestamp in enumerate(timestamps):
            open_ms = _semantic_epoch_ms(timestamp)
            if open_ms is None:
                continue
            age_ms = receipt_ms - (open_ms + interval_ms)
            if 0 <= age_ms <= interval_ms:
                temporal_candidates.append((open_ms, index))
        if not temporal_candidates:
            return {**base, "reason": "no_recent_finalized_observation"}
        open_ms, index = max(temporal_candidates, key=lambda item: item[0])
        ratio = _semantic_number(ratios[index]) if index < len(ratios) else None
        if ratio is None or ratio <= 0:
            return {**base, "reason": "numeric_domain_invalid"}
        values = {"long_short_ratio": ratio}
    else:
        selected = _recent_finalized_row(
            data, interval_ms=interval_ms, available_at_ms=receipt_ms
        )
        if selected is None:
            return {**base, "reason": "no_recent_finalized_observation"}
        row, open_ms = selected
        if endpoint_name == "openInterest_kline":
            values = _validated_ohlc(row, nonnegative=True)
        elif endpoint_name == "fundingRate_kline":
            # The bridge interprets CoinAnk kline values as percentage points
            # and accepts at most +/-5 percentage points before /100 scaling.
            values = _validated_ohlc(row, nonnegative=False, max_abs=5.0)
        elif endpoint_name == "liquidation_history":
            if not isinstance(row, Mapping):
                values = None
            else:
                long_turnover = _semantic_number(row.get("longTurnover"))
                short_turnover = _semantic_number(row.get("shortTurnover"))
                values = (
                    {
                        "long_turnover": long_turnover,
                        "short_turnover": short_turnover,
                    }
                    if long_turnover is not None
                    and short_turnover is not None
                    and long_turnover >= 0
                    and short_turnover >= 0
                    else None
                )
        else:
            if not isinstance(row, list | tuple) or len(row) < 3:
                values = None
            else:
                buy_value = _semantic_number(row[1])
                sell_value = _semantic_number(row[2])
                values = (
                    {"buy_value": buy_value, "sell_value": sell_value}
                    if buy_value is not None
                    and sell_value is not None
                    and buy_value >= 0
                    and sell_value >= 0
                    else None
                )
        if values is None:
            return {**base, "reason": "numeric_domain_invalid"}

    cutoff_ms = open_ms + interval_ms
    return {
        **base,
        "valid": True,
        "reason": None,
        "bar_open_time_ms": open_ms,
        "feature_cutoff_ms": cutoff_ms,
        "available_at_ms": receipt_ms,
        "closed_bar_age_seconds": (receipt_ms - cutoff_ms) / 1000.0,
        "values": values,
    }
