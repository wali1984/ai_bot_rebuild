"""``PaperRecoveryPolicyV1`` — the single isolated paper-recovery gate.

This object is the ONLY place recovery relaxations live.  It permits a bounded,
paper-only, explicitly-tagged inference/execution lane so the full chain

    features -> prediction -> orchestrator -> canonical risk -> paper signal
    -> paper intent -> paper fill -> lifecycle -> close -> reconciliation

can be exercised on current/bounded-recovery evidence *without* touching any
strict validator.  Every strict promotion / PIT / live gate stays unchanged and
continues to reject the same artifacts.

Hard invariants (never relaxed here):
* disabled by default (must be explicitly enabled by env),
* can never authorise a live route or an exchange action,
* every artifact it blesses is tagged non-promotable / non-trainer-eligible /
  non-live-eligible,
* any recovery-tagged artifact presented to a live path is denied with
  ``DENY_RECOVERY_ARTIFACT_NOT_LIVE_ELIGIBLE``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

RECOVERY_LIVE_DENY_REASON = "DENY_RECOVERY_ARTIFACT_NOT_LIVE_ELIGIBLE"

REQUIRED_LIVE_GATE = "blocked_human_only"

# Exact fields every recovery-waived artifact must carry (spec section 1).
SNAPSHOT_PIT_WAIVER_FIELDS: dict[str, Any] = {
    "paper_recovery_only": True,
    "pit_evidence_mode": "SNAPSHOT_LEVEL_RECOVERY_WAIVER",
    "pit_strict_complete": False,
    "pit_waiver": True,
    "pit_waiver_reason": "PER_SLOT_IMMUTABLE_LEDGER_NOT_YET_AVAILABLE",
    "trainer_eligible": False,
    "checkpoint_promotable": False,
    "live_eligible": False,
    "routes_to_live": False,
}

# Non-promotable recovery checkpoint tags (spec section 2).
RECOVERY_CHECKPOINT_TAGS: dict[str, Any] = {
    "paper_only": True,
    "recovery_checkpoint": True,
    "non_promotable": True,
    "checkpoint_promotion_authorized": False,
    "live_eligible": False,
    "routes_to_live": False,
}

# Engineering canary / replay tags (spec sections Phase 1 & Phase 4).
ENGINEERING_CANARY_TAGS: dict[str, Any] = {
    "engineering_canary": True,
    "synthetic_candidate": True,
    "paper_only": True,
    "excluded_from_economic_metrics": True,
    "excluded_from_training": True,
    "excluded_from_checkpoint_promotion": True,
    "live_eligible": False,
    "routes_to_live": False,
}


class PaperRecoveryWaiverError(ValueError):
    """Raised when a snapshot cannot be granted the bounded recovery waiver."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(raw: str | None, default: int, *, minimum: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(float(raw)))
    except (TypeError, ValueError):
        return default


def _parse_clock(value: Any) -> datetime | None:
    """Parse an ISO-8601 (or epoch-us/ms/s) timestamp into aware UTC, else None."""

    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        v = float(value)
        # us -> s heuristics matching the ledger (feature_cutoff_us etc.)
        if v > 1e17:
            v = v / 1e9
        elif v > 1e14:
            v = v / 1e6
        elif v > 1e11:
            v = v / 1e3
        try:
            return datetime.fromtimestamp(v, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PaperRecoveryPolicyV1:
    """Immutable recovery-lane policy.  Disabled unless explicitly enabled."""

    enabled: bool = False
    allowed_symbols: tuple[str, ...] = ("BTCUSDT",)
    max_snapshot_age_seconds: int = 1800
    allow_snapshot_pit_waiver: bool = True
    allow_single_interval_gap: bool = True
    allow_reduced_feature_abi: bool = True
    # Paper-recovery train-row floor. Deliberately far below the strict champion
    # gate (1000): the recovery checkpoint is paper-only + non-promotable +
    # never live-eligible, so it must NOT wait on the strict 1000-row corpus.
    # 272 (current recovery checkpoint) >= 256 => PAPER_RECOVERY_TRAIN_GATE_SATISFIED.
    minimum_recovery_train_rows: int = 256
    allow_non_promotable_checkpoint: bool = True
    allow_engineering_canary: bool = True
    # Non-bypassable safety anchors — fixed, never configurable to a live value.
    live_gate_required: str = REQUIRED_LIVE_GATE
    exchange_action_required_false: bool = True
    # Every recovery run is bound to the deployment time so waived snapshots must
    # be generated *after* recovery went live (spec section 1).
    recovery_deployment_at: datetime | None = field(default=None)

    def is_symbol_allowed(self, symbol: str) -> bool:
        return bool(symbol) and symbol in self.allowed_symbols

    # ---- the immovable safety guard ------------------------------------
    def deny_live_route(self, artifact: Mapping[str, Any]) -> str | None:
        """Return the deny reason if a recovery artifact is offered to a live path.

        Any artifact carrying a recovery/paper-recovery/engineering tag can never
        be live-eligible.  Returns ``DENY_RECOVERY_ARTIFACT_NOT_LIVE_ELIGIBLE``
        when it must be refused, else ``None``.
        """

        recovery_tagged = any(
            bool(artifact.get(flag))
            for flag in (
                "paper_recovery_only",
                "recovery_checkpoint",
                "engineering_canary",
                "synthetic_candidate",
                "pit_waiver",
            )
        )
        if recovery_tagged:
            return RECOVERY_LIVE_DENY_REASON
        if artifact.get("live_eligible") is True or artifact.get("routes_to_live") is True:
            # A recovery-lane object must never assert live eligibility.
            if artifact.get("paper_recovery_only") is not None:
                return RECOVERY_LIVE_DENY_REASON
        return None

    # ---- bounded snapshot-level PIT waiver -----------------------------
    def evaluate_snapshot_pit_waiver(
        self,
        snapshot: Mapping[str, Any],
        *,
        now: datetime,
        expected_symbol: str,
        expected_timeframe: str,
    ) -> dict[str, Any]:
        """Validate a snapshot for the bounded recovery waiver (spec section 1).

        Returns the waiver receipt on success; raises ``PaperRecoveryWaiverError``
        with an exact reason on any failed condition.  Never fabricates per-slot
        receipts and never marks the evidence strict-PIT-complete.
        """

        if not self.enabled:
            raise PaperRecoveryWaiverError("PAPER_RECOVERY_MODE_DISABLED")
        if not self.allow_snapshot_pit_waiver:
            raise PaperRecoveryWaiverError("SNAPSHOT_PIT_WAIVER_NOT_PERMITTED")
        if not self.is_symbol_allowed(expected_symbol):
            raise PaperRecoveryWaiverError("RECOVERY_SYMBOL_NOT_ALLOWED")

        snapshot_id = snapshot.get("feature_snapshot_id") or snapshot.get("durable_snapshot_id")
        if not snapshot_id:
            raise PaperRecoveryWaiverError("RECOVERY_SNAPSHOT_ID_MISSING")

        vector = snapshot.get("feature_values")
        if not isinstance(vector, Sequence) or isinstance(vector, str | bytes) or len(vector) == 0:
            raise PaperRecoveryWaiverError("RECOVERY_ORDERED_VECTOR_MISSING")

        for name in (
            "model_vector_sha256",
            "feature_abi_sha256",
            "source_lineage_sha256",
        ):
            digest = snapshot.get(name)
            if not (isinstance(digest, str) and len(digest) == 64 and _is_hex(digest)):
                raise PaperRecoveryWaiverError(f"RECOVERY_{name.upper()}_INVALID")

        if str(snapshot.get("symbol")) != str(expected_symbol):
            raise PaperRecoveryWaiverError("RECOVERY_SYMBOL_MISMATCH")
        if str(snapshot.get("timeframe")) != str(expected_timeframe):
            raise PaperRecoveryWaiverError("RECOVERY_TIMEFRAME_MISMATCH")

        # No NaN / inf feature values.
        for element in vector:
            try:
                val = float(element)
            except (TypeError, ValueError) as exc:
                raise PaperRecoveryWaiverError("RECOVERY_FEATURE_VALUE_NON_NUMERIC") from exc
            if not math.isfinite(val):
                raise PaperRecoveryWaiverError("RECOVERY_FEATURE_VALUE_NOT_FINITE")

        decision_time = _parse_clock(
            snapshot.get("ppo_decision_time")
            or snapshot.get("decision_time")
            or snapshot.get("feature_decision_time")
        )
        feature_cutoff = _parse_clock(
            snapshot.get("feature_cutoff") or snapshot.get("ppo_feature_cutoff")
        )
        generated_at = _parse_clock(snapshot.get("generated_at"))
        available_at = _parse_clock(snapshot.get("available_at")) or generated_at
        if decision_time is None or feature_cutoff is None or generated_at is None:
            raise PaperRecoveryWaiverError("RECOVERY_REQUIRED_TIMESTAMP_MISSING")

        # No timestamp in the future.
        for label, ts in (
            ("decision_time", decision_time),
            ("feature_cutoff", feature_cutoff),
            ("generated_at", generated_at),
            ("available_at", available_at),
        ):
            if ts > now:
                raise PaperRecoveryWaiverError(f"RECOVERY_{label.upper()}_IN_FUTURE")

        if feature_cutoff > decision_time:
            raise PaperRecoveryWaiverError("RECOVERY_FEATURE_CUTOFF_AFTER_DECISION")
        if available_at is not None and available_at > decision_time:
            raise PaperRecoveryWaiverError("RECOVERY_AVAILABLE_AFTER_DECISION")

        # Snapshot generated after the recovery deployment.
        if self.recovery_deployment_at is not None and generated_at < self.recovery_deployment_at:
            raise PaperRecoveryWaiverError("RECOVERY_SNAPSHOT_PREDATES_DEPLOYMENT")

        # Freshness limit.
        age_seconds = (now - generated_at).total_seconds()
        if age_seconds < 0 or age_seconds > self.max_snapshot_age_seconds:
            raise PaperRecoveryWaiverError("RECOVERY_SNAPSHOT_STALE")

        receipt = dict(SNAPSHOT_PIT_WAIVER_FIELDS)
        receipt.update(
            {
                "feature_snapshot_id": str(snapshot_id),
                "symbol": str(expected_symbol),
                "timeframe": str(expected_timeframe),
                "feature_abi_sha256": str(snapshot.get("feature_abi_sha256")),
                "model_vector_sha256": str(snapshot.get("model_vector_sha256")),
                "source_lineage_sha256": str(snapshot.get("source_lineage_sha256")),
                "snapshot_age_seconds": round(age_seconds, 3),
                "decision_time": decision_time.isoformat(),
                "feature_cutoff": feature_cutoff.isoformat(),
                "generated_at": generated_at.isoformat(),
                "recovery_freshness_limit_seconds": self.max_snapshot_age_seconds,
                "live_gate": self.live_gate_required,
                "exchange_action_taken": False,
            }
        )
        return receipt


def _is_hex(text: str) -> bool:
    try:
        int(text, 16)
        return True
    except ValueError:
        return False


def load_paper_recovery_policy_v1(
    environ: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> PaperRecoveryPolicyV1:
    """Build the policy from env — DISABLED unless ``PAPER_RECOVERY_MODE_ENABLED``.

    The live-gate anchor and the exchange-action-false anchor are fixed and can
    never be overridden to a live-capable value.
    """

    enabled = _as_bool(environ.get("PAPER_RECOVERY_MODE_ENABLED"), False)
    symbols_raw = environ.get("PAPER_RECOVERY_ALLOWED_SYMBOLS", "BTCUSDT")
    allowed = tuple(s.strip().upper() for s in symbols_raw.split(",") if s.strip())
    # Fixed anchors — read but hard-clamped so they can never authorise live.
    live_gate = environ.get("PAPER_RECOVERY_LIVE_GATE", REQUIRED_LIVE_GATE)
    if live_gate != REQUIRED_LIVE_GATE:
        live_gate = REQUIRED_LIVE_GATE
    return PaperRecoveryPolicyV1(
        enabled=enabled,
        allowed_symbols=allowed or ("BTCUSDT",),
        max_snapshot_age_seconds=_as_int(
            environ.get("PAPER_RECOVERY_MAX_SNAPSHOT_AGE_SECONDS"), 1800, minimum=1
        ),
        allow_snapshot_pit_waiver=_as_bool(
            environ.get("PAPER_RECOVERY_ALLOW_SNAPSHOT_PIT_WAIVER"), True
        ),
        allow_single_interval_gap=_as_bool(
            environ.get("PAPER_RECOVERY_ALLOW_SINGLE_INTERVAL_GAP"), True
        ),
        allow_reduced_feature_abi=_as_bool(
            environ.get("PAPER_RECOVERY_ALLOW_REDUCED_FEATURE_ABI"), True
        ),
        minimum_recovery_train_rows=_as_int(
            environ.get("PAPER_RECOVERY_MIN_TRAIN_ROWS"), 256, minimum=1
        ),
        allow_non_promotable_checkpoint=_as_bool(
            environ.get("PAPER_RECOVERY_ALLOW_NON_PROMOTABLE_CHECKPOINT"), True
        ),
        allow_engineering_canary=_as_bool(
            environ.get("PAPER_RECOVERY_ALLOW_ENGINEERING_CANARY"), True
        ),
        live_gate_required=live_gate,
        exchange_action_required_false=True,
        recovery_deployment_at=now,
    )


def snapshot_recovery_waiver_receipt(
    snapshot: Mapping[str, Any],
    *,
    policy: PaperRecoveryPolicyV1,
    now: datetime,
    expected_symbol: str,
    expected_timeframe: str,
) -> dict[str, Any]:
    """Convenience wrapper returning the waiver receipt (raises on rejection)."""

    return policy.evaluate_snapshot_pit_waiver(
        snapshot,
        now=now,
        expected_symbol=expected_symbol,
        expected_timeframe=expected_timeframe,
    )
