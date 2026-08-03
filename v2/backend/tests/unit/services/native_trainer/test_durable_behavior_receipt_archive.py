from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_ENTRY_ACCEPTED,
    EVENT_NO_ENTRY_FINALIZED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_PUBLISHED,
    EVENT_TRAINER_CONSUMED,
    BehaviorReceiptArchiveError,
    append_lifecycle_event,
    archive_behavior_receipt,
    build_no_entry_terminal_binding,
    canonical_sha256,
    load_behavior_receipt,
    receipt_lifecycle_status,
)

DECISION_TIME = "2026-07-18T00:00:00Z"
ENTRY_TIME = "2026-07-18T00:01:00Z"
OUTCOME_AVAILABLE_AT = "2026-07-18T00:02:00Z"
LEDGER_RECORDED_UTC = "2026-07-18T00:03:00Z"


def _receipt() -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "unit_exact_receipt_v1",
        "prediction_id": "pred-1",
        "symbol": "BTCUSDT",
        "decision_time": DECISION_TIME,
        "selected_action": "long",
        "paper_only": True,
        "routes_to_live": False,
    }
    receipt["receipt_hash"] = canonical_sha256(receipt)
    return receipt


def _published_binding(*, prediction_id: str = "pred-1") -> dict[str, str]:
    return {
        "prediction_id": prediction_id,
        "decision_time": DECISION_TIME,
    }


def _entry_binding(*, fill_id: str = "fill-1") -> dict[str, str]:
    return {
        "paper_fill_id": fill_id,
        "decision_time": DECISION_TIME,
        "entry_time": ENTRY_TIME,
    }


def _outcome_binding() -> dict[str, str]:
    return {
        "finalized_outcome_id": "outcome-1",
        "finalized_outcome_digest": "d" * 64,
        "ppo_consumption_update_key": "a" * 64,
        "outcome_available_at": OUTCOME_AVAILABLE_AT,
    }


def _binding_for_event(event_type: str) -> dict[str, object]:
    if event_type == EVENT_PUBLISHED:
        return _published_binding()
    if event_type == EVENT_ENTRY_ACCEPTED:
        return _entry_binding()
    if event_type == EVENT_OUTCOME_FINALIZED:
        return _outcome_binding()
    if event_type == EVENT_TRAINER_CONSUMED:
        return {
            "ppo_consumption_update_key": "a" * 64,
            "ledger_recorded_utc": LEDGER_RECORDED_UTC,
        }
    raise AssertionError(event_type)


def _recorded_at_for_event(event_type: str) -> str:
    return {
        EVENT_PUBLISHED: DECISION_TIME,
        EVENT_ENTRY_ACCEPTED: ENTRY_TIME,
        EVENT_OUTCOME_FINALIZED: OUTCOME_AVAILABLE_AT,
        EVENT_TRAINER_CONSUMED: LEDGER_RECORDED_UTC,
    }[event_type]


def _append_valid_prefix(
    *,
    receipt_hash: str,
    before_event_type: str,
    root: Path,
) -> None:
    for event_type in (
        EVENT_PUBLISHED,
        EVENT_ENTRY_ACCEPTED,
        EVENT_OUTCOME_FINALIZED,
        EVENT_TRAINER_CONSUMED,
    ):
        if event_type == before_event_type:
            return
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=event_type,
            binding=_binding_for_event(event_type),
            root=root,
            recorded_at=_recorded_at_for_event(event_type),
        )
    raise AssertionError(before_event_type)


def _rewrite_self_consistent_event(
    path: Path,
    *,
    binding_updates: dict[str, object],
) -> Path:
    row = json.loads(path.read_text(encoding="utf-8"))
    row.pop("event_hash")
    row["binding"].update(binding_updates)
    event_hash = canonical_sha256(row)
    row["event_hash"] = event_hash
    rewritten = path.with_name(f"{event_hash}.json")
    path.unlink()
    rewritten.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return rewritten


def test_receipt_lifecycle_is_durable_idempotent_and_retained_until_consumed(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])

    first = archive_behavior_receipt(receipt, root=tmp_path)
    second = archive_behavior_receipt(receipt, root=tmp_path)
    assert first.already_present is False
    assert second.already_present is True
    assert load_behavior_receipt(receipt_hash, root=tmp_path) == receipt

    published = append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )
    entry = append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding=_entry_binding(),
        root=tmp_path,
        recorded_at=ENTRY_TIME,
    )
    finalized = append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_OUTCOME_FINALIZED,
        binding=_outcome_binding(),
        root=tmp_path,
        recorded_at=OUTCOME_AVAILABLE_AT,
    )
    assert published.event_hash and entry.event_hash and finalized.event_hash
    before = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert before["outcome_finalized_durable"] is True
    assert before["trainer_consumed_durable"] is False
    assert before["retention_required"] is True

    consumed = append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_TRAINER_CONSUMED,
        binding={
            "ppo_consumption_update_key": "a" * 64,
            "ledger_recorded_utc": LEDGER_RECORDED_UTC,
        },
        root=tmp_path,
        recorded_at=LEDGER_RECORDED_UTC,
    )
    duplicate = append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_TRAINER_CONSUMED,
        binding={
            "ppo_consumption_update_key": "a" * 64,
            "ledger_recorded_utc": LEDGER_RECORDED_UTC,
        },
        root=tmp_path,
        recorded_at=LEDGER_RECORDED_UTC,
    )
    assert duplicate.already_present is True
    assert duplicate.event_hash == consumed.event_hash
    after = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert after["trainer_consumed_durable"] is True
    assert after["retention_required"] is False


def test_legacy_missing_archive_and_out_of_order_lifecycle_fail_closed(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    with pytest.raises(BehaviorReceiptArchiveError, match="ARCHIVED_RECEIPT_MISSING"):
        load_behavior_receipt(receipt_hash, root=tmp_path)

    archive_behavior_receipt(receipt, root=tmp_path)
    with pytest.raises(
        BehaviorReceiptArchiveError, match="LIFECYCLE_PREREQUISITE_MISSING"
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_ENTRY_ACCEPTED,
            binding={"paper_fill_id": "fill-1"},
            root=tmp_path,
        )


def test_lifecycle_recorded_times_cannot_move_backwards_in_event_order(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at="2026-07-18T00:02:00Z",
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_TEMPORAL_ORDER_INVALID",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_ENTRY_ACCEPTED,
            binding=_entry_binding(),
            root=tmp_path,
            recorded_at="2026-07-18T00:01:00Z",
        )


def test_read_rejects_self_consistent_backdated_lifecycle_journal(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at="2026-07-18T00:02:00Z",
    )
    entry = append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding=_entry_binding(),
        root=tmp_path,
        recorded_at="2026-07-18T00:03:00Z",
    )
    row = json.loads(entry.event_path.read_text(encoding="utf-8"))
    row.pop("event_hash")
    row["recorded_at"] = "2026-07-18T00:01:00Z"
    backdated_hash = canonical_sha256(row)
    row["event_hash"] = backdated_hash
    backdated_path = entry.event_path.with_name(f"{backdated_hash}.json")
    entry.event_path.unlink()
    backdated_path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_TEMPORAL_ORDER_INVALID",
    ):
        receipt_lifecycle_status(receipt_hash, root=tmp_path)


def test_entry_recorded_time_cannot_predate_bound_decision_or_entry_time(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding={
            "prediction_id": "pred-1",
            "decision_time": DECISION_TIME,
        },
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_RECORDED_AT_BEFORE_SEMANTIC_TIME",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_ENTRY_ACCEPTED,
            binding={
                "paper_fill_id": "fill-1",
                "decision_time": DECISION_TIME,
                "entry_time": "2026-07-18T00:02:00Z",
            },
            root=tmp_path,
            recorded_at="2026-07-18T00:01:30Z",
        )


def test_outcome_recorded_time_requires_and_cannot_predate_availability(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding=_entry_binding(),
        root=tmp_path,
        recorded_at=ENTRY_TIME,
    )
    outcome_binding = {
        "finalized_outcome_id": "outcome-1",
        "finalized_outcome_digest": "d" * 64,
        "ppo_consumption_update_key": "a" * 64,
    }

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_SEMANTIC_TIME_MISSING",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_OUTCOME_FINALIZED,
            binding=outcome_binding,
            root=tmp_path,
            recorded_at="2026-07-18T00:02:00Z",
        )
    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_RECORDED_AT_BEFORE_SEMANTIC_TIME",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_OUTCOME_FINALIZED,
            binding={
                **outcome_binding,
                "outcome_available_at": "2026-07-18T00:03:00Z",
            },
            root=tmp_path,
            recorded_at="2026-07-18T00:02:00Z",
        )


def test_trainer_consumed_time_cannot_predate_bound_ledger_time(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding=_entry_binding(),
        root=tmp_path,
        recorded_at=ENTRY_TIME,
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_OUTCOME_FINALIZED,
        binding=_outcome_binding(),
        root=tmp_path,
        recorded_at=OUTCOME_AVAILABLE_AT,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_RECORDED_AT_BEFORE_SEMANTIC_TIME",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_TRAINER_CONSUMED,
            binding={
                "ppo_consumption_update_key": "a" * 64,
                "ledger_recorded_utc": "2026-07-18T00:04:00Z",
            },
            root=tmp_path,
            recorded_at="2026-07-18T00:03:00Z",
        )


@pytest.mark.parametrize(
    ("event_type", "semantic_field"),
    (
        (EVENT_PUBLISHED, "decision_time"),
        (EVENT_ENTRY_ACCEPTED, "decision_time"),
        (EVENT_ENTRY_ACCEPTED, "entry_time"),
        (EVENT_OUTCOME_FINALIZED, "outcome_available_at"),
        (EVENT_TRAINER_CONSUMED, "ledger_recorded_utc"),
    ),
)
@pytest.mark.parametrize(
    ("invalid_value", "expected_error"),
    (
        (None, "LIFECYCLE_EVENT_SEMANTIC_TIME_MISSING"),
        ("2026-07-18T00:00:00", "LIFECYCLE_EVENT_SEMANTIC_TIME_INVALID"),
        ("not-a-clock", "LIFECYCLE_EVENT_SEMANTIC_TIME_INVALID"),
    ),
)
def test_every_lifecycle_semantic_clock_is_required_strict_and_aware(
    tmp_path: Path,
    event_type: str,
    semantic_field: str,
    invalid_value: object,
    expected_error: str,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    _append_valid_prefix(
        receipt_hash=receipt_hash,
        before_event_type=event_type,
        root=tmp_path,
    )
    binding = _binding_for_event(event_type)
    binding[semantic_field] = invalid_value

    with pytest.raises(BehaviorReceiptArchiveError, match=expected_error):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=event_type,
            binding=binding,
            root=tmp_path,
            recorded_at="2026-07-18T00:04:00Z",
        )


@pytest.mark.parametrize(
    ("recorded_at", "expected_error"),
    (
        ("2026-07-18T00:00:00", "LIFECYCLE_RECORDED_AT_INVALID"),
        ("not-a-clock", "LIFECYCLE_RECORDED_AT_INVALID"),
        ("2026-07-17T23:59:59Z", "LIFECYCLE_EVENT_RECORDED_AT_BEFORE_SEMANTIC_TIME"),
    ),
)
def test_lifecycle_recorded_at_is_strict_and_not_before_own_semantic_clock(
    tmp_path: Path,
    recorded_at: str,
    expected_error: str,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)

    with pytest.raises(BehaviorReceiptArchiveError, match=expected_error):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_PUBLISHED,
            binding=_published_binding(),
            root=tmp_path,
            recorded_at=recorded_at,
        )


def test_entry_decision_time_must_bind_published_decision_time_exactly(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_ENTRY_DECISION_TIME_BINDING_MISMATCH",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_ENTRY_ACCEPTED,
            binding={
                **_entry_binding(),
                "decision_time": "2026-07-18T00:00:01Z",
            },
            root=tmp_path,
            recorded_at=ENTRY_TIME,
        )


@pytest.mark.parametrize(
    ("event_type", "binding"),
    (
        (
            EVENT_ENTRY_ACCEPTED,
            {
                **_entry_binding(),
                "entry_time": "2026-07-17T23:59:59Z",
            },
        ),
        (
            EVENT_OUTCOME_FINALIZED,
            {
                **_outcome_binding(),
                "outcome_available_at": "2026-07-18T00:00:30Z",
            },
        ),
        (
            EVENT_TRAINER_CONSUMED,
            {
                "ppo_consumption_update_key": "a" * 64,
                "ledger_recorded_utc": "2026-07-18T00:01:30Z",
            },
        ),
    ),
)
def test_cross_event_semantic_clock_inversions_fail_closed_on_append(
    tmp_path: Path,
    event_type: str,
    binding: dict[str, object],
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    _append_valid_prefix(
        receipt_hash=receipt_hash,
        before_event_type=event_type,
        root=tmp_path,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="LIFECYCLE_EVENT_SEMANTIC_ORDER_INVALID",
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=event_type,
            binding=binding,
            root=tmp_path,
            recorded_at="2026-07-18T00:04:00Z",
        )


@pytest.mark.parametrize(
    ("event_type", "binding_updates", "expected_error"),
    (
        (
            EVENT_ENTRY_ACCEPTED,
            {"decision_time": "2026-07-18T00:00:01Z"},
            "LIFECYCLE_ENTRY_DECISION_TIME_BINDING_MISMATCH",
        ),
        (
            EVENT_OUTCOME_FINALIZED,
            {"outcome_available_at": "2026-07-18T00:00:30Z"},
            "LIFECYCLE_EVENT_SEMANTIC_ORDER_INVALID",
        ),
        (
            EVENT_TRAINER_CONSUMED,
            {"ledger_recorded_utc": "2026-07-18T00:03:00"},
            "LIFECYCLE_EVENT_SEMANTIC_TIME_INVALID",
        ),
    ),
)
def test_disk_read_revalidates_semantic_identity_clocks_and_causal_order(
    tmp_path: Path,
    event_type: str,
    binding_updates: dict[str, object],
    expected_error: str,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    writes = {}
    for current_event_type in (
        EVENT_PUBLISHED,
        EVENT_ENTRY_ACCEPTED,
        EVENT_OUTCOME_FINALIZED,
        EVENT_TRAINER_CONSUMED,
    ):
        writes[current_event_type] = append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=current_event_type,
            binding=_binding_for_event(current_event_type),
            root=tmp_path,
            recorded_at=_recorded_at_for_event(current_event_type),
        )
    _rewrite_self_consistent_event(
        writes[event_type].event_path,
        binding_updates=binding_updates,
    )

    with pytest.raises(BehaviorReceiptArchiveError, match=expected_error):
        receipt_lifecycle_status(receipt_hash, root=tmp_path)


def test_tampered_receipt_and_conflicting_lifecycle_identity_fail_closed(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )
    with pytest.raises(
        BehaviorReceiptArchiveError, match="LIFECYCLE_EVENT_BINDING_CONFLICT"
    ):
        append_lifecycle_event(
            receipt_hash=receipt_hash,
            event_type=EVENT_PUBLISHED,
            binding=_published_binding(prediction_id="pred-2"),
            root=tmp_path,
            recorded_at=DECISION_TIME,
        )

    tampered = deepcopy(receipt)
    tampered["symbol"] = "ETHUSDT"
    with pytest.raises(
        BehaviorReceiptArchiveError, match="RECEIPT_HASH_CONTENT_MISMATCH"
    ):
        archive_behavior_receipt(tampered, root=tmp_path)


def test_concurrent_conflicting_entry_events_are_serialized_fail_closed(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )

    def attempt(fill_id: str) -> str:
        try:
            append_lifecycle_event(
                receipt_hash=receipt_hash,
                event_type=EVENT_ENTRY_ACCEPTED,
                binding=_entry_binding(fill_id=fill_id),
                root=tmp_path,
                recorded_at=ENTRY_TIME,
            )
        except BehaviorReceiptArchiveError as exc:
            return str(exc)
        return "WRITTEN"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("fill-a", "fill-b")))

    assert results.count("WRITTEN") == 1
    assert results.count("LIFECYCLE_EVENT_BINDING_CONFLICT") == 1
    status = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert status["event_types"].count(EVENT_ENTRY_ACCEPTED) == 1


def test_sampled_hold_terminalization_wins_over_invalid_entry_attempt(
    tmp_path: Path,
) -> None:
    receipt = _receipt()
    receipt["selected_action"] = "hold"
    receipt.pop("receipt_hash")
    receipt["receipt_hash"] = canonical_sha256(receipt)
    receipt_hash = str(receipt["receipt_hash"])
    archive_behavior_receipt(receipt, root=tmp_path)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding=_published_binding(),
        root=tmp_path,
        recorded_at=DECISION_TIME,
    )

    def accept_entry() -> str:
        try:
            append_lifecycle_event(
                receipt_hash=receipt_hash,
                event_type=EVENT_ENTRY_ACCEPTED,
                binding=_entry_binding(),
                root=tmp_path,
                recorded_at=ENTRY_TIME,
            )
        except BehaviorReceiptArchiveError as exc:
            return str(exc)
        return EVENT_ENTRY_ACCEPTED

    def reject_entry() -> str:
        try:
            append_lifecycle_event(
                receipt_hash=receipt_hash,
                event_type=EVENT_NO_ENTRY_FINALIZED,
                binding=build_no_entry_terminal_binding(
                    prediction_id="pred-1",
                    decision_time=DECISION_TIME,
                    disposition_available_at=ENTRY_TIME,
                    terminal_disposition="SAMPLED_HOLD_FINALIZED",
                    reason_codes=["SAMPLED_HOLD"],
                ),
                root=tmp_path,
                recorded_at=ENTRY_TIME,
            )
        except BehaviorReceiptArchiveError as exc:
            return str(exc)
        return EVENT_NO_ENTRY_FINALIZED

    with ThreadPoolExecutor(max_workers=2) as executor:
        accepted_future = executor.submit(accept_entry)
        rejected_future = executor.submit(reject_entry)
        results = [accepted_future.result(), rejected_future.result()]

    entry_errors = {
        "LIFECYCLE_ENTRY_RECEIPT_BINDING_MISMATCH",
        "LIFECYCLE_TERMINAL_PATH_CONFLICT",
    }
    assert sum(result in entry_errors for result in results) == 1
    assert results.count(EVENT_NO_ENTRY_FINALIZED) == 1
    status = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert status["entry_accepted_durable"] is False
    assert status["no_entry_finalized_durable"] is True
