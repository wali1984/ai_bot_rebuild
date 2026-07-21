from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any

from .accounting import coerce_float
from .caps import PaperExposureCaps, evaluate_exposure_caps
from .exits import PAPER_EXIT_POLICY_VERSION, PaperExitConfig, effective_atr_stop_bps, evaluate_exit
from .generation_identity import (
    closed_generation_match,
    entry_generation_identity,
    normalize_timestamp,
)
from .hedging import evaluate_adaptive_hedge_trigger, evaluate_adaptive_hedge_unwind
from .market_price_evidence import verify_market_price_evidence
from .netting import classify_fill
from .outcomes import build_close_event, capture_close_outcome_availability
from .policy_funding_repair import repair_policy_funding_rows
from .position_state import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    PAPER_POSITION_RECONSTRUCTION_PERSISTENCE_FIELDS,
    PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION,
    PaperNetPosition,
    first_present,
    position_from_fill,
    seconds_between,
    utc_iso_from_any,
    utc_now_iso,
    validate_paper_position_reconstruction,
)

_ADAPTIVE_CAPITAL_REQUIRED_FIELDS = (
    "risk_budget_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "recommended_leverage",
    "effective_leverage",
    "recommended_margin_mode",
    "stop_distance_bps",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "expected_fees_usd",
    "expected_slippage_usd",
    "expected_funding_usd",
    "expected_net_pnl_usd",
    "expected_shortfall_usd",
    "hedge_budget_usd",
    "capital_allocation_reason",
)

_ADAPTIVE_CAPITAL_CARRY_FIELDS = (
    "adaptive_capital_policy_version",
    "policy_activated_at",
    "gross_notional_usd",
    "allocated_margin_usd",
    "effective_leverage",
    "recommended_leverage",
    "recommended_margin_mode",
    "margin_mode_simulated",
    "maintenance_margin_rate",
    "maintenance_margin_cum",
    "maintenance_margin_estimate",
    "maintenance_margin_notional_usd",
    "maintenance_margin_mark_price",
    "maintenance_margin_mark_time",
    "maintenance_bracket_id",
    "maintenance_bracket_maint_margin_ratio",
    "maintenance_bracket_cum",
    "maintenance_bracket_max_initial_leverage",
    "maintenance_bracket_evidence_hash",
    "maintenance_bracket_evidence_checksum_sha256",
    "maintenance_bracket_evidence_hmac_sha256",
    "maintenance_bracket_binding",
    "maintenance_bracket_environment_id",
    "maintenance_bracket_key_id",
    "maintenance_bracket_source",
    "maintenance_bracket_available_at",
    "maintenance_bracket_expires_at",
    "maintenance_bracket_consumer_observed_at",
    "maintenance_bracket_prevalidated",
    "maintenance_bracket_evidence_status",
    "maintenance_bracket_evidence_reason",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "risk_budget_usd",
    "risk_budget_source",
    "stop_distance_bps",
    "expected_fees_usd",
    "expected_funding_bps",
    "funding_rate",
    "funding_interval_seconds",
    "expected_funding_usd",
    "expected_net_pnl_usd",
    "expected_shortfall_usd",
    "hedge_budget_usd",
    "capital_allocation_reason",
)

_PAPER_NETTING_FILL_RECEIPT_SCHEMA_VERSION = "PAPER_NETTING_FILL_RECEIPT_V1"


@dataclass(frozen=True)
class PaperLifecycleConfig:
    exposure_caps: PaperExposureCaps = PaperExposureCaps()
    exit_config: PaperExitConfig = PaperExitConfig()
    # Fallback execution-cost rates are per side, not pre-summed round-trip
    # rates. A close charges the entry notional once and the exit notional once.
    fee_bps: float = 4.0
    slippage_bps: float = 2.0
    allow_explicit_hedge: bool = False
    # Portfolio drawdown (bps) at cycle start; feeds the adaptive hedge
    # trigger's drawdown pressure term when explicit hedging is enabled.
    portfolio_drawdown_bps: float = 0.0
    portfolio_equity_usdt: float | None = None
    disable_trailing_on_negative_runtime_expectancy: bool = False
    trailing_runtime_min_closed_trades: int = 50
    trailing_runtime_min_win_rate: float = 0.40
    trailing_runtime_min_pnl_usd: float = 0.0
    trailing_expectancy_evidence_policy_version: str | None = None
    enable_contextual_trailing_policy: bool = True
    trailing_context_min_closed_trades: int = 20
    trailing_context_min_win_rate: float = 0.40
    trailing_context_min_pnl_usd: float = 0.0


def _fill_identity(row: dict[str, Any]) -> str:
    for key in ("fill_id", "ledger_row_id", "intent_id", "signal_id", "prediction_id", "source_prediction_id"):
        value = row.get(key)
        if value:
            return str(value)
    return f"{row.get('symbol')}:{row.get('timeframe')}:{row.get('side')}"


def _close_proves_generation_fully_consumed(closed: dict[str, Any]) -> bool:
    """Return true only when the close proves no quantity remained.

    A partial close carries every entry fill id for lineage, but that does not
    mean every fill was fully consumed.  Suppressing those ids on restart would
    delete the remainder.  New close rows bind the answer directly through the
    exact entry-cost allocation receipt; older rows need equivalent quantity
    evidence and otherwise stay unsuppressed.
    """

    explicit = closed.get("entry_cost_is_final_close")
    if explicit is False:
        return False
    pre_close = coerce_float(closed.get("entry_cost_pre_close_quantity"))
    closed_quantity = coerce_float(
        first_present(
            closed.get("entry_cost_closed_quantity"),
            closed.get("closed_quantity"),
        )
    )
    if pre_close is not None and pre_close > 0.0 and closed_quantity is not None:
        quantity_proves_final = closed_quantity >= pre_close or math.isclose(
            pre_close,
            closed_quantity,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        return explicit is True and quantity_proves_final
    remaining = coerce_float(
        first_present(
            closed.get("remaining_quantity_after_close"),
            closed.get("position_remaining_quantity"),
        )
    )
    return (
        explicit is True
        and remaining is not None
        and abs(remaining) <= 1e-12
    )


def _closed_generation_evidence(
    fill: dict[str, Any],
    *,
    fill_id: str,
    closed_trades: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for closed in closed_trades:
        if not _close_proves_generation_fully_consumed(closed):
            continue
        evidence = closed_generation_match(
            fill,
            closed,
            accepted_source_identity=fill_id,
        )
        if evidence is not None:
            return {
                **evidence,
                "close_id": closed.get("close_id"),
                "closed_position_id": closed.get("position_id"),
            }
    return None


def _existing_closed_trades(existing_ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows = existing_ledger.get("closed_trades") or existing_ledger.get("closes") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _existing_outcome_labels(existing_ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows = existing_ledger.get("outcome_labels") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _realized_pnl(row: dict[str, Any]) -> float:
    return (
        coerce_float(
            first_present(
                row.get("realized_net_pnl_usd"),
                row.get("realized_net_pnl"),
                row.get("realized_pnl_usd"),
                row.get("realized_pnl_usdt"),
                row.get("realized_pnl"),
            )
        )
        or 0.0
    )


def _first_realized_number(row: dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = coerce_float(row.get(field))
        if value is not None:
            return value
    return None


def _realized_pnl_notional_usd(row: dict[str, Any]) -> float | None:
    notional = _first_realized_number(
        row,
        "gross_notional_usd",
        "gross_notional",
        "notional_usd",
        "notional_usdt",
        "target_notional_usd",
        "target_notional_usdt",
        "order_size_usd",
        "order_size",
    )
    if notional is not None and notional > 0.0:
        return abs(notional)
    quantity = _first_realized_number(row, "closed_quantity", "quantity", "qty")
    entry_price = _first_realized_number(row, "entry_price", "avg_entry_price", "fill_price")
    if quantity is not None and quantity > 0.0 and entry_price is not None and entry_price > 0.0:
        return abs(quantity * entry_price)
    return None


def _normalize_realized_pnl_usd_population(row: dict[str, Any]) -> dict[str, Any]:
    """Populate P-0019 gross/net realized USD aliases on carried paper rows."""

    normalized = dict(row)
    realized_bps = _first_realized_number(
        normalized,
        "realized_pnl_bps",
        "paper_exit_pnl_bps",
        "pnl_bps",
    )
    notional = _realized_pnl_notional_usd(normalized)
    gross_from_bps = None
    if realized_bps is not None and notional is not None and notional > 0.0:
        gross_from_bps = realized_bps / 10000.0 * notional

    existing_gross_usd = _first_realized_number(
        normalized,
        "realized_pnl_usd",
        "realized_pnl_usdt",
        "realized_pnl",
    )
    gross_usd = gross_from_bps if gross_from_bps is not None else existing_gross_usd
    if gross_from_bps is not None:
        if existing_gross_usd is not None and abs(existing_gross_usd - gross_from_bps) > 1e-9:
            normalized["pre_p0019_realized_pnl_usd_value"] = existing_gross_usd
        normalized["realized_pnl_usd_population_source"] = (
            "P0019_DERIVED_FROM_REALIZED_PNL_BPS_AND_GROSS_NOTIONAL_USD"
        )
    elif gross_usd is None and gross_from_bps is not None:
        gross_usd = gross_from_bps
        normalized["realized_pnl_usd_population_source"] = (
            "P0019_DERIVED_FROM_REALIZED_PNL_BPS_AND_GROSS_NOTIONAL_USD"
        )
    if gross_usd is not None:
        normalized["realized_pnl_usd"] = gross_usd
        normalized["realized_pnl_usdt"] = gross_usd
        normalized["realized_pnl"] = gross_usd

    net_usd = _first_realized_number(
        normalized,
        "realized_net_pnl_usd",
        "realized_net_pnl",
    )
    if net_usd is None and gross_usd is not None:
        fees = _first_realized_number(normalized, "fees", "fees_usd", "expected_fees_usd") or 0.0
        slippage = (
            _first_realized_number(
                normalized,
                "slippage",
                "slippage_usd",
                "realized_slippage_usd",
                "expected_slippage_usd",
            )
            or 0.0
        )
        funding = (
            _first_realized_number(
                normalized,
                "funding_pnl_usd",
                "funding_usd",
                "funding",
                "expected_funding_usd",
            )
            or 0.0
        )
        net_usd = gross_usd - fees - slippage + funding
        normalized["realized_net_pnl_usd_population_source"] = (
            "P0019_DERIVED_FROM_REALIZED_PNL_USD_MINUS_COSTS_PLUS_FUNDING"
        )
    if net_usd is not None:
        normalized["realized_net_pnl_usd"] = net_usd
        normalized["realized_net_pnl"] = net_usd
    return normalized


def _normalize_realized_pnl_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _normalize_realized_pnl_usd_population(row)
        for row in rows
        if isinstance(row, dict)
    ]


def _trailing_stop_rows(closed_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in closed_trades
        if str(row.get("close_reason") or row.get("exit_reason") or "") == "TIER_2_TRAILING_STOP"
    ]


def _policy_scoped_rows(
    rows: list[dict[str, Any]],
    policy_version: str | None,
) -> tuple[list[dict[str, Any]], int]:
    if not policy_version:
        return rows, 0
    scoped = [
        row
        for row in rows
        if str(row.get("paper_exit_policy_version") or "") == str(policy_version)
    ]
    return scoped, len(rows) - len(scoped)


def _clean_context_value(value: Any, *, uppercase: bool = False, lowercase: bool = False) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"none", "null", "unknown"}:
        return None
    if uppercase:
        return cleaned.upper()
    if lowercase:
        return cleaned.lower()
    return cleaned


def _trailing_context_fields_from_row(row: dict[str, Any]) -> dict[str, str | None]:
    return {
        "symbol": _clean_context_value(row.get("symbol"), uppercase=True),
        "timeframe": _clean_context_value(row.get("timeframe"), lowercase=True),
        "strategy_mode": _clean_context_value(
            first_present(
                row.get("strategy_selected_mode"),
                row.get("strategy_subtype"),
                row.get("strategy_mode"),
                row.get("entry_reason"),
            ),
            lowercase=True,
        ),
        "market_regime": _clean_context_value(
            first_present(row.get("market_regime_at_entry"), row.get("market_regime_at_exit")),
            lowercase=True,
        ),
    }


def _trailing_context_fields_from_position(position: PaperNetPosition) -> dict[str, str | None]:
    return {
        "symbol": _clean_context_value(position.symbol, uppercase=True),
        "timeframe": _clean_context_value(position.timeframe, lowercase=True),
        "strategy_mode": _clean_context_value(position.strategy_selected_mode or position.strategy_id, lowercase=True),
        "market_regime": _clean_context_value(position.market_regime_at_entry, lowercase=True),
    }


def _trailing_context_key(scope: str, fields: dict[str, str | None]) -> str:
    return "|".join(
        [
            scope,
            fields.get("symbol") or "*",
            fields.get("timeframe") or "*",
            fields.get("strategy_mode") or "*",
            fields.get("market_regime") or "*",
        ]
    )


def _prior_has_complete_adaptive_capital_v1(prior: dict[str, Any]) -> bool:
    allocation = prior.get("adaptive_allocation") if isinstance(prior.get("adaptive_allocation"), dict) else {}
    version = first_present(
        prior.get("adaptive_capital_policy_version"),
        allocation.get("adaptive_capital_policy_version"),
    )
    if str(version or "") != ADAPTIVE_CAPITAL_POLICY_VERSION:
        return False
    return all(first_present(prior.get(field), allocation.get(field)) not in (None, "") for field in _ADAPTIVE_CAPITAL_REQUIRED_FIELDS)


def _position_has_complete_adaptive_capital_v1(position: PaperNetPosition) -> bool:
    allocation = position.adaptive_allocation if isinstance(position.adaptive_allocation, dict) else {}
    version = first_present(
        position.adaptive_capital_policy_version,
        allocation.get("adaptive_capital_policy_version"),
    )
    if str(version or "") != ADAPTIVE_CAPITAL_POLICY_VERSION:
        return False
    return all(
        first_present(getattr(position, field, None), allocation.get(field)) not in (None, "")
        for field in _ADAPTIVE_CAPITAL_REQUIRED_FIELDS
    )


def _trailing_context_candidates(fields: dict[str, str | None]) -> list[dict[str, Any]]:
    symbol = fields.get("symbol")
    timeframe = fields.get("timeframe")
    strategy_mode = fields.get("strategy_mode")
    market_regime = fields.get("market_regime")
    candidates: list[dict[str, Any]] = []
    if symbol and timeframe and strategy_mode and market_regime:
        candidates.append({
            "scope": "symbol_timeframe_strategy_regime",
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_mode": strategy_mode,
            "market_regime": market_regime,
        })
    if symbol and timeframe and strategy_mode:
        candidates.append({
            "scope": "symbol_timeframe_strategy",
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_mode": strategy_mode,
            "market_regime": None,
        })
    if symbol and timeframe:
        candidates.append({
            "scope": "symbol_timeframe",
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_mode": None,
            "market_regime": None,
        })
    if timeframe and strategy_mode:
        candidates.append({
            "scope": "timeframe_strategy",
            "symbol": None,
            "timeframe": timeframe,
            "strategy_mode": strategy_mode,
            "market_regime": None,
        })
    if timeframe:
        candidates.append({
            "scope": "timeframe",
            "symbol": None,
            "timeframe": timeframe,
            "strategy_mode": None,
            "market_regime": None,
        })
    return candidates


def _finalize_trailing_context_stats(
    raw: dict[str, dict[str, Any]],
    config: PaperLifecycleConfig,
) -> dict[str, dict[str, Any]]:
    finalized: dict[str, dict[str, Any]] = {}
    for key, row in raw.items():
        count = int(row["sample_count"])
        wins = int(row["win_count"])
        pnl = float(row["pnl_usd"])
        win_rate = wins / count if count else None
        enough_samples = count >= int(config.trailing_context_min_closed_trades)
        failed = enough_samples and (
            pnl <= float(config.trailing_context_min_pnl_usd)
            or (win_rate is not None and win_rate < float(config.trailing_context_min_win_rate))
        )
        positive = enough_samples and not failed
        reasons: list[str] = []
        if not enough_samples:
            reasons.append("TRAILING_CONTEXT_SAMPLE_BELOW_MINIMUM")
        if enough_samples and pnl <= float(config.trailing_context_min_pnl_usd):
            reasons.append("TRAILING_CONTEXT_PNL_NOT_POSITIVE")
        if enough_samples and win_rate is not None and win_rate < float(config.trailing_context_min_win_rate):
            reasons.append("TRAILING_CONTEXT_WIN_RATE_BELOW_THRESHOLD")
        finalized[key] = {
            **row,
            "win_rate": win_rate,
            "minimum_sample_count": int(config.trailing_context_min_closed_trades),
            "minimum_win_rate": float(config.trailing_context_min_win_rate),
            "minimum_pnl_usd": float(config.trailing_context_min_pnl_usd),
            "enough_samples": enough_samples,
            "positive_expectancy": positive,
            "failed": failed,
            "reasons": reasons,
        }
    return finalized


def _trailing_stop_context_policy(
    closed_trades: list[dict[str, Any]],
    config: PaperLifecycleConfig,
) -> dict[str, Any]:
    raw: dict[str, dict[str, Any]] = {}
    policy_version = config.trailing_expectancy_evidence_policy_version
    unfiltered_trailing_rows = _trailing_stop_rows(closed_trades)
    trailing_rows, filtered_out_count = _policy_scoped_rows(unfiltered_trailing_rows, policy_version)
    for row in trailing_rows:
        fields = _trailing_context_fields_from_row(row)
        for candidate in _trailing_context_candidates(fields):
            key = _trailing_context_key(str(candidate["scope"]), candidate)
            bucket = raw.setdefault(
                key,
                {
                    "key": key,
                    "scope": candidate["scope"],
                    "symbol": candidate.get("symbol"),
                    "timeframe": candidate.get("timeframe"),
                    "strategy_mode": candidate.get("strategy_mode"),
                    "market_regime": candidate.get("market_regime"),
                    "sample_count": 0,
                    "win_count": 0,
                    "pnl_usd": 0.0,
                },
            )
            bucket["sample_count"] += 1
            pnl = _realized_pnl(row)
            bucket["pnl_usd"] += pnl
            if pnl > 0.0:
                bucket["win_count"] += 1
    stats = _finalize_trailing_context_stats(raw, config)
    return {
        "enabled": bool(config.enable_contextual_trailing_policy),
        "paper_only": True,
        "policy_version_filter_enabled": bool(policy_version),
        "policy_version": policy_version,
        "unfiltered_sample_count": len(unfiltered_trailing_rows),
        "filtered_out_sample_count": filtered_out_count,
        "trailing_sample_count": len(trailing_rows),
        "context_count": len(stats),
        "positive_context_count": sum(1 for row in stats.values() if row["positive_expectancy"]),
        "degraded_context_count": sum(1 for row in stats.values() if row["failed"]),
        "minimum_sample_count": int(config.trailing_context_min_closed_trades),
        "minimum_win_rate": float(config.trailing_context_min_win_rate),
        "minimum_pnl_usd": float(config.trailing_context_min_pnl_usd),
        "stats_by_key": stats,
    }


def _trailing_context_policy_status(policy: dict[str, Any]) -> dict[str, Any]:
    stats = list((policy.get("stats_by_key") or {}).values())
    stats.sort(key=lambda row: (not bool(row.get("failed")), not bool(row.get("positive_expectancy")), str(row.get("key"))))
    return {
        "enabled": bool(policy.get("enabled")),
        "paper_only": True,
        "policy_version_filter_enabled": bool(policy.get("policy_version_filter_enabled")),
        "policy_version": policy.get("policy_version"),
        "unfiltered_sample_count": int(policy.get("unfiltered_sample_count") or 0),
        "filtered_out_sample_count": int(policy.get("filtered_out_sample_count") or 0),
        "trailing_sample_count": int(policy.get("trailing_sample_count") or 0),
        "context_count": int(policy.get("context_count") or 0),
        "positive_context_count": int(policy.get("positive_context_count") or 0),
        "degraded_context_count": int(policy.get("degraded_context_count") or 0),
        "minimum_sample_count": int(policy.get("minimum_sample_count") or 0),
        "minimum_win_rate": policy.get("minimum_win_rate"),
        "minimum_pnl_usd": policy.get("minimum_pnl_usd"),
        "sample_contexts": stats[:25],
    }


def _exit_config_for_trailing_context(
    *,
    position: PaperNetPosition,
    base_exit_config: PaperExitConfig,
    global_circuit_breaker: dict[str, Any],
    context_policy: dict[str, Any],
) -> tuple[PaperExitConfig, dict[str, Any]]:
    global_enabled = bool(base_exit_config.trailing_stop_enabled) and not bool(global_circuit_breaker.get("disabled"))
    decision: dict[str, Any] = {
        "enabled": bool(context_policy.get("enabled")),
        "paper_only": True,
        "symbol": position.symbol,
        "timeframe": position.timeframe,
        "strategy_mode": position.strategy_selected_mode or position.strategy_id,
        "market_regime": position.market_regime_at_entry,
        "global_trailing_stop_enabled": global_enabled,
        "trailing_stop_enabled": global_enabled,
        "selected_context": None,
        "decision_source": "GLOBAL_TRAILING_RUNTIME_CIRCUIT_BREAKER",
        "reasons": list(global_circuit_breaker.get("reasons") or []),
    }
    if not context_policy.get("enabled"):
        return replace(base_exit_config, trailing_stop_enabled=global_enabled), decision
    stats_by_key = context_policy.get("stats_by_key") or {}
    fields = _trailing_context_fields_from_position(position)
    for candidate in _trailing_context_candidates(fields):
        key = _trailing_context_key(str(candidate["scope"]), candidate)
        stats = stats_by_key.get(key)
        if not stats or not stats.get("enough_samples"):
            continue
        decision["selected_context"] = stats
        decision["decision_source"] = "CONTEXTUAL_TRAILING_EXPECTANCY_POLICY"
        if stats.get("failed"):
            decision["trailing_stop_enabled"] = False
            decision["reasons"] = list(stats.get("reasons") or ["TRAILING_CONTEXT_EXPECTANCY_FAILED"])
        elif stats.get("positive_expectancy"):
            decision["trailing_stop_enabled"] = bool(base_exit_config.trailing_stop_enabled)
            decision["reasons"] = ["TRAILING_CONTEXT_EXPECTANCY_POSITIVE"]
        return replace(
            base_exit_config,
            trailing_stop_enabled=bool(decision["trailing_stop_enabled"]),
        ), decision
    if global_circuit_breaker.get("disabled"):
        decision["trailing_stop_enabled"] = False
        decision["reasons"] = list(global_circuit_breaker.get("reasons") or ["GLOBAL_TRAILING_EXPECTANCY_FAILED"])
    return replace(base_exit_config, trailing_stop_enabled=bool(decision["trailing_stop_enabled"])), decision


def _trailing_stop_runtime_circuit_breaker(
    closed_trades: list[dict[str, Any]],
    config: PaperLifecycleConfig,
) -> dict[str, Any]:
    policy_version = config.trailing_expectancy_evidence_policy_version
    unfiltered_trailing_rows = _trailing_stop_rows(closed_trades)
    trailing_rows, filtered_out_count = _policy_scoped_rows(unfiltered_trailing_rows, policy_version)
    count = len(trailing_rows)
    wins = sum(1 for row in trailing_rows if _realized_pnl(row) > 0.0)
    pnl = sum(_realized_pnl(row) for row in trailing_rows)
    win_rate = (wins / count) if count else None
    enough_samples = count >= int(config.trailing_runtime_min_closed_trades)
    expectancy_failed = enough_samples and (
        pnl <= float(config.trailing_runtime_min_pnl_usd)
        or (win_rate is not None and win_rate < float(config.trailing_runtime_min_win_rate))
    )
    disabled = bool(config.disable_trailing_on_negative_runtime_expectancy and expectancy_failed)
    reasons: list[str] = []
    if not config.disable_trailing_on_negative_runtime_expectancy:
        reasons.append("TRAILING_RUNTIME_CIRCUIT_BREAKER_NOT_ENABLED")
    if not enough_samples:
        reasons.append("TRAILING_RUNTIME_SAMPLE_BELOW_MINIMUM")
    if policy_version and not enough_samples:
        reasons.append("TRAILING_RUNTIME_POLICY_SAMPLE_BELOW_MINIMUM")
    if enough_samples and pnl <= float(config.trailing_runtime_min_pnl_usd):
        reasons.append("TRAILING_RUNTIME_PNL_NOT_POSITIVE")
    if enough_samples and win_rate is not None and win_rate < float(config.trailing_runtime_min_win_rate):
        reasons.append("TRAILING_RUNTIME_WIN_RATE_BELOW_THRESHOLD")
    return {
        "enabled": bool(config.disable_trailing_on_negative_runtime_expectancy),
        "trailing_stop_enabled": not disabled,
        "disabled": disabled,
        "disable_reason": "TRAILING_STOP_RUNTIME_EXPECTANCY_CIRCUIT_BREAKER" if disabled else None,
        "reasons": reasons,
        "policy_version_filter_enabled": bool(policy_version),
        "policy_version": policy_version,
        "unfiltered_sample_count": len(unfiltered_trailing_rows),
        "filtered_out_sample_count": filtered_out_count,
        "sample_count": count,
        "minimum_sample_count": int(config.trailing_runtime_min_closed_trades),
        "win_count": wins,
        "win_rate": win_rate,
        "minimum_win_rate": float(config.trailing_runtime_min_win_rate),
        "pnl_usd": pnl,
        "minimum_pnl_usd": float(config.trailing_runtime_min_pnl_usd),
        "paper_only": True,
    }


def _hedge_position_key(symbol: str) -> str:
    return f"{str(symbol).upper()}::HEDGE"


def _is_hedge_child_row(row: dict[str, Any]) -> bool:
    return bool(row.get("hedge_parent_id")) and str(row.get("hedge_state") or "").upper() == "HEDGE_CHILD"


def _prior_positions_by_symbol(existing_ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prior: dict[str, dict[str, Any]] = {}
    positions_by_symbol = existing_ledger.get("positions_by_symbol")
    if isinstance(positions_by_symbol, dict):
        for symbol, row in positions_by_symbol.items():
            if isinstance(row, dict):
                key = str(symbol).upper()
                if _is_hedge_child_row(row) and not key.endswith("::HEDGE"):
                    key = _hedge_position_key(key)
                prior[key] = dict(row)
    for row in existing_ledger.get("open_positions") or []:
        if isinstance(row, dict) and row.get("symbol"):
            key = str(row["symbol"]).upper()
            if _is_hedge_child_row(row):
                key = _hedge_position_key(key)
            prior[key] = dict(row)
    return prior


def _prior_matches_position_generation(
    position: PaperNetPosition,
    prior: dict[str, Any],
) -> bool:
    prior_generation = prior.get("position_generation_id")
    if prior_generation not in (None, ""):
        return str(prior_generation) == str(position.position_generation_id or "")
    prior_position_id = prior.get("position_id")
    if prior_position_id not in (None, "") and str(prior_position_id) == position.position_id:
        return True
    if str(prior.get("symbol") or "").upper() != position.symbol:
        return False
    prior_side = str(prior.get("side") or "").lower()
    if prior_side in {"buy", "long"}:
        prior_side = "long"
    elif prior_side in {"sell", "short"}:
        prior_side = "short"
    if prior_side and prior_side != position.side:
        return False

    prior_entry_ids = {
        str(item)
        for item in (prior.get("source_fill_ids") or [])
        if item not in (None, "")
    }
    prior_entry_fill = first_present(prior.get("entry_fill_id"), prior.get("fill_id"))
    if prior_entry_fill not in (None, ""):
        prior_entry_ids.add(str(prior_entry_fill))
    if prior_entry_ids and position.fill_ids:
        return str(position.fill_ids[0]) in prior_entry_ids

    # Legacy position ids were symbol-static.  Preserve their path/context
    # carry only when the normalized entry timestamp also identifies this exact
    # generation; a later reopen of the same symbol must not inherit old state.
    prior_entry_time = normalize_timestamp(
        first_present(
            prior.get("entry_generation_time_utc"),
            prior.get("entry_time"),
            prior.get("opened_est"),
        )
    )
    current_entry_time = normalize_timestamp(
        first_present(position.entry_generation_time_utc, position.opened_est)
    )
    return bool(
        prior_position_id == position.legacy_position_id
        and prior_entry_time
        and current_entry_time
        and prior_entry_time == current_entry_time
    )


def _carry_prior_position_state(
    position: PaperNetPosition,
    prior: dict[str, Any] | None,
    *,
    require_generation_match: bool = True,
    carry_capital: bool = True,
    restore_economic_snapshot: bool = False,
) -> None:
    if not prior or (
        require_generation_match
        and not _prior_matches_position_generation(position, prior)
    ):
        return
    if restore_economic_snapshot:
        reconstruction_reasons = validate_paper_position_reconstruction(prior)
        if reconstruction_reasons:
            raise ValueError(
                "INVALID_PERSISTED_OPEN_POSITION_RECONSTRUCTION:"
                + ",".join(reconstruction_reasons)
            )
        source_fill_ids = [
            str(value)
            for value in prior.get("source_fill_ids") or []
            if value not in (None, "")
        ]
        quantity = coerce_float(prior.get("net_quantity"))
        avg_entry_price = coerce_float(prior.get("avg_entry_price"))
        if quantity is None or avg_entry_price is None:
            raise ValueError("PERSISTED_POSITION_ECONOMICS_MISSING")
        position.position_id = str(prior["position_id"])
        position.legacy_position_id = (
            str(prior["legacy_position_id"])
            if prior.get("legacy_position_id") not in (None, "")
            else None
        )
        position.position_generation_id = str(prior["position_generation_id"])
        position.position_id_version = str(prior["position_id_version"])
        position.entry_generation_time_utc = str(
            prior["entry_generation_time_utc"]
        )
        position.net_quantity = float(quantity)
        position.avg_entry_price = float(avg_entry_price)
        position.fill_ids = source_fill_ids
        position.realized_pnl = float(coerce_float(prior.get("realized_pnl")) or 0.0)
        for attr in (
            "entry_fees_incurred_usd",
            "entry_fees_remaining_usd",
            "entry_fees_allocated_to_closes_usd",
            "entry_fee_fallback_bps_per_side",
            "entry_slippage_incurred_usd",
            "entry_slippage_remaining_usd",
            "entry_slippage_allocated_to_closes_usd",
            "entry_slippage_fallback_bps_per_side",
        ):
            setattr(position, attr, coerce_float(prior.get(attr)))
        position.entry_fee_cost_sources = [
            str(value)
            for value in prior.get("entry_fee_cost_sources") or []
            if value not in (None, "")
        ]
        position.entry_slippage_cost_sources = [
            str(value)
            for value in prior.get("entry_slippage_cost_sources") or []
            if value not in (None, "")
        ]
        position.entry_cost_basis_status = str(
            prior.get("entry_cost_basis_status") or "MISSING_ENTRY_COST_BASIS"
        )
    best = prior.get("best_favorable_price")
    try:
        best_value = float(best)
    except (TypeError, ValueError):
        best_value = None
    if best_value is not None and best_value > 0:
        if position.side == "long":
            position.best_favorable_price = max(position.best_favorable_price or position.avg_entry_price, best_value)
        else:
            position.best_favorable_price = min(position.best_favorable_price or position.avg_entry_price, best_value)
    opened = prior.get("opened_est")
    if isinstance(opened, str) and opened:
        position.opened_est = opened
    position.strategy_id = first_present(position.strategy_id, prior.get("strategy_id"))
    position.strategy_family = first_present(position.strategy_family, prior.get("strategy_family"))
    position.strategy_selected_mode = first_present(
        position.strategy_selected_mode,
        prior.get("strategy_selected_mode"),
    )
    position.hedge_state = first_present(position.hedge_state, prior.get("hedge_state"))
    position.hedge_reason = first_present(position.hedge_reason, prior.get("hedge_reason"))
    position.hedge_pending_since = first_present(
        position.hedge_pending_since, prior.get("hedge_pending_since")
    )
    position.drawdown_at_entry = first_present(position.drawdown_at_entry, prior.get("drawdown_at_entry"))
    position.market_regime_at_entry = first_present(
        position.market_regime_at_entry,
        prior.get("market_regime_at_entry"),
    )
    position.liquidity_zone_context = first_present(
        position.liquidity_zone_context,
        prior.get("liquidity_zone_context"),
    )
    position.liquidation_distance_context = first_present(
        position.liquidation_distance_context,
        prior.get("liquidation_distance_context"),
    )
    position.microstructure_context = first_present(
        position.microstructure_context,
        prior.get("microstructure_context"),
    )
    position.oi_funding_context = first_present(
        position.oi_funding_context,
        prior.get("oi_funding_context"),
    )
    position.public_intel_context = first_present(
        position.public_intel_context,
        prior.get("public_intel_context"),
    )
    position.major_move_signal_id = first_present(
        position.major_move_signal_id,
        prior.get("major_move_signal_id"),
    )
    position.squeeze_evidence_score = first_present(
        position.squeeze_evidence_score,
        prior.get("squeeze_evidence_score"),
    )
    position.squeeze_evidence_source = first_present(
        position.squeeze_evidence_source,
        prior.get("squeeze_evidence_source"),
    )
    position.squeeze_evidence_components = first_present(
        position.squeeze_evidence_components,
        prior.get("squeeze_evidence_components"),
    )
    position.squeeze_evidence_unavailable_reason = first_present(
        position.squeeze_evidence_unavailable_reason,
        prior.get("squeeze_evidence_unavailable_reason"),
    )
    position.future_window_label_source = first_present(
        position.future_window_label_source,
        prior.get("future_window_label_source"),
    )
    position_has_complete_adaptive_capital = _position_has_complete_adaptive_capital_v1(position)
    prior_allocation = prior.get("adaptive_allocation") if isinstance(prior.get("adaptive_allocation"), dict) else None
    if position.adaptive_allocation is None and prior_allocation is not None and _prior_has_complete_adaptive_capital_v1(prior):
        position.adaptive_allocation = dict(prior_allocation)
    for attr in (
        "source_signal_id",
        "prediction_id",
        "risk_decision_id",
        "orchestrator_decision_id",
        "allocator_decision_id",
        "materialization_queue_id",
        "materialization_queue_accepted_at",
        "materialization_queue_expires_at",
        "market_state_id",
        "trainer_source",
        "timeframe",
        "feature_snapshot_id",
        "decision_id",
        "mtf_snapshot_id",
        "feature_cutoff",
        "decision_time",
        "available_at",
        "selected_action",
        "model_version",
        "model_source",
        "candidate_id",
        "paper_policy_owner",
        "policy_fingerprint",
        "checkpoint_id",
        "checkpoint_id_source",
        "entry_prediction_snapshot",
        "risk_decision_record_key",
        "risk_decision_record_hash",
        "risk_decision_record_resolved",
        "risk_decision_source",
        "orchestrator_decision_record_key",
        "orchestrator_decision_record_hash",
        "orchestrator_decision_record_resolved",
        "orchestrator_decision_source",
        "decision_record_missing_reasons",
        "source_hashes",
        "feature_vector_hash",
        "provider_hashes",
        "confidence_executable_trade",
        "dynamic_exploration_floor",
        "dynamic_exploration_floor_formula",
        "exploration_floor_inputs",
        "paper_risk_controller_exploration_above_floor",
        "paper_risk_controller_exploration_eligible",
        "bootstrap_exploration",
        "bootstrap_overridden_blockers",
        "selector_policy_fingerprint",
        "frozen_selector_fingerprint",
        "candidate_selected_before_outcome",
        "candidate_selected_after_outcome",
        "post_outcome_candidate_selection",
        "future_labels_used_as_features",
        "paper_opportunity_tier",
        "paper_opportunity_tier_reason",
        "explicit_paper_opportunity_tier",
        "paper_fill_allowed_source",
        "strict_paper_fill_allowed_upstream",
        "calibration_label_purpose",
        "entry_market_state_id",
        "adaptive_capital_policy_version",
        "policy_activated_at",
        "gross_notional_usd",
        "allocated_margin_usd",
        "effective_leverage",
        "recommended_leverage",
        "recommended_margin_mode",
        "margin_mode_simulated",
        "maintenance_margin_rate",
        "maintenance_margin_cum",
        "maintenance_margin_estimate",
        "maintenance_margin_notional_usd",
        "maintenance_margin_mark_price",
        "maintenance_margin_mark_time",
        "maintenance_bracket_id",
        "maintenance_bracket_maint_margin_ratio",
        "maintenance_bracket_cum",
        "maintenance_bracket_max_initial_leverage",
        "maintenance_bracket_evidence_hash",
        "maintenance_bracket_evidence_checksum_sha256",
        "maintenance_bracket_evidence_hmac_sha256",
        "maintenance_bracket_binding",
        "maintenance_bracket_environment_id",
        "maintenance_bracket_key_id",
        "maintenance_bracket_source",
        "maintenance_bracket_available_at",
        "maintenance_bracket_expires_at",
        "maintenance_bracket_consumer_observed_at",
        "maintenance_bracket_prevalidated",
        "maintenance_bracket_evidence_status",
        "maintenance_bracket_evidence_reason",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
        "risk_budget_usd",
        "risk_budget_source",
        "stop_distance_bps",
        "expected_fees_usd",
        "expected_funding_bps",
        "funding_rate",
        "funding_interval_seconds",
        "expected_funding_usd",
        "expected_net_pnl_usd",
        "expected_max_loss_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
        "capital_allocation_reason",
        "entry_atr_bps",
        "entry_feature_available_at",
        "entry_feature_generated_at",
        "entry_feature_cutoff",
        "entry_feature_decision_time",
        "entry_feature_source",
        "entry_feature_candle_closed_confirmed",
        "entry_feature_unavailable_reason",
        "entry_feature_snapshot",
        "entry_observed_spread_bps",
        "entry_spread_source",
        "entry_spread_unavailable_reason",
        "observed_bid",
        "observed_ask",
        "observed_spread_bps",
        "order_size",
        "order_size_usd",
        "top_book_bid_depth_usd",
        "top_book_ask_depth_usd",
        "bid_depth_usd",
        "ask_depth_usd",
        "orderbook_depth_usd",
        "entry_orderbook_depth_usd",
        "entry_orderbook_depth_side",
        "top_of_book_depth_usd",
        "market_depth_usd",
        "orderbook_depth_source",
        "depth_utilization_pct",
        "depth_price_impact_bps",
        "depth_price_impact_source",
        "depth_price_impact_model",
        "depth_price_impact_side",
        "depth_price_impact_quantity",
        "depth_price_impact_filled_quantity",
        "depth_price_impact_fill_complete",
        "depth_price_impact_vwap",
        "depth_price_impact_touch_price",
        "depth_derived_price_impact_bps",
        "expected_slippage_bps",
        "expected_slippage_usd",
        "expected_slippage_source",
        "expected_slippage_modeled",
        "expected_slippage_unavailable_reason",
        "correlation_exposure_pct",
        "correlation_input_source",
        "correlation_input_status",
        "correlation_pair_count",
        "correlation_diagnostics",
        "realized_slippage_bps",
        "realized_slippage_usd",
        "decision_latency_ms",
        "last_mark_price",
        "last_mark_est",
        "worst_adverse_price",
        "intra_trade_high_price",
        "intra_trade_low_price",
        "trailing_activation_price",
        "trailing_activation_time",
        "trailing_stop_price",
        "latency_reserve_bps",
        "latency_reserve_source",
        "maker_taker_assumption",
        "maker_taker_probability_detail",
        "fee_schedule",
        "fee_bps",
        "fee_bps_source",
        "fee_bps_configured_schedule",
        "entry_cost_accounting_version",
        "entry_fees_incurred_usd",
        "entry_fees_remaining_usd",
        "entry_fees_allocated_to_closes_usd",
        "entry_fee_fallback_bps_per_side",
        "entry_slippage_incurred_usd",
        "entry_slippage_remaining_usd",
        "entry_slippage_allocated_to_closes_usd",
        "entry_slippage_fallback_bps_per_side",
        "entry_fee_cost_sources",
        "entry_slippage_cost_sources",
        "entry_cost_basis_status",
        "holding_period_funding_bps",
        "holding_period_funding_source",
        "partial_fill_estimate",
        "partial_fill_probability",
        "partial_fill_adjustment_bps",
        "execution_probability",
        "cost_source",
        "cost_source_timestamp",
        "source_timestamp",
        "cost_evidence_freshness_ms",
        "cost_evidence_source_fields",
        "runtime_cost_capture_source",
        "runtime_cost_capture_status",
        "runtime_cost_capture_required_fields",
        "runtime_cost_capture_missing_fields",
        "runtime_cost_capture_explained_missing_fields",
        "runtime_cost_capture_unexplained_missing_fields",
        "runtime_cost_capture_order_cost_applicable",
        "runtime_cost_capture_no_order_reason",
        "runtime_cost_capture_temporal_reject_reasons",
        "fallback_cost_flag",
        "fallback",
        "production_grade_cost_flag",
        "production_grade_cost_evidence",
        "estimated_production_cost",
        "estimated_production_cost_bps",
        "counts_as_production_grade_training_evidence",
    ):
        value = prior.get(attr)
        if attr == "policy_activated_at" and value in (None, "") and prior_allocation is not None:
            value = prior_allocation.get("policy_activated_at")
        if (
            not restore_economic_snapshot
            and attr in _ADAPTIVE_CAPITAL_CARRY_FIELDS
            and (
            position_has_complete_adaptive_capital or not carry_capital
            )
        ):
            continue
        if (
            attr == "adaptive_capital_policy_version"
            and value == ADAPTIVE_CAPITAL_POLICY_VERSION
            and not _prior_has_complete_adaptive_capital_v1(prior)
        ):
            continue
        if (
            restore_economic_snapshot
            and attr in PAPER_POSITION_RECONSTRUCTION_PERSISTENCE_FIELDS
        ):
            # The reconstruction hash binds explicit null/empty states too.
            # A newly constructed object may have derived a diagnostic while
            # parsing the persisted row; restoring only non-empty values would
            # then change the byte-equivalent economic/risk envelope and make a
            # position written by this process impossible to restore.
            setattr(position, attr, value)
        elif value not in (None, "", {}, []):
            setattr(position, attr, value)
    for attr in ("mfe_bps", "mae_bps", "mfe_usd", "mae_usd"):
        value = prior.get(attr)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            setattr(position, attr, max(float(getattr(position, attr)), parsed))
    history = prior.get("trailing_stop_history")
    if isinstance(history, list):
        position.trailing_stop_history = [dict(row) for row in history if isinstance(row, dict)]
    _restore_path_telemetry_from_prior(position, prior)
    position.recompute_capital_accounting()


def _prior_has_partial_close_evidence(
    prior: dict[str, Any],
    closed_trades: list[dict[str, Any]],
) -> bool:
    for field in (
        "entry_fees_allocated_to_closes_usd",
        "entry_slippage_allocated_to_closes_usd",
    ):
        allocated = coerce_float(prior.get(field))
        if allocated is not None and allocated > 0.0:
            return True
    source_identity = first_present(
        prior.get("entry_fill_id"),
        *(
            prior.get("source_fill_ids")
            if isinstance(prior.get("source_fill_ids"), list)
            else []
        ),
    )
    for closed in closed_trades:
        if _close_proves_generation_fully_consumed(closed):
            continue
        if closed_generation_match(
            prior,
            closed,
            accepted_source_identity=source_identity,
        ) is not None:
            return True
    return False


def _restore_hashed_prior_position(
    prior: dict[str, Any],
    *,
    observed_at: str,
) -> tuple[PaperNetPosition | None, list[str]]:
    reasons = validate_paper_position_reconstruction(
        prior,
        observed_at=observed_at,
    )
    if reasons:
        return None, reasons
    side = str(prior.get("side") or "").lower()
    if side == "buy":
        side = "long"
    elif side == "sell":
        side = "short"
    source_fill_ids = [
        str(value)
        for value in prior.get("source_fill_ids") or []
        if value not in (None, "")
    ]
    quantity = coerce_float(prior.get("net_quantity"))
    price = coerce_float(prior.get("avg_entry_price"))
    if not source_fill_ids or quantity is None or price is None:
        return None, ["PERSISTED_POSITION_ECONOMICS_MISSING"]
    try:
        restored = position_from_fill(
            prior,
            fill_id=source_fill_ids[0],
            side=side,
            quantity=float(quantity),
            price=float(price),
        )
        _carry_prior_position_state(
            restored,
            prior,
            require_generation_match=False,
            restore_economic_snapshot=True,
        )
        restored_envelope = restored.reconstruction_envelope(
            generated_utc=str(prior["position_reconstruction_generated_at"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        return None, [f"PERSISTED_POSITION_RESTORE_FAILED:{exc}"]
    if (
        restored_envelope.get("position_reconstruction_hash")
        != prior.get("position_reconstruction_hash")
    ):
        return None, ["PERSISTED_POSITION_RESTORE_ROUND_TRIP_HASH_MISMATCH"]
    return restored, []


def _seeded_fill_replay_status(
    fill: dict[str, Any],
    *,
    position: PaperNetPosition,
    prior: dict[str, Any],
) -> tuple[str | None, list[str]]:
    """Classify an accepted row relative to a verified persisted open state."""

    fill_position_id = fill.get("position_id")
    fill_generation_id = fill.get("position_generation_id")
    if (
        fill_position_id not in (None, "")
        and fill_generation_id not in (None, "")
        and str(fill_position_id) == position.position_id
        and str(fill_generation_id) == str(position.position_generation_id)
    ):
        return "VERIFIED_OPEN_POSITION_SNAPSHOT_REPLAY", []
    fill_id = _fill_identity(fill)
    if fill_id not in position.fill_ids:
        return None, []
    persisted_status = str(fill.get("paper_fill_persistence_status") or "")
    lifecycle_status = str(fill.get("paper_lifecycle_status") or "")
    if persisted_status.startswith("EXISTING_") or lifecycle_status in {
        "OPEN_POSITION",
        "NETTED_INTO_EXISTING_POSITION",
        "OPEN_POSITION_RESTORED_FROM_HASHED_SNAPSHOT",
    }:
        return "VERIFIED_SOURCE_FILL_REPLAY", []
    fill_time = normalize_timestamp(
        first_present(
            fill.get("fill_time_utc"),
            fill.get("fill_time"),
            fill.get("fill_price_utc"),
            fill.get("accepted_at_utc"),
            fill.get("decision_time"),
            fill.get("generated_utc"),
        )
    )
    snapshot_time = normalize_timestamp(
        prior.get("position_reconstruction_generated_at")
    )
    if fill_time and snapshot_time and fill_time <= snapshot_time:
        return "VERIFIED_SOURCE_FILL_REPLAY_BEFORE_SNAPSHOT", []
    return None, ["SOURCE_FILL_ID_REUSED_WHILE_POSITION_OPEN"]


def _netting_receipt_material(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": row.get("paper_netting_fill_receipt_schema_version"),
        "close_id": row.get("paper_netting_close_id"),
        "position_generation_id": row.get(
            "paper_netting_position_generation_id"
        ),
        "fill_id": _fill_identity(row),
        "side": str(row.get("side") or "").lower(),
        "input_quantity": coerce_float(row.get("paper_netting_input_quantity")),
        "consumed_quantity": coerce_float(
            row.get("paper_netting_consumed_quantity")
        ),
        "residual_quantity": coerce_float(
            row.get("paper_netting_residual_quantity")
        ),
    }


def _netting_receipt_hash(row: dict[str, Any]) -> str | None:
    try:
        canonical = json.dumps(
            _netting_receipt_material(row),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _attach_netting_receipt(
    row: dict[str, Any],
    *,
    close_event: dict[str, Any],
    input_quantity: float,
    consumed_quantity: float,
    residual_quantity: float,
) -> dict[str, Any]:
    receipt = dict(row)
    receipt.update(
        {
            "paper_netting_fill_receipt_schema_version": (
                _PAPER_NETTING_FILL_RECEIPT_SCHEMA_VERSION
            ),
            "paper_netting_close_id": close_event.get("close_id"),
            "paper_netting_position_generation_id": close_event.get(
                "position_generation_id"
            ),
            "paper_netting_input_quantity": float(input_quantity),
            "paper_netting_consumed_quantity": float(consumed_quantity),
            "paper_netting_residual_quantity": float(residual_quantity),
        }
    )
    receipt_hash = _netting_receipt_hash(receipt)
    if receipt_hash is None:
        raise ValueError("PAPER_NETTING_FILL_RECEIPT_HASH_FAILED")
    receipt["paper_netting_fill_receipt_hash"] = receipt_hash
    return receipt


def _netting_receipt_integrity_reasons(
    fill: dict[str, Any],
    *,
    closed_trades: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    if (
        fill.get("paper_netting_fill_receipt_schema_version")
        != _PAPER_NETTING_FILL_RECEIPT_SCHEMA_VERSION
    ):
        reasons.append("PAPER_NETTING_FILL_RECEIPT_SCHEMA_INVALID")
    supplied_hash = str(fill.get("paper_netting_fill_receipt_hash") or "")
    if not supplied_hash or supplied_hash != _netting_receipt_hash(fill):
        reasons.append("PAPER_NETTING_FILL_RECEIPT_HASH_INVALID")
    input_quantity = coerce_float(fill.get("paper_netting_input_quantity"))
    consumed_quantity = coerce_float(fill.get("paper_netting_consumed_quantity"))
    residual_quantity = coerce_float(fill.get("paper_netting_residual_quantity"))
    if (
        input_quantity is None
        or consumed_quantity is None
        or residual_quantity is None
        or not all(
            math.isfinite(value) and value >= 0.0
            for value in (input_quantity, consumed_quantity, residual_quantity)
        )
        or not math.isclose(
            input_quantity,
            consumed_quantity + residual_quantity,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ):
        reasons.append("PAPER_NETTING_FILL_RECEIPT_QUANTITY_CONSERVATION_FAILED")
    close_id = str(fill.get("paper_netting_close_id") or "")
    generation_id = str(fill.get("paper_netting_position_generation_id") or "")
    matching_closes = [
        closed
        for closed in closed_trades
        if str(closed.get("close_id") or "") == close_id
        and str(closed.get("position_generation_id") or "") == generation_id
    ]
    if len(matching_closes) != 1:
        reasons.append("PAPER_NETTING_FILL_RECEIPT_CLOSE_BINDING_INVALID")
    elif consumed_quantity is not None:
        closed_quantity = coerce_float(matching_closes[0].get("closed_quantity"))
        if closed_quantity is None or not math.isclose(
            consumed_quantity,
            closed_quantity,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            reasons.append("PAPER_NETTING_FILL_RECEIPT_CLOSE_QUANTITY_MISMATCH")
    return list(dict.fromkeys(reasons))


def _historical_netting_receipt_evidence(
    fill: dict[str, Any],
    *,
    closed_trades: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if _netting_receipt_integrity_reasons(fill, closed_trades=closed_trades):
        return None
    supplied_hash = str(fill["paper_netting_fill_receipt_hash"])
    residual = coerce_float(fill.get("paper_netting_residual_quantity"))
    if residual is None or residual > 1e-12:
        return None
    close_id = str(fill.get("paper_netting_close_id") or "")
    generation_id = str(fill.get("paper_netting_position_generation_id") or "")
    consumed_quantity = coerce_float(fill.get("paper_netting_consumed_quantity"))
    for closed in closed_trades:
        if str(closed.get("close_id") or "") != close_id:
            continue
        if str(closed.get("position_generation_id") or "") != generation_id:
            continue
        closed_quantity = coerce_float(closed.get("closed_quantity"))
        if (
            consumed_quantity is None
            or closed_quantity is None
            or not math.isclose(
                consumed_quantity,
                closed_quantity,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            continue
        return {
            "close_id": close_id,
            "position_generation_id": generation_id,
            "receipt_hash": supplied_hash,
        }
    return None


def _accepted_fill_with_position_metadata(
    fill: dict[str, Any],
    *,
    status: str,
    position: PaperNetPosition,
) -> dict[str, Any]:
    row = _accepted_fill_with_entry_policy_metadata(fill, status=status)
    allocation = position.adaptive_allocation if isinstance(position.adaptive_allocation, dict) else {}
    allocation_id = first_present(
        allocation.get("allocation_id"),
        allocation.get("allocator_decision_id"),
    )
    allocator_decision_id = first_present(position.allocator_decision_id, allocation_id)
    allocator_decision_id_source = (
        "paper_position.allocator_decision_id"
        if position.allocator_decision_id not in (None, "")
        else "adaptive_allocation.allocation_id"
        if allocation_id not in (None, "")
        else None
    )
    provider_hashes = position.provider_hashes
    if not provider_hashes and isinstance(position.source_hashes, dict):
        provider_hashes = {
            key: value
            for key, value in position.source_hashes.items()
            if key not in {"feature_vector_hash", "prediction_hash", "source_lineage_hash"}
            and value not in (None, "")
        } or None
    feature_vector_hash = first_present(
        position.feature_vector_hash,
        position.source_hashes.get("feature_vector_hash") if isinstance(position.source_hashes, dict) else None,
    )
    raw_safety_fields = {
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "test_order": False,
        "live_order": False,
        "counts_as_A_plus": False,
        "counts_as_final_A_plus": False,
        "counts_as_live_ready": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    invariant_checks = {
        "paper_only_is_true": True,
        "routes_to_live_is_false": True,
        "places_real_order_is_false": True,
        "test_order_is_false": True,
        "live_order_is_false": True,
        "counts_as_A_plus_is_false": True,
        "counts_as_final_A_plus_is_false": True,
        "counts_as_live_ready_is_false": True,
        "order_submitted_is_false": True,
        "test_order_submitted_is_false": True,
        "leverage_mutated_is_false": True,
        "margin_mutated_is_false": True,
    }
    position_fields = {
        "position_id": position.position_id,
        "legacy_position_id": position.legacy_position_id,
        "position_generation_id": position.position_generation_id,
        "position_id_version": position.position_id_version,
        "entry_generation_time_utc": position.entry_generation_time_utc,
        "signal_id": position.source_signal_id,
        "entry_signal_id": position.source_signal_id,
        "prediction_id": position.prediction_id,
        "entry_prediction_id": position.prediction_id,
        "preemptive_decision_id": position.preemptive_decision_id,
        "risk_decision_id": position.risk_decision_id,
        "orchestrator_decision_id": position.orchestrator_decision_id,
        "allocator_decision_id": allocator_decision_id,
        "allocator_decision_id_source": allocator_decision_id_source,
        "allocation_id": allocation_id,
        "materialization_queue_id": position.materialization_queue_id,
        "materialization_queue_accepted_at": position.materialization_queue_accepted_at,
        "materialization_queue_expires_at": position.materialization_queue_expires_at,
        "decision_id": position.decision_id,
        "market_state_id": position.market_state_id,
        "entry_market_state_id": position.entry_market_state_id or position.market_state_id,
        "trainer_source": position.trainer_source,
        "timeframe": position.timeframe,
        "feature_snapshot_id": position.feature_snapshot_id,
        "entry_feature_snapshot_id": position.feature_snapshot_id,
        "mtf_snapshot_id": position.mtf_snapshot_id,
        "feature_cutoff": position.feature_cutoff,
        "decision_time": position.decision_time,
        "available_at": position.available_at,
        "selected_action": position.selected_action,
        "model_version": position.model_version,
        "model_source": position.model_source,
        "candidate_id": position.candidate_id,
        "paper_policy_owner": position.paper_policy_owner,
        "policy_fingerprint": position.policy_fingerprint,
        "checkpoint_id": position.checkpoint_id,
        "checkpoint_id_source": position.checkpoint_id_source,
        "entry_prediction_snapshot": position.entry_prediction_snapshot,
        "risk_decision_record_key": position.risk_decision_record_key,
        "risk_decision_record_hash": position.risk_decision_record_hash,
        "risk_decision_record_resolved": position.risk_decision_record_resolved,
        "risk_decision_source": position.risk_decision_source,
        "orchestrator_decision_record_key": position.orchestrator_decision_record_key,
        "orchestrator_decision_record_hash": position.orchestrator_decision_record_hash,
        "orchestrator_decision_record_resolved": position.orchestrator_decision_record_resolved,
        "orchestrator_decision_source": position.orchestrator_decision_source,
        "decision_record_missing_reasons": position.decision_record_missing_reasons,
        "source_hashes": position.source_hashes,
        "feature_vector_hash": feature_vector_hash,
        "provider_hashes": provider_hashes,
        "confidence_executable_trade": position.confidence_executable_trade,
        "dynamic_exploration_floor": position.dynamic_exploration_floor,
        "dynamic_exploration_floor_formula": position.dynamic_exploration_floor_formula,
        "exploration_floor_inputs": position.exploration_floor_inputs,
        "paper_risk_controller_exploration_above_floor": (
            position.paper_risk_controller_exploration_above_floor
        ),
        "paper_risk_controller_exploration_eligible": (
            position.paper_risk_controller_exploration_eligible
        ),
        "bootstrap_exploration": position.bootstrap_exploration,
        "bootstrap_overridden_blockers": position.bootstrap_overridden_blockers,
        "selector_policy_fingerprint": position.selector_policy_fingerprint,
        "frozen_selector_fingerprint": position.frozen_selector_fingerprint,
        "candidate_selected_before_outcome": position.candidate_selected_before_outcome,
        "candidate_selected_after_outcome": position.candidate_selected_after_outcome,
        "post_outcome_candidate_selection": position.post_outcome_candidate_selection,
        "future_labels_used_as_features": position.future_labels_used_as_features,
        "paper_opportunity_tier": position.paper_opportunity_tier,
        "tier": (
            position.paper_opportunity_tier
            if str(position.paper_opportunity_tier or "").strip().upper()
            == "PAPER_RISK_CONTROLLER_EXPLORATION"
            else None
        ),
        "exploration_tier": (
            position.paper_opportunity_tier
            if str(position.paper_opportunity_tier or "").strip().upper()
            == "PAPER_RISK_CONTROLLER_EXPLORATION"
            else None
        ),
        "paper_exploration_tier": (
            position.paper_opportunity_tier
            if str(position.paper_opportunity_tier or "").strip().upper()
            == "PAPER_RISK_CONTROLLER_EXPLORATION"
            else None
        ),
        "paper_opportunity_tier_reason": position.paper_opportunity_tier_reason,
        "explicit_paper_opportunity_tier": position.explicit_paper_opportunity_tier,
        "paper_fill_allowed_source": position.paper_fill_allowed_source,
        "strict_paper_fill_allowed_upstream": position.strict_paper_fill_allowed_upstream,
        "calibration_label_purpose": position.calibration_label_purpose,
        "entry_feature_available_at": position.entry_feature_available_at,
        "entry_feature_generated_at": position.entry_feature_generated_at,
        "entry_feature_cutoff": position.entry_feature_cutoff,
        "entry_feature_decision_time": position.entry_feature_decision_time,
        "entry_feature_source": position.entry_feature_source,
        "entry_feature_candle_closed_confirmed": position.entry_feature_candle_closed_confirmed,
        "entry_feature_unavailable_reason": position.entry_feature_unavailable_reason,
        "entry_feature_snapshot": position.entry_feature_snapshot,
        "observed_bid": position.observed_bid,
        "observed_ask": position.observed_ask,
        "observed_spread_bps": position.observed_spread_bps,
        "order_size": position.order_size,
        "order_size_usd": position.order_size_usd,
        "actual_observed_spread_entry_bps": position.entry_observed_spread_bps,
        "bid_depth_usd": position.bid_depth_usd,
        "ask_depth_usd": position.ask_depth_usd,
        "orderbook_depth_usd": position.orderbook_depth_usd,
        "entry_orderbook_depth_usd": position.entry_orderbook_depth_usd,
        "entry_orderbook_depth_side": position.entry_orderbook_depth_side,
        "top_book_bid_depth_usd": position.top_book_bid_depth_usd,
        "top_book_ask_depth_usd": position.top_book_ask_depth_usd,
        "top_of_book_depth_usd": position.top_of_book_depth_usd,
        "market_depth_usd": position.market_depth_usd,
        "orderbook_depth_source": position.orderbook_depth_source,
        "depth_utilization_pct": position.depth_utilization_pct,
        "depth_price_impact_bps": position.depth_price_impact_bps,
        "depth_derived_price_impact_bps": position.depth_derived_price_impact_bps,
        "depth_price_impact_source": position.depth_price_impact_source,
        "depth_price_impact_model": position.depth_price_impact_model,
        "depth_price_impact_side": position.depth_price_impact_side,
        "depth_price_impact_quantity": position.depth_price_impact_quantity,
        "depth_price_impact_filled_quantity": position.depth_price_impact_filled_quantity,
        "depth_price_impact_fill_complete": position.depth_price_impact_fill_complete,
        "depth_price_impact_vwap": position.depth_price_impact_vwap,
        "depth_price_impact_touch_price": position.depth_price_impact_touch_price,
        "adaptive_capital_policy_version": position.adaptive_capital_policy_version,
        "policy_activated_at": position.policy_activated_at,
        "fee_schedule": position.fee_schedule,
        "fee_bps": position.fee_bps,
        "fee_bps_source": position.fee_bps_source,
        "fee_bps_configured_schedule": position.fee_bps_configured_schedule,
        "entry_cost_accounting_version": position.entry_cost_accounting_version,
        "entry_fees_incurred_usd": position.entry_fees_incurred_usd,
        "entry_fees_remaining_usd": position.entry_fees_remaining_usd,
        "entry_fees_allocated_to_closes_usd": (
            position.entry_fees_allocated_to_closes_usd
        ),
        "entry_fee_fallback_bps_per_side": (
            position.entry_fee_fallback_bps_per_side
        ),
        "entry_slippage_incurred_usd": position.entry_slippage_incurred_usd,
        "entry_slippage_remaining_usd": position.entry_slippage_remaining_usd,
        "entry_slippage_allocated_to_closes_usd": (
            position.entry_slippage_allocated_to_closes_usd
        ),
        "entry_slippage_fallback_bps_per_side": (
            position.entry_slippage_fallback_bps_per_side
        ),
        "entry_fee_cost_sources": list(position.entry_fee_cost_sources),
        "entry_slippage_cost_sources": list(
            position.entry_slippage_cost_sources
        ),
        "entry_cost_basis_status": position.entry_cost_basis_status,
        "expected_funding_bps": position.expected_funding_bps,
        "funding_rate": position.funding_rate,
        "funding_interval_seconds": position.funding_interval_seconds,
        "expected_funding_usd": position.expected_funding_usd,
        "expected_net_pnl_usd": position.expected_net_pnl_usd,
        "expected_max_loss_usd": position.expected_max_loss_usd,
        "expected_shortfall_usd": position.expected_shortfall_usd,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "counts_as_A_plus": False,
        "counts_as_final_A_plus": False,
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "raw_safety_fields": raw_safety_fields,
        "invariant_checks": invariant_checks,
        "holding_period_funding_bps": position.holding_period_funding_bps,
        "holding_period_funding_source": position.holding_period_funding_source,
        "latency_reserve_bps": position.latency_reserve_bps,
        "latency_reserve_source": position.latency_reserve_source,
        "maker_taker_assumption": position.maker_taker_assumption,
        "maker_taker_probability_detail": position.maker_taker_probability_detail,
        "partial_fill_estimate": position.partial_fill_estimate,
        "partial_fill_probability": position.partial_fill_probability,
        "partial_fill_adjustment_bps": position.partial_fill_adjustment_bps,
        "execution_probability": position.execution_probability,
        "cost_source": position.cost_source,
        "cost_source_timestamp": position.cost_source_timestamp,
        "source_timestamp": position.source_timestamp,
        "cost_evidence_freshness_ms": position.cost_evidence_freshness_ms,
        "cost_evidence_source_fields": position.cost_evidence_source_fields,
        "runtime_cost_capture_source": position.runtime_cost_capture_source,
        "runtime_cost_capture_status": position.runtime_cost_capture_status,
        "runtime_cost_capture_required_fields": position.runtime_cost_capture_required_fields,
        "runtime_cost_capture_missing_fields": position.runtime_cost_capture_missing_fields,
        "runtime_cost_capture_explained_missing_fields": position.runtime_cost_capture_explained_missing_fields,
        "runtime_cost_capture_unexplained_missing_fields": position.runtime_cost_capture_unexplained_missing_fields,
        "runtime_cost_capture_order_cost_applicable": position.runtime_cost_capture_order_cost_applicable,
        "runtime_cost_capture_no_order_reason": position.runtime_cost_capture_no_order_reason,
        "runtime_cost_capture_temporal_reject_reasons": position.runtime_cost_capture_temporal_reject_reasons,
        "fallback_cost_flag": position.fallback_cost_flag,
        "fallback": position.fallback,
        "production_grade_cost_flag": position.production_grade_cost_flag,
        "production_grade_cost_evidence": position.production_grade_cost_evidence,
        "estimated_production_cost": position.estimated_production_cost,
        "estimated_production_cost_bps": position.estimated_production_cost_bps,
        "counts_as_production_grade_training_evidence": position.counts_as_production_grade_training_evidence,
    }
    for field, value in position_fields.items():
        if value not in (None, "", {}, []):
            row[field] = value
    return row


def _allocation_from_fill(fill: dict[str, Any]) -> dict[str, Any]:
    value = fill.get("adaptive_allocation")
    return value if isinstance(value, dict) else {}


def _model_inputs_from_allocation(allocation: dict[str, Any]) -> dict[str, Any]:
    value = allocation.get("model_inputs")
    return value if isinstance(value, dict) else {}


def _first_numeric(*values: Any) -> float | None:
    for value in values:
        parsed = coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def _accepted_fill_with_entry_policy_metadata(
    fill: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    row = dict(fill)
    allocation = dict(_allocation_from_fill(fill))
    model_inputs = _model_inputs_from_allocation(allocation)
    row["paper_lifecycle_status"] = status
    policy_version = first_present(
        row.get("adaptive_capital_policy_version"),
        allocation.get("adaptive_capital_policy_version"),
    )
    if policy_version not in (None, ""):
        row.setdefault("adaptive_capital_policy_version", policy_version)
    if str(policy_version or "") == ADAPTIVE_CAPITAL_POLICY_VERSION:
        entry_time_utc = (
            utc_iso_from_any(row.get("fill_price_utc"))
            or utc_iso_from_any(row.get("generated_utc"))
            or utc_iso_from_any(row.get("entry_price_utc"))
            or utc_iso_from_any(row.get("fill_time_est"))
        )
        policy_activated_at = first_present(
            row.get("policy_activated_at"),
            allocation.get("policy_activated_at"),
            entry_time_utc,
        )
        if policy_activated_at not in (None, ""):
            row["policy_activated_at"] = policy_activated_at
            allocation.setdefault("policy_activated_at", policy_activated_at)
    expected_funding_bps = _first_numeric(
        row.get("expected_funding_bps"),
        row.get("funding_bps"),
        row.get("funding_rate_bps"),
        allocation.get("expected_funding_bps"),
        model_inputs.get("expected_funding_bps"),
        model_inputs.get("funding_bps"),
        model_inputs.get("funding_rate_bps"),
    )
    funding_rate = _first_numeric(
        row.get("funding_rate"),
        allocation.get("funding_rate"),
        model_inputs.get("funding_rate"),
    )
    if funding_rate is None and expected_funding_bps is not None:
        funding_rate = expected_funding_bps / 10000.0
    if expected_funding_bps is None and funding_rate is not None:
        expected_funding_bps = funding_rate * 10000.0
    if expected_funding_bps is not None:
        row.setdefault("expected_funding_bps", expected_funding_bps)
        allocation.setdefault("expected_funding_bps", expected_funding_bps)
        model_inputs.setdefault("expected_funding_bps", expected_funding_bps)
    if funding_rate is not None:
        row.setdefault("funding_rate", funding_rate)
        model_inputs.setdefault("funding_rate", funding_rate)
    funding_interval_seconds = _first_numeric(
        row.get("funding_interval_seconds"),
        allocation.get("funding_interval_seconds"),
        model_inputs.get("funding_interval_seconds"),
    )
    if funding_interval_seconds is not None and (funding_rate is not None or expected_funding_bps is not None):
        row.setdefault("funding_interval_seconds", funding_interval_seconds)
        model_inputs.setdefault("funding_interval_seconds", funding_interval_seconds)
    if model_inputs:
        allocation["model_inputs"] = model_inputs
    if allocation:
        row["adaptive_allocation"] = allocation
    return row


def _positive_price(*values: Any) -> list[float]:
    prices: list[float] = []
    for value in values:
        parsed = coerce_float(value)
        if parsed is not None and parsed > 0.0:
            prices.append(parsed)
    return prices


def _restore_path_telemetry_from_prior(position: PaperNetPosition, prior: dict[str, Any]) -> None:
    prices = _positive_price(
        position.avg_entry_price,
        position.last_mark_price,
        prior.get("last_mark_price"),
        prior.get("best_favorable_price"),
        prior.get("worst_adverse_price"),
        prior.get("intra_trade_high_price"),
        prior.get("intra_trade_low_price"),
    )
    if not prices:
        return
    position.intra_trade_high_price = max(
        _positive_price(position.intra_trade_high_price, max(prices))
    )
    position.intra_trade_low_price = min(
        _positive_price(position.intra_trade_low_price, min(prices))
    )
    if position.best_favorable_price is None:
        if position.side == "short":
            position.best_favorable_price = min(prices)
        else:
            position.best_favorable_price = max(prices)
    if position.worst_adverse_price is None:
        if position.side == "short":
            position.worst_adverse_price = max(prices)
        else:
            position.worst_adverse_price = min(prices)
    high = coerce_float(position.intra_trade_high_price)
    low = coerce_float(position.intra_trade_low_price)
    entry = coerce_float(position.avg_entry_price)
    quantity = coerce_float(position.net_quantity) or 0.0
    if high is None or low is None or entry is None or entry <= 0.0:
        return
    if position.side == "short":
        favorable_delta = max(0.0, entry - low)
        adverse_delta = max(0.0, high - entry)
    else:
        favorable_delta = max(0.0, high - entry)
        adverse_delta = max(0.0, entry - low)
    position.mfe_bps = max(float(position.mfe_bps), favorable_delta / entry * 10000.0)
    position.mae_bps = max(float(position.mae_bps), adverse_delta / entry * 10000.0)
    position.mfe_usd = max(float(position.mfe_usd), favorable_delta * quantity)
    position.mae_usd = max(float(position.mae_usd), adverse_delta * quantity)


def _structured_market_price_evidence_required(
    mark_prices: dict[str, Any],
    symbol: str,
) -> bool:
    value = mark_prices.get(symbol.upper())
    return (
        isinstance(value, dict)
        and value.get("market_price_evidence_required") is True
    )


def _mark_for_symbol(mark_prices: dict[str, Any], symbol: str, fallback: float | None) -> tuple[float | None, str | None]:
    value = mark_prices.get(symbol.upper())
    if isinstance(value, dict):
        if value.get("market_price_evidence_required") is True:
            evidence = value.get("market_price_evidence")
            expected_timeframe = str(
                value.get("market_price_requested_timeframe") or ""
            ).lower()
            verification = verify_market_price_evidence(
                evidence,
                expected_symbol=symbol,
                expected_timeframe=expected_timeframe,
            )
            evidence_price = coerce_float(verification.get("price"))
            mapped_price = coerce_float(value.get("price"))
            if (
                verification.get("valid") is not True
                or evidence_price is None
                or mapped_price != evidence_price
            ):
                reasons = list(verification.get("reasons") or [])
                if mapped_price != evidence_price:
                    reasons.append("LIFECYCLE_MARK_PRICE_EVIDENCE_BINDING_MISMATCH")
                reason = (
                    ",".join(sorted(set(reasons)))
                    or "INVALID_MARKET_PRICE_EVIDENCE"
                )
                return None, f"MARK_PRICE_EVIDENCE_REJECTED:{reason}"
            return evidence_price, str(
                evidence.get("source_label") or "VERIFIED_V2_MARK_PRICE"
            )
        try:
            price = float(value.get("price"))
        except (TypeError, ValueError):
            price = None
        source = value.get("source")
    else:
        try:
            price = float(value)
        except (TypeError, ValueError):
            price = None
        source = None
    if price is not None and price > 0:
        return price, str(source or "V2_MARK_PRICE")
    return fallback, "ENTRY_PRICE_FALLBACK_ONLY_FOR_UNCHANGED_MARK"


def _maintenance_bracket_for_symbol(
    mark_prices: dict[str, Any],
    symbol: str,
) -> dict[str, Any] | None:
    """Return only the prevalidated lifecycle mapping attached to this mark."""

    value = mark_prices.get(symbol.upper())
    if not isinstance(value, dict):
        return None
    evidence = value.get("maintenance_bracket_evidence")
    return dict(evidence) if isinstance(evidence, dict) else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def _exit_spread_from_mapping(mapping: dict[str, Any] | None) -> tuple[float | None, str | None, str | None]:
    if not isinstance(mapping, dict):
        return None, None, None
    micro = mapping.get("microstructure_context") if isinstance(mapping.get("microstructure_context"), dict) else {}
    spread = _first_number(
        mapping.get("actual_observed_spread_exit_bps"),
        mapping.get("actual_observed_spread_entry_bps"),
        mapping.get("observed_bid_ask_spread_bps"),
        mapping.get("bid_ask_spread_bps"),
        micro.get("bid_ask_spread_bps"),
        micro.get("spread_bps"),
        micro.get("ob_spread_bps"),
    )
    source = first_present(
        mapping.get("exit_spread_source"),
        mapping.get("entry_spread_source"),
        micro.get("source"),
    )
    available_at = first_present(
        mapping.get("exit_spread_available_at"),
        mapping.get("entry_spread_available_at"),
    )
    return spread, str(source) if source else None, str(available_at) if available_at else None


_REQUIRED_CLOSE_PATH_FIELDS = (
    "mfe_bps",
    "mae_bps",
    "intra_trade_high_price",
    "intra_trade_low_price",
)


def _close_event_dirty_reasons(close_event: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in _REQUIRED_CLOSE_PATH_FIELDS:
        if coerce_float(close_event.get(field)) is None:
            reasons.append(f"MISSING_{field.upper()}")
    if str(close_event.get("close_reason") or close_event.get("exit_reason") or "") == "TIER_2_TRAILING_STOP":
        history = close_event.get("trailing_stop_history")
        if not isinstance(history, list) or not history:
            reasons.append("MISSING_TRAILING_STOP_HISTORY_FOR_TRAILING_EXIT")
        if coerce_float(close_event.get("trailing_activation_price")) is None:
            reasons.append("MISSING_TRAILING_ACTIVATION_PRICE_FOR_TRAILING_EXIT")
        if not close_event.get("trailing_activation_time"):
            reasons.append("MISSING_TRAILING_ACTIVATION_TIME_FOR_TRAILING_EXIT")
        if coerce_float(close_event.get("trailing_stop_price")) is None:
            reasons.append("MISSING_TRAILING_STOP_PRICE_FOR_TRAILING_EXIT")
    return reasons


def _close_position(
    *,
    positions: dict[str, PaperNetPosition],
    symbol: str,
    close_quantity: float,
    exit_price: float,
    exit_time: str,
    close_reason: str,
    fee_bps: float,
    slippage_bps: float,
    exit_signal_id: str | None = None,
    exit_prediction_id: str | None = None,
    exit_spread_bps: float | None = None,
    exit_spread_source: str | None = None,
    exit_spread_available_at: str | None = None,
    exit_audit_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    position = positions.get(symbol)
    if position is None or close_quantity <= 0:
        return None, None, None
    quantity = min(position.net_quantity, close_quantity)
    position.update_mark(mark_price=exit_price, mark_time=exit_time)
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=quantity,
        exit_price=exit_price,
        exit_time=exit_time,
        close_reason=close_reason,
        exit_signal_id=exit_signal_id,
        exit_prediction_id=exit_prediction_id,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        exit_spread_bps=exit_spread_bps,
        exit_spread_source=exit_spread_source,
        exit_spread_available_at=exit_spread_available_at,
        exit_audit_context=exit_audit_context,
    )
    dirty_reasons = _close_event_dirty_reasons(close_event)
    if dirty_reasons:
        return None, None, {
            "symbol": symbol,
            "position_id": position.position_id,
            "close_reason": close_reason,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "close_quantity": quantity,
            "paper_close_blocked": True,
            "paper_close_block_reasons": dirty_reasons,
            "paper_only": True,
            "places_real_order": False,
        }
    close_event, outcome, timing_reasons = capture_close_outcome_availability(
        close_event,
        outcome,
    )
    if timing_reasons:
        return None, None, {
            "symbol": symbol,
            "position_id": position.position_id,
            "close_reason": close_reason,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "close_quantity": quantity,
            "paper_close_blocked": True,
            "paper_close_block_reasons": timing_reasons,
            "paper_outcome_availability_status": "BLOCKED",
            "paper_only": True,
            "places_real_order": False,
        }
    try:
        # Cost basis consumption is deliberately after dirty/timing admission
        # and before the quantity mutation.  Failed close construction or
        # publication therefore cannot spend entry costs, while an admitted
        # partial close persists the exact pro-rata remainder with the open
        # position.
        position.consume_entry_cost_allocation(close_event)
    except (TypeError, ValueError) as exc:
        return None, None, {
            "symbol": symbol,
            "position_id": position.position_id,
            "close_reason": close_reason,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "close_quantity": quantity,
            "paper_close_blocked": True,
            "paper_close_block_reasons": ["ENTRY_COST_BASIS_CONSUMPTION_FAILED"],
            "paper_close_cost_basis_error": str(exc),
            "paper_only": True,
            "places_real_order": False,
        }
    position.realized_pnl += float(
        first_present(close_event.get("realized_net_pnl_usd"), close_event["realized_pnl_usd"])
    )
    position.net_quantity = max(0.0, position.net_quantity - quantity)
    if position.net_quantity <= 1e-12:
        del positions[symbol]
    else:
        position.recompute_capital_accounting()
    return close_event, outcome, None


def _exit_audit_context(
    *,
    exit_config: PaperExitConfig,
    exit_eval: dict[str, Any] | None = None,
    trailing_context_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_eval = exit_eval or {}
    trailing_context_decision = trailing_context_decision or {}
    return {
        "paper_exit_policy_version": PAPER_EXIT_POLICY_VERSION,
        "trailing_after_cost_floor_enabled": True,
        "min_profit_before_trailing_bps": exit_config.min_profit_before_trailing_bps,
        "trailing_stop_min_after_cost_buffer_bps": exit_config.trailing_stop_min_after_cost_buffer_bps,
        "trailing_stop_bps_effective": exit_eval.get("trailing_stop_bps_effective"),
        "trailing_profit_floor_bps": exit_eval.get("trailing_profit_floor_bps"),
        "trailing_after_cost_buffer_bps": exit_eval.get("trailing_after_cost_buffer_bps"),
        "trailing_after_cost_floor_blocker": (
            exit_eval.get("blocker")
            if exit_eval.get("blocker") == "TRAILING_AFTER_COST_PROFIT_FLOOR_NOT_MET"
            else None
        ),
        "trailing_profit_floor_gap_bps": exit_eval.get("trailing_profit_floor_gap_bps"),
        "trailing_profit_floor_gap_exit": exit_eval.get("trailing_profit_floor_gap_exit"),
        "trailing_profit_floor_gap_exit_reason": exit_eval.get("trailing_profit_floor_gap_exit_reason"),
        "paper_exit_price": exit_eval.get("paper_exit_price"),
        "paper_exit_price_source": exit_eval.get("paper_exit_price_source"),
        "paper_exit_pnl_bps": exit_eval.get("paper_exit_pnl_bps"),
        "trailing_stop_exit_floor_bps": exit_eval.get("trailing_stop_exit_floor_bps"),
        "trailing_stop_exit_floor_gap_bps": exit_eval.get("trailing_stop_exit_floor_gap_bps"),
        "trailing_stop_exit_after_cost_floor_not_met": exit_eval.get(
            "trailing_stop_exit_after_cost_floor_not_met"
        ),
        "trailing_stop_mark_price": exit_eval.get("trailing_stop_mark_price"),
        "trailing_stop_gap_bps": exit_eval.get("trailing_stop_gap_bps"),
        "trailing_context_decision_source": trailing_context_decision.get("decision_source"),
        "trailing_context_selected_key": (
            (trailing_context_decision.get("selected_context") or {}).get("key")
            if isinstance(trailing_context_decision.get("selected_context"), dict)
            else None
        ),
        # ATR stop telemetry: the fired stop distance and its adaptive inputs,
        # so the runtime can compute the rolling exit-overshoot premium
        # (|realized gross pnl_bps| - atr_stop_bps) from closed trades.
        "atr_stop_bps": exit_eval.get("atr_stop_bps"),
        "atr_stop_multiplier_used": exit_eval.get("atr_stop_multiplier_used"),
        "atr_stop_confidence_used": exit_eval.get("atr_stop_confidence_used"),
        "atr_stop_confidence_gain_used": exit_eval.get("atr_stop_confidence_gain_used"),
        "atr_stop_regime_scale_used": exit_eval.get("atr_stop_regime_scale_used"),
        "atr_stop_floor_applied": exit_eval.get("atr_stop_floor_applied"),
        "atr_stop_overshoot_premium_bps": exit_eval.get("atr_stop_overshoot_premium_bps"),
    }


def reconcile_paper_lifecycle(
    *,
    existing_ledger: dict[str, Any] | None,
    accepted_fills: list[dict[str, Any]],
    mark_prices: dict[str, Any] | None = None,
    generated_utc: str | None = None,
    config: PaperLifecycleConfig | None = None,
    portfolio_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_ledger = existing_ledger or {}
    mark_prices = mark_prices or {}
    generated_utc = generated_utc or utc_now_iso()
    config = config or PaperLifecycleConfig()

    positions: dict[str, PaperNetPosition] = {}
    closed_trades = _existing_closed_trades(existing_ledger)
    outcome_labels = _existing_outcome_labels(existing_ledger)
    trailing_circuit_breaker = _trailing_stop_runtime_circuit_breaker(closed_trades, config)
    trailing_context_policy = _trailing_stop_context_policy(closed_trades, config)
    trailing_context_decisions: list[dict[str, Any]] = []
    prior_positions = _prior_positions_by_symbol(existing_ledger)
    blocked_entries: list[dict[str, Any]] = []
    accepted_open_fills: list[dict[str, Any]] = []
    closed_previously_fills: list[dict[str, Any]] = []
    cap_evaluations: list[dict[str, Any]] = []
    netting_events: list[dict[str, Any]] = []
    exit_evaluations: list[dict[str, Any]] = []
    new_close_events: list[dict[str, Any]] = []
    new_outcomes: list[dict[str, Any]] = []
    dirty_close_blocks: list[dict[str, Any]] = []
    seen_fill_generations: set[str] = set()
    restored_prior_rows: dict[str, dict[str, Any]] = {}
    reconstruction_blocks: list[dict[str, Any]] = []
    blocked_prior_keys: set[str] = set()

    for prior_key, prior in prior_positions.items():
        has_reconstruction_envelope = any(
            prior.get(field) not in (None, "")
            for field in (
                "position_reconstruction_schema_version",
                "position_reconstruction_hash",
                "position_reconstruction_generated_at",
            )
        )
        if has_reconstruction_envelope:
            restored, restore_reasons = _restore_hashed_prior_position(
                prior,
                observed_at=generated_utc,
            )
            if restored is not None:
                positions[prior_key] = restored
                restored_prior_rows[prior_key] = prior
                continue
            block = {
                "symbol": prior.get("symbol"),
                "position_id": prior.get("position_id"),
                "position_generation_id": prior.get("position_generation_id"),
                "paper_lifecycle_status": "POSITION_RECONSTRUCTION_BLOCKED",
                "paper_lifecycle_block_reasons": restore_reasons,
                "paper_only": True,
                "places_real_order": False,
            }
            reconstruction_blocks.append(block)
            blocked_entries.append(block)
            blocked_prior_keys.add(prior_key)
            continue
        if _prior_has_partial_close_evidence(prior, closed_trades):
            block = {
                "symbol": prior.get("symbol"),
                "position_id": prior.get("position_id"),
                "position_generation_id": prior.get("position_generation_id"),
                "paper_lifecycle_status": "LEGACY_PARTIAL_POSITION_RECONSTRUCTION_BLOCKED",
                "paper_lifecycle_block_reasons": [
                    "LEGACY_PARTIAL_POSITION_MISSING_VERSIONED_HASHED_RECONSTRUCTION"
                ],
                "paper_only": True,
                "places_real_order": False,
            }
            reconstruction_blocks.append(block)
            blocked_entries.append(block)
            blocked_prior_keys.add(prior_key)

    for fill in accepted_fills:
        if not isinstance(fill, dict):
            continue
        fill_id = _fill_identity(fill)
        has_netting_receipt = any(
            fill.get(field) not in (None, "")
            for field in (
                "paper_netting_fill_receipt_schema_version",
                "paper_netting_fill_receipt_hash",
                "paper_netting_close_id",
            )
        )
        netting_receipt_reasons = (
            _netting_receipt_integrity_reasons(
                fill,
                closed_trades=closed_trades,
            )
            if has_netting_receipt
            else []
        )
        if netting_receipt_reasons:
            rejected = dict(fill)
            rejected["paper_lifecycle_status"] = (
                "HISTORICAL_NETTING_FILL_RECEIPT_BLOCKED"
            )
            rejected["paper_lifecycle_block_reasons"] = netting_receipt_reasons
            blocked_entries.append(rejected)
            continue
        if (
            not has_netting_receipt
            and str(fill.get("paper_lifecycle_status") or "")
            in {
                "CLOSE_OR_REDUCE_EXISTING_POSITION",
                "NETTING_FILL_CONSUMED_PREVIOUSLY",
            }
        ):
            rejected = dict(fill)
            rejected["paper_lifecycle_status"] = (
                "LEGACY_HISTORICAL_NETTING_FILL_BLOCKED"
            )
            rejected["paper_lifecycle_block_reasons"] = [
                "LEGACY_NETTING_FILL_MISSING_VERSIONED_CLOSE_RECEIPT"
            ]
            blocked_entries.append(rejected)
            continue
        historical_netting = _historical_netting_receipt_evidence(
            fill,
            closed_trades=closed_trades,
        )
        if historical_netting is not None:
            carried = _accepted_fill_with_entry_policy_metadata(
                fill,
                status="NETTING_FILL_CONSUMED_PREVIOUSLY",
            )
            carried["historical_netting_receipt_evidence"] = historical_netting
            closed_previously_fills.append(carried)
            continue
        fill_symbol = str(fill.get("symbol") or "").upper()
        fill_key = (
            _hedge_position_key(fill_symbol)
            if _is_hedge_child_row(fill)
            else fill_symbol
        )
        if fill_key in blocked_prior_keys:
            rejected = dict(fill)
            rejected["paper_lifecycle_status"] = (
                "ENTRY_BLOCKED_BY_UNRESTORABLE_PRIOR_POSITION"
            )
            rejected["paper_lifecycle_block_reasons"] = [
                "PRIOR_OPEN_POSITION_RECONSTRUCTION_NOT_TRUSTED"
            ]
            blocked_entries.append(rejected)
            continue
        seeded_position = positions.get(fill_key)
        seeded_prior = restored_prior_rows.get(fill_key)
        if seeded_position is not None and seeded_prior is not None:
            replay_status, replay_blockers = _seeded_fill_replay_status(
                fill,
                position=seeded_position,
                prior=seeded_prior,
            )
            if replay_status is not None:
                continue
            if replay_blockers:
                rejected = dict(fill)
                rejected["paper_lifecycle_status"] = (
                    "ENTRY_BLOCKED_AMBIGUOUS_SOURCE_FILL_REPLAY"
                )
                rejected["paper_lifecycle_block_reasons"] = replay_blockers
                blocked_entries.append(rejected)
                continue
        fill_generation = entry_generation_identity(
            fill,
            source_identity_override=fill_id,
        )
        dedupe_identity = (
            fill_generation.generation_id
            if fill_generation.complete
            else f"legacy:{fill_id}"
        )
        if dedupe_identity in seen_fill_generations:
            continue
        seen_fill_generations.add(dedupe_identity)
        closed_evidence = _closed_generation_evidence(
            fill,
            fill_id=fill_id,
            closed_trades=closed_trades,
        )
        if closed_evidence is not None:
            carried = _accepted_fill_with_entry_policy_metadata(
                fill,
                status="CLOSED_PREVIOUSLY",
            )
            carried["closed_generation_match"] = closed_evidence
            carried["position_generation_id"] = fill_generation.generation_id
            closed_previously_fills.append(carried)
            continue
        classified = classify_fill(fill)
        if not classified["economic"]:
            rejected = dict(fill)
            rejected["paper_lifecycle_status"] = "ENTRY_BLOCKED"
            rejected["paper_lifecycle_block_reasons"] = classified["blockers"]
            blocked_entries.append(rejected)
            continue
        symbol = str(classified["symbol"])
        side = str(classified["side"])
        quantity = float(classified["quantity"])
        notional = abs(float(classified["notional"]))
        # ADAPTIVE FIX: Derive price from notional/quantity if price is missing
        price = classified["price"]
        if price is None or price <= 0:
            if notional > 0 and quantity > 0:
                price = notional / quantity
            else:
                price = 1.0  # Fallback: unit price for accounting purposes
        else:
            price = float(price)
        # Explicit adaptive hedge routing (operator-gated via
        # config.allow_explicit_hedge): a tagged hedge fill opens a paired
        # hedge position under "{symbol}::HEDGE" and must NEVER fall through
        # to the opposite-side netting close below — same-symbol netting is
        # load-bearing for untagged fills (TIER_3_MODEL_REVERSAL_NETTING).
        if (
            config.allow_explicit_hedge
            and fill.get("hedge_intent") is True
            and fill.get("hedge_parent_id")
        ):
            hedge_key = _hedge_position_key(symbol)
            if hedge_key in positions:
                netting_events.append(
                    {
                        "symbol": symbol,
                        "event": "EXPLICIT_HEDGE_DUPLICATE_SKIPPED",
                        "side": side,
                        "quantity": quantity,
                    }
                )
                continue
            cap = evaluate_exposure_caps(
                positions=positions,
                symbol=symbol,
                candidate_notional=notional,
                caps=config.exposure_caps,
                portfolio_equity_usdt=config.portfolio_equity_usdt,
            )
            cap_evaluations.append(cap)
            if not cap["allowed"]:
                rejected = dict(fill)
                rejected["paper_lifecycle_status"] = "ENTRY_BLOCKED"
                rejected["paper_lifecycle_block_reasons"] = list(cap["blockers"])
                rejected["paper_hedge_admission_blocked_by_exposure_caps"] = True
                blocked_entries.append(rejected)
                continue
            positions[hedge_key] = position_from_fill(
                fill, fill_id=fill_id, side=side, quantity=quantity, price=price
            )
            _carry_prior_position_state(positions[hedge_key], prior_positions.get(hedge_key))
            parent_position = positions.get(symbol)
            if parent_position is not None:
                parent_position.hedge_state = "HEDGED"
                parent_position.hedge_reason = str(
                    fill.get("hedge_reason") or "ADAPTIVE_ADVERSE_EXCURSION_HEDGE"
                )
                parent_position.hedge_child_id = str(fill_id)
            accepted_open_fills.append(
                _accepted_fill_with_position_metadata(
                    fill,
                    status="HEDGE_POSITION_OPENED",
                    position=positions[hedge_key],
                )
            )
            netting_events.append(
                {
                    "symbol": symbol,
                    "event": "EXPLICIT_HEDGE_OPENED",
                    "side": side,
                    "quantity": quantity,
                    "hedge_parent_id": fill.get("hedge_parent_id"),
                }
            )
            continue
        existing = positions.get(symbol)
        if existing is None:
            cap = evaluate_exposure_caps(
                positions=positions,
                symbol=symbol,
                candidate_notional=notional,
                caps=config.exposure_caps,
                portfolio_equity_usdt=config.portfolio_equity_usdt,
            )
            cap_evaluations.append(cap)
            if not cap["allowed"]:
                rejected = dict(fill)
                rejected["paper_lifecycle_status"] = "ENTRY_BLOCKED"
                rejected["paper_lifecycle_block_reasons"] = list(cap["blockers"])
                blocked_entries.append(rejected)
                continue
            positions[symbol] = position_from_fill(fill, fill_id=fill_id, side=side, quantity=quantity, price=price)
            _carry_prior_position_state(positions[symbol], prior_positions.get(symbol))
            accepted_open_fills.append(
                _accepted_fill_with_position_metadata(
                    fill,
                    status="OPEN_POSITION",
                    position=positions[symbol],
                )
            )
            netting_events.append({"symbol": symbol, "event": "OPEN_POSITION", "side": side, "quantity": quantity})
            continue
        if existing.side == side:
            cap = evaluate_exposure_caps(
                positions=positions,
                symbol=symbol,
                candidate_notional=notional,
                caps=config.exposure_caps,
                portfolio_equity_usdt=config.portfolio_equity_usdt,
            )
            cap_evaluations.append(cap)
            if not cap["allowed"]:
                rejected = dict(fill)
                rejected["paper_lifecycle_status"] = "ENTRY_BLOCKED"
                rejected["paper_lifecycle_block_reasons"] = list(cap["blockers"])
                blocked_entries.append(rejected)
                continue
            incoming_position = position_from_fill(
                fill,
                fill_id=fill_id,
                side=side,
                quantity=quantity,
                price=price,
            )
            try:
                existing.apply_same_side_fill(
                    fill_id=fill_id,
                    quantity=quantity,
                    price=price,
                    incoming_position=incoming_position,
                )
                _carry_prior_position_state(
                    existing,
                    fill,
                    require_generation_match=False,
                    carry_capital=False,
                )
            except ValueError as exc:
                rejected = dict(fill)
                rejected["paper_lifecycle_status"] = "ENTRY_BLOCKED"
                rejected["paper_lifecycle_block_reasons"] = [
                    "PAPER_SAME_SIDE_CAPITAL_AGGREGATION_FAILED"
                ]
                rejected["paper_same_side_capital_error"] = str(exc)
                blocked_entries.append(rejected)
                continue
            accepted_open_fills.append(
                _accepted_fill_with_position_metadata(
                    fill,
                    status="NETTED_INTO_EXISTING_POSITION",
                    position=existing,
                )
            )
            netting_events.append({"symbol": symbol, "event": "NET_SAME_DIRECTION", "side": side, "quantity": quantity})
            continue

        close_qty = min(existing.net_quantity, quantity)
        exit_spread_bps, exit_spread_source, exit_spread_available_at = _exit_spread_from_mapping(fill)
        close_event, outcome, dirty_close_block = _close_position(
            positions=positions,
            symbol=symbol,
            close_quantity=close_qty,
            exit_price=price,
            exit_time=generated_utc,
            close_reason="TIER_3_MODEL_REVERSAL_NETTING",
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            exit_signal_id=fill.get("signal_id"),
            exit_prediction_id=fill.get("prediction_id") or fill.get("source_prediction_id"),
            exit_spread_bps=exit_spread_bps,
            exit_spread_source=exit_spread_source,
            exit_spread_available_at=exit_spread_available_at,
            exit_audit_context=_exit_audit_context(exit_config=config.exit_config),
        )
        if dirty_close_block is not None:
            dirty_close_blocks.append(dirty_close_block)
            rejected = dict(fill)
            rejected["paper_lifecycle_status"] = "CLOSE_BLOCKED_DIRTY_TELEMETRY"
            rejected["paper_lifecycle_block_reasons"] = list(dirty_close_block["paper_close_block_reasons"])
            blocked_entries.append(rejected)
            netting_events.append({
                "symbol": symbol,
                "event": "OPPOSITE_SIDE_CLOSE_BLOCKED_DIRTY_TELEMETRY",
                "from_side": existing.side,
                "to_side": side,
                "quantity": close_qty,
                "block_reasons": list(dirty_close_block["paper_close_block_reasons"]),
            })
            continue
        if close_event is not None and outcome is not None:
            closed_trades.append(close_event)
            outcome_labels.append(outcome)
            new_close_events.append(close_event)
            new_outcomes.append(outcome)
        netting_events.append({"symbol": symbol, "event": "OPPOSITE_SIDE_REDUCED_OR_CLOSED", "from_side": existing.side, "to_side": side, "quantity": close_qty})
        residual_qty = max(0.0, quantity - close_qty)
        if residual_qty <= 1e-12:
            consumed_fill = _accepted_fill_with_entry_policy_metadata(
                fill,
                status="CLOSE_OR_REDUCE_EXISTING_POSITION",
            )
            if close_event is not None:
                consumed_fill = _attach_netting_receipt(
                    consumed_fill,
                    close_event=close_event,
                    input_quantity=quantity,
                    consumed_quantity=close_qty,
                    residual_quantity=0.0,
                )
            accepted_open_fills.append(consumed_fill)
            continue
        residual_notional = abs(residual_qty * price)
        cap = evaluate_exposure_caps(
            positions=positions,
            symbol=symbol,
            candidate_notional=residual_notional,
            caps=config.exposure_caps,
            portfolio_equity_usdt=config.portfolio_equity_usdt,
        )
        cap_evaluations.append(cap)
        if not cap["allowed"]:
            rejected = dict(fill)
            rejected["paper_lifecycle_status"] = "REVERSE_ENTRY_BLOCKED_AFTER_NETTING"
            rejected["paper_lifecycle_block_reasons"] = list(cap["blockers"])
            blocked_entries.append(rejected)
            continue
        reverse_fill = dict(fill)
        reverse_fill["quantity"] = residual_qty
        reverse_fill["notional"] = residual_notional
        reverse_fill["notional_usdt"] = residual_notional
        positions[symbol] = position_from_fill(reverse_fill, fill_id=fill_id, side=side, quantity=residual_qty, price=price)
        _carry_prior_position_state(positions[symbol], prior_positions.get(symbol))
        reverse_row = _accepted_fill_with_position_metadata(
            reverse_fill,
            status="REVERSE_POSITION_OPENED_AFTER_NETTING",
            position=positions[symbol],
        )
        if close_event is not None:
            reverse_row = _attach_netting_receipt(
                reverse_row,
                close_event=close_event,
                input_quantity=quantity,
                consumed_quantity=close_qty,
                residual_quantity=residual_qty,
            )
        accepted_open_fills.append(reverse_row)

    # ── Adaptive hedge pair management (pre-pass) ─────────────────────────
    # Hedge children ("{SYM}::HEDGE" keys) are owned by the pair manager, not
    # the standard exit tiers. Evaluate unwind/close-both for every pair
    # before standard exits so a HOLD verdict can defer the parent's TIER_1
    # ATR stop below (TIER_0 tiers are never deferred).
    hedge_directives: list[dict[str, Any]] = []
    hedge_pair_events: list[dict[str, Any]] = []
    hedge_protected_symbols: set[str] = set()
    if config.allow_explicit_hedge:
        for hedge_key in [k for k in list(positions.keys()) if k.endswith("::HEDGE")]:
            hedge_position = positions.get(hedge_key)
            if hedge_position is None:
                continue
            base_symbol = hedge_key.split("::")[0]
            parent_position = positions.get(base_symbol)
            mark, _mark_src = _mark_for_symbol(
                mark_prices, base_symbol, hedge_position.last_mark_price or hedge_position.avg_entry_price
            )
            maintenance_bracket = _maintenance_bracket_for_symbol(
                mark_prices,
                base_symbol,
            )
            if mark is None or mark <= 0:
                hedge_pair_events.append(
                    {"symbol": base_symbol, "action": "HOLD", "reason": "MARK_PRICE_MISSING"}
                )
                if parent_position is not None:
                    hedge_protected_symbols.add(base_symbol)
                continue
            hedge_position.update_mark(
                mark_price=mark,
                mark_time=generated_utc,
                maintenance_bracket_evidence=maintenance_bracket,
            )
            hedge_pnl_bps_value = hedge_position.unrealized_pnl_bps()
            parent_pnl_bps_value = None
            parent_payload: dict[str, Any] = {}
            if parent_position is not None:
                parent_position.update_mark(
                    mark_price=mark,
                    mark_time=generated_utc,
                    maintenance_bracket_evidence=maintenance_bracket,
                )
                parent_pnl_bps_value = parent_position.unrealized_pnl_bps()
                parent_payload = parent_position.to_payload(generated_utc=generated_utc)
            hedge_best_excursion = None
            if (
                hedge_position.best_favorable_price
                and hedge_position.avg_entry_price
                and hedge_position.avg_entry_price > 0
            ):
                if hedge_position.side == "long":
                    hedge_best_excursion = (
                        (hedge_position.best_favorable_price - hedge_position.avg_entry_price)
                        / hedge_position.avg_entry_price
                        * 10000.0
                    )
                else:
                    hedge_best_excursion = (
                        (hedge_position.avg_entry_price - hedge_position.best_favorable_price)
                        / hedge_position.avg_entry_price
                        * 10000.0
                    )
            parent_atr_stop = None
            if parent_position is not None:
                parent_atr_stop = effective_atr_stop_bps(
                    atr_bps=parent_position.entry_atr_bps,
                    confidence_calibrated=parent_position.confidence_calibrated,
                    strategy_selected_mode=parent_position.strategy_selected_mode,
                    market_regime=parent_position.market_regime_at_entry,
                    config=config.exit_config,
                )
            unwind = evaluate_adaptive_hedge_unwind(
                parent_payload=parent_payload,
                hedge_payload=hedge_position.to_payload(generated_utc=generated_utc),
                parent_pnl_bps=parent_pnl_bps_value,
                hedge_pnl_bps=hedge_pnl_bps_value,
                hedge_best_excursion_bps=hedge_best_excursion,
                parent_atr_stop_bps=parent_atr_stop,
                hedge_hold_seconds=seconds_between(hedge_position.opened_est, generated_utc),
                max_hold_seconds=float(config.exit_config.max_hold_seconds),
                fee_bps=config.fee_bps,
                slippage_bps=config.slippage_bps,
            )
            action = str(unwind.get("action") or "HOLD")
            hedge_pair_events.append({"symbol": base_symbol, **unwind})
            if action in ("UNWIND_HEDGE", "ORPHAN_UNWIND"):
                close_event, outcome, dirty_block = _close_position(
                    positions=positions,
                    symbol=hedge_key,
                    close_quantity=hedge_position.net_quantity,
                    exit_price=mark,
                    exit_time=generated_utc,
                    close_reason="TIER_2_HEDGE_UNWIND_EXHAUSTED",
                    fee_bps=config.fee_bps,
                    slippage_bps=config.slippage_bps,
                    exit_audit_context=_exit_audit_context(exit_config=config.exit_config),
                )
                if dirty_block is not None:
                    dirty_close_blocks.append(dirty_block)
                elif close_event is not None and outcome is not None:
                    closed_trades.append(close_event)
                    outcome_labels.append(outcome)
                    new_close_events.append(close_event)
                    new_outcomes.append(outcome)
                if parent_position is not None:
                    parent_position.hedge_state = "HEDGE_UNWOUND"
                    parent_position.hedge_reason = str(unwind.get("reason") or "HEDGE_UNWOUND")
            elif action == "CLOSE_BOTH":
                for close_key, close_pos in ((hedge_key, hedge_position), (base_symbol, parent_position)):
                    if close_pos is None or close_key not in positions:
                        continue
                    close_event, outcome, dirty_block = _close_position(
                        positions=positions,
                        symbol=close_key,
                        close_quantity=close_pos.net_quantity,
                        exit_price=mark,
                        exit_time=generated_utc,
                        close_reason="TIER_2_HEDGE_PAIR_CLOSE",
                        fee_bps=config.fee_bps,
                        slippage_bps=config.slippage_bps,
                        exit_audit_context=_exit_audit_context(exit_config=config.exit_config),
                    )
                    if dirty_block is not None:
                        dirty_close_blocks.append(dirty_block)
                    elif close_event is not None and outcome is not None:
                        closed_trades.append(close_event)
                        outcome_labels.append(outcome)
                        new_close_events.append(close_event)
                        new_outcomes.append(outcome)
            else:
                if parent_position is not None:
                    hedge_protected_symbols.add(base_symbol)

    for symbol, position in list(positions.items()):
        if symbol.endswith("::HEDGE"):
            # Hedge children are pair-managed above; standard exit tiers must
            # not close them independently.
            continue
        mark, mark_source = _mark_for_symbol(mark_prices, symbol, position.last_mark_price or position.avg_entry_price)
        if mark is None and _structured_market_price_evidence_required(
            mark_prices,
            symbol,
        ):
            # A structured mark explicitly opts into fail-closed evidence.
            # Preserve the position's prior mark and produce no close/outcome;
            # using the entry/last mark here would launder rejected evidence
            # through a lifecycle fallback.
            exit_evaluations.append(
                {
                    "symbol": symbol,
                    "should_close": False,
                    "close_reason": None,
                    "mark_price_source": mark_source,
                    "blocker": "VERIFIED_MARKET_PRICE_EVIDENCE_REQUIRED",
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                }
            )
            continue
        maintenance_bracket = _maintenance_bracket_for_symbol(mark_prices, symbol)
        exit_spread_bps, exit_spread_source, exit_spread_available_at = _exit_spread_from_mapping(
            mark_prices.get(symbol.upper()) if isinstance(mark_prices, dict) else None
        )
        position.update_mark(
            mark_price=mark,
            mark_time=generated_utc,
            maintenance_bracket_evidence=maintenance_bracket,
        )
        effective_exit_config, trailing_context_decision = _exit_config_for_trailing_context(
            position=position,
            base_exit_config=config.exit_config,
            global_circuit_breaker=trailing_circuit_breaker,
            context_policy=trailing_context_policy,
        )
        trailing_context_decisions.append(trailing_context_decision)
        exit_eval = evaluate_exit(
            position=position,
            mark_price=mark,
            generated_utc=generated_utc,
            config=effective_exit_config,
            alpha_context={
                **(position.liquidity_zone_context or {}),
                **(position.liquidation_distance_context or {}),
                **(position.microstructure_context or {}),
            },
            model_context={},
            account_context={},
            atr_bps=position.entry_atr_bps,
            ob_spread_bps=(
                position.entry_observed_spread_bps
                if position.entry_observed_spread_bps is not None
                else None
            ),
        )
        # Portfolio cascade guard (paper-only): a confirmed cascade on a LOSING
        # position, or a portfolio-level worst-case liquidation breach, forces a
        # TIER_0 protective close -- one coin's MM move must never cascade the
        # book (legacy failure mode). Winning positions are left to ride; the
        # trailing/sweep-reversal exits own the reversal.
        _guard_directives = {
            str(d.get("symbol") or "").upper(): d
            for d in ((portfolio_guard or {}).get("directives") or [])
            if isinstance(d, dict)
        }
        _guard_hit = _guard_directives.get(symbol.upper())
        if _guard_hit and str(_guard_hit.get("action") or "").upper() == "CLOSE":
            exit_eval = {
                "should_close": True,
                "close_reason": "TIER_0_PORTFOLIO_CASCADE_GUARD",
                "tier": 0,
                "pnl_bps": position.unrealized_pnl_bps(),
                "portfolio_cascade_guard_reason": _guard_hit.get("reason"),
                "portfolio_cascade_guard_cascade_score": _guard_hit.get("cascade_score"),
            }
        # ── Adaptive hedging hooks (operator-gated) ───────────────────────
        if config.allow_explicit_hedge and mark is not None:
            _would_atr_stop = (
                exit_eval.get("should_close") is True
                and str(exit_eval.get("close_reason") or "") == "TIER_1_ATR_VOLATILITY_STOP"
            )
            if symbol in hedge_protected_symbols and _would_atr_stop:
                # An active hedge already covers this adverse move; the pair
                # manager owns the exit. TIER_0 tiers are never deferred.
                exit_eval = {
                    "should_close": False,
                    "close_reason": None,
                    "tier": None,
                    "blocker": "ATR_STOP_DEFERRED_TO_ACTIVE_HEDGE",
                    "pnl_bps": exit_eval.get("pnl_bps"),
                    "deferred_close_reason": "TIER_1_ATR_VOLATILITY_STOP",
                }
                _would_atr_stop = False
            elif (
                _would_atr_stop
                and str(position.hedge_state or "").upper() == "HEDGE_PENDING"
            ):
                # The hedge fill is in flight (directive emitted, synthesis
                # lands next cycle). Without this, the stop closes the parent
                # before the hedge can open (observed: BARDUSDT directive at
                # one cycle, TIER_1 close the next, synthesis skipped with
                # PARENT_POSITION_NO_LONGER_OPEN). The deferral is BOUNDED:
                # ~2 directive lifetimes, after which the pending state
                # clears and the stop fires normally; the TIER_0 catastrophic
                # floor stays armed throughout.
                _pending_age = seconds_between(
                    position.hedge_pending_since or position.opened_est, generated_utc
                )
                if _pending_age <= 600:
                    exit_eval = {
                        "should_close": False,
                        "close_reason": None,
                        "tier": None,
                        "blocker": "ATR_STOP_DEFERRED_HEDGE_FILL_IN_FLIGHT",
                        "pnl_bps": exit_eval.get("pnl_bps"),
                        "deferred_close_reason": "TIER_1_ATR_VOLATILITY_STOP",
                        "hedge_pending_age_seconds": _pending_age,
                    }
                    _would_atr_stop = False
                else:
                    position.hedge_state = "NO_HEDGE"
                    position.hedge_reason = "HEDGE_PENDING_EXPIRED_STOP_RESUMES"
                    position.hedge_pending_since = None
            elif (
                symbol not in hedge_protected_symbols
                and (exit_eval.get("should_close") is not True or _would_atr_stop)
                and str(position.hedge_state or "NO_HEDGE").upper() in ("", "NO_HEDGE", "NONE")
            ):
                _pnl_bps_now = position.unrealized_pnl_bps()
                _atr_stop_now = coerce_float(exit_eval.get("atr_stop_bps"))
                if _atr_stop_now is None or _atr_stop_now <= 0:
                    _atr_stop_now = effective_atr_stop_bps(
                        atr_bps=position.entry_atr_bps,
                        confidence_calibrated=position.confidence_calibrated,
                        strategy_selected_mode=position.strategy_selected_mode,
                        market_regime=position.market_regime_at_entry,
                        config=effective_exit_config,
                    )
                trigger = evaluate_adaptive_hedge_trigger(
                    position_payload=position.to_payload(generated_utc=generated_utc),
                    pnl_bps=_pnl_bps_now,
                    atr_stop_bps=_atr_stop_now,
                    portfolio_drawdown_bps=config.portfolio_drawdown_bps,
                    drawdown_emergency_bps=effective_exit_config.drawdown_emergency_bps,
                    fee_bps=config.fee_bps,
                    slippage_bps=config.slippage_bps,
                )
                if trigger.get("trigger") is True:
                    position.hedge_state = "HEDGE_PENDING"
                    position.hedge_reason = str(trigger.get("reason"))
                    position.hedge_pending_since = generated_utc
                    hedge_directives.append(
                        {
                            "symbol": symbol,
                            "parent_position_id": position.position_id,
                            "parent_entry_fill_id": (
                                position.fill_ids[0] if position.fill_ids else position.position_id
                            ),
                            "hedge_side": trigger.get("hedge_side"),
                            "hedge_ratio": trigger.get("hedge_ratio"),
                            "hedge_quantity": round(
                                position.net_quantity * float(trigger.get("hedge_ratio") or 0.0), 12
                            ),
                            "mark_price": mark,
                            "parent_pnl_bps_at_trigger": _pnl_bps_now,
                            "atr_stop_bps_at_trigger": _atr_stop_now,
                            "reason": trigger.get("reason"),
                            "trigger_diagnostics": {
                                k: v
                                for k, v in trigger.items()
                                if k not in ("trigger", "reason", "hedge_side", "hedge_ratio")
                            },
                            "generated_utc": generated_utc,
                            "paper_only": True,
                            "places_real_order": False,
                        }
                    )
                    if _would_atr_stop:
                        # Convert the imminent full stop-out into a hedge:
                        # position stays open, hedge fill synthesizes next
                        # cycle, TIER_0 catastrophic floor stays armed.
                        exit_eval = {
                            "should_close": False,
                            "close_reason": None,
                            "tier": None,
                            "blocker": "ATR_STOP_CONVERTED_TO_HEDGE_DIRECTIVE",
                            "pnl_bps": _pnl_bps_now,
                            "deferred_close_reason": "TIER_1_ATR_VOLATILITY_STOP",
                            "hedge_directive_emitted": True,
                        }
        exit_eval["symbol"] = symbol
        exit_eval["mark_price_source"] = mark_source
        exit_eval["trailing_context_decision"] = trailing_context_decision
        exit_evaluations.append(exit_eval)
        if exit_eval.get("should_close") is not True or mark is None:
            continue
        exit_price = mark
        paper_exit_price = coerce_float(exit_eval.get("paper_exit_price"))
        if (
            exit_eval.get("close_reason") == "TIER_2_TRAILING_STOP"
            and paper_exit_price is not None
            and paper_exit_price > 0
        ):
            exit_price = paper_exit_price
        close_event, outcome, dirty_close_block = _close_position(
            positions=positions,
            symbol=symbol,
            close_quantity=position.net_quantity,
            exit_price=exit_price,
            exit_time=generated_utc,
            close_reason=str(exit_eval.get("close_reason")),
            fee_bps=config.fee_bps,
            slippage_bps=config.slippage_bps,
            exit_spread_bps=exit_spread_bps,
            exit_spread_source=exit_spread_source,
            exit_spread_available_at=exit_spread_available_at,
            exit_audit_context=_exit_audit_context(
                exit_config=effective_exit_config,
                exit_eval=exit_eval,
                trailing_context_decision=trailing_context_decision,
            ),
        )
        if dirty_close_block is not None:
            dirty_close_blocks.append(dirty_close_block)
            exit_eval["close_blocked"] = True
            exit_eval["close_block_reasons"] = list(dirty_close_block["paper_close_block_reasons"])
            continue
        if close_event is not None and outcome is not None:
            closed_trades.append(close_event)
            outcome_labels.append(outcome)
            new_close_events.append(close_event)
            new_outcomes.append(outcome)

    for prior_key, prior in restored_prior_rows.items():
        restored_position = positions.get(prior_key)
        if restored_position is None or str(
            restored_position.position_generation_id or ""
        ) != str(prior.get("position_generation_id") or ""):
            continue
        snapshot_payload = restored_position.to_payload(generated_utc=generated_utc)
        accepted_open_fills.append(
            _accepted_fill_with_position_metadata(
                snapshot_payload,
                status="OPEN_POSITION_RESTORED_FROM_HASHED_SNAPSHOT",
                position=restored_position,
            )
        )

    open_positions = [pos.to_payload(generated_utc=generated_utc) for pos in positions.values()]
    # Hedge children key under "{SYM}::HEDGE" so they never overwrite the
    # parent row (both payloads carry the same base symbol field).
    positions_by_symbol = {
        (_hedge_position_key(row["symbol"]) if _is_hedge_child_row(row) else row["symbol"]): row
        for row in open_positions
    }
    policy_funding_repair_accepted_rows = [
        *accepted_open_fills,
        *closed_previously_fills,
        *[dict(row) for row in accepted_fills if isinstance(row, dict)],
    ]
    closed_trades, policy_funding_repair_report, _closed_repair_by_token = repair_policy_funding_rows(
        closed_trades,
        accepted_rows=policy_funding_repair_accepted_rows,
        generated_at=generated_utc,
    )
    outcome_labels, outcome_policy_funding_repair_report, _outcome_repair_by_token = repair_policy_funding_rows(
        outcome_labels,
        accepted_rows=policy_funding_repair_accepted_rows,
        generated_at=generated_utc,
    )
    closed_trades = _normalize_realized_pnl_rows(closed_trades)
    outcome_labels = _normalize_realized_pnl_rows(outcome_labels)
    realized_total = sum(_realized_pnl(row) for row in closed_trades)
    realized_gross_total = sum(
        _first_realized_number(
            row, "realized_pnl_usd", "realized_pnl_usdt", "realized_pnl"
        )
        or 0.0
        for row in closed_trades
    )
    unrealized_total = sum(float(row.get("unrealized_pnl") or 0.0) for row in open_positions)
    total_exposure = sum(float(row.get("notional") or 0.0) for row in open_positions)
    close_reasons: dict[str, int] = {}
    for close in closed_trades:
        reason = str(close.get("close_reason") or "UNKNOWN_CLOSE_REASON")
        close_reasons[reason] = close_reasons.get(reason, 0) + 1
    active_policy_closed_trades = [
        row
        for row in closed_trades
        if str(row.get("paper_exit_policy_version") or "") == PAPER_EXIT_POLICY_VERSION
    ]
    active_policy_close_reasons: dict[str, int] = {}
    for close in active_policy_closed_trades:
        reason = str(close.get("close_reason") or "UNKNOWN_CLOSE_REASON")
        active_policy_close_reasons[reason] = active_policy_close_reasons.get(reason, 0) + 1
    historical_trailing_stop_count = len(_trailing_stop_rows(closed_trades))
    active_policy_trailing_stop_count = len(_trailing_stop_rows(active_policy_closed_trades))
    any_trailing_enabled = any(
        bool(row.get("trailing_stop_enabled")) for row in trailing_context_decisions
    ) if trailing_context_decisions else (
        bool(config.exit_config.trailing_stop_enabled) and not bool(trailing_circuit_breaker.get("disabled"))
    )
    trailing_context_status = _trailing_context_policy_status(trailing_context_policy)
    trailing_context_status["position_decisions"] = trailing_context_decisions[:25]

    return {
        "generated_utc": generated_utc,
        "accepted_open_fills": accepted_open_fills,
        "closed_previously_fills": closed_previously_fills,
        "blocked_entries": blocked_entries,
        "open_positions": open_positions,
        "positions_by_symbol": positions_by_symbol,
        "closed_trades": closed_trades,
        "new_close_events": new_close_events,
        "outcome_labels": outcome_labels,
        "new_outcome_labels": new_outcomes,
        "realized_pnl_usd": realized_total,
        # Ledger-level aggregate is NET (fees/slippage/funding applied); per-trade
        # realized_pnl_usd is GROSS (bps x notional). Explicit aliases prevent
        # gross-vs-net reconciliation category errors (guardian gate G08).
        "realized_net_pnl_usd": realized_total,
        "realized_gross_pnl_usd": realized_gross_total,
        "unrealized_pnl_usd": unrealized_total,
        "total_open_notional": total_exposure,
        "paper_position_lifecycle_status": {
            "state_machine": "NEW_SIGNAL->ENTRY_CHECK->OPEN_POSITION->HOLD->REDUCE->CLOSE->CLOSED->OUTCOME_LABEL_WRITTEN",
            "open_positions_count": len(open_positions),
            "closed_positions_count": len(closed_trades),
            "new_close_event_count": len(new_close_events),
            "closed_previously_fill_count": len(closed_previously_fills),
            "outcome_label_count": len(outcome_labels),
            "blocked_entry_count": len(blocked_entries),
            "dirty_close_block_count": len(dirty_close_blocks),
            "hashed_position_reconstruction_restored_count": len(
                restored_prior_rows
            ),
            "position_reconstruction_block_count": len(reconstruction_blocks),
            "position_reconstruction_blocks": reconstruction_blocks[:25],
            "position_reconstruction_schema_version": (
                PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION
            ),
            "final_close_required_for_source_fill_suppression": True,
        },
        "paper_position_exposure_cap_status": {
            "evaluations": cap_evaluations,
            "blocked_count": sum(1 for row in cap_evaluations if not row.get("allowed")),
            "max_single_symbol_exposure_pct": config.exposure_caps.max_single_symbol_exposure_pct,
            "max_total_paper_exposure_pct": config.exposure_caps.max_total_paper_exposure_pct,
            "portfolio_equity_usdt": config.portfolio_equity_usdt,
            "emergency_absolute_cap_usdt": config.exposure_caps.emergency_absolute_cap_usdt,
        },
        "paper_hedge_netting_status": {
            "accidental_hedge_pairs_allowed": False,
            "events": netting_events,
            "opposite_side_netting_count": sum(1 for row in netting_events if row.get("event") == "OPPOSITE_SIDE_REDUCED_OR_CLOSED"),
            "same_side_netting_count": sum(1 for row in netting_events if row.get("event") == "NET_SAME_DIRECTION"),
        },
        "hedge_directives": hedge_directives,
        "paper_adaptive_hedge_status": {
            "enabled": bool(config.allow_explicit_hedge),
            "active_hedge_pairs": sorted(
                k.split("::")[0] for k in positions.keys() if k.endswith("::HEDGE")
            ),
            "hedge_protected_symbols": sorted(hedge_protected_symbols),
            "directives_emitted": len(hedge_directives),
            "pair_events": hedge_pair_events[:25],
            "explicit_hedge_opens": sum(
                1 for row in netting_events if row.get("event") == "EXPLICIT_HEDGE_OPENED"
            ),
            "paper_only": True,
            "places_real_order": False,
        },
        "paper_exit_coordinator_status": {
            "tiers_enabled": ["TIER_0", "TIER_1", "TIER_2", "TIER_3", "TIER_4"],
            "evaluations": exit_evaluations,
            "close_reasons": close_reasons,
            "active_policy_version": PAPER_EXIT_POLICY_VERSION,
            "active_policy_close_reasons": active_policy_close_reasons,
            "active_policy_closed_trade_count": len(active_policy_closed_trades),
            "active_policy_trailing_stop_triggered_count": active_policy_trailing_stop_count,
            "dirty_close_blocks": dirty_close_blocks[:25],
            "dirty_close_block_count": len(dirty_close_blocks),
            "trailing_stop_runtime_circuit_breaker": trailing_circuit_breaker,
            "trailing_stop_context_policy": trailing_context_status,
        },
        "paper_stop_takeprofit_trailing_status": {
            "paper_exit_policy_version": PAPER_EXIT_POLICY_VERSION,
            "stop_loss_bps": config.exit_config.stop_loss_bps,
            "static_stop_loss_enabled": config.exit_config.static_stop_loss_enabled,
            "take_profit_bps": config.exit_config.take_profit_bps,
            "static_take_profit_enabled": config.exit_config.static_take_profit_enabled,
            "static_profit_lock_enabled": config.exit_config.static_profit_lock_enabled,
            "static_profit_bank_enabled": config.exit_config.static_profit_bank_enabled,
            "trailing_stop_bps": config.exit_config.trailing_stop_bps,
            "min_profit_before_trailing_bps": config.exit_config.min_profit_before_trailing_bps,
            "trailing_stop_min_after_cost_buffer_bps": (
                config.exit_config.trailing_stop_min_after_cost_buffer_bps
            ),
            "atr_trailing_stop_multiplier": config.exit_config.atr_trailing_stop_multiplier,
            "trailing_stop_enabled": any_trailing_enabled,
            "trailing_stop_runtime_circuit_breaker": trailing_circuit_breaker,
            "trailing_stop_context_policy": trailing_context_status,
            "max_hold_seconds": config.exit_config.max_hold_seconds,
            "static_max_hold_enabled": config.exit_config.static_max_hold_enabled,
            "min_hold_seconds": config.exit_config.min_hold_seconds,
            "new_close_event_count": len(new_close_events),
            "historical_trailing_stop_triggered_count": historical_trailing_stop_count,
            "active_policy_version": PAPER_EXIT_POLICY_VERSION,
            "active_policy_closed_trade_count": len(active_policy_closed_trades),
            "active_policy_trailing_stop_triggered_count": active_policy_trailing_stop_count,
            "active_policy_close_reasons": active_policy_close_reasons,
            "triggered_count_semantics": "LEGACY_ALIAS_FOR_NEW_CLOSE_EVENT_COUNT",
            "triggered_count": len(new_close_events),
        },
        "paper_closed_trade_outcome_label_status": {
            "closed_trade_count": len(closed_trades),
            "new_closed_trade_count": len(new_close_events),
            "outcome_label_count": len(outcome_labels),
            "trainer_feedback_rows_ready": len(outcome_labels),
            "dirty_close_block_count": len(dirty_close_blocks),
            "dirty_close_blocks": dirty_close_blocks[:25],
            "policy_funding_repair": policy_funding_repair_report,
            "outcome_label_policy_funding_repair": outcome_policy_funding_repair_report,
        },
    }
