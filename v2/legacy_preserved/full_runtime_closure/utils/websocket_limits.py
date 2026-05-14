"""Shared websocket rate limiting utilities for Binance/CCXT clients."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

_DEFAULT_MAX_STREAMS = int(
    ("1024")
)
_DEFAULT_MAX_CONNECTIONS = int("300")
_DEFAULT_WINDOW_SECONDS = int("300")


@dataclass(frozen=True)
class WebSocketLimitConfig:
    """Configuration for websocket stream and connection limiting."""

    max_streams: int = _DEFAULT_MAX_STREAMS
    max_connections: int = _DEFAULT_MAX_CONNECTIONS
    window_seconds: int = _DEFAULT_WINDOW_SECONDS


class WebSocketLimiter:
    """Track websocket connection attempts to stay under Binance quotas.

    The limiter supports both synchronous and asynchronous acquisition. Each
    call to :meth:`acquire_sync` or :meth:`acquire_async` records a connection
    attempt. If the number of attempts within ``window_seconds`` would exceed
    ``max_connections`` the call will block (or await) until it is safe to
    continue.
    """

    def __init__(self, config: WebSocketLimitConfig | None = None, *, logger: logging.Logger | None = None) -> None:
        self._config = config or WebSocketLimitConfig()
        self._logger = logger or logging.getLogger(__name__)
        self._attempts: deque[float] = deque()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def config(self) -> WebSocketLimitConfig:
        return self._config

    def validate_stream_count(self, stream_count: int, *, context: str | None = None) -> None:
        """Ensure a connection does not subscribe to more than ``max_streams``.

        Args:
            stream_count: Number of requested streams for a websocket
                connection.
            context: Optional label for log messages (e.g. ``"klines"``).

        Raises:
            ValueError: if ``stream_count`` exceeds ``max_streams``.
        """

        if stream_count <= 0:
            return

        max_streams = self._config.max_streams
        if stream_count > max_streams:
            label = f" ({context})" if context else ""
            raise ValueError(
                f"Requested {stream_count} websocket streams{label} exceeds configured limit of {max_streams}."
            )

        # Log when approaching 90% of the limit – helpful for future tuning
        threshold = max_streams * 0.9
        if stream_count >= threshold:
            label = f" for {context}" if context else ""
            self._logger.warning(
                "⚠️ High websocket stream count%s: %s/%s", label, stream_count, max_streams
            )

    def acquire_sync(self) -> None:
        """Block the current thread until a connection slot is available."""

        while True:
            with self._lock:
                sleep_for = self._maybe_register_attempt(time.monotonic())
                if sleep_for is None:
                    return
            time.sleep(sleep_for)

    async def acquire_async(self) -> None:
        """Await until a connection slot is available in an async context."""

        while True:
            with self._lock:
                sleep_for = self._maybe_register_attempt(time.monotonic())
                if sleep_for is None:
                    return
            await asyncio.sleep(sleep_for)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _maybe_register_attempt(self, now: float) -> float | None:
        """Register a connection attempt or return required sleep time."""

        attempts = self._attempts
        window = self._config.window_seconds

        # Drop attempts outside the rolling window
        while attempts and now - attempts[0] > window:
            attempts.popleft()

        if len(attempts) < self._config.max_connections:
            attempts.append(now)
            return None

        # When limit hit, compute sleep time until the oldest attempt expires
        wait_time = window - (now - attempts[0]) + 0.01
        if wait_time < 0.05:
            wait_time = 0.05
        self._logger.debug(
            "Websocket connection limit reached (%s attempts in %ss window); throttling for %.2fs",
            len(attempts),
            window,
            wait_time,
        )
        return wait_time


__all__ = ["WebSocketLimiter", "WebSocketLimitConfig"]
