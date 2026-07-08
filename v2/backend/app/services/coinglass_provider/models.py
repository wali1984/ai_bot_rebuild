"""CoinGlass provider models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CoinGlassResponse:
    endpoint_id: str
    symbol: str | None
    http_status: int | None
    payload: Any
    headers: dict[str, object] = field(default_factory=dict)
    error_class: str | None = None

    @property
    def ok(self) -> bool:
        return self.http_status is not None and 200 <= int(self.http_status) <= 299
