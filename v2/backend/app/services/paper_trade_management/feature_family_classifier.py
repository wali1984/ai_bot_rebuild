"""Feature family classifier for paper trade gates.

Maps raw feature names (from trainer prediction rows) to canonical family labels.
A family is PRESENT when at least one of its member features appears in the
prediction's feature_names and is NOT in missing_feature_names.
A family is MISSING when ALL of its members are absent or stale.

Critical families for high-precision paper entries:
    mark_price, candles, volume, atr, orderbook, oi_funding,
    long_short_ratio, microstructure, liquidation_clusters,
    sweep_spoof_wall, paper_context, public_intel

Non-critical (nice-to-have) families:
    volatility, spread, taker_flow

Architecture principle:
    This module is pure classification logic with no I/O and no state.
    It can be called at every paper fill evaluation without Redis or DB access.
"""
from __future__ import annotations

from typing import Mapping, Any

# ── Canonical family → feature name prefixes / exact names ───────────────────

FAMILY_FEATURE_PREFIXES: dict[str, tuple[str, ...]] = {
    "mark_price": ("mark_price", "last_price", "index_price"),
    "candles": ("open", "high", "low", "close", "num_trades"),
    "volume": ("volume", "quote_volume"),
    "atr": ("atr", "volatility", "volatility_pct"),
    "orderbook": ("ob_best_bid", "ob_best_ask", "ob_mid_price", "ob_spread_bps", "ob_imbalance"),
    "oi_funding": ("funding_rate", "open_interest", "oi_change_pct"),
    "long_short_ratio": ("long_short_ratio", "long_account_ratio", "short_account_ratio"),
    "microstructure": (
        "taker_buy_ratio", "taker_sell_ratio", "order_flow_imbalance",
        "tape_imbalance", "coinapi_wsds_tape_imbalance",
    ),
    "liquidation_clusters": (
        "nearest_liquidation_level_above", "nearest_liquidation_level_below",
        "liquidation_cascade_risk", "liquidation_pressure_direction",
        "liquidation_count_5m", "liquidity_zone_above", "liquidity_zone_below",
        "distance_to_liquidity_zone_bps",
    ),
    "sweep_spoof_wall": (
        "depth_vs_tape_divergence", "sweep_up_detected", "sweep_down_detected",
        "spoof_wall_detected", "liquidity_hunt_detected", "stop_run_risk",
        "toxic_flow_detected",
    ),
    "paper_context": (
        "paper_position_present", "paper_unrealized_bps",
        "risk_recent_allow_rate", "orchestrator_recent_allow_rate",
    ),
    "public_intel": (
        "nansen_score", "lunarcrush_score", "aicoin_score", "surf_score",
    ),
}

# Critical families — ALL must be present for high-precision paper fills.
CRITICAL_FEATURE_FAMILIES: tuple[str, ...] = (
    "mark_price",
    "candles",
    "volume",
    "atr",
    "orderbook",
    "oi_funding",
    "long_short_ratio",
    "microstructure",
    "liquidation_clusters",
    "sweep_spoof_wall",
    "paper_context",
    "public_intel",
)

# Hard-critical families — missing these blocks entry even without high-precision mode.
HARD_CRITICAL_FAMILIES: tuple[str, ...] = (
    "mark_price",
    "candles",
    "volume",
    "atr",
    "orderbook",
    "oi_funding",
    "long_short_ratio",
)


def classify_feature_families(
    *,
    feature_names: list[str] | None,
    missing_feature_names: list[str] | None = None,
) -> tuple[set[str], set[str]]:
    """Return (present_families, missing_families) from raw feature lists.

    Normal mode (feature_names populated):
        A family is PRESENT when at least one canonical member is in feature_names
        AND is NOT in missing_feature_names.

    Inference mode (feature_names is None/empty, missing_feature_names is provided):
        A family is MISSING_CONFIRMED when ALL its canonical members appear in
        missing_feature_names.  Otherwise it is PRESENT_INFERRED (at least one
        member is plausibly available).  This is conservative: a partially-missing
        family still counts as present so only fully-absent families block the gate.
    """
    names_set = set(feature_names or [])
    missing_set = set(missing_feature_names or [])

    present: set[str] = set()
    missing: set[str] = set()

    if names_set:
        # Normal mode
        actually_present = names_set - missing_set
        for family, members in FAMILY_FEATURE_PREFIXES.items():
            if any(m in actually_present for m in members):
                present.add(family)
            else:
                missing.add(family)
    else:
        # Inference mode — feature_names unavailable; use missing_feature_names.
        # Family is MISSING_CONFIRMED only when ALL known members are absent.
        for family, members in FAMILY_FEATURE_PREFIXES.items():
            all_missing = all(m in missing_set for m in members)
            if all_missing:
                missing.add(family)
            else:
                present.add(family)

    return present, missing


def classify_families_from_prediction(prediction: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """Convenience wrapper that reads feature_names and missing_feature_names
    directly from a trainer prediction dict.
    """
    feature_names = list(prediction.get("feature_names") or [])
    missing_feature_names = list(prediction.get("missing_feature_names") or [])
    return classify_feature_families(
        feature_names=feature_names,
        missing_feature_names=missing_feature_names,
    )


def feature_family_coverage_summary(
    present_families: set[str],
    missing_families: set[str],
    *,
    classification_mode: str = "normal",
) -> dict[str, Any]:
    """Return a structured coverage summary for audit logs and gate diagnostics.

    classification_mode is 'normal' when feature_names was available, or
    'inference_missing_names_only' when only missing_feature_names was used.
    """
    critical_present = [f for f in CRITICAL_FEATURE_FAMILIES if f in present_families]
    critical_missing = [f for f in CRITICAL_FEATURE_FAMILIES if f in missing_families]
    hard_critical_missing = [f for f in HARD_CRITICAL_FAMILIES if f in missing_families]
    return {
        "classification_mode": classification_mode,
        "total_families_checked": len(FAMILY_FEATURE_PREFIXES),
        "families_present": sorted(present_families),
        "families_missing": sorted(missing_families),
        "critical_families_present": critical_present,
        "critical_families_missing": critical_missing,
        "hard_critical_families_missing": hard_critical_missing,
        "critical_coverage_pct": round(
            100.0 * len(critical_present) / max(len(CRITICAL_FEATURE_FAMILIES), 1), 1
        ),
        "all_critical_present": len(critical_missing) == 0,
        "hard_critical_gate_pass": len(hard_critical_missing) == 0,
    }
