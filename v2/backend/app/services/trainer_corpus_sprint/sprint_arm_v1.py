"""TrainerCorpusSprintArmV1 — operator-armed, auto-expiring corpus-sprint control.

The sprint accelerates the profiled-base-feature publisher (full admission-ready
eligible universe, short cycle) and the trainer manifest cadence toward the strict
1,000 admitted-training-row gate, for a bounded window. It is deliberately
fail-closed and self-limiting:

* paper-only, never live-eligible, never routes to exchange;
* automatically expires (Redis TTL == maximum_duration_seconds) so the normal
  publisher configuration is restored even if nothing calls the disarm path;
* disables itself the moment any resource guard trips (disk growth cap, free-disk
  reserve, publisher restart) — a running publisher restart during a sprint is
  treated as a fault, not a retry.

This module is PURE + side-effect-minimal (only Redis get/set) so it is fully unit
testable. It grants NO trading, promotion, serving, or live authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

SPRINT_ARM_KEY = "v2:trainer:corpus_sprint:arm"

# Hard limits from the operator's six-hour sprint contract.
MAX_DURATION_SECONDS = 21_600  # 6 hours
MAX_DISK_GROWTH_BYTES = 21_474_836_480  # 20 GiB
MAX_SELECTED_SYMBOLS = 74
DEFAULT_MIN_FREE_DISK_BYTES = 40 * 1024**3  # 40 GiB safe reserve default

# Cycle cadence (Phase 6).
SPRINT_CYCLE_SECONDS = 180
SPRINT_CYCLE_BACKOFF_SECONDS = 300
SPRINT_CYCLE_ELAPSED_BACKOFF_THRESHOLD = 120

# Publication-health pause (Phase 6): pause + report when the publisher cannot
# sustain a third of its attempts across three consecutive cycles.
SPRINT_LOW_SUCCESS_RATIO = 0.33
SPRINT_LOW_SUCCESS_CONSECUTIVE_CYCLES = 3


@dataclass(frozen=True)
class TrainerCorpusSprintArmV1:
    arm_id: str
    armed_at: str
    expires_at: str
    minimum_free_disk_bytes: int
    maximum_duration_seconds: int = MAX_DURATION_SECONDS
    maximum_disk_growth_bytes: int = MAX_DISK_GROWTH_BYTES
    maximum_selected_symbols: int = MAX_SELECTED_SYMBOLS
    paper_only: bool = True
    live_eligible: bool = False
    operator_authorized: bool = True
    non_promotable: bool = True
    routes_to_live: bool = False
    baseline_disk_used_bytes: int | None = None
    cycle_seconds: int = SPRINT_CYCLE_SECONDS
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        payload = {
            "arm_id": self.arm_id,
            "armed_at": self.armed_at,
            "expires_at": self.expires_at,
            "maximum_duration_seconds": self.maximum_duration_seconds,
            "maximum_disk_growth_bytes": self.maximum_disk_growth_bytes,
            "maximum_selected_symbols": self.maximum_selected_symbols,
            "minimum_free_disk_bytes": self.minimum_free_disk_bytes,
            "paper_only": self.paper_only,
            "live_eligible": self.live_eligible,
            "operator_authorized": self.operator_authorized,
            "non_promotable": self.non_promotable,
            "routes_to_live": self.routes_to_live,
            "baseline_disk_used_bytes": self.baseline_disk_used_bytes,
            "cycle_seconds": self.cycle_seconds,
            **self.extra,
        }
        return json.dumps(payload, sort_keys=True)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def create_sprint_arm(
    redis_client: Any,
    *,
    arm_id: str,
    now: datetime,
    minimum_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
    maximum_duration_seconds: int = MAX_DURATION_SECONDS,
    maximum_disk_growth_bytes: int = MAX_DISK_GROWTH_BYTES,
    maximum_selected_symbols: int = MAX_SELECTED_SYMBOLS,
    baseline_disk_used_bytes: int | None = None,
    cycle_seconds: int = SPRINT_CYCLE_SECONDS,
    operator_authorized: bool = True,
) -> TrainerCorpusSprintArmV1:
    """Arm the sprint. TTL == duration so it self-expires and normal config resumes.

    ``operator_authorized`` must be True — the sprint is only ever operator-armed.
    """
    if not operator_authorized:
        raise ValueError("TRAINER_CORPUS_SPRINT_REQUIRES_OPERATOR_AUTHORIZATION")
    duration = max(1, min(int(maximum_duration_seconds), MAX_DURATION_SECONDS))
    disk_cap = max(1, min(int(maximum_disk_growth_bytes), MAX_DISK_GROWTH_BYTES))
    symbol_cap = max(1, min(int(maximum_selected_symbols), MAX_SELECTED_SYMBOLS))
    expires = now.astimezone(UTC) + timedelta(seconds=duration)
    arm = TrainerCorpusSprintArmV1(
        arm_id=str(arm_id),
        armed_at=now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        expires_at=expires.isoformat().replace("+00:00", "Z"),
        minimum_free_disk_bytes=int(minimum_free_disk_bytes),
        maximum_duration_seconds=duration,
        maximum_disk_growth_bytes=disk_cap,
        maximum_selected_symbols=symbol_cap,
        baseline_disk_used_bytes=baseline_disk_used_bytes,
        cycle_seconds=int(cycle_seconds),
        operator_authorized=True,
    )
    redis_client.set(SPRINT_ARM_KEY, arm.to_json(), ex=duration)
    return arm


def read_sprint_arm(redis_client: Any) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(SPRINT_ARM_KEY)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def validate_sprint_arm(
    *,
    redis_client: Any,
    now: datetime,
    current_free_disk_bytes: int | None = None,
    current_disk_growth_bytes: int | None = None,
    publisher_restart_count: int = 0,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (arm, None) when the sprint is live and safe, else (None, reason).

    Fail-closed: any missing field, expiry, wrong authority, or tripped resource
    guard rejects. Callers must treat a reject as "run normal configuration".
    """
    data = read_sprint_arm(redis_client)
    if not data:
        return None, "SPRINT_ARM_ABSENT_OR_EXPIRED"
    if data.get("operator_authorized") is not True:
        return None, "SPRINT_ARM_NOT_OPERATOR_AUTHORIZED"
    if data.get("paper_only") is not True:
        return None, "SPRINT_ARM_NOT_PAPER_ONLY"
    if data.get("live_eligible") is True or data.get("routes_to_live") is True:
        return None, "SPRINT_ARM_LIVE_MARKER_PRESENT"
    expires = _parse_utc(data.get("expires_at"))
    if expires is None:
        return None, "SPRINT_ARM_EXPIRY_UNPARSEABLE"
    if now.astimezone(UTC) >= expires:
        return None, "SPRINT_ARM_EXPIRED"
    if int(publisher_restart_count or 0) > 0:
        return None, "SPRINT_ARM_PUBLISHER_RESTARTED"
    disk_cap = int(data.get("maximum_disk_growth_bytes") or MAX_DISK_GROWTH_BYTES)
    if current_disk_growth_bytes is not None and int(current_disk_growth_bytes) > disk_cap:
        return None, "SPRINT_ARM_DISK_GROWTH_CAP_EXCEEDED"
    min_free = int(data.get("minimum_free_disk_bytes") or DEFAULT_MIN_FREE_DISK_BYTES)
    if current_free_disk_bytes is not None and int(current_free_disk_bytes) < min_free:
        return None, "SPRINT_ARM_FREE_DISK_BELOW_RESERVE"
    return data, None


def sprint_cycle_seconds(
    *,
    base_cycle_seconds: int = SPRINT_CYCLE_SECONDS,
    last_cycle_elapsed_seconds: float | None = None,
) -> int:
    """Adaptive cadence: start at 180s, back off to 300s when a cycle overruns."""
    if (
        last_cycle_elapsed_seconds is not None
        and float(last_cycle_elapsed_seconds) > SPRINT_CYCLE_ELAPSED_BACKOFF_THRESHOLD
    ):
        return SPRINT_CYCLE_BACKOFF_SECONDS
    return int(base_cycle_seconds)


def sprint_disable_decision(
    *,
    publisher_restart_count: int = 0,
    disk_growth_bytes: int | None = None,
    disk_growth_cap_bytes: int = MAX_DISK_GROWTH_BYTES,
    free_disk_bytes: int | None = None,
    minimum_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
    low_success_consecutive_cycles: int = 0,
) -> tuple[bool, bool, list[str]]:
    """Return (disable_sprint, pause_and_report, reasons) per the Phase-6 rules.

    * disable_sprint -> hard stop the sprint and restore normal config.
    * pause_and_report -> soft pause, surface the exact publication blockers.
    """
    reasons: list[str] = []
    disable = False
    pause = False
    if int(publisher_restart_count or 0) > 0:
        disable = True
        reasons.append("PUBLISHER_RESTARTED")
    if disk_growth_bytes is not None and int(disk_growth_bytes) > int(disk_growth_cap_bytes):
        disable = True
        reasons.append("DISK_GROWTH_CAP_EXCEEDED")
    if free_disk_bytes is not None and int(free_disk_bytes) < int(minimum_free_disk_bytes):
        disable = True
        reasons.append("FREE_DISK_BELOW_RESERVE")
    if int(low_success_consecutive_cycles or 0) >= SPRINT_LOW_SUCCESS_CONSECUTIVE_CYCLES:
        pause = True
        reasons.append("PUBLICATION_SUCCESS_RATIO_LOW_THREE_CYCLES")
    return disable, pause, reasons


def estimate_commits_needed(
    *,
    strict_train_rows_remaining: int,
    admission_yield_ratio: float | None,
) -> int | None:
    """estimated_commits_needed = remaining / yield (recomputed each terminal cycle)."""
    if strict_train_rows_remaining <= 0:
        return 0
    if not admission_yield_ratio or admission_yield_ratio <= 0.0:
        return None
    return int(strict_train_rows_remaining / float(admission_yield_ratio) + 0.999)


def disarm_sprint(redis_client: Any) -> bool:
    """Best-effort explicit disarm (the TTL is the durable backstop)."""
    try:
        redis_client.delete(SPRINT_ARM_KEY)
        return True
    except Exception:  # noqa: BLE001
        return False


def is_sprint_active(redis_client: Any, *, now: datetime, **guards: Any) -> bool:
    arm, _reject = validate_sprint_arm(redis_client=redis_client, now=now, **guards)
    return arm is not None


def paper_recovery_train_gate(
    *,
    train_rows: int | None,
    min_train_rows: int,
) -> dict[str, Any]:
    """The recovery train-row gate (Phase 1 telemetry): 272/256 PASS.

    Independent of the strict champion gate. Never blocks paper fill on the strict
    1,000 requirement; only checks the paper-recovery minimum.
    """
    have = int(train_rows) if isinstance(train_rows, int | float) else None
    satisfied = have is not None and have >= int(min_train_rows)
    return {
        "paper_recovery_min_train_rows": int(min_train_rows),
        "paper_recovery_train_rows": have,
        "paper_recovery_train_gate_satisfied": satisfied,
        "display": (
            f"paper recovery: {have}/{int(min_train_rows)} "
            f"{'PASS' if satisfied else 'PENDING'}"
        ),
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
