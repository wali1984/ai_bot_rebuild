from __future__ import annotations

from datetime import UTC, datetime

import pytest

from v2.backend.app.services.paper_recovery.paper_recovery_policy_v1 import (
    ENGINEERING_CANARY_TAGS,
    RECOVERY_CHECKPOINT_TAGS,
    RECOVERY_LIVE_DENY_REASON,
    PaperRecoveryPolicyV1,
    PaperRecoveryWaiverError,
    load_paper_recovery_policy_v1,
)

NOW = datetime(2026, 7, 25, 0, 30, tzinfo=UTC)
DEPLOY = datetime(2026, 7, 25, 0, 0, tzinfo=UTC)


def _valid_snapshot(**overrides):
    snap = {
        "feature_snapshot_id": "v2_fsnap_abc",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_values": [1.0, 2.0, 3.0, 4.0],
        "model_vector_sha256": "a" * 64,
        "feature_abi_sha256": "b" * 64,
        "source_lineage_sha256": "c" * 64,
        "generated_at": "2026-07-25T00:29:30Z",
        "ppo_decision_time": "2026-07-25T00:29:45Z",
        "feature_cutoff": "2026-07-25T00:29:00Z",
        "available_at": "2026-07-25T00:29:30Z",
    }
    snap.update(overrides)
    return snap


def _enabled_policy() -> PaperRecoveryPolicyV1:
    return load_paper_recovery_policy_v1(
        {"PAPER_RECOVERY_MODE_ENABLED": "true"}, now=DEPLOY
    )


def test_recovery_mode_disabled_by_default() -> None:
    policy = load_paper_recovery_policy_v1({})
    assert policy.enabled is False


def test_snapshot_pit_waiver_accepted_but_never_strict_complete() -> None:
    policy = _enabled_policy()
    receipt = policy.evaluate_snapshot_pit_waiver(
        _valid_snapshot(), now=NOW, expected_symbol="BTCUSDT", expected_timeframe="5m"
    )
    assert receipt["pit_waiver"] is True
    assert receipt["pit_strict_complete"] is False
    assert receipt["pit_evidence_mode"] == "SNAPSHOT_LEVEL_RECOVERY_WAIVER"
    assert receipt["trainer_eligible"] is False
    assert receipt["checkpoint_promotable"] is False
    assert receipt["live_eligible"] is False
    assert receipt["routes_to_live"] is False


def test_disabled_policy_rejects_waiver() -> None:
    policy = load_paper_recovery_policy_v1({}, now=DEPLOY)
    with pytest.raises(PaperRecoveryWaiverError) as exc:
        policy.evaluate_snapshot_pit_waiver(
            _valid_snapshot(), now=NOW, expected_symbol="BTCUSDT", expected_timeframe="5m"
        )
    assert exc.value.reason == "PAPER_RECOVERY_MODE_DISABLED"


@pytest.mark.parametrize(
    "override,expected_reason",
    [
        ({"feature_values": [1.0, float("nan")]}, "RECOVERY_FEATURE_VALUE_NOT_FINITE"),
        ({"feature_values": [1.0, float("inf")]}, "RECOVERY_FEATURE_VALUE_NOT_FINITE"),
        ({"feature_values": []}, "RECOVERY_ORDERED_VECTOR_MISSING"),
        ({"generated_at": "2026-07-25T02:00:00Z"}, "RECOVERY_GENERATED_AT_IN_FUTURE"),
        ({"generated_at": "2026-07-24T00:00:00Z"}, "RECOVERY_SNAPSHOT_PREDATES_DEPLOYMENT"),
        ({"model_vector_sha256": "short"}, "RECOVERY_MODEL_VECTOR_SHA256_INVALID"),
        ({"symbol": "ETHUSDT"}, "RECOVERY_SYMBOL_MISMATCH"),
        ({"feature_cutoff": "2026-07-25T00:30:30Z"}, "RECOVERY_FEATURE_CUTOFF_IN_FUTURE"),
    ],
)
def test_waiver_rejections(override, expected_reason) -> None:
    policy = _enabled_policy()
    with pytest.raises(PaperRecoveryWaiverError) as exc:
        policy.evaluate_snapshot_pit_waiver(
            _valid_snapshot(**override),
            now=NOW,
            expected_symbol="BTCUSDT",
            expected_timeframe="5m",
        )
    assert exc.value.reason == expected_reason


def test_stale_snapshot_rejected_by_age() -> None:
    # deployment unset so the age branch (not predates-deployment) fires.
    policy = load_paper_recovery_policy_v1({"PAPER_RECOVERY_MODE_ENABLED": "true"})
    # generated 1.5h ago -> exceeds the 1800s freshness limit.
    old = _valid_snapshot(generated_at="2026-07-24T23:00:00Z")
    with pytest.raises(PaperRecoveryWaiverError) as exc:
        policy.evaluate_snapshot_pit_waiver(
            old, now=NOW, expected_symbol="BTCUSDT", expected_timeframe="5m"
        )
    assert exc.value.reason == "RECOVERY_SNAPSHOT_STALE"


def test_symbol_not_allowed_rejected() -> None:
    policy = _enabled_policy()
    with pytest.raises(PaperRecoveryWaiverError) as exc:
        policy.evaluate_snapshot_pit_waiver(
            _valid_snapshot(symbol="ETHUSDT"),
            now=NOW,
            expected_symbol="ETHUSDT",
            expected_timeframe="5m",
        )
    assert exc.value.reason == "RECOVERY_SYMBOL_NOT_ALLOWED"


def test_recovery_artifacts_can_never_route_live() -> None:
    policy = _enabled_policy()
    for tags in (
        {"paper_recovery_only": True},
        RECOVERY_CHECKPOINT_TAGS,
        ENGINEERING_CANARY_TAGS,
        {"pit_waiver": True},
        {"synthetic_candidate": True},
    ):
        assert policy.deny_live_route(dict(tags)) == RECOVERY_LIVE_DENY_REASON


def test_clean_non_recovery_artifact_is_not_denied() -> None:
    policy = _enabled_policy()
    assert policy.deny_live_route({"live_eligible": True}) is None


def test_tag_dicts_are_never_live_eligible() -> None:
    for tags in (RECOVERY_CHECKPOINT_TAGS, ENGINEERING_CANARY_TAGS):
        assert tags["live_eligible"] is False
        assert tags["routes_to_live"] is False


def test_live_gate_anchor_cannot_be_overridden() -> None:
    policy = load_paper_recovery_policy_v1(
        {
            "PAPER_RECOVERY_MODE_ENABLED": "true",
            "PAPER_RECOVERY_LIVE_GATE": "enabled_operator_approved",
        },
        now=DEPLOY,
    )
    assert policy.live_gate_required == "blocked_human_only"
    assert policy.exchange_action_required_false is True


def test_recovery_min_train_rows_defaults_to_256_and_is_below_strict_1000() -> None:
    policy = load_paper_recovery_policy_v1({})
    # Paper-recovery floor is 256, deliberately far below the strict champion
    # gate (1000). 272 (recovery checkpoint) >= 256 => gate satisfied.
    assert policy.minimum_recovery_train_rows == 256
    assert policy.minimum_recovery_train_rows < 1000


def test_recovery_min_train_rows_env_override() -> None:
    policy = load_paper_recovery_policy_v1({"PAPER_RECOVERY_MIN_TRAIN_ROWS": "300"})
    assert policy.minimum_recovery_train_rows == 300
