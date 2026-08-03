"""Strategy ↔ regime permission matrix (Phase 3 hard rules).

Hard rules from the goal:
    * No trend strategy in RANGING regime.
    * No mean-reversion strategy in strong TRENDING regime unless reversal
      evidence exists.
    * No trade in VOLATILE_EXPANSION unless trade tape + microstructure
      confirm.
    * LIQUIDITY_SWEEP / FAKEOUT_RISK / NO_TRADE never allow new entries.

The matrix is deny-by-default: unknown strategies or unknown regimes resolve
to blocked.
"""
from __future__ import annotations

from typing import Any, Mapping

from .classifier import REGIMES

SCHEMA_VERSION = "v2_strategy_regime_permission_matrix_v1"

TREND_STRATEGIES = frozenset({"trend_mode", "trend", "breakout", "squeeze", "momentum"})
MEAN_REVERSION_STRATEGIES = frozenset(
    {"mean_reversion", "mean_reversion_mode", "range_mode", "range", "reversion"}
)

# regime -> strategy family -> permission
# "allow" | "block" | "conditional" (conditions carried in strategy_allowed_in_regime)
STRATEGY_REGIME_PERMISSION_MATRIX: dict[str, dict[str, str]] = {
    "TRENDING_UP": {
        "trend_long": "allow",
        "trend_short": "block",
        "mean_reversion": "conditional",  # only with reversal evidence
    },
    "TRENDING_DOWN": {
        "trend_long": "block",
        "trend_short": "allow",
        "mean_reversion": "conditional",
    },
    "RANGING": {
        "trend_long": "block",
        "trend_short": "block",
        "mean_reversion": "allow",
    },
    "VOLATILE_EXPANSION": {
        "trend_long": "conditional",  # tape + microstructure confirmation required
        "trend_short": "conditional",
        "mean_reversion": "block",
    },
    "LIQUIDITY_SWEEP": {"trend_long": "block", "trend_short": "block", "mean_reversion": "block"},
    "FAKEOUT_RISK": {"trend_long": "block", "trend_short": "block", "mean_reversion": "block"},
    "NO_TRADE": {"trend_long": "block", "trend_short": "block", "mean_reversion": "block"},
}


def _strategy_family(strategy_id: str, side: str) -> str:
    normalized = (strategy_id or "").strip().lower()
    normalized_side = (side or "").strip().lower()
    if normalized in MEAN_REVERSION_STRATEGIES or "reversion" in normalized:
        return "mean_reversion"
    if normalized in TREND_STRATEGIES or "trend" in normalized or "breakout" in normalized:
        return f"trend_{normalized_side}" if normalized_side in {"long", "short"} else "trend_unknown"
    return "unknown"


def _finite(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def strategy_allowed_in_regime(
    *,
    strategy_id: str,
    side: str,
    regime_decision: Mapping[str, Any],
    trade_tape: Mapping[str, Any] | None = None,
    microstructure_trust: Mapping[str, Any] | None = None,
    reversal_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Deny-by-default permission check for one candidate trade."""
    regime = str(regime_decision.get("regime") or "NO_TRADE")
    family = _strategy_family(strategy_id, side)
    reasons: list[str] = []
    allowed = False

    if regime not in REGIMES:
        reasons.append(f"UNKNOWN_REGIME:{regime}")
        regime = "NO_TRADE"

    permissions = STRATEGY_REGIME_PERMISSION_MATRIX.get(regime, {})
    permission = permissions.get(family, "block")

    if family == "unknown":
        reasons.append(f"UNKNOWN_STRATEGY_FAMILY:{strategy_id}")
        permission = "block"
    if family == "trend_unknown":
        reasons.append(f"TREND_STRATEGY_WITHOUT_SIDE:{strategy_id}:{side}")
        permission = "block"

    if permission == "allow":
        allowed = True
        reasons.append(f"MATRIX_ALLOW:{regime}:{family}")
    elif permission == "block":
        reasons.append(f"MATRIX_BLOCK:{regime}:{family}")
    elif permission == "conditional":
        if regime in {"TRENDING_UP", "TRENDING_DOWN"} and family == "mean_reversion":
            evidence = reversal_evidence or {}
            has_reversal = bool(evidence.get("reversal_confirmed"))
            if has_reversal:
                allowed = True
                reasons.append(f"MEAN_REVERSION_IN_TREND_WITH_REVERSAL_EVIDENCE:{evidence.get('reason')}")
            else:
                reasons.append("MEAN_REVERSION_IN_STRONG_TREND_WITHOUT_REVERSAL_EVIDENCE")
        elif regime == "VOLATILE_EXPANSION":
            tape = trade_tape or {}
            micro = microstructure_trust or {}
            tape_score = _finite(tape.get("trade_tape_confirmation_score"))
            tape_ok = (
                str(tape.get("trade_tape_confirmation_state") or "") == "TAPE_DATA_OK"
                and tape_score is not None
                and (
                    (side.strip().lower() == "long" and tape_score >= 0.6)
                    or (side.strip().lower() == "short" and tape_score <= 0.4)
                )
            )
            trust_score = _finite(
                micro.get("microstructure_trust_score") or micro.get("trust_score") or micro.get("score")
            )
            micro_ok = trust_score is not None and trust_score >= 0.6
            if tape_ok and micro_ok:
                allowed = True
                reasons.append(
                    f"VOLATILE_EXPANSION_CONFIRMED:tape={tape_score:.2f}:micro_trust={trust_score:.2f}"
                )
            else:
                if not tape_ok:
                    reasons.append("VOLATILE_EXPANSION_TAPE_CONFIRMATION_MISSING")
                if not micro_ok:
                    reasons.append("VOLATILE_EXPANSION_MICROSTRUCTURE_TRUST_MISSING")
        else:
            reasons.append(f"CONDITIONAL_PATH_UNDEFINED:{regime}:{family}")

    return {
        "schema_version": SCHEMA_VERSION,
        "allowed": allowed,
        "regime": regime,
        "strategy_id": strategy_id,
        "strategy_family": family,
        "side": (side or "").strip().lower(),
        "permission": permission,
        "reasons": reasons,
        "regime_confidence": regime_decision.get("confidence"),
        "places_real_order": False,
    }


def permission_matrix_status() -> dict[str, Any]:
    """Serializable matrix snapshot for artifacts and GUI."""
    behavioral_proofs = permission_matrix_behavioral_proofs()
    return {
        "schema_version": SCHEMA_VERSION,
        "regimes": list(REGIMES),
        "matrix": {regime: dict(families) for regime, families in STRATEGY_REGIME_PERMISSION_MATRIX.items()},
        "hard_rules": [
            "NO_TREND_STRATEGY_IN_RANGING_REGIME",
            "NO_MEAN_REVERSION_IN_STRONG_TREND_WITHOUT_REVERSAL_EVIDENCE",
            "NO_TRADE_IN_VOLATILE_EXPANSION_WITHOUT_TAPE_AND_MICROSTRUCTURE_CONFIRMATION",
            "NO_ENTRIES_IN_LIQUIDITY_SWEEP_FAKEOUT_RISK_OR_NO_TRADE",
            "DENY_BY_DEFAULT_FOR_UNKNOWN_STRATEGY_OR_REGIME",
        ],
        "deny_by_default": True,
        "behavioral_proofs": behavioral_proofs["proofs"],
        "hard_rules_proven": behavioral_proofs["all_proofs_passed"],
    }


def permission_matrix_behavioral_proofs() -> dict[str, Any]:
    """Static behavioral cases proving the Phase 3 hard rules."""
    cases = [
        {
            "name": "no_trend_strategy_in_ranging_regime",
            "expected_allowed": False,
            "strategy_id": "trend_mode",
            "side": "long",
            "regime_decision": {"regime": "RANGING", "confidence": 0.8},
            "expected_reason_token": "MATRIX_BLOCK:RANGING:trend_long",
        },
        {
            "name": "mean_reversion_blocked_in_trend_without_reversal",
            "expected_allowed": False,
            "strategy_id": "mean_reversion_mode",
            "side": "short",
            "regime_decision": {"regime": "TRENDING_UP", "confidence": 0.8},
            "expected_reason_token": "MEAN_REVERSION_IN_STRONG_TREND_WITHOUT_REVERSAL_EVIDENCE",
        },
        {
            "name": "mean_reversion_allowed_in_trend_with_reversal",
            "expected_allowed": True,
            "strategy_id": "mean_reversion_mode",
            "side": "short",
            "regime_decision": {"regime": "TRENDING_UP", "confidence": 0.8},
            "reversal_evidence": {"reversal_confirmed": True, "reason": "unit_reversal"},
            "expected_reason_token": "MEAN_REVERSION_IN_TREND_WITH_REVERSAL_EVIDENCE",
        },
        {
            "name": "volatile_expansion_blocks_without_tape_and_microstructure",
            "expected_allowed": False,
            "strategy_id": "trend_mode",
            "side": "long",
            "regime_decision": {"regime": "VOLATILE_EXPANSION", "confidence": 0.8},
            "expected_reason_token": "VOLATILE_EXPANSION_TAPE_CONFIRMATION_MISSING",
        },
        {
            "name": "volatile_expansion_allows_with_tape_and_microstructure",
            "expected_allowed": True,
            "strategy_id": "trend_mode",
            "side": "long",
            "regime_decision": {"regime": "VOLATILE_EXPANSION", "confidence": 0.8},
            "trade_tape": {
                "trade_tape_confirmation_state": "TAPE_DATA_OK",
                "trade_tape_confirmation_score": 0.75,
            },
            "microstructure_trust": {"microstructure_trust_score": 0.75},
            "expected_reason_token": "VOLATILE_EXPANSION_CONFIRMED",
        },
        {
            "name": "liquidity_sweep_blocks_entries",
            "expected_allowed": False,
            "strategy_id": "trend_mode",
            "side": "short",
            "regime_decision": {"regime": "LIQUIDITY_SWEEP", "confidence": 0.9},
            "expected_reason_token": "MATRIX_BLOCK:LIQUIDITY_SWEEP:trend_short",
        },
        {
            "name": "fakeout_risk_blocks_entries",
            "expected_allowed": False,
            "strategy_id": "trend_mode",
            "side": "long",
            "regime_decision": {"regime": "FAKEOUT_RISK", "confidence": 0.9},
            "expected_reason_token": "MATRIX_BLOCK:FAKEOUT_RISK:trend_long",
        },
        {
            "name": "no_trade_blocks_entries",
            "expected_allowed": False,
            "strategy_id": "mean_reversion_mode",
            "side": "long",
            "regime_decision": {"regime": "NO_TRADE", "confidence": 1.0},
            "expected_reason_token": "MATRIX_BLOCK:NO_TRADE:mean_reversion",
        },
        {
            "name": "unknown_strategy_deny_by_default",
            "expected_allowed": False,
            "strategy_id": "unknown_alpha",
            "side": "long",
            "regime_decision": {"regime": "TRENDING_UP", "confidence": 0.8},
            "expected_reason_token": "UNKNOWN_STRATEGY_FAMILY",
        },
    ]
    proofs: list[dict[str, Any]] = []
    for case in cases:
        verdict = strategy_allowed_in_regime(
            strategy_id=str(case["strategy_id"]),
            side=str(case["side"]),
            regime_decision=case["regime_decision"],
            trade_tape=case.get("trade_tape"),
            microstructure_trust=case.get("microstructure_trust"),
            reversal_evidence=case.get("reversal_evidence"),
        )
        reasons = [str(reason) for reason in verdict.get("reasons") or []]
        token = str(case["expected_reason_token"])
        passed = verdict.get("allowed") is case["expected_allowed"] and any(
            token in reason for reason in reasons
        )
        proofs.append(
            {
                "name": case["name"],
                "expected_allowed": case["expected_allowed"],
                "actual_allowed": verdict.get("allowed"),
                "passed": passed,
                "regime": verdict.get("regime"),
                "strategy_family": verdict.get("strategy_family"),
                "permission": verdict.get("permission"),
                "reasons": reasons,
            }
        )
    return {
        "proofs": proofs,
        "all_proofs_passed": all(proof["passed"] for proof in proofs),
    }
