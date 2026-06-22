"""V2 native paper-only proposal bus (no legacy Redis).

Pure stdlib in-process FIFO bus with V2 namespace + duplicate
rejection + stale rejection. NEVER writes to legacy Redis. NEVER
calls an exchange SDK.

Legacy citation:

- v2/legacy_owned_runtime/rl/proposal_bus.py
    sha256=e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Optional

from .proposal import DEFAULT_MAX_AGE_SECONDS, Proposal

LEGACY_PROPOSAL_BUS_SHA256 = "e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d"

PROPOSAL_BUS_NAMESPACE = "v2_native_proposal_bus"
PROPOSAL_BUS_SCHEMA_VERSION = "v2_native_proposal_bus_v1"


@dataclass(frozen=True)
class ProposalBusAccepted:
    proposal_id: str
    accepted_at_utc: str


@dataclass(frozen=True)
class ProposalBusRejected:
    proposal_id: str
    reason: str  # DUPLICATE | STALE | INVALID


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class V2NativeProposalBus:
    """In-process bus. No Redis. No exchange. No live."""

    def __init__(self, *, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS, capacity: int = 256) -> None:
        self._namespace = PROPOSAL_BUS_NAMESPACE
        self._max_age_seconds = int(max_age_seconds)
        self._seen_ids: set[str] = set()
        self._queue: Deque[Proposal] = deque(maxlen=int(capacity))
        self._accepted: list[ProposalBusAccepted] = []
        self._rejected: list[ProposalBusRejected] = []

    @property
    def namespace(self) -> str:
        return self._namespace

    def publish(self, proposal: Proposal) -> ProposalBusAccepted | ProposalBusRejected:
        if not proposal.proposal_id or not proposal.symbol or not proposal.side:
            r = ProposalBusRejected(proposal_id=proposal.proposal_id or "", reason="INVALID")
            self._rejected.append(r)
            return r
        if proposal.proposal_id in self._seen_ids:
            r = ProposalBusRejected(proposal_id=proposal.proposal_id, reason="DUPLICATE")
            self._rejected.append(r)
            return r
        if proposal.freshness_seconds > self._max_age_seconds:
            r = ProposalBusRejected(proposal_id=proposal.proposal_id, reason="STALE")
            self._rejected.append(r)
            return r
        self._seen_ids.add(proposal.proposal_id)
        self._queue.append(proposal)
        a = ProposalBusAccepted(proposal_id=proposal.proposal_id, accepted_at_utc=_utc_iso())
        self._accepted.append(a)
        return a

    def drain(self) -> list[Proposal]:
        out = list(self._queue)
        self._queue.clear()
        return out

    def status(self) -> dict:
        return {
            "namespace": self._namespace,
            "schema_version": PROPOSAL_BUS_SCHEMA_VERSION,
            "max_age_seconds": self._max_age_seconds,
            "accepted_count": len(self._accepted),
            "rejected_count": len(self._rejected),
            "rejected_reasons": [r.reason for r in self._rejected],
            "current_queue_depth": len(self._queue),
            "legacy_proposal_bus_sha256": LEGACY_PROPOSAL_BUS_SHA256,
            "imports_redis": False,
            "imports_exchange_sdk": False,
            "writes_legacy_redis": False,
            "places_exchange_orders": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
        }
