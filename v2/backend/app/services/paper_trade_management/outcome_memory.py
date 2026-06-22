"""Outcome-memory store for paper entry gate.

Replaces static hard-coded symbol/timeframe exclusion lists with
evidence-driven dynamic controls based on rolling trade outcomes.

Each (symbol, timeframe) bucket tracks:
    rolling_win_rate: fraction of recent trades that closed in profit
    rolling_ev_bps: average expected value after cost in bps
    drawdown_contribution_usd: cumulative PnL loss from this bucket
    slippage_failure_rate: fraction of fills where slippage exceeded estimate
    reversal_after_entry_rate: fraction of fills that reversed within 2 candles
    missed_tp_then_stop_rate: fraction of fills that nearly hit TP then hit SL

A bucket is DEGRADED when it fails any configured threshold.
Degraded buckets are blocked from new entries until they recover.

All reads/writes use v2: Redis prefix. No legacy Redis writes.
Redis key: v2:paper:outcome_memory:{symbol}:{timeframe}

If Redis is unavailable, returns a non-blocking advisory fallback. Static
soak-test evidence is preserved as metadata only; it is not a permanent
symbol or timeframe blacklist.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ── Static soak-test baseline (advisory only, not gate logic) ─────────────────
# Source: soak-test data 2026-06-16, 340 closed paper trades.
# These are preserved for reference when Redis has no data.
_SOAK_ZERO_EDGE_SYMBOLS: frozenset[str] = frozenset({
    "BCHUSDT",    # 0% WR, -$6.11
    "FILUSDT",    # 0% WR, -$5.04
    "SIRENUSDT",  # 0% WR, -$3.57
    "SUIUSDT",    # 0% WR, -$3.14
    "TRUMPUSDT",  # 0% WR, -$3.04
    "OPUSDT",     # 0% WR, -$2.56
    "CHZUSDT",    # 0% WR, -$2.50
    "ETCUSDT",    # 0% WR, -$3.52
})
_SOAK_NOISY_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m"})
_SOAK_EVIDENCE_DATE = "2026-06-16"
_SOAK_TRADE_COUNT = 340


@dataclass
class OutcomeMemoryBucket:
    """Rolling outcome statistics for one (symbol, timeframe) bucket."""
    symbol: str
    timeframe: str
    trade_count: int = 0
    rolling_win_rate: float | None = None
    rolling_ev_bps: float | None = None
    drawdown_contribution_usd: float = 0.0
    slippage_failure_rate: float | None = None
    reversal_after_entry_rate: float | None = None
    missed_tp_then_stop_rate: float | None = None
    last_updated: str = ""
    block_reason: str | None = None
    degraded: bool = False
    degraded_since: str | None = None
    data_source: str = "REDIS"
    baseline_advisory_reasons: list[str] = field(default_factory=list)
    baseline_evidence_date: str | None = None
    baseline_trade_count: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutcomeMemoryBucket":
        trade_count = d.get("trade_count")
        if trade_count is None:
            trade_count = d.get("total_trades")
        return cls(
            symbol=str(d.get("symbol") or ""),
            timeframe=str(d.get("timeframe") or ""),
            trade_count=int(trade_count or 0),
            rolling_win_rate=_float_or_none(d.get("rolling_win_rate")),
            rolling_ev_bps=_float_or_none(d.get("rolling_ev_bps")),
            drawdown_contribution_usd=float(d.get("drawdown_contribution_usd") or 0.0),
            slippage_failure_rate=_float_or_none(d.get("slippage_failure_rate")),
            reversal_after_entry_rate=_float_or_none(d.get("reversal_after_entry_rate")),
            missed_tp_then_stop_rate=_float_or_none(d.get("missed_tp_then_stop_rate")),
            last_updated=str(d.get("last_updated") or ""),
            block_reason=d.get("block_reason"),
            degraded=bool(d.get("degraded")),
            degraded_since=d.get("degraded_since"),
            data_source=str(d.get("data_source") or "REDIS"),
            baseline_advisory_reasons=list(d.get("baseline_advisory_reasons") or []),
            baseline_evidence_date=d.get("baseline_evidence_date"),
            baseline_trade_count=int(d.get("baseline_trade_count") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "trade_count": self.trade_count,
            "rolling_win_rate": self.rolling_win_rate,
            "rolling_ev_bps": self.rolling_ev_bps,
            "drawdown_contribution_usd": self.drawdown_contribution_usd,
            "slippage_failure_rate": self.slippage_failure_rate,
            "reversal_after_entry_rate": self.reversal_after_entry_rate,
            "missed_tp_then_stop_rate": self.missed_tp_then_stop_rate,
            "last_updated": self.last_updated,
            "block_reason": self.block_reason,
            "degraded": self.degraded,
            "degraded_since": self.degraded_since,
            "data_source": self.data_source,
            "baseline_advisory_reasons": list(self.baseline_advisory_reasons),
            "baseline_evidence_date": self.baseline_evidence_date,
            "baseline_trade_count": self.baseline_trade_count,
        }


@dataclass(frozen=True)
class OutcomeMemoryThresholds:
    """Degradation thresholds — a bucket is DEGRADED when any threshold is breached.

    Defaults are conservative: designed to block on clear underperformance
    while not over-filtering on small sample sizes.
    """
    # Minimum acceptable rolling win rate
    min_win_rate: float = 0.35
    # Maximum acceptable drawdown contribution per bucket (USD)
    max_drawdown_usd: float = -10.0
    # Minimum acceptable rolling expected value per trade after costs (bps)
    min_rolling_ev_bps: float = -5.0
    # Maximum acceptable slippage failure rate
    max_slippage_failure_rate: float = 0.40
    # Maximum acceptable reversal-after-entry rate
    max_reversal_after_entry_rate: float = 0.50
    # Maximum acceptable missed-TP-then-stop rate
    max_missed_tp_then_stop_rate: float = 0.40
    # Minimum trade count before dynamic blocking activates.
    # Below this threshold, keep the bucket eligible and continue collecting evidence.
    min_trade_count_for_dynamic: int = 20


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate_outcome_memory_bucket(
    bucket: OutcomeMemoryBucket,
    thresholds: OutcomeMemoryThresholds | None = None,
) -> dict[str, Any]:
    """Check if a bucket is degraded. Returns a dict with allowed/blocked/reasons."""
    cfg = thresholds or OutcomeMemoryThresholds()
    reasons: list[str] = []

    # Honour pre-set degraded flag from current Redis evidence or previous evaluation.
    if bucket.degraded and bucket.block_reason:
        return {
            "allowed": False,
            "blocked": True,
            "reasons": [bucket.block_reason],
            "source": bucket.data_source,
            "trade_count": bucket.trade_count,
            "rolling_win_rate": bucket.rolling_win_rate,
            "rolling_ev_bps": bucket.rolling_ev_bps,
            "drawdown_contribution_usd": bucket.drawdown_contribution_usd,
        }

    if bucket.trade_count < cfg.min_trade_count_for_dynamic:
        return {
            "allowed": True,
            "blocked": False,
            "reasons": [],
            "source": bucket.data_source
            if bucket.data_source != "REDIS"
            else "INSUFFICIENT_SAMPLE_CURRENT_OUTCOME_MEMORY",
            "trade_count": bucket.trade_count,
            "min_trade_count": cfg.min_trade_count_for_dynamic,
            "baseline_advisory_reasons": list(bucket.baseline_advisory_reasons),
            "baseline_evidence_date": bucket.baseline_evidence_date,
            "baseline_trade_count": bucket.baseline_trade_count,
        }

    if bucket.rolling_win_rate is not None and bucket.rolling_win_rate < cfg.min_win_rate:
        reasons.append(
            f"WIN_RATE_DEGRADED:{bucket.rolling_win_rate:.2%}<{cfg.min_win_rate:.2%}"
        )
    if bucket.drawdown_contribution_usd < cfg.max_drawdown_usd:
        reasons.append(
            f"DRAWDOWN_EXCEEDED:{bucket.drawdown_contribution_usd:.2f}usd<{cfg.max_drawdown_usd:.2f}usd"
        )
    if bucket.rolling_ev_bps is not None and bucket.rolling_ev_bps < cfg.min_rolling_ev_bps:
        reasons.append(
            f"ROLLING_EV_DEGRADED:{bucket.rolling_ev_bps:.2f}bps<{cfg.min_rolling_ev_bps:.2f}bps"
        )
    if (
        bucket.slippage_failure_rate is not None
        and bucket.slippage_failure_rate > cfg.max_slippage_failure_rate
    ):
        reasons.append(
            f"SLIPPAGE_FAILURE_RATE_HIGH:{bucket.slippage_failure_rate:.2%}>{cfg.max_slippage_failure_rate:.2%}"
        )
    if (
        bucket.reversal_after_entry_rate is not None
        and bucket.reversal_after_entry_rate > cfg.max_reversal_after_entry_rate
    ):
        reasons.append(
            f"REVERSAL_AFTER_ENTRY_HIGH:{bucket.reversal_after_entry_rate:.2%}>{cfg.max_reversal_after_entry_rate:.2%}"
        )
    if (
        bucket.missed_tp_then_stop_rate is not None
        and bucket.missed_tp_then_stop_rate > cfg.max_missed_tp_then_stop_rate
    ):
        reasons.append(
            f"MISSED_TP_THEN_STOP_HIGH:{bucket.missed_tp_then_stop_rate:.2%}>{cfg.max_missed_tp_then_stop_rate:.2%}"
        )

    return {
        "allowed": len(reasons) == 0,
        "blocked": len(reasons) > 0,
        "reasons": reasons,
        "source": bucket.data_source,
        "trade_count": bucket.trade_count,
        "rolling_win_rate": bucket.rolling_win_rate,
        "rolling_ev_bps": bucket.rolling_ev_bps,
        "drawdown_contribution_usd": bucket.drawdown_contribution_usd,
    }


def load_outcome_memory_bucket(
    symbol: str,
    timeframe: str,
    redis_client: Any | None,
) -> OutcomeMemoryBucket:
    """Load outcome memory from Redis.

    Missing Redis data is not treated as a permanent exclusion. The returned
    bucket carries advisory baseline metadata but does not block entries until
    current outcome-memory evidence exists for the bucket.
    """
    sym = symbol.upper().strip()
    tf = timeframe.lower().strip()
    key = f"v2:paper:outcome_memory:{sym}:{tf}"

    _min_trade_count = 20  # mirrors OutcomeMemoryThresholds.min_trade_count_for_dynamic
    if redis_client is not None:
        per_symbol_bucket: OutcomeMemoryBucket | None = None
        try:
            raw = redis_client.get(key)
            if raw:
                data = json.loads(raw)
                per_symbol_bucket = OutcomeMemoryBucket.from_dict(data)
                per_symbol_bucket.data_source = "REDIS"
        except Exception:  # noqa: BLE001
            pass

        # CG-F014 fix: when the per-symbol bucket has insufficient trades, also
        # consult the timeframe aggregate. If the aggregate is degraded, prefer
        # it so that a known-bad TF cannot be bypassed by low-sample per-symbol data.
        if per_symbol_bucket is not None and per_symbol_bucket.trade_count >= _min_trade_count:
            return per_symbol_bucket

        aggregate_bucket: OutcomeMemoryBucket | None = None
        try:
            aggregate_key = f"v2:paper:outcome_memory:__ALL__:{tf}"
            raw = redis_client.get(aggregate_key)
            if raw:
                data = json.loads(raw)
                aggregate_bucket = OutcomeMemoryBucket.from_dict(data)
                aggregate_bucket.symbol = sym
                aggregate_bucket.data_source = "REDIS_TIMEFRAME_AGGREGATE"
        except Exception:  # noqa: BLE001
            pass

        # If aggregate is degraded, return it to block the entry even when the
        # per-symbol bucket has insufficient data for its own dynamic block.
        if aggregate_bucket is not None and aggregate_bucket.degraded:
            return aggregate_bucket

        # Per-symbol has some data but insufficient for dynamic block, and
        # aggregate is not degraded (or missing) — return per-symbol bucket.
        if per_symbol_bucket is not None:
            return per_symbol_bucket

        # Per-symbol key missing but aggregate exists (not degraded) — use aggregate.
        if aggregate_bucket is not None:
            return aggregate_bucket

    # Static soak-test advisory fallback: never blocks by itself.
    is_soak_blocked_symbol = sym in _SOAK_ZERO_EDGE_SYMBOLS
    is_soak_noisy_tf = tf in _SOAK_NOISY_TIMEFRAMES
    advisory_reasons: list[str] = []
    if is_soak_blocked_symbol:
        advisory_reasons.append(f"STATIC_SOAK_ZERO_EDGE_SYMBOL:{sym}:evidence_date={_SOAK_EVIDENCE_DATE}")
    if is_soak_noisy_tf:
        advisory_reasons.append(f"STATIC_SOAK_NOISY_TIMEFRAME:{tf}:evidence_date={_SOAK_EVIDENCE_DATE}")

    bucket = OutcomeMemoryBucket(
        symbol=sym,
        timeframe=tf,
        trade_count=0,
        rolling_win_rate=None,
        data_source="NO_CURRENT_OUTCOME_MEMORY_ADVISORY_BASELINE",
        degraded=False,
        block_reason=None,
        baseline_advisory_reasons=advisory_reasons,
        baseline_evidence_date=_SOAK_EVIDENCE_DATE,
        baseline_trade_count=_SOAK_TRADE_COUNT,
    )
    return bucket


def save_outcome_memory_bucket(
    bucket: OutcomeMemoryBucket,
    redis_client: Any,
) -> None:
    """Persist an outcome memory bucket to Redis. All writes use v2: prefix."""
    key = f"v2:paper:outcome_memory:{bucket.symbol.upper()}:{bucket.timeframe.lower()}"
    try:
        redis_client.set(key, json.dumps(bucket.to_dict()))
    except Exception:  # noqa: BLE001
        pass
