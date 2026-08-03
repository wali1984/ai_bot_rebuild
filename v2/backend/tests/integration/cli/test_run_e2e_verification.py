from __future__ import annotations

import json

from v2.backend.app.cli import run_e2e_verification as cli
from v2.backend.app.services.e2e_verification.service import (
    ScenarioRun,
    VerificationReport,
)


def test_run_e2e_verification_writes_json_and_text_reports(tmp_path) -> None:
    exit_code = cli.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    json_path = tmp_path / "e2e_verification_report.json"
    text_path = tmp_path / "e2e_verification_report.txt"
    replay_path = tmp_path / "e2e_verification_replays.json"
    assert json_path.exists()
    assert text_path.exists()
    assert replay_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["scenario_count"] == 11
    assert payload["summary"]["critical_failures"] == 0
    assert "clean_trending_up_market" in text_path.read_text(encoding="utf-8")


def test_run_e2e_verification_exits_nonzero_when_critical_failure_present(
    monkeypatch,
    tmp_path,
) -> None:
    report = VerificationReport(
        generated_at="2026-06-11T00:00:00Z",
        output_dir=str(tmp_path),
        scenarios=[
            ScenarioRun(
                scenario_name="forced_failure",
                expected_result="forced failure",
                actual_result="BLOCKED_BY_DATA_GATE",
                passed=False,
                critical=True,
                decision_id="dec_fail",
                data_quality_flags=["missing_required_candles"],
                masa_ppo_cutoff={
                    "masa_feature_cutoffs": {},
                    "ppo_feature_cutoff": "2026-06-11T00:00:00Z",
                    "stale_masa_prediction": False,
                    "future_leakage_detected": False,
                    "cutoff_mismatch": False,
                },
                risk_decision={"risk_action": "deny", "risk_reason_code": "deny_data_integrity_gate"},
                trade_approved=False,
                training_sample_accepted=False,
                strategy_mode="no_trade_mode",
                replay_snapshot={"decision_id": "dec_fail"},
            )
        ],
        summary={
            "scenario_count": 1,
            "passed_count": 0,
            "failed_count": 1,
            "critical_failures": 1,
            "all_decision_ids_replayable": True,
            "clean_data_valid_decisions": False,
            "dirty_data_blocked_from_training": True,
            "dirty_data_blocked_from_execution": True,
        },
        replay_records={"dec_fail": {"decision_id": "dec_fail"}},
    )

    def _fake_runner(*, output_dir):  # noqa: ARG001
        return report, 1

    monkeypatch.setattr(cli, "run_e2e_verification_report", _fake_runner)

    exit_code = cli.main(["--output-dir", str(tmp_path)])

    assert exit_code == 1
