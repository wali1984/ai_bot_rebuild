from __future__ import annotations

from ...domain.symbols.models import SymbolIdentity
from ...domain.symbols.normalization import normalize_source_symbol


class KuCoinFuturesSymbolSource:
    source = "kucoin"

    def from_payload(self, payload: dict) -> list[SymbolIdentity]:
        rows = payload if isinstance(payload, list) else payload.get("symbols", [])
        return [normalize_source_symbol(self.source, row) for row in rows]

