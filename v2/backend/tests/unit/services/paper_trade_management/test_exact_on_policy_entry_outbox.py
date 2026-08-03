from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from typing import Any

import pytest

from v2.backend.app.services.paper_trade_management.exact_on_policy_entry_outbox import (
    COMMIT_BINDING_SCHEMA_VERSION,
    ENTRY_EVENT_TYPE,
    LIFECYCLE_EVENT_SCHEMA_VERSION,
    PAPER_STATE_TRANSITION_SCHEMA_VERSION,
    STATE_COMMITTED,
    STATE_ENTRY_EVENT_APPENDED,
    STATE_PREPARED,
    STATE_TRANSITION_FIELD,
    STATE_TRANSITION_KIND,
    ExactOnPolicyEntryOutbox,
    ExactOnPolicyEntryOutboxError,
)


def _sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt(*, prediction_id: str = "prediction-1") -> dict[str, Any]:
    material = {
        "schema_version": "v2_test_exact_behavior_receipt_v1",
        "prediction_id": prediction_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": "2026-07-17T23:59:58Z",
        "available_at": "2026-07-17T23:59:59Z",
        "candle_close_time": "2026-07-17T23:59:57Z",
        "decision_time": "2026-07-18T00:00:00Z",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return {**material, "receipt_hash": _sha256(material)}


def _seal_state_transition(fill: dict[str, Any]) -> None:
    receipt_hash = str(fill["behavior_policy_receipt_hash"])
    accepted_delta = {"paper_fill_id": str(fill["intent_id"]), "insert": True}
    position_delta = {"symbol": fill["symbol"], "side": fill["side"]}
    margin_delta = {"paper_fill_id": str(fill["intent_id"]), "reserve": True}
    delta = {
        "transition_kind": STATE_TRANSITION_KIND,
        "paper_fill_id": str(fill["intent_id"]),
        "behavior_policy_receipt_hash": receipt_hash,
        "symbol": fill["symbol"],
        "side": fill["side"],
        "quantity": fill["quantity"],
        "fill_price": fill["fill_price"],
        "state_mutations": [
            {
                "state_component": "accepted_fill",
                "state_key": str(fill["intent_id"]),
                "operation": "INSERT",
                "canonical_delta": accepted_delta,
                "canonical_delta_sha256": _sha256(accepted_delta),
            },
            {
                "state_component": "open_position",
                "state_key": fill["symbol"],
                "operation": "INSERT",
                "canonical_delta": position_delta,
                "canonical_delta_sha256": _sha256(position_delta),
            },
            {
                "state_component": "margin_reservation",
                "state_key": str(fill["intent_id"]),
                "operation": "INSERT",
                "canonical_delta": margin_delta,
                "canonical_delta_sha256": _sha256(margin_delta),
            },
        ],
    }
    material = {
        "schema_version": PAPER_STATE_TRANSITION_SCHEMA_VERSION,
        "transition_kind": STATE_TRANSITION_KIND,
        "paper_fill_id": str(fill["intent_id"]),
        "behavior_policy_receipt_hash": receipt_hash,
        "canonical_state_owner": "paper_trade_management",
        "canonical_state_key": "paper-book:account-1",
        "prior_state_revision": 41,
        "prior_state_sha256": "d" * 64,
        "next_state_revision": 42,
        "next_state_sha256": "e" * 64,
        "canonical_state_delta_complete": True,
        "canonical_state_delta": delta,
        "canonical_state_delta_sha256": _sha256(delta),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    fill[STATE_TRANSITION_FIELD] = {
        **material,
        "contract_sha256": _sha256(material),
    }


def _sealed_fill(
    *,
    paper_fill_id: str = "paper-fill-1",
    prediction_id: str = "prediction-1",
) -> dict[str, Any]:
    receipt = _receipt(prediction_id=prediction_id)
    fill = {
        "intent_id": paper_fill_id,
        "prediction_id": prediction_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "decision_time": "2026-07-18T00:00:00Z",
        "paper_final_admission_decision_time": (
            "2026-07-18T00:00:00.500000Z"
        ),
        "fill_price_observed_at": "2026-07-18T00:00:00.750000Z",
        "entry_time": "2026-07-18T00:00:01Z",
        "execution_time": "2026-07-18T00:00:01Z",
        "paper_fill_materialized_at": "2026-07-18T00:00:01Z",
        "quantity": 0.01,
        "fill_price": 100_000.0,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "ppo_on_policy_entry_fields_present": True,
        "on_policy_action_receipt_prevalidated": True,
        "on_policy_action_receipt_valid": False,
        "behavior_policy_receipt_entry_event_pending": True,
        "behavior_policy_receipt_hash": receipt["receipt_hash"],
        "behavior_policy_receipt": receipt,
    }
    _seal_state_transition(fill)
    return fill


def _entry_binding(record) -> dict[str, Any]:
    fill = record.sealed_fill
    transition = fill[STATE_TRANSITION_FIELD]
    return {
        "paper_fill_id": record.paper_fill_id,
        "prediction_id": fill["prediction_id"],
        "symbol": fill["symbol"],
        "timeframe": fill["timeframe"],
        "decision_time": fill["decision_time"],
        "entry_time": fill["entry_time"],
        "execution_time": fill["execution_time"],
        "paper_fill_materialized_at": fill["paper_fill_materialized_at"],
        "behavior_policy_receipt_hash": record.receipt_hash,
        "entry_fee_schedule_evidence_sha256": "b" * 64,
        "exact_on_policy_entry_outbox_record_id": record.record_id,
        "sealed_fill_sha256": record.sealed_fill_sha256,
        "paper_state_transition_contract_sha256": transition[
            "contract_sha256"
        ],
    }


def _entry_event_hash(
    record,
    binding: dict[str, Any],
    *,
    recorded_at: str,
) -> str:
    return _sha256(
        {
            "schema_version": LIFECYCLE_EVENT_SCHEMA_VERSION,
            "receipt_hash": record.receipt_hash,
            "event_type": ENTRY_EVENT_TYPE,
            "recorded_at": recorded_at,
            "binding": binding,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )


def _mark_evented(
    outbox: ExactOnPolicyEntryOutbox,
    prepared,
    *,
    recorded_at: str = "2026-07-18T00:00:03Z",
):
    binding = _entry_binding(prepared)
    return outbox.mark_entry_event_appended(
        prepared.record_id,
        event_hash=_entry_event_hash(
            prepared,
            binding,
            recorded_at=recorded_at,
        ),
        binding=binding,
        recorded_at=recorded_at,
    )


def _commit_evidence(
    evented,
    *,
    state_materialized_at: str = "2026-07-18T00:00:03.500000Z",
) -> dict[str, Any]:
    transition = evented.sealed_fill[STATE_TRANSITION_FIELD]
    return {
        "record_id": evented.record_id,
        "paper_fill_id": evented.paper_fill_id,
        "behavior_policy_receipt_hash": evented.receipt_hash,
        "sealed_fill_sha256": evented.sealed_fill_sha256,
        "entry_event_hash": evented.entry_event_hash,
        "paper_state_transition_contract_sha256": transition[
            "contract_sha256"
        ],
        "canonical_state_delta_sha256": transition[
            "canonical_state_delta_sha256"
        ],
        "applied_prior_state_revision": transition["prior_state_revision"],
        "applied_prior_state_sha256": transition["prior_state_sha256"],
        "committed_state_revision": transition["next_state_revision"],
        "committed_state_sha256": transition["next_state_sha256"],
        "materialized_outbox_state": STATE_ENTRY_EVENT_APPENDED,
        "state_materialized": True,
        "state_readback_verified": True,
        "accepted_state_written": True,
        "open_or_terminal_state_written": True,
        "state_materialized_at": state_materialized_at,
    }


def test_outbox_recovers_prepared_and_event_appended_rows_across_reopen(
    tmp_path,
) -> None:
    path = tmp_path / "entry-outbox.sqlite3"
    outbox = ExactOnPolicyEntryOutbox(path)
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )

    assert prepared.state == STATE_PREPARED
    assert prepared.materialized_fill()["on_policy_action_receipt_valid"] is False
    assert outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:03Z",
    ) == prepared

    reopened = ExactOnPolicyEntryOutbox(path)
    assert reopened.pending() == [prepared]

    evented = _mark_evented(reopened, prepared)
    assert evented.state == STATE_ENTRY_EVENT_APPENDED
    materialized = evented.materialized_fill()
    assert materialized["on_policy_action_receipt_valid"] is True
    assert materialized["behavior_policy_receipt_entry_event_pending"] is False
    assert materialized[
        "behavior_policy_receipt_archive_entry_event_hash"
    ] == evented.entry_event_hash
    assert ExactOnPolicyEntryOutbox(path).pending() == [evented]


def test_outbox_commit_is_bound_idempotent_and_removes_pending_row(
    tmp_path,
) -> None:
    path = tmp_path / "entry-outbox.sqlite3"
    outbox = ExactOnPolicyEntryOutbox(path)
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    evented = _mark_evented(outbox, prepared)
    evidence = _commit_evidence(evented)

    committed = outbox.mark_committed(
        evented.record_id,
        commit_evidence=evidence,
        committed_at="2026-07-18T00:00:04Z",
    )
    assert committed.state == STATE_COMMITTED
    assert outbox.pending() == []
    assert ExactOnPolicyEntryOutbox(path).get(committed.record_id) == committed
    assert outbox.mark_committed(
        evented.record_id,
        commit_evidence=evidence,
        committed_at="2026-07-18T00:00:05Z",
    ) == committed


def test_outbox_rejects_fill_id_reuse_for_a_different_receipt(tmp_path) -> None:
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    conflicting = _sealed_fill(prediction_id="prediction-2")

    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_PAPER_FILL_ID_IMMUTABLE_CONFLICT",
    ):
        outbox.prepare(
            conflicting,
            prepared_at="2026-07-18T00:00:03Z",
        )

    with sqlite3.connect(outbox.path) as connection:
        indexes = connection.execute(
            "PRAGMA index_list('exact_entry_outbox')"
        ).fetchall()
    assert any(row[1] == "exact_entry_outbox_paper_fill_id_uq" and row[2] for row in indexes)


def test_outbox_rejects_mutation_of_one_receipt_or_lifecycle_transition(
    tmp_path,
) -> None:
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    changed = deepcopy(_sealed_fill())
    changed["quantity"] = 0.02
    _seal_state_transition(changed)
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_IMMUTABLE_PREPARE_CONFLICT",
    ):
        outbox.prepare(changed, prepared_at="2026-07-18T00:00:03Z")

    evented = _mark_evented(outbox, prepared)
    changed_binding = _entry_binding(prepared)
    changed_binding["additional_archive_evidence"] = "immutable-change"
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_ENTRY_EVENT_IMMUTABLE_CONFLICT",
    ):
        outbox.mark_entry_event_appended(
            prepared.record_id,
            event_hash=_entry_event_hash(
                prepared,
                changed_binding,
                recorded_at="2026-07-18T00:00:03Z",
            ),
            binding=changed_binding,
            recorded_at="2026-07-18T00:00:03Z",
        )

    evidence = _commit_evidence(evented)
    evidence["state_materialized"] = False
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_COMMIT_STATE_MATERIALIZED_NOT_TRUE",
    ):
        outbox.mark_committed(
            evented.record_id,
            commit_evidence=evidence,
            committed_at="2026-07-18T00:00:04Z",
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"routes_to_live": True}, "ROUTES_TO_LIVE_TRUE"),
        (
            {"entry_time": "2026-07-17T23:59:59Z"},
            "ENTRY_EXECUTION_MATERIALIZATION_TIME_MISMATCH",
        ),
        (
            {"execution_time": "2026-07-18T00:00:01"},
            "EXECUTION_TIME_MISSING",
        ),
        (
            {"behavior_policy_receipt_entry_event_pending": False},
            "ENTRY_EVENT_NOT_PENDING",
        ),
        (
            {"paper_fill_materialized_at": "2026-07-18T00:00:02Z"},
            "ENTRY_EXECUTION_MATERIALIZATION_TIME_MISMATCH",
        ),
        (
            {
                "paper_final_admission_decision_time": (
                    "2026-07-18T00:00:02Z"
                )
            },
            "FINAL_ADMISSION_TIME_AFTER_ENTRY_TIME",
        ),
        (
            {"fill_price_observed_at": "2026-07-18T00:00:02Z"},
            "FILL_PRICE_OBSERVATION_AFTER_ENTRY_TIME",
        ),
    ],
)
def test_outbox_prepare_fails_closed_on_unsafe_or_invalid_fill(
    tmp_path,
    mutation,
    match,
) -> None:
    fill = _sealed_fill()
    fill.update(mutation)
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    with pytest.raises(ExactOnPolicyEntryOutboxError, match=match):
        outbox.prepare(fill, prepared_at="2026-07-18T00:00:02Z")


def test_prepare_authenticates_receipt_content_and_feature_clock(tmp_path) -> None:
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    tampered = _sealed_fill()
    tampered["behavior_policy_receipt"]["symbol"] = "ETHUSDT"
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_BEHAVIOR_RECEIPT_CONTENT_HASH_MISMATCH",
    ):
        outbox.prepare(tampered, prepared_at="2026-07-18T00:00:02Z")

    future_available = _sealed_fill()
    receipt = future_available["behavior_policy_receipt"]
    receipt["available_at"] = "2026-07-18T00:00:00Z"
    material = dict(receipt)
    material.pop("receipt_hash")
    receipt["receipt_hash"] = _sha256(material)
    future_available["behavior_policy_receipt_hash"] = receipt["receipt_hash"]
    _seal_state_transition(future_available)
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="RECEIPT_AVAILABLE_AT_NOT_BEFORE_DECISION_TIME",
    ):
        outbox.prepare(
            future_available,
            prepared_at="2026-07-18T00:00:02Z",
        )


def test_prepare_requires_revision_bound_complete_economic_transition(
    tmp_path,
) -> None:
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    missing = _sealed_fill()
    missing.pop(STATE_TRANSITION_FIELD)
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_ECONOMIC_STATE_TRANSITION_MISSING",
    ):
        outbox.prepare(missing, prepared_at="2026-07-18T00:00:02Z")

    incomplete = _sealed_fill()
    contract = incomplete[STATE_TRANSITION_FIELD]
    contract["canonical_state_delta_complete"] = False
    material = dict(contract)
    material.pop("contract_sha256")
    contract["contract_sha256"] = _sha256(material)
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="CANONICAL_STATE_DELTA_NOT_DECLARED_COMPLETE",
    ):
        outbox.prepare(incomplete, prepared_at="2026-07-18T00:00:02Z")


def test_entry_event_and_commit_clocks_fail_closed(tmp_path) -> None:
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    binding = _entry_binding(prepared)
    too_early = "2026-07-18T00:00:01.500000Z"
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_ENTRY_EVENT_BEFORE_PREPARED_AT",
    ):
        outbox.mark_entry_event_appended(
            prepared.record_id,
            event_hash=_entry_event_hash(
                prepared,
                binding,
                recorded_at=too_early,
            ),
            binding=binding,
            recorded_at=too_early,
        )

    evented = _mark_evented(outbox, prepared)
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_COMMIT_BEFORE_ENTRY_EVENT",
    ):
        outbox.mark_committed(
            evented.record_id,
            commit_evidence=_commit_evidence(
                evented,
                state_materialized_at="2026-07-18T00:00:03Z",
            ),
            committed_at="2026-07-18T00:00:02.500000Z",
        )


@pytest.mark.parametrize(
    ("column", "value", "match"),
    [
        (
            "receipt_hash",
            "f" * 64,
            "OUTBOX_DATABASE_RECEIPT_HASH_BINDING_MISMATCH",
        ),
        (
            "paper_fill_id",
            "tampered-fill-id",
            "OUTBOX_DATABASE_PAPER_FILL_ID_BINDING_MISMATCH",
        ),
        (
            "prepared_at",
            "2026-07-18T00:00:02.500000Z",
            "OUTBOX_RECORD_ID_CONTENT_MISMATCH",
        ),
    ],
)
def test_restart_read_reauthenticates_database_identity_columns(
    tmp_path,
    column,
    value,
    match,
) -> None:
    path = tmp_path / "entry-outbox.sqlite3"
    outbox = ExactOnPolicyEntryOutbox(path)
    outbox.prepare(_sealed_fill(), prepared_at="2026-07-18T00:00:02Z")
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE exact_entry_outbox SET {column} = ?",  # noqa: S608
            (value,),
        )
    with pytest.raises(ExactOnPolicyEntryOutboxError, match=match):
        ExactOnPolicyEntryOutbox(path).pending()


def test_restart_read_reauthenticates_event_binding_and_hash(tmp_path) -> None:
    path = tmp_path / "entry-outbox.sqlite3"
    outbox = ExactOnPolicyEntryOutbox(path)
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    evented = _mark_evented(outbox, prepared)
    corrupted_binding = dict(evented.entry_event_binding or {})
    corrupted_binding["corrupt"] = True
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE exact_entry_outbox
            SET entry_event_binding_json = ?
            """,
            (json.dumps(corrupted_binding),),
        )
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_ENTRY_EVENT_CONTENT_HASH_MISMATCH",
    ):
        ExactOnPolicyEntryOutbox(path).pending()


def test_restart_read_reauthenticates_commit_evidence_and_clock(tmp_path) -> None:
    path = tmp_path / "entry-outbox.sqlite3"
    outbox = ExactOnPolicyEntryOutbox(path)
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    evented = _mark_evented(outbox, prepared)
    committed = outbox.mark_committed(
        evented.record_id,
        commit_evidence=_commit_evidence(evented),
        committed_at="2026-07-18T00:00:04Z",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE exact_entry_outbox
            SET committed_at = ?
            WHERE record_id = ?
            """,
            ("2026-07-18T00:00:05Z", committed.record_id),
        )
    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_COMMIT_EVIDENCE_HASH_MISMATCH",
    ):
        ExactOnPolicyEntryOutbox(path).get(committed.record_id)


def test_outbox_pending_limit_is_a_fail_closed_resource_bound(tmp_path) -> None:
    outbox = ExactOnPolicyEntryOutbox(tmp_path / "entry-outbox.sqlite3")
    outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    outbox.prepare(
        _sealed_fill(
            paper_fill_id="paper-fill-2",
            prediction_id="prediction-2",
        ),
        prepared_at="2026-07-18T00:00:03Z",
    )

    with pytest.raises(
        ExactOnPolicyEntryOutboxError,
        match="OUTBOX_PENDING_RESOURCE_BOUND_EXCEEDED",
    ):
        outbox.pending(limit=1)


def test_commit_binding_hash_includes_commit_clock(tmp_path) -> None:
    path = tmp_path / "entry-outbox.sqlite3"
    outbox = ExactOnPolicyEntryOutbox(path)
    prepared = outbox.prepare(
        _sealed_fill(),
        prepared_at="2026-07-18T00:00:02Z",
    )
    evented = _mark_evented(outbox, prepared)
    evidence = _commit_evidence(evented)
    committed = outbox.mark_committed(
        evented.record_id,
        commit_evidence=evidence,
        committed_at="2026-07-18T00:00:04Z",
    )
    expected = _sha256(
        {
            "schema_version": COMMIT_BINDING_SCHEMA_VERSION,
            "committed_at": "2026-07-18T00:00:04Z",
            "commit_evidence": evidence,
        }
    )
    assert committed.commit_evidence_sha256 == expected
