"""V2 1000x goal-trajectory telemetry — read-only mirror of the tracker key.

Exposes ``GET /api/v2/goal/trajectory-1000x`` which echoes the Redis key
``v2:goal:trajectory_1000x`` written every 5 minutes by the
``ai-bot-v2-1000x-trajectory-tracker`` service (goal telemetry; paper-only;
never trades).

This route:
- never places orders, mutates leverage/margin, or touches the live gate
- reads only the ``v2:`` namespace
- adds honest server-side staleness (``age_seconds`` computed from the
  payload's ``generated_utc``) so the GUI can never render stale telemetry
  as fresh
- is public-read, matching the posture of the other control-center
  telemetry contracts (e.g. ``/api/v2/a-plus/inventory``).

The objective string in the payload is explicit that this is a research
objective, not a promise; the route must preserve it verbatim.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.api.v2.control_center_status import _age_seconds, _contract, _read_json

router = APIRouter(prefix="/goal", tags=["v2-goal-trajectory"])

GOAL_TRAJECTORY_1000X_KEY = "v2:goal:trajectory_1000x"
# Publisher refresh cadence (ai-bot-v2-1000x-trajectory-tracker): 5 minutes.
PUBLISH_INTERVAL_SECONDS = 300.0
# GUI amber threshold — anything older than 15 minutes is stale telemetry.
STALE_AFTER_SECONDS = 900.0


@router.get("/trajectory-1000x")
async def get_goal_trajectory_1000x() -> dict[str, Any]:
    """Read-only 1000x trajectory telemetry with honest staleness."""
    client = get_redis()
    payload = _read_json(client, GOAL_TRAJECTORY_1000X_KEY)
    source_key_present = bool(payload)
    age_seconds = _age_seconds(payload) if source_key_present else None

    data: dict[str, Any] = dict(payload)
    data["source_key_present"] = source_key_present
    # Echo generated_utc explicitly (even when missing) and add the
    # server-computed age so clients never have to trust their own clock.
    data["generated_utc"] = payload.get("generated_utc")
    data["age_seconds"] = age_seconds
    data["publish_interval_seconds"] = PUBLISH_INTERVAL_SECONDS
    data["stale_after_seconds"] = STALE_AFTER_SECONDS
    data["is_stale"] = (
        not source_key_present
        or age_seconds is None
        or age_seconds > STALE_AFTER_SECONDS
    )
    if not source_key_present:
        # Source-key honesty: the key is missing/expired, which means the
        # tracker service is stale — not "trajectory unknown but fine".
        data["missing_reason"] = (
            "GOAL_TRAJECTORY_KEY_MISSING_OR_EXPIRED_TRACKER_STALE"
        )

    return _contract(
        schema_version="goal_trajectory_1000x_contract_v1",
        canonical_owner="/api/v2/goal/trajectory-1000x",
        source=f"redis:{GOAL_TRAJECTORY_1000X_KEY}",
        data=data,
        staleness_seconds=age_seconds,
    )
