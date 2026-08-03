"""Causal request receipts and flat snapshots for CoinAnk ingestion.

The helpers are deliberately I/O-light and independent of Redis.  A request
clock is captured immediately before the supplied session performs network
I/O, and a response-observation clock immediately after it returns.  Redis
commit time remains a separate producer clock; none of these clocks is a
trainer-authority receipt.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

MAX_SIGNED_64_BIT_INTEGER = (1 << 63) - 1


def _positive_epoch_ms(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}_NOT_INTEGER_MS")
    if value <= 0:
        raise ValueError(f"{name}_NOT_POSITIVE")
    if value > MAX_SIGNED_64_BIT_INTEGER:
        raise ValueError(f"{name}_OUTSIDE_SIGNED_64_BIT_MS")
    return value


def causal_request_receipt_fields(
    receipt: Mapping[str, Any],
    *,
    persisted_at_ms: Any,
) -> dict[str, int]:
    """Validate and return an immutable causal request-clock projection."""

    if not isinstance(receipt, Mapping):
        raise ValueError("COINANK_REQUEST_RECEIPT_NOT_MAPPING")
    request_started_at_ms = _positive_epoch_ms(
        receipt.get("request_started_at_ms"),
        name="COINANK_REQUEST_STARTED_AT",
    )
    response_observed_at_ms = _positive_epoch_ms(
        receipt.get("response_observed_at_ms"),
        name="COINANK_RESPONSE_OBSERVED_AT",
    )
    persisted = _positive_epoch_ms(
        persisted_at_ms,
        name="COINANK_PERSISTED_AT",
    )
    if not request_started_at_ms <= response_observed_at_ms <= persisted:
        raise ValueError("COINANK_REQUEST_RECEIPT_CLOCK_ORDER_INVALID")
    return {
        "request_started_at_ms": request_started_at_ms,
        "response_observed_at_ms": response_observed_at_ms,
    }


def request_with_causal_receipt(
    session: Any,
    *,
    url: str,
    params: Mapping[str, Any],
    timeout: float,
    now_ms: Callable[[], int],
) -> tuple[Any, dict[str, int]]:
    """Perform one request with clocks immediately around network I/O."""

    request_started_at_ms = _positive_epoch_ms(
        now_ms(),
        name="COINANK_REQUEST_STARTED_AT",
    )
    response = session.get(url, params=dict(params), timeout=timeout)
    response_observed_at_ms = _positive_epoch_ms(
        now_ms(),
        name="COINANK_RESPONSE_OBSERVED_AT",
    )
    if response_observed_at_ms < request_started_at_ms:
        raise ValueError("COINANK_REQUEST_RECEIPT_CLOCK_ORDER_INVALID")
    return response, {
        "request_started_at_ms": request_started_at_ms,
        "response_observed_at_ms": response_observed_at_ms,
    }


def build_coinank_flat_snapshot(
    *,
    persisted_at_ms: Any,
    request_receipt: Mapping[str, Any],
    symbol: str,
    exchange: str,
    family: str,
    endpoint: str,
    endpoint_variant: str | None,
    request_parameters: Mapping[str, Any],
    interval: str,
    data: Any,
) -> dict[str, Any]:
    """Build the exact legacy flat-key payload with causal request clocks."""

    persisted = _positive_epoch_ms(
        persisted_at_ms,
        name="COINANK_PERSISTED_AT",
    )
    receipt_fields = causal_request_receipt_fields(
        request_receipt,
        persisted_at_ms=persisted,
    )
    return {
        "ts_ms": persisted,
        "timestamp": persisted,
        **receipt_fields,
        "symbol": str(symbol),
        "exchange": str(exchange),
        "family": str(family),
        "endpoint": str(endpoint),
        "endpoint_variant": endpoint_variant or None,
        "request_parameters": dict(request_parameters),
        "interval": str(interval),
        "data": data,
    }


__all__ = [
    "MAX_SIGNED_64_BIT_INTEGER",
    "build_coinank_flat_snapshot",
    "causal_request_receipt_fields",
    "request_with_causal_receipt",
]
