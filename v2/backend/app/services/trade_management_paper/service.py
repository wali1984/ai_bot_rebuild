"""Trade Management Paper Engine.

Native V2 paper/shadow only. Implements the small but load-bearing subset
of the legacy trading exit machinery that a paper-shadow soak needs to be
realistic:

- Stealth stop schedule (no orderbook leakage; computes a hidden stop level
  and a trigger condition based on price + a buffer + time-decay).
- Dynamic ATR-based stop plan.
- Dynamic take-profit ladder (laddered partial exits).
- Churn veto (block reopening too soon after a same-side close).
- Fee-ratio gate (block when fee_bps / abs(expected_move_after_cost_bps)
  exceeds a configured ratio).
- Hedge / DCA evaluator (fail-closed by default; returns deny + reason).

Legacy behavior sources (read-only, in v2/legacy_preserved/full_runtime_closure/):

- trading/stealth_stops.py
    sha256=a76de1902e7c2a754f2e90a39fa9aac23d991ec059d5c54d6e0772b79b8a47cf
    size=389228
- trading/dynamic_tp_engine.py
    sha256=54bf102e9d5cfedb00f22f953c4894c4592a1b627a16bad51c034a7069c1e908
    size=72213
- trading/dynamic_adaptive_stops.py
    sha256=523ef574f6f6729c831047e73ce53bfad3d980cb562a386bf8b648b22d9d061f
    size=47578
- trading/churn_prevention.py
    sha256=f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f
    size=22085
- trading/fee_ratio_gate.py
    sha256=c1829afcbdb6848fb8dffd76e14b78a140832c663bb9c2f16e75029b0e7f8e7f
    size=14577

This service is NOT a full port. It implements V2-native paper-acceptable
behavior for each gate. Hedge / DCA are intentionally FAIL_CLOSED_STUB.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any

TRADE_MANAGEMENT_PAPER_SCHEMA_VERSION = "1.0.0"

LIVE_GATE_STATUS = "blocked_human_only"

LEGACY_SOURCES = {
    "trading/stealth_stops.py": {
        "sha256": "a76de1902e7c2a754f2e90a39fa9aac23d991ec059d5c54d6e0772b79b8a47cf",
        "size_bytes": 389228,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/trading/stealth_stops.py",
    },
    "trading/dynamic_tp_engine.py": {
        "sha256": "54bf102e9d5cfedb00f22f953c4894c4592a1b627a16bad51c034a7069c1e908",
        "size_bytes": 72213,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/trading/dynamic_tp_engine.py",
    },
    "trading/dynamic_adaptive_stops.py": {
        "sha256": "523ef574f6f6729c831047e73ce53bfad3d980cb562a386bf8b648b22d9d061f",
        "size_bytes": 47578,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/trading/dynamic_adaptive_stops.py",
    },
    "trading/churn_prevention.py": {
        "sha256": "f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f",
        "size_bytes": 22085,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/trading/churn_prevention.py",
    },
    "trading/fee_ratio_gate.py": {
        "sha256": "c1829afcbdb6848fb8dffd76e14b78a140832c663bb9c2f16e75029b0e7f8e7f",
        "size_bytes": 14577,
        "v2_preserved_path": "v2/legacy_preserved/full_runtime_closure/trading/fee_ratio_gate.py",
    },
}


# ----------------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class PaperPositionSnapshot:
    symbol: str
    side: str  # "long" | "short"
    entry_price: float
    current_price: float
    atr_pct: float | None
    age_seconds: int
    realized_pnl_bps: float | None = None
    unrealized_pnl_bps: float | None = None


@dataclass(frozen=True)
class StealthStopSchedule:
    symbol: str
    side: str
    initial_stop_price: float
    trailing_buffer_bps: float
    time_decay_seconds: int
    notes: str


@dataclass(frozen=True)
class DynamicStopPlan:
    symbol: str
    side: str
    stop_price: float
    atr_multiplier: float
    rationale: str


@dataclass(frozen=True)
class DynamicTakeProfitLadder:
    symbol: str
    side: str
    rungs: tuple[tuple[float, float], ...]  # (price, partial_fraction)
    rationale: str


@dataclass(frozen=True)
class ChurnVetoResult:
    blocked: bool
    reason: str
    seconds_since_last_close: int


@dataclass(frozen=True)
class FeeRatioGateResult:
    blocked: bool
    fee_bps: float
    expected_move_after_cost_bps: float | None
    ratio: float | None
    reason: str


@dataclass(frozen=True)
class HedgeDcaEvaluation:
    allowed: bool
    reason: str
    classification: str  # "FAIL_CLOSED_STUB" by default


# ----------------------------------------------------------------------- helpers


def _sign_for_side(side: str) -> int:
    s = (side or "").lower()
    if s == "long":
        return 1
    if s == "short":
        return -1
    raise ValueError(f"unknown side: {side!r}")


# ----------------------------------------------------------------------- stealth stops


def compute_stealth_stop_schedule(
    snap: PaperPositionSnapshot,
    *,
    base_buffer_bps: float = 25.0,
    min_buffer_bps: float = 8.0,
    max_buffer_bps: float = 80.0,
    time_decay_seconds: int = 1800,
) -> StealthStopSchedule:
    """Compute a stealth stop schedule.

    The buffer (in bps) decays over time from base toward min, controlled
    by `time_decay_seconds`. The stop price is placed on the opposite side
    of the entry, never broadcast to any exchange (paper only).
    """
    sign = _sign_for_side(snap.side)
    age = max(0, int(snap.age_seconds))
    decay_factor = max(0.0, 1.0 - (age / max(1, time_decay_seconds)))
    buffer_bps = max(min_buffer_bps, min(max_buffer_bps, base_buffer_bps * decay_factor))
    buffer_pct = buffer_bps / 10000.0
    # Stop is below entry for long; above entry for short.
    initial_stop_price = snap.entry_price * (1.0 - sign * buffer_pct)
    return StealthStopSchedule(
        symbol=snap.symbol,
        side=snap.side,
        initial_stop_price=initial_stop_price,
        trailing_buffer_bps=buffer_bps,
        time_decay_seconds=time_decay_seconds,
        notes="paper_only_no_exchange_broadcast",
    )


# ----------------------------------------------------------------------- dynamic stops


def compute_dynamic_stop_plan(
    snap: PaperPositionSnapshot,
    *,
    atr_multiplier: float = 2.0,
    default_atr_pct_when_missing: float = 0.01,
) -> DynamicStopPlan:
    """Dynamic ATR-based stop. Falls back to a conservative default if atr_pct
    is missing — never emits a None price (the paper engine must always have
    a stop).
    """
    sign = _sign_for_side(snap.side)
    atr_pct = snap.atr_pct if snap.atr_pct and snap.atr_pct > 0 else default_atr_pct_when_missing
    stop_distance = max(0.0001, atr_pct * atr_multiplier)
    stop_price = snap.current_price * (1.0 - sign * stop_distance)
    rationale = (
        f"atr_multiplier={atr_multiplier} atr_pct={atr_pct:.6f} "
        f"stop_distance={stop_distance:.6f}"
    )
    return DynamicStopPlan(
        symbol=snap.symbol,
        side=snap.side,
        stop_price=stop_price,
        atr_multiplier=atr_multiplier,
        rationale=rationale,
    )


# ----------------------------------------------------------------------- take profit


def compute_dynamic_take_profit_ladder(
    snap: PaperPositionSnapshot,
    *,
    rungs_bps: tuple[float, ...] = (20.0, 50.0, 100.0),
    partial_fractions: tuple[float, ...] = (0.5, 0.3, 0.2),
) -> DynamicTakeProfitLadder:
    """Laddered partial exits at progressive bps targets."""
    if len(rungs_bps) != len(partial_fractions):
        raise ValueError("rungs_bps and partial_fractions must have equal length")
    fractions_sum = sum(partial_fractions)
    if not (0.999 <= fractions_sum <= 1.001):
        raise ValueError(f"partial_fractions must sum to ~1.0, got {fractions_sum}")
    sign = _sign_for_side(snap.side)
    rungs: list[tuple[float, float]] = []
    for bps, fraction in zip(rungs_bps, partial_fractions):
        target_price = snap.entry_price * (1.0 + sign * (bps / 10000.0))
        rungs.append((target_price, fraction))
    return DynamicTakeProfitLadder(
        symbol=snap.symbol,
        side=snap.side,
        rungs=tuple(rungs),
        rationale=(
            f"laddered rungs at "
            + ", ".join(f"{b}bps" for b in rungs_bps)
            + f" with fractions {partial_fractions}"
        ),
    )


# ----------------------------------------------------------------------- churn veto


def churn_veto(
    *,
    seconds_since_last_close: int,
    minimum_hold_seconds: int = 300,
) -> ChurnVetoResult:
    """Block reopening same-side too soon after a close."""
    blocked = seconds_since_last_close < minimum_hold_seconds
    return ChurnVetoResult(
        blocked=blocked,
        reason=(
            f"BLOCKED_BY_MINIMUM_HOLD seconds_since_last_close="
            f"{seconds_since_last_close} < minimum_hold_seconds={minimum_hold_seconds}"
            if blocked
            else "ALLOWED"
        ),
        seconds_since_last_close=seconds_since_last_close,
    )


# ----------------------------------------------------------------------- fee ratio gate


def evaluate_fee_ratio_gate(
    *,
    fee_bps: float,
    expected_move_after_cost_bps: float | None,
    max_ratio: float = 0.5,
) -> FeeRatioGateResult:
    """Block when fee_bps / abs(expected_move_after_cost_bps) exceeds max_ratio.

    If expected_move_after_cost_bps is missing or zero, the gate is blocked
    (cannot prove the expected move beats fees).
    """
    if expected_move_after_cost_bps is None or abs(expected_move_after_cost_bps) <= 0.0:
        return FeeRatioGateResult(
            blocked=True,
            fee_bps=fee_bps,
            expected_move_after_cost_bps=expected_move_after_cost_bps,
            ratio=None,
            reason="MISSING_EXPECTED_MOVE_AFTER_COST_BPS",
        )
    ratio = fee_bps / abs(expected_move_after_cost_bps)
    blocked = ratio > max_ratio
    return FeeRatioGateResult(
        blocked=blocked,
        fee_bps=fee_bps,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
        ratio=ratio,
        reason=(
            f"BLOCKED_BY_FEE_RATIO ratio={ratio:.4f} > max_ratio={max_ratio:.4f}"
            if blocked
            else "ALLOWED"
        ),
    )


# ----------------------------------------------------------------------- hedge / DCA


def evaluate_hedge_dca(*, request: dict[str, Any]) -> HedgeDcaEvaluation:
    """Hedge / DCA evaluator. Fail-closed by default.

    The legacy adaptive hedge builders are NOT ported to V2 yet. This stub
    denies every request with an explicit reason. It is intentionally
    classified `FAIL_CLOSED_STUB` under the migration completion contract.
    """
    return HedgeDcaEvaluation(
        allowed=False,
        reason="HEDGE_DCA_NOT_PORTED_TO_V2_FAIL_CLOSED_STUB",
        classification="FAIL_CLOSED_STUB",
    )


# ----------------------------------------------------------------------- service


@dataclass
class TradeManagementPaperService:
    """Public facade for the paper trade-management engine."""

    base_buffer_bps: float = 25.0
    atr_multiplier: float = 2.0
    minimum_hold_seconds: int = 300
    fee_ratio_max: float = 0.5

    def plan_for_position(self, snap: PaperPositionSnapshot) -> dict[str, Any]:
        stealth = compute_stealth_stop_schedule(snap, base_buffer_bps=self.base_buffer_bps)
        stop = compute_dynamic_stop_plan(snap, atr_multiplier=self.atr_multiplier)
        tp = compute_dynamic_take_profit_ladder(snap)
        return {
            "schema_version": TRADE_MANAGEMENT_PAPER_SCHEMA_VERSION,
            "symbol": snap.symbol,
            "side": snap.side,
            "stealth_stop": asdict(stealth),
            "dynamic_stop": asdict(stop),
            "take_profit_ladder": {
                "symbol": tp.symbol,
                "side": tp.side,
                "rungs": list(tp.rungs),
                "rationale": tp.rationale,
            },
        }

    def evaluate_pre_trade(
        self,
        *,
        seconds_since_last_close: int,
        fee_bps: float,
        expected_move_after_cost_bps: float | None,
    ) -> dict[str, Any]:
        churn = churn_veto(
            seconds_since_last_close=seconds_since_last_close,
            minimum_hold_seconds=self.minimum_hold_seconds,
        )
        fee_gate = evaluate_fee_ratio_gate(
            fee_bps=fee_bps,
            expected_move_after_cost_bps=expected_move_after_cost_bps,
            max_ratio=self.fee_ratio_max,
        )
        allowed = (not churn.blocked) and (not fee_gate.blocked)
        return {
            "allowed": allowed,
            "churn_veto": asdict(churn),
            "fee_ratio_gate": asdict(fee_gate),
        }

    def evaluate_hedge_request(self, request: dict[str, Any]) -> dict[str, Any]:
        hd = evaluate_hedge_dca(request=request)
        return asdict(hd)

    def current_paper_only_status(self) -> dict[str, Any]:
        return {
            "worker_id": "v2_trade_management_paper",
            "schema_version": TRADE_MANAGEMENT_PAPER_SCHEMA_VERSION,
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": false_(),
            "scope": "PAPER_ONLY",
            "components_ported": [
                "stealth_stop_schedule_with_time_decay",
                "dynamic_atr_based_stop_plan",
                "dynamic_take_profit_ladder",
                "churn_veto_minimum_hold",
                "fee_ratio_gate",
                "hedge_dca_fail_closed_stub",
                "paper_position_lifecycle_controller",
                "paper_netting_and_symbol_exposure_caps",
                "paper_exit_coordinator_minimum_tiers",
                "paper_closed_trade_outcome_labels",
                "TradeManagementPaperService.plan_for_position",
                "TradeManagementPaperService.evaluate_pre_trade",
            ],
            "components_missing": [
                "full_legacy_stealth_stops_state_machine",
                "full_dynamic_tp_engine_regime_adaptive_ladders",
                "full_dynamic_adaptive_stops_regime_adaptive_distance",
                "adaptive_hedge_builder",
                "dynamic_adaptive_hedge",
                "hedge_pair_coordinator",
                "leg_manager",
                "stealth_dynamic_integration",
                "live_order_routing",
            ],
            "legacy_sha256_citations": LEGACY_SOURCES,
            "migration_classification": "PARTIALLY_MIGRATED",
            "contract_ref": "claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md",
        }


def false_() -> bool:
    """Explicit boolean false for the `approves_redis_trim` field.

    Wrapped to make grep-based audits trivially confirm no truthy override.
    """
    return False
