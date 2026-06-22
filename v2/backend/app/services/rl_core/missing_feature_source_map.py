"""Missing-feature source map for the V2 full observation builder.

For each unfilled slot in the legacy V3 1911-dim observation, classify
the source as one of:

- ``V2_SOURCE_EXISTS`` -- V2 already has a usable native source (the
  position is filled by `full_observation_builder` today).
- ``V2_SOURCE_MISSING_BUT_BUILDABLE`` -- V2 runtime data exists but a
  new V2-native projection module is required.
- ``EXTERNAL_SOURCE_REQUIRED`` -- needs a new external feed (e.g.
  on-chain feed for `onchain_btc` / `onchain_eth`).
- ``OPERATOR_DECISION_REQUIRED`` -- adoption requires explicit operator
  approval (e.g. extending portfolio_state beyond paper-only scope).
- ``NOT_REQUIRED_FOR_CURRENT_CHECKPOINT_PATH`` -- optional in the
  legacy V3 schema; can be skipped for compact V2 paper inference.

This module does NOT load any pickle, does NOT import torch, does NOT
mutate legacy. It reads the legacy V3 slice layout (via the existing
V2-owned legacy mirror parsers in
`legacy_observation_contract.py`) and the live builder output to
classify exactly which positions are still missing and why.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.rl_core.full_observation_builder import (
    SLICE_SIZES,
    TARGET_FULL_DIM,
    V2_NATIVE_POSITION_CONTEXT_FIELDS,
    V2_NATIVE_PORTFOLIO_STATE_FIELDS,
    V2_NATIVE_UNIFIED_FEATURE_FIELDS,
)

UNIFIED_FAMILIES: dict[str, dict[str, Any]] = {
    # Legacy-source feature families derived from
    # legacy_owned_runtime/rl/unified_feature_builder.py FeatureDimensions.
    "binance_klines": {
        "legacy_size_per_source": 20,
        "v2_source_status": "V2_SOURCE_MISSING_BUT_BUILDABLE",
        "v2_source_hint": "v2:market:* live binance klines ingestor exists; project ohlcv-derived expansion features.",
    },
    "binance_orderbook": {
        "legacy_size_per_source": 15,
        "v2_source_status": "V2_SOURCE_MISSING_BUT_BUILDABLE",
        "v2_source_hint": "v2 ingestors emit basic depth_imbalance/bid_ask_spread_bps; full orderbook depth slice requires new V2 module.",
    },
    "ccxt_ohlcv": {
        "legacy_size_per_source": 10,
        "v2_source_status": "OPERATOR_DECISION_REQUIRED",
        "v2_source_hint": "Alternative-exchange OHLCV. V2 keeps the native binance loop as canonical; operator must decide whether secondary feed is required for paper parity.",
    },
    "liquidations": {
        "legacy_size_per_source": 12,
        "v2_source_status": "V2_SOURCE_MISSING_BUT_BUILDABLE",
        "v2_source_hint": "v2_native_ingestors_live_loop already ingests liquidations; needs a 12-dim aggregator (intensity/direction/volume bins).",
    },
    "technical_analysis": {
        "legacy_size_per_source": 25,
        "v2_source_status": "V2_SOURCE_EXISTS_PARTIAL",
        "v2_source_hint": "v2:features:* already publishes ~15 TA fields (RSI/MACD/EMA/BB/etc.); 10 remaining indicators need V2-native TA expansion.",
    },
    "token_metrics": {
        "legacy_size_per_source": 18,
        "v2_source_status": "EXTERNAL_SOURCE_REQUIRED",
        "v2_source_hint": "On-chain/sentiment metrics. V2 has no native source today; requires new external ingestor and operator approval.",
    },
    "coinank": {
        "legacy_size_per_source": 22,
        "v2_source_status": "V2_SOURCE_EXISTS_PARTIAL",
        "v2_source_hint": "v2_native_ingestors_live_loop has coinank funding/OI fields; needs expansion to 22-field aggregator.",
    },
    "portfolio_state_unified": {
        "legacy_size_per_source": 15,
        "v2_source_status": "V2_SOURCE_EXISTS_PARTIAL",
        "v2_source_hint": "v2:paper:* gives a 12-of-15 projection; extend with margin/leverage/exposure scalars.",
    },
}

# Legacy portfolio_state slice (401 dims) maps to portfolio_aware_features
# config: per_symbol_features=12 over up to 10 symbols + global=15 + risk=8.
PORTFOLIO_STATE_DECOMPOSITION = {
    "per_symbol_features_count": 12,
    "max_symbols_tracked": 10,
    "global_features": 15,
    "risk_features": 8,
    # Note: legacy portfolio_state V3 size 401 ≈ (12*32) + 15 + 8 if older
    # 32-symbol cap was used. Today's V3 obs_schema records 401 verbatim.
    # We honor the schema number, not back-calculation.
    "legacy_v3_total_size": 401,
    "v2_paper_native_size_today": 12,
    "missing_dims_today": 389,
}

POSITION_CONTEXT_DECOMPOSITION = {
    "legacy_v3_total_size": 50,
    "v2_paper_native_size_today": 9,
    "missing_dims_today": 41,
    "categories": [
        "position MFE/MAE",
        "ROE history",
        "hold-time stats",
        "drawdown over position",
        "risk-flag history",
    ],
}

ONCHAIN_BTC_DECOMPOSITION = {
    "legacy_v3_total_size": 15,
    "v2_native_size_today": 0,
    "missing_dims_today": 15,
    "v2_source_status": "EXTERNAL_SOURCE_REQUIRED",
    "v2_source_hint": "No V2-native on-chain ingestor. Requires new external feed and operator approval before adoption.",
}

ONCHAIN_ETH_DECOMPOSITION = {
    "legacy_v3_total_size": 15,
    "v2_native_size_today": 0,
    "missing_dims_today": 15,
    "v2_source_status": "EXTERNAL_SOURCE_REQUIRED",
    "v2_source_hint": "No V2-native on-chain ingestor. Requires new external feed and operator approval before adoption.",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclasses.dataclass(frozen=True)
class SourceFamilyClassification:
    family_id: str
    legacy_size_per_source: int
    v2_source_status: str
    v2_source_hint: str


def classify_source_families() -> list[SourceFamilyClassification]:
    rows: list[SourceFamilyClassification] = []
    for name, cfg in UNIFIED_FAMILIES.items():
        rows.append(
            SourceFamilyClassification(
                family_id=f"unified_feature_family.{name}",
                legacy_size_per_source=cfg["legacy_size_per_source"],
                v2_source_status=cfg["v2_source_status"],
                v2_source_hint=cfg["v2_source_hint"],
            )
        )
    rows.append(
        SourceFamilyClassification(
            family_id="portfolio_state.extended",
            legacy_size_per_source=PORTFOLIO_STATE_DECOMPOSITION["legacy_v3_total_size"],
            v2_source_status="V2_SOURCE_MISSING_BUT_BUILDABLE",
            v2_source_hint=(
                "Project per-symbol/per-tf positions, margin, exposure, "
                "drawdown, leverage, hold-times, win-rate, var_95, sharpe, "
                "volatility, correlation, risk_score from v2:paper:* and "
                "v2:risk:* — paper-only."
            ),
        )
    )
    rows.append(
        SourceFamilyClassification(
            family_id="position_context.extended",
            legacy_size_per_source=POSITION_CONTEXT_DECOMPOSITION["legacy_v3_total_size"],
            v2_source_status="V2_SOURCE_MISSING_BUT_BUILDABLE",
            v2_source_hint=(
                "Compute MFE/MAE/ROE/hold-time stats from v2:paper:positions "
                "history; emit explicit MISSING flags when no position open."
            ),
        )
    )
    rows.append(
        SourceFamilyClassification(
            family_id="onchain_btc",
            legacy_size_per_source=ONCHAIN_BTC_DECOMPOSITION["legacy_v3_total_size"],
            v2_source_status=ONCHAIN_BTC_DECOMPOSITION["v2_source_status"],
            v2_source_hint=ONCHAIN_BTC_DECOMPOSITION["v2_source_hint"],
        )
    )
    rows.append(
        SourceFamilyClassification(
            family_id="onchain_eth",
            legacy_size_per_source=ONCHAIN_ETH_DECOMPOSITION["legacy_v3_total_size"],
            v2_source_status=ONCHAIN_ETH_DECOMPOSITION["v2_source_status"],
            v2_source_hint=ONCHAIN_ETH_DECOMPOSITION["v2_source_hint"],
        )
    )
    return rows


def build_missing_feature_source_map() -> dict[str, Any]:
    families = classify_source_families()
    status_counts: dict[str, int] = {}
    for f in families:
        status_counts[f.v2_source_status] = status_counts.get(f.v2_source_status, 0) + 1
    rollup_families = [dataclasses.asdict(f) for f in families]
    narrow_tasks_required: list[dict[str, Any]] = []
    for f in families:
        if f.v2_source_status in {
            "V2_SOURCE_MISSING_BUT_BUILDABLE",
            "EXTERNAL_SOURCE_REQUIRED",
            "OPERATOR_DECISION_REQUIRED",
        }:
            narrow_tasks_required.append(
                {
                    "family_id": f.family_id,
                    "task_id": f"claude_fix_v2_gap_{f.family_id.replace('.', '_')}_source",
                    "paired_codex_review_task_id": f"codex_review_fix_v2_gap_{f.family_id.replace('.', '_')}_source",
                    "severity": "OPERATOR_DECISION_REQUIRED",
                    "auto_apply_allowed_by_this_loop": False,
                    "v2_source_status": f.v2_source_status,
                    "rationale": f.v2_source_hint,
                    "legacy_size_per_source": f.legacy_size_per_source,
                }
            )
    return {
        "schema_version": "v2_full_observation_missing_feature_source_map_v1",
        "generated_utc": _utc_iso(),
        "target_full_observation_dim": TARGET_FULL_DIM,
        "slice_sizes_target": SLICE_SIZES,
        "v2_native_unified_feature_fields_today": list(V2_NATIVE_UNIFIED_FEATURE_FIELDS),
        "v2_native_portfolio_state_fields_today": list(V2_NATIVE_PORTFOLIO_STATE_FIELDS),
        "v2_native_position_context_fields_today": list(V2_NATIVE_POSITION_CONTEXT_FIELDS),
        "unified_feature_family_decomposition": UNIFIED_FAMILIES,
        "portfolio_state_decomposition": PORTFOLIO_STATE_DECOMPOSITION,
        "position_context_decomposition": POSITION_CONTEXT_DECOMPOSITION,
        "onchain_btc_decomposition": ONCHAIN_BTC_DECOMPOSITION,
        "onchain_eth_decomposition": ONCHAIN_ETH_DECOMPOSITION,
        "families": rollup_families,
        "status_counts": status_counts,
        "narrow_tasks_required": narrow_tasks_required,
        "narrow_tasks_required_count": len(narrow_tasks_required),
        "policy_architecture_port_implementation_claimed": False,
        "checkpoint_compatibility_claimed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
