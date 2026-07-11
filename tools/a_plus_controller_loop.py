#!/usr/bin/env python3
"""Safe A+ pipeline controller loop.

Runs the strategy-supply, paper, inventory, blocker, and evidence refresh path
without live orders, test orders, leverage mutation, or margin mutation.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_GOAL_ID = (
    "V2_CONTINUOUS_EDGE_FACTORY_PAPER_NEVER_STOPS_BINANCE_LIVE_TRADER_READY_A_PLUS_UNBLOCK_COMPLETION"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started, 6),
        "stdout_tail": completed.stdout[-4000:],
    }


def _safe_env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = ".:v2/backend"
    env["LIVE_GATE"] = "blocked_human_only"
    env["places_real_order"] = "false"
    env["routes_to_live"] = "false"
    env["order_transport_submit_enabled"] = "false"
    return env


def _blocker_action(
    *,
    summary: dict[str, Any],
    resolver: dict[str, Any],
    replay_status: dict[str, Any],
) -> dict[str, Any]:
    a_plus_count = int(summary.get("a_plus_candidate_count") or 0)
    live_ready_count = int(summary.get("live_ready_candidate_count") or 0)
    primary_blocker = str(summary.get("primary_blocker") or resolver.get("selected_blocker_class") or "")
    exact_blocker = str((resolver.get("action") or {}).get("exact_blocker") or "")
    matured_rows = int(replay_status.get("matured_counterfactual_rows") or 0)
    pending_rows = int(replay_status.get("pending_counterfactual_rows") or 0)
    if a_plus_count > 0:
        category = "INDEPENDENT_A_PLUS_CANDIDATE_READY"
        action = "RUN_LIVE_CANARY_DRY_RUN_KEEP_LIVE_BLOCKED"
        marker = "V2_CONTINUOUS_EDGE_FACTORY_A_PLUS_CANDIDATE_READY_LIVE_BLOCKED"
    elif primary_blocker == "RISK_GATEWAY_BLOCKER" and "GUARDIAN_HALTED" in exact_blocker:
        category = "PERFORMANCE_EVIDENCE_MATURATION"
        action = "KEEP_PAPER_SHADOW_COUNTERFACTUAL_REPLAY_AND_TRAINER_FEEDBACK_RUNNING"
        marker = "V2_CONTINUOUS_EDGE_FACTORY_RUNNING_GUARDIAN_PERFORMANCE_EVIDENCE_MATURING"
    elif matured_rows > 0 or pending_rows > 0:
        category = "LABEL_FACTORY_ACTIVE"
        action = "CONTINUE_REPLAY_COUNTERFACTUAL_MATURATION_AND_RERUN_INVENTORY"
        marker = "V2_CONTINUOUS_EDGE_FACTORY_RUNNING_LABEL_FACTORY_ACTIVE"
    else:
        category = "EVIDENCE_FACTORY_BOOTSTRAPPING"
        action = "PRODUCE_SHADOW_COUNTERFACTUAL_REPLAY_EVIDENCE_NEXT_CYCLE"
        marker = "V2_CONTINUOUS_EDGE_FACTORY_RUNNING_EVIDENCE_BOOTSTRAPPING"
    return {
        "schema_version": "continuous_edge_factory_blocker_action_v1",
        "generated_utc": _utc_now(),
        "category": category,
        "action": action,
        "final_marker": marker,
        "a_plus_candidate_count": a_plus_count,
        "live_ready_candidate_count": live_ready_count,
        "primary_blocker": primary_blocker,
        "exact_blocker": exact_blocker,
        "matured_counterfactual_rows": matured_rows,
        "pending_counterfactual_rows": pending_rows,
        "generic_blocked": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def run_controller(
    *,
    goal_id: str,
    output_dir: Path,
    max_cycles: int,
    sleep_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    repo = _repo_root()
    env = _safe_env(repo)
    output_dir.mkdir(parents=True, exist_ok=True)
    cycles: list[dict[str, Any]] = []
    final_marker = "V2_CONTINUOUS_EDGE_FACTORY_RUNNING_EVIDENCE_BOOTSTRAPPING"
    blocker_action_log = output_dir / "phase5_blocker_action_log.jsonl"

    for cycle in range(1, max(1, max_cycles) + 1):
        cycle_dir = output_dir / f"cycle_{cycle:03d}"
        inventory_dir = cycle_dir / "inventory"
        resolver_dir = cycle_dir / "resolver"
        evidence_dir = output_dir / "evidence_state"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        commands = [
            [
                sys.executable,
                "-m",
                "app.cli.v2_strategy_supply_publish_hypotheses",
                "--output-dir",
                str(cycle_dir / "strategy_supply"),
                "--ttl-seconds",
                "900",
                "--json",
            ],
            [
                sys.executable,
                "-m",
                "app.cli.v2_trade_management_paper_loop",
                "--once",
                "--out",
                str(cycle_dir / "paper_loop_once_status.json"),
            ],
            [
                sys.executable,
                "-m",
                "app.cli.v2_out_of_sample_reverify_evidence_producer",
                "realtime",
                "--out-dir",
                str(evidence_dir),
                "--realtime-rows",
                str(evidence_dir / "out_of_sample_realtime_paper_reverify_rows.jsonl"),
                "--read-redis",
                "--realtime-redis-only",
                "--summary-only",
            ],
            [
                sys.executable,
                "-m",
                "app.cli.v2_strategy_supply_feedback_maturation",
                "--pending-path",
                str(evidence_dir / "strategy_supply_pending_evidence.jsonl"),
                "--matured-path",
                str(evidence_dir / "strategy_supply_matured_evidence.jsonl"),
                "--rejected-path",
                str(evidence_dir / "strategy_supply_rejected_evidence.jsonl"),
                "--status-path",
                str(evidence_dir / "strategy_supply_feedback_maturation_status.json"),
                "--read-redis",
                "--publish-redis",
                "--json",
            ],
            [
                sys.executable,
                str(repo / "tools" / "edge_replay_factory_loop.py"),
                "--once",
                "--output-dir",
                str(cycle_dir / "edge_replay_factory"),
                "--publish-redis",
                "--json",
            ],
            [
                sys.executable,
                "-m",
                "app.cli.v2_a_plus_candidate_inventory",
                "--output-dir",
                str(inventory_dir),
                "--session",
                "current",
                "--all-symbols",
                "--all-timeframes",
                "--json",
            ],
            [
                sys.executable,
                "-m",
                "app.cli.v2_a_plus_blocker_resolver",
                "--inventory-dir",
                str(inventory_dir),
                "--output-dir",
                str(resolver_dir),
                "--json",
            ],
        ]
        results = [_run(command, cwd=repo, env=env, timeout=timeout_seconds) for command in commands]
        summary = _load_json(inventory_dir / "candidate_inventory_summary.json")
        resolver = _load_json(resolver_dir / "blocker_resolution_status.json")
        replay_status = _load_json(
            cycle_dir / "edge_replay_factory" / "phase3_historical_replay_edge_factory_status.json"
        )
        a_plus_count = int(summary.get("a_plus_candidate_count") or 0)
        live_ready_count = int(summary.get("live_ready_candidate_count") or 0)
        blocker_action = _blocker_action(
            summary=summary,
            resolver=resolver,
            replay_status=replay_status,
        )
        final_marker = str(blocker_action["final_marker"])
        with blocker_action_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(blocker_action, sort_keys=True) + "\n")
        cycle_record = {
            "cycle": cycle,
            "generated_utc": _utc_now(),
            "a_plus_candidate_count": a_plus_count,
            "live_ready_candidate_count": live_ready_count,
            "blocker_action": blocker_action,
            "commands": results,
            "paper_only": True,
            "places_real_order": False,
            "test_orders": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
        }
        cycles.append(cycle_record)
        (cycle_dir / "controller_cycle_status.json").write_text(
            json.dumps(cycle_record, indent=2, sort_keys=True) + "\n"
        )
        if a_plus_count > 0:
            dry_run_dir = cycle_dir / "live_dry_run"
            dry_run = _run(
                [
                    sys.executable,
                    "-m",
                    "app.cli.v2_live_canary_dry_run",
                    "--inventory-dir",
                    str(inventory_dir),
                    "--output-dir",
                    str(dry_run_dir),
                    "--json",
                ],
                cwd=repo,
                env=env,
                timeout=timeout_seconds,
            )
            cycle_record["live_dry_run"] = dry_run
            final_marker = "V2_CONTINUOUS_EDGE_FACTORY_A_PLUS_CANDIDATE_READY_LIVE_BLOCKED"
            break
        if cycle < max_cycles:
            time.sleep(max(0.0, sleep_seconds))

    status = {
        "schema_version": "continuous_edge_factory_controller_loop_status_v1",
        "generated_utc": _utc_now(),
        "goal_id": goal_id,
        "final_marker": final_marker,
        "cycle_count": len(cycles),
        "cycles": cycles,
        "blocker_action_log": str(blocker_action_log),
        "generic_blocked": False,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "live_gate_required": "blocked_human_only",
    }
    (output_dir / "phase8_a_plus_controller_loop_status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n"
    )
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal-id", default=DEFAULT_GOAL_ID)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=60.0)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir or Path("goal_state") / args.goal_id / "phase8_controller_loop"
    status = run_controller(
        goal_id=str(args.goal_id),
        output_dir=output_dir,
        max_cycles=int(args.max_cycles),
        sleep_seconds=float(args.sleep_seconds),
        timeout_seconds=int(args.timeout_seconds),
    )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(status["final_marker"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
