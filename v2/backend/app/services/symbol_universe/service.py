from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Iterable, List

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


class SymbolUniverseService:
    def __init__(self, identities: Iterable[SymbolIdentity] = ()):
        self.identities = list(identities)

    def all_discovered_symbols(self) -> List[SymbolIdentity]:
        return list(self.identities)

    def legacy_active_symbols(self) -> List[str]:
        return sorted({i.legacy_symbol for i in self.identities if i.legacy_symbol})

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

