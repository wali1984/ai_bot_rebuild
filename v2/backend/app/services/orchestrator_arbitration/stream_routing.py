"""Static stream routing metadata (PaperOnly).

Mirrors the legacy ``rl/orchestrator_worker.py`` environment-driven mapping:

    SIGNAL_STREAM_PRIMARY = os.getenv(
        "ORCHESTRATOR_SIGNAL_STREAM_PRIMARY", "signals:trading:primary"
    )
    SIGNAL_STREAM_ASJAD = os.getenv(
        "ORCHESTRATOR_SIGNAL_STREAM_ASJAD", "signals:trading:asjad"
    )

The V2 paper-only port treats stream labels as informational metadata only:
no Redis client is constructed, no stream is opened, nothing is published.
The router simply answers "what label should we tag a paper-only arbitration
result with for downstream observability?".
"""
from __future__ import annotations

from typing import Dict, Mapping, Tuple


STREAM_LABEL_PRIMARY = "primary"
STREAM_LABEL_ASJAD = "asjad"
STREAM_LABEL_SHADOW = "shadow"

STREAM_LABEL_ALLOWED: Tuple[str, ...] = (
    STREAM_LABEL_PRIMARY,
    STREAM_LABEL_ASJAD,
    STREAM_LABEL_SHADOW,
)


class StreamRouter:
    """Map a symbol to a paper-only stream label."""

    def __init__(self, mapping: Mapping[str, str] | None = None) -> None:
        normalized: Dict[str, str] = {}
        if mapping is not None:
            if not isinstance(mapping, Mapping):
                raise TypeError("mapping must be a Mapping[str, str] or None")
            for raw_symbol, raw_label in mapping.items():
                if not isinstance(raw_symbol, str) or not raw_symbol.strip():
                    raise ValueError(
                        "stream router symbol keys must be non-empty strings"
                    )
                if not isinstance(raw_label, str) or raw_label not in STREAM_LABEL_ALLOWED:
                    raise ValueError(
                        "stream router labels must be one of "
                        f"{STREAM_LABEL_ALLOWED}"
                    )
                normalized[raw_symbol.strip().upper()] = raw_label
        self._mapping: Dict[str, str] = normalized

    def route_for(self, symbol: str) -> str:
        if not isinstance(symbol, str) or not symbol.strip():
            return STREAM_LABEL_SHADOW
        return self._mapping.get(symbol.strip().upper(), STREAM_LABEL_SHADOW)

    def mapping_snapshot(self) -> Dict[str, str]:
        return dict(self._mapping)

    def allowed_labels(self) -> Tuple[str, ...]:
        return STREAM_LABEL_ALLOWED
