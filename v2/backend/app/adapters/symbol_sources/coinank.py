from __future__ import annotations

from typing import Any, Dict, List

from ...domain.symbols.coinank_rows import (
    coinank_identity_from_row,
    coinank_row_from_payload,
    confirm_coinank_against_usdm,
)
from ...domain.symbols.models import SymbolIdentity
from ...domain.symbols.normalization import build_alias_set


class CoinAnkSymbolSource:
    source = "coinank"

    def from_payload(self, payload: Any) -> List[SymbolIdentity]:
        rows = self._extract_rows(payload)
        identities: List[SymbolIdentity] = []
        for raw in rows:
            row = coinank_row_from_payload(raw)
            identity = coinank_identity_from_row(row)
            identities.append(
                SymbolIdentity(**{**identity.__dict__, "alias_set": build_alias_set(identity)})
            )
        return identities

    def confirm_against_usdm(
        self,
        coinank_identities: List[SymbolIdentity],
        usdm_identities: List[SymbolIdentity],
    ) -> Dict[str, SymbolIdentity]:
        confirmed: Dict[str, SymbolIdentity] = {}
        for cid in coinank_identities:
            usdm = confirm_coinank_against_usdm(cid, usdm_identities)
            if usdm is not None:
                confirmed[cid.canonical_symbol_id] = usdm
        return confirmed

    @staticmethod
    def _extract_rows(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return list(payload)
        if isinstance(payload, dict):
            for key in ("symbols", "rows", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return list(value)
        return []
