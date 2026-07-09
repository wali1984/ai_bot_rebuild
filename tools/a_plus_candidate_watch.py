#!/usr/bin/env python3
"""Watch current-session A+ candidate supply and run one blocker repair pass.

Read-only. The loop writes status artifacts and never submits orders, test
orders, leverage changes, margin changes, transfers, or withdrawals.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.cli.v2_a_plus_blocker_resolver import resolve_blocker  # noqa: E402
from v2.backend.app.cli.v2_a_plus_candidate_inventory import build_inventory  # noqa: E402
from v2.backend.app.cli.v2_live_canary_dry_run import build_dry_run_packet  # noqa: E402


GOAL_ID = "V2_A_PLUS_CANDIDATE_GENERATION_PREEMPTIVE_LIVE_CANARY_UNBLOCK_AND_OPERATOR_REVIEW_READY"
SCHEMA_VERSION = "a_plus_candidate_watch_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _redis_client(redis_url: str | None = None) -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    url = redis_url or os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def _one_blocker_artifact(
    *,
    output_dir: Path,
    inventory: Mapping[str, Any],
    resolver_status: Mapping[str, Any],
    final_state: str,
) -> dict[str, Any]:
    summary = dict(inventory.get("summary") or {})
    matrix = dict(inventory.get("rejection_matrix") or {})
    blocker_class = str(resolver_status.get("selected_blocker_class") or matrix.get("top_blocker_class") or "EXPECTED_NET_EDGE_BLOCKER")
    affected_count = int(resolver_status.get("affected_candidate_count") or 0)
    artifact = {
        "schema_version": "production_stack_ready_live_blocked_one_reason_v1",
        "generated_utc": _utc_now(),
        "final_state": final_state,
        "primary_blocker": blocker_class,
        "blocker_class": blocker_class,
        "affected_candidate_count": affected_count,
        "total_candidate_count": summary.get("total_candidate_count") or matrix.get("total_candidate_count") or 0,
        "top_symbols": summary.get("top_symbols") or [],
        "top_timeframes": list((summary.get("counts_by_timeframe") or {}).keys()),
        "exact_code_owner": "v2/backend/app/cli/v2_a_plus_candidate_inventory.py",
        "exact_function": "build_inventory",
        "exact_redis_key": "v2:paper:preemptive_candidate_decision_matrix",
        "exact_next_patch": (resolver_status.get("action") or {}).get("action_name"),
        "why_not_operator_action": "candidate supply has non-operator blockers before signed live review",
        "why_not_live_ready": "no independent current-session A+ live-ready candidate was produced",
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    _write_json(output_dir / "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON.json", artifact)
    return artifact


def run_watch(
    *,
    output_dir: Path,
    client: Any,
    interval_seconds: float = 60.0,
    max_iterations: int = 3,
    max_prediction_keys: int = 2500,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "a_plus_candidate_watch_status.json"
    iterations_path = output_dir / "a_plus_candidate_watch_iterations.jsonl"
    repair_actions_path = output_dir / "a_plus_repair_actions.jsonl"
    blocker_repeats: dict[str, int] = {}
    final_state = "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON"
    final_artifact: dict[str, Any] | None = None
    last_inventory: dict[str, Any] | None = None
    last_resolver: dict[str, Any] | None = None

    for index in range(1, max_iterations + 1):
        iteration_dir = output_dir / "candidate_inventory" / f"iteration_{index:03d}"
        inventory = build_inventory(
            client=client,
            output_dir=iteration_dir,
            session="current",
            max_prediction_keys=max_prediction_keys,
        )
        last_inventory = inventory
        summary = inventory["summary"]
        a_plus_rows = list(inventory.get("a_plus_rows") or [])
        live_ready_rows = list(inventory.get("rows") or [])
        live_ready_rows = [row for row in live_ready_rows if row.get("live_ready_candidate")]
        iteration = {
            "schema_version": f"{SCHEMA_VERSION}_iteration",
            "generated_utc": _utc_now(),
            "iteration": index,
            "total_candidate_count": summary.get("total_candidate_count"),
            "a_plus_candidate_count": summary.get("a_plus_candidate_count"),
            "live_ready_candidate_count": summary.get("live_ready_candidate_count"),
            "primary_blocker": summary.get("primary_blocker"),
        }
        if live_ready_rows or a_plus_rows:
            candidate = live_ready_rows[0] if live_ready_rows else a_plus_rows[0]
            packet_status = build_dry_run_packet(
                client=client,
                candidate=candidate,
                output_dir=output_dir,
            )
            final_state = (
                "OPERATOR_REVIEW_READY_FIRST_LIVE_CANARY"
                if packet_status["first_live_canary_operator_packet"].get("live_ready") is True
                else "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON"
            )
            iteration["packet_status"] = packet_status["first_live_canary_operator_packet"].get("status")
            iteration["final_state"] = final_state
            _append_jsonl(iterations_path, iteration)
            if final_state != "OPERATOR_REVIEW_READY_FIRST_LIVE_CANARY":
                last_resolver = resolve_blocker(inventory_dir=iteration_dir, output_dir=output_dir)
                if last_resolver.get("action"):
                    _append_jsonl(repair_actions_path, last_resolver["action"])
                final_artifact = _one_blocker_artifact(
                    output_dir=output_dir,
                    inventory=inventory,
                    resolver_status=last_resolver,
                    final_state=final_state,
                )
            break

        resolver_status = resolve_blocker(inventory_dir=iteration_dir, output_dir=output_dir)
        last_resolver = resolver_status
        if resolver_status.get("action"):
            _append_jsonl(repair_actions_path, resolver_status["action"])
        blocker = str(resolver_status.get("selected_blocker_class") or summary.get("primary_blocker") or "NO_BLOCKER")
        blocker_repeats[blocker] = blocker_repeats.get(blocker, 0) + 1
        iteration["resolver_status"] = resolver_status.get("status")
        iteration["selected_blocker_class"] = blocker
        iteration["same_blocker_repeat_count"] = blocker_repeats[blocker]
        _append_jsonl(iterations_path, iteration)
        if blocker == "SIGNED_READ_OPERATOR_BLOCKER":
            final_state = "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON"
            final_artifact = _one_blocker_artifact(
                output_dir=output_dir,
                inventory=inventory,
                resolver_status=resolver_status,
                final_state=final_state,
            )
            break
        if blocker_repeats[blocker] > 3:
            final_state = "BLOCKED_STABLE_BLOCKER"
            final_artifact = _one_blocker_artifact(
                output_dir=output_dir,
                inventory=inventory,
                resolver_status=resolver_status,
                final_state=final_state,
            )
            break
        if index < max_iterations and interval_seconds > 0:
            time.sleep(interval_seconds)
    else:
        if last_inventory is not None and last_resolver is not None:
            final_artifact = _one_blocker_artifact(
                output_dir=output_dir,
                inventory=last_inventory,
                resolver_status=last_resolver,
                final_state=final_state,
            )

    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _utc_now(),
        "goal_id": GOAL_ID,
        "status": final_state,
        "iterations_run": index if "index" in locals() else 0,
        "stable_blocker_repeats": blocker_repeats,
        "final_artifact": final_artifact,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    _write_json(status_path, status)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "goal_state" / GOAL_ID),
    )
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--max-prediction-keys", type=int, default=2500)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_watch(
        output_dir=Path(args.output_dir),
        client=_redis_client(args.redis_url),
        interval_seconds=args.interval_seconds,
        max_iterations=args.max_iterations,
        max_prediction_keys=args.max_prediction_keys,
    )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "status": status["status"],
            "iterations_run": status["iterations_run"],
            "stable_blocker_repeats": status["stable_blocker_repeats"],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
