"""Feature Intelligence service.

Native V2, paper/shadow only. Computes:

- Microstructure features (bid/ask spread, depth imbalance, micro price,
  realized volatility, toxicity proxy).
- Feature freshness flag (FRESH / STALE / MISSING).
- A simple regime classifier (TRENDING / RANGING / VOLATILE / UNCERTAIN)
  derived from realized volatility, trend strength, and orderbook imbalance.

Legacy behavior sources (read-only, in v2/legacy_preserved/full_runtime_closure/):

- rl/microstructure_proactive.py
    sha256=92946a87ebf60c6f6ae271da67b5ca9ab2d867ddd860df52b45c7d1bb9dfe43d
    size=65862
- rl/toxicity_shield.py
    sha256=e00f098be80a682d41e5c98b34bf3d98392eb84db57a675ea49a15fe3e924c46
    size=6227
- rl/unified_feature_builder.py
    sha256=2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5
    size=29925
- trading/market_regime_detector.py
    sha256=714511302a2cd2826f2c7a6763db5001c2d0abac0030ff10756d716934ac5d87
    size=36243
- feature_pipeline.py
    sha256=<not_in_manifest_search_required>
    size=~1437_lines

This service is NOT a full port of those modules. It implements V2-native
core invariants and a paper-acceptable subset of microstructure + regime
classification. The remaining behaviors are MISSING_IN_V2 per the migration
completion contract.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

FEATURE_INTELLIGENCE_SCHEMA_VERSION = "1.0.0"

LIVE_GATE_STATUS = "blocked_human_only"

LEGACY_SOURCES = {
    "rl/microstructure_proactive.py": {
        "sha256": "92946a87ebf60c6f6ae271da67b5ca9ab2d867ddd860df52b45c7d1bb9dfe43d",
        "size_bytes": 65862,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/rl/microstructure_proactive.py",
    },
    "rl/toxicity_shield.py": {
        "sha256": "e00f098be80a682d41e5c98b34bf3d98392eb84db57a675ea49a15fe3e924c46",
        "size_bytes": 6227,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/rl/toxicity_shield.py",
    },
    "rl/unified_feature_builder.py": {
        "sha256": "2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5",
        "size_bytes": 29925,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/rl/unified_feature_builder.py",
    },
    "trading/market_regime_detector.py": {
        "sha256": "714511302a2cd2826f2c7a6763db5001c2d0abac0030ff10756d716934ac5d87",
        "size_bytes": 36243,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/trading/market_regime_detector.py",
    },
}


class RegimeLabel(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class FeatureSnapshotIn:
    """Input snapshot the service computes against. All fields are optional.

    Missing fields produce MISSING_EVIDENCE flags rather than fabricated values.
    """

    symbol: str
    timeframe: str
    generated_utc: str
    bid_price: float | None = None
    ask_price: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_trade_price: float | None = None
    recent_close_prices: tuple[float, ...] = field(default_factory=tuple)
    recent_high_low_ranges: tuple[float, ...] = field(default_factory=tuple)
    funding_rate: float | None = None
    open_interest_change_pct: float | None = None


@dataclass(frozen=True)
class MicrostructureFeatures:
    bid_ask_spread_bps: float | None
    depth_imbalance: float | None
    micro_price: float | None
    realized_volatility_pct: float | None
    toxicity_proxy: float | None
    missing_inputs: tuple[str, ...]


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def compute_microstructure(snap: FeatureSnapshotIn) -> MicrostructureFeatures:
    """Compute paper-only microstructure features.

    Returns explicit MISSING_INPUT markers when required inputs are absent
    rather than silently zero-filling.
    """
    missing: list[str] = []

    bid = _safe_float(snap.bid_price)
    ask = _safe_float(snap.ask_price)
    bsize = _safe_float(snap.bid_size)
    asize = _safe_float(snap.ask_size)
    last = _safe_float(snap.last_trade_price)

    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        missing.append("bid_ask")
        spread_bps: float | None = None
        micro_price: float | None = None
    else:
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 10000.0
        if bsize is not None and asize is not None and (bsize + asize) > 0:
            micro_price = (bid * asize + ask * bsize) / (bsize + asize)
        else:
            micro_price = mid

    if bsize is None or asize is None or (bsize + asize) <= 0:
        missing.append("depth_sizes")
        depth_imbalance: float | None = None
    else:
        depth_imbalance = (bsize - asize) / (bsize + asize)

    closes = [c for c in (snap.recent_close_prices or []) if isinstance(c, (int, float)) and c > 0]
    if len(closes) < 3:
        missing.append("recent_closes")
        realized_vol_pct: float | None = None
    else:
        # log-returns realized volatility (percent).
        rets = []
        for i in range(1, len(closes)):
            try:
                rets.append(math.log(closes[i] / closes[i - 1]))
            except (ValueError, ZeroDivisionError):
                continue
        if len(rets) >= 2:
            stdev = statistics.pstdev(rets)
            realized_vol_pct = stdev * 100.0
        else:
            missing.append("returns_insufficient")
            realized_vol_pct = None

    # Toxicity proxy: combines spread + depth imbalance into a [0, 1] score.
    if spread_bps is None or depth_imbalance is None:
        missing.append("toxicity_inputs")
        toxicity_proxy: float | None = None
    else:
        # Normalize spread (cap at 50 bps) and abs-imbalance (cap at 1).
        spread_norm = min(spread_bps / 50.0, 1.0)
        imbalance_norm = min(abs(depth_imbalance), 1.0)
        toxicity_proxy = max(0.0, min(1.0, 0.5 * spread_norm + 0.5 * imbalance_norm))

    return MicrostructureFeatures(
        bid_ask_spread_bps=spread_bps,
        depth_imbalance=depth_imbalance,
        micro_price=micro_price,
        realized_volatility_pct=realized_vol_pct,
        toxicity_proxy=toxicity_proxy,
        missing_inputs=tuple(missing),
    )


def feature_freshness_flag(generated_utc: str | None, *, max_age_seconds: int = 120) -> str:
    """Return FRESH / STALE / MISSING for a payload timestamp."""
    if not generated_utc:
        return "MISSING"
    try:
        ts = dt.datetime.fromisoformat(generated_utc.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "MISSING"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()
    if age < 0:
        # clock skew — be conservative
        return "STALE"
    return "FRESH" if age <= max_age_seconds else "STALE"


def classify_regime(
    *,
    realized_volatility_pct: float | None,
    trend_strength_pct: float | None,
    depth_imbalance: float | None,
) -> RegimeLabel:
    """Classify regime from a small evidence triple.

    - VOLATILE if realized_volatility_pct exceeds 1.5 (pct).
    - TRENDING_UP if trend_strength_pct > 0.5 and not VOLATILE.
    - TRENDING_DOWN if trend_strength_pct < -0.5 and not VOLATILE.
    - RANGING if abs(trend_strength_pct) <= 0.5 and realized_volatility_pct
      is moderate.
    - UNCERTAIN if any input is None.
    """
    if realized_volatility_pct is None or trend_strength_pct is None:
        return RegimeLabel.UNCERTAIN
    if realized_volatility_pct > 1.5:
        return RegimeLabel.VOLATILE
    if trend_strength_pct > 0.5:
        return RegimeLabel.TRENDING_UP
    if trend_strength_pct < -0.5:
        return RegimeLabel.TRENDING_DOWN
    # additional ranging confirmation: depth_imbalance near 0
    if depth_imbalance is None or abs(depth_imbalance) < 0.3:
        return RegimeLabel.RANGING
    return RegimeLabel.UNCERTAIN


@dataclass
class FeatureIntelligenceService:
    """Native V2 paper-only feature intelligence service."""

    max_age_seconds: int = 120

    def compute(self, snap: FeatureSnapshotIn) -> dict[str, Any]:
        micro = compute_microstructure(snap)
        freshness = feature_freshness_flag(snap.generated_utc, max_age_seconds=self.max_age_seconds)
        # trend strength proxy: pct change from first to last close.
        closes = [c for c in (snap.recent_close_prices or []) if isinstance(c, (int, float)) and c > 0]
        if len(closes) >= 2 and closes[0] > 0:
            trend_strength_pct = ((closes[-1] - closes[0]) / closes[0]) * 100.0
        else:
            trend_strength_pct = None
        regime = classify_regime(
            realized_volatility_pct=micro.realized_volatility_pct,
            trend_strength_pct=trend_strength_pct,
            depth_imbalance=micro.depth_imbalance,
        )
        return {
            "schema_version": FEATURE_INTELLIGENCE_SCHEMA_VERSION,
            "symbol": snap.symbol,
            "timeframe": snap.timeframe,
            "generated_utc": snap.generated_utc,
            "freshness": freshness,
            "microstructure": asdict(micro),
            "trend_strength_pct": trend_strength_pct,
            "regime": regime.value,
            "missing_inputs": list(micro.missing_inputs),
        }

    def current_paper_only_status(self) -> dict[str, Any]:
        return {
            "worker_id": "v2_feature_intelligence",
            "schema_version": FEATURE_INTELLIGENCE_SCHEMA_VERSION,
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "scope": "PAPER_ONLY",
            "components_ported": [
                "microstructure_features_bid_ask_spread_depth_imbalance_micro_price",
                "realized_volatility_from_recent_closes",
                "toxicity_proxy_spread_and_imbalance",
                "feature_freshness_FRESH_STALE_MISSING",
                "regime_classifier_TRENDING_RANGING_VOLATILE_UNCERTAIN",
                "missing_inputs_explicit_labels",
            ],
            "components_missing": [
                "full_unified_feature_builder_2000_plus_features",
                "cross_timeframe_aggregations",
                "funding_oi_derived_features",
                "ingestor_layer_websocket_rest_native",
            ],
            "legacy_sha256_citations": LEGACY_SOURCES,
            "migration_classification": "PARTIALLY_MIGRATED",
            "contract_ref": "claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md",
        }
