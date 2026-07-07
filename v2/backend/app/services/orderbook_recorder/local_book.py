"""Local orderbook maintenance with sequence-gap detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import build_orderbook_payloads, normalize_levels


@dataclass
class LocalOrderBook:
    exchange: str
    symbol: str
    depth_limit: int = 500
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_sequence_id: int | None = None
    last_sequence_source: str | None = None
    sequence_gap_count: int = 0
    last_sequence_gap: bool = False
    snapshot_count: int = 0
    delta_count: int = 0

    def apply_snapshot(
        self,
        *,
        bids: Any,
        asks: Any,
        sequence_id: Any = None,
    ) -> None:
        self.bids = {row["price"]: row["quantity"] for row in normalize_levels(bids, limit=self.depth_limit) if row["quantity"] > 0}
        self.asks = {row["price"]: row["quantity"] for row in normalize_levels(asks, limit=self.depth_limit) if row["quantity"] > 0}
        parsed_sequence = _int_or_none(sequence_id)
        if parsed_sequence is not None:
            self.last_sequence_id = parsed_sequence
            self.last_sequence_source = "snapshot"
        self.last_sequence_gap = False
        self.snapshot_count += 1

    def apply_absolute_delta(
        self,
        *,
        bids: Any,
        asks: Any,
        first_sequence_id: Any = None,
        final_sequence_id: Any = None,
        previous_sequence_id: Any = None,
    ) -> bool:
        first_id = _int_or_none(first_sequence_id)
        final_id = _int_or_none(final_sequence_id)
        previous_id = _int_or_none(previous_sequence_id)
        gap = False
        if self.last_sequence_id is not None:
            if previous_id is not None and previous_id != self.last_sequence_id:
                snapshot_bridge = (
                    self.last_sequence_source == "snapshot"
                    and first_id is not None
                    and final_id is not None
                    and first_id <= self.last_sequence_id + 1 <= final_id
                )
                gap = not snapshot_bridge
            elif previous_id is None and first_id is not None and first_id > self.last_sequence_id + 1:
                gap = True
        if gap:
            self.sequence_gap_count += 1
        self.last_sequence_gap = gap
        self._apply_side(self.bids, bids)
        self._apply_side(self.asks, asks)
        if final_id is not None:
            self.last_sequence_id = final_id
            self.last_sequence_source = "delta"
        self.delta_count += 1
        self._trim()
        return gap

    def apply_top_of_book(self, *, bids: Any, asks: Any) -> None:
        """Update best levels without clearing the maintained depth book."""
        normalized_bids = normalize_levels(bids, limit=None)
        normalized_asks = normalize_levels(asks, limit=None)
        if normalized_bids:
            best_bid = max(row["price"] for row in normalized_bids)
            for price in [price for price in self.bids if price > best_bid]:
                self.bids.pop(price, None)
        if normalized_asks:
            best_ask = min(row["price"] for row in normalized_asks)
            for price in [price for price in self.asks if price < best_ask]:
                self.asks.pop(price, None)
        self._apply_side(self.bids, normalized_bids)
        self._apply_side(self.asks, normalized_asks)
        self.last_sequence_gap = False
        self.delta_count += 1
        self._trim()

    def top_levels(self) -> tuple[list[list[float]], list[list[float]]]:
        bids = [[price, qty] for price, qty in sorted(self.bids.items(), key=lambda item: item[0], reverse=True)]
        asks = [[price, qty] for price, qty in sorted(self.asks.items(), key=lambda item: item[0])]
        return bids[: self.depth_limit], asks[: self.depth_limit]

    def payloads(
        self,
        *,
        event_time_ms: Any = None,
        transaction_time_ms: Any = None,
        received_at: str | None = None,
        available_at: str | None = None,
        sequence_id: Any = None,
        previous_sequence_id: Any = None,
        source_latency_ms: float | None = None,
        update_type: str = "delta",
        depth_level: Any = None,
        feed_speed_ms: Any = None,
    ) -> dict[str, dict[str, Any]]:
        bids, asks = self.top_levels()
        return build_orderbook_payloads(
            exchange=self.exchange,
            symbol=self.symbol,
            bids=bids,
            asks=asks,
            event_time_ms=event_time_ms,
            transaction_time_ms=transaction_time_ms,
            received_at=received_at,
            available_at=available_at,
            sequence_id=sequence_id if sequence_id is not None else self.last_sequence_id,
            previous_sequence_id=previous_sequence_id,
            sequence_gap=self.last_sequence_gap,
            source_latency_ms=source_latency_ms,
            update_type=update_type,
            depth_level=depth_level,
            feed_speed_ms=feed_speed_ms,
            depth_limit=self.depth_limit,
        )

    def _apply_side(self, book: dict[float, float], rows: Any) -> None:
        for row in normalize_levels(rows, limit=None):
            price = row["price"]
            qty = row["quantity"]
            if qty <= 0:
                book.pop(price, None)
            else:
                book[price] = qty

    def _trim(self) -> None:
        self.bids = dict(sorted(self.bids.items(), key=lambda item: item[0], reverse=True)[: self.depth_limit])
        self.asks = dict(sorted(self.asks.items(), key=lambda item: item[0])[: self.depth_limit])


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
