from __future__ import annotations

from typing import Protocol

from ...domain.symbols.models import SymbolIdentity


class SymbolSourceAdapter(Protocol):
    source: str

    def from_payload(self, payload: dict) -> list[SymbolIdentity]:
        ...


class SymbolSourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SymbolSourceAdapter] = {}

    def register(self, adapter: SymbolSourceAdapter) -> None:
        self._adapters[adapter.source] = adapter

    def get(self, source: str) -> SymbolSourceAdapter:
        return self._adapters[source]

    def sources(self) -> list[str]:
        return sorted(self._adapters)

