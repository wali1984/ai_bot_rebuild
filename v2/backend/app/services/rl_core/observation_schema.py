"""V2 observation schema descriptor.

This module declares the V2 observation field schema as a *descriptor only*.
It does NOT assemble a runtime tensor. Runtime tensor assembly depends on the
unified feature builder, which is owned by Subproject 2
(feature_intelligence) and is currently MISSING_IN_V2 at the policy-input
layer.

Legacy reference:
    v2/legacy_preserved/full_runtime_closure/rl/obs_schema.py
    sha256: 9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f
    size_bytes: 17346

The legacy ``ObsSchema`` defines 3 versions (V1=1053 dims, V2=1061 dims,
V3=1911 dims) as opaque slice groups. The V2 schema here is a *field-level*
descriptor for the ~30 high-level features the policy consumes; the underlying
tensor dimension is determined by the (still missing) unified feature builder.

Each :class:`V2ObservationField` carries:

- ``name``: canonical V2 field identifier
- ``dtype``: numpy-compatible dtype string
- ``low`` / ``high``: documented normalized value range (None = unbounded)
- ``freshness_required``: whether the feature must be fresh-stamped by the
  feature pipeline (block stale)
- ``legacy_slice``: which legacy ObsSchema slice this field belongs to
- ``description``: short prose
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

LEGACY_OBS_SHA256 = "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f"
"""SHA256 of v2/legacy_preserved/full_runtime_closure/rl/obs_schema.py.

Cited from claude_worklog/legacy_runtime_closure/full_runtime_copied_source_manifest.json.
"""


@dataclass(frozen=True)
class V2ObservationField:
    """A single declarative V2 observation field descriptor."""

    name: str
    dtype: str
    low: Optional[float]
    high: Optional[float]
    freshness_required: bool
    legacy_slice: str
    description: str


# The descriptor below lists ~30 high-level fields the policy is expected to
# consume in V2. It is intentionally field-level and human-readable, in
# contrast to the legacy ObsSchema which is a flat 1911-dim slice register.
# Mapping back to legacy slices is preserved via ``legacy_slice``.
V2_OBSERVATION_SCHEMA: tuple[V2ObservationField, ...] = (
    # --- Price / OHLCV normalization ---
    V2ObservationField(
        name="price_norm",
        dtype="float32",
        low=-10.0,
        high=10.0,
        freshness_required=True,
        legacy_slice="ohlcv_multi_tf",
        description="Z-scored last price across the symbol's rolling window.",
    ),
    V2ObservationField(
        name="return_1m",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="ohlcv_multi_tf",
        description="Log return over 1 minute.",
    ),
    V2ObservationField(
        name="return_5m",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="ohlcv_multi_tf",
        description="Log return over 5 minutes.",
    ),
    V2ObservationField(
        name="return_15m",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="ohlcv_multi_tf",
        description="Log return over 15 minutes.",
    ),
    V2ObservationField(
        name="return_1h",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="ohlcv_multi_tf",
        description="Log return over 1 hour.",
    ),
    # --- Volatility / ATR ---
    V2ObservationField(
        name="atr_pct",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="volatility",
        description="ATR as a fraction of price.",
    ),
    V2ObservationField(
        name="realized_vol_1h",
        dtype="float32",
        low=0.0,
        high=5.0,
        freshness_required=True,
        legacy_slice="volatility",
        description="Realized volatility over the last hour.",
    ),
    # --- Volume / flow ---
    V2ObservationField(
        name="volume_zscore",
        dtype="float32",
        low=-10.0,
        high=10.0,
        freshness_required=True,
        legacy_slice="volume_profile",
        description="Z-scored last-bar volume.",
    ),
    V2ObservationField(
        name="taker_buy_ratio",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="volume_profile",
        description="Fraction of taker buy volume in the most recent bar.",
    ),
    # --- Momentum / technicals ---
    V2ObservationField(
        name="rsi_14",
        dtype="float32",
        low=0.0,
        high=100.0,
        freshness_required=True,
        legacy_slice="technical_indicators",
        description="RSI(14) classical momentum.",
    ),
    V2ObservationField(
        name="macd_hist",
        dtype="float32",
        low=-5.0,
        high=5.0,
        freshness_required=True,
        legacy_slice="momentum",
        description="MACD histogram normalized.",
    ),
    V2ObservationField(
        name="bollinger_pct_b",
        dtype="float32",
        low=-1.0,
        high=2.0,
        freshness_required=True,
        legacy_slice="technical_indicators",
        description="Bollinger %B position.",
    ),
    # --- Derivatives microstructure ---
    V2ObservationField(
        name="funding_rate",
        dtype="float32",
        low=-0.01,
        high=0.01,
        freshness_required=True,
        legacy_slice="orderbook_depth",
        description="Latest funding rate (8h, USDM convention).",
    ),
    V2ObservationField(
        name="oi_change_pct",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="orderbook_depth",
        description="Open interest percentage change over recent window.",
    ),
    V2ObservationField(
        name="basis_pct",
        dtype="float32",
        low=-0.05,
        high=0.05,
        freshness_required=True,
        legacy_slice="orderbook_depth",
        description="Perp-spot basis as percentage.",
    ),
    V2ObservationField(
        name="liquidations_1m_usd",
        dtype="float32",
        low=0.0,
        high=None,
        freshness_required=True,
        legacy_slice="orderbook_depth",
        description="USD-denominated liquidations in the last minute.",
    ),
    # --- Orderbook proxies ---
    V2ObservationField(
        name="spread_bps",
        dtype="float32",
        low=0.0,
        high=500.0,
        freshness_required=True,
        legacy_slice="orderbook_depth",
        description="Top-of-book spread in basis points.",
    ),
    V2ObservationField(
        name="depth_imbalance",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="orderbook_depth",
        description="(bid_depth - ask_depth) / (bid + ask) within top N levels.",
    ),
    # --- Regime / context (one-hot) ---
    V2ObservationField(
        name="regime_trend",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="unified_features",
        description="One-hot regime: trend.",
    ),
    V2ObservationField(
        name="regime_range",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="unified_features",
        description="One-hot regime: range.",
    ),
    V2ObservationField(
        name="regime_chop",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="unified_features",
        description="One-hot regime: chop.",
    ),
    # --- BTC anchor / on-chain proxies ---
    V2ObservationField(
        name="btc_return_5m",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="onchain_btc",
        description="BTC 5-minute return; cross-symbol anchor.",
    ),
    V2ObservationField(
        name="btc_corr_30m",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=False,
        legacy_slice="onchain_btc",
        description="Rolling 30-minute correlation with BTC return.",
    ),
    # --- Confidence inputs ---
    V2ObservationField(
        name="confidence_blended_logit",
        dtype="float32",
        low=-20.0,
        high=20.0,
        freshness_required=True,
        legacy_slice="unified_features",
        description="Blended PPO/MASA decision logit feed into confidence.",
    ),
    V2ObservationField(
        name="confidence_temperature",
        dtype="float32",
        low=0.01,
        high=10.0,
        freshness_required=False,
        legacy_slice="unified_features",
        description="Temperature-scaling parameter T (informational; >1 softer).",
    ),
    # --- Expected move signal ---
    V2ObservationField(
        name="expected_move_bps",
        dtype="float32",
        low=0.0,
        high=10000.0,
        freshness_required=True,
        legacy_slice="unified_features",
        description="Expected move magnitude in basis points.",
    ),
    # --- Position state ---
    V2ObservationField(
        name="position_side",
        dtype="float32",
        low=-1.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="portfolio_state",
        description="Position side encoding: -1 short / 0 flat / +1 long.",
    ),
    V2ObservationField(
        name="position_size_norm",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="portfolio_state",
        description="Position notional normalized by account equity cap.",
    ),
    V2ObservationField(
        name="unrealized_roe_pct",
        dtype="float32",
        low=-5.0,
        high=5.0,
        freshness_required=True,
        legacy_slice="position_context",
        description="Unrealized ROE as a fraction (e.g. 0.05 = 5%).",
    ),
    V2ObservationField(
        name="time_in_position_min",
        dtype="float32",
        low=0.0,
        high=None,
        freshness_required=True,
        legacy_slice="position_context",
        description="Minutes since current position open (0 if flat).",
    ),
    V2ObservationField(
        name="account_drawdown_pct",
        dtype="float32",
        low=0.0,
        high=1.0,
        freshness_required=True,
        legacy_slice="portfolio_state",
        description="Account-level drawdown from peak as a fraction.",
    ),
)


def observation_field_names() -> tuple[str, ...]:
    """Return the ordered tuple of V2 observation field names."""
    return tuple(field.name for field in V2_OBSERVATION_SCHEMA)


def observation_schema_completeness() -> dict[str, object]:
    """Summarize coverage of the V2 schema against legacy slices.

    Returns a dict with:

    - ``field_count``: number of declared fields
    - ``legacy_slices_covered``: sorted unique legacy slice names
    - ``freshness_required_count``: fields that require fresh data
    - ``unbounded_high_fields``: fields with no documented upper bound
    - ``legacy_obs_sha256``: cited SHA256 of the legacy obs_schema.py
    """
    fields = V2_OBSERVATION_SCHEMA
    slices = sorted({f.legacy_slice for f in fields})
    return {
        "field_count": len(fields),
        "legacy_slices_covered": slices,
        "freshness_required_count": sum(1 for f in fields if f.freshness_required),
        "unbounded_high_fields": [f.name for f in fields if f.high is None],
        "legacy_obs_sha256": LEGACY_OBS_SHA256,
    }
