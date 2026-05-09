from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from v2.backend.app.proof import build_non_live_proof


REPO_ROOT = Path(__file__).resolve().parents[5]
BUILDER_PATH = REPO_ROOT / "claude_worklog/tools/build_autonomous_live_readiness_builder.py"

PARITY_FIELDS = (
    "model_version",
    "checkpoint_id",
    "confidence_raw",
    "confidence_calibrated",
    "trainer_worker_liveness",
)

EXPECTED_VALUES = {
    "safe_long_paper_intent": {
        "model_version": "hybrid_trainer_v2026_05",
        "checkpoint_id": "ckpt_safe_long_paper_intent_2026_05",
        "confidence_raw": 0.86,
        "confidence_calibrated": 0.82,
        "trainer_worker_liveness": "alive",
    },
    "stale_data_blocked": {
        "model_version": "hybrid_trainer_v2026_05",
        "checkpoint_id": "ckpt_stale_data_blocked_2026_05",
        "confidence_raw": 0.81,
        "confidence_calibrated": 0.78,
        "trainer_worker_liveness": "degraded",
    },
    "duplicate_signal_blocked": {
        "model_version": "hybrid_trainer_v2026_05",
        "checkpoint_id": "ckpt_duplicate_signal_blocked_2026_05",
        "confidence_raw": 0.77,
        "confidence_calibrated": 0.74,
        "trainer_worker_liveness": "alive",
    },
    "hedge_close_residual_exposure_blocked": {
        "model_version": "hybrid_trainer_v2026_05",
        "checkpoint_id": "ckpt_hedge_close_residual_exposure_blocked_2026_05",
        "confidence_raw": 0.72,
        "confidence_calibrated": 0.69,
        "trainer_worker_liveness": "alive",
    },
    "lab_hedge_unwind_short_squeeze": {
        "model_version": "hybrid_trainer_v2026_05",
        "checkpoint_id": "ckpt_lab_hedge_unwind_short_squeeze_2026_05",
        "confidence_raw": 0.69,
        "confidence_calibrated": 0.66,
        "trainer_worker_liveness": "worker_dead",
    },
}


def _load_builder_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "phase2v_autonomous_live_readiness_builder", BUILDER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decision_explainability_result_carries_five_trainer_fields() -> None:
    proof = build_non_live_proof()
    explanations = proof["decision_explainability_result"]["explanations"]

    by_scenario = {row["scenario_id"]: row for row in explanations}
    assert set(by_scenario) == set(EXPECTED_VALUES)
    for scenario_id, expected in EXPECTED_VALUES.items():
        row = by_scenario[scenario_id]
        for field, value in expected.items():
            assert field in row, f"{scenario_id} explanation row missing field {field}"
            assert row[field] == value, (
                f"{scenario_id}.{field}: expected {value!r}, got {row.get(field)!r}"
            )


def test_paper_ledger_events_carry_five_trainer_fields() -> None:
    proof = build_non_live_proof()
    events = proof["paper_ledger_result"]["events"]

    assert events, "paper ledger should contain fixture events"
    for event in events:
        for field in PARITY_FIELDS:
            assert field in event, f"paper ledger event missing field {field}: {event!r}"
            assert event[field] not in (None, "", "evidence_missing"), (
                f"paper ledger event has empty {field}: {event!r}"
            )


def test_build_trainer_gate_marker_flips_to_ready(tmp_path: Path) -> None:
    module = _load_builder_module()

    trainer_dir = tmp_path / "trainer_lineage_and_readiness/latest"
    public_trainer_dir = tmp_path / "public/trainer_lineage_and_readiness/latest"
    original_trainer = module.TRAINER
    original_public_trainer = module.PUBLIC_TRAINER
    try:
        module.TRAINER = trainer_dir
        module.PUBLIC_TRAINER = public_trainer_dir
        result = module.build_trainer_gate()
    finally:
        module.TRAINER = original_trainer
        module.PUBLIC_TRAINER = original_public_trainer

    assert result["marker"] == "TRAINER_LINEAGE_AND_READINESS_READY"
    assert result["gaps"] == []
    for field in PARITY_FIELDS:
        assert result["coverage"][field] is True

    runtime_marker = (trainer_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip()
    public_marker = (public_trainer_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip()
    assert runtime_marker == "TRAINER_LINEAGE_AND_READINESS_READY"
    assert public_marker == "TRAINER_LINEAGE_AND_READINESS_READY"
