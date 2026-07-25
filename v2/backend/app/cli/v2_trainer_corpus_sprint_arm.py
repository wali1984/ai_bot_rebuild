"""Arm / disarm / inspect the operator-armed trainer corpus sprint.

The sprint accelerates the profiled-base-feature publisher (full admission-ready
eligible universe, short cycle) and the trainer manifest cadence toward the strict
1,000 admitted-training-row gate for a bounded, auto-expiring window.

This CLI ONLY writes the operator-armed control signal + an honest status. It does
NOT restart the publisher, mutate any immutable release, grant trading/promotion/
serving/live authority, or touch the strict 1,000-row promotion gate. The arm is a
paper-only, self-expiring Redis record (TTL == duration) so normal configuration is
restored automatically even if nothing calls --disarm.

Runtime consumption of the arm (per-cycle full-universe selection at the sprint
cadence) requires the publisher release that carries BOTH the disk-horizon override
AND the throughput controller, plus operator-provisioned publisher credentials — see
the status field ``execution_blockers`` for the current gating.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime

from v2.backend.app.services.trainer_corpus_sprint.sprint_arm_v1 import (
    DEFAULT_MIN_FREE_DISK_BYTES,
    MAX_DISK_GROWTH_BYTES,
    MAX_DURATION_SECONDS,
    MAX_SELECTED_SYMBOLS,
    SPRINT_CYCLE_SECONDS,
    create_sprint_arm,
    disarm_sprint,
    validate_sprint_arm,
)

SPRINT_STATUS_KEY = "v2:trainer:corpus_sprint:status"
DATA_ROOT = os.environ.get(
    "V2_NATIVE_TRAINER_DATA_ROOT", "/home/wali/ai_bot_local_data/v2_native_trainer"
)

# Honest execution gating: the running publisher is an immutable release that does
# not carry the arm-consumption path, its credentials are operator-provisioned, and
# a restart into absent credentials fails closed (exit 78). These must clear before
# the arm actually accelerates the publisher.
EXECUTION_BLOCKERS = [
    "PUBLISHER_RUNS_IMMUTABLE_RELEASE_WITHOUT_ARM_CONSUMPTION_PATH",
    "PUBLISHER_HORIZON_OVERRIDE_AND_THROUGHPUT_CONTROLLER_NOT_IN_ONE_RELEASE",
    "PUBLISHER_OPERATOR_CREDENTIALS_REQUIRED_FOR_RESTART_EXIT78_IF_ABSENT",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _redis():
    import redis

    url = os.environ.get("V2_REDIS_URL", "redis://127.0.0.1:6379/0")
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)


def _disk_bytes() -> tuple[int, int]:
    usage = shutil.disk_usage(DATA_ROOT)
    return int(usage.used), int(usage.free)


def _publish_status(r, arm_payload: dict | None, *, armed: bool) -> dict:
    used, free = _disk_bytes()
    status = {
        "schema_version": "v2_trainer_corpus_sprint_status_v1",
        "generated_utc": _now().isoformat().replace("+00:00", "Z"),
        "state": "STRICT_TRAIN_ROW_SPRINT_ACTIVE" if armed else "STRICT_TRAIN_ROW_SPRINT_DISARMED",
        "operator_authorized": bool(arm_payload) if armed else False,
        "arm": arm_payload,
        "disk_used_bytes": used,
        "disk_free_bytes": free,
        # Honest: the arm is the operator control signal; runtime acceleration is
        # still gated on the items below (a hollow "accelerating" claim is avoided).
        "publisher_acceleration_active": False,
        "execution_blockers": EXECUTION_BLOCKERS if armed else [],
        "safety": {
            "paper_only": True,
            "non_promotable": True,
            "live_eligible": False,
            "routes_to_live": False,
            "places_real_order": False,
            "live_gate": "blocked_human_only",
            "strict_champion_min_train_rows_unchanged": 1000,
        },
    }
    r.set(SPRINT_STATUS_KEY, json.dumps(status, sort_keys=True), ex=MAX_DURATION_SECONDS)
    return status


def cmd_arm(args: argparse.Namespace) -> int:
    r = _redis()
    used, free = _disk_bytes()
    now = _now()
    arm = create_sprint_arm(
        r,
        arm_id="corpus_sprint_" + now.strftime("%Y%m%dT%H%M%SZ"),
        now=now,
        minimum_free_disk_bytes=int(args.minimum_free_disk_bytes),
        maximum_duration_seconds=int(args.duration_seconds),
        maximum_disk_growth_bytes=int(args.max_disk_growth_bytes),
        maximum_selected_symbols=int(args.max_symbols),
        baseline_disk_used_bytes=used,
        cycle_seconds=int(args.cycle_seconds),
        operator_authorized=True,
    )
    arm_payload = json.loads(arm.to_json())
    status = _publish_status(r, arm_payload, armed=True)
    print(json.dumps({"armed": True, "arm": arm_payload, "status": status}, indent=2))
    return 0


def cmd_disarm(_args: argparse.Namespace) -> int:
    r = _redis()
    disarm_sprint(r)
    status = _publish_status(r, None, armed=False)
    print(json.dumps({"armed": False, "status": status}, indent=2))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    r = _redis()
    used, free = _disk_bytes()
    disk_growth = None
    arm, reject = validate_sprint_arm(
        redis_client=r,
        now=_now(),
        current_free_disk_bytes=free,
        current_disk_growth_bytes=disk_growth,
        publisher_restart_count=0,
    )
    raw = r.get(SPRINT_STATUS_KEY)
    print(
        json.dumps(
            {
                "arm_valid": arm is not None,
                "reject_reason": reject,
                "disk_free_bytes": free,
                "published_status": json.loads(raw) if raw else None,
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trainer corpus-sprint arm control")
    sub = parser.add_subparsers(dest="command", required=True)

    p_arm = sub.add_parser("arm", help="Operator-arm the sprint (auto-expiring)")
    p_arm.add_argument("--duration-seconds", type=int, default=MAX_DURATION_SECONDS)
    p_arm.add_argument("--max-disk-growth-bytes", type=int, default=MAX_DISK_GROWTH_BYTES)
    p_arm.add_argument("--max-symbols", type=int, default=MAX_SELECTED_SYMBOLS)
    p_arm.add_argument("--cycle-seconds", type=int, default=SPRINT_CYCLE_SECONDS)
    p_arm.add_argument(
        "--minimum-free-disk-bytes", type=int, default=DEFAULT_MIN_FREE_DISK_BYTES
    )
    p_arm.set_defaults(func=cmd_arm)

    p_dis = sub.add_parser("disarm", help="Disarm + restore normal configuration")
    p_dis.set_defaults(func=cmd_disarm)

    p_stat = sub.add_parser("status", help="Show the current arm + guard state")
    p_stat.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
