"""Non-authoritative diagnostics for the canonical adaptive gate policy."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import UTC, datetime
from typing import Any, Protocol

from v2.backend.app.cli.v2_adaptive_gate_tuner import (
    CANONICAL_PRODUCER,
    FAIL_CLOSED_CONFIDENCE_FLOOR,
    FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE,
    FAIL_CLOSED_LOSS_PROBABILITY_CEILING,
    MAX_A_PLUS_STRICTNESS,
    adaptive_gate_tuning_rejection_reasons,
    capture_canonical_gate_tuning_redis_bytes,
    decode_canonical_gate_tuning_redis_payload,
)
from v2.backend.app.cli.v2_adaptive_gate_tuner import (
    GATE_TUNING_KEY as _CANONICAL_GATE_TUNING_KEY,
)

logger = logging.getLogger(__name__)

CANONICAL_GATE_TUNING_KEY = _CANONICAL_GATE_TUNING_KEY
SHADOW_GATE_TUNING_KEY = "v2:diagnostic:adaptive_gate_tuning:runtime_tuner_shadow"
# Compatibility name for callers that imported the old writer constant.  It
# deliberately resolves to the noncanonical key so this dormant service can
# never collide with the canonical CLI publisher again.
GATE_TUNING_KEY = SHADOW_GATE_TUNING_KEY
SHADOW_PRODUCER = "v2.backend.app.services.adaptive_gate_tuning.runtime_tuner"
SHADOW_SCHEMA_VERSION = "v2_adaptive_gate_tuning_shadow_v1"
SHADOW_TTL_SECONDS = 60
FAIL_CLOSED_THRESHOLD_VALUES = {
    "adaptive_confidence_threshold": FAIL_CLOSED_CONFIDENCE_FLOOR,
    "adaptive_loss_probability_threshold": FAIL_CLOSED_LOSS_PROBABILITY_CEILING,
    "adaptive_long_confidence_floor": FAIL_CLOSED_CONFIDENCE_FLOOR,
    "adaptive_short_confidence_floor": FAIL_CLOSED_CONFIDENCE_FLOOR,
    "adaptive_expectancy_floor": math.inf,
    "adaptive_entry_freeze_allowance": FAIL_CLOSED_ENTRY_FREEZE_ALLOWANCE,
    "adaptive_a_plus_strictness": MAX_A_PLUS_STRICTNESS,
}


class RedisReader(Protocol):
    def get(self, key: str) -> Any: ...


class RedisStore(RedisReader, Protocol):
    def set(self, key: str, value: str, ex: int | None = None) -> Any: ...


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode_mapping(raw: Any) -> dict[str, Any] | None:
    decoded, _rejection_reasons = decode_canonical_gate_tuning_redis_payload(raw)
    return decoded


def compute_adaptive_gate_tuning(
    r: RedisReader,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Project validation metadata only; never derive a second gate policy."""

    read_error: str | None
    try:
        raw = r.get(CANONICAL_GATE_TUNING_KEY)
    except Exception as exc:
        raw = None
        read_error = f"CANONICAL_READ_FAILED_{type(exc).__name__.upper()}"
    else:
        read_error = None
    raw_bytes, capture_rejection_reasons = capture_canonical_gate_tuning_redis_bytes(raw)
    if capture_rejection_reasons:
        canonical = None
        decode_rejection_reasons = capture_rejection_reasons
    else:
        assert raw_bytes is not None
        canonical, decode_rejection_reasons = decode_canonical_gate_tuning_redis_payload(raw_bytes)
    rejection_reasons = list(decode_rejection_reasons)
    if canonical is not None:
        rejection_reasons.extend(
            adaptive_gate_tuning_rejection_reasons(
                canonical,
                observed_at=observed_at or datetime.now(UTC),
            )
        )
    if read_error is not None:
        rejection_reasons.append(read_error)
    canonical_valid = not rejection_reasons
    return {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "producer": SHADOW_PRODUCER,
        "authoritative": False,
        "authority_status": "NON_AUTHORITATIVE_SHADOW_DIAGNOSTIC",
        "intended_use": "DIAGNOSTIC_COMPARISON_ONLY",
        "may_control_admission": False,
        "canonical_authority_key": CANONICAL_GATE_TUNING_KEY,
        "shadow_key": SHADOW_GATE_TUNING_KEY,
        "canonical_payload_present": raw is not None,
        "canonical_payload_bytes_captured": raw_bytes is not None,
        "canonical_payload_valid": canonical_valid,
        "canonical_validation_scope": (
            "PUBLICATION_INTEGRITY_AND_FRESHNESS_ONLY_NO_SESSION_ADMISSION"
        ),
        "canonical_rejection_reasons": sorted(set(rejection_reasons)),
        "canonical_payload_sha256": (
            hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None
        ),
        "canonical_policy_id": (
            canonical.get("policy_id") if canonical_valid and canonical is not None else None
        ),
        "canonical_policy_status": (
            canonical.get("policy_status") if canonical_valid and canonical is not None else None
        ),
        "emits_admission_thresholds": False,
        "static_market_or_performance_thresholds": False,
        "derivation_owner": CANONICAL_PRODUCER,
        "generated_utc": _utc_iso(),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def publish_adaptive_gate_tuning(r: RedisStore) -> None:
    """Publish one bounded non-authoritative canonical-validation shadow."""
    try:
        tuning_state = compute_adaptive_gate_tuning(r)
        r.set(
            SHADOW_GATE_TUNING_KEY,
            json.dumps(tuning_state, sort_keys=True, default=str),
            ex=SHADOW_TTL_SECONDS,
        )
        logger.info(
            "Published adaptive tuning validation shadow: canonical_valid=%s",
            tuning_state.get("canonical_payload_valid"),
        )
    except Exception as exc:
        logger.error("Failed to publish adaptive gate tuning: %s", exc)


def get_adaptive_threshold(
    r: RedisReader,
    threshold_name: str,
    default: float | None = None,
    *,
    current_paper_session_id: str | None = None,
    observed_at: datetime | None = None,
) -> float:
    """Read one fully validated canonical threshold or its fail-closed extremum.

    ``default`` remains only for source compatibility with the retired reader;
    it is deliberately ignored because a caller-provided market threshold is
    not a safe substitute for missing, expired, or cross-session authority.
    """

    del default
    if threshold_name not in FAIL_CLOSED_THRESHOLD_VALUES:
        raise ValueError(f"UNSUPPORTED_ADAPTIVE_THRESHOLD:{threshold_name}")
    fail_closed = FAIL_CLOSED_THRESHOLD_VALUES[threshold_name]
    try:
        tuning, decode_rejection_reasons = decode_canonical_gate_tuning_redis_payload(
            r.get(CANONICAL_GATE_TUNING_KEY)
        )
        if decode_rejection_reasons:
            logger.debug(
                "Rejected canonical adaptive threshold %s during decode: %s",
                threshold_name,
                ",".join(decode_rejection_reasons),
            )
            return fail_closed
        reasons = adaptive_gate_tuning_rejection_reasons(
            tuning,
            observed_at=observed_at or datetime.now(UTC),
            current_paper_session_id=current_paper_session_id,
            require_current_session=True,
        )
        if reasons:
            logger.debug(
                "Rejected canonical adaptive threshold %s: %s",
                threshold_name,
                ",".join(reasons),
            )
            return fail_closed
        assert tuning is not None
        parsed = float(tuning[threshold_name])
        return parsed if math.isfinite(parsed) else fail_closed
    except Exception as exc:
        # Redis/network/decoder failures at this external boundary must never
        # revive the retired caller-supplied fallback threshold.
        logger.debug("Failed to read %s: %s", threshold_name, exc)
        return fail_closed
