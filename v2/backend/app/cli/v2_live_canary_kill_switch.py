"""V2 live-canary kill-switch CLI (arm / disarm / status).

The kill switch is the operator's emergency stop. When ARMED, the
executor's gate cascade refuses every candidate with
``KILL_SWITCH_ARMED_BLOCKED_HUMAN_ONLY``.

Default ARM behavior is one-line, idempotent, and reversible.
``--disarm`` requires the operator approval file to be present and a
codex pass marker to exist; without those, ``--disarm`` is refused.

NEVER places, cancels, or modifies any exchange entry. NEVER writes
outside ``v2:live_canary:*``. NEVER touches legacy keys. The kill
switch *cannot* approve trading; arming or disarming the switch does
not flip ``live_enabled`` to True.

Allowed Redis writes:
- ``v2:live_canary:kill_switch``
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.live_canary.execution_adapter import (
    APPROVAL_FILE_PATH,
    CODEX_PASS_MARKER_PATH,
    DEFAULT_KILL_SWITCH_TTL_SECONDS,
    KEY_KILL_SWITCH,
    LIVE_CANARY_NAMESPACE,
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _safe_set(r, key: str, value: str, ex: int) -> bool:
    if r is None:
        return False
    if not key.startswith(LIVE_CANARY_NAMESPACE):
        return False
    try:
        r.set(key, value, ex=int(ex))
        return True
    except Exception:
        return False


def _read_status(r) -> dict[str, Any]:
    if r is None:
        return {"redis_connected": False, "armed": True}  # fail closed
    try:
        raw = r.get(KEY_KILL_SWITCH)
    except Exception:
        return {"redis_connected": True, "armed": True, "read_error": True}
    if raw is None:
        return {"redis_connected": True, "armed": False, "value": None}
    text = str(raw).strip()
    armed_now = text.lower() not in ("", "false", "0", "off", "disarmed")
    return {
        "redis_connected": True,
        "armed": armed_now,
        "value": text,
    }


def arm(
    r,
    *,
    reason: str,
    operator: str,
    ttl_seconds: int = DEFAULT_KILL_SWITCH_TTL_SECONDS,
) -> dict[str, Any]:
    payload = {
        "schema_version": "v2_live_canary_kill_switch_v1",
        "armed": True,
        "armed_utc": _utc_iso(),
        "reason": reason or "OPERATOR_EMERGENCY_STOP",
        "operator": operator or "UNKNOWN_OPERATOR",
        "ttl_seconds": int(ttl_seconds),
    }
    ok = _safe_set(r, KEY_KILL_SWITCH, json.dumps(payload), ex=int(ttl_seconds))
    return {"applied": ok, "payload": payload}


def disarm(
    r,
    *,
    operator: str,
    approval_path: Path,
    codex_marker_path: Path,
    confirm: bool,
) -> dict[str, Any]:
    """Disarm the kill switch ONLY when the operator approval file +
    Codex pass marker exist AND ``--confirm`` is passed. Otherwise the
    disarm is refused.
    """
    blockers: list[str] = []
    if not approval_path.exists():
        blockers.append("OPERATOR_APPROVAL_FILE_ABSENT")
    if not codex_marker_path.exists():
        blockers.append("CODEX_LIVE_CANARY_PASS_MARKER_ABSENT")
    if not confirm:
        blockers.append("DISARM_CONFIRMATION_FLAG_NOT_SET")
    if blockers:
        return {
            "applied": False,
            "refused_blockers": blockers,
            "armed": True,
        }
    payload = {
        "schema_version": "v2_live_canary_kill_switch_v1",
        "armed": False,
        "disarmed_utc": _utc_iso(),
        "operator": operator or "UNKNOWN_OPERATOR",
    }
    ok = _safe_set(r, KEY_KILL_SWITCH, "false", ex=DEFAULT_KILL_SWITCH_TTL_SECONDS)
    return {"applied": ok, "payload": payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_live_canary_kill_switch")
    sub = parser.add_subparsers(dest="action", required=True)

    p_arm = sub.add_parser("arm", help="Arm the kill switch immediately")
    p_arm.add_argument("--reason", type=str, default="OPERATOR_EMERGENCY_STOP")
    p_arm.add_argument("--operator", type=str, default="UNKNOWN_OPERATOR")
    p_arm.add_argument(
        "--ttl-seconds", type=int, default=DEFAULT_KILL_SWITCH_TTL_SECONDS
    )

    p_disarm = sub.add_parser("disarm", help="Disarm the kill switch (requires approvals)")
    p_disarm.add_argument("--operator", type=str, default="UNKNOWN_OPERATOR")
    p_disarm.add_argument("--approval-path", type=Path, default=APPROVAL_FILE_PATH)
    p_disarm.add_argument(
        "--codex-pass-marker-path", type=Path, default=CODEX_PASS_MARKER_PATH
    )
    p_disarm.add_argument("--confirm", action="store_true")

    sub.add_parser("status", help="Print kill-switch status")

    args = parser.parse_args(argv)
    r = _connect_redis()
    if args.action == "arm":
        result = arm(
            r,
            reason=args.reason,
            operator=args.operator,
            ttl_seconds=args.ttl_seconds,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["applied"] else 1
    if args.action == "disarm":
        result = disarm(
            r,
            operator=args.operator,
            approval_path=args.approval_path,
            codex_marker_path=args.codex_pass_marker_path,
            confirm=args.confirm,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["applied"] else 2
    if args.action == "status":
        result = _read_status(r)
        print(json.dumps(result, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
