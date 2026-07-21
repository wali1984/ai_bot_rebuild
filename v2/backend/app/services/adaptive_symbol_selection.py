"""Point-in-time-safe adaptive symbol ranking and scope selection.

This module deliberately does not place orders or grant execution authority.
It separates three concepts that were previously conflated by the public
symbol-universe payload:

* data-collection ranking (market data can be collected broadly),
* training eligibility (closed/final, available data and pipeline readiness),
* trading-universe eligibility (training readiness plus genuine out-of-sample,
  after-cost evidence).

Every clock used by the selector is part of the input contract.  Missing,
future, stale, out-of-order, or non-finite evidence fails closed.  Preferred
majors receive retention/ordering preference only after satisfying the same
health checks as every other symbol.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from v2.backend.app.services.v2_symbol_runtime_universe import (
    MANDATORY_PREFERRED_MAJOR_SYMBOLS,
    PREFERRED_MAJOR_SYMBOLS,
    is_valid_runtime_symbol,
)

SCHEMA_VERSION = "v2_adaptive_symbol_selection_v1"
MAX_EVIDENCE_ROWS = 4096


@dataclass(frozen=True)
class AdaptiveSymbolSelectionPolicy:
    """Bounded selector thresholds; none of these authorize execution."""

    min_closed_candle_count: int = 72
    min_market_data_coverage_ratio: float = 0.95
    max_feature_age_seconds: float = 15.0 * 60.0
    max_executability_age_seconds: float = 2.0 * 60.0
    min_closed_quote_volume_usd: float = 100_000.0
    target_closed_quote_volume_usd: float = 1_000_000_000.0
    min_top_book_depth_usd: float = 100.0
    target_top_book_depth_usd: float = 1_000_000.0
    max_spread_bps: float = 30.0
    min_realized_volatility_bps: float = 1.0
    target_realized_volatility_bps: float = 150.0
    max_realized_volatility_bps: float = 5_000.0
    target_absolute_move_bps: float = 300.0
    min_validation_samples: int = 30
    min_after_cost_expectancy_bps: float = 0.0
    min_after_cost_ci_lower_bps: float = 0.0
    target_after_cost_expectancy_bps: float = 20.0
    target_after_cost_ci_lower_bps: float = 10.0
    training_entry_score: float = 0.50
    training_exit_score: float = 0.42
    trading_entry_score: float = 0.55
    trading_exit_score: float = 0.48
    training_max_symbols: int = 80
    trading_max_symbols: int = 25
    max_training_additions_per_cycle: int = 8
    max_training_removals_per_cycle: int = 8
    max_trading_additions_per_cycle: int = 3
    max_trading_removals_per_cycle: int = 3
    preferred_major_score_bonus: float = 0.03

    def validate(self) -> None:
        numeric = asdict(self)
        try:
            numeric_invalid = any(
                type(value) not in (int, float) or not math.isfinite(float(value))
                for value in numeric.values()
            )
        except (OverflowError, TypeError, ValueError):
            numeric_invalid = True
        if numeric_invalid:
            raise ValueError("adaptive_symbol_policy_nonfinite_or_nonnumeric")
        integer_fields = (
            "min_closed_candle_count",
            "min_validation_samples",
            "training_max_symbols",
            "trading_max_symbols",
            "max_training_additions_per_cycle",
            "max_training_removals_per_cycle",
            "max_trading_additions_per_cycle",
            "max_trading_removals_per_cycle",
        )
        if any(type(numeric[field]) is not int for field in integer_fields):
            raise ValueError("adaptive_symbol_policy_integer_bound_invalid")
        if self.min_closed_candle_count < 2:
            raise ValueError("adaptive_symbol_policy_min_closed_candles_invalid")
        if not 0.0 < self.min_market_data_coverage_ratio <= 1.0:
            raise ValueError("adaptive_symbol_policy_coverage_invalid")
        if self.max_feature_age_seconds <= 0.0:
            raise ValueError("adaptive_symbol_policy_feature_age_invalid")
        if self.max_executability_age_seconds <= 0.0:
            raise ValueError("adaptive_symbol_policy_executability_age_invalid")
        if self.min_closed_quote_volume_usd <= 0.0:
            raise ValueError("adaptive_symbol_policy_min_volume_invalid")
        if self.min_top_book_depth_usd <= 0.0:
            raise ValueError("adaptive_symbol_policy_min_depth_invalid")
        if self.max_spread_bps <= 0.0:
            raise ValueError("adaptive_symbol_policy_spread_invalid")
        if self.target_absolute_move_bps <= 0.0:
            raise ValueError("adaptive_symbol_policy_move_target_invalid")
        if self.min_validation_samples < 1:
            raise ValueError("adaptive_symbol_policy_validation_samples_invalid")
        if (
            self.min_after_cost_expectancy_bps < 0.0
            or self.target_after_cost_expectancy_bps
            <= self.min_after_cost_expectancy_bps
        ):
            raise ValueError("adaptive_symbol_policy_expectancy_targets_invalid")
        if (
            self.min_after_cost_ci_lower_bps < 0.0
            or self.target_after_cost_ci_lower_bps
            <= self.min_after_cost_ci_lower_bps
        ):
            raise ValueError("adaptive_symbol_policy_ci_targets_invalid")
        if not 0.0 <= self.training_exit_score <= self.training_entry_score <= 1.0:
            raise ValueError("adaptive_symbol_policy_training_hysteresis_invalid")
        if not 0.0 <= self.trading_exit_score <= self.trading_entry_score <= 1.0:
            raise ValueError("adaptive_symbol_policy_trading_hysteresis_invalid")
        if not 0.0 <= self.preferred_major_score_bonus <= 1.0:
            raise ValueError("adaptive_symbol_policy_preferred_bonus_invalid")
        if self.training_max_symbols < 1 or self.trading_max_symbols < 1:
            raise ValueError("adaptive_symbol_policy_scope_limit_invalid")
        if (
            min(
                self.max_training_additions_per_cycle,
                self.max_training_removals_per_cycle,
                self.max_trading_additions_per_cycle,
                self.max_trading_removals_per_cycle,
            )
            < 0
        ):
            raise ValueError("adaptive_symbol_policy_turnover_limit_invalid")
        if self.target_closed_quote_volume_usd <= self.min_closed_quote_volume_usd:
            raise ValueError("adaptive_symbol_policy_volume_targets_invalid")
        if self.target_top_book_depth_usd <= self.min_top_book_depth_usd:
            raise ValueError("adaptive_symbol_policy_depth_targets_invalid")
        if not (
            0.0
            < self.min_realized_volatility_bps
            < self.target_realized_volatility_bps
            < self.max_realized_volatility_bps
        ):
            raise ValueError("adaptive_symbol_policy_volatility_targets_invalid")


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _clock_seconds(value: Any) -> float | None:
    """Parse an aware ISO clock or an epoch in seconds/milliseconds."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = _finite(value)
        if number is None or number <= 0:
            return None
        if number > 1.0e17:  # nanoseconds
            number /= 1.0e9
        elif number > 1.0e14:  # microseconds
            number /= 1.0e6
        elif number > 1.0e11:  # milliseconds
            number /= 1.0e3
        try:
            dt.datetime.fromtimestamp(number, tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None
        return number
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        seconds = parsed.timestamp()
        dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return seconds


def _iso(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def _bounded_ratio(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _log_ratio(value: float, low: float, high: float) -> float:
    if value <= 0 or low <= 0 or high <= low:
        return 0.0
    return _bounded_ratio(math.log10(value), math.log10(low), math.log10(high))


def _symbols(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        symbol = str(item or "").strip().upper()
        if is_valid_runtime_symbol(symbol) and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def _validation_state(
    row: Mapping[str, Any],
    *,
    decision_seconds: float,
    feature_cutoff_seconds: float | None,
    policy: AdaptiveSymbolSelectionPolicy,
) -> tuple[str, list[str], float, dict[str, Any]]:
    blockers: list[str] = []
    source_blockers = row.get("validation_source_blockers")
    if isinstance(source_blockers, Sequence) and not isinstance(
        source_blockers, str | bytes | bytearray
    ):
        blockers.extend(
            f"source:{str(item)}" for item in source_blockers if str(item)
        )
    sample_count = row.get("validation_sample_count")
    expectancy = _finite(row.get("after_cost_expectancy_bps"))
    ci_lower = _finite(row.get("after_cost_ci_lower_bps"))
    clocks: dict[str, float] = {}
    for field in (
        "validation_cutoff",
        "validation_event_time",
        "validation_ingested_at",
        "validation_available_at",
        "validation_generated_at",
    ):
        parsed = _clock_seconds(row.get(field))
        if parsed is None:
            blockers.append(f"missing_or_invalid_{field}")
        else:
            clocks[field] = parsed

    if type(sample_count) is not int or sample_count < policy.min_validation_samples:
        blockers.append("insufficient_oos_validation_samples")
    if expectancy is None:
        blockers.append("missing_or_nonfinite_after_cost_expectancy")
    elif expectancy <= policy.min_after_cost_expectancy_bps:
        blockers.append("after_cost_expectancy_not_positive")
    if ci_lower is None:
        blockers.append("missing_or_nonfinite_after_cost_ci_lower")
    elif ci_lower <= policy.min_after_cost_ci_lower_bps:
        blockers.append("after_cost_ci_lower_not_positive")
    if row.get("validation_out_of_sample") is not True:
        blockers.append("validation_not_explicitly_out_of_sample")
    if row.get("validation_after_cost") is not True:
        blockers.append("validation_not_explicitly_after_cost")
    if row.get("validation_leakage_free") is not True:
        blockers.append("validation_not_explicitly_leakage_free")

    ordered_fields = (
        "validation_cutoff",
        "validation_event_time",
        "validation_ingested_at",
        "validation_available_at",
        "validation_generated_at",
    )
    if all(field in clocks for field in ordered_fields):
        ordered_values = [clocks[field] for field in ordered_fields]
        if any(
            left > right for left, right in zip(ordered_values, ordered_values[1:], strict=False)
        ):
            blockers.append("validation_temporal_order_invalid")
        if clocks["validation_generated_at"] > decision_seconds:
            blockers.append("validation_available_after_decision_time")
        if (
            feature_cutoff_seconds is not None
            and clocks["validation_cutoff"] >= feature_cutoff_seconds
        ):
            blockers.append("validation_cutoff_not_before_feature_cutoff")

    blockers = sorted(set(blockers))
    if blockers:
        state = "unavailable" if sample_count in (None, 0) else "invalid_or_not_proven"
        score = 0.0
    else:
        assert expectancy is not None and ci_lower is not None
        sample_score = min(1.0, float(sample_count) / float(policy.min_validation_samples * 3))
        expectancy_score = _bounded_ratio(
            expectancy,
            policy.min_after_cost_expectancy_bps,
            policy.target_after_cost_expectancy_bps,
        )
        ci_score = _bounded_ratio(
            ci_lower,
            policy.min_after_cost_ci_lower_bps,
            policy.target_after_cost_ci_lower_bps,
        )
        score = 0.25 * sample_score + 0.35 * expectancy_score + 0.40 * ci_score
        state = "proven_oos_after_cost"

    return (
        state,
        blockers,
        round(score, 8),
        {
            "sample_count": sample_count if type(sample_count) is int else None,
            "after_cost_expectancy_bps": expectancy,
            "after_cost_ci_lower_bps": ci_lower,
            "clocks": {field: _iso(value) for field, value in clocks.items()},
        },
    )


def _evaluate_row(
    row: Mapping[str, Any],
    *,
    decision_seconds: float,
    preferred: set[str],
    preferred_ranks: Mapping[str, int],
    policy: AdaptiveSymbolSelectionPolicy,
) -> dict[str, Any] | None:
    symbol = str(row.get("symbol") or "").strip().upper()
    if not is_valid_runtime_symbol(symbol):
        return None

    blockers: list[str] = []
    source_blockers = row.get("source_blockers")
    if isinstance(source_blockers, Sequence) and not isinstance(
        source_blockers, str | bytes | bytearray
    ):
        blockers.extend(f"source:{str(item)}" for item in source_blockers if str(item))

    clocks: dict[str, float] = {}
    for field in (
        "candle_close_time",
        "feature_cutoff",
        "event_time",
        "ingested_at",
        "available_at",
        "market_event_time",
        "market_ingested_at",
        "market_available_at",
        "generated_at",
    ):
        parsed = _clock_seconds(row.get(field))
        if parsed is None:
            blockers.append(f"missing_or_invalid_{field}")
        else:
            clocks[field] = parsed

    if row.get("exchange_confirmed") is not True:
        blockers.append("exchange_not_confirmed")
    if row.get("candle_final") is not True:
        blockers.append("candle_not_explicitly_final")
    if row.get("training_data_ready") is not True:
        blockers.append("training_data_pipeline_not_ready")

    candle_fields = (
        "candle_close_time",
        "feature_cutoff",
        "event_time",
        "ingested_at",
        "available_at",
    )
    if all(field in clocks for field in candle_fields):
        values = [clocks[field] for field in candle_fields]
        if abs(clocks["candle_close_time"] - clocks["feature_cutoff"]) > 0.001:
            blockers.append("feature_cutoff_not_latest_final_candle_close")
        if any(left > right for left, right in zip(values, values[1:], strict=False)):
            blockers.append("candle_temporal_order_invalid")
        if clocks["candle_close_time"] >= decision_seconds:
            blockers.append("candle_close_not_before_decision_time")
        if decision_seconds - clocks["feature_cutoff"] > policy.max_feature_age_seconds:
            blockers.append("closed_market_data_stale")

    market_fields = ("market_event_time", "market_ingested_at", "market_available_at")
    if all(field in clocks for field in market_fields):
        values = [clocks[field] for field in market_fields]
        if any(left > right for left, right in zip(values, values[1:], strict=False)):
            blockers.append("executability_temporal_order_invalid")
        if clocks["market_available_at"] > decision_seconds:
            blockers.append("executability_available_after_decision_time")
        if decision_seconds - clocks["market_available_at"] > policy.max_executability_age_seconds:
            blockers.append("executability_snapshot_stale")
    if "generated_at" in clocks:
        latest_available = max(
            clocks.get("available_at", 0.0), clocks.get("market_available_at", 0.0)
        )
        if clocks["generated_at"] < latest_available:
            blockers.append("evidence_generated_before_source_available")
        if clocks["generated_at"] > decision_seconds:
            blockers.append("evidence_generated_after_decision_time")

    numeric_fields = {
        "market_data_coverage_ratio": _finite(row.get("market_data_coverage_ratio")),
        "closed_quote_volume_usd": _finite(row.get("closed_quote_volume_usd")),
        "spread_bps": _finite(row.get("spread_bps")),
        "top_book_depth_usd": _finite(row.get("top_book_depth_usd")),
        "realized_volatility_bps": _finite(row.get("realized_volatility_bps")),
        "absolute_move_bps": _finite(row.get("absolute_move_bps")),
    }
    for field, value in numeric_fields.items():
        if value is None:
            blockers.append(f"missing_or_nonfinite_{field}")

    candle_count = row.get("closed_candle_count")
    if type(candle_count) is not int:
        blockers.append("missing_or_invalid_closed_candle_count")
    elif candle_count < policy.min_closed_candle_count:
        blockers.append("closed_candle_coverage_short")

    coverage = numeric_fields["market_data_coverage_ratio"]
    volume = numeric_fields["closed_quote_volume_usd"]
    spread = numeric_fields["spread_bps"]
    depth = numeric_fields["top_book_depth_usd"]
    volatility = numeric_fields["realized_volatility_bps"]
    move = numeric_fields["absolute_move_bps"]
    if coverage is not None and not 0.0 <= coverage <= 1.0:
        blockers.append("market_data_coverage_ratio_out_of_range")
    elif coverage is not None and coverage < policy.min_market_data_coverage_ratio:
        blockers.append("market_data_coverage_below_minimum")
    if volume is not None and volume < policy.min_closed_quote_volume_usd:
        blockers.append("closed_quote_volume_below_minimum")
    if spread is not None and (spread < 0.0 or spread > policy.max_spread_bps):
        blockers.append("spread_not_executable")
    if depth is not None and depth < policy.min_top_book_depth_usd:
        blockers.append("top_book_depth_below_minimum")
    if volatility is not None and not (
        policy.min_realized_volatility_bps <= volatility <= policy.max_realized_volatility_bps
    ):
        blockers.append("realized_volatility_outside_opportunity_bounds")
    if move is not None and move < 0.0:
        blockers.append("absolute_move_negative")

    component_scores = {
        "liquidity_executability": 0.0,
        "data_coverage_freshness": 0.0,
        "volatility_move_opportunity": 0.0,
        "validated_predictability_benefit": 0.0,
    }
    if volume is not None and spread is not None and depth is not None:
        volume_score = _log_ratio(
            volume,
            policy.min_closed_quote_volume_usd,
            policy.target_closed_quote_volume_usd,
        )
        depth_score = _log_ratio(
            depth,
            policy.min_top_book_depth_usd,
            policy.target_top_book_depth_usd,
        )
        spread_score = 1.0 - _bounded_ratio(spread, 0.0, policy.max_spread_bps)
        component_scores["liquidity_executability"] = round(
            0.45 * volume_score + 0.30 * depth_score + 0.25 * spread_score, 8
        )
    if coverage is not None and "feature_cutoff" in clocks:
        freshness_score = 1.0 - _bounded_ratio(
            decision_seconds - clocks["feature_cutoff"],
            0.0,
            policy.max_feature_age_seconds,
        )
        component_scores["data_coverage_freshness"] = round(
            0.70 * max(0.0, min(1.0, coverage)) + 0.30 * freshness_score, 8
        )
    if volatility is not None and move is not None:
        volatility_score = _bounded_ratio(
            volatility,
            policy.min_realized_volatility_bps,
            policy.target_realized_volatility_bps,
        )
        move_score = _bounded_ratio(move, 0.0, policy.target_absolute_move_bps)
        component_scores["volatility_move_opportunity"] = round(
            0.65 * volatility_score + 0.35 * move_score, 8
        )

    validation_state, validation_blockers, validation_score, validation = _validation_state(
        row,
        decision_seconds=decision_seconds,
        feature_cutoff_seconds=clocks.get("feature_cutoff"),
        policy=policy,
    )
    component_scores["validated_predictability_benefit"] = validation_score

    training_blockers = sorted(set(blockers))
    trading_blockers = sorted(set(training_blockers + validation_blockers))
    training_score = (
        0.38 * component_scores["liquidity_executability"]
        + 0.37 * component_scores["data_coverage_freshness"]
        + 0.25 * component_scores["volatility_move_opportunity"]
    )
    trading_score = (
        0.30 * component_scores["liquidity_executability"]
        + 0.25 * component_scores["data_coverage_freshness"]
        + 0.20 * component_scores["volatility_move_opportunity"]
        + 0.25 * component_scores["validated_predictability_benefit"]
    )
    if symbol in preferred:
        training_score = min(1.0, training_score + policy.preferred_major_score_bonus)
        trading_score = min(1.0, trading_score + policy.preferred_major_score_bonus)

    return {
        "symbol": symbol,
        "preferred_major": symbol in preferred,
        "preferred_major_rank": preferred_ranks.get(symbol),
        "prior_training_selected": False,
        "prior_trading_selected": False,
        "training_eligible": not training_blockers,
        "trading_eligible": not trading_blockers,
        "training_score": round(training_score, 8),
        "trading_score": round(trading_score, 8),
        "component_scores": component_scores,
        "training_blockers": training_blockers,
        "trading_blockers": trading_blockers,
        "predictability_evidence_state": validation_state,
        "validation_evidence": validation,
        "clocks": {field: _iso(value) for field, value in clocks.items()},
        "selection_reasons": [],
    }


def _rank_key(row: Mapping[str, Any], score_field: str) -> tuple[int, int, float, str]:
    # Preference never changes eligibility; it only reserves first consideration
    # among already-eligible candidates.
    return (
        0 if row.get("preferred_major") is True else 1,
        int(row["preferred_major_rank"])
        if row.get("preferred_major") is True and type(row.get("preferred_major_rank")) is int
        else 1_000_000,
        -float(row.get(score_field) or 0.0),
        str(row.get("symbol") or ""),
    )


def _stable_membership(
    evaluations: dict[str, dict[str, Any]],
    *,
    scope: str,
    previous: list[str] | None,
    entry_score: float,
    exit_score: float,
    max_symbols: int,
    max_additions: int,
    max_removals: int,
) -> tuple[list[str], dict[str, Any]]:
    eligible_field = f"{scope}_eligible"
    score_field = f"{scope}_score"
    ranked_eligible = sorted(
        (row for row in evaluations.values() if row[eligible_field]),
        key=lambda row: _rank_key(row, score_field),
    )
    eligible_by_symbol = {row["symbol"]: row for row in ranked_eligible}

    # No prior state means a bounded bootstrap, not a turnover event.
    if previous is None:
        admitted = [
            row
            for row in ranked_eligible
            if row[score_field] >= entry_score
            or (row["preferred_major"] and row[score_field] >= exit_score)
        ][:max_symbols]
        selected = [row["symbol"] for row in admitted]
        for symbol in selected:
            evaluations[symbol]["selection_reasons"].append(f"{scope}_bootstrap_selected")
        return selected, {
            "previous_state_present": False,
            "added_symbols": selected,
            "removed_symbols": [],
            "forced_health_removals": [],
            "deferred_exit_symbols": [],
            "max_additions_per_cycle": max_additions,
            "max_removals_per_cycle": max_removals,
            "bootstrap_not_turnover_limited": True,
        }

    prior = _symbols(previous)
    prior_set = set(prior)
    for symbol in prior:
        if symbol in evaluations:
            evaluations[symbol][f"prior_{scope}_selected"] = True

    forced_removals = sorted(symbol for symbol in prior if symbol not in eligible_by_symbol)
    healthy_prior = [symbol for symbol in prior if symbol in eligible_by_symbol]
    exit_candidates = sorted(
        (
            symbol
            for symbol in healthy_prior
            if eligible_by_symbol[symbol][score_field] < exit_score
        ),
        key=lambda symbol: (
            eligible_by_symbol[symbol][score_field],
            symbol,
        ),
    )
    normal_removals = exit_candidates[:max_removals]
    deferred_exits = exit_candidates[max_removals:]
    current = [symbol for symbol in healthy_prior if symbol not in set(normal_removals)]

    # If a prior scope was oversized, shrink it gradually without retaining an
    # unhealthy symbol.  Forced health removals are intentionally never capped.
    removal_budget_left = max(0, max_removals - len(normal_removals))
    if len(current) > max_symbols and removal_budget_left:
        removable = sorted(
            current,
            key=lambda symbol: (
                eligible_by_symbol[symbol]["preferred_major"],
                eligible_by_symbol[symbol][score_field],
                symbol,
            ),
        )
        overflow_removals = removable[: min(len(current) - max_symbols, removal_budget_left)]
        normal_removals.extend(overflow_removals)
        current = [symbol for symbol in current if symbol not in set(overflow_removals)]

    candidates = [
        row
        for row in ranked_eligible
        if row["symbol"] not in set(current)
        and row["symbol"] not in prior_set
        and (
            row[score_field] >= entry_score
            or (row["preferred_major"] and row[score_field] >= exit_score)
        )
    ]
    slots = max(0, max_symbols - len(current))
    additions = [row["symbol"] for row in candidates[: min(max_additions, slots)]]
    current.extend(additions)
    selected = [row["symbol"] for row in ranked_eligible if row["symbol"] in set(current)]
    # Deferred exits can make the current scope temporarily exceed max_symbols;
    # they remain visible and block additions until churn catches up.
    for symbol in selected:
        reason = f"{scope}_retained_by_hysteresis" if symbol in prior_set else f"{scope}_added"
        evaluations[symbol]["selection_reasons"].append(reason)
    for symbol in forced_removals:
        if symbol in evaluations:
            evaluations[symbol]["selection_reasons"].append(f"{scope}_forced_health_removal")
    for symbol in deferred_exits:
        evaluations[symbol]["selection_reasons"].append(f"{scope}_exit_deferred_by_turnover_limit")
    return selected, {
        "previous_state_present": True,
        "added_symbols": additions,
        "removed_symbols": sorted(set(forced_removals + normal_removals)),
        "forced_health_removals": forced_removals,
        "deferred_exit_symbols": deferred_exits,
        "max_additions_per_cycle": max_additions,
        "max_removals_per_cycle": max_removals,
        "bootstrap_not_turnover_limited": False,
    }


def select_adaptive_symbol_universe(
    evidence_rows: Iterable[Mapping[str, Any]],
    *,
    decision_time: Any,
    previous_state: Mapping[str, Any] | None = None,
    preferred_symbols: Sequence[str] = PREFERRED_MAJOR_SYMBOLS,
    policy: AdaptiveSymbolSelectionPolicy | None = None,
) -> dict[str, Any]:
    """Rank evidence and return separate, bounded training/trading scopes.

    ``trading_eligible`` means eligible for the *candidate universe* only.
    The returned payload explicitly denies execution authority; all downstream
    health, risk, position-transition, and order gates remain mandatory.
    """

    policy = policy or AdaptiveSymbolSelectionPolicy()
    policy.validate()
    decision_seconds = _clock_seconds(decision_time)
    if decision_seconds is None:
        raise ValueError("adaptive_symbol_selection_decision_time_invalid")
    rows = list(evidence_rows)
    if len(rows) > MAX_EVIDENCE_ROWS:
        raise ValueError("adaptive_symbol_selection_evidence_row_limit_exceeded")
    preferred_list = _symbols(
        (*MANDATORY_PREFERRED_MAJOR_SYMBOLS, *preferred_symbols)
    )
    preferred = set(preferred_list)
    preferred_ranks = {symbol: index for index, symbol in enumerate(preferred_list)}

    evaluations: dict[str, dict[str, Any]] = {}
    invalid_symbol_row_count = 0
    duplicate_symbol_row_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            invalid_symbol_row_count += 1
            continue
        evaluated = _evaluate_row(
            row,
            decision_seconds=decision_seconds,
            preferred=preferred,
            preferred_ranks=preferred_ranks,
            policy=policy,
        )
        if evaluated is None:
            invalid_symbol_row_count += 1
            continue
        symbol = evaluated["symbol"]
        if symbol in evaluations:
            # Ambiguous duplicated evidence is never merged or cherry-picked.
            duplicate_symbol_row_count += 1
            evaluations[symbol]["training_eligible"] = False
            evaluations[symbol]["trading_eligible"] = False
            evaluations[symbol]["training_blockers"] = sorted(
                set(evaluations[symbol]["training_blockers"] + ["duplicate_symbol_evidence"])
            )
            evaluations[symbol]["trading_blockers"] = sorted(
                set(evaluations[symbol]["trading_blockers"] + ["duplicate_symbol_evidence"])
            )
            continue
        evaluations[symbol] = evaluated

    previous_selection = previous_state or {}
    previous_training_raw = previous_selection.get("training_selected_symbols")
    previous_trading_raw = previous_selection.get("trading_selected_symbols")
    previous_training = (
        _symbols(previous_training_raw) if previous_training_raw is not None else None
    )
    previous_trading = _symbols(previous_trading_raw) if previous_trading_raw is not None else None
    training_selected, training_turnover = _stable_membership(
        evaluations,
        scope="training",
        previous=previous_training,
        entry_score=policy.training_entry_score,
        exit_score=policy.training_exit_score,
        max_symbols=policy.training_max_symbols,
        max_additions=policy.max_training_additions_per_cycle,
        max_removals=policy.max_training_removals_per_cycle,
    )
    trading_selected, trading_turnover = _stable_membership(
        evaluations,
        scope="trading",
        previous=previous_trading,
        entry_score=policy.trading_entry_score,
        exit_score=policy.trading_exit_score,
        max_symbols=policy.trading_max_symbols,
        max_additions=policy.max_trading_additions_per_cycle,
        max_removals=policy.max_trading_removals_per_cycle,
    )
    training_selected_set = set(training_selected)
    trading_outside_training = [
        symbol for symbol in trading_selected if symbol not in training_selected_set
    ]
    if trading_outside_training:
        excluded = set(trading_outside_training)
        prior_trading_set = set(previous_trading or [])
        forced_cross_scope_removals = sorted(excluded & prior_trading_set)
        trading_selected = [symbol for symbol in trading_selected if symbol not in excluded]
        trading_turnover["added_symbols"] = [
            symbol for symbol in trading_turnover["added_symbols"] if symbol not in excluded
        ]
        trading_turnover["cross_scope_excluded_symbols"] = trading_outside_training
        trading_turnover["forced_training_scope_removals"] = forced_cross_scope_removals
        trading_turnover["removed_symbols"] = sorted(
            set(trading_turnover["removed_symbols"]) | set(forced_cross_scope_removals)
        )
        for symbol in trading_outside_training:
            evaluations[symbol]["selection_reasons"].append(
                "trading_excluded_outside_current_training_scope"
            )
    else:
        trading_turnover["cross_scope_excluded_symbols"] = []
        trading_turnover["forced_training_scope_removals"] = []

    training_ranked = sorted(evaluations.values(), key=lambda row: _rank_key(row, "training_score"))
    trading_ranked = sorted(evaluations.values(), key=lambda row: _rank_key(row, "trading_score"))
    training_eligible = [row["symbol"] for row in training_ranked if row["training_eligible"]]
    trading_eligible = [row["symbol"] for row in trading_ranked if row["trading_eligible"]]
    preferred_status = {
        symbol: {
            "evidence_present": symbol in evaluations,
            "training_eligible": bool(evaluations.get(symbol, {}).get("training_eligible") is True),
            "trading_eligible": bool(evaluations.get(symbol, {}).get("trading_eligible") is True),
            "preference_bypassed_health_checks": False,
        }
        for symbol in preferred_list
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "decision_time": _iso(decision_seconds),
        "preferred_symbols": preferred_list,
        "preferred_symbol_status": preferred_status,
        "training_ranked_symbols": [row["symbol"] for row in training_ranked],
        "trading_ranked_symbols": [row["symbol"] for row in trading_ranked],
        "training_eligible_symbols": training_eligible,
        "trading_eligible_symbols": trading_eligible,
        "training_selected_symbols": training_selected,
        "trading_selected_symbols": trading_selected,
        "trading_selected_subset_of_training_selected": set(trading_selected).issubset(
            training_selected_set
        ),
        "symbol_explanations": {symbol: evaluations[symbol] for symbol in sorted(evaluations)},
        "turnover": {
            "training": training_turnover,
            "trading": trading_turnover,
        },
        "metrics": {
            "evidence_row_count": len(rows),
            "evaluated_symbol_count": len(evaluations),
            "invalid_symbol_row_count": invalid_symbol_row_count,
            "duplicate_symbol_row_count": duplicate_symbol_row_count,
            "training_eligible_count": len(training_eligible),
            "trading_eligible_count": len(trading_eligible),
            "training_selected_count": len(training_selected),
            "trading_selected_count": len(trading_selected),
            "predictability_proven_symbol_count": sum(
                row["predictability_evidence_state"] == "proven_oos_after_cost"
                for row in evaluations.values()
            ),
        },
        "policy": asdict(policy),
        "selection_is_execution_authorization": False,
        "rankings_are_opportunity_and_feasibility_candidates_not_forecasts": True,
        "guaranteed_return_claim": False,
        "guaranteed_1000x_claim": False,
        "downstream_health_risk_position_and_order_gates_required": True,
        "uses_current_prediction_confidence_as_proven_benefit": False,
        "uses_unvalidated_altdata_score_as_proven_benefit": False,
    }
