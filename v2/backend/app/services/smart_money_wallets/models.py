"""Moralis provider models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_MORALIS_RAW_RESPONSE_BYTES = 262_144
MORALIS_RAW_RESPONSE_BYTES_SCOPE = (
    "HTTPX_ITER_RAW_AFTER_TRANSFER_DECODING_WITH_IDENTITY_CONTENT_ENCODING"
)


@dataclass(frozen=True)
class MoralisResponse:
    endpoint_id: str
    chain: str
    wallet: str | None
    token: str | None
    symbol: str | None
    http_status: int | None
    payload: Any
    headers: dict[str, object] = field(default_factory=dict)
    error_class: str | None = None
    request_dispatched: bool = False
    raw_response_bytes: bytes | None = None
    raw_response_sha256: str | None = None
    raw_response_byte_count: int | None = None
    raw_response_bytes_scope: str | None = None
    transport_started_at: str | None = None
    observed_at: str | None = None
    ingested_at: str | None = None
    # Only an atomic durable publication/readback receipt may populate this.
    # The HTTP client deliberately has no such authority.
    available_at: None = None

    @property
    def ok(self) -> bool:
        return (
            self.error_class is None
            and self.http_status is not None
            and 200 <= int(self.http_status) <= 299
        )
