from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .accounting import coerce_float
from .caps import PaperExposureCaps, evaluate_exposure_caps
from .exits import PAPER_EXIT_POLICY_VERSION, PaperExitConfig, evaluate_exit
from .netting import classify_fill
from .outcomes import build_close_event
from .policy_funding_repair import repair_policy_funding_rows
from .position_state import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    PaperNetPosition,
    first_present,
    position_from_fill,
    utc_iso_from_any,
    utc_now_iso,
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
    "maintenance_margin_estimate",
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


@dataclass(frozen=True)
class PaperLifecycleConfig:
    exposure_caps: PaperExposureCaps = PaperExposureCaps()
    exit_config: PaperExitConfig = PaperExitConfig()
    fee_bps: float = 4.0
    slippage_bps: float = 2.0
    allow_explicit_hedge: bool = False
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


def _closed_fill_ids(existing_ledger: dict[str, Any]) -> set[str]:
    closed: set[str] = set()
    for row in existing_ledger.get("closed_trades") or existing_ledger.get("closes") or []:
        if not isinstance(row, dict):
            continue
        for fill_id in row.get("source_fill_ids") or []:
            closed.add(str(fill_id))
    return closed


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


def _prior_positions_by_symbol(existing_ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prior: dict[str, dict[str, Any]] = {}
    positions_by_symbol = existing_ledger.get("positions_by_symbol")
    if isinstance(positions_by_symbol, dict):
        for symbol, row in positions_by_symbol.items():
            if isinstance(row, dict):
                prior[str(symbol).upper()] = dict(row)
    for row in existing_ledger.get("open_positions") or []:
        if isinstance(row, dict) and row.get("symbol"):
            prior[str(row["symbol"]).upper()] = dict(row)
    return prior


def _carry_prior_position_state(position: PaperNetPosition, prior: dict[str, Any] | None) -> None:
    if not prior:
        return
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
        "maintenance_margin_estimate",
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
        if attr in _ADAPTIVE_CAPITAL_CARRY_FIELDS and position_has_complete_adaptive_capital:
            continue
        if (
            attr == "adaptive_capital_policy_version"
            and value == ADAPTIVE_CAPITAL_POLICY_VERSION
            and not _prior_has_complete_adaptive_capital_v1(prior)
        ):
            continue
        if value not in (None, "", {}, []):
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


def _mark_for_symbol(mark_prices: dict[str, Any], symbol: str, fallback: float | None) -> tuple[float | None, str | None]:
    value = mark_prices.get(symbol.upper())
    if isinstance(value, dict):
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
    position.realized_pnl += float(
        first_present(close_event.get("realized_net_pnl_usd"), close_event["realized_pnl_usd"])
    )
    position.net_quantity = max(0.0, position.net_quantity - quantity)
    if position.net_quantity <= 1e-12:
        del positions[symbol]
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
    closed_fill_ids = _closed_fill_ids(existing_ledger)
    blocked_entries: list[dict[str, Any]] = []
    accepted_open_fills: list[dict[str, Any]] = []
    closed_previously_fills: list[dict[str, Any]] = []
    cap_evaluations: list[dict[str, Any]] = []
    netting_events: list[dict[str, Any]] = []
    exit_evaluations: list[dict[str, Any]] = []
    new_close_events: list[dict[str, Any]] = []
    new_outcomes: list[dict[str, Any]] = []
    dirty_close_blocks: list[dict[str, Any]] = []
    seen_fill_ids: set[str] = set()

    for fill in accepted_fills:
        if not isinstance(fill, dict):
            continue
        fill_id = _fill_identity(fill)
        if fill_id in seen_fill_ids:
            continue
        seen_fill_ids.add(fill_id)
        if fill_id in closed_fill_ids:
            carried = _accepted_fill_with_entry_policy_metadata(
                fill,
                status="CLOSED_PREVIOUSLY",
            )
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
            existing.apply_same_side_fill(fill_id=fill_id, quantity=quantity, price=price)
            _carry_prior_position_state(existing, fill)
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
            accepted_open_fills.append(
                _accepted_fill_with_entry_policy_metadata(
                    fill,
                    status="CLOSE_OR_REDUCE_EXISTING_POSITION",
                )
            )
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
        accepted_open_fills.append(
            _accepted_fill_with_position_metadata(
                reverse_fill,
                status="REVERSE_POSITION_OPENED_AFTER_NETTING",
                position=positions[symbol],
            )
        )

    for symbol, position in list(positions.items()):
        mark, mark_source = _mark_for_symbol(mark_prices, symbol, position.last_mark_price or position.avg_entry_price)
        exit_spread_bps, exit_spread_source, exit_spread_available_at = _exit_spread_from_mapping(
            mark_prices.get(symbol.upper()) if isinstance(mark_prices, dict) else None
        )
        position.update_mark(mark_price=mark, mark_time=generated_utc)
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

    open_positions = [pos.to_payload(generated_utc=generated_utc) for pos in positions.values()]
    positions_by_symbol = {row["symbol"]: row for row in open_positions}
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
