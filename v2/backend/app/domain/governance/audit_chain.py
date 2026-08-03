from __future__ import annotations

import hashlib
import json
from typing import Any


def chain_local_paper_audit_event(
    event: dict[str, Any],
    *,
    existing_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prev = (existing_events or [])
    prev_hash = prev[0].get("event_hash", "") if prev else ""
    payload = json.dumps(event, sort_keys=True, default=str)
    event_hash = hashlib.sha256((prev_hash + payload).encode()).hexdigest()
    return {
        **event,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "previous_event_hash": prev_hash,
        "chain_seq": len(prev),
        "tamper_evident": True,
    }


def verify_local_paper_audit_chain(
    events: list[dict[str, Any]],
    *,
    expected_event_count: int,
) -> dict[str, Any]:
    actual_count = len(events)
    count_match = actual_count == expected_event_count
    link_mismatch_count = 0
    hash_mismatch_count = 0
    for index, event in enumerate(events):
        if not isinstance(event.get("event_hash"), str) or not event.get("event_hash"):
            hash_mismatch_count += 1
        if index + 1 < len(events):
            previous = events[index + 1]
            if event.get("previous_event_hash") != previous.get("event_hash"):
                link_mismatch_count += 1
        elif event.get("previous_event_hash", "") not in {"", None}:
            link_mismatch_count += 1
    verified = count_match and actual_count > 0 and link_mismatch_count == 0 and hash_mismatch_count == 0
    return {
        "valid": verified,
        "verified": verified,
        "window_complete": count_match,
        "event_count": actual_count,
        "expected_event_count": expected_event_count,
        "count_match": count_match,
        "chain_verified": verified,
        "link_mismatch_count": link_mismatch_count,
        "hash_mismatch_count": hash_mismatch_count,
        "verification_note": "Local paper audit hash-chain window verified." if verified else "Local paper audit chain verification failed or is incomplete.",
    }


def local_paper_audit_policy_metadata(
    *,
    event_count: int,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    has_events = event_count > 0
    tamper_evident = has_events and all(
        isinstance(event, dict)
        and event.get("tamper_evident") is True
        and isinstance(event.get("event_hash"), str)
        and bool(event.get("event_hash"))
        for event in (events or [])
    )
    return {
        "policy_kind": "local_paper_audit_policy",
        "mode": "paper",
        "live_trading_blocked": True,
        "event_count": event_count,
        "has_events": has_events,
        "tamper_evident": tamper_evident,
        "audit_source": "local_paper_ledger",
        "production_durable_store": False,
        "live_mutation_prohibited": True,
        "chain_integrity": verify_local_paper_audit_chain(events or [], expected_event_count=event_count),
        "policy_status": "active" if has_events else "empty",
        "warnings": (
            ["Paper audit policy is local-only; durable audit storage is not yet wired."]
            if not has_events
            else []
        ),
        "missing_fields": [] if has_events else ["audit_events"],
    }
