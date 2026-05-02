from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, List

from ...domain.symbols.models import SymbolIdentity
from ...domain.symbols.normalization import normalize_source_symbol


class BinanceCoinMFuturesSource:
    source = "binance_coinm"

    def __init__(self, base_endpoint: str = "https://dapi.binance.com") -> None:
        self.base_endpoint = base_endpoint.rstrip("/")

    @property
    def exchange_info_url(self) -> str:
        return f"{self.base_endpoint}/dapi/v1/exchangeInfo"

    def fetch_exchange_info(self, timeout: float = 10.0) -> Dict[str, Any]:
        with urllib.request.urlopen(self.exchange_info_url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def from_payload(self, payload: Dict[str, Any]) -> List[SymbolIdentity]:
        return [normalize_source_symbol(self.source, item) for item in payload.get("symbols", [])]

