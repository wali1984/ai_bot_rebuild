from __future__ import annotations

from collections.abc import ItemsView, Iterator, Mapping
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    build_authenticated_sampling_plan_envelope,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    BehaviorReceiptArchiveError,
    archive_authenticated_sampling_plan_envelope,
    archive_sampling_cohort_completeness_proof,
    archive_sampling_cohort_manifest,
    build_sampling_cohort_completeness_proof,
    build_sampling_cohort_manifest,
    load_sampling_cohort_manifest,
    verify_archived_sampling_cohort_manifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    adaptive_on_policy_lane_plan,
    canonical_sha256,
)
from v2.backend.tests.unit.services.native_trainer.test_authenticated_sampling_plan_archive import (
    AUTH_KEY,
    AUTH_KEY_ID,
    CHECKPOINT_HASH,
    COMPLETENESS_AT,
    MANIFEST_AT,
    PARENT_POLICY_FINGERPRINT,
    PROCESS_INSTANCE_ID,
    SEALED_AT,
    _envelope,
    _KeyResolver,
    _receipt,
    _sampling_plan,
)
from v2.backend.tests.unit.services.native_trainer.test_on_policy_behavior_receipt import (
    CHECKPOINT_ID,
)


def _zero_selected_plan() -> dict[str, object]:
    reference = _sampling_plan()
    return adaptive_on_policy_lane_plan(
        [],
        paper_margin_status=reference["paper_margin_inputs"],
        paper_entry_freeze=reference["paper_entry_freeze_inputs"],
        carry_in=0.0,
        single_candidate_ordinary_credit_in=0,
    )


def _zero_selected_envelope() -> dict[str, object]:
    return build_authenticated_sampling_plan_envelope(
        sampling_plan=_zero_selected_plan(),
        cycle_id="v2_cycle_sampling_plan_empty_manifest_unit",
        process_instance_id=PROCESS_INSTANCE_ID,
        parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256=CHECKPOINT_HASH,
        selected_index_draws={},
        sealed_at=SEALED_AT,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )


class _ExplodingTerminalDispositions(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        raise RuntimeError("mapping moved")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("mapping moved")

    def __len__(self) -> int:
        raise RuntimeError("mapping moved")

    def items(self) -> ItemsView[str, str]:
        raise RuntimeError("mapping moved")


def test_zero_selected_plan_archives_exact_empty_pre_admission_manifest(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _zero_selected_envelope()
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )

    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )

    assert manifest["members"] == []
    assert manifest["sampled_receipt_hashes"] == []
    assert manifest["sampled_receipt_count"] == 0
    assert manifest["pre_admission_manifest"] is True
    write = archive_sampling_cohort_manifest(
        manifest,
        key_resolver=resolver,
        root=tmp_path,
    )
    assert write.already_present is False
    assert (
        load_sampling_cohort_manifest(
            envelope["plan_instance_id"],
            key_resolver=resolver,
            root=tmp_path,
        )
        == manifest
    )
    assert (
        verify_archived_sampling_cohort_manifest(
            manifest,
            key_resolver=resolver,
            root=tmp_path,
        )
        == manifest
    )


def test_nonempty_selected_plan_still_rejects_empty_receipt_mapping() -> None:
    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_MANIFEST_NOT_COMPLETE",
    ):
        build_sampling_cohort_manifest(
            sampling_plan_envelope=_envelope(),
            receipts_by_selected_index={},
            key_resolver=_KeyResolver(AUTH_KEY),
            generated_at=MANIFEST_AT,
        )


def test_empty_manifest_rejects_boolean_sample_count_representation(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _zero_selected_envelope()
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    malformed = dict(manifest)
    malformed.pop("manifest_digest")
    malformed["sampled_receipt_count"] = False
    malformed["manifest_digest"] = canonical_sha256(malformed)

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_MANIFEST_MEMBERSHIP_INVALID",
    ):
        archive_sampling_cohort_manifest(
            malformed,
            key_resolver=resolver,
            root=tmp_path,
        )


def test_nonempty_completeness_proof_rejects_boolean_count_representations(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _envelope()
    receipt = _receipt()
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    proof = build_sampling_cohort_completeness_proof(
        manifest=manifest,
        terminal_dispositions={
            receipt["receipt_hash"]: "ENTRY_OUTCOME_FINALIZED",
        },
        generated_at=COMPLETENESS_AT,
    )
    malformed = dict(proof)
    malformed.pop("cohort_digest")
    malformed["sampled_receipt_count"] = True
    malformed["terminalized_receipt_count"] = True
    malformed["cohort_digest"] = canonical_sha256(malformed)

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_COMPLETENESS_COUNTS_OR_TIME_INVALID",
    ):
        archive_sampling_cohort_completeness_proof(
            malformed,
            key_resolver=resolver,
            root=tmp_path,
        )


def test_empty_cohort_cannot_masquerade_as_terminal_completeness_proof() -> None:
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=_zero_selected_envelope(),
        receipts_by_selected_index={},
        key_resolver=_KeyResolver(AUTH_KEY),
        generated_at=MANIFEST_AT,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_COMPLETENESS_EMPTY_COHORT",
    ):
        build_sampling_cohort_completeness_proof(
            manifest=manifest,
            terminal_dispositions={},
            generated_at=MANIFEST_AT,
        )


def test_empty_cohort_rejects_before_reading_terminal_dispositions() -> None:
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=_zero_selected_envelope(),
        receipts_by_selected_index={},
        key_resolver=_KeyResolver(AUTH_KEY),
        generated_at=MANIFEST_AT,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_COMPLETENESS_EMPTY_COHORT",
    ):
        build_sampling_cohort_completeness_proof(
            manifest=manifest,
            terminal_dispositions=_ExplodingTerminalDispositions(),
            generated_at=MANIFEST_AT,
        )
