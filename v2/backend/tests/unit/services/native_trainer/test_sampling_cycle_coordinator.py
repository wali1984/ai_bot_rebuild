from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import traceback
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    U53_DENOMINATOR,
    sampling_plan_instance_id,
)
from v2.backend.app.services.native_trainer.sampling_cycle_coordinator import (
    CARRY_HEAD_TRANSITION_SCHEMA_VERSION,
    CYCLE_PREPARATION_SCHEMA_VERSION,
    MAX_COORDINATOR_JSON_BYTES,
    MAX_PUBLICATION_KEY_CHARACTERS,
    MAX_RESOURCE_INTEGER,
    MAX_SAFE_OPAQUE_ID_CHARACTERS,
    MAX_SELECTED_RECEIPTS,
    PHASE_COMPLETE,
    PHASE_LIFECYCLE_VERIFIED,
    PHASE_PREPARED,
    PHASE_PUBLICATION_COMMIT_UNKNOWN,
    PHASE_PUBLICATION_READBACK_VERIFIED,
    TRANSITION_EVIDENCE_SCHEMA_VERSION,
    SamplingCycleCoordinator,
    SamplingCycleCoordinatorError,
)

PROCESS = "pytest-native-trainer:coordinator-process-1"
CYCLE = "pytest-native-trainer:coordinator-cycle-1"
CHECKPOINT = "v2_hybrid_ckpt_aaaaaaaa_bbbbbbbbbbbbbbbb_cccccccccccc"
PREPARED_AT = "2026-07-19T12:00:00Z"
UNKNOWN_AT = "2026-07-19T12:00:01Z"
READBACK_AT = "2026-07-19T12:00:02Z"
LIFECYCLE_AT = "2026-07-19T12:00:03Z"
COMPLETE_AT = "2026-07-19T12:00:04Z"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _cycle(
    *,
    process: str = PROCESS,
    cycle_id: str = CYCLE,
    selected_count: int = 1,
    carry_in: float = 0.25,
    carry_out: float = 0.75,
    credit_in: int = 2,
    credit_out: int = 3,
) -> dict[str, Any]:
    selected = [
        {
            "selected_index": index,
            "receipt_hash": hashlib.sha256(f"receipt:{index}".encode()).hexdigest(),
            "draw_u53": 100 + index,
            "draw_denominator": U53_DENOMINATOR,
        }
        for index in range(selected_count)
    ]
    return {
        "schema_version": CYCLE_PREPARATION_SCHEMA_VERSION,
        "process_instance_id": process,
        "cycle_id": cycle_id,
        "plan_instance_id": sampling_plan_instance_id(
            cycle_id=cycle_id, process_instance_id=process
        ),
        "sampling_plan_envelope_auth_tag": "1" * 64,
        "sampling_plan_auth_key_id": "pytest-sampling-plan-key-2026-07",
        "sampling_plan_hash": "2" * 64,
        "sampling_plan_input_hash": "3" * 64,
        "parent_policy_fingerprint": "4" * 64,
        "checkpoint_id": CHECKPOINT,
        "checkpoint_weight_sha256": "5" * 64,
        "manifest_digest": "6" * 64,
        "cohort_id": "7" * 64,
        "selected_receipts": selected,
        "selected_receipt_count": selected_count,
        "carry_in": carry_in,
        "carry_out": carry_out,
        "single_candidate_ordinary_credit_in": credit_in,
        "single_candidate_ordinary_credit_out": credit_out,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _publication_records(cycle: Mapping[str, Any], *, status: str) -> list[dict[str, Any]]:
    return [
        {
            "receipt_hash": member["receipt_hash"],
            "publication_key": f"paper:behavior-receipt:{member['receipt_hash']}",
            "payload_sha256": hashlib.sha256(
                f"payload:{member['receipt_hash']}".encode()
            ).hexdigest(),
            "publication_status": status,
        }
        for member in cycle["selected_receipts"]
    ]


def _lifecycle_records(cycle: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "receipt_hash": member["receipt_hash"],
            "terminal_disposition": (
                "SAMPLED_HOLD_FINALIZED"
                if member["selected_index"] % 2
                else "ENTRY_OUTCOME_FINALIZED"
            ),
            "lifecycle_receipt_sha256": hashlib.sha256(
                f"lifecycle:{member['receipt_hash']}".encode()
            ).hexdigest(),
        }
        for member in cycle["selected_receipts"]
    ]


def _evidence(
    record: Any,
    *,
    target: str,
    observed_at: str,
    carry_head_transition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cycle = record.cycle
    selected_count = cycle["selected_receipt_count"]
    zero = selected_count == 0
    expected_by_target = {
        PHASE_PUBLICATION_COMMIT_UNKNOWN: (PHASE_PREPARED, 0),
        PHASE_PUBLICATION_READBACK_VERIFIED: (
            PHASE_PUBLICATION_COMMIT_UNKNOWN,
            1,
        ),
        PHASE_LIFECYCLE_VERIFIED: (PHASE_PUBLICATION_READBACK_VERIFIED, 2),
        PHASE_COMPLETE: (PHASE_LIFECYCLE_VERIFIED, 3),
    }
    expected_phase, expected_revision = expected_by_target[target]
    publication_status = (
        "COMMIT_UNKNOWN" if target == PHASE_PUBLICATION_COMMIT_UNKNOWN else "READBACK_VERIFIED"
    )
    publications = _publication_records(cycle, status=publication_status)
    if zero:
        publication_state = (
            "VACUOUS_NO_PUBLICATION_ATTEMPTED"
            if target == PHASE_PUBLICATION_COMMIT_UNKNOWN
            else "VACUOUS_NO_PUBLICATION_REQUIRED"
        )
        publication_digest = None
    else:
        publication_state = publication_status
        publication_digest = _sha(publications)
    if target in {PHASE_LIFECYCLE_VERIFIED, PHASE_COMPLETE}:
        lifecycles = _lifecycle_records(cycle)
        lifecycle_state = "VACUOUS_NO_LIFECYCLE_REQUIRED" if zero else "TERMINAL_LIFECYCLE_VERIFIED"
        lifecycle_digest = None if zero else _sha(lifecycles)
    else:
        lifecycles = []
        lifecycle_state = "NOT_YET_VERIFIED"
        lifecycle_digest = None
    return {
        "schema_version": TRANSITION_EVIDENCE_SCHEMA_VERSION,
        "cycle_identity_sha256": record.cycle_identity_sha256,
        "transition_to": target,
        "expected_phase": expected_phase,
        "expected_revision": expected_revision,
        "observed_at": observed_at,
        "selected_receipt_count": selected_count,
        "publication_records": publications,
        "publication_record_count": len(publications),
        "publication_state": publication_state,
        "publication_set_sha256": publication_digest,
        "lifecycle_records": lifecycles,
        "lifecycle_record_count": len(lifecycles),
        "lifecycle_state": lifecycle_state,
        "lifecycle_set_sha256": lifecycle_digest,
        "zero_selected_vacuous": zero,
        "carry_head_transition": carry_head_transition,
        "blind_republish_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _worst_bounded_cycle(selected_count: int, *, suffix: str = "capacity") -> dict[str, Any]:
    opaque_prefix = "\\" * (MAX_SAFE_OPAQUE_ID_CHARACTERS - len(suffix) - 1)
    cycle = _cycle(
        process=f"{opaque_prefix}:{suffix}",
        cycle_id=f"{opaque_prefix}/{suffix}",
        selected_count=selected_count,
        carry_in=2.2250738585072014e-308,
        carry_out=1.2345678901234568e-300,
        credit_in=MAX_RESOURCE_INTEGER,
        credit_out=MAX_RESOURCE_INTEGER,
    )
    cycle["sampling_plan_auth_key_id"] = "/" * 128
    return cycle


def _worst_bounded_publication_key(index: int, count: int) -> str:
    suffix_width = max(1, len(str(max(0, count - 1))))
    suffix = f"{index:0{suffix_width}d}"
    return "\\" * (MAX_PUBLICATION_KEY_CHARACTERS - len(suffix)) + suffix


def _worst_bounded_evidence(
    record: Any,
    *,
    target: str,
    observed_at: str,
    carry_head_transition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _evidence(
        record,
        target=target,
        observed_at=observed_at,
        carry_head_transition=carry_head_transition,
    )
    publications = evidence["publication_records"]
    for index, publication in enumerate(publications):
        publication["publication_key"] = _worst_bounded_publication_key(index, len(publications))
    if publications:
        evidence["publication_set_sha256"] = _sha(publications)
    lifecycles = evidence["lifecycle_records"]
    for lifecycle in lifecycles:
        lifecycle["terminal_disposition"] = "SAMPLED_HOLD_FINALIZED"
    if lifecycles:
        evidence["lifecycle_set_sha256"] = _sha(lifecycles)
    return evidence


def _coordinator(tmp_path: Path, name: str = "coordinator.sqlite3") -> SamplingCycleCoordinator:
    tmp_path.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    return SamplingCycleCoordinator(tmp_path / name)


def _advance_to_lifecycle_verified(
    coordinator: SamplingCycleCoordinator, cycle: Mapping[str, Any] | None = None
) -> Any:
    prepared = coordinator.prepare_cycle(cycle or _cycle(), prepared_at=PREPARED_AT)
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256,
        _evidence(
            prepared,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
            observed_at=UNKNOWN_AT,
        ),
    )
    readback = coordinator.mark_publication_readback_verified(
        unknown.cycle_identity_sha256,
        _evidence(
            unknown,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
            observed_at=READBACK_AT,
        ),
    )
    return coordinator.mark_lifecycle_verified(
        readback.cycle_identity_sha256,
        _evidence(
            readback,
            target=PHASE_LIFECYCLE_VERIFIED,
            observed_at=LIFECYCLE_AT,
        ),
    )


def _complete(
    coordinator: SamplingCycleCoordinator, lifecycle: Any, *, at: str = COMPLETE_AT
) -> tuple[Any, dict[str, Any]]:
    binding = coordinator.completion_head_transition(
        lifecycle.cycle_identity_sha256, observed_at=at
    )
    evidence = _evidence(
        lifecycle,
        target=PHASE_COMPLETE,
        observed_at=at,
        carry_head_transition=binding,
    )
    return coordinator.complete(lifecycle.cycle_identity_sha256, evidence), evidence


def test_full_phase_chain_is_durable_canonical_and_advances_head_only_at_complete(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _cycle()

    prepared = coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)

    assert prepared.phase == PHASE_PREPARED
    assert prepared.revision == 0
    assert prepared.cycle_identity_sha256 == _sha(cycle)
    assert prepared.blind_republish_allowed is False
    assert coordinator.unresolved_for_process(PROCESS) == prepared
    genesis = coordinator.carry_head(PROCESS)
    assert (genesis.revision, genesis.carry, genesis.single_candidate_ordinary_credit) == (
        0,
        0.25,
        2,
    )

    unknown_evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at=UNKNOWN_AT,
    )
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256, unknown_evidence
    )
    assert (unknown.phase, unknown.revision) == (PHASE_PUBLICATION_COMMIT_UNKNOWN, 1)
    assert coordinator.carry_head(PROCESS) == genesis

    readback = coordinator.mark_publication_readback_verified(
        unknown.cycle_identity_sha256,
        _evidence(
            unknown,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
            observed_at=READBACK_AT,
        ),
    )
    assert (readback.phase, readback.revision) == (
        PHASE_PUBLICATION_READBACK_VERIFIED,
        2,
    )
    assert coordinator.carry_head(PROCESS) == genesis

    lifecycle = coordinator.mark_lifecycle_verified(
        readback.cycle_identity_sha256,
        _evidence(
            readback,
            target=PHASE_LIFECYCLE_VERIFIED,
            observed_at=LIFECYCLE_AT,
        ),
    )
    assert (lifecycle.phase, lifecycle.revision) == (PHASE_LIFECYCLE_VERIFIED, 3)
    assert coordinator.carry_head(PROCESS) == genesis

    complete, complete_evidence = _complete(coordinator, lifecycle)
    assert (complete.phase, complete.revision) == (PHASE_COMPLETE, 4)
    assert coordinator.unresolved_for_process(PROCESS) is None
    head = coordinator.carry_head(PROCESS)
    assert (
        head.revision,
        head.carry,
        head.single_candidate_ordinary_credit,
        head.completed_cycle_identity_sha256,
    ) == (1, 0.75, 3, complete.cycle_identity_sha256)
    assert head.head_sha256 == complete_evidence["carry_head_transition"]["next_head_sha256"]
    assert os.stat(coordinator.path).st_mode & 0o777 == 0o600

    with sqlite3.connect(coordinator.path) as connection:
        evidence_rows = connection.execute(
            "SELECT evidence_json, evidence_sha256 FROM sampling_cycle_evidence ORDER BY revision"
        ).fetchall()
        assert len(evidence_rows) == 4
        for evidence_json, evidence_sha in evidence_rows:
            assert evidence_json == _canonical(json.loads(evidence_json))
            assert evidence_sha == hashlib.sha256(evidence_json.encode("ascii")).hexdigest()
        assert connection.execute(
            "SELECT COUNT(*) FROM sampling_cycle_carry_head_advances"
        ).fetchone() == (1,)


def test_crash_reopen_recovers_unresolved_cycle_and_stable_head(tmp_path: Path) -> None:
    first = _coordinator(tmp_path)
    prepared = first.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    unknown = first.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256,
        _evidence(
            prepared,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
            observed_at=UNKNOWN_AT,
        ),
    )
    before = first.carry_head(PROCESS)

    reopened = SamplingCycleCoordinator(first.path)

    assert reopened.unresolved_for_process(PROCESS) == unknown
    assert reopened.carry_head(PROCESS) == before
    readback = reopened.mark_publication_readback_verified(
        unknown.cycle_identity_sha256,
        _evidence(
            unknown,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
            observed_at=READBACK_AT,
        ),
    )
    assert readback.phase == PHASE_PUBLICATION_READBACK_VERIFIED


def test_identical_retries_are_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _cycle()
    prepared = coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)

    assert coordinator.prepare_cycle(deepcopy(cycle), prepared_at=PREPARED_AT) == prepared
    conflict = deepcopy(cycle)
    conflict["manifest_digest"] = "8" * 64
    with pytest.raises(SamplingCycleCoordinatorError, match="conflicting_retry"):
        coordinator.prepare_cycle(conflict, prepared_at=PREPARED_AT)
    with pytest.raises(SamplingCycleCoordinatorError, match="conflicting_retry"):
        coordinator.prepare_cycle(cycle, prepared_at=UNKNOWN_AT)

    evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at=UNKNOWN_AT,
    )
    first = coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, evidence)
    assert (
        coordinator.mark_publication_commit_unknown(
            prepared.cycle_identity_sha256, deepcopy(evidence)
        )
        == first
    )
    conflicting = deepcopy(evidence)
    conflicting["publication_records"][0]["payload_sha256"] = "9" * 64
    with pytest.raises(SamplingCycleCoordinatorError, match="conflicting_transition_retry"):
        coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, conflicting)


def test_one_unresolved_cycle_per_process_and_carry_continuity(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    second = _cycle(cycle_id="cycle-2")
    with pytest.raises(SamplingCycleCoordinatorError, match="already_has_unresolved"):
        coordinator.prepare_cycle(second, prepared_at=UNKNOWN_AT)

    coordinator = _coordinator(tmp_path / "sequential", "cycles.sqlite3")
    lifecycle = _advance_to_lifecycle_verified(coordinator)
    _complete(coordinator, lifecycle)
    wrong_head = _cycle(
        cycle_id="cycle-2",
        carry_in=0.74,
        carry_out=0.1,
        credit_in=3,
        credit_out=4,
    )
    with pytest.raises(SamplingCycleCoordinatorError, match="carry_head_input_mismatch"):
        coordinator.prepare_cycle(wrong_head, prepared_at="2026-07-19T12:00:05Z")
    right_head = _cycle(
        cycle_id="cycle-2",
        carry_in=0.75,
        carry_out=0.1,
        credit_in=3,
        credit_out=4,
    )
    second_prepared = coordinator.prepare_cycle(right_head, prepared_at="2026-07-19T12:00:05Z")
    assert second_prepared.phase == PHASE_PREPARED
    assert coordinator.carry_head(PROCESS).revision == 1


def test_commit_unknown_never_allows_blind_republish_or_phase_skip(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    readback_evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_READBACK_VERIFIED,
        observed_at=READBACK_AT,
    )
    with pytest.raises(SamplingCycleCoordinatorError, match="transition_skip_rejected"):
        coordinator.mark_publication_readback_verified(
            prepared.cycle_identity_sha256, readback_evidence
        )

    unknown_evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at=UNKNOWN_AT,
    )
    forbidden = deepcopy(unknown_evidence)
    forbidden["blind_republish_allowed"] = True
    with pytest.raises(SamplingCycleCoordinatorError, match="blind_republish_forbidden"):
        coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, forbidden)
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256, unknown_evidence
    )
    readback = coordinator.mark_publication_readback_verified(
        unknown.cycle_identity_sha256,
        _evidence(
            unknown,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
            observed_at=READBACK_AT,
        ),
    )
    with pytest.raises(SamplingCycleCoordinatorError, match="transition_replay_rejected"):
        coordinator.mark_publication_commit_unknown(
            readback.cycle_identity_sha256, unknown_evidence
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate_key", "payload"])
def test_publication_readback_requires_exact_key_and_payload_membership(
    tmp_path: Path, mutation: str
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(selected_count=2), prepared_at=PREPARED_AT)
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256,
        _evidence(
            prepared,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
            observed_at=UNKNOWN_AT,
        ),
    )
    evidence = _evidence(
        unknown,
        target=PHASE_PUBLICATION_READBACK_VERIFIED,
        observed_at=READBACK_AT,
    )
    if mutation == "missing":
        evidence["publication_records"].pop()
        evidence["publication_record_count"] -= 1
    elif mutation == "extra":
        evidence["publication_records"].append(deepcopy(evidence["publication_records"][0]))
        evidence["publication_record_count"] += 1
    elif mutation == "duplicate_key":
        evidence["publication_records"][1]["publication_key"] = evidence["publication_records"][0][
            "publication_key"
        ]
    else:
        evidence["publication_records"][0]["payload_sha256"] = "e" * 64
    evidence["publication_set_sha256"] = _sha(evidence["publication_records"])

    with pytest.raises(SamplingCycleCoordinatorError):
        coordinator.mark_publication_readback_verified(unknown.cycle_identity_sha256, evidence)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_receipt", "disposition"])
def test_lifecycle_transition_requires_exact_terminal_receipt_membership(
    tmp_path: Path, mutation: str
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(selected_count=2), prepared_at=PREPARED_AT)
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256,
        _evidence(
            prepared,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
            observed_at=UNKNOWN_AT,
        ),
    )
    readback = coordinator.mark_publication_readback_verified(
        unknown.cycle_identity_sha256,
        _evidence(
            unknown,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
            observed_at=READBACK_AT,
        ),
    )
    evidence = _evidence(
        readback,
        target=PHASE_LIFECYCLE_VERIFIED,
        observed_at=LIFECYCLE_AT,
    )
    if mutation == "missing":
        evidence["lifecycle_records"].pop()
        evidence["lifecycle_record_count"] -= 1
    elif mutation == "extra":
        evidence["lifecycle_records"].append(deepcopy(evidence["lifecycle_records"][0]))
        evidence["lifecycle_record_count"] += 1
    elif mutation == "wrong_receipt":
        evidence["lifecycle_records"][0]["receipt_hash"] = "d" * 64
    else:
        evidence["lifecycle_records"][0]["terminal_disposition"] = "NOT_TERMINAL"
    evidence["lifecycle_set_sha256"] = _sha(evidence["lifecycle_records"])

    with pytest.raises(SamplingCycleCoordinatorError):
        coordinator.mark_lifecycle_verified(readback.cycle_identity_sha256, evidence)


def test_zero_selected_cycle_uses_explicit_vacuous_evidence_without_fake_digest(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    zero_cycle = _cycle(
        selected_count=0,
        carry_in=0.5,
        carry_out=0.9,
        credit_in=0,
        credit_out=1,
    )
    lifecycle = _advance_to_lifecycle_verified(coordinator, zero_cycle)

    for evidence in lifecycle.transition_evidence:
        assert evidence["zero_selected_vacuous"] is True
        assert evidence["selected_receipt_count"] == 0
        assert evidence["publication_records"] == []
        assert evidence["publication_set_sha256"] is None
        assert evidence["lifecycle_set_sha256"] is None
    complete, _evidence_row = _complete(coordinator, lifecycle)
    assert complete.phase == PHASE_COMPLETE
    head = coordinator.carry_head(PROCESS)
    assert (head.carry, head.single_candidate_ordinary_credit) == (0.9, 1)


def test_zero_selected_cycle_rejects_fabricated_completeness(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(selected_count=0), prepared_at=PREPARED_AT)
    evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at=UNKNOWN_AT,
    )
    evidence["publication_set_sha256"] = _sha([])
    with pytest.raises(SamplingCycleCoordinatorError, match="not_vacuous"):
        coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, evidence)


def test_largest_admitted_worst_bounded_cycle_reaches_complete(tmp_path: Path) -> None:
    assert 0 < MAX_SELECTED_RECEIPTS < 1_000
    coordinator = _coordinator(tmp_path)
    cycle = _worst_bounded_cycle(MAX_SELECTED_RECEIPTS)
    prepared_at = "9999-12-31T23:59:59.000000Z"
    unknown_at = "9999-12-31T23:59:59.100000Z"
    readback_at = "9999-12-31T23:59:59.200000Z"
    lifecycle_at = "9999-12-31T23:59:59.300000Z"
    complete_at = "9999-12-31T23:59:59.400000Z"

    prepared = coordinator.prepare_cycle(cycle, prepared_at=prepared_at)
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256,
        _worst_bounded_evidence(
            prepared,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
            observed_at=unknown_at,
        ),
    )
    readback = coordinator.mark_publication_readback_verified(
        unknown.cycle_identity_sha256,
        _worst_bounded_evidence(
            unknown,
            target=PHASE_PUBLICATION_READBACK_VERIFIED,
            observed_at=readback_at,
        ),
    )
    lifecycle = coordinator.mark_lifecycle_verified(
        readback.cycle_identity_sha256,
        _worst_bounded_evidence(
            readback,
            target=PHASE_LIFECYCLE_VERIFIED,
            observed_at=lifecycle_at,
        ),
    )
    transition = coordinator.completion_head_transition(
        lifecycle.cycle_identity_sha256,
        observed_at=complete_at,
    )
    completion_evidence = _worst_bounded_evidence(
        lifecycle,
        target=PHASE_COMPLETE,
        observed_at=complete_at,
        carry_head_transition=transition,
    )
    assert len(_canonical(completion_evidence).encode("ascii")) <= MAX_COORDINATOR_JSON_BYTES
    complete = coordinator.complete(lifecycle.cycle_identity_sha256, completion_evidence)

    assert complete.phase == PHASE_COMPLETE
    assert complete.revision == 4
    assert coordinator.carry_head(cycle["process_instance_id"]).revision == 1


@pytest.mark.parametrize(
    ("selected_count", "suffix"),
    [
        (MAX_SELECTED_RECEIPTS + 1, "first-over-capacity"),
        (1_000, "one-thousand-not-completable"),
    ],
)
def test_uncompletable_capacity_rejects_before_prepared(
    tmp_path: Path,
    selected_count: int,
    suffix: str,
) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _worst_bounded_cycle(selected_count, suffix=suffix)

    with pytest.raises(
        SamplingCycleCoordinatorError,
        match="^sampling_cycle_terminal_capacity_exceeded$",
    ):
        coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)

    assert coordinator.unresolved_for_process(cycle["process_instance_id"]) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_receipt_count", True),
        ("single_candidate_ordinary_credit_in", True),
        ("single_candidate_ordinary_credit_out", False),
        ("carry_in", float("nan")),
        ("carry_out", float("inf")),
    ],
)
def test_prepare_rejects_boolean_counts_and_nonfinite_numbers(
    tmp_path: Path, field: str, value: object
) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _cycle()
    cycle[field] = value
    with pytest.raises(SamplingCycleCoordinatorError):
        coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)


@pytest.mark.parametrize(("field", "value"), [("selected_index", True), ("draw_u53", False)])
def test_prepare_rejects_boolean_selected_index_or_draw(
    tmp_path: Path, field: str, value: object
) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _cycle()
    cycle["selected_receipts"][0][field] = value
    with pytest.raises(SamplingCycleCoordinatorError):
        coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)


@pytest.mark.parametrize(
    "field",
    ["expected_revision", "selected_receipt_count", "publication_record_count"],
)
def test_transition_rejects_boolean_revisions_and_counts(tmp_path: Path, field: str) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at=UNKNOWN_AT,
    )
    evidence[field] = True
    with pytest.raises(SamplingCycleCoordinatorError):
        coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, evidence)


def test_non_decreasing_timestamp_contract_rejects_regression(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at="2026-07-19T11:59:59Z",
    )
    with pytest.raises(SamplingCycleCoordinatorError, match="time_regressed"):
        coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, evidence)


def test_completion_head_binding_is_revision_and_hash_bound_and_advances_once(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    lifecycle = _advance_to_lifecycle_verified(coordinator)
    binding = coordinator.completion_head_transition(
        lifecycle.cycle_identity_sha256, observed_at=COMPLETE_AT
    )
    assert binding["schema_version"] == CARRY_HEAD_TRANSITION_SCHEMA_VERSION
    stale = deepcopy(binding)
    stale["expected_head_revision"] = stale["expected_head_revision"] + 1
    stale["next_head_revision"] = stale["next_head_revision"] + 1
    evidence = _evidence(
        lifecycle,
        target=PHASE_COMPLETE,
        observed_at=COMPLETE_AT,
        carry_head_transition=stale,
    )
    with pytest.raises(SamplingCycleCoordinatorError, match="transition_binding_invalid"):
        coordinator.complete(lifecycle.cycle_identity_sha256, evidence)
    assert coordinator.carry_head(PROCESS).revision == 0

    complete, exact_evidence = _complete(coordinator, lifecycle)
    first_head = coordinator.carry_head(PROCESS)
    assert coordinator.complete(complete.cycle_identity_sha256, exact_evidence) == complete
    assert coordinator.carry_head(PROCESS) == first_head


class _HostileMapping(Mapping[str, Any]):
    def __init__(
        self,
        first_items: list[tuple[str, Any]],
        *,
        later_items: list[tuple[str, Any]] | None = None,
        items_error: bool = False,
    ) -> None:
        self._first_items = first_items
        self._later_items = later_items or first_items
        self._values = dict(first_items)
        self._items_error = items_error
        self.items_calls = 0

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("hostile-sensitive-marker")

    def __len__(self) -> int:
        raise RuntimeError("hostile-sensitive-marker")

    def items(self) -> Any:
        self.items_calls += 1
        if self._items_error:
            raise RuntimeError("hostile-sensitive-marker")
        return self._first_items if self.items_calls == 1 else self._later_items


class _HostileClassObservation:
    def __init__(self) -> None:
        self.observations = 0

    def __getattribute__(self, name: str) -> Any:
        if name == "__class__":
            observations = cast(int, object.__getattribute__(self, "observations"))
            object.__setattr__(self, "observations", observations + 1)
            raise RuntimeError("hostile-class-secret-marker")
        return object.__getattribute__(self, name)


@pytest.mark.parametrize("boundary", ["prepare", "transition_evidence"])
def test_hostile_class_hook_is_never_observed_at_public_json_boundaries(
    tmp_path: Path,
    boundary: str,
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = (
        coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
        if boundary == "transition_evidence"
        else None
    )
    hostile = _HostileClassObservation()

    with pytest.raises(SamplingCycleCoordinatorError) as captured:
        if prepared is None:
            coordinator.prepare_cycle(hostile, prepared_at=PREPARED_AT)  # type: ignore[arg-type]
        else:
            coordinator.mark_publication_commit_unknown(
                prepared.cycle_identity_sha256,
                hostile,  # type: ignore[arg-type]
            )

    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert hostile.observations == 0
    assert str(captured.value) == "sampling_cycle_json_type_invalid"
    assert "hostile-class-secret-marker" not in rendered


def test_moving_mapping_is_snapshotted_once_without_len_or_second_read(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    original = _cycle()
    moved = deepcopy(original)
    moved["manifest_digest"] = "f" * 64
    hostile = _HostileMapping(list(original.items()), later_items=list(moved.items()))

    prepared = coordinator.prepare_cycle(hostile, prepared_at=PREPARED_AT)

    assert hostile.items_calls == 1
    assert prepared.cycle["manifest_digest"] == original["manifest_digest"]


def test_duplicate_and_malformed_mapping_items_fail_before_materialization(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _cycle()
    duplicate = _HostileMapping([*list(cycle.items()), ("manifest_digest", "f" * 64)])
    with pytest.raises(SamplingCycleCoordinatorError, match="key_duplicate"):
        coordinator.prepare_cycle(duplicate, prepared_at=PREPARED_AT)
    assert duplicate.items_calls == 1


def test_hostile_mapping_exception_is_fixed_and_does_not_leak_payload(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    hostile = _HostileMapping(list(_cycle().items()), items_error=True)
    with pytest.raises(SamplingCycleCoordinatorError) as captured:
        coordinator.prepare_cycle(hostile, prepared_at=PREPARED_AT)
    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert str(captured.value) == "sampling_cycle_json_mapping_invalid"
    assert "hostile-sensitive-marker" not in rendered


def _rewrite_cycle_json(coordinator: SamplingCycleCoordinator, replacement: str) -> None:
    with sqlite3.connect(coordinator.path) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sampling_cycle_cycles_guard_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER sampling_cycle_cycles_guard_update")
        connection.execute("UPDATE sampling_cycle_cycles SET cycle_json = ?", (replacement,))
        connection.execute(trigger_sql)
        connection.commit()


@pytest.mark.parametrize("kind", ["duplicate", "noncanonical", "nonfinite"])
def test_stored_duplicate_noncanonical_and_nonfinite_json_is_detected(
    tmp_path: Path, kind: str
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    canonical = _canonical(prepared.cycle)
    if kind == "duplicate":
        replacement = '{"carry_in":0.25,' + canonical[1:]
    elif kind == "noncanonical":
        replacement = canonical + " "
    else:
        replacement = canonical.replace('"carry_in":0.25', '"carry_in":NaN', 1)
    _rewrite_cycle_json(coordinator, replacement)

    with pytest.raises(SamplingCycleCoordinatorError, match="stored_json"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_transition_hash_tamper_and_immutable_evidence_updates_are_rejected(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    unknown = coordinator.mark_publication_commit_unknown(
        prepared.cycle_identity_sha256,
        _evidence(
            prepared,
            target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
            observed_at=UNKNOWN_AT,
        ),
    )
    with sqlite3.connect(coordinator.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="evidence_immutable"):
            connection.execute(
                "UPDATE sampling_cycle_evidence SET transition_sha256 = ?",
                ("0" * 64,),
            )

    with sqlite3.connect(coordinator.path) as connection:
        trigger_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sampling_cycle_evidence_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER sampling_cycle_evidence_no_update")
        connection.execute(
            "UPDATE sampling_cycle_evidence SET transition_sha256 = ?",
            ("0" * 64,),
        )
        connection.execute(trigger_sql)
        connection.commit()
    with pytest.raises(SamplingCycleCoordinatorError, match="transition_seal_invalid"):
        coordinator.get_cycle(unknown.cycle_identity_sha256)


def test_schema_trigger_removal_is_detected_before_state_access(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    with sqlite3.connect(coordinator.path) as connection:
        connection.execute("DROP TRIGGER sampling_cycle_cycles_no_delete")
        connection.commit()
    with pytest.raises(SamplingCycleCoordinatorError, match="schema_objects_invalid"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_schema_column_drift_is_detected_even_when_metadata_is_unchanged(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    with sqlite3.connect(coordinator.path) as connection:
        connection.execute("ALTER TABLE sampling_cycle_cycles ADD COLUMN injected_state TEXT")
        connection.commit()
    with pytest.raises(SamplingCycleCoordinatorError, match="schema_ddl_invalid"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_carry_head_aba_mutation_is_blocked_by_immutable_advance_trigger(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    lifecycle = _advance_to_lifecycle_verified(coordinator)
    _complete(coordinator, lifecycle)
    with sqlite3.connect(coordinator.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="head_advance_immutable"):
            connection.execute(
                "UPDATE sampling_cycle_carry_head_advances SET prior_head_sha256 = ?",
                ("0" * 64,),
            )


def test_concurrent_identical_prepare_and_transition_are_idempotent(tmp_path: Path) -> None:
    first = _coordinator(tmp_path)
    second = SamplingCycleCoordinator(first.path)
    cycle = _cycle()
    with ThreadPoolExecutor(max_workers=2) as pool:
        prepared_rows = list(
            pool.map(
                lambda coordinator: coordinator.prepare_cycle(
                    deepcopy(cycle), prepared_at=PREPARED_AT
                ),
                (first, second),
            )
        )
    assert prepared_rows[0] == prepared_rows[1]
    evidence = _evidence(
        prepared_rows[0],
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at=UNKNOWN_AT,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        transitioned = list(
            pool.map(
                lambda coordinator: coordinator.mark_publication_commit_unknown(
                    prepared_rows[0].cycle_identity_sha256,
                    deepcopy(evidence),
                ),
                (first, second),
            )
        )
    assert transitioned[0] == transitioned[1]
    assert transitioned[0].revision == 1


def test_concurrent_conflicting_cycles_leave_exactly_one_unresolved(tmp_path: Path) -> None:
    first = _coordinator(tmp_path)
    second = SamplingCycleCoordinator(first.path)
    cycles = (_cycle(cycle_id="concurrent-a"), _cycle(cycle_id="concurrent-b"))

    def prepare(args: tuple[SamplingCycleCoordinator, dict[str, Any]]) -> object:
        coordinator, cycle = args
        try:
            return coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)
        except SamplingCycleCoordinatorError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(prepare, ((first, cycles[0]), (second, cycles[1]))))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, SamplingCycleCoordinatorError) for result in results) == 1
    assert first.unresolved_for_process(PROCESS) is not None


@pytest.mark.parametrize("mode", [0o400, 0o644, 0o660, 0o604])
def test_existing_database_requires_private_mode(tmp_path: Path, mode: int) -> None:
    coordinator = _coordinator(tmp_path)
    coordinator.path.chmod(mode)
    try:
        with pytest.raises(SamplingCycleCoordinatorError, match="private_mode_required"):
            SamplingCycleCoordinator(coordinator.path)
    finally:
        coordinator.path.chmod(0o600)


@pytest.mark.parametrize("mode", [0o750, 0o705, 0o711])
def test_database_parent_must_hide_transient_sqlite_journal(tmp_path: Path, mode: int) -> None:
    tmp_path.chmod(mode)
    try:
        with pytest.raises(SamplingCycleCoordinatorError, match="parent_not_owner_private"):
            SamplingCycleCoordinator(tmp_path / "coordinator.sqlite3")
    finally:
        tmp_path.chmod(0o700)


def test_path_must_be_explicit_absolute_and_not_symlink(tmp_path: Path) -> None:
    with pytest.raises(SamplingCycleCoordinatorError, match="explicit_absolute_path"):
        SamplingCycleCoordinator(Path("relative.sqlite3"))
    with pytest.raises(SamplingCycleCoordinatorError, match="explicit_absolute_path"):
        SamplingCycleCoordinator(str(tmp_path / "string.sqlite3"))  # type: ignore[arg-type]
    lexical_parent_escape = tmp_path / "unused" / ".." / "escape.sqlite3"
    with pytest.raises(SamplingCycleCoordinatorError, match="lexically_invalid"):
        SamplingCycleCoordinator(lexical_parent_escape)

    coordinator = _coordinator(tmp_path, "real.sqlite3")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(coordinator.path)
    with pytest.raises(SamplingCycleCoordinatorError, match="db_file_invalid"):
        SamplingCycleCoordinator(link)


def test_symlinked_ancestor_is_rejected_by_lexical_dirfd_walk(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    alias = tmp_path / "alias-parent"
    alias.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(SamplingCycleCoordinatorError, match="parent_open_failed"):
        SamplingCycleCoordinator(alias / "coordinator.sqlite3")
    assert not (real_parent / "coordinator.sqlite3").exists()


def test_post_construction_main_path_swap_is_rejected_before_reopen(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    original = tmp_path / "original.sqlite3"
    coordinator.path.rename(original)
    coordinator.path.write_bytes(original.read_bytes())
    coordinator.path.chmod(0o600)

    with pytest.raises(SamplingCycleCoordinatorError, match="main_inode_changed"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


@pytest.mark.parametrize("operation", ["read", "write"])
def test_connect_time_main_swap_restored_before_path_validation_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    parent = tmp_path / operation
    coordinator = _coordinator(parent)
    original_record = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)

    replacement_path = parent / "replacement.sqlite3"
    replacement_path.write_bytes(coordinator.path.read_bytes())
    replacement_path.chmod(0o600)
    replacement_coordinator = SamplingCycleCoordinator(replacement_path)
    replacement_cycle = _cycle(
        process=f"{PROCESS}:{operation}:replacement",
        cycle_id=f"{CYCLE}:{operation}:replacement",
    )
    replacement_record = replacement_coordinator.prepare_cycle(
        replacement_cycle,
        prepared_at=PREPARED_AT,
    )

    original_identity = (
        int(coordinator.path.stat().st_dev),
        int(coordinator.path.stat().st_ino),
    )
    replacement_identity = (
        int(replacement_path.stat().st_dev),
        int(replacement_path.stat().st_ino),
    )
    original_bytes_sha256 = hashlib.sha256(coordinator.path.read_bytes()).hexdigest()
    replacement_bytes_sha256 = hashlib.sha256(replacement_path.read_bytes()).hexdigest()
    descriptors_before = len(os.listdir("/proc/self/fd"))
    held_original = parent / "held-original.sqlite3"
    real_connect = sqlite3.connect

    def swap_only_during_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        coordinator.path.replace(held_original)
        replacement_path.replace(coordinator.path)
        try:
            return cast(sqlite3.Connection, real_connect(*args, **kwargs))
        finally:
            coordinator.path.replace(replacement_path)
            held_original.replace(coordinator.path)

    monkeypatch.setattr(sqlite3, "connect", swap_only_during_connect)
    with pytest.raises(
        SamplingCycleCoordinatorError,
        match="^sampling_cycle_db_connection_main_binding_mismatch$",
    ):
        if operation == "read":
            coordinator.get_cycle(replacement_record.cycle_identity_sha256)
        else:
            coordinator.prepare_cycle(
                _cycle(
                    process=f"{PROCESS}:{operation}:candidate",
                    cycle_id=f"{CYCLE}:{operation}:candidate",
                ),
                prepared_at=UNKNOWN_AT,
            )
    monkeypatch.undo()

    assert not held_original.exists()
    assert (
        int(coordinator.path.stat().st_dev),
        int(coordinator.path.stat().st_ino),
    ) == original_identity
    assert (
        int(replacement_path.stat().st_dev),
        int(replacement_path.stat().st_ino),
    ) == replacement_identity
    assert hashlib.sha256(coordinator.path.read_bytes()).hexdigest() == original_bytes_sha256
    assert hashlib.sha256(replacement_path.read_bytes()).hexdigest() == replacement_bytes_sha256
    assert len(os.listdir("/proc/self/fd")) == descriptors_before
    assert coordinator.get_cycle(original_record.cycle_identity_sha256) == original_record
    assert (
        replacement_coordinator.get_cycle(replacement_record.cycle_identity_sha256)
        == replacement_record
    )


def test_connect_time_swap_cannot_hide_behind_expected_inode_decoy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    replacement = tmp_path / "decoy-replacement.sqlite3"
    replacement.write_bytes(coordinator.path.read_bytes())
    replacement.chmod(0o600)
    held_original = tmp_path / "decoy-held-original.sqlite3"
    real_connect = sqlite3.connect
    decoy_descriptors: list[int] = []
    descriptors_before = len(os.listdir("/proc/self/fd"))

    def swap_and_retain_expected_decoy(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        coordinator.path.replace(held_original)
        replacement.replace(coordinator.path)
        decoy_descriptors.append(os.open(held_original, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)))
        try:
            return cast(sqlite3.Connection, real_connect(*args, **kwargs))
        finally:
            coordinator.path.replace(replacement)
            held_original.replace(coordinator.path)

    monkeypatch.setattr(sqlite3, "connect", swap_and_retain_expected_decoy)
    try:
        with pytest.raises(
            SamplingCycleCoordinatorError,
            match="^sampling_cycle_db_connection_main_binding_mismatch$",
        ):
            coordinator.get_cycle(prepared.cycle_identity_sha256)
    finally:
        monkeypatch.undo()
        for descriptor in decoy_descriptors:
            os.close(descriptor)

    assert len(os.listdir("/proc/self/fd")) == descriptors_before
    assert coordinator.get_cycle(prepared.cycle_identity_sha256) == prepared


def test_lexical_database_path_property_cannot_be_retargeted(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    with pytest.raises(AttributeError):
        coordinator.path = tmp_path / "other.sqlite3"  # type: ignore[misc]


def test_post_construction_parent_replaced_by_symlink_is_rejected(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "private-parent"
    coordinator = _coordinator(parent)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    moved = tmp_path / "moved-parent"
    parent.rename(moved)
    parent.symlink_to(moved, target_is_directory=True)

    with pytest.raises(SamplingCycleCoordinatorError, match="parent_open_failed"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_post_construction_parent_inode_swap_rejects_even_same_main_inode(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "private-parent"
    coordinator = _coordinator(parent)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    moved = tmp_path / "moved-parent"
    parent.rename(moved)
    parent.mkdir(mode=0o700)
    (moved / coordinator.path.name).rename(parent / coordinator.path.name)

    with pytest.raises(SamplingCycleCoordinatorError, match="parent_inode_changed"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_symlinked_sqlite_sidecar_is_rejected_before_reopen(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    target = tmp_path / "sidecar-target"
    target.write_bytes(b"not-a-journal")
    target.chmod(0o600)
    sidecar = Path(f"{coordinator.path}-journal")
    sidecar.symlink_to(target)

    with pytest.raises(SamplingCycleCoordinatorError, match="journal_open_failed"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_open_delete_journal_descriptor_is_inode_bound_during_mutation(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    connection = coordinator._open_writable()
    journal_path = Path(f"{coordinator.path}-journal")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("PRAGMA user_version=2")
        guarded_connection = cast(Any, connection)
        bound_sidecars = cast(
            dict[str, tuple[int, tuple[int, int]]],
            guarded_connection._sampling_cycle_connection_sidecar_fds,
        )
        assert set(bound_sidecars) == {"journal"}
        journal_fd, bound_identity = bound_sidecars["journal"]
        journal_stat = journal_path.stat()
        descriptor_stat = os.fstat(journal_fd)
        assert bound_identity == (
            int(journal_stat.st_dev),
            int(journal_stat.st_ino),
        )
        assert bound_identity == (
            int(descriptor_stat.st_dev),
            int(descriptor_stat.st_ino),
        )
        connection.rollback()
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
    assert not journal_path.exists()
    assert SamplingCycleCoordinator(coordinator.path).path == coordinator.path


def test_reopen_rechecks_parent_mode_main_mode_and_link_count(tmp_path: Path) -> None:
    parent_mode = tmp_path / "parent-mode"
    parent_coordinator = _coordinator(parent_mode)
    parent_record = parent_coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    parent_mode.chmod(0o750)
    try:
        with pytest.raises(SamplingCycleCoordinatorError, match="parent_not_owner_private"):
            parent_coordinator.get_cycle(parent_record.cycle_identity_sha256)
    finally:
        parent_mode.chmod(0o700)

    file_mode = tmp_path / "file-mode"
    file_coordinator = _coordinator(file_mode)
    file_record = file_coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    file_coordinator.path.chmod(0o640)
    try:
        with pytest.raises(SamplingCycleCoordinatorError, match="main_private_mode_required"):
            file_coordinator.get_cycle(file_record.cycle_identity_sha256)
    finally:
        file_coordinator.path.chmod(0o600)

    hardlink_parent = tmp_path / "hardlink"
    hardlink_coordinator = _coordinator(hardlink_parent)
    hardlink_record = hardlink_coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    os.link(hardlink_coordinator.path, hardlink_parent / "alias.sqlite3")
    with pytest.raises(SamplingCycleCoordinatorError, match="main_hardlink_forbidden"):
        hardlink_coordinator.get_cycle(hardlink_record.cycle_identity_sha256)


@pytest.mark.parametrize("weakening", ["noop_trigger", "nonunique_index"])
def test_same_name_weakened_schema_object_is_rejected_by_exact_ddl(
    tmp_path: Path, weakening: str
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    with sqlite3.connect(coordinator.path) as connection:
        if weakening == "noop_trigger":
            connection.execute("DROP TRIGGER sampling_cycle_cycles_no_delete")
            connection.execute(
                """
                CREATE TRIGGER sampling_cycle_cycles_no_delete
                BEFORE DELETE ON sampling_cycle_cycles BEGIN
                    SELECT 1;
                END
                """
            )
        else:
            connection.execute("DROP INDEX sampling_cycle_one_unresolved_per_process")
            connection.execute(
                """
                CREATE INDEX sampling_cycle_one_unresolved_per_process
                ON sampling_cycle_cycles(process_instance_id)
                WHERE phase != 'COMPLETE'
                """
            )
        connection.commit()

    with pytest.raises(SamplingCycleCoordinatorError, match="schema_ddl_invalid"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


@pytest.mark.parametrize(
    ("pragma", "expected_error"),
    [
        ("application_id=0", "application_id_invalid"),
        ("user_version=0", "user_version_invalid"),
    ],
)
def test_sqlite_header_identity_is_verified_on_every_access(
    tmp_path: Path, pragma: str, expected_error: str
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    with sqlite3.connect(coordinator.path) as connection:
        connection.execute(f"PRAGMA {pragma}")
    with pytest.raises(SamplingCycleCoordinatorError, match=expected_error):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


def test_foreign_key_check_must_be_empty_before_any_state_read(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    evidence_json = _canonical({"orphan": True})
    with sqlite3.connect(coordinator.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """
            INSERT INTO sampling_cycle_evidence(
                cycle_identity_sha256, revision, from_phase, to_phase,
                evidence_json, evidence_sha256, observed_at,
                previous_transition_sha256, transition_sha256
            ) VALUES (?, 1, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                "f" * 64,
                PHASE_PREPARED,
                PHASE_PUBLICATION_COMMIT_UNKNOWN,
                evidence_json,
                hashlib.sha256(evidence_json.encode("ascii")).hexdigest(),
                UNKNOWN_AT,
                "e" * 64,
            ),
        )
        connection.commit()
    with pytest.raises(SamplingCycleCoordinatorError, match="foreign_key_check_failed"):
        coordinator.get_cycle(prepared.cycle_identity_sha256)


@pytest.mark.parametrize(
    "timestamp",
    ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"],
)
def test_extreme_aware_prepare_timestamp_is_totalized_to_fixed_error(
    tmp_path: Path, timestamp: str
) -> None:
    coordinator = _coordinator(tmp_path)
    with pytest.raises(
        SamplingCycleCoordinatorError,
        match="sampling_cycle_prepared_time_invalid",
    ):
        coordinator.prepare_cycle(_cycle(), prepared_at=timestamp)


def test_extreme_aware_transition_timestamp_is_totalized_to_fixed_error(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    prepared = coordinator.prepare_cycle(_cycle(), prepared_at=PREPARED_AT)
    evidence = _evidence(
        prepared,
        target=PHASE_PUBLICATION_COMMIT_UNKNOWN,
        observed_at="9999-12-31T23:59:59-14:00",
    )
    with pytest.raises(
        SamplingCycleCoordinatorError,
        match="sampling_cycle_evidence_time_invalid",
    ):
        coordinator.mark_publication_commit_unknown(prepared.cycle_identity_sha256, evidence)


def test_carry_head_rewrite_without_prior_cycle_read_is_bound_to_complete_cycle(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    lifecycle = _advance_to_lifecycle_verified(coordinator)
    _complete(coordinator, lifecycle)

    with sqlite3.connect(coordinator.path) as connection:
        head_row = connection.execute(
            "SELECT head_json FROM sampling_cycle_carry_heads WHERE process_instance_id = ?",
            (PROCESS,),
        ).fetchone()
        assert head_row is not None
        rewritten_head = json.loads(head_row[0])
        rewritten_head["carry"] = 0.66
        rewritten_json = _canonical(rewritten_head)
        rewritten_sha = hashlib.sha256(rewritten_json.encode("ascii")).hexdigest()
        trigger_sql = {
            name: connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
            ).fetchone()[0]
            for name in (
                "sampling_cycle_carry_heads_guard_update",
                "sampling_cycle_head_advances_no_update",
            )
        }
        for name in trigger_sql:
            connection.execute(f"DROP TRIGGER {name}")
        connection.execute(
            """
            UPDATE sampling_cycle_carry_head_advances
            SET next_head_json = ?, next_head_sha256 = ?
            WHERE process_instance_id = ? AND head_revision = 1
            """,
            (rewritten_json, rewritten_sha, PROCESS),
        )
        connection.execute(
            """
            UPDATE sampling_cycle_carry_heads
            SET head_json = ?, head_sha256 = ?
            WHERE process_instance_id = ?
            """,
            (rewritten_json, rewritten_sha, PROCESS),
        )
        for sql in trigger_sql.values():
            connection.execute(sql)
        connection.commit()

    with pytest.raises(
        SamplingCycleCoordinatorError,
        match="(completion_head_binding|cycle_binding)_invalid",
    ):
        coordinator.carry_head(PROCESS)


def test_cycle_identity_binds_every_low_level_identity_and_state_input(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator(tmp_path)
    cycle = _cycle()
    prepared = coordinator.prepare_cycle(cycle, prepared_at=PREPARED_AT)
    assert prepared.cycle_identity_sha256 == _sha(cycle)
    mutations: list[tuple[str, object]] = [
        ("sampling_plan_envelope_auth_tag", "a" * 64),
        ("sampling_plan_auth_key_id", "another-retained-key"),
        ("sampling_plan_hash", "b" * 64),
        ("sampling_plan_input_hash", "c" * 64),
        ("parent_policy_fingerprint", "d" * 64),
        ("checkpoint_id", "v2_hybrid_ckpt_dddddddd_eeeeeeeeeeeeeeee_ffffffffffff"),
        ("checkpoint_weight_sha256", "e" * 64),
        ("manifest_digest", "f" * 64),
        ("cohort_id", "8" * 64),
        ("carry_in", 0.26),
        ("carry_out", 0.76),
        ("single_candidate_ordinary_credit_in", 4),
        ("single_candidate_ordinary_credit_out", 5),
    ]
    for field, value in mutations:
        changed = deepcopy(cycle)
        changed[field] = value
        assert _sha(changed) != prepared.cycle_identity_sha256
    changed_member = deepcopy(cycle)
    changed_member["selected_receipts"][0]["receipt_hash"] = "9" * 64
    assert _sha(changed_member) != prepared.cycle_identity_sha256
    changed_draw = deepcopy(cycle)
    changed_draw["selected_receipts"][0]["draw_u53"] += 1
    assert _sha(changed_draw) != prepared.cycle_identity_sha256


def test_coordinator_surface_has_no_publish_or_lifecycle_append_operation() -> None:
    public = {name for name in dir(SamplingCycleCoordinator) if not name.startswith("_")}
    assert public == {
        "carry_head",
        "complete",
        "completion_head_transition",
        "get_cycle",
        "mark_lifecycle_verified",
        "mark_publication_commit_unknown",
        "mark_publication_readback_verified",
        "path",
        "prepare_cycle",
        "unresolved_for_process",
    }
