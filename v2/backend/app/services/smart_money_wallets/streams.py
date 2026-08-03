"""Moralis Streams webhook helpers.

This module validates only the local contract shape. It does not create or
mutate Moralis streams; stream setup remains an operator action.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.smart_money_wallets.endpoint_registry import moralis_endpoint_registry
from app.services.smart_money_wallets.normalizer import normalize_moralis_payload


def normalize_stream_webhook(payload: Mapping[str, Any]) -> dict[str, Any]:
    spec = next(item for item in moralis_endpoint_registry() if item.endpoint_id == "streams")
    chain = str(payload.get("chainId") or payload.get("chain") or "unknown")
    return normalize_moralis_payload(
        spec=spec,
        symbol=None,
        chain=chain,
        wallet=None,
        token=None,
        payload=payload,
    )
