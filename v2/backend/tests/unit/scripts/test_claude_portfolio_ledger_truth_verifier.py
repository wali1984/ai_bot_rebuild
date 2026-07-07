from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_verifier_module():
    repo_root = Path(__file__).resolve().parents[5]
    path = repo_root / "tools" / "claude_portfolio_ledger_truth_verifier.py"
    spec = importlib.util.spec_from_file_location("claude_portfolio_ledger_truth_verifier", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trainer_quarantine_allows_valid_consumable_rows_without_quarantine() -> None:
    verifier = _load_verifier_module()

    result = verifier.check_09_trainer_quarantine_isolation(
        {
            "trainer_feedback_quarantined_row_count": 0,
            "trainer_feedback_consumable_row_count": 2,
            "trainer_feedback_outcomes_quarantine": [],
            "trainer_feedback_outcomes": [
                {"fill_id": "valid-1"},
                {"fill_id": "valid-2"},
            ],
        }
    )

    assert result["status"] == "PASS"
    assert result["quarantine_clean"] is True
    assert result["valid_consumable_rows_allowed"] is True


def test_trainer_quarantine_fails_when_quarantined_row_is_consumed() -> None:
    verifier = _load_verifier_module()

    result = verifier.check_09_trainer_quarantine_isolation(
        {
            "trainer_feedback_quarantined_row_count": 1,
            "trainer_feedback_consumable_row_count": 1,
            "trainer_feedback_outcomes_quarantine": [{"fill_id": "bad-fill"}],
            "trainer_feedback_outcomes": [{"fill_id": "bad-fill"}],
        }
    )

    assert result["status"] == "ALERT_QUARANTINE_BREACH"
    assert result["overlap_fill_ids"] == ["bad-fill"]


def test_paper_loop_inactive_passes_when_new_entries_are_halted(monkeypatch) -> None:
    verifier = _load_verifier_module()

    monkeypatch.setattr(verifier, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )

    result = verifier.check_15_paper_loop_pid_health(
        entry_freeze={
            "paper_new_entries_halted": True,
            "new_entries_allowed": False,
            "reason": "CLEAN_3000_SESSION_5_TRADE_GATE_FAILED",
        }
    )

    assert result["status"] == "PASS"
    assert result["expected_inactive_due_to_halt"] is True
    assert result["halt_reason"] == "CLEAN_3000_SESSION_5_TRADE_GATE_FAILED"
