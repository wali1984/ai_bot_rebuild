from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_PUBLISHED,
    append_lifecycle_event,
    archive_behavior_receipt,
    canonical_sha256,
    receipt_lifecycle_status,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    data_loader as data_loader_mod,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    runtime as runtime_mod,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    REJECTED_ATTEMPT_LINEAGE,
    checkpoint_stores,
    reconcile_checkpoint_consumption,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    HybridTrainerConfig,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    PPOTrainingResult,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _checkpoint_promotion_status_fields,
    _trusted_replay_load_limit_for_cycle,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_state import (
    ppo_consumption_update_key,
    training_partition_digest,
)


def test_trusted_replay_scan_cap_can_survive_normal_rejections_above_phase_two_floor() -> None:
    assert data_loader_mod.TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE >= 16_384


def _runtime_test_example(symbol: str, timeframe: str, index: int) -> TrainingExample:
    tensor = FeatureTensorRecord(
        tensor_id=f"tensor_{symbol}_{timeframe}",
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=f"feat_{symbol}_{timeframe}",
        values=(float(index),),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )
    return TrainingExample(
        symbol=symbol,
        timeframe=timeframe,
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row={
            "accepted_for_training": True,
            "reject_reasons": [],
            "feature_cutoff": "2026-07-11T00:00:00Z",
            "decision_time": "2026-07-11T00:01:00Z",
            "available_at": "2026-07-11T00:00:30Z",
        },
    )


def test_parallel_prediction_grid_loader_preserves_pair_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_build_example(
        self: V2HybridTrainerDataLoader,
        *,
        symbol: str,
        timeframe: str,
        snapshot_fast_path: bool = False,
    ) -> TrainingExample:
        del self
        calls.append((symbol, timeframe, snapshot_fast_path))
        return _runtime_test_example(symbol, timeframe, len(calls))

    monkeypatch.setattr(V2HybridTrainerDataLoader, "build_example", fake_build_example)
    loader = V2HybridTrainerDataLoader()

    examples = loader.load_prediction_grid_examples(
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1m", "5m"),
        max_workers=2,
    )

    assert [(row.symbol, row.timeframe) for row in examples] == [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "5m"),
        ("ETHUSDT", "1m"),
        ("ETHUSDT", "5m"),
    ]
    assert all(snapshot_fast_path is True for *_pair, snapshot_fast_path in calls)
    assert loader.last_prediction_grid_load["parallel_loader_used"] is True
    assert loader.last_prediction_grid_load["parallel_workers"] == 2


def test_resident_replay_load_limit_uses_replay_buffer_capacity() -> None:
    replay_buffer = deque(maxlen=4096)

    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=replay_buffer,
    )

    assert limit == 4096


def test_nonresident_replay_load_limit_uses_requested_rows() -> None:
    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=None,
    )

    assert limit == 32768


def _runtime_promotion_metrics(**overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "validation_split_pit_safe": True,
        "validation_split_reason": "PIT_SAFE_CHRONOLOGICAL_PURGED_SPLIT",
        "validation_split_actual_training_rows": 1,
        "validation_split_actual_validation_rows": 2,
        "validation_split_temporal_overlap": False,
        "validation_split_label_overlap": False,
        "validation_policy_edge_status": "VALID",
        "validation_policy_edge_evidence_valid": True,
        "validation_policy_edge_after_cost_bps": -1.0,
        "validation_policy_edge_standard_error_bps": 1.0,
        "validation_policy_edge_lower_confidence_bound_bps": -2.0,
        "validation_policy_edge_uncertainty_multiplier": 1.0,
        "validation_policy_edge_rows_evaluated": 2,
    }
    metrics.update(overrides)
    return metrics


def test_runtime_suppresses_rejected_candidate_forward_and_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    example = _runtime_test_example("BTCUSDT", "1m", 1)
    training_observation_cutoffs: list[str] = []

    class FakeLoader:
        def __init__(self, **_kwargs) -> None:
            self.last_prediction_grid_load = {}
            self.last_trusted_replay_scan = {}
            self.last_trusted_replay_backfill_scan = {}

        def load_prediction_grid_examples(self, **_kwargs):
            return [example]

        def load_training_examples(self, **kwargs):
            training_observation_cutoffs.append(kwargs["training_observed_at"])
            return [example]

        def load_trusted_replay_examples(self, **kwargs):
            training_observation_cutoffs.append(kwargs["training_observed_at"])
            return []

    class FakeModel:
        forward_calls = 0

        def __init__(self, *, input_dim: int) -> None:
            self.input_dim = input_dim
            self.model_id = "model_rejected_candidate"
            self.device = "cpu"
            self.cuda_active = False
            self.torch_available = False
            self._fallback_weights = [0.1, -0.1]

        @property
        def confidence_calibration_state(self) -> dict[str, object]:
            return {"fitted": False, "reason": "TEST_UNFITTED"}

        def forward(self, _tensor):
            type(self).forward_calls += 1
            raise AssertionError("a rejected candidate must never run inference")

        def model_tensors_device_verified(self) -> bool:
            return True

        def architecture_status(self) -> dict[str, object]:
            return {"test_model": True}

    class FakeCheckpointManager:
        def __init__(self, _model_dir) -> None:
            pass

        def load_latest_weights(self, _model) -> dict[str, object]:
            return {
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST",
            }

        def latest_manifest(self, **_kwargs):
            return None

        def write_checkpoint(self, **_kwargs):
            raise AssertionError("a rejected candidate must never be written")

        def status(self, checkpoint) -> dict[str, object]:
            return {
                "checkpoint_id": checkpoint.checkpoint_id,
                "weight_file_path": checkpoint.weight_file_path,
            }

    class FakeTrainer:
        def __init__(self, **kwargs) -> None:
            training_observation_cutoffs.append(kwargs["training_observed_at"])

        def plan_exact_ppo_optimizer_attempts(self, examples, **_kwargs):
            return {
                "optimizer_attempt_descriptors": [],
                "eligible_examples": [],
                "ordered_update_keys": [],
                "ordered_update_keys_complete": True,
                "ordered_update_keys_unique": True,
                "duplicate_update_keys": [],
                "available_rows": list(examples),
                "trusted_rows": list(examples),
                "all_ppo_rows": [],
                "ppo_rows": [],
                "outcome_rows": list(examples),
                "learnable_rows": list(examples),
                "selected_rows_for_split": list(examples),
                "train_rows": list(examples),
                "validation_rows": [],
                "learning_mode": "outcome_supervised",
                "target_batch_size": 1,
                "tuned_batch_size": 1,
                "rejection_metrics": {},
                "split_metrics": {},
            }

        def train(self, _examples, **_kwargs) -> PPOTrainingResult:
            return PPOTrainingResult(
                status="TEST_REJECTED_CANDIDATE",
                device="cpu",
                cuda_active=False,
                cuda_claim_verified=True,
                gpu_name=None,
                vram_allocated_mb=None,
                batch_size=1,
                training_steps=1,
                train_rows=1,
                validation_rows=2,
                loss_before=1.0,
                loss_after=0.9,
                action_distribution={"hold": 1},
                metrics=_runtime_promotion_metrics(
                    validation_rows_evaluated=2,
                    validation_split_actual_validation_rows=2,
                    validation_policy_edge_rows_evaluated=2,
                    validation_policy_edge_after_cost_bps=-1.0,
                    validation_policy_edge_lower_confidence_bound_bps=-2.0,
                    optimizer_steps_this_cycle=1,
                    parameter_hash_before="before",
                    parameter_hash_after="after",
                    weight_delta_norm=1.0,
                    training_trusted_rows=1,
                ),
            )

    class FakeEnv:
        def __init__(self, _examples) -> None:
            pass

        def reset(self):
            return [0.0], {"reset": True}

        def step(self, _action):
            return [0.0], 0.0, False, False, {"step": True}

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:
            pass

        def publish_prediction(self, _payload):
            raise AssertionError("rejected candidate prediction publication attempted")

        def publish_lineage(self, **_kwargs):
            raise AssertionError("rejected candidate lineage publication attempted")

    monkeypatch.setattr(runtime_mod, "V2HybridTrainerDataLoader", FakeLoader)
    monkeypatch.setattr(runtime_mod, "V2HybridPolicyModel", FakeModel)
    monkeypatch.setattr(runtime_mod, "V2HybridCheckpointManager", FakeCheckpointManager)
    monkeypatch.setattr(runtime_mod, "V2HybridPPOTrainer", FakeTrainer)
    monkeypatch.setattr(runtime_mod, "V2PaperShadowHybridEnv", FakeEnv)
    monkeypatch.setattr(runtime_mod, "V2HybridPredictionPublisher", FakePublisher)
    monkeypatch.setattr(
        runtime_mod,
        "run_policy_archive_backtest",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("rejected candidate backtest attempted")
        ),
    )
    monkeypatch.setattr(
        runtime_mod,
        "run_parallel_env_rollout_proof",
        lambda *_args, **_kwargs: SimpleNamespace(to_jsonable=lambda: {}),
    )

    result = runtime_mod.run_hybrid_trainer_cycle(
        config=HybridTrainerConfig(
            symbols=("BTCUSDT",),
            timeframes=("1m",),
            model_dir=tmp_path / ".local_models/rejected_candidate_test",
            max_training_rows_per_cycle=1,
            batch_size=1,
        ),
        publish=False,
    )

    assert FakeModel.forward_calls == 0
    assert result.predictions == []
    assert result.lineages == []
    assert result.status["prediction_suppressed_count"] == 1
    assert result.status["prediction_publication_status"] == (
        "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
    )
    assert result.status["model_serving_allowed"] is False
    assert result.metrics["cuda_cpu_resource_utilization"]["policy_backtest"][
        "status"
    ] == (
        "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
    )
    assert len(training_observation_cutoffs) == 3
    assert len(set(training_observation_cutoffs)) == 1
    assert datetime.fromisoformat(
        training_observation_cutoffs[0].replace("Z", "+00:00")
    ).tzinfo is not None


def test_decision_clock_is_strictly_after_exact_cost_observation() -> None:
    observed = datetime.now(UTC) + timedelta(seconds=5)

    decision = runtime_mod._causal_decision_time_after_cost_observation(
        {
            "exact_cost_provenance": {
                "consumer_observed_at": observed.isoformat(
                    timespec="microseconds"
                ).replace("+00:00", "Z")
            }
        }
    )

    parsed = datetime.fromisoformat(decision.replace("Z", "+00:00"))
    assert parsed > observed


class _TerminalAttemptLedger:
    def __init__(self, attempt: dict[str, object]) -> None:
        self.attempt = dict(attempt)
        self.sync_sequence = 0
        self.archive_binding: dict[str, object] | None = None

    def attempt_rows(
        self,
        update_keys: list[str] | None = None,
    ) -> list[dict[str, object]]:
        if update_keys is not None and update_keys != [self.attempt["update_key"]]:
            return []
        return [dict(self.attempt)]

    def archive_sync_status(self) -> dict[str, object]:
        return {
            "archive_sync_integrity_verified": True,
            "archive_sync_rejection_reasons": [],
            "activation_sequence": 1,
            "sync_sequence": self.sync_sequence,
            "sync_chain_hash": (
                str(self.attempt["chain_hash"])
                if self.sync_sequence
                else "0" * 64
            ),
            "ledger_row_count": 1,
            "legacy_terminal_attempts_not_archive_bound": 0,
            "unsynced_terminal_attempts": 1 - self.sync_sequence,
        }

    def unsynced_attempt_rows(self) -> list[dict[str, object]]:
        return [dict(self.attempt)] if self.sync_sequence == 0 else []

    def archive_sync_bindings(self) -> list[dict[str, object]]:
        return [] if self.archive_binding is None else [dict(self.archive_binding)]

    def mark_archive_synced(
        self,
        *,
        sequence: int,
        chain_hash: str,
        receipt_hash: str,
        trainer_consumed_event_hash: str,
    ) -> dict[str, object]:
        assert sequence == 1
        assert chain_hash == self.attempt["chain_hash"]
        assert receipt_hash == self.attempt["receipt_hash"]
        self.archive_binding = {
            **self.attempt,
            "ledger_chain_hash": chain_hash,
            "trainer_consumed_event_hash": trainer_consumed_event_hash,
        }
        self.sync_sequence = 1
        return {**self.archive_sync_status(), "watermark_advanced": True}


def _archived_terminal_attempt(
    root: Path,
    *,
    finalized_digest: str = "e" * 64,
) -> tuple[dict[str, object], str]:
    receipt: dict[str, object] = {
        "schema_version": "unit_exact_receipt_v1",
        "prediction_id": "prediction-sync-1",
        "symbol": "BTCUSDT",
        "paper_only": True,
        "routes_to_live": False,
    }
    receipt["receipt_hash"] = canonical_sha256(receipt)
    receipt_hash = str(receipt["receipt_hash"])
    parent_fingerprint = "d" * 64
    update_key = ppo_consumption_update_key(
        receipt_hash=receipt_hash,
        finalized_outcome_digest=finalized_digest,
        parent_policy_fingerprint=parent_fingerprint,
    )
    archive_behavior_receipt(receipt, root=root)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding={
            "prediction_id": "prediction-sync-1",
            "decision_time": "2026-07-18T00:00:00Z",
        },
        root=root,
        recorded_at="2026-07-18T00:00:00Z",
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding={
            "paper_fill_id": "fill-sync-1",
            "decision_time": "2026-07-18T00:00:00Z",
            "entry_time": "2026-07-18T00:01:00Z",
        },
        root=root,
        recorded_at="2026-07-18T00:01:00Z",
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_OUTCOME_FINALIZED,
        binding={
            "finalized_outcome_id": "outcome-sync-1",
            "finalized_outcome_digest": finalized_digest,
            "ppo_consumption_update_key": update_key,
            "outcome_available_at": "2026-07-18T00:02:00Z",
        },
        root=root,
        recorded_at="2026-07-18T00:02:00Z",
    )
    return (
        {
            "sequence": 1,
            "update_key": update_key,
            "receipt_hash": receipt_hash,
            "finalized_outcome_digest": finalized_digest,
            "parent_policy_fingerprint": parent_fingerprint,
            "child_policy_fingerprint": "f" * 64,
            "disposition": "NON_SERVING_CANDIDATE_PERSISTED",
            "checkpoint_id": "checkpoint-sync-1",
            "recorded_utc": "2026-07-18T00:03:00Z",
            "chain_hash": "a" * 64,
        },
        receipt_hash,
    )


def test_terminal_ledger_attempt_advances_watermark_and_skips_historical_rescan(
    tmp_path: Path,
) -> None:
    attempt, receipt_hash = _archived_terminal_attempt(tmp_path)
    ledger = _TerminalAttemptLedger(attempt)

    first = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
    )
    second = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
        update_keys=[str(attempt["update_key"])],
    )

    assert first["trainer_consumed_events_appended"] == 1
    assert first["archive_sync_after"]["sync_sequence"] == 1
    assert second["ledger_attempts_checked"] == 0
    assert second["trainer_consumed_events_already_present"] == 0
    status = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert status["trainer_consumed_durable"] is True
    assert status["retention_required"] is False
    consumed = status["event_bindings"]["TRAINER_CONSUMED"]
    assert consumed["ppo_consumption_update_key"] == attempt["update_key"]
    assert consumed["ledger_disposition"] == attempt["disposition"]
    assert consumed["finalized_outcome_digest"] == attempt[
        "finalized_outcome_digest"
    ]


def test_synced_archive_event_deletion_revokes_watermark_readiness(
    tmp_path: Path,
) -> None:
    attempt, _receipt_hash = _archived_terminal_attempt(tmp_path)
    ledger = _TerminalAttemptLedger(attempt)
    first = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
    )
    # Resolve the event named by the ledger's exact per-sequence binding and
    # delete it after the watermark has already advanced.
    bound_event_hash = str(
        ledger.archive_sync_bindings()[0]["trainer_consumed_event_hash"]
    )
    paths = list(tmp_path.rglob(f"{bound_event_hash}.json"))
    assert len(paths) == 1
    assert first["archive_sync_after"]["archive_event_bindings_verified"] is True
    paths[0].unlink()

    with pytest.raises(
        RuntimeError,
        match="durable_receipt_consumption_watermark_invalid",
    ):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=ledger,
            archive_root=tmp_path,
        )


def test_terminal_consumption_retries_existing_event_after_pre_watermark_crash(
    tmp_path: Path,
) -> None:
    attempt, receipt_hash = _archived_terminal_attempt(tmp_path)

    class _CrashAfterArchiveEventLedger(_TerminalAttemptLedger):
        crash_once = True

        def mark_archive_synced(
            self,
            *,
            sequence: int,
            chain_hash: str,
            receipt_hash: str,
            trainer_consumed_event_hash: str,
        ) -> dict[str, object]:
            if self.crash_once:
                self.crash_once = False
                raise RuntimeError("simulated_crash_before_watermark")
            return super().mark_archive_synced(
                sequence=sequence,
                chain_hash=chain_hash,
                receipt_hash=receipt_hash,
                trainer_consumed_event_hash=trainer_consumed_event_hash,
            )

    ledger = _CrashAfterArchiveEventLedger(attempt)

    with pytest.raises(
        RuntimeError,
        match="durable_receipt_consumption_watermark_advance_failed",
    ):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=ledger,
            archive_root=tmp_path,
        )

    after_crash = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert after_crash["trainer_consumed_durable"] is True
    assert ledger.sync_sequence == 0

    retried = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
    )

    assert retried["trainer_consumed_events_appended"] == 0
    assert retried["trainer_consumed_events_already_present"] == 1
    assert retried["archive_sync_after"]["sync_sequence"] == 1


def test_startup_repairs_checkpoint_and_archive_crash_windows_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove both post-optimizer restart repairs with real durable stores."""

    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    archive_root = tmp_path / "behavior_receipts"
    model_dir = tmp_path / ".local_models" / "crash_window_models"
    archived_attempt, receipt_hash = _archived_terminal_attempt(archive_root)
    descriptor = {
        field: archived_attempt[field]
        for field in (
            "update_key",
            "receipt_hash",
            "finalized_outcome_digest",
            "parent_policy_fingerprint",
        )
    }
    update_key = str(descriptor["update_key"])
    partition_digest = training_partition_digest([update_key])
    dead_owner = "00000000-0000-0000-0000-000000000000:999999999:0"

    before_crash = checkpoint_stores(model_dir)
    claim = before_crash.ledger.claim_attempts(
        attempts=[descriptor],
        owner_id=dead_owner,
    )
    assert claim["claimed_update_keys"] == [update_key]
    before_crash.ledger.mark_optimizer_started(
        owner_id=dead_owner,
        update_keys=[update_key],
        partition_digest=partition_digest,
    )
    model = V2HybridPolicyModel(input_dim=4, seed=701)
    artifact = before_crash.rejected_attempt.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=REJECTED_ATTEMPT_LINEAGE,
        parent_checkpoint_id=None,
        parent_policy_fingerprint=str(descriptor["parent_policy_fingerprint"]),
        consumed_ppo_update_keys=(update_key,),
        training_partition_digest=partition_digest,
        checkpoint_evidence={
            "checkpoint_role": REJECTED_ATTEMPT_LINEAGE,
            "ledger_disposition": "REJECTED_TRAINING_ATTEMPT_PERSISTED",
            "candidate_progress_decision": {
                "candidate_progress_allowed": False,
            },
            "serving_promotion_decision": {
                "checkpoint_promotion_allowed": False,
            },
        },
    )
    assert before_crash.ledger.attempt_rows() == []
    assert receipt_lifecycle_status(receipt_hash, root=archive_root)[
        "trainer_consumed_durable"
    ] is False

    # Simulated crash after the child checkpoint's atomic write but before the
    # terminal ledger commit. Startup discovers the dead fenced claim in the
    # verified artifact and commits exactly one terminal disposition.
    after_checkpoint_restart = checkpoint_stores(model_dir)
    reconciliation = reconcile_checkpoint_consumption(after_checkpoint_restart)
    assert reconciliation["verified_checkpoint_reconciled_attempts"] == 1
    assert reconciliation["ambiguous_optimizer_attempts_consumed"] == 0
    rows = after_checkpoint_restart.ledger.attempt_rows([update_key])
    assert len(rows) == 1
    terminal = rows[0]
    assert terminal["disposition"] == "REJECTED_TRAINING_ATTEMPT_PERSISTED"
    assert terminal["checkpoint_id"] == artifact.checkpoint_id
    assert terminal["checkpoint_path"] == artifact.weight_file_path
    assert terminal["checkpoint_sha256"] == artifact.weight_file_sha256
    assert terminal["child_policy_fingerprint"] == artifact.model_parameter_fingerprint
    assert terminal["training_partition_digest"] == partition_digest
    assert receipt_lifecycle_status(receipt_hash, root=archive_root)[
        "trainer_consumed_durable"
    ] is False

    # Simulated second crash after the terminal ledger commit but before its
    # archive event. The next startup mirrors the exact ledger binding.
    after_ledger_restart = checkpoint_stores(model_dir)
    archive_repair = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=after_ledger_restart.ledger,
        archive_root=archive_root,
    )
    assert archive_repair["trainer_consumed_events_appended"] == 1
    assert archive_repair["archive_sync_after"]["sync_sequence"] == 1
    lifecycle = receipt_lifecycle_status(receipt_hash, root=archive_root)
    assert lifecycle["event_count"] == 4
    assert lifecycle["trainer_consumed_durable"] is True
    assert lifecycle["retention_required"] is False
    consumed = lifecycle["event_bindings"]["TRAINER_CONSUMED"]
    assert consumed["ppo_consumption_update_key"] == update_key
    assert consumed["ledger_sequence"] == terminal["sequence"]
    assert consumed["ledger_chain_hash"] == terminal["chain_hash"]
    assert consumed["ledger_disposition"] == terminal["disposition"]
    assert consumed["checkpoint_id"] == artifact.checkpoint_id
    assert consumed["child_policy_fingerprint"] == terminal[
        "child_policy_fingerprint"
    ]
    assert consumed["finalized_outcome_digest"] == terminal[
        "finalized_outcome_digest"
    ]
    assert consumed["ledger_recorded_utc"] == terminal["recorded_utc"]

    # A further restart is idempotent, and the terminal row fences the same
    # optimizer input permanently instead of admitting a replay.
    final_restart = checkpoint_stores(model_dir)
    repeated_reconciliation = reconcile_checkpoint_consumption(final_restart)
    repeated_sync = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=final_restart.ledger,
        archive_root=archive_root,
    )
    replay_claim = final_restart.ledger.claim_attempts(
        attempts=[descriptor],
        owner_id=final_restart.ledger.process_owner_id(),
    )
    assert repeated_reconciliation["verified_checkpoint_reconciled_attempts"] == 0
    assert repeated_sync["ledger_attempts_checked"] == 0
    assert final_restart.ledger.attempt_rows([update_key]) == [terminal]
    assert replay_claim["claimed_update_keys"] == []
    assert replay_claim["unavailable_update_keys"] == [update_key]
    assert receipt_lifecycle_status(receipt_hash, root=archive_root)[
        "event_count"
    ] == 4


def test_consumption_sync_fails_closed_when_archive_is_missing(tmp_path: Path) -> None:
    attempt, _receipt_hash = _archived_terminal_attempt(tmp_path / "source")

    with pytest.raises(RuntimeError, match="archive_invalid"):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=_TerminalAttemptLedger(attempt),
            archive_root=tmp_path / "missing",
        )


def test_consumption_sync_rejects_finalized_digest_binding_tamper(
    tmp_path: Path,
) -> None:
    attempt, _receipt_hash = _archived_terminal_attempt(tmp_path)
    attempt["finalized_outcome_digest"] = "b" * 64
    attempt["update_key"] = ppo_consumption_update_key(
        receipt_hash=str(attempt["receipt_hash"]),
        finalized_outcome_digest=str(attempt["finalized_outcome_digest"]),
        parent_policy_fingerprint=str(attempt["parent_policy_fingerprint"]),
    )

    with pytest.raises(RuntimeError, match="finalized_binding_invalid"):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=_TerminalAttemptLedger(attempt),
            archive_root=tmp_path,
        )


def test_exact_claim_contract_rejects_cpu_fallback_key_echo_without_ppo() -> None:
    update_key = "a" * 64
    attempt = {"update_key": update_key}
    fallback_metrics = {
        "ppo_consumed_update_keys": [update_key],
        "ppo_consumed_update_keys_complete": True,
        "ppo_consumed_update_keys_ordered": True,
        "ppo_consumed_update_keys_unique": True,
        "ppo_objective_used": False,
        "ppo_rows_consumed": 0,
        "ppo_rows_available_but_optimizer_unavailable": 1,
        "ppo_clipped_surrogate_rows": 0,
        "optimizer_steps_this_cycle": 1,
    }

    assert runtime_mod._exact_ppo_optimizer_contract_valid(  # noqa: SLF001
        metrics=fallback_metrics,
        optimizer_attempts=[attempt],
        ordered_update_keys=[update_key],
    ) is False


def test_checkpoint_promotion_status_fields_surface_rejection_streak() -> None:
    fields = _checkpoint_promotion_status_fields(
        {
            "checkpoint_promotion_guard_active": True,
            "checkpoint_promotion_allowed": False,
            "checkpoint_promotion_rejected": True,
            "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
            "overfit_gap_warning_advisory": None,
            "prior_promotion_rejection_streak": 2,
            "promotion_rejection_streak_after": 0,
            "max_promotion_rejection_streak": 3,
            "forced_promote_after_rejection_streak": 3,
        }
    )

    assert fields == {
        "pit_edge_promotion_gate_active": None,
        "mandatory_pit_edge_gate_passed": None,
        "checkpoint_promotion_guard_active": True,
        "checkpoint_promotion_allowed": False,
        "checkpoint_promotion_rejected": True,
        "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
        "overfit_gap_warning_advisory": None,
        "prior_promotion_rejection_streak": 2,
        "promotion_rejection_streak_after": 0,
        "max_promotion_rejection_streak": 3,
        "forced_promote_after_rejection_streak": 3,
        "forced_promote_after_rejection_streak_blocked": None,
        "forced_promote_block_reason": None,
        "hard_promotion_rejection_reason": None,
        "pit_edge_hard_rejection_reason": None,
        "force_promote_after_rejection_streak_enabled": None,
        "validation_split_pit_safe": None,
        "validation_split_reason": None,
        "validation_policy_edge_status": None,
        "validation_policy_edge_after_cost_bps": None,
        "validation_policy_edge_lower_confidence_bound_bps": None,
        "validation_policy_edge_rows_evaluated": None,
        "model_serving_allowed": None,
        "model_serving_source": None,
        "rejected_candidate_serving_suppressed": None,
        "model_serving_suppression_reason": None,
    }
