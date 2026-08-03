"""Market structure features: liquidity zones, FVG, order blocks, structure.

All computations derive from V2-owned evidence (closed candles, orderbook
features, liquidation levels, trade tape). Missing inputs yield explicit None
fields with reasons — never fabricated values. Paper-only analytics; nothing
here touches an exchange.
"""

from v2.backend.app.services.market_structure.liquidity_zones import (
    compute_liquidity_zones,
)
from v2.backend.app.services.market_structure.fair_value_gap import compute_fvg
from v2.backend.app.services.market_structure.structure_breaks import (
    compute_structure,
)
from v2.backend.app.services.market_structure.volume_profile import (
    compute_volume_profile,
)
from v2.backend.app.services.market_structure.vwap_features import (
    compute_vwap_features,
)
from v2.backend.app.services.market_structure.cvd_features import (
    compute_cvd_features,
)
from v2.backend.app.services.market_structure.trade_tape_features import (
    compute_trade_tape_features,
)

__all__ = [
    "compute_liquidity_zones",
    "compute_fvg",
    "compute_structure",
    "compute_volume_profile",
    "compute_vwap_features",
    "compute_cvd_features",
    "compute_trade_tape_features",
]
