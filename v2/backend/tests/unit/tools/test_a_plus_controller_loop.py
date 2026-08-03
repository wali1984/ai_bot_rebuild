from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tools.a_plus_controller_loop as controller


def test_controller_uses_persistent_evidence_state_for_maturation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int,
    ) -> dict[str, Any]:
        _ = cwd, env, timeout
        commands.append(command)
        if "app.cli.v2_a_plus_candidate_inventory" in command:
            output_dir = Path(command[command.index("--output-dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "candidate_inventory_summary.json").write_text(
                json.dumps(
                    {
                        "a_plus_candidate_count": 0,
                        "live_ready_candidate_count": 0,
                    }
                )
                + "\n"
            )
        if any("edge_replay_factory_loop.py" in part for part in command):
            output_dir = Path(command[command.index("--output-dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "phase3_historical_replay_edge_factory_status.json").write_text(
                json.dumps(
                    {
                        "matured_counterfactual_rows": 0,
                        "pending_counterfactual_rows": 3,
                    }
                )
                + "\n"
            )
        if "app.cli.v2_a_plus_blocker_resolver" in command:
            output_dir = Path(command[command.index("--output-dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "blocker_resolution_status.json").write_text(
                json.dumps(
                    {
                        "selected_blocker_class": "RISK_GATEWAY_BLOCKER",
                        "action": {"exact_blocker": "GUARDIAN_HALTED_AFTER_PIT_THRESHOLD_MET"},
                    }
                )
                + "\n"
            )
        return {"command": command, "returncode": 0, "duration_seconds": 0.0, "stdout_tail": ""}

    monkeypatch.setattr(controller, "_run", fake_run)
    output_dir = tmp_path / "controller"

    status = controller.run_controller(
        goal_id="unit-goal",
        output_dir=output_dir,
        max_cycles=2,
        sleep_seconds=0,
        timeout_seconds=1,
    )

    evidence_state = str(output_dir / "evidence_state")
    evidence_commands = [
        command for command in commands if "app.cli.v2_out_of_sample_reverify_evidence_producer" in command
    ]
    maturation_commands = [
        command for command in commands if "app.cli.v2_strategy_supply_feedback_maturation" in command
    ]
    replay_commands = [
        command for command in commands if any("edge_replay_factory_loop.py" in part for part in command)
    ]
    assert len(evidence_commands) == 2
    assert len(maturation_commands) == 2
    assert len(replay_commands) == 2
    assert all(command[command.index("--out-dir") + 1] == evidence_state for command in evidence_commands)
    assert all(
        command[command.index("--pending-path") + 1]
        == str(output_dir / "evidence_state" / "strategy_supply_pending_evidence.jsonl")
        for command in maturation_commands
    )
    assert "cycle_001/evidence" not in json.dumps(commands)
    assert status["final_marker"] == "V2_CONTINUOUS_EDGE_FACTORY_RUNNING_GUARDIAN_PERFORMANCE_EVIDENCE_MATURING"
    assert status["generic_blocked"] is False
    assert status["paper_only"] is True
    assert status["places_real_order"] is False
