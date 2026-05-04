from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StreamLatestIdReader(Protocol):
    def latest_stream_id(self, stream_name: str) -> str | None:
        ...
