from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_remediation():
    root = Path(__file__).resolve().parents[5]
    path = root / "claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py"
    spec = importlib.util.spec_from_file_location("v2_continuous_legacy_log_remediation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _enriched(causes_per_symbol: dict[str, list[str]]) -> dict:
    return {
        "per_symbol": [
            {
                "symbol": sym,
                "mismatch_causes_classified": causes,
                "match": False,
                "v2_action": "hold",
                "v2_paper_fill_allowed": True,
                "legacy_redis_action": "OPEN_LONG",
                "legacy_log_action": None,
            }
            for sym, causes in causes_per_symbol.items()
        ]
    }


def test_checkpoint_weight_missing_is_blocks_production_equivalence() -> None:
    mod = _load_remediation()
    gaps = mod._classify_gaps(_enriched({"BTCUSDT": ["checkpoint_weight_missing"]}))
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "BLOCKS_PRODUCTION_EQUIVALENCE"
    assert gaps[0]["gap_id"] == "trainer_missing_checkpoint_weight_shape_contract"


def test_v2_hold_due_strict_gate_is_operator_decision_required() -> None:
    mod = _load_remediation()
    gaps = mod._classify_gaps(_enriched({"ETHUSDT": ["V2_hold_due_strict_gate"]}))
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "OPERATOR_DECISION_REQUIRED"
    assert gaps[0]["gap_id"] == "trainer_missing_checkpoint_weight_shape_contract"


def test_missing_legacy_log_action_evidence_is_safe_block() -> None:
    mod = _load_remediation()
    gaps = mod._classify_gaps(_enriched({"SOLUSDT": ["missing_legacy_log_action_evidence"]}))
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "NO_ACTION_REQUIRED_SAFE_BLOCK"


def test_paper_fill_block_with_reasons_is_safe_block() -> None:
    mod = _load_remediation()
    enriched = {
        "per_symbol": [
            {
                "symbol": "SOLUSDT",
                "mismatch_causes_classified": ["v2_paper_fill_gate_blocked"],
                "match": False,
                "v2_action": "hold",
                "v2_paper_fill_allowed": False,
                "v2_paper_fill_gate_block_reasons": ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"],
                "legacy_redis_action": "OPEN_LONG",
                "legacy_log_action": "MISSING_EVIDENCE",
            }
        ]
    }
    gaps = mod._classify_gaps(enriched)
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "NO_ACTION_REQUIRED_SAFE_BLOCK"
    assert gaps[0]["gap_id"] == "paper_fill_gate_blocked_with_reason"
    assert gaps[0]["paper_fill_gate_block_reasons"] == ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]


def test_paper_fill_block_without_reasons_stays_p1() -> None:
    mod = _load_remediation()
    enriched = {
        "per_symbol": [
            {
                "symbol": "SOLUSDT",
                "mismatch_causes_classified": ["v2_paper_fill_gate_blocked"],
                "match": False,
                "v2_action": "hold",
                "v2_paper_fill_allowed": False,
                "v2_paper_fill_gate_block_reasons": [],
                "legacy_redis_action": "OPEN_LONG",
                "legacy_log_action": "MISSING_EVIDENCE",
            }
        ]
    }
    gaps = mod._classify_gaps(enriched)
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "P1_FIX"
    assert gaps[0]["gap_id"] == "paper_fill_gate_block_reason_passthrough_missing"


def test_unknown_cause_falls_back_to_p1_fix() -> None:
    mod = _load_remediation()
    gaps = mod._classify_gaps(_enriched({"BTCUSDT": ["feature_freshness_mismatch"]}))
    assert len(gaps) == 1
    assert gaps[0]["severity"] == "P1_FIX"
    assert gaps[0]["gap_id"] == "feature_pipeline_freshness_mismatch_for_symbol"


def test_match_rows_with_no_causes_are_dropped() -> None:
    mod = _load_remediation()
    enriched = {
        "per_symbol": [
            {
                "symbol": "BTCUSDT",
                "mismatch_causes_classified": [],
                "match": True,
            }
        ]
    }
    assert mod._classify_gaps(enriched) == []
