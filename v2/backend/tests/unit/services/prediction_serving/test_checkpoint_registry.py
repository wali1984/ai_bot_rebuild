from __future__ import annotations

from v2.backend.app.contracts.runtime_v2.contracts import (
    CheckpointBundleV2,
    canonical_sha256,
    prediction_record_v2_policy_fields_present,
)
from v2.backend.app.services.prediction_serving import checkpoint_registry as reg


class FakeRedis:
    """Minimal Redis double: get/set + a no-op pipeline that falls back."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value
        return True

    def pipeline(self):  # force the AttributeError fallback path (no watch/multi)
        raise AttributeError("no pipeline in fake")


def _bundle(checkpoint_id: str = "ckpt_a", steps: int = 150) -> CheckpointBundleV2:
    cal = {
        "fitted": True, "temperature": 0.5,
        "confidence_head_actions": ["long", "short"], "action_counts": {"long": 10, "short": 10},
        "sample": 20,
    }
    return CheckpointBundleV2(
        checkpoint_id=checkpoint_id,
        checkpoint_classification="PAPER_PROVISIONAL",
        model_architecture="mlp_v1",
        model_source="m",
        training_manifest_id="man1",
        training_manifest_sha256="a" * 64,
        feature_abi_sha256="b" * 64,
        ordered_feature_names=("f0", "f1", "f2"),
        input_width=3,
        action_labels=("long", "short", "hold"),
        weight_file_path="/tmp/ckpt.pt",
        weight_sha256="c" * 64,
        model_parameter_fingerprint="d" * 64,
        calibration_state=cal,
        calibration_state_sha256=canonical_sha256(cal),
        training_rows=80, validation_rows=10, holdout_rows=10,
        optimizer_steps=steps, training_metrics={"final_loss": 0.5},
        generated_at="2026-07-26T00:00:00.000Z",
    )


def test_bundle_validate_passes_and_policy_is_never_live():
    b = _bundle()
    assert b.validate() == []
    assert b.paper_eligible is True
    assert b.live_eligible is False
    assert b.checkpoint_promotable is False


def test_bundle_validate_catches_defects():
    bad = _bundle(steps=10)  # below 100
    assert "OPTIMIZER_STEPS_BELOW_MINIMUM" in bad.validate()


def test_activation_is_atomic_generation_increment_with_receipt():
    r = FakeRedis()
    b = _bundle("ckpt_a")
    reg.register_candidate(r, b, lane="paper")
    smoke = {"generated_utc": "2026-07-26T00:01:00.000Z", "records_published": 5}
    receipt = reg.activate(
        r, b, lane="paper", activated_by="test", activation_reason="init",
        serving_smoke_result=smoke,
    )
    assert receipt.registry_generation == 1
    assert receipt.previous_generation == 0
    active = reg.read_active(r, lane="paper")
    assert active["registry_generation"] == 1
    assert active["checkpoint_id"] == "ckpt_a"
    assert active["live_eligible"] is False
    # receipt persisted
    assert reg.RECEIPT_KEY.format(receipt_id=receipt.receipt_id) in r.store


def test_second_activation_advances_generation_and_keeps_rollback():
    r = FakeRedis()
    smoke = {"generated_utc": "2026-07-26T00:01:00.000Z"}
    reg.activate(r, _bundle("ckpt_a"), lane="paper", activated_by="t",
                 activation_reason="a", serving_smoke_result=smoke)
    reg.activate(r, _bundle("ckpt_b"), lane="paper", activated_by="t",
                 activation_reason="b", serving_smoke_result=smoke)
    active = reg.read_active(r, lane="paper")
    assert active["registry_generation"] == 2
    assert active["checkpoint_id"] == "ckpt_b"
    assert active["rollback_checkpoint_id"] == "ckpt_a"


def test_generation_cas_conflict_rejected():
    r = FakeRedis()
    smoke = {"generated_utc": "2026-07-26T00:01:00.000Z"}
    reg.activate(r, _bundle("ckpt_a"), lane="paper", activated_by="t",
                 activation_reason="a", serving_smoke_result=smoke)
    try:
        reg.activate(r, _bundle("ckpt_b"), lane="paper", activated_by="t",
                     activation_reason="b", serving_smoke_result=smoke,
                     expected_generation=0)  # stale expectation -> conflict
        raise AssertionError("expected CAS conflict")
    except ValueError as exc:
        assert "generation_conflict" in str(exc)


def test_rollback_restores_previous_active():
    r = FakeRedis()
    smoke = {"generated_utc": "2026-07-26T00:01:00.000Z"}
    reg.activate(r, _bundle("ckpt_a"), lane="paper", activated_by="t",
                 activation_reason="a", serving_smoke_result=smoke)
    reg.activate(r, _bundle("ckpt_b"), lane="paper", activated_by="t",
                 activation_reason="b", serving_smoke_result=smoke)
    restored = reg.rollback(r, lane="paper", rolled_back_by="t", reason="health_fail")
    assert restored["checkpoint_id"] == "ckpt_a"
    assert restored["registry_generation"] == 3
    assert restored["rolled_back_from_checkpoint_id"] == "ckpt_b"


def test_prediction_record_v2_policy_fields_detected():
    missing = prediction_record_v2_policy_fields_present({"serving_runtime_release_sha": "x"})
    assert "active_model_registry_generation" in missing
    assert "serving_runtime_release_sha" not in missing
