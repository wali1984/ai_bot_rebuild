from __future__ import annotations

import copy
import hashlib
import pickle
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_profiled_optimizer_admission_v1 as admission_module,
)
from v2.backend.app.services.native_trainer import (
    authenticated_profiled_optimizer_corpus_v1 as corpus_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    AuthenticatedProfiledOptimizerAdmissionV1Error,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (
    AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION,
    AuthenticatedProfiledOptimizerCorpusV1Error,
    build_authenticated_profiled_optimizer_corpus_v1,
    validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1,
    validate_authenticated_profiled_optimizer_execution_authorization_pair_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_PROFILE_SELECTION_MASK,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_optimizer_admission_v1 as admission_support,
)

adapter_evidence = admission_support.adapter_evidence


def _admitted(evidence: dict[str, Any]) -> Any:
    return admission_support._admit(evidence)


def _target_material(target: Any) -> dict[str, Any]:
    return {
        "schema_version": target.schema_version,
        "label_binding_sha256": target.label_binding_sha256,
        "action_index": target.action_index,
        "target_action": target.target_action,
        "signed_expected_move_after_cost_bps": target.signed_expected_move_after_cost_bps,
        "label_value_float64_sha256": target.label_value_float64_sha256,
        "label_available_at": target.label_available_at,
        "horizon_seconds": target.horizon_seconds,
        "canonical_finalized_label_bound": target.canonical_finalized_label_bound,
        "future_labels_excluded_from_feature_tensor": (
            target.future_labels_excluded_from_feature_tensor
        ),
        "static_action_threshold_used": target.static_action_threshold_used,
    }


def _replace_target(target: Any, **updates: Any) -> Any:
    material = {**_target_material(target), **updates}
    return replace(target, **updates, target_sha256=stable_sha256(material))


def _different_sha256(name: str) -> str:
    return hashlib.sha256(name.encode("ascii")).hexdigest()


def _row_inventory_material(row: Any, **updates: Any) -> dict[str, Any]:
    values = {
        "ordinal": row.ordinal,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "sample_identity_sha256": row.sample_identity_sha256,
        "label_binding_sha256": row.label_binding_sha256,
        "tensor_binding_sha256": row.tensor_binding_sha256,
        "logical_model_vector_sha256": row.logical_model_vector_sha256,
        "logical_projection_sha256": row.logical_projection_sha256,
        "model_input_float64_sha256": row.model_input_float64_sha256,
        "supervised_target_sha256": row.supervised_target.target_sha256,
        "target_label_value_float64_sha256": (row.supervised_target.label_value_float64_sha256),
        "model_feature_cutoff": row.model_feature_cutoff,
        "record_wide_evidence_cutoff": row.record_wide_evidence_cutoff,
        "source_feature_available_at": row.source_feature_available_at,
        "decision_feature_available_at": row.decision_feature_available_at,
        "feature_generated_at": row.feature_generated_at,
        "training_record_generated_at": row.training_record_generated_at,
        "decision_time": row.decision_time,
        "trainer_sample_available_at": row.trainer_sample_available_at,
        "label_available_at": row.label_available_at,
        "observation_time": row.observation_time,
    }
    return corpus_module._row_material(**{**values, **updates})


def _sample_identity_variant(admitted: Any) -> Any:
    return replace(admitted, sample_identity_sha256=_different_sha256("different-sample"))


def _tensor_identity_variant(admitted: Any) -> Any:
    return replace(admitted, tensor_binding_sha256=_different_sha256("different-tensor"))


def _label_identity_variant(admitted: Any) -> Any:
    label_sha256 = _different_sha256("different-label")
    target = _replace_target(admitted.supervised_target, label_binding_sha256=label_sha256)
    return replace(
        admitted,
        label_binding_sha256=label_sha256,
        supervised_target=target,
    )


def _model_bit_variant(admitted: Any) -> Any:
    values = list(admitted.model_input)
    availability_offset = 3 * len(LOGICAL_PROFILE_SELECTION_MASK)
    selected = LOGICAL_PROFILE_SELECTION_MASK.index(1)
    bit_ordinal = availability_offset + selected
    values[bit_ordinal] = 0.0 if values[bit_ordinal] == 1.0 else 1.0
    model_input = tuple(values)
    return replace(
        admitted,
        model_input=model_input,
        model_input_float64_sha256=admission_module._model_vector_sha256(model_input),
        logical_model_vector_sha256=admission_module._logical_model_vector_sha256(model_input),
    )


def _label_value_variant(admitted: Any) -> Any:
    target = admitted.supervised_target
    changed_value = target.signed_expected_move_after_cost_bps + 1.0
    value_sha256 = admission_module._float64_sha256(
        changed_value,
        reason="TEST_LABEL_VALUE_INVALID",
    )
    changed_target = _replace_target(
        target,
        signed_expected_move_after_cost_bps=changed_value,
        label_value_float64_sha256=value_sha256,
    )
    return replace(admitted, supervised_target=changed_target)


def _causal_clock_variant(admitted: Any) -> Any:
    changed_cutoff = admitted.model_feature_cutoff
    if changed_cutoff == admitted.record_wide_evidence_cutoff:
        changed_cutoff = admitted.decision_time
    return replace(admitted, record_wide_evidence_cutoff=changed_cutoff)


def test_full_manifest_corpus_binds_exact_inventory_and_authorizes_only_input(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    corpus = build_authenticated_profiled_optimizer_corpus_v1((admitted,))

    assert corpus.schema_version == AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION
    assert corpus.manifest_id == admitted.manifest_id
    assert corpus.manifest_total_profiled_samples == admitted.manifest_total_profiled_samples
    assert corpus.manifest_admitted_example_count == 1
    assert corpus.manifest_label_unavailable_count == 0
    assert corpus.completion_event_sha256 == admitted.completion_event_sha256
    assert corpus.external_authorization_envelope_sha256 == (
        admitted.external_authorization_envelope_sha256
    )
    assert corpus.witness_public_key_sha256 == admitted.witness_public_key_sha256
    assert corpus.admitted_ordinals == (admitted.ordinal,)
    assert len(corpus.rows) == 1
    assert corpus.rows[0].sample_identity_sha256 == admitted.sample_identity_sha256
    assert corpus.rows[0].label_binding_sha256 == admitted.label_binding_sha256
    assert corpus.rows[0].tensor_binding_sha256 == admitted.tensor_binding_sha256
    assert corpus.rows[0].model_input_float64_sha256 == admitted.model_input_float64_sha256
    assert corpus.rows[0].supervised_optimizer_input_authorized is True
    assert corpus.rows[0].supervised_optimizer_execution_authorized is False
    assert corpus.rows[0].ppo_behavior_policy_terms_enabled is False
    assert corpus.logical_profile_selection_mask == LOGICAL_PROFILE_SELECTION_MASK
    assert corpus.full_manifest_admitted_inventory_bound is True
    assert corpus.ordered_unique_admitted_ordinals_verified is True
    assert corpus.outcome_supervised_objective_only is True
    assert corpus.behavior_receipt_bound is False
    assert corpus.ppo_behavior_policy_terms_enabled is False
    assert corpus.supervised_optimizer_input_authorized is True
    assert corpus.supervised_optimizer_execution_authorized is False
    assert corpus.optimizer_execution_authorized is False
    assert all(
        value is False
        for value in (
            corpus.checkpoint_write_authorized,
            corpus.model_write_authorized,
            corpus.prediction_authorized,
            corpus.paper_trading_authorized,
            corpus.live_execution_authorized,
            corpus.order_submission_authorized,
            corpus.execution_authorized,
            corpus.runtime_wired,
        )
    )


def test_exact_before_after_inventory_authorizes_only_supervised_optimizer_execution(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))

    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=before,
        after=after,
    )

    assert before.rows is not after.rows
    assert before.rows[0] is not after.rows[0]
    assert before.rows[0].supervised_target is not after.rows[0].supervised_target
    assert before.causal_clock_range is not after.causal_clock_range
    assert authorization.before_after_inventory_equality_verified is True
    assert authorization.independent_temporal_materialization_verified is False
    assert authorization.before_ordered_admitted_inventory_sha256 == (
        authorization.after_ordered_admitted_inventory_sha256
    )
    assert authorization.before_causal_clock_range_sha256 == (
        authorization.after_causal_clock_range_sha256
    )
    assert authorization.supervised_optimizer_input_authorized is True
    assert authorization.supervised_optimizer_execution_authorized is True
    assert authorization.optimizer_execution_authorized is True
    assert authorization.outcome_supervised_objective_only is True
    assert authorization.ppo_behavior_policy_terms_enabled is False
    assert all(
        value is False
        for value in (
            authorization.checkpoint_write_authorized,
            authorization.model_write_authorized,
            authorization.prediction_authorized,
            authorization.paper_trading_authorized,
            authorization.live_execution_authorized,
            authorization.order_submission_authorized,
            authorization.execution_authorized,
            authorization.runtime_wired,
        )
    )


def test_same_object_cannot_impersonate_independent_before_after_snapshots(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    corpus = build_authenticated_profiled_optimizer_corpus_v1((admitted,))

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_DISTINCT_BEFORE_AFTER_SNAPSHOTS_REQUIRED",
    ):
        validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
            before=corpus,
            after=corpus,
        )

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_INVALID",
    ):
        replace(corpus)


def test_deep_dataclass_replace_clone_cannot_masquerade_as_second_materialization(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    corpus = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    cloned_target = replace(corpus.rows[0].supervised_target)

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_ROW_FACTORY_SEAL_INVALID",
    ):
        replace(corpus.rows[0], supervised_target=cloned_target)


@pytest.mark.parametrize("operation", (copy.copy, copy.deepcopy, pickle.dumps))
def test_corpus_graph_copy_or_pickle_transfer_fails_closed(
    adapter_evidence: dict[str, Any], operation: Any
) -> None:
    admitted = _admitted(adapter_evidence)
    corpus = build_authenticated_profiled_optimizer_corpus_v1((admitted,))

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_PICKLE_OR_COPY_FORBIDDEN",
    ):
        operation(corpus)


def test_seals_retain_exact_owner_references_and_authorization_is_pair_bound(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=before,
        after=after,
    )
    unrelated_before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    unrelated_after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))

    assert before._factory_seal._owner is before
    assert before.rows[0]._factory_seal._owner is before.rows[0]
    assert before.causal_clock_range._factory_seal._owner is before.causal_clock_range
    assert authorization._factory_seal._owner is authorization
    validate_authenticated_profiled_optimizer_execution_authorization_pair_v1(
        authorization=authorization,
        before=before,
        after=after,
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_EXECUTION_AUTHORIZATION_OWNER_PAIR_MISMATCH",
    ):
        validate_authenticated_profiled_optimizer_execution_authorization_pair_v1(
            authorization=authorization,
            before=unrelated_before,
            after=unrelated_after,
        )


def test_execution_authorization_cannot_grant_ppo_or_downstream_authority(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=before,
        after=after,
    )

    for field_name in (
        "ppo_behavior_policy_terms_enabled",
        "checkpoint_write_authorized",
        "model_write_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
    ):
        with pytest.raises(
            AuthenticatedProfiledOptimizerCorpusV1Error,
            match="PROFILED_OPTIMIZER_EXECUTION_AUTHORIZATION_INVALID",
        ):
            replace(authorization, **{field_name: True})


@pytest.mark.parametrize(
    "updates",
    (
        {
            "manifest_total_profiled_samples": 2,
            "manifest_admitted_example_count": 2,
            "completion_consumed_entry_count": 2,
            "completion_admitted_entry_count": 2,
        },
        {
            "manifest_total_profiled_samples": 3,
            "manifest_admitted_example_count": 2,
            "manifest_label_unavailable_count": 1,
            "completion_consumed_entry_count": 3,
            "completion_admitted_entry_count": 2,
            "completion_label_unavailable_count": 1,
            "ordinal": 3,
        },
        {"ordinal": 2},
    ),
    ids=("full-count", "label-unavailable-gap", "ordinal"),
)
def test_manifest_completeness_or_gap_cannot_be_fabricated_by_coherent_replace(
    adapter_evidence: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match=("PROFILED_OPTIMIZER_ADMISSION_(?:RESULT|FACTORY_SEAL)_INVALID"),
    ):
        replace(admitted, **updates)


def test_duplicate_factory_admission_cannot_expand_the_manifest_inventory(
    adapter_evidence: dict[str, Any],
) -> None:
    first = _admitted(adapter_evidence)
    second = _admitted(adapter_evidence)

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_FULL_MANIFEST_ADMITTED_COUNT_MISMATCH",
    ):
        build_authenticated_profiled_optimizer_corpus_v1((first, second))


@pytest.mark.parametrize(
    "variant",
    (
        _sample_identity_variant,
        _label_identity_variant,
        _tensor_identity_variant,
        _model_bit_variant,
        _label_value_variant,
        _causal_clock_variant,
    ),
    ids=(
        "sample_identity",
        "label_identity",
        "tensor_identity",
        "model_bit",
        "label_value",
        "causal_clock",
    ),
)
def test_coherent_admission_or_target_replace_cannot_change_authenticated_material(
    adapter_evidence: dict[str, Any],
    variant: Callable[[Any], Any],
) -> None:
    admitted = _admitted(adapter_evidence)

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match=("PROFILED_OPTIMIZER_(?:ADMISSION|OUTCOME_TARGET)_FACTORY_SEAL_INVALID"),
    ):
        variant(admitted)


def test_before_after_equality_rejects_inventory_truncation(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    object.__setattr__(after, "rows", ())

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_ROWS_REQUIRED",
    ):
        validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
            before=before,
            after=after,
        )


def test_witness_manifest_or_completion_identity_cannot_be_replaced(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_ADMISSION_FACTORY_SEAL_INVALID",
    ):
        replace(
            admitted,
            external_authorization_envelope_sha256=_different_sha256("different-envelope"),
        )


def test_coherent_row_inventory_replace_cannot_reuse_factory_token(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    row = build_authenticated_profiled_optimizer_corpus_v1((admitted,)).rows[0]
    changed_identity = _different_sha256("coherent-row-sample-substitution")
    changed_material = _row_inventory_material(
        row,
        sample_identity_sha256=changed_identity,
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_ROW_FACTORY_SEAL_INVALID",
    ):
        replace(
            row,
            sample_identity_sha256=changed_identity,
            row_inventory_sha256=stable_sha256(changed_material),
        )


def test_coherent_corpus_identity_replace_cannot_reuse_factory_token(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    corpus = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    changed_envelope = _different_sha256("coherent-corpus-envelope-substitution")
    common = corpus._common_material()
    common["external_authorization_envelope_sha256"] = changed_envelope
    material = corpus_module._corpus_material(
        common=common,
        admitted_ordinals=corpus.admitted_ordinals,
        ordered_admitted_inventory_sha256=corpus.ordered_admitted_inventory_sha256,
        causal_clock_range_sha256=corpus.causal_clock_range.causal_clock_range_sha256,
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_INVALID",
    ):
        replace(
            corpus,
            external_authorization_envelope_sha256=changed_envelope,
            corpus_contract_sha256=stable_sha256(material),
        )


def test_coherent_clock_range_replace_cannot_reuse_factory_token(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    clock_range = build_authenticated_profiled_optimizer_corpus_v1((admitted,)).causal_clock_range
    material = clock_range._as_material()
    material["earliest_record_wide_evidence_cutoff"] = admitted.decision_time
    material["latest_record_wide_evidence_cutoff"] = admitted.decision_time
    material.pop("causal_clock_range_sha256")

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_CLOCK_RANGE_FACTORY_SEAL_INVALID",
    ):
        replace(
            clock_range,
            earliest_record_wide_evidence_cutoff=admitted.decision_time,
            latest_record_wide_evidence_cutoff=admitted.decision_time,
            causal_clock_range_sha256=stable_sha256(material),
        )


def test_coherent_execution_authorization_replace_cannot_reuse_factory_token(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=build_authenticated_profiled_optimizer_corpus_v1((admitted,)),
        after=build_authenticated_profiled_optimizer_corpus_v1((admitted,)),
    )
    changed_manifest = _different_sha256("coherent-authorization-manifest-substitution")
    material = authorization._material(include_identity=False)
    material["manifest_id"] = changed_manifest

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_EXECUTION_AUTHORIZATION_FACTORY_SEAL_INVALID",
    ):
        replace(
            authorization,
            manifest_id=changed_manifest,
            inventory_equality_sha256=stable_sha256(material),
        )


def test_target_type_confusion_and_nonfinite_model_inputs_fail_closed(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    target_material = _target_material(admitted.supervised_target)
    target_material.update(action_index=True, target_action="long")

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_OUTCOME_TARGET_INVALID",
    ):
        replace(
            admitted.supervised_target,
            action_index=True,
            target_action="long",
            target_sha256=stable_sha256(target_material),
        )

    nonfinite = (float("nan"), *admitted.model_input[1:])
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_MODEL_INPUT_NONFINITE",
    ):
        replace(admitted, model_input=nonfinite)


def test_projection_or_logical_selection_mask_drift_is_rejected_directly(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    changed_mask = list(admitted.logical_profile_selection_mask)
    changed_mask[LOGICAL_PROFILE_SELECTION_MASK.index(1)] = 0
    changed_projection = replace(admitted)
    object.__setattr__(
        changed_projection,
        "projection_implementation_sha256",
        _different_sha256("different-projection"),
    )
    changed_selection = replace(admitted)
    object.__setattr__(
        changed_selection,
        "logical_profile_selection_mask",
        tuple(changed_mask),
    )
    object.__setattr__(
        changed_selection,
        "logical_profile_selection_mask_sha256",
        stable_sha256(changed_mask),
    )

    for changed in (changed_projection, changed_selection):
        with pytest.raises(
            AuthenticatedProfiledOptimizerCorpusV1Error,
            match="PROFILED_OPTIMIZER_CORPUS_ADMISSION_REVALIDATION_FAILED",
        ):
            build_authenticated_profiled_optimizer_corpus_v1((changed,))


def test_ppo_or_downstream_authority_cannot_be_enabled_after_inventory_build(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admitted(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    object.__setattr__(after, "ppo_behavior_policy_terms_enabled", True)

    with pytest.raises(
        AuthenticatedProfiledOptimizerCorpusV1Error,
        match="PROFILED_OPTIMIZER_CORPUS_INVALID",
    ):
        validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
            before=before,
            after=after,
        )
