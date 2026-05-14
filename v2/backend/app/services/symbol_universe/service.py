from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Iterable, List, Optional

from ...domain.symbols.models import SymbolIdentity, SymbolOverride, SymbolStateRecord, UniverseVersion
from ...domain.symbols.state_machine import apply_override


HOT_RELOAD_COMPONENTS = [
    "ingestors",
    "feature_pipeline",
    "trainer",
    "orchestrator",
    "risk_gateway",
    "trader_fleet",
    "monitor",
    "gui",
]


LEGACY_ACTIVE_SYMBOLS_25 = [
    "1000BONKUSDT",
    "1000FLOKIUSDT",
    "1000PEPEUSDT",
    "1000SHIBUSDT",
    "ALICEUSDT",
    "ASTERUSDT",
    "AUCTIONUSDT",
    "AVNTUSDT",
    "BANKUSDT",
    "BARDUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "FARTCOINUSDT",
    "HIGHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "PENGUUSDT",
    "PIPPINUSDT",
    "RAVEUSDT",
    "RIVERUSDT",
    "SOLUSDT",
    "UNIUSDT",
    "WIFUSDT",
    "XRPUSDT",
]

DYNAMIC_SYMBOL_SOURCES = [
    "binance_futures",
    "coinank",
    "coinapi",
    "kucoin",
    "future_ingestors",
]

SYMBOL_SELECTION_SCORE_FACTORS = [
    "liquidity",
    "volume",
    "volatility",
    "funding",
    "open_interest",
    "spread",
    "freshness",
    "feature_completeness",
    "exchange_availability",
    "risk_profile",
    "model_confidence",
    "replay_performance",
    "operator_overrides",
]


class SymbolUniverseService:
    def __init__(
        self,
        identities: Iterable[SymbolIdentity] = (),
        legacy_active_symbols: Optional[Iterable[str]] = None,
    ):
        self.identities = list(identities)
        legacy_seed = legacy_active_symbols if legacy_active_symbols is not None else LEGACY_ACTIVE_SYMBOLS_25
        self._legacy_active_symbols = sorted({symbol.upper() for symbol in legacy_seed})

    def all_discovered_symbols(self) -> List[SymbolIdentity]:
        return list(self.identities)

    def legacy_active_symbols(self) -> List[str]:
        return list(self._legacy_active_symbols)

    def apply_manual_override(self, record: SymbolStateRecord, override: SymbolOverride) -> SymbolStateRecord:
        return apply_override(record, override)

    def make_universe_version(
        self,
        previous: Iterable[SymbolIdentity],
        current: Iterable[SymbolIdentity],
        reason: str,
        approval_state: str = "pending_review",
    ) -> UniverseVersion:
        prev_ids = {i.canonical_symbol_id for i in previous}
        curr_ids = {i.canonical_symbol_id for i in current}
        added = sorted(curr_ids - prev_ids)
        removed = sorted(prev_ids - curr_ids)
        changed = sorted(added + removed)
        digest = hashlib.sha256(json.dumps(changed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        return UniverseVersion(
            universe_version_id=f"universe-{digest}",
            generated_ts=dt.datetime.now(dt.timezone.utc).isoformat(),
            source_snapshot_ids=[],
            changed_symbols=changed,
            added_symbols=added,
            removed_symbols=removed,
            disabled_symbols=[],
            override_symbols=[],
            reason=reason,
            approval_state=approval_state,
            hot_reload_required_components=HOT_RELOAD_COMPONENTS if changed else [],
        )
