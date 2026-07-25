"""``PaperRecoveryCanaryArmV1`` — a single-use, ID-bound engineering-canary arm.

This is the ONLY authorization that lets exactly one paper engineering canary
bypass the three *certification/economic* controls (performance circuit breaker,
bucket quarantine, high-confidence loss-cluster) so the paper fill/close/accounting
plumbing can be exercised.  It authorizes nothing else: every hard control
(accounting, sizing, exposure, stop, liquidation, duplicate, mark-price, and the
blocked live gate) still fully applies, and the arm can never authorize live.

The arm is:
* created explicitly by the recovery driver, bound to the exact prediction /
  orchestrator-decision / risk-decision IDs and symbol/timeframe,
* auto-expiring (<= 900s TTL),
* single-use — consumed atomically on the first accepted fill via SET NX,
* fail-closed on reuse, wrong symbol, wrong IDs, expiry, or any live marker.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

ARM_KEY = "v2:paper:recovery:canary_arm:{prediction_id}"
ARM_CONSUMED_KEY = "v2:paper:recovery:canary_arm_consumed:{prediction_id}"
MAX_ARM_TTL_SECONDS = 900
MAX_SIMULATED_NOTIONAL_USD = 10.0
MAX_OPEN_POSITIONS = 1

# Economic/certification controls the armed canary may bypass — and ONLY these.
BYPASSABLE_ECONOMIC_BLOCK_REASONS = (
    "PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED",
    "PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCKED_AFTER_QUEUE_CONSUMPTION",
    "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY",
    "PAPER_HIGH_CONFIDENCE_LOSS_CLUSTER_BLOCKED_REENTRY",
)


@dataclass(frozen=True)
class PaperRecoveryCanaryArmV1:
    arm_id: str
    armed_at: str
    expires_at: str
    allowed_symbol: str
    allowed_timeframe: str
    allowed_prediction_id: str
    allowed_orchestrator_decision_id: str
    allowed_risk_decision_id: str
    maximum_simulated_notional_usd: float = MAX_SIMULATED_NOTIONAL_USD
    maximum_open_positions: int = MAX_OPEN_POSITIONS
    single_use: bool = True
    consumed: bool = False
    paper_only: bool = True
    engineering_canary: bool = True
    live_eligible: bool = False
    routes_to_live: bool = False
    places_real_order: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def create_canary_arm(
    redis_client: Any,
    *,
    arm_id: str,
    symbol: str,
    timeframe: str,
    prediction_id: str,
    orchestrator_decision_id: str,
    risk_decision_id: str,
    now: datetime,
    ttl_seconds: int = MAX_ARM_TTL_SECONDS,
) -> PaperRecoveryCanaryArmV1:
    """Write a fresh single-use arm bound to the exact IDs, with a bounded TTL."""

    ttl = max(1, min(int(ttl_seconds), MAX_ARM_TTL_SECONDS))
    arm = PaperRecoveryCanaryArmV1(
        arm_id=arm_id,
        armed_at=_iso(now),
        expires_at=_iso(now + timedelta(seconds=ttl)),
        allowed_symbol=symbol,
        allowed_timeframe=timeframe,
        allowed_prediction_id=prediction_id,
        allowed_orchestrator_decision_id=orchestrator_decision_id,
        allowed_risk_decision_id=risk_decision_id,
    )
    redis_client.set(ARM_KEY.format(prediction_id=prediction_id), arm.to_json(), ex=ttl)
    return arm


def validate_canary_arm(
    intent: Mapping[str, Any],
    *,
    redis_client: Any,
    now: datetime,
) -> tuple[PaperRecoveryCanaryArmV1 | None, str | None]:
    """Return (arm, None) when the exact armed engineering canary is authorized,
    else (None, reject_reason).  Fail-closed on every mismatch."""

    if intent.get("engineering_canary") is not True:
        return None, "CANARY_ARM_INTENT_NOT_ENGINEERING_CANARY"
    if intent.get("paper_recovery_only") is not True:
        return None, "CANARY_ARM_INTENT_NOT_PAPER_RECOVERY"
    # No artifact bound to real execution may ever be armed.
    if (
        intent.get("live_eligible") is True
        or intent.get("routes_to_live") is True
        or intent.get("places_real_order") is True
        or str(intent.get("live_gate") or "blocked_human_only") != "blocked_human_only"
    ):
        return None, "CANARY_ARM_LIVE_MARKER_PRESENT"

    prediction_id = str(intent.get("prediction_id") or "")
    if not prediction_id:
        return None, "CANARY_ARM_PREDICTION_ID_MISSING"
    raw = None
    try:
        raw = redis_client.get(ARM_KEY.format(prediction_id=prediction_id))
    except Exception:  # noqa: BLE001
        return None, "CANARY_ARM_LOOKUP_ERROR"
    if not raw:
        return None, "CANARY_ARM_ABSENT_OR_EXPIRED"
    try:
        data = json.loads(raw)
        fields = PaperRecoveryCanaryArmV1.__annotations__
        arm = PaperRecoveryCanaryArmV1(**{k: v for k, v in data.items() if k in fields})
    except (json.JSONDecodeError, TypeError, KeyError):
        return None, "CANARY_ARM_MALFORMED"

    expires = _parse(arm.expires_at)
    if expires is None or now >= expires:
        return None, "CANARY_ARM_EXPIRED"
    if arm.allowed_symbol != str(intent.get("symbol") or ""):
        return None, "CANARY_ARM_SYMBOL_MISMATCH"
    if arm.allowed_timeframe != str(intent.get("timeframe") or ""):
        return None, "CANARY_ARM_TIMEFRAME_MISMATCH"
    if arm.allowed_prediction_id != prediction_id:
        return None, "CANARY_ARM_PREDICTION_MISMATCH"
    if arm.allowed_orchestrator_decision_id != str(intent.get("orchestrator_decision_id") or ""):
        return None, "CANARY_ARM_ORCHESTRATOR_MISMATCH"
    if arm.allowed_risk_decision_id != str(intent.get("risk_decision_id") or ""):
        return None, "CANARY_ARM_RISK_MISMATCH"
    if arm.live_eligible or arm.routes_to_live or arm.places_real_order:
        return None, "CANARY_ARM_LIVE_MARKER_IN_ARM"
    # Already consumed?
    try:
        if redis_client.get(ARM_CONSUMED_KEY.format(prediction_id=prediction_id)):
            return None, "CANARY_ARM_ALREADY_CONSUMED"
    except Exception:  # noqa: BLE001
        return None, "CANARY_ARM_CONSUMED_LOOKUP_ERROR"
    return arm, None


def consume_canary_arm(redis_client: Any, *, prediction_id: str, arm_id: str) -> bool:
    """Atomically consume the arm on first fill.  Returns True iff we consumed it
    (SET NX); False if it was already consumed (reuse rejected)."""

    key = ARM_CONSUMED_KEY.format(prediction_id=prediction_id)
    ok = redis_client.set(key, arm_id, nx=True, ex=MAX_ARM_TTL_SECONDS)
    return bool(ok)


# Certification/liveness-only block reasons an armed engineering-replay canary may
# clear — NEVER a hard control (sizing/margin/stop/liquidation/exposure/duplicate/
# mark-price all stay enforced).
BYPASSABLE_CERTIFICATION_BLOCK_REASONS = (
    "STALE_FEATURE_STATE",
    "MARKET_STATE_INTEGRITY_SCORE_BELOW_PAPER_MIN",
    "VALID_FOR_PAPER_NOT_TRUE",
    "MISSING_ENTRY_FEATURE_AVAILABLE_AT",
    "MISSING_ENTRY_FEATURE_GENERATED_AT",
    "MISSING_ENTRY_FEATURE_CUTOFF",
    "ENTRY_FEATURE_CANDLE_NOT_CONFIRMED_CLOSED",
    "MISSING_EXPLICIT_FUNDING_BPS_AT_DECISION_TIME",
    "source_event_time_missing",
    "candle_open_or_close_time_missing",
    "CANONICAL_RISK_DECISION_UNRESOLVED",
    "RISK_GATEWAY_DECISION_PENDING",
)


def resolve_recovery_risk_allow(
    intent: Mapping[str, Any],
    *,
    redis_client: Any,
    now: datetime,
) -> tuple[bool, str | None]:
    """For an armed canary, resolve the EXACT persisted canonical risk record and
    confirm risk_action=allow with matching identities and no live marker.  The
    persisted ``v2:decision:risk:{risk_decision_id}`` record is the authority — the
    display value ``PASS`` is never trusted alone.  Returns (resolved, reason)."""

    risk_decision_id = str(intent.get("risk_decision_id") or "")
    if not risk_decision_id:
        return False, "RECOVERY_RISK_ID_MISSING"
    try:
        raw = redis_client.get(f"v2:decision:risk:{risk_decision_id}")
    except Exception:  # noqa: BLE001
        return False, "RECOVERY_RISK_RECORD_LOOKUP_ERROR"
    if not raw:
        return False, "RECOVERY_RISK_RECORD_MISSING"
    try:
        rec = json.loads(raw)
    except json.JSONDecodeError:
        return False, "RECOVERY_RISK_RECORD_MALFORMED"
    expires = _parse(rec.get("expires_at"))
    if expires is not None and now >= expires:
        return False, "RECOVERY_RISK_RECORD_EXPIRED"
    if str(rec.get("prediction_id") or "") != str(intent.get("prediction_id") or ""):
        return False, "RECOVERY_RISK_PREDICTION_ID_MISMATCH"
    rec_orch = str(rec.get("orchestrator_decision_id") or "")
    if rec_orch != str(intent.get("orchestrator_decision_id") or ""):
        return False, "RECOVERY_RISK_ORCHESTRATOR_ID_MISMATCH"
    if str(rec.get("symbol") or "") != str(intent.get("symbol") or ""):
        return False, "RECOVERY_RISK_SYMBOL_MISMATCH"
    if str(rec.get("timeframe") or "") != str(intent.get("timeframe") or ""):
        return False, "RECOVERY_RISK_TIMEFRAME_MISMATCH"
    action = str(rec.get("decision") or rec.get("risk_action") or "").lower()
    if action != "allow":
        return False, "RECOVERY_RISK_ACTION_NOT_ALLOW"
    if rec.get("places_real_order") is True or rec.get("routes_to_live") is True:
        return False, "RECOVERY_RISK_LIVE_MARKER_PRESENT"
    if str(rec.get("live_gate") or "blocked_human_only") != "blocked_human_only":
        return False, "RECOVERY_RISK_LIVE_MARKER_PRESENT"
    return True, None


def apply_certification_bypass(
    block_reasons: list[str],
    *,
    armed_engineering_replay: bool,
) -> tuple[list[str], list[str]]:
    """For a validated armed engineering-replay canary, remove ONLY certification/
    liveness block reasons; every hard control is preserved."""

    if not armed_engineering_replay:
        return list(block_reasons), []
    removed: list[str] = []
    remaining: list[str] = []
    for reason in block_reasons:
        if reason in BYPASSABLE_CERTIFICATION_BLOCK_REASONS:
            removed.append(reason)
        else:
            remaining.append(reason)
    return remaining, removed


def apply_economic_control_exception(
    block_reasons: list[str],
    *,
    armed: bool,
) -> tuple[list[str], list[str]]:
    """Given the fill-gate block reasons, when a valid arm exists remove ONLY the
    bypassable economic controls.  Returns (remaining_reasons, exception_reasons).
    Every other (hard) control is preserved untouched."""

    if not armed:
        return list(block_reasons), []
    removed: list[str] = []
    remaining: list[str] = []
    for reason in block_reasons:
        if reason in BYPASSABLE_ECONOMIC_BLOCK_REASONS:
            removed.append(reason)
        else:
            remaining.append(reason)
    return remaining, removed
