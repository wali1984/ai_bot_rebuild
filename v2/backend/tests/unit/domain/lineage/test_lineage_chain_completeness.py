"""Phase 1 lineage completeness tests.

Proves:
1. REQUIRED_LINEAGE_IDS includes orchestrator_decision_id and paper_ledger_entry_id.
2. validate_lineage_ids returns ok=True only when all 7 IDs are present.
3. validate_minimum_actionable_ids blocks signals missing risk/orch/intent IDs.
4. assert_actionable_has_lineage raises when an actionable signal has missing IDs.
5. build_paper_runtime_lineage output includes all 7 lineage IDs.
6. derive_all_ids produces non-empty deterministic IDs for all 7 fields.
"""
from __future__ import annotations

import pytest

from v2.backend.app.domain.lineage.chain import (
    MINIMUM_ACTIONABLE_IDS,
    REQUIRED_LINEAGE_IDS,
)
from v2.backend.app.domain.lineage.ids import derive_all_ids
from v2.backend.app.domain.lineage.validators import (
    assert_actionable_has_lineage,
    validate_lineage_ids,
    validate_minimum_actionable_ids,
)


# ── chain constants ────────────────────────────────────────────────────────────


def test_required_ids_includes_orchestrator_decision_id() -> None:
    assert "orchestrator_decision_id" in REQUIRED_LINEAGE_IDS


def test_required_ids_includes_paper_ledger_entry_id() -> None:
    assert "paper_ledger_entry_id" in REQUIRED_LINEAGE_IDS


def test_required_ids_includes_risk_decision_id() -> None:
    assert "risk_decision_id" in REQUIRED_LINEAGE_IDS


def test_required_ids_includes_execution_intent_id() -> None:
    assert "execution_intent_id" in REQUIRED_LINEAGE_IDS


def test_minimum_actionable_ids_does_not_require_ledger_entry() -> None:
    assert "paper_ledger_entry_id" not in MINIMUM_ACTIONABLE_IDS


# ── validate_lineage_ids ───────────────────────────────────────────────────────


def _full_ids() -> dict:
    return {
        "prediction_id": "pred_abc",
        "feature_snapshot_id": "snap_abc",
        "signal_id": "sig_abc",
        "orchestrator_decision_id": "orch_abc",
        "risk_decision_id": "risk_abc",
        "execution_intent_id": "pei_abc",
        "paper_ledger_entry_id": "pledger_abc",
    }


def test_validate_full_ids_ok() -> None:
    ok, missing = validate_lineage_ids(_full_ids())
    assert ok is True
    assert missing == []


@pytest.mark.parametrize("drop_field", [
    "prediction_id",
    "feature_snapshot_id",
    "signal_id",
    "orchestrator_decision_id",
    "risk_decision_id",
    "execution_intent_id",
    "paper_ledger_entry_id",
])
def test_validate_ids_fails_when_field_missing(drop_field: str) -> None:
    ids = _full_ids()
    ids[drop_field] = None
    ok, missing = validate_lineage_ids(ids)
    assert ok is False
    assert drop_field in missing


def test_validate_ids_fails_on_empty_dict() -> None:
    ok, missing = validate_lineage_ids({})
    assert ok is False
    assert len(missing) == len(REQUIRED_LINEAGE_IDS)


# ── validate_minimum_actionable_ids ───────────────────────────────────────────


def _minimum_ids() -> dict:
    ids = _full_ids()
    ids.pop("paper_ledger_entry_id")
    return ids


def test_minimum_actionable_ok_without_ledger_entry() -> None:
    ok, missing = validate_minimum_actionable_ids(_minimum_ids())
    assert ok is True
    assert missing == []


def test_minimum_actionable_fails_without_risk_decision() -> None:
    ids = _minimum_ids()
    ids["risk_decision_id"] = None
    ok, missing = validate_minimum_actionable_ids(ids)
    assert ok is False
    assert "risk_decision_id" in missing


def test_minimum_actionable_fails_without_orchestrator_decision() -> None:
    ids = _minimum_ids()
    ids["orchestrator_decision_id"] = None
    ok, missing = validate_minimum_actionable_ids(ids)
    assert ok is False
    assert "orchestrator_decision_id" in missing


# ── assert_actionable_has_lineage ─────────────────────────────────────────────


def test_assert_actionable_passes_with_full_lineage() -> None:
    signal = {
        "actionable": True,
        "signal_id": "sig_test",
        "prediction_id": "pred_test",
        "lineage_ids": _minimum_ids(),
    }
    assert_actionable_has_lineage(signal)  # must not raise


def test_assert_actionable_skips_non_actionable_signals() -> None:
    signal = {"actionable": False, "signal_id": "sig_test", "lineage_ids": {}}
    assert_actionable_has_lineage(signal)  # must not raise


def test_assert_actionable_raises_when_risk_decision_missing() -> None:
    ids = _minimum_ids()
    ids["risk_decision_id"] = None
    signal = {"actionable": True, "signal_id": "sig_test", "lineage_ids": ids}
    with pytest.raises(ValueError, match="risk_decision_id"):
        assert_actionable_has_lineage(signal)


def test_assert_actionable_raises_when_orchestrator_missing() -> None:
    ids = _minimum_ids()
    ids["orchestrator_decision_id"] = None
    signal = {"actionable": True, "signal_id": "sig_test", "lineage_ids": ids}
    with pytest.raises(ValueError, match="orchestrator_decision_id"):
        assert_actionable_has_lineage(signal)


def test_assert_actionable_falls_back_to_top_level_ids() -> None:
    signal = {
        "actionable": True,
        "signal_id": "sig_test",
        "prediction_id": "pred_test",
        "feature_snapshot_id": "snap_test",
        "orchestrator_decision_id": "orch_test",
        "risk_decision_id": "risk_test",
        "execution_intent_id": "pei_test",
        "lineage_ids": {},
    }
    assert_actionable_has_lineage(signal)  # must not raise


# ── derive_all_ids ─────────────────────────────────────────────────────────────


def test_derive_all_ids_returns_all_seven_fields() -> None:
    ids = derive_all_ids(
        prediction_id="pred_xyz",
        tick_id="tick_xyz",
        feature_snapshot_id="snap_xyz",
    )
    for field in REQUIRED_LINEAGE_IDS:
        assert ids.get(field), f"derived ids missing {field!r}"


def test_derive_all_ids_are_deterministic() -> None:
    ids1 = derive_all_ids(prediction_id="pred_abc", tick_id="t1", feature_snapshot_id="snap_abc")
    ids2 = derive_all_ids(prediction_id="pred_abc", tick_id="t1", feature_snapshot_id="snap_abc")
    assert ids1 == ids2


def test_derive_all_ids_differ_for_different_prediction_ids() -> None:
    ids1 = derive_all_ids(prediction_id="pred_aaa", tick_id="t1", feature_snapshot_id="snap_x")
    ids2 = derive_all_ids(prediction_id="pred_bbb", tick_id="t1", feature_snapshot_id="snap_x")
    assert ids1["risk_decision_id"] != ids2["risk_decision_id"]
    assert ids1["orchestrator_decision_id"] != ids2["orchestrator_decision_id"]


# ── signal_publisher integration ──────────────────────────────────────────────


def test_build_paper_runtime_lineage_includes_all_lineage_ids() -> None:
    from v2.backend.app.services.signal_publisher import build_paper_runtime_lineage

    prediction = {
        "prediction_id": "pred_test_1",
        "feature_snapshot_id": "snap_test_1",
        "confidence_calibrated": 0.8,
        "raw_output": {"side": "long"},
        "trainer_state": "LIVE",
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
    }
    feature_snapshot = {
        "feature_snapshot_id": "snap_test_1",
        "features": {},
        "freshness_state": "CURRENT",
    }

    lineage = build_paper_runtime_lineage(
        tick_id="tick_test_1",
        generated_at="2026-06-17T00:00:00Z",
        feature_snapshot=feature_snapshot,
        prediction=prediction,
        market_symbol="BTCUSDT",
        market_freshness_state="CURRENT",
        market_age_seconds=5,
    )

    ids = lineage.get("lineage_ids") or {}
    assert ids.get("prediction_id") == "pred_test_1"
    assert ids.get("feature_snapshot_id") == "snap_test_1"
    assert ids.get("orchestrator_decision_id"), "orchestrator_decision_id must be present"
    assert ids.get("risk_decision_id"), "risk_decision_id must be present"
    assert ids.get("execution_intent_id"), "execution_intent_id must be present"
    assert ids.get("paper_ledger_entry_id"), "paper_ledger_entry_id must be present"
    assert ids.get("signal_id"), "signal_id must be present"


def test_build_paper_runtime_lineage_no_risk_decision_missing_for_valid_prediction() -> None:
    from v2.backend.app.services.signal_publisher import build_paper_runtime_lineage

    prediction = {
        "prediction_id": "pred_risk_check",
        "feature_snapshot_id": "snap_risk_check",
        "confidence_calibrated": 0.85,
        "raw_output": {"side": "short"},
        "trainer_state": "LIVE",
    }
    feature_snapshot = {
        "feature_snapshot_id": "snap_risk_check",
        "features": {},
        "freshness_state": "CURRENT",
    }
    lineage = build_paper_runtime_lineage(
        tick_id="tick_risk_check",
        generated_at="2026-06-17T00:00:00Z",
        feature_snapshot=feature_snapshot,
        prediction=prediction,
        market_symbol="ETHUSDT",
        market_freshness_state="CURRENT",
        market_age_seconds=10,
    )
    risk_decision = lineage.get("risk_decision") or {}
    assert risk_decision.get("risk_decision_id"), "risk_decision_id must be present in risk_decision block"
    assert risk_decision.get("orchestrator_decision_id"), "orchestrator_decision_id must be in risk_decision block"
