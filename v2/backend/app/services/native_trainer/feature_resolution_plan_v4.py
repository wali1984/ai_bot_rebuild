"""Closed, audit-only resolution plan for the pinned 446-slot feature ABI.

This module is deliberately declarative.  It turns the configured source label
in :mod:`feature_source_registry_v4` into one exact key template, one source
schema identity, and zero or more ordered, feature-specific selector branches.
It does not read Redis, inspect a provider, resolve a value, publish a feature,
or authorize a consumer.

The current TensorBuilder has a final feature-name lookup across unrelated
payloads.  That behavior is intentionally absent here.  A slot with no
truthful, source-specific selector remains represented exactly once with an
explicit non-resolving reason.  In particular, retrospective liquidation
levels are not accepted under the old future-looking feature names.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final, NoReturn

from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
)

FEATURE_RESOLUTION_PLAN_V4_SCHEMA_VERSION: Final = "trainer_feature_resolution_plan_v4"
FEATURE_RESOLUTION_PLAN_V4_EVIDENCE_CLASSIFICATION: Final = (
    "AUDIT_ONLY_CODE_OWNED_SELECTOR_PLAN_UNWIRED"
)
FEATURE_RESOLUTION_PLAN_V4_DOWNSTREAM_STATUS: Final = (
    "NON_AUTHORITATIVE_CANNOT_GRANT_TENSOR_TRAINER_PREDICTION_PAPER_OR_LIVE_ELIGIBILITY"
)
FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT: Final = 446
FEATURE_RESOLUTION_PLAN_V4_SHA256: Final = (
    "99379f75c5e3412a6c734dcfa1ed7325cdb65146aa09d61f60db33be297354cb"
)
CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION: Final = "canonical_feature_source_record_v4"
SOURCE_TIMEFRAME_REQUEST: Final = "REQUEST_TIMEFRAME"

PLAN_RESOLVABLE: Final = "RESOLVABLE_EXACT_SOURCE_ONLY"
PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN: Final = (
    "UNRESOLVED_GENERIC_SOURCE_AGNOSTIC_FALLBACK_FORBIDDEN"
)
PLAN_UNRESOLVED_FUTURE_SEMANTICS: Final = (
    "UNRESOLVED_RETROSPECTIVE_LIQUIDATION_DATA_CANNOT_PROVE_FUTURE_SEMANTICS"
)
PLAN_UNRESOLVED_NO_PRODUCER: Final = "UNRESOLVED_NO_LEGITIMATE_CONFIGURED_PRODUCER"
PLAN_UNRESOLVED_AUTHENTICATED_WINDOW: Final = (
    "UNRESOLVED_AUTHENTICATED_EXACT_WINDOW_AGGREGATOR_REQUIRED"
)
PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION: Final = (
    "UNRESOLVED_REQUEST_TIMEFRAME_OVERWRITES_SHARED_PHYSICAL_SOURCE_KEY"
)

TRANSFORM_IDENTITY: Final = "FINITE_FLOAT32_IDENTITY_V1"
TRANSFORM_BOOL: Final = "EXACT_BOOLEAN_TO_FLOAT32_V1"
TRANSFORM_NONNEGATIVE_DIFFERENCE: Final = "NONNEGATIVE_DIFFERENCE_FLOAT32_V1"
TRANSFORM_RATIO: Final = "CAUSAL_RATIO_FLOAT32_V1"
TRANSFORM_COMPLEMENT_RATIO: Final = "CAUSAL_COMPLEMENT_RATIO_FLOAT32_V1"

NULL_POLICY: Final = "PRESERVE_NONE_STOP_BRANCH_SEARCH"
EMPTY_COLLECTION_POLICY: Final = "AUTHENTICATED_EXACT_EMPTY_WINDOW_RECEIPT_REQUIRED"
TYPED_NEGATIVE_POLICY: Final = "AUTHENTICATED_TYPED_NEGATIVE_RECEIPT_REQUIRED"

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@{}-]{0,511}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()


class FeatureResolutionPlanV4ValidationError(ValueError):
    """The code-owned plan no longer matches its pinned contract."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise FeatureResolutionPlanV4ValidationError(*reasons) from None


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("FEATURE_RESOLUTION_PLAN_V4_CANONICAL_ENCODING_FAILED")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class FeatureResolutionBranchPlanV4:
    """One ordered alias/transform branch within one exact source record."""

    branch_id: str
    selected_alias: str
    dependency_paths: tuple[tuple[str, ...], ...]
    transform_id: str
    transform_version: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_branch_plan(self)


@dataclass(frozen=True, slots=True)
class FeatureSlotResolutionPlanV4:
    """The only allowed resolution plan for one deployed model slot."""

    ordinal: int
    feature_name: str
    configured_source_label: str
    requirement_class: str
    source_key_template: str | None
    source_timeframe_template: str | None
    source_payload_schema_version: str | None
    plan_status: str
    unresolved_reason: str | None
    branches: tuple[FeatureResolutionBranchPlanV4, ...]
    requires_closed_candle: bool
    null_policy: str
    empty_collection_policy: str
    typed_negative_policy: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_RESOLUTION_PLAN_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_slot_plan(self)


@dataclass(frozen=True, slots=True)
class FeatureResolutionPlanSetV4:
    """Frozen 446-slot plan with all downstream authority fixed false."""

    schema_version: str
    evidence_classification: str
    downstream_status: str
    feature_source_registry_sha256: str
    slots: tuple[FeatureSlotResolutionPlanV4, ...]
    plan_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_RESOLUTION_PLAN_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_plan_set(self)

    @property
    def audit_only(self) -> bool:
        return True

    @property
    def runtime_wired(self) -> bool:
        return False

    @property
    def source_reads_performed(self) -> bool:
        return False

    @property
    def tensor_eligible(self) -> bool:
        return False

    @property
    def trainer_admission_authorized(self) -> bool:
        return False

    @property
    def prediction_authorized(self) -> bool:
        return False

    @property
    def paper_trading_authorized(self) -> bool:
        return False

    @property
    def live_execution_authorized(self) -> bool:
        return False


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _validate_branch_plan(branch: FeatureResolutionBranchPlanV4) -> None:
    if branch._construction_token is not _CONSTRUCTION_TOKEN:
        _fail("FEATURE_RESOLUTION_PLAN_V4_FACTORY_CONSTRUCTION_REQUIRED")
    if not _valid_label(branch.branch_id) or not _valid_label(branch.selected_alias):
        _fail("FEATURE_RESOLUTION_PLAN_V4_BRANCH_IDENTITY_INVALID")
    if (
        type(branch.dependency_paths) is not tuple
        or not branch.dependency_paths
        or len(branch.dependency_paths) > 16
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_DEPENDENCY_PATHS_INVALID")
    for path in branch.dependency_paths:
        if (
            type(path) is not tuple
            or not path
            or len(path) > 16
            or any(not _valid_label(part) or "*" in part for part in path)
        ):
            _fail("FEATURE_RESOLUTION_PLAN_V4_DEPENDENCY_PATH_INVALID")
    if not _valid_label(branch.transform_id) or branch.transform_version != "v1":
        _fail("FEATURE_RESOLUTION_PLAN_V4_TRANSFORM_INVALID")


def _branch(
    feature_name: str,
    alias: str,
    path: tuple[str, ...],
    *,
    transform_id: str = TRANSFORM_IDENTITY,
    dependencies: tuple[tuple[str, ...], ...] | None = None,
) -> FeatureResolutionBranchPlanV4:
    return FeatureResolutionBranchPlanV4(
        branch_id=f"{feature_name}@{alias}",
        selected_alias=alias,
        dependency_paths=dependencies or (path,),
        transform_id=transform_id,
        transform_version="v1",
        _construction_token=_CONSTRUCTION_TOKEN,
    )


# Exact source identities.  These are key declarations, not fallback prefixes;
# the resolver materializes exactly one key for a requested symbol/timeframe.
_SOURCE_FAMILIES: Final[dict[str, tuple[str, str]]] = {
    "v2:market:prices": ("v2:market:prices:{symbol}", "canonical_market_prices_payload_v4"),
    "v2:market:funding": ("v2:market:funding:{symbol}", "canonical_market_funding_payload_v4"),
    "v2:market:open_interest": (
        "v2:market:open_interest:{symbol}",
        "canonical_market_open_interest_payload_v4",
    ),
    "v2:market:open_interest_hist": (
        "v2:market:open_interest_hist:{symbol}:5m",
        "canonical_market_open_interest_history_payload_v4",
    ),
    "v2:market:long_short": (
        "v2:market:long_short:{symbol}",
        "canonical_market_long_short_payload_v4",
    ),
    "v2:market:ohlcv": (
        "v2:market:ohlcv_closed:binance:{symbol}:{timeframe}",
        "canonical_binance_closed_candle_payload_v4",
    ),
    "v2:market:orderbook": (
        "v2:market:orderbook:{symbol}",
        "canonical_market_orderbook_payload_v4",
    ),
    "v2:orderbook:features": (
        "v2:orderbook:features:binance:{symbol}",
        "canonical_binance_orderbook_features_payload_v4",
    ),
    "v2:features:latest": (
        "v2:features:latest:{symbol}:{timeframe}",
        "canonical_feature_snapshot_payload_v4",
    ),
    "v2:features:ta": (
        "v2:features:ta:{symbol}:{timeframe}",
        "canonical_ta_feature_payload_v4",
    ),
    "v2:features:ta_full": (
        "v2:features:ta_full:{symbol}:{timeframe}",
        "canonical_ta_full_feature_payload_v4",
    ),
    "v2:features:ta_full:1h": (
        "v2:features:ta_full:{symbol}:1h",
        "canonical_ta_full_feature_payload_v4",
    ),
    "v2:market:liquidation_levels": (
        "v2:market:liquidation_levels:{symbol}",
        "canonical_observed_liquidation_state_payload_v4",
    ),
    "v2:liquidations:levels": (
        "v2:liquidations:levels:{symbol}:{timeframe}",
        "canonical_observed_liquidation_levels_payload_v4",
    ),
    "v2:liquidations:events": (
        "v2:liquidations:events",
        "canonical_liquidation_event_window_payload_v4",
    ),
    "v2:market:liquidations:aggregate": (
        "v2:market:liquidations:aggregate:{symbol}",
        "canonical_observed_liquidation_aggregate_payload_v4",
    ),
    "v2:market:liquidity_zones": (
        "v2:market:liquidity_zones:{symbol}",
        "canonical_market_liquidity_zones_payload_v4",
    ),
    "v2:market:fvg": (
        "v2:market:fvg:{symbol}:{timeframe}",
        "canonical_market_fvg_payload_v4",
    ),
    "v2:market:structure": (
        "v2:market:structure:{symbol}:{timeframe}",
        "canonical_market_structure_payload_v4",
    ),
    "v2:market:sweep_risk": (
        "v2:market:sweep_risk:{symbol}:{timeframe}",
        "canonical_market_sweep_risk_payload_v4",
    ),
    "v2:market:vwap": (
        "v2:market:vwap:{symbol}:{timeframe}",
        "canonical_market_vwap_payload_v4",
    ),
    "v2:market:volume_profile": (
        "v2:market:volume_profile:{symbol}:{timeframe}",
        "canonical_market_volume_profile_payload_v4",
    ),
    "v2:market:cvd": (
        "v2:market:cvd:{symbol}:{timeframe}",
        "canonical_market_cvd_payload_v4",
    ),
    "v2:market:trade_tape_features": (
        "v2:market:trade_tape_features:{symbol}",
        "canonical_market_trade_tape_payload_v4",
    ),
    "v2:market:microstructure": (
        "v2:market:microstructure:{symbol}",
        "canonical_market_microstructure_payload_v4",
    ),
    "v2:microstructure:trust_score": (
        "v2:microstructure:trust_score:{symbol}:{timeframe}",
        "canonical_microstructure_trust_payload_v4",
    ),
    "v2:microstructure:feed_quality": (
        "v2:microstructure:feed_quality:binance:{symbol}",
        "canonical_microstructure_feed_quality_payload_v4",
    ),
    "v2:microstructure:adversarial_features": (
        "v2:microstructure:adversarial_features:binance:{symbol}",
        "canonical_microstructure_adversarial_payload_v4",
    ),
    "v2:microstructure:trade_tape_confirmation": (
        "v2:microstructure:trade_tape_confirmation:{symbol}",
        "canonical_microstructure_trade_tape_confirmation_payload_v4",
    ),
    "v2:microstructure:cross_venue_confirmation": (
        "v2:microstructure:cross_venue_confirmation:{symbol}",
        "canonical_microstructure_cross_venue_payload_v4",
    ),
    "v2:microstructure:sweep_risk": (
        "v2:microstructure:sweep_risk:{symbol}:{timeframe}",
        "canonical_microstructure_sweep_risk_payload_v4",
    ),
    "v2:microstructure:cascade_context": (
        "v2:microstructure:cascade_context:{symbol}:{timeframe}",
        "canonical_microstructure_cascade_context_payload_v4",
    ),
    "v2:altdata:symbol_score": (
        "v2:altdata:symbol_score:{symbol}",
        "canonical_altdata_symbol_score_payload_v4",
    ),
    "v2:altdata:public_intel": (
        "v2:altdata:public_intel:symbol:{symbol}",
        "canonical_altdata_public_intel_payload_v4",
    ),
    "v2:altdata:whale_walls": (
        "v2:altdata:whale_walls:symbol:{symbol}",
        "canonical_altdata_whale_walls_payload_v4",
    ),
    "v2:features:moralis": (
        "v2:features:moralis:{symbol}:{timeframe}",
        "canonical_moralis_feature_bridge_payload_v4",
    ),
    "v2:altdata:confluence": (
        "v2:altdata:confluence:{symbol}:{timeframe}",
        "canonical_altdata_confluence_payload_v4",
    ),
    "v2:paper:positions": (
        "v2:paper:positions",
        "canonical_paper_position_window_payload_v4",
    ),
    "v2:risk:decisions": (
        "v2:risk:decisions",
        "canonical_risk_decision_window_payload_v4",
    ),
    "v2:orchestrator:decisions": (
        "v2:orchestrator:decisions",
        "canonical_orchestrator_decision_window_payload_v4",
    ),
}

# A physical source timeframe is not the same thing as the model/request
# timeframe.  Sources whose key contains ``{timeframe}`` are evaluated at the
# request timeframe.  These two families are explicitly fixed regardless of
# the model timeframe.  A request-derived family that incorrectly shares one
# unkeyed producer key is identified explicitly and remains unresolved.  Other
# sources without a timeframe-bearing key are timeless at this layer and use
# ``None`` rather than silently inheriting a request clock.
_FIXED_SOURCE_TIMEFRAMES: Final[dict[str, str]] = {
    "v2:market:open_interest_hist": "5m",
    "v2:features:ta_full:1h": "1h",
}
_REQUEST_BOUND_UNKEYED_SOURCE_LABELS: Final[frozenset[str]] = frozenset(
    {"v2:market:liquidity_zones"}
)


def _source_timeframe_template(source_label: str) -> str | None:
    fixed = _FIXED_SOURCE_TIMEFRAMES.get(source_label)
    if fixed is not None:
        return fixed
    if source_label in _REQUEST_BOUND_UNKEYED_SOURCE_LABELS:
        return SOURCE_TIMEFRAME_REQUEST
    key_template = _SOURCE_FAMILIES[source_label][0]
    return SOURCE_TIMEFRAME_REQUEST if "{timeframe}" in key_template else None


# These families are defined from completed-candle state.  Their shadow source
# record must therefore carry the exact underlying candle close and finality;
# temporal clocks alone cannot turn a partially formed candle into final data.
_CLOSED_CANDLE_SOURCE_LABELS: Final[frozenset[str]] = frozenset(
    {
        "v2:market:ohlcv",
        "v2:features:latest",
        "v2:features:ta",
        "v2:features:ta_full",
        "v2:features:ta_full:1h",
        "v2:market:liquidity_zones",
        "v2:market:fvg",
        "v2:market:structure",
        "v2:market:sweep_risk",
        "v2:market:vwap",
        "v2:market:volume_profile",
        "v2:market:cvd",
    }
)


# Exact names with an explicit pre-generic TensorBuilder route.  Membership in
# this tuple is a compile-time allowlist; it is never inferred from caller data.
_EXPLICIT_PRE_GENERIC_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "last_price",
        "mark_price",
        "index_price",
        "basis_pct",
        "price_last",
        "open",
        "high",
        "low",
        "close",
        "ohlcv_close",
        "volume",
        "ohlcv_volume",
        "quote_volume",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
        "taker_sell_base_vol",
        "taker_sell_quote_vol",
        "taker_buy_ratio",
        "taker_sell_ratio",
        "ob_best_bid",
        "ob_best_ask",
        "ob_mid_price",
        "bid_ask_mid",
        "best_bid_size",
        "best_ask_size",
        "ob_spread_bps",
        "spread_bps",
        "ob_imbalance",
        "orderbook_depth_usd",
        "depth_total_usd",
        "depth_usd",
        "depth_5_bid_usd",
        "depth_5_ask_usd",
        "depth_20_bid_usd",
        "depth_20_ask_usd",
        "depth_slope",
        "estimated_price_impact_bps",
        "update_age_ms",
        "sequence_gap_flag",
        "source_latency_ms",
        "microstructure_trust_score",
        "feed_latency_ms",
        "spread_instability",
        "depth_persistence",
        "cancel_pressure",
        "book_trade_divergence",
        "cross_venue_confirmation",
        "sweep_risk",
        "post_sweep_reversal_probability",
        "realized_slippage_error",
        "depth_vs_tape_divergence",
        "orderbook_spread_bps",
        "orderbook_depth_imbalance",
        "funding_rate",
        "open_interest",
        "oi_change_pct",
        "long_short_ratio",
        "long_account_ratio",
        "short_account_ratio",
        "open_interest_change_pct",
        "volatility",
        "volatility_pct",
        "RSI",
        "MACD",
        "MACD_signal",
        "MACD_hist",
        "ATR",
        "EMA_12",
        "EMA_26",
        "bollinger_upper",
        "bollinger_middle",
        "bollinger_lower",
        "bollinger_width_pct",
        "liquidation_count_5m",
        "liquidation_long_level",
        "liquidation_short_level",
        "nearest_liquidation_level_above",
        "nearest_liquidation_level_below",
        "distance_to_long_liq_bps",
        "distance_to_short_liq_bps",
        "liquidation_cluster_strength_long",
        "liquidation_cluster_strength_short",
        "liquidation_distance_pct",
        "liquidation_strength",
        "liquidation_cascade_risk",
        "liquidation_pressure_direction",
        "liquidation_sweep_target_long",
        "liquidation_sweep_target_short",
        "liquidation_sweep_target_long_distance_bps",
        "liquidation_sweep_target_short_distance_bps",
        "liquidation_zones_long_count",
        "liquidation_zones_short_count",
        "liquidation_count_1h",
        "liquidation_notional_1h",
        "liquidation_direction_bias_1h",
        "liquidity_zone_above",
        "liquidity_zone_below",
        "distance_to_liquidity_zone_bps",
        "bullish_fvg_present",
        "bearish_fvg_present",
        "fvg_size_bps",
        "distance_to_fvg_bps",
        "fvg_fill_percent",
        "fvg_age_candles",
        "fvg_retest_confirmed",
        "htf_fvg_alignment",
        "fvg_liquidity_confluence",
        "fvg_orderbook_trust_confluence",
        "fvg_trade_tape_confirmation",
        "fvg_expected_edge_after_cost",
        "bos_direction_code",
        "choch_direction_code",
        "order_block_strength",
        "breaker_block_active",
        "mitigation_block_active",
        "equal_highs_distance_bps",
        "equal_lows_distance_bps",
        "premium_discount_zone_code",
        "session_high_sweep",
        "session_low_sweep",
        "structure_trend_state_code",
        "nearest_liquidity_above",
        "nearest_liquidity_below",
        "distance_to_liquidity_above_bps",
        "distance_to_liquidity_below_bps",
        "liquidity_zone_strength",
        "sweep_risk_long_side",
        "sweep_risk_short_side",
        "fake_breakout_risk",
        "fake_breakdown_risk",
        "cascade_continuation_probability",
        "session_vwap",
        "anchored_vwap",
        "distance_to_vwap_bps",
        "vwap_slope",
        "volume_profile_poc",
        "high_volume_node_above",
        "high_volume_node_below",
        "low_volume_node_above",
        "low_volume_node_below",
        "cvd",
        "cvd_slope",
        "cvd_divergence",
        "trade_imbalance",
        "large_trade_cluster",
        "sweep_prints",
        "orderbook_wall_strength",
        "microstructure_liquidity_depth",
        "coinapi_wsds_tape_imbalance",
        "last_liq_bps_24h",
        "liquidation_is_stale",
        "liquidation_level_distance_bps",
        "microprice",
        "spread",
        "micro_volatility",
        "toxicity_proxy",
        "tape_imbalance",
        "order_flow_imbalance",
        "paper_position_present",
        "paper_unrealized_bps",
        "risk_recent_allow_rate",
        "orchestrator_recent_allow_rate",
        "altdata_symbol_score",
        "provider_availability_score",
        "altdata_freshness_score",
        "coingecko_discovery_score",
        "coingecko_liquidity_score",
        "coingecko_momentum_score",
        "surf_market_price_signal_score",
        "coinglass_derivatives_score",
        "public_intel_score",
        "defillama_liquidity_score",
        "defillama_tvl_momentum_score",
        "news_attention_score",
        "news_sentiment_score",
        "fear_greed_score",
        "btc_mempool_pressure_score",
        "whale_wall_score",
        "whale_bid_pressure_score",
        "whale_ask_pressure_score",
        "whale_wall_imbalance_score",
        "whale_wall_count_score",
        "whale_wall_event_count",
        "whale_bid_wall_notional_usd",
        "whale_ask_wall_notional_usd",
        "whale_total_wall_notional_usd",
        "nearest_bid_wall_distance_bps",
        "nearest_ask_wall_distance_bps",
        "coingecko_score",
        "surf_score",
        "defillama_score",
        "fear_greed_context",
        "mempool_context",
    }
)

_FUTURE_SEMANTICS_ORDINALS: Final[frozenset[int]] = frozenset(
    {*range(68, 78), *range(136, 142), 165}
)
_NO_LEGITIMATE_PRODUCER_ORDINALS: Final[frozenset[int]] = frozenset({131, 133})
_PHYSICAL_TIMEFRAME_COLLISION_ORDINALS: Final[frozenset[int]] = frozenset(
    {80, 81, 82, 106, 107, 108, 109, 110}
)
_AUTHENTICATED_WINDOW_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "last_liq_bps_24h",
        "liquidation_count_5m",
        "paper_position_present",
        "paper_unrealized_bps",
        "risk_recent_allow_rate",
        "orchestrator_recent_allow_rate",
    }
)

_BOOL_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "bullish_fvg_present",
        "bearish_fvg_present",
        "fvg_retest_confirmed",
        "htf_fvg_alignment",
        "fvg_liquidity_confluence",
        "breaker_block_active",
        "mitigation_block_active",
        "session_high_sweep",
        "session_low_sweep",
        "sequence_gap_flag",
    }
)

_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "last_price": ("ticker_24hr.lastPrice", "price", "last", "last_price"),
    "price_last": ("ticker_24hr.lastPrice", "price", "last", "last_price"),
    "mark_price": ("funding.markPrice", "mark_price", "markPrice"),
    "index_price": ("funding.indexPrice", "index_price", "indexPrice"),
    "basis_pct": ("basis_pct", "funding.basis_pct"),
    "funding_rate": ("funding_rate", "rate", "fundingRate", "lastFundingRate"),
    "open_interest": ("open_interest", "oi", "openInterest", "sumOpenInterest"),
    "oi_change_pct": ("change_pct", "oi_change_pct"),
    "open_interest_change_pct": ("change_pct", "oi_change_pct"),
    "long_short_ratio": ("long_short_ratio", "longShortRatio"),
    "long_account_ratio": ("long_account_ratio", "longAccount"),
    "short_account_ratio": ("short_account_ratio", "shortAccount"),
    "estimated_price_impact_bps": ("estimated_price_impact_bps", "price_impact_bps"),
    "microprice": ("microprice", "micro_price"),
    "spread": ("spread", "spread_bps"),
    "liquidation_is_stale": ("is_stale", "liquidation_is_stale"),
    "public_intel_score": ("score", "public_intel_score"),
    "coingecko_score": ("coingecko_score", "coingecko_discovery_score"),
    "surf_score": ("surf_score", "surf_market_price_signal_score"),
    "defillama_score": ("defillama_score", "defillama_liquidity_score"),
    "fear_greed_context": ("fear_greed_context", "fear_greed_score"),
    "mempool_context": ("mempool_context", "btc_mempool_pressure_score"),
}

_TA_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "RSI": ("RSI", "rsi_14", "ta_RSI_14", "ta_RSI"),
    "MACD": ("MACD", "macd", "ta_MACD_12_26_9_macd", "ta_MACD_macd"),
    "MACD_signal": ("MACD_signal", "macd_signal", "ta_MACD_12_26_9_signal", "ta_MACD_macdsignal"),
    "MACD_hist": ("MACD_hist", "macd_hist", "ta_MACD_12_26_9_hist", "ta_MACD_macdhist"),
    "ATR": ("ATR", "atr_14", "ta_ATR_14", "ta_ATR"),
    "EMA_12": ("EMA_12", "ema_12", "ta_EMA_12"),
    "EMA_26": ("EMA_26", "ema_26", "ta_EMA_26"),
    "bollinger_upper": ("bollinger_upper", "bb_upper", "ta_BBANDS_20_upper", "ta_BBANDS_upperband"),
    "bollinger_middle": (
        "bollinger_middle",
        "bb_middle",
        "ta_BBANDS_20_middle",
        "ta_BBANDS_middleband",
    ),
    "bollinger_lower": ("bollinger_lower", "bb_lower", "ta_BBANDS_20_lower", "ta_BBANDS_lowerband"),
    "bollinger_width_pct": ("bollinger_width_pct", "bb_width_pct", "bb_width"),
}

_TA_FULL_SIMPLE_ALIASES: Final[dict[str, str]] = {
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
}

_TA_MULTI_OUTPUT_BASES: Final[tuple[tuple[str, str], ...]] = (
    ("aroon_", "AROON_"),
    ("bbands_", "BBANDS_"),
    ("ht_phasor_", "HT_PHASOR_"),
    ("ht_sine_", "HT_SINE_"),
    ("macdext_", "MACDEXT_"),
    ("macdfix_", "MACDFIX_"),
    ("mama_", "MAMA_"),
    ("stochf_", "STOCHF_"),
    ("stochrsi_", "STOCHRSI_"),
    ("stoch_", "STOCH_"),
)

_HTF1H_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "htf1h_taf_rsi": ("rsi_14", "ta_RSI"),
    "htf1h_taf_adx": ("ta_ADX",),
    "htf1h_taf_macd_hist": ("macd_hist", "ta_MACD_macdhist"),
    "htf1h_taf_atr": ("atr_14", "ta_ATR"),
    "htf1h_taf_mfi": ("ta_MFI",),
    "htf1h_taf_willr": ("ta_WILLR",),
    "htf1h_taf_natr": ("ta_NATR",),
    "htf1h_taf_cci": ("ta_CCI",),
}

_CASCADE_ALIASES: Final[dict[str, str]] = {
    "cascade_risk_score": "cascade_risk_score",
    "cascade_event_component": "cascade_event_component",
    "cascade_level_proximity_component": "liquidation_level_proximity_component",
    "fast_squeeze_probability": "fast_squeeze_squeeze_probability",
    "fast_squeeze_trap_score": "fast_squeeze_market_maker_trap_score",
    "cross_asset_lead_component": "cross_asset_component",
}

_MICRO_TRUST_ALIASES: Final[dict[str, str]] = {
    "micro_cancel_pressure_score": "book_cancel_pressure_score",
    "micro_depth_persistence_score": "book_depth_persistence_score",
    "micro_book_trade_divergence": "book_trade_divergence",
    "micro_book_sequence_gap": "book_sequence_gap",
}


def _ta_full_alias(feature_name: str) -> str | None:
    simple = _TA_FULL_SIMPLE_ALIASES.get(feature_name)
    if simple is not None:
        return simple
    prefix = "taf_ta_"
    if not feature_name.startswith(prefix):
        return None
    suffix = feature_name[len(prefix) :]
    if suffix.endswith("_integer"):
        return f"ta_{suffix[:-len('_integer')].upper()}_integer"
    for raw_prefix, rendered_prefix in _TA_MULTI_OUTPUT_BASES:
        if suffix.startswith(raw_prefix):
            return f"ta_{rendered_prefix}{suffix[len(raw_prefix):]}"
    return f"ta_{suffix.upper()}"


def _path_prefix(source_label: str) -> tuple[str, ...]:
    if source_label == "v2:features:latest":
        return ("features",)
    if source_label in {"v2:features:ta", "v2:features:ta_full", "v2:features:ta_full:1h"}:
        return ("indicators",)
    if source_label in {"v2:features:moralis", "v2:altdata:confluence"}:
        return ("features",)
    return ()


def _field_path(source_label: str, alias: str) -> tuple[str, ...]:
    return _path_prefix(source_label) + tuple(alias.split("."))


def _custom_ohlcv_branches(feature_name: str) -> tuple[FeatureResolutionBranchPlanV4, ...] | None:
    root = {
        "volume": ("volume",),
        "quote": ("quote_volume",),
        "buy_base": ("taker_buy_base_vol",),
        "buy_quote": ("taker_buy_quote_vol",),
    }
    if feature_name == "taker_sell_base_vol":
        return (
            _branch(
                feature_name,
                "derived.volume-minus-taker_buy_base_vol",
                root["volume"],
                transform_id=TRANSFORM_NONNEGATIVE_DIFFERENCE,
                dependencies=(root["volume"], root["buy_base"]),
            ),
        )
    if feature_name == "taker_sell_quote_vol":
        return (
            _branch(
                feature_name,
                "derived.quote_volume-minus-taker_buy_quote_vol",
                root["quote"],
                transform_id=TRANSFORM_NONNEGATIVE_DIFFERENCE,
                dependencies=(root["quote"], root["buy_quote"]),
            ),
        )
    if feature_name == "taker_buy_ratio":
        return (
            _branch(
                feature_name,
                "derived.taker_buy_base_vol-over-volume",
                root["buy_base"],
                transform_id=TRANSFORM_RATIO,
                dependencies=(root["buy_base"], root["volume"]),
            ),
        )
    if feature_name == "taker_sell_ratio":
        return (
            _branch(
                feature_name,
                "derived.one-minus-taker_buy_base_vol-over-volume",
                root["buy_base"],
                transform_id=TRANSFORM_COMPLEMENT_RATIO,
                dependencies=(root["buy_base"], root["volume"]),
            ),
        )
    return None


def _branches_for_slot(
    ordinal: int, feature_name: str, source_label: str
) -> tuple[tuple[FeatureResolutionBranchPlanV4, ...], str, str | None]:
    if ordinal in _FUTURE_SEMANTICS_ORDINALS:
        return (), PLAN_UNRESOLVED_FUTURE_SEMANTICS, PLAN_UNRESOLVED_FUTURE_SEMANTICS
    if ordinal in _NO_LEGITIMATE_PRODUCER_ORDINALS:
        return (), PLAN_UNRESOLVED_NO_PRODUCER, PLAN_UNRESOLVED_NO_PRODUCER
    if ordinal in _PHYSICAL_TIMEFRAME_COLLISION_ORDINALS:
        return (
            (),
            PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION,
            PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION,
        )
    if feature_name in _AUTHENTICATED_WINDOW_FEATURES:
        return (), PLAN_UNRESOLVED_AUTHENTICATED_WINDOW, PLAN_UNRESOLVED_AUTHENTICATED_WINDOW

    ohlcv = _custom_ohlcv_branches(feature_name)
    if ohlcv is not None:
        return ohlcv, PLAN_RESOLVABLE, None

    aliases: tuple[str, ...] | None = None
    if feature_name in _EXPLICIT_PRE_GENERIC_FEATURES:
        aliases = _TA_ALIASES.get(feature_name) or _ALIASES.get(feature_name) or (feature_name,)
    elif source_label == "v2:features:ta_full":
        ta_alias = _ta_full_alias(feature_name)
        aliases = None if ta_alias is None else (ta_alias,)
    elif source_label == "v2:features:ta_full:1h":
        aliases = _HTF1H_ALIASES.get(feature_name)
    elif source_label == "v2:microstructure:cascade_context":
        cascade_alias = _CASCADE_ALIASES.get(feature_name)
        aliases = None if cascade_alias is None else (cascade_alias,)
    elif source_label == "v2:microstructure:trust_score" and feature_name in _MICRO_TRUST_ALIASES:
        aliases = (_MICRO_TRUST_ALIASES[feature_name],)
    elif source_label in {"v2:features:moralis", "v2:altdata:confluence"}:
        aliases = (feature_name,)

    if aliases is None:
        return (
            (),
            PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN,
            PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN,
        )
    transform = TRANSFORM_BOOL if feature_name in _BOOL_FEATURES else TRANSFORM_IDENTITY
    return (
        tuple(
            _branch(
                feature_name,
                alias,
                _field_path(source_label, alias),
                transform_id=transform,
            )
            for alias in aliases
        ),
        PLAN_RESOLVABLE,
        None,
    )


def _validate_slot_plan(slot: FeatureSlotResolutionPlanV4) -> None:
    if slot._construction_token is not _CONSTRUCTION_TOKEN:
        _fail("FEATURE_RESOLUTION_PLAN_V4_FACTORY_CONSTRUCTION_REQUIRED")
    if (
        type(slot.ordinal) is not int
        or not 0 <= slot.ordinal < FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_ORDINAL_INVALID")
    if not _valid_label(slot.feature_name) or not _valid_label(slot.configured_source_label):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SLOT_IDENTITY_INVALID")
    if not _valid_label(slot.requirement_class):
        _fail("FEATURE_RESOLUTION_PLAN_V4_REQUIREMENT_INVALID")
    if slot.configured_source_label not in _SOURCE_FAMILIES:
        _fail("FEATURE_RESOLUTION_PLAN_V4_SOURCE_FAMILY_UNDECLARED")
    expected_key, expected_schema = _SOURCE_FAMILIES[slot.configured_source_label]
    if (
        slot.source_key_template != expected_key
        or slot.source_payload_schema_version != expected_schema
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SOURCE_IDENTITY_MISMATCH")
    if slot.source_timeframe_template != _source_timeframe_template(slot.configured_source_label):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SOURCE_TIMEFRAME_MISMATCH")
    if slot.source_timeframe_template is not None and not _valid_label(
        slot.source_timeframe_template
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SOURCE_TIMEFRAME_INVALID")
    if not _valid_label(slot.source_key_template) or not _valid_label(
        slot.source_payload_schema_version
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SOURCE_IDENTITY_INVALID")
    if type(slot.branches) is not tuple or any(
        type(branch) is not FeatureResolutionBranchPlanV4 for branch in slot.branches
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_BRANCHES_INVALID")
    for branch in slot.branches:
        _validate_branch_plan(branch)
    if slot.plan_status == PLAN_RESOLVABLE:
        if not slot.branches or slot.unresolved_reason is not None:
            _fail("FEATURE_RESOLUTION_PLAN_V4_RESOLVABLE_BRANCH_REQUIRED")
    elif slot.branches or slot.unresolved_reason != slot.plan_status:
        _fail("FEATURE_RESOLUTION_PLAN_V4_UNRESOLVED_BRANCH_FORBIDDEN")
    if slot.null_policy != NULL_POLICY:
        _fail("FEATURE_RESOLUTION_PLAN_V4_NULL_POLICY_INVALID")
    if slot.empty_collection_policy != EMPTY_COLLECTION_POLICY:
        _fail("FEATURE_RESOLUTION_PLAN_V4_EMPTY_COLLECTION_POLICY_INVALID")
    if slot.typed_negative_policy != TYPED_NEGATIVE_POLICY:
        _fail("FEATURE_RESOLUTION_PLAN_V4_TYPED_NEGATIVE_POLICY_INVALID")
    if slot.requires_closed_candle is not (
        slot.configured_source_label in _CLOSED_CANDLE_SOURCE_LABELS
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_CLOSED_CANDLE_POLICY_INVALID")
    branch_ids = tuple(branch.branch_id for branch in slot.branches)
    if len(branch_ids) != len(set(branch_ids)):
        _fail("FEATURE_RESOLUTION_PLAN_V4_BRANCH_ID_DUPLICATE")


def _slot_contract(slot: FeatureSlotResolutionPlanV4) -> dict[str, Any]:
    return {
        "ordinal": slot.ordinal,
        "feature_name": slot.feature_name,
        "configured_source_label": slot.configured_source_label,
        "requirement_class": slot.requirement_class,
        "source_key_template": slot.source_key_template,
        "source_timeframe_template": slot.source_timeframe_template,
        "source_payload_schema_version": slot.source_payload_schema_version,
        "plan_status": slot.plan_status,
        "unresolved_reason": slot.unresolved_reason,
        "branches": [
            {
                "branch_id": branch.branch_id,
                "selected_alias": branch.selected_alias,
                "dependency_paths": [list(path) for path in branch.dependency_paths],
                "transform_id": branch.transform_id,
                "transform_version": branch.transform_version,
            }
            for branch in slot.branches
        ],
        "requires_closed_candle": slot.requires_closed_candle,
        "null_policy": slot.null_policy,
        "empty_collection_policy": slot.empty_collection_policy,
        "typed_negative_policy": slot.typed_negative_policy,
    }


def _plan_material(slots: tuple[FeatureSlotResolutionPlanV4, ...]) -> dict[str, Any]:
    return {
        "schema_version": FEATURE_RESOLUTION_PLAN_V4_SCHEMA_VERSION,
        "evidence_classification": FEATURE_RESOLUTION_PLAN_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": FEATURE_RESOLUTION_PLAN_V4_DOWNSTREAM_STATUS,
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "slot_count": FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT,
        "slots": [_slot_contract(slot) for slot in slots],
        "authorization": {
            "audit_only": True,
            "runtime_wired": False,
            "source_reads_performed": False,
            "tensor_eligible": False,
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_trading_authorized": False,
            "live_execution_authorized": False,
        },
    }


def _validate_plan_set(plan: FeatureResolutionPlanSetV4) -> None:
    if plan._construction_token is not _CONSTRUCTION_TOKEN:
        _fail("FEATURE_RESOLUTION_PLAN_V4_FACTORY_CONSTRUCTION_REQUIRED")
    if plan.schema_version != FEATURE_RESOLUTION_PLAN_V4_SCHEMA_VERSION:
        _fail("FEATURE_RESOLUTION_PLAN_V4_SCHEMA_MISMATCH")
    if plan.evidence_classification != FEATURE_RESOLUTION_PLAN_V4_EVIDENCE_CLASSIFICATION:
        _fail("FEATURE_RESOLUTION_PLAN_V4_CLASSIFICATION_MISMATCH")
    if plan.downstream_status != FEATURE_RESOLUTION_PLAN_V4_DOWNSTREAM_STATUS:
        _fail("FEATURE_RESOLUTION_PLAN_V4_DOWNSTREAM_STATUS_MISMATCH")
    if plan.feature_source_registry_sha256 != FEATURE_SOURCE_REGISTRY_V4_SHA256:
        _fail("FEATURE_RESOLUTION_PLAN_V4_REGISTRY_SHA256_MISMATCH")
    if type(plan.slots) is not tuple or len(plan.slots) != FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT:
        _fail("FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT_MISMATCH")
    if tuple(slot.ordinal for slot in plan.slots) != tuple(
        range(FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT)
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SLOT_ORDER_MISMATCH")
    if len({slot.feature_name for slot in plan.slots}) != FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT:
        _fail("FEATURE_RESOLUTION_PLAN_V4_FEATURE_NAME_DUPLICATE")
    for slot, registry_slot in zip(plan.slots, FEATURE_SOURCE_REGISTRY_V4.slots, strict=True):
        _validate_slot_plan(slot)
        if (
            slot.ordinal != registry_slot.ordinal
            or slot.feature_name != registry_slot.feature_name
            or slot.configured_source_label != registry_slot.configured_source_label
            or slot.requirement_class != registry_slot.requirement_class
        ):
            _fail("FEATURE_RESOLUTION_PLAN_V4_REGISTRY_BINDING_MISMATCH")
    for ordinal in _FUTURE_SEMANTICS_ORDINALS:
        slot = plan.slots[ordinal]
        if slot.plan_status != PLAN_UNRESOLVED_FUTURE_SEMANTICS or slot.branches:
            _fail("FEATURE_RESOLUTION_PLAN_V4_FUTURE_SEMANTICS_ALIAS_FORBIDDEN")
    for ordinal in _NO_LEGITIMATE_PRODUCER_ORDINALS:
        slot = plan.slots[ordinal]
        if slot.plan_status != PLAN_UNRESOLVED_NO_PRODUCER or slot.branches:
            _fail("FEATURE_RESOLUTION_PLAN_V4_NO_PRODUCER_SELECTOR_FORBIDDEN")
    for ordinal in _PHYSICAL_TIMEFRAME_COLLISION_ORDINALS:
        slot = plan.slots[ordinal]
        if (
            slot.plan_status != PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION
            or slot.branches
            or slot.source_timeframe_template != SOURCE_TIMEFRAME_REQUEST
        ):
            _fail("FEATURE_RESOLUTION_PLAN_V4_PHYSICAL_TIMEFRAME_COLLISION_UNSAFE")
    authority = (
        plan.audit_only,
        plan.runtime_wired,
        plan.source_reads_performed,
        plan.tensor_eligible,
        plan.trainer_admission_authorized,
        plan.prediction_authorized,
        plan.paper_trading_authorized,
        plan.live_execution_authorized,
    )
    if authority != (True, False, False, False, False, False, False, False):
        _fail("FEATURE_RESOLUTION_PLAN_V4_AUTHORITY_INVALID")
    if (
        plan.plan_sha256 != FEATURE_RESOLUTION_PLAN_V4_SHA256
        or plan.plan_sha256 != _canonical_sha256(_plan_material(plan.slots))
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_SHA256_INVALID")


def build_feature_resolution_plan_v4() -> FeatureResolutionPlanSetV4:
    """Build the one code-owned plan; callers cannot supply plan fragments."""

    if (
        FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT != FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT
        or FEATURE_SOURCE_REGISTRY_V4_SHA256 != FEATURE_SOURCE_REGISTRY_V4.registry_sha256
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_PINNED_REGISTRY_MISMATCH")
    registry_names = {slot.feature_name for slot in FEATURE_SOURCE_REGISTRY_V4.slots}
    if (
        len(_EXPLICIT_PRE_GENERIC_FEATURES) != 194
        or not _EXPLICIT_PRE_GENERIC_FEATURES <= registry_names
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_EXPLICIT_ROUTE_INVENTORY_MISMATCH")
    slots: list[FeatureSlotResolutionPlanV4] = []
    for registry_slot in FEATURE_SOURCE_REGISTRY_V4.slots:
        source_key, payload_schema = _SOURCE_FAMILIES[registry_slot.configured_source_label]
        branches, status, reason = _branches_for_slot(
            registry_slot.ordinal,
            registry_slot.feature_name,
            registry_slot.configured_source_label,
        )
        slots.append(
            FeatureSlotResolutionPlanV4(
                ordinal=registry_slot.ordinal,
                feature_name=registry_slot.feature_name,
                configured_source_label=registry_slot.configured_source_label,
                requirement_class=registry_slot.requirement_class,
                source_key_template=source_key,
                source_timeframe_template=_source_timeframe_template(
                    registry_slot.configured_source_label
                ),
                source_payload_schema_version=payload_schema,
                plan_status=status,
                unresolved_reason=reason,
                branches=branches,
                requires_closed_candle=(
                    registry_slot.configured_source_label in _CLOSED_CANDLE_SOURCE_LABELS
                ),
                null_policy=NULL_POLICY,
                empty_collection_policy=EMPTY_COLLECTION_POLICY,
                typed_negative_policy=TYPED_NEGATIVE_POLICY,
                _construction_token=_CONSTRUCTION_TOKEN,
            )
        )
    frozen = tuple(slots)
    digest = _canonical_sha256(_plan_material(frozen))
    if digest != FEATURE_RESOLUTION_PLAN_V4_SHA256:
        _fail("FEATURE_RESOLUTION_PLAN_V4_SHA256_MISMATCH")
    return FeatureResolutionPlanSetV4(
        schema_version=FEATURE_RESOLUTION_PLAN_V4_SCHEMA_VERSION,
        evidence_classification=FEATURE_RESOLUTION_PLAN_V4_EVIDENCE_CLASSIFICATION,
        downstream_status=FEATURE_RESOLUTION_PLAN_V4_DOWNSTREAM_STATUS,
        feature_source_registry_sha256=FEATURE_SOURCE_REGISTRY_V4_SHA256,
        slots=frozen,
        plan_sha256=digest,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def feature_resolution_plan_v4_contract(plan: FeatureResolutionPlanSetV4) -> dict[str, Any]:
    """Return a detached canonical plan contract with no authorization."""

    if type(plan) is not FeatureResolutionPlanSetV4:
        _fail("FEATURE_RESOLUTION_PLAN_V4_NOT_EXACT_PLAN")
    _validate_plan_set(plan)
    contract = _plan_material(plan.slots)
    contract["plan_sha256"] = plan.plan_sha256
    return contract


def _validate_pinned_slot_instance(slot: object) -> FeatureSlotResolutionPlanV4:
    if type(slot) is not FeatureSlotResolutionPlanV4:
        _fail("FEATURE_RESOLUTION_PLAN_V4_NOT_EXACT_SLOT")
    _validate_plan_set(FEATURE_RESOLUTION_PLAN_V4)
    exact_slot = slot
    _validate_slot_plan(exact_slot)
    if exact_slot is not FEATURE_RESOLUTION_PLAN_V4.slots[exact_slot.ordinal]:
        _fail("FEATURE_RESOLUTION_PLAN_V4_SLOT_NOT_PINNED_INSTANCE")
    return exact_slot


def materialize_feature_source_key_v4(
    slot: FeatureSlotResolutionPlanV4,
    *,
    symbol: str,
    timeframe: str,
) -> str:
    """Materialize only the exact key template embedded in a validated slot."""

    slot = _validate_pinned_slot_instance(slot)
    if type(symbol) is not str or re.fullmatch(r"[A-Z0-9]{2,32}", symbol) is None:
        _fail("FEATURE_RESOLUTION_PLAN_V4_SYMBOL_INVALID")
    if type(timeframe) is not str or re.fullmatch(r"[1-9][0-9]{0,5}[mhdw]", timeframe) is None:
        _fail("FEATURE_RESOLUTION_PLAN_V4_TIMEFRAME_INVALID")
    template = slot.source_key_template
    if template is None:  # pragma: no cover - current registry always has a family declaration.
        _fail("FEATURE_RESOLUTION_PLAN_V4_SOURCE_KEY_UNDECLARED")
    return template.format(symbol=symbol, timeframe=timeframe)


def materialize_feature_source_timeframe_v4(
    slot: FeatureSlotResolutionPlanV4,
    *,
    request_timeframe: str,
) -> str | None:
    """Return the physical source timeframe without conflating model cadence."""

    slot = _validate_pinned_slot_instance(slot)
    if (
        type(request_timeframe) is not str
        or re.fullmatch(r"[1-9][0-9]{0,5}[mhdw]", request_timeframe) is None
    ):
        _fail("FEATURE_RESOLUTION_PLAN_V4_REQUEST_TIMEFRAME_INVALID")
    template = slot.source_timeframe_template
    if template is None:
        return None
    return request_timeframe if template == SOURCE_TIMEFRAME_REQUEST else template


FEATURE_RESOLUTION_PLAN_V4 = build_feature_resolution_plan_v4()


__all__ = [
    "CANONICAL_SOURCE_RECORD_V4_SCHEMA_VERSION",
    "EMPTY_COLLECTION_POLICY",
    "FEATURE_RESOLUTION_PLAN_V4",
    "FEATURE_RESOLUTION_PLAN_V4_DOWNSTREAM_STATUS",
    "FEATURE_RESOLUTION_PLAN_V4_EVIDENCE_CLASSIFICATION",
    "FEATURE_RESOLUTION_PLAN_V4_SCHEMA_VERSION",
    "FEATURE_RESOLUTION_PLAN_V4_SHA256",
    "FEATURE_RESOLUTION_PLAN_V4_SLOT_COUNT",
    "FeatureResolutionBranchPlanV4",
    "FeatureResolutionPlanSetV4",
    "FeatureResolutionPlanV4ValidationError",
    "FeatureSlotResolutionPlanV4",
    "NULL_POLICY",
    "PLAN_RESOLVABLE",
    "PLAN_UNRESOLVED_AUTHENTICATED_WINDOW",
    "PLAN_UNRESOLVED_FUTURE_SEMANTICS",
    "PLAN_UNRESOLVED_GENERIC_FALLBACK_FORBIDDEN",
    "PLAN_UNRESOLVED_NO_PRODUCER",
    "PLAN_UNRESOLVED_PHYSICAL_TIMEFRAME_COLLISION",
    "SOURCE_TIMEFRAME_REQUEST",
    "TRANSFORM_BOOL",
    "TRANSFORM_COMPLEMENT_RATIO",
    "TRANSFORM_IDENTITY",
    "TRANSFORM_NONNEGATIVE_DIFFERENCE",
    "TRANSFORM_RATIO",
    "TYPED_NEGATIVE_POLICY",
    "build_feature_resolution_plan_v4",
    "feature_resolution_plan_v4_contract",
    "materialize_feature_source_key_v4",
    "materialize_feature_source_timeframe_v4",
]
