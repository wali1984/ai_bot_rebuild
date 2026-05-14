"""Lightweight position context scaffolding.

Maintains per-symbol position state and exposes a fixed-size vector for
optional model consumption. Defaults are zeroed to avoid behavior changes
when disabled.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PositionSnapshot:
    side: str = "FLAT"
    entry_price: float = 0.0
    ts_open: float = 0.0
    last_price: float = 0.0
    unrealized_pnl_pct: float = 0.0
    realized_pnl_today: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    distance_to_liq_long: float = 0.0
    distance_to_liq_short: float = 0.0
    updated_at: float = field(default_factory=lambda: time.time())


class PositionContextManager:
    """Manage per-symbol position context with safe defaults."""

    def __init__(self, vector_size: int = 10, redis_client=None, warn_interval_sec: int = 3600):
        self.vector_size = vector_size
        self.redis = redis_client
        self._snapshots: Dict[str, PositionSnapshot] = {}
        self._last_warn_ts: float = 0.0
        self._warn_interval = warn_interval_sec
        self._zero_vector: List[float] = [0.0 for _ in range(vector_size)]

    def _clamp(self, value: float, lo: float = -100.0, hi: float = 100.0) -> float:
        try:
            return max(lo, min(hi, float(value)))
        except Exception:
            return 0.0

    def _side_onehot(self, side: str) -> Tuple[float, float, float]:
        side_upper = (side or "").upper()
        if side_upper == "LONG":
            return (1.0, 0.0, 0.0)
        if side_upper == "SHORT":
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)

    def update(self, symbol: str, position: Optional[Dict[str, float]], last_price: Optional[float] = None):
        """Update tracked snapshot from external position data."""
        if not symbol:
            return
        snap = self._snapshots.get(symbol, PositionSnapshot())

        if position:
            snap.side = position.get("side", snap.side) or "FLAT"
            snap.entry_price = float(position.get("entry_price", snap.entry_price) or 0.0)
            snap.ts_open = float(position.get("timestamp", position.get("ts_open", snap.ts_open) or 0.0))
            snap.unrealized_pnl_pct = float(position.get("unrealized_pnl_pct", snap.unrealized_pnl_pct) or 0.0)
            snap.realized_pnl_today = float(position.get("realized_pnl_today", snap.realized_pnl_today) or 0.0)
            snap.mfe_pct = float(position.get("mfe_pct", snap.mfe_pct) or snap.unrealized_pnl_pct)
            snap.mae_pct = float(position.get("mae_pct", snap.mae_pct) or 0.0)
            snap.distance_to_liq_long = float(position.get("distance_to_liq_long", snap.distance_to_liq_long) or 0.0)
            snap.distance_to_liq_short = float(position.get("distance_to_liq_short", snap.distance_to_liq_short) or 0.0)

        snap.last_price = float(last_price or snap.last_price or 0.0)
        snap.updated_at = time.time()
        self._snapshots[symbol] = snap

    def _warn_missing_once(self, symbol: str):
        now = time.time()
        if now - self._last_warn_ts >= self._warn_interval:
            self._last_warn_ts = now
            logger.info(f"[POSITION_CONTEXT] Missing position data for {symbol} — using zeros")

    def get_context(self, symbol: str) -> PositionSnapshot:
        snap = self._snapshots.get(symbol)
        if snap:
            return snap
        self._warn_missing_once(symbol)
        return PositionSnapshot()

    def get_vector(self, symbol: str, now: Optional[float] = None) -> List[float]:
        snap = self.get_context(symbol)
        ts_now = now or time.time()
        time_in_trade = max(0.0, ts_now - float(snap.ts_open or 0.0)) if snap.ts_open else 0.0
        time_norm = min(time_in_trade / 86400.0, 1.0)  # Normalize to 1 day window

        side_vec = self._side_onehot(snap.side)
        unreal = self._clamp(snap.unrealized_pnl_pct)
        mfe = self._clamp(snap.mfe_pct if snap.mfe_pct != 0.0 else snap.unrealized_pnl_pct)
        mae = self._clamp(snap.mae_pct)
        realized_norm = self._clamp(snap.realized_pnl_today, lo=-1000.0, hi=1000.0) / 100.0

        dist_long = max(0.0, float(snap.distance_to_liq_long or 0.0))
        dist_short = max(0.0, float(snap.distance_to_liq_short or 0.0))
        nearest_liq = min([d for d in [dist_long, dist_short] if d > 0], default=0.0)

        vector = list(side_vec) + [
            time_norm,
            unreal,
            mfe,
            mae,
            realized_norm,
            dist_long,
            dist_short,
            nearest_liq,
        ]

        # Pad or trim to target vector size to remain stable
        if len(vector) < self.vector_size:
            vector = vector + [0.0] * (self.vector_size - len(vector))
        elif len(vector) > self.vector_size:
            vector = vector[: self.vector_size]
        return vector

    def as_dict(self, symbol: str) -> Dict[str, float]:
        snap = self.get_context(symbol)
        return {
            "side": snap.side,
            "entry_price": snap.entry_price,
            "ts_open": snap.ts_open,
            "unrealized_pnl_pct": snap.unrealized_pnl_pct,
            "realized_pnl_today": snap.realized_pnl_today,
            "mfe_pct": snap.mfe_pct,
            "mae_pct": snap.mae_pct,
            "distance_to_liq_long": snap.distance_to_liq_long,
            "distance_to_liq_short": snap.distance_to_liq_short,
            "nearest_liq": min([d for d in [snap.distance_to_liq_long, snap.distance_to_liq_short] if d > 0], default=0.0),
            "last_price": snap.last_price,
            "updated_at": snap.updated_at,
        }
