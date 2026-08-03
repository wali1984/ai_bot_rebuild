from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    checkpoint as checkpoint_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_UNCERTAINTY_EVIDENCE_FIELDS,
    CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
    CONFIDENCE_UNCERTAINTY_METHOD,
    confidence_uncertainty_evidence_digest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_state import (
    PPOConsumptionLedger,
    candidate_progress_decision,
    canonical_digest,
    confidence_promotion_decision,
    ppo_consumption_update_key,
    training_partition_digest,
)


def _confidence_state(fingerprint: str) -> dict[str, object]:
    return {
        "schema_version": "v2_profitability_confidence_calibration_v2",
        "fitted": True,
        "reason": None,
        "temperature": 1.2,
        "sample": 4,
        "positive_outcomes": 2,
        "negative_outcomes": 2,
        "fit_partition": "PURGED_TRAIN_ONLY",
        "validation_rows_used": 0,
        "label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
        ),
        "confidence_head_schema_version": (
            "v2_per_directional_action_profitability_head_v1"
        ),
        "confidence_head_actions": ["long", "short"],
        "action_counts": {"long": 2, "short": 2},
        "model_parameter_fingerprint": fingerprint,
        "row_digest": "1" * 64,
    }


def _confidence_metrics(fingerprint: str) -> dict[str, object]:
    metrics: dict[str, object] = {
        "confidence_calibration_fitted": True,
        "confidence_calibration_fit_partition": "PURGED_TRAIN_ONLY",
        "confidence_calibration_validation_rows_used": 0,
        "confidence_calibration_label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
        ),
        "confidence_calibration_model_parameter_fingerprint": fingerprint,
        "validation_confidence_status": "EVALUATED_UNTOUCHED_FORWARD_PARTITION",
        "validation_confidence_partition_untouched": True,
        "validation_confidence_fit_validation_digest_disjoint": True,
        "validation_confidence_rows_used_for_fit": 0,
        "validation_confidence_label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
        ),
        "validation_confidence_fit_row_digest": "1" * 64,
        "validation_confidence_eligible_row_digest": "2" * 64,
        "validation_confidence_rows_evaluated": 4,
        "validation_confidence_long_rows": 2,
        "validation_confidence_short_rows": 2,
        "validation_confidence_raw_brier": 0.24,
        "validation_confidence_calibrated_brier": 0.22,
        "validation_confidence_raw_ece": 0.18,
        "validation_confidence_calibrated_ece": 0.16,
    }
    for action in ("long", "short"):
        metrics[f"validation_confidence_{action}_raw_brier"] = 0.25
        metrics[f"validation_confidence_{action}_calibrated_brier"] = 0.23
        metrics[f"validation_confidence_{action}_raw_ece"] = 0.2
        metrics[f"validation_confidence_{action}_calibrated_ece"] = 0.19
    for scope, count, brier_delta, ece_delta in (
        ("", 4, -0.02, -0.02),
        ("long_", 2, -0.02, -0.01),
        ("short_", 2, -0.02, -0.01),
    ):
        prefix = f"validation_confidence_{scope}"
        metrics[f"{prefix}paired_brier_delta_per_row"] = [
            brier_delta
        ] * count
        metrics[f"{prefix}paired_brier_delta_mean"] = brier_delta
        metrics[f"{prefix}paired_brier_delta_standard_error"] = 0.0
        metrics[
            f"{prefix}paired_brier_delta_one_standard_error_upper_bound"
        ] = brier_delta
        metrics[f"{prefix}paired_brier_uncertainty_available"] = True
        metrics[f"{prefix}paired_brier_non_regression_proven"] = True
        metrics[f"{prefix}ece_delta"] = ece_delta
        metrics[f"{prefix}ece_leave_one_out_delta"] = [ece_delta] * count
        metrics[f"{prefix}ece_jackknife_standard_error"] = 0.0
        metrics[f"{prefix}ece_one_standard_error_upper_bound"] = ece_delta
        metrics[f"{prefix}ece_uncertainty_available"] = True
        metrics[f"{prefix}ece_non_regression_proven"] = True
        metrics[f"{prefix}uncertainty_row_count"] = count
        metrics[f"{prefix}uncertainty_minimum_not_configured"] = True
        metrics[f"{prefix}uncertainty_mathematical_minimum_rows"] = 2
        scope_name = scope.rstrip("_").upper() if scope else "GLOBAL"
        metrics[f"{prefix}uncertainty_evidence_schema_version"] = (
            CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION
        )
        metrics[f"{prefix}uncertainty_scope"] = scope_name
        metrics[f"{prefix}uncertainty_method"] = CONFIDENCE_UNCERTAINTY_METHOD
        metrics[f"{prefix}uncertainty_evidence_digest"] = (
            confidence_uncertainty_evidence_digest(
                scope=scope_name,
                evidence={
                    field_name: metrics[f"{prefix}{field_name}"]
                    for field_name in CONFIDENCE_UNCERTAINTY_EVIDENCE_FIELDS
                },
            )
        )
    return metrics


def _progress_metrics(**overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "validation_split_pit_safe": True,
        "validation_rows": 10,
        "validation_policy_edge_rows_evaluated": 10,
        "optimizer_steps_this_cycle": 1,
        "parameter_hash_before": "a" * 64,
        "parameter_hash_after": "b" * 64,
        "validation_supervised_loss_before": 2.0,
        "validation_supervised_loss": 1.5,
        "validation_policy_edge_before_lower_confidence_bound_bps": -3.0,
        "validation_policy_edge_lower_confidence_bound_bps": -2.0,
    }
    metrics.update(overrides)
    return metrics


def test_candidate_progress_can_retain_negative_but_forward_improving_non_serving_model() -> None:
    decision = candidate_progress_decision(_progress_metrics())

    assert decision["candidate_progress_allowed"] is True
    assert decision["candidate_progress_reason"] == (
        "PIT_SAFE_NON_SERVING_PARETO_PROGRESS"
    )
    assert decision["validation_policy_edge_lcb_after_bps"] < 0.0
    assert decision["serving_authorized"] is False


def test_confidence_promotion_requires_checkpoint_bound_non_regressing_forward_metrics() -> None:
    fingerprint = "a" * 64
    decision = confidence_promotion_decision(
        training_metrics=_confidence_metrics(fingerprint),
        calibration_state=_confidence_state(fingerprint),
        candidate_policy_fingerprint=fingerprint,
    )

    assert decision["confidence_promotion_gate_passed"] is True
    assert decision["serving_authorized"] is False


@pytest.mark.parametrize(
    ("metric", "value", "reason"),
    [
        (
            "confidence_calibration_model_parameter_fingerprint",
            "b" * 64,
            "CONFIDENCE_METRIC_FINGERPRINT_NOT_BOUND_TO_CANDIDATE",
        ),
        (
            "validation_confidence_fit_validation_digest_disjoint",
            False,
            "CONFIDENCE_FIT_VALIDATION_PARTITIONS_NOT_PROVEN_DISJOINT",
        ),
        (
            "validation_confidence_long_calibrated_brier",
            0.26,
            "CONFIDENCE_LONG_BRIER_CALIBRATION_REGRESSED",
        ),
        (
            "validation_confidence_rows_evaluated",
            "not-an-integer",
            "CONFIDENCE_FORWARD_VALIDATION_ROWS_MISSING",
        ),
    ],
)
def test_confidence_promotion_fails_closed_on_identity_partition_or_metric_regression(
    metric: str,
    value: object,
    reason: str,
) -> None:
    fingerprint = "a" * 64
    metrics = _confidence_metrics(fingerprint)
    metrics[metric] = value

    decision = confidence_promotion_decision(
        training_metrics=metrics,
        calibration_state=_confidence_state(fingerprint),
        candidate_policy_fingerprint=fingerprint,
    )

    assert decision["confidence_promotion_gate_passed"] is False
    assert reason in decision["confidence_promotion_rejection_reasons"]


@pytest.mark.parametrize(
    ("metric", "value", "reason"),
    [
        (
            "validation_confidence_long_uncertainty_row_count",
            2.5,
            "CONFIDENCE_LONG_ROW_COUNT_INVALID",
        ),
        (
            "validation_confidence_long_paired_brier_delta_mean",
            -0.01,
            "CONFIDENCE_LONG_PAIRED_BRIER_MEAN_ARITHMETIC_MISMATCH",
        ),
        (
            "validation_confidence_long_paired_brier_delta_per_row",
            [-0.02],
            "CONFIDENCE_LONG_PAIRED_BRIER_DELTAS_MISSING",
        ),
        (
            "validation_confidence_long_uncertainty_evidence_digest",
            "f" * 64,
            "CONFIDENCE_LONG_UNCERTAINTY_EVIDENCE_DIGEST_MISMATCH",
        ),
    ],
)
def test_confidence_promotion_rederives_uncertainty_and_rejects_tamper(
    metric: str,
    value: object,
    reason: str,
) -> None:
    fingerprint = "a" * 64
    metrics = _confidence_metrics(fingerprint)
    metrics[metric] = value

    decision = confidence_promotion_decision(
        training_metrics=metrics,
        calibration_state=_confidence_state(fingerprint),
        candidate_policy_fingerprint=fingerprint,
    )

    assert decision["confidence_promotion_gate_passed"] is False
    assert reason in decision["confidence_promotion_rejection_reasons"]


def test_confidence_promotion_rejects_single_row_direction_uncertainty() -> None:
    fingerprint = "a" * 64
    metrics = _confidence_metrics(fingerprint)
    metrics["validation_confidence_rows_evaluated"] = 3
    metrics["validation_confidence_long_rows"] = 1
    prefix = "validation_confidence_long_"
    metrics[f"{prefix}paired_brier_delta_per_row"] = [-0.02]
    metrics[f"{prefix}ece_leave_one_out_delta"] = []
    metrics[f"{prefix}paired_brier_delta_mean"] = -0.02
    metrics[f"{prefix}paired_brier_delta_standard_error"] = None
    metrics[f"{prefix}paired_brier_delta_one_standard_error_upper_bound"] = None
    metrics[f"{prefix}paired_brier_uncertainty_available"] = False
    metrics[f"{prefix}paired_brier_non_regression_proven"] = False
    metrics[f"{prefix}ece_jackknife_standard_error"] = None
    metrics[f"{prefix}ece_one_standard_error_upper_bound"] = None
    metrics[f"{prefix}ece_uncertainty_available"] = False
    metrics[f"{prefix}ece_non_regression_proven"] = False
    metrics[f"{prefix}uncertainty_row_count"] = 1

    decision = confidence_promotion_decision(
        training_metrics=metrics,
        calibration_state=_confidence_state(fingerprint),
        candidate_policy_fingerprint=fingerprint,
    )

    assert decision["confidence_promotion_gate_passed"] is False
    assert (
        "CONFIDENCE_LONG_PAIRED_UNCERTAINTY_NOT_IDENTIFIABLE"
        in decision["confidence_promotion_rejection_reasons"]
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"validation_split_pit_safe": False},
            "CANDIDATE_VALIDATION_SPLIT_PIT_UNSAFE",
        ),
        (
            {"validation_supervised_loss": 2.1},
            "CANDIDATE_VALIDATION_LOSS_REGRESSED",
        ),
        (
            {
                "validation_policy_edge_lower_confidence_bound_bps": -4.0,
            },
            "CANDIDATE_VALIDATION_EDGE_LCB_REGRESSED",
        ),
        (
            {
                "validation_supervised_loss": 2.0,
                "validation_policy_edge_lower_confidence_bound_bps": -3.0,
            },
            "CANDIDATE_NO_STRICT_FORWARD_VALIDATION_IMPROVEMENT",
        ),
    ],
)
def test_candidate_progress_fails_closed_on_unsafe_or_non_improving_validation(
    overrides: dict[str, object],
    reason: str,
) -> None:
    decision = candidate_progress_decision(_progress_metrics(**overrides))

    assert decision["candidate_progress_allowed"] is False
    assert reason in decision["candidate_progress_rejection_reasons"]


def test_consumption_key_binds_receipt_outcome_and_parent_policy() -> None:
    first = ppo_consumption_update_key(
        receipt_hash="a" * 64,
        finalized_outcome_digest="b" * 64,
        parent_policy_fingerprint="c" * 64,
    )
    second = ppo_consumption_update_key(
        receipt_hash="a" * 64,
        finalized_outcome_digest="b" * 64,
        parent_policy_fingerprint="d" * 64,
    )

    assert len(first) == 64
    assert first != second


def test_ppo_consumption_ledger_is_append_only_idempotent_and_tamper_evident(
    tmp_path: Path,
) -> None:
    ledger = PPOConsumptionLedger(tmp_path / "ppo_consumption.sqlite3")
    parent = "c" * 64
    receipt = "a" * 64
    outcome = "b" * 64
    update_key = ppo_consumption_update_key(
        receipt_hash=receipt,
        finalized_outcome_digest=outcome,
        parent_policy_fingerprint=parent,
    )
    partition = training_partition_digest([update_key])
    attempt = {
        "update_key": update_key,
        "receipt_hash": receipt,
        "finalized_outcome_digest": outcome,
        "parent_policy_fingerprint": parent,
    }
    owner = ledger.process_owner_id()
    claim = ledger.claim_attempts(attempts=[attempt], owner_id=owner)
    fenced = ledger.claim_attempts(
        attempts=[attempt],
        owner_id="00000000-0000-0000-0000-000000000000:999999999:0",
    )

    assert claim["claimed_update_keys"] == [update_key]
    assert fenced["claimed_update_keys"] == []
    assert fenced["unavailable_update_keys"] == [update_key]
    ledger.mark_optimizer_started(
        owner_id=owner,
        update_keys=[update_key],
        partition_digest=partition,
    )

    first = ledger.record_attempts(
        attempts=[attempt],
        child_policy_fingerprint="d" * 64,
        disposition="REJECTED_NOT_DURABLE",
        checkpoint_id=None,
        checkpoint_path=None,
        checkpoint_sha256=None,
        partition_digest=partition,
        owner_id=owner,
    )
    second = ledger.record_attempts(
        attempts=[attempt],
        child_policy_fingerprint="d" * 64,
        disposition="REJECTED_NOT_DURABLE",
        checkpoint_id=None,
        checkpoint_path=None,
        checkpoint_sha256=None,
        partition_digest=partition,
    )

    assert first["attempts_inserted"] == 1
    assert second["attempts_inserted"] == 0
    assert ledger.consumed_update_keys() == {update_key}
    assert [row["update_key"] for row in ledger.attempt_rows()] == [update_key]
    assert [
        row["update_key"] for row in ledger.attempt_rows([update_key])
    ] == [update_key]
    with ledger._connect() as connection:  # noqa: SLF001 - durable claim probe
        claim_count = connection.execute("SELECT COUNT(*) FROM ppo_claims").fetchone()[0]
    assert claim_count == 0

    with pytest.raises(RuntimeError, match="stable_key_semantic_conflict"):
        ledger.record_attempts(
            attempts=[attempt],
            child_policy_fingerprint="e" * 64,
            disposition="RETRY_MUST_NOT_REWRITE",
            checkpoint_id=None,
            checkpoint_path=None,
            checkpoint_sha256=None,
            partition_digest=partition,
        )

    with ledger._connect() as connection:  # noqa: SLF001 - adversarial corruption probe
        connection.execute(
            "UPDATE ppo_attempts SET disposition = 'FORGED' WHERE update_key = ?",
            (update_key,),
        )
        connection.commit()

    integrity = ledger.verify_integrity()
    assert integrity["integrity_verified"] is False
    assert "PPO_LEDGER_CHAIN_HASH_MISMATCH" in integrity[
        "integrity_rejection_reasons"
    ]
    with pytest.raises(RuntimeError, match="integrity_failed"):
        ledger.consumed_update_keys()


def test_consumption_ledger_v2_migrates_optimizer_fence_columns_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ppo_consumption.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE ppo_attempts (
                sequence INTEGER NOT NULL UNIQUE,
                update_key TEXT PRIMARY KEY,
                receipt_hash TEXT NOT NULL,
                finalized_outcome_digest TEXT NOT NULL,
                parent_policy_fingerprint TEXT NOT NULL,
                child_policy_fingerprint TEXT NOT NULL,
                disposition TEXT NOT NULL,
                checkpoint_id TEXT,
                checkpoint_path TEXT,
                checkpoint_sha256 TEXT,
                training_partition_digest TEXT NOT NULL,
                recorded_utc TEXT NOT NULL,
                previous_chain_hash TEXT NOT NULL,
                chain_hash TEXT NOT NULL
            );
            CREATE TABLE ppo_claims (
                update_key TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                receipt_hash TEXT NOT NULL,
                finalized_outcome_digest TEXT NOT NULL,
                parent_policy_fingerprint TEXT NOT NULL,
                claimed_utc TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES(?, ?)",
            (
                ("schema_version", "v2_exact_ppo_consumption_ledger_v2"),
                ("row_count", "0"),
                ("chain_tip", "0" * 64),
            ),
        )
        connection.commit()

    ledger = PPOConsumptionLedger(path)

    assert ledger.verify_integrity()["integrity_verified"] is True
    with sqlite3.connect(path) as connection:
        schema = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
        claim_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(ppo_claims)")
        }
    assert schema == "v2_exact_ppo_consumption_ledger_v4"
    assert {
        "optimizer_started_utc",
        "optimizer_partition_digest",
        "optimizer_partition_index",
    } <= claim_columns


def test_existing_nonempty_ledger_activates_archive_contract_after_legacy_tip(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ppo_consumption.sqlite3"
    ledger = PPOConsumptionLedger(path)
    attempt = {
        "receipt_hash": "a" * 64,
        "finalized_outcome_digest": "b" * 64,
        "parent_policy_fingerprint": "c" * 64,
    }
    attempt["update_key"] = ppo_consumption_update_key(**attempt)
    owner = ledger.process_owner_id()
    ledger.claim_attempts(attempts=[attempt], owner_id=owner)
    partition = training_partition_digest([str(attempt["update_key"])])
    ledger.mark_optimizer_started(
        owner_id=owner,
        update_keys=[str(attempt["update_key"])],
        partition_digest=partition,
    )
    ledger.record_attempts(
        attempts=[attempt],
        child_policy_fingerprint="d" * 64,
        disposition="LEGACY_TERMINAL_ATTEMPT",
        checkpoint_id=None,
        checkpoint_path=None,
        checkpoint_sha256=None,
        partition_digest=partition,
        owner_id=owner,
    )
    with ledger._connect() as connection:  # noqa: SLF001 - migration fixture
        connection.execute(
            "DELETE FROM metadata WHERE key LIKE 'receipt_archive_%'"
        )
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
            ("v2_exact_ppo_consumption_ledger_v2",),
        )
        connection.commit()

    migrated = PPOConsumptionLedger(path)
    status = migrated.archive_sync_status()

    assert status["archive_sync_integrity_verified"] is True
    assert status["activation_sequence"] == 2
    assert status["sync_sequence"] == 1
    assert status["legacy_terminal_attempts_not_archive_bound"] == 1
    assert status["unsynced_terminal_attempts"] == 0
    assert migrated.unsynced_attempt_rows() == []


def test_v3_unbound_watermark_is_reset_for_exact_archive_event_revalidation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ppo_consumption.sqlite3"
    ledger = PPOConsumptionLedger(path)
    attempt = {
        "receipt_hash": "a" * 64,
        "finalized_outcome_digest": "b" * 64,
        "parent_policy_fingerprint": "c" * 64,
    }
    attempt["update_key"] = ppo_consumption_update_key(**attempt)
    owner = ledger.process_owner_id()
    ledger.claim_attempts(attempts=[attempt], owner_id=owner)
    partition = training_partition_digest([str(attempt["update_key"])])
    ledger.mark_optimizer_started(
        owner_id=owner,
        update_keys=[str(attempt["update_key"])],
        partition_digest=partition,
    )
    ledger.record_attempts(
        attempts=[attempt],
        child_policy_fingerprint="d" * 64,
        disposition="UNIT_TERMINAL_ATTEMPT",
        checkpoint_id=None,
        checkpoint_path=None,
        checkpoint_sha256=None,
        partition_digest=partition,
        owner_id=owner,
    )
    terminal = ledger.attempt_rows()[0]
    ledger.mark_archive_synced(
        sequence=1,
        chain_hash=str(terminal["chain_hash"]),
        receipt_hash=str(terminal["receipt_hash"]),
        trainer_consumed_event_hash="e" * 64,
    )

    legacy_state = {
        "schema_version": "v2_exact_ppo_receipt_archive_sync_v1",
        "activation_sequence": 1,
        "sync_sequence": 1,
        "sync_chain_hash": str(terminal["chain_hash"]),
    }
    with ledger._connect() as connection:  # noqa: SLF001 - migration fixture
        connection.execute("DELETE FROM ppo_archive_sync_bindings")
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
            ("v2_exact_ppo_consumption_ledger_v3",),
        )
        connection.execute(
            "UPDATE metadata SET value = ? "
            "WHERE key = 'receipt_archive_sync_schema_version'",
            ("v2_exact_ppo_receipt_archive_sync_v1",),
        )
        connection.execute(
            "UPDATE metadata SET value = ? "
            "WHERE key = 'receipt_archive_sync_state_digest'",
            (canonical_digest(legacy_state),),
        )
        connection.execute(
            "DELETE FROM metadata "
            "WHERE key = 'receipt_archive_sync_binding_chain_tip'"
        )
        connection.commit()

    migrated = PPOConsumptionLedger(path)
    status = migrated.archive_sync_status()

    assert status["archive_sync_integrity_verified"] is True
    assert status["activation_sequence"] == 1
    assert status["sync_sequence"] == 0
    assert status["archive_event_binding_count"] == 0
    assert [row["sequence"] for row in migrated.unsynced_attempt_rows()] == [1]


def test_receipt_archive_watermark_is_contiguous_idempotent_and_tamper_evident(
    tmp_path: Path,
) -> None:
    ledger = PPOConsumptionLedger(tmp_path / "ppo_consumption.sqlite3")
    for index, receipt in enumerate(("a" * 64, "d" * 64)):
        attempt = {
            "receipt_hash": receipt,
            "finalized_outcome_digest": chr(ord("b") + index) * 64,
            "parent_policy_fingerprint": "c" * 64,
        }
        attempt["update_key"] = ppo_consumption_update_key(**attempt)
        owner = ledger.process_owner_id()
        ledger.claim_attempts(attempts=[attempt], owner_id=owner)
        partition = training_partition_digest([str(attempt["update_key"])])
        ledger.mark_optimizer_started(
            owner_id=owner,
            update_keys=[str(attempt["update_key"])],
            partition_digest=partition,
        )
        ledger.record_attempts(
            attempts=[attempt],
            child_policy_fingerprint="f" * 64,
            disposition="UNIT_TERMINAL_ATTEMPT",
            checkpoint_id=None,
            checkpoint_path=None,
            checkpoint_sha256=None,
            partition_digest=partition,
            owner_id=owner,
        )

    unsynced = ledger.unsynced_attempt_rows()
    assert [row["sequence"] for row in unsynced] == [1, 2]
    first = unsynced[0]
    advanced = ledger.mark_archive_synced(
        sequence=int(first["sequence"]),
        chain_hash=str(first["chain_hash"]),
        receipt_hash=str(first["receipt_hash"]),
        trainer_consumed_event_hash="1" * 64,
    )
    repeated = ledger.mark_archive_synced(
        sequence=int(first["sequence"]),
        chain_hash=str(first["chain_hash"]),
        receipt_hash=str(first["receipt_hash"]),
        trainer_consumed_event_hash="1" * 64,
    )
    assert advanced["watermark_advanced"] is True
    assert len(str(advanced["sync_state_digest"])) == 64
    assert repeated["watermark_advanced"] is False
    with pytest.raises(RuntimeError, match="not_contiguous"):
        ledger.mark_archive_synced(
            sequence=3,
            chain_hash="e" * 64,
            receipt_hash="e" * 64,
            trainer_consumed_event_hash="3" * 64,
        )
    second = ledger.unsynced_attempt_rows()[0]
    ledger.mark_archive_synced(
        sequence=int(second["sequence"]),
        chain_hash=str(second["chain_hash"]),
        receipt_hash=str(second["receipt_hash"]),
        trainer_consumed_event_hash="2" * 64,
    )
    assert ledger.unsynced_attempt_rows() == []

    with ledger._connect() as connection:  # noqa: SLF001 - corruption probe
        connection.execute(
            "UPDATE metadata SET value = ? "
            "WHERE key = 'receipt_archive_sync_chain_hash'",
            ("0" * 64,),
        )
        connection.commit()
    status = ledger.archive_sync_status()
    assert status["archive_sync_integrity_verified"] is False
    assert "PPO_RECEIPT_ARCHIVE_SYNC_CHAIN_HASH_MISMATCH" in status[
        "archive_sync_rejection_reasons"
    ]


def test_checkpoint_ids_are_parameter_content_addressed_and_hash_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "candidate")
    model = V2HybridPolicyModel(input_dim=4, seed=31)
    first = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_evidence={"candidate_progress_allowed": True},
    )
    if model.torch_available:
        assert model.torch is not None and model.net is not None
        with model.torch.no_grad():
            next(model.net.parameters()).view(-1)[0].add_(0.001)
    else:
        model._fallback_weights[0] += 0.001  # noqa: SLF001
    second = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        parent_checkpoint_id=first.checkpoint_id,
        parent_policy_fingerprint=first.model_parameter_fingerprint,
        checkpoint_evidence={"candidate_progress_allowed": True},
    )

    assert first.checkpoint_id != second.checkpoint_id
    assert first.weight_file_sha256 and second.weight_file_sha256
    assert Path(first.weight_file_path or "").is_file()
    assert Path(second.weight_file_path or "").is_file()
    restored = V2HybridPolicyModel(input_dim=4, seed=31)
    load = manager.load_latest_weights(restored)
    assert load["latest_checkpoint_loadable"] is True
    assert load["model_parameter_fingerprint_verified"] is True
    assert load["checkpoint_evidence_verified"] is True
    assert load["checkpoint_identity_verified"] is True
    assert load["lineage_kind"] == "NON_SERVING_TRAINING_CANDIDATE"

    second_path = Path(second.weight_file_path or "")
    second_path.write_bytes(second_path.read_bytes() + b"tamper")
    tampered = manager.load_latest_weights(V2HybridPolicyModel(input_dim=4, seed=31))
    assert tampered["latest_checkpoint_loadable"] is False
    assert tampered["load_status"] == "WEIGHT_BLOB_SHA256_MISMATCH"


def test_expected_checkpoint_guard_blocks_reselection_before_npz_deserialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "serving")
    model = V2HybridPolicyModel(input_dim=4, seed=33)
    first = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="VERIFIED_SERVING_POLICY",
        checkpoint_evidence={"checkpoint_role": "VERIFIED_SERVING_POLICY"},
    )
    if model.torch_available:
        assert model.torch is not None and model.net is not None
        with model.torch.no_grad():
            next(model.net.parameters()).view(-1)[0].add_(0.001)
    else:
        model._fallback_weights[0] += 0.001  # noqa: SLF001
    second = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="VERIFIED_SERVING_POLICY",
        parent_checkpoint_id=first.checkpoint_id,
        parent_policy_fingerprint=first.model_parameter_fingerprint,
        checkpoint_evidence={"checkpoint_role": "VERIFIED_SERVING_POLICY"},
    )
    expected_load = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=33),
        allowed_lineage_kinds=frozenset({"VERIFIED_SERVING_POLICY"}),
        expected_checkpoint_id=second.checkpoint_id,
    )
    assert expected_load["latest_checkpoint_loadable"] is True
    assert expected_load["checkpoint_id"] == second.checkpoint_id

    def npz_deserialization_forbidden(
        *_args: object,
        **_kwargs: object,
    ) -> None:
        raise AssertionError(
            "unexpected checkpoint must be rejected before NPZ deserialization"
        )

    monkeypatch.setattr(
        checkpoint_module,
        "_safe_npz_semantics",
        npz_deserialization_forbidden,
    )
    metadata_only = manager.manifests(
        input_dim=4,
        model_id=model.model_id,
        allowed_lineage_kinds=frozenset({"VERIFIED_SERVING_POLICY"}),
        require_weight_blob=True,
        verify_lineage_artifacts=False,
    )
    assert metadata_only[0].checkpoint_id == second.checkpoint_id
    invalid_guard = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=33),
        allowed_lineage_kinds=frozenset({"VERIFIED_SERVING_POLICY"}),
        expected_checkpoint_id=f" {second.checkpoint_id}",
    )
    assert invalid_guard["load_status"] == "EXPECTED_CHECKPOINT_ID_INVALID"
    assert invalid_guard["model_state_restored"] is False
    result = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=33),
        allowed_lineage_kinds=frozenset({"VERIFIED_SERVING_POLICY"}),
        expected_checkpoint_id=first.checkpoint_id,
    )

    assert first.checkpoint_id != second.checkpoint_id
    assert result["load_status"] == "EXPECTED_CHECKPOINT_ID_MISMATCH"
    assert result["checkpoint_id"] == second.checkpoint_id
    assert result["expected_checkpoint_id"] == first.checkpoint_id
    assert result["latest_checkpoint_loadable"] is False
    assert result["model_state_restored"] is False


def test_checkpoint_rejects_manifest_evidence_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "candidate")
    model = V2HybridPolicyModel(input_dim=4, seed=41)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_evidence={"candidate_progress_allowed": True},
    )
    manifest_path = Path(manifest.path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["checkpoint_evidence"]["candidate_progress_allowed"] = False
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    rejected = manager.load_latest_weights(V2HybridPolicyModel(input_dim=4, seed=41))

    assert rejected["latest_checkpoint_loadable"] is False
    assert rejected["checkpoint_evidence_verified"] is False
    assert rejected["load_status"] == "CHECKPOINT_EVIDENCE_DIGEST_MISMATCH"


def test_orphan_claim_is_reconciled_from_fully_verified_durable_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    ledger = PPOConsumptionLedger(tmp_path / "ppo_consumption.sqlite3")
    model = V2HybridPolicyModel(input_dim=4, seed=51)
    parent = "c" * 64
    receipt = "a" * 64
    outcome = "b" * 64
    update_key = ppo_consumption_update_key(
        receipt_hash=receipt,
        finalized_outcome_digest=outcome,
        parent_policy_fingerprint=parent,
    )
    attempt = {
        "update_key": update_key,
        "receipt_hash": receipt,
        "finalized_outcome_digest": outcome,
        "parent_policy_fingerprint": parent,
    }
    dead_owner = "00000000-0000-0000-0000-000000000000:999999999:0"
    assert ledger.claim_attempts(
        attempts=[attempt], owner_id=dead_owner
    )["claimed_update_keys"] == [update_key]
    partition = training_partition_digest([update_key])
    ledger.mark_optimizer_started(
        owner_id=dead_owner,
        update_keys=[update_key],
        partition_digest=partition,
    )
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "candidate")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        consumed_ppo_update_keys=(update_key,),
        training_partition_digest=partition,
        checkpoint_evidence={
            "ledger_disposition": "NON_SERVING_CANDIDATE_PERSISTED"
        },
    )
    load = manager.load_latest_weights(V2HybridPolicyModel(input_dim=4, seed=51))

    reconciled = ledger.reconcile_verified_checkpoint_attempts(
        checkpoint_load=load,
        disposition="NON_SERVING_CANDIDATE_PERSISTED",
    )

    assert manifest.checkpoint_id == load["checkpoint_id"]
    assert reconciled["reconciled_update_keys"] == 1
    assert ledger.consumed_update_keys() == {update_key}


def test_post_fence_crash_is_consumed_fail_closed_while_pre_fence_claim_releases(
    tmp_path: Path,
) -> None:
    ledger = PPOConsumptionLedger(tmp_path / "ppo_consumption.sqlite3")
    dead_owner = "00000000-0000-0000-0000-000000000000:999999999:0"
    parent = "c" * 64
    attempts = []
    for receipt, outcome in (("a" * 64, "b" * 64), ("d" * 64, "e" * 64)):
        update_key = ppo_consumption_update_key(
            receipt_hash=receipt,
            finalized_outcome_digest=outcome,
            parent_policy_fingerprint=parent,
        )
        attempts.append(
            {
                "update_key": update_key,
                "receipt_hash": receipt,
                "finalized_outcome_digest": outcome,
                "parent_policy_fingerprint": parent,
            }
        )
    claimed = ledger.claim_attempts(attempts=attempts, owner_id=dead_owner)
    assert claimed["claimed_update_keys"] == [
        attempt["update_key"] for attempt in attempts
    ]
    started_key = str(attempts[0]["update_key"])
    ledger.mark_optimizer_started(
        owner_id=dead_owner,
        update_keys=[started_key],
        partition_digest=training_partition_digest([started_key]),
    )
    reentry = ledger.claim_attempts(
        attempts=[attempts[0]],
        owner_id=dead_owner,
    )
    assert reentry["claimed_update_keys"] == []
    assert reentry["unavailable_update_keys"] == [started_key]

    released = ledger.recover_orphaned_claims()
    ambiguous = ledger.record_ambiguous_dead_optimizer_attempts()

    assert released == {
        "orphaned_claims_released": 1,
        "active_claims_preserved": 0,
        "optimizer_started_claims_preserved": 1,
    }
    assert ambiguous["ambiguous_optimizer_attempts_consumed"] == 1
    assert ledger.consumed_update_keys() == {started_key}


def test_every_historical_checkpoint_can_be_verified_without_model_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "candidate")
    model = V2HybridPolicyModel(input_dim=4, seed=53)
    first = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_evidence={"ledger_disposition": "NON_SERVING_CANDIDATE_PERSISTED"},
    )
    if model.torch_available:
        assert model.torch is not None and model.net is not None
        with model.torch.no_grad():
            next(model.net.parameters()).view(-1)[0].add_(0.001)
    else:
        model._fallback_weights[0] += 0.001  # noqa: SLF001
    second = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        parent_checkpoint_id=first.checkpoint_id,
        parent_policy_fingerprint=first.model_parameter_fingerprint,
        checkpoint_evidence={"ledger_disposition": "NON_SERVING_CANDIDATE_PERSISTED"},
    )

    manifests = manager.manifests(
        allowed_lineage_kinds=frozenset({"NON_SERVING_TRAINING_CANDIDATE"}),
        require_weight_blob=True,
    )
    results = [manager.verify_manifest_artifact(manifest) for manifest in manifests]

    assert {manifest.checkpoint_id for manifest in manifests} == {
        first.checkpoint_id,
        second.checkpoint_id,
    }
    assert all(result["checkpoint_artifact_verified"] for result in results)
    assert all(result["verification_is_non_mutating"] for result in results)
    first_path = Path(first.weight_file_path or "")
    first_path.write_bytes(first_path.read_bytes() + b"tamper")
    rejected = manager.verify_manifest_artifact(first)
    assert rejected["checkpoint_artifact_verified"] is False
    assert "WEIGHT_BLOB_SHA256_MISMATCH" in rejected[
        "artifact_verification_rejection_reasons"
    ]


def test_manifest_enumeration_fails_closed_on_semantically_malformed_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model_dir = tmp_path / ".local_models" / "candidate"
    manager = V2HybridCheckpointManager(model_dir)
    model = V2HybridPolicyModel(input_dim=4, seed=59)
    manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_evidence={"ledger_disposition": "NON_SERVING_CANDIDATE_PERSISTED"},
    )
    malformed = model_dir / "v2_hybrid_ckpt_ffffffff_ffffffffffffffff_ffffffffffff.json"
    malformed.write_text(
        '{"checkpoint_id":"v2_hybrid_ckpt_ffffffff_ffffffffffffffff_ffffffffffff",'
        '"model_id":"model","input_dim":true,"weight_blob_written":true}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="checkpoint_manifest_scan_invalid"):
        manager.manifests()


def test_manifest_enumeration_fails_closed_on_nonfinite_json_constant(
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / ".local_models" / "candidate"
    manager = V2HybridCheckpointManager(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    malformed = model_dir / "v2_hybrid_ckpt_ffffffff_ffffffffffffffff_ffffffffffff.json"
    malformed.write_text(
        '{"checkpoint_id":"v2_hybrid_ckpt_ffffffff_ffffffffffffffff_ffffffffffff",'
        '"model_id":"model","input_dim":4,"weight_blob_written":true,'
        '"confidence_calibration_temperature":NaN}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="checkpoint_manifest_scan_invalid"):
        manager.manifests()


def test_same_semantic_checkpoint_is_create_or_identical_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "candidate")
    model = V2HybridPolicyModel(input_dim=4, seed=61)
    kwargs = {
        "model": model,
        "input_dim": 4,
        "device": model.device,
        "cuda_active": model.cuda_active,
        "lineage_kind": "NON_SERVING_TRAINING_CANDIDATE",
        "checkpoint_evidence": {"candidate_progress_allowed": True},
    }
    first = manager.write_checkpoint(**kwargs)
    weight_path = Path(first.weight_file_path or "")
    original_inode = weight_path.stat().st_ino
    original_bytes = weight_path.read_bytes()

    def overwrite_forbidden(_path: Path) -> dict[str, object]:
        raise AssertionError("idempotent semantic checkpoint attempted an overwrite")

    monkeypatch.setattr(model, "save_weight_blob", overwrite_forbidden)
    second = manager.write_checkpoint(**kwargs)

    assert second == first
    assert weight_path.stat().st_ino == original_inode
    assert weight_path.read_bytes() == original_bytes

    metadata_only_retry = manager.write_checkpoint(
        **{**kwargs, "write_weight_blob": False}
    )
    assert metadata_only_retry == first
    assert weight_path.stat().st_ino == original_inode
    assert weight_path.read_bytes() == original_bytes


def test_checkpoint_load_is_explicitly_lineage_filtered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "mixed")
    model = V2HybridPolicyModel(input_dim=4, seed=71)
    manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_evidence={"checkpoint_role": "NON_SERVING_TRAINING_CANDIDATE"},
    )

    blocked = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=71),
        allowed_lineage_kinds=frozenset({"VERIFIED_SERVING_POLICY"}),
    )
    candidate = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=71),
        allowed_lineage_kinds=frozenset({"NON_SERVING_TRAINING_CANDIDATE"}),
    )

    assert blocked["latest_checkpoint_loadable"] is False
    assert blocked["load_status"] == "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST"
    assert candidate["latest_checkpoint_loadable"] is True
    assert candidate["lineage_kind"] == "NON_SERVING_TRAINING_CANDIDATE"


def test_checkpoint_manifest_cannot_escape_manager_owned_weight_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model_dir = tmp_path / ".local_models" / "candidate"
    manager = V2HybridCheckpointManager(model_dir)
    model = V2HybridPolicyModel(input_dim=4, seed=73)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_evidence={"checkpoint_role": "NON_SERVING_TRAINING_CANDIDATE"},
    )
    canonical = Path(manifest.weight_file_path or "")
    external = tmp_path / "outside.weights.npz"
    external.write_bytes(canonical.read_bytes())
    payload = json.loads(Path(manifest.path).read_text(encoding="utf-8"))
    payload["weight_file_path"] = str(external)
    Path(manifest.path).write_text(json.dumps(payload), encoding="utf-8")
    canonical.unlink()

    load = manager.load_latest_weights(V2HybridPolicyModel(input_dim=4, seed=73))

    assert load["latest_checkpoint_loadable"] is False
    assert load["load_status"] == "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST"


def test_corrupt_new_manifest_never_silently_falls_back_to_older_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model_dir = tmp_path / ".local_models" / "serving"
    manager = V2HybridCheckpointManager(model_dir)
    model = V2HybridPolicyModel(input_dim=4, seed=81)
    manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="VERIFIED_SERVING_POLICY",
        checkpoint_evidence={"checkpoint_role": "VERIFIED_SERVING_POLICY"},
    )
    corrupt = model_dir / "v2_hybrid_ckpt_ffffffff_ffffffffffffffff_ffffffffffff.json"
    corrupt.write_text("{not-json", encoding="utf-8")

    load = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=81),
        allowed_lineage_kinds=frozenset({"VERIFIED_SERVING_POLICY"}),
    )

    assert load["latest_checkpoint_loadable"] is False
    assert load["load_status"] == "CHECKPOINT_MANIFEST_SCAN_INVALID"
    assert load["manifest_scan_errors"]
