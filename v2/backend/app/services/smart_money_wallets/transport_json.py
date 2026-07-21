"""Bounded JSON canonicalization for exact Moralis transport evidence.

Transport validity and semantic admissibility are deliberately separate.  A
provider response may contain Unicode display metadata that is unsafe for a
Redis key, feature, model input, or operator label while still being valid
JSON evidence.  This module applies only type and resource bounds and emits an
ASCII canonical form; semantic callers must project and validate the fields
they actually use.
"""

from __future__ import annotations

import json
import math
from typing import Any

MAX_MORALIS_TRANSPORT_JSON_DEPTH = 16
MAX_MORALIS_TRANSPORT_JSON_LIST_ITEMS = 1000
MAX_MORALIS_TRANSPORT_JSON_OBJECT_FIELDS = 512
MAX_MORALIS_TRANSPORT_JSON_STRING_BYTES = 16_384
MAX_MORALIS_TRANSPORT_JSON_TOTAL_NODES = 20_000
MAX_MORALIS_TRANSPORT_CANONICAL_JSON_BYTES = 4_194_304


def canonical_transport_json_bytes(value: Any) -> bytes:
    """Return bounded canonical ASCII JSON without granting semantic safety."""

    validate_transport_json(value)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii", errors="strict")
    if len(encoded) > MAX_MORALIS_TRANSPORT_CANONICAL_JSON_BYTES:
        raise ValueError("transport JSON byte limit exceeded")
    return encoded


def validate_transport_json(
    value: Any,
    *,
    depth: int = 0,
    node_budget: list[int] | None = None,
) -> None:
    """Validate JSON types and resource bounds while retaining raw metadata."""

    if node_budget is None:
        node_budget = [MAX_MORALIS_TRANSPORT_JSON_TOTAL_NODES]
    node_budget[0] -= 1
    if node_budget[0] < 0:
        raise ValueError("transport JSON node limit exceeded")
    if depth > MAX_MORALIS_TRANSPORT_JSON_DEPTH:
        raise ValueError("transport JSON depth limit exceeded")
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("transport JSON non-finite number")
        return
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="strict")
        if len(encoded) > MAX_MORALIS_TRANSPORT_JSON_STRING_BYTES:
            raise ValueError("transport JSON string byte limit exceeded")
        return
    if isinstance(value, list):
        if len(value) > MAX_MORALIS_TRANSPORT_JSON_LIST_ITEMS:
            raise ValueError("transport JSON list cardinality exceeded")
        for item in value:
            validate_transport_json(
                item,
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    if isinstance(value, dict):
        if len(value) > MAX_MORALIS_TRANSPORT_JSON_OBJECT_FIELDS:
            raise ValueError("transport JSON object cardinality exceeded")
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("transport JSON non-string object key")
            if len(key.encode("utf-8", errors="strict")) > (
                MAX_MORALIS_TRANSPORT_JSON_STRING_BYTES
            ):
                raise ValueError("transport JSON object-key byte limit exceeded")
            validate_transport_json(
                item,
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    raise TypeError(f"unsupported transport JSON type {type(value).__name__}")
