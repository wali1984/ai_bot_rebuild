"""V2 paper shadow-outcome metrics (no-trade outcome analysis).

After acceptance-state normalization, `v2:paper:positions` carries
only accepted paper fills; shadow rows (local gates pass but the
upstream strict paper-fill gate withheld the fill) and held rows
(orchestrator pre-emptively held) live in their own keys. This
module computes outcome metrics on those NON-FILL rows so the
system can learn from blocked intents.

Strict invariants enforced at the service boundary:

- Shadow outcomes are labeled ``SHADOW_OUTCOME_ONLY`` and ``HELD_OUTCOME_ONLY``.
- A shadow outcome NEVER counts as an accepted paper position.
- A shadow outcome NEVER counts as a fill.
- A shadow outcome NEVER affects the PnL ledger.
- A shadow outcome NEVER opens the strict paper-fill gate.
- A shadow outcome NEVER approves live, canary, legacy shutdown, or
  Redis trim.
- When the current market price is missing, the outcome row carries
  an explicit ``MISSING_V2_MARKET_PRICE_FOR_SHADOW_OUTCOME`` blocker
  and the metrics are ``None`` â NEVER a fabricated price.

Source rule precedence for the current price:

1. ``v2:market:prices:{symbol}.ticker_24hr.lastPrice``
2. ``v2:features:latest:{symbol}:1m.features.close_price`` only when
   ``feature_freshness_state="CURRENT"``
3. otherwise emit MISSING blocker
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

V2_REDIS_PREFIX = "v2:"
SHADOW_OUTCOME_KEY_TEMPLATE = "v2:paper:shadow_outcome:{symbol}"
SHADOW_OUTCOME_HEARTBEAT_KEY = "v2:paper:shadow_outcome:heartbeat"

SOURCE_V2_MARKET_LAST = "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE"
SOURCE_V2_FEATURES_FRESH_CLOSE = "V2_FEATURES_LATEST_FRESH_CLOSE_PRICE"
MISSING_CURRENT_PRICE_BLOCKER = "MISSING_V2_MARKET_PRICE_FOR_SHADOW_OUTCOME"

LABEL_SHADOW = "SHADOW_OUTCOME_ONLY"
LABEL_HELD = "HELD_OUTCOME_ONLY"

DEFAULT_ROUND_TRIP_FEE_BPS = 10.0  # 5 bps in, 5 bps out (paper-accurate)
DEFAULT_DIRECTION_CONSISTENCY_THRESHOLD_BPS = 5.0
DEFAULT_SHADOW_OUTCOME_TTL_SECONDS = 600
DEFAULT_HEARTBEAT_TTL_SECONDS = 600


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return v if v == v else None
    return None


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        d = datetime.fromisoformat(text)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def _safe_redis_set(redis_client: Any, key: str, value: str, ex: int | None) -> bool:
    """Refuse any key outside v2:paper:shadow_outcome:* (heartbeat included).

    The shadow-outcome service must NEVER write into the accepted-position
    namespace, the legacy namespace, or any non-shadow_outcome key.
    """
    if redis_client is None:
        return False
    if not isinstance(key, str) or not key.startswith(V2_REDIS_PREFIX):
        return False
    if key != SHADOW_OUTCOME_HEARTBEAT_KEY and not key.startswith(
        "v2:paper:shadow_outcome:"
    ):
        return False
    try:
        if ex is not None:
            redis_client.set(key, value, ex=int(ex))
        else:
            redis_client.set(key, value)
        return True
    except Exception:
        return False


def read_v2_current_price(
    redis_client: Any, symbol: str
) -> tuple[float | None, str, str | None]:
    """Return (price, source_label, source_utc) using strict V2-only sources.

    Returns (None, MISSING_CURRENT_PRICE_BLOCKER, None) when neither
    source is available. NEVER reads legacy Redis. NEVER fabricates.
    """
    if redis_client is None or not symbol:
        return None, MISSING_CURRENT_PRICE_BLOCKER, None
    try:
        raw = redis_client.get(f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    except Exception:
        raw = None
    if raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            ticker = payload.get("ticker_24hr")
            if isinstance(ticker, dict):
                px = _coerce_float(ticker.get("lastPrice"))
                if px is not None and px > 0:
                    return px, SOURCE_V2_MARKET_LAST, payload.get("fetched_utc")
    try:
        raw = redis_client.get(f"{V2_REDIS_PREFIX}features:latest:{symbol}:1m")
    except Exception:
        raw = None
    if raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict) and payload.get("feature_freshness_state") == "CURRENT":
            feats = payload.get("features") if isinstance(payload.get("features"), dict) else {}
            for key in ("close_price", "last_price", "lastPrice"):
                px = _coerce_float(feats.get(key))
                if px is not None and px > 0:
                    return px, SOURCE_V2_FEATURES_FRESH_CLOSE, payload.get("generated_at")
    return None, MISSING_CURRENT_PRICE_BLOCKER, None


def _sided_bps(entry: float, current: float, side: str) -> float:
    """Signed bps move in the direction of ``side`` (long: +up, short: +down)."""
    if entry <= 0:
        return 0.0
    raw_bps = ((current - entry) / entry) * 10_000.0
    return raw_bps if str(side).lower() == "long" else -raw_bps


@dataclasses.dataclass(frozen=True)
class ShadowOutcome:
    symbol: str
    decision_label: str  # SHADOW_OUTCOME_ONLY or HELD_OUTCOME_ONLY
    block_reason: str | None
    side: str | None
    shadow_entry_price: float | None
    shadow_entry_price_source: str | None
    shadow_entry_price_utc: str | None
    current_price: float | None
    current_price_source: str
    current_price_source_utc: str | None
    missed_move_bps: float | None
    missed_move_after_cost_bps: float | None
    fee_round_trip_bps: float
    time_since_shadow_seconds: float | None
    direction_consistent_with_prediction: bool | None
    no_trade_correct: bool | None
    false_block_candidate: bool | None
    missing_flags: list[str]
    stale_flags: list[str]
    generated_utc: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "v2_paper_shadow_outcome_v1",
            "symbol": self.symbol,
            "decision_label": self.decision_label,
            "block_reason": self.block_reason,
            "side": self.side,
            "shadow_entry_price": self.shadow_entry_price,
            "shadow_entry_price_source": self.shadow_entry_price_source,
            "shadow_entry_price_utc": self.shadow_entry_price_utc,
            "current_price": self.current_price,
            "current_price_source": self.current_price_source,
            "current_price_source_utc": self.current_price_source_utc,
            "missed_move_bps": self.missed_move_bps,
            "missed_move_after_cost_bps": self.missed_move_after_cost_bps,
            "fee_round_trip_bps": self.fee_round_trip_bps,
            "time_since_shadow_seconds": self.time_since_shadow_seconds,
            "direction_consistent_with_prediction": self.direction_consistent_with_prediction,
            "no_trade_correct": self.no_trade_correct,
            "false_block_candidate": self.false_block_candidate,
            "missing_flags": list(self.missing_flags),
            "stale_flags": list(self.stale_flags),
            "generated_utc": self.generated_utc,
            # Strict invariants pinned in every emitted row.
            "counted_as_accepted_position": False,
            "counted_as_fill": False,
            "affects_pnl_ledger": False,
            "opens_paper_fill_gate": False,
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "places_real_order": False,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        }


def _classify(
    *,
    direction_consistent: bool | None,
    missed_move_after_cost_bps: float | None,
    consistency_threshold_bps: float,
) -> tuple[bool | None, bool | None]:
    """Classify the no-trade outcome of a shadow / held row.

    Returns (no_trade_correct, false_block_candidate).

    A block is "correct" when the asset moved AGAINST the would-be
    direction by enough that the round-trip cost would not have
    been recovered. A block is a "false_block_candidate" when the
    asset moved IN FAVOUR of the would-be direction by more than the
    consistency threshold (i.e. we missed a profitable move).

    When direction or move is unknown, both values are None â the
    row is honestly uncertain, never classified.
    """
    if direction_consistent is None or missed_move_after_cost_bps is None:
        return None, None
    if direction_consistent:
        # asset moved in favour: blocking was a missed opportunity if
        # the move after cost exceeds the threshold.
        return False, missed_move_after_cost_bps > consistency_threshold_bps
    # asset moved against: blocking saved us from a loss after costs.
    return missed_move_after_cost_bps < -consistency_threshold_bps, False


def build_shadow_outcome(
    *,
    redis_client: Any,
    symbol: str,
    side: str | None,
    decision_label: str,
    block_reason: str | None,
    shadow_entry_price: float | None,
    shadow_entry_price_source: str | None,
    shadow_entry_price_utc: str | None,
    prediction: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    fee_round_trip_bps: float = DEFAULT_ROUND_TRIP_FEE_BPS,
    direction_consistency_threshold_bps: float = DEFAULT_DIRECTION_CONSISTENCY_THRESHOLD_BPS,
) -> ShadowOutcome:
    """Compute one shadow / held outcome row.

    Pure-ish: only reads ``v2:market:prices:{symbol}`` and
    ``v2:features:latest:{symbol}:1m`` through ``redis_client``. Does
    not write Redis. Never fabricates a price.
    """
    now = now or datetime.now(timezone.utc)
    missing: list[str] = []
    stale: list[str] = []

    current_price, current_price_source, current_price_source_utc = read_v2_current_price(
        redis_client, symbol
    )
    if current_price is None:
        missing.append(MISSING_CURRENT_PRICE_BLOCKER)

    if shadow_entry_price is None:
        missing.append("MISSING_SHADOW_ENTRY_PRICE")

    missed_move_bps: float | None = None
    missed_move_after_cost_bps: float | None = None
    if shadow_entry_price is not None and current_price is not None and side:
        missed_move_bps = _sided_bps(shadow_entry_price, current_price, side)
        missed_move_after_cost_bps = missed_move_bps - fee_round_trip_bps

    time_since_seconds: float | None = None
    shadow_utc_dt = _parse_utc(shadow_entry_price_utc)
    if shadow_utc_dt is not None:
        time_since_seconds = max(0.0, (now - shadow_utc_dt).total_seconds())
    else:
        missing.append("MISSING_SHADOW_ENTRY_UTC")

    pred_side: str | None = None
    if isinstance(prediction, Mapping):
        sa = prediction.get("selected_action")
        if isinstance(sa, str):
            sa_low = sa.lower()
            if sa_low in ("long", "buy"):
                pred_side = "long"
            elif sa_low in ("short", "sell"):
                pred_side = "short"
    direction_consistent: bool | None = None
    if missed_move_bps is not None:
        # The shadow row carries its own side. If we have a prediction
        # whose selected_action also gives a side, both must agree
        # AND the realised move must support that direction.
        effective_side = pred_side or side
        if effective_side:
            moved_in_favour = (
                missed_move_bps > 0 if effective_side == "long" else missed_move_bps < 0
            )
            direction_consistent = bool(moved_in_favour)

    no_trade_correct, false_block_candidate = _classify(
        direction_consistent=direction_consistent,
        missed_move_after_cost_bps=missed_move_after_cost_bps,
        consistency_threshold_bps=direction_consistency_threshold_bps,
    )

    return ShadowOutcome(
        symbol=symbol.upper(),
        decision_label=decision_label,
        block_reason=block_reason,
        side=side,
        shadow_entry_price=shadow_entry_price,
        shadow_entry_price_source=shadow_entry_price_source,
        shadow_entry_price_utc=shadow_entry_price_utc,
        current_price=current_price,
        current_price_source=current_price_source,
        current_price_source_utc=current_price_source_utc,
        missed_move_bps=missed_move_bps,
        missed_move_after_cost_bps=missed_move_after_cost_bps,
        fee_round_trip_bps=fee_round_trip_bps,
        time_since_shadow_seconds=time_since_seconds,
        direction_consistent_with_prediction=direction_consistent,
        no_trade_correct=no_trade_correct,
        false_block_candidate=false_block_candidate,
        missing_flags=missing,
        stale_flags=stale,
        generated_utc=_utc_iso(),
    )


def write_outcome_to_redis(redis_client: Any, outcome: ShadowOutcome) -> bool:
    key = SHADOW_OUTCOME_KEY_TEMPLATE.format(symbol=outcome.symbol)
    return _safe_redis_set(
        redis_client,
        key,
        json.dumps(outcome.as_payload(), sort_keys=True),
        ex=DEFAULT_SHADOW_OUTCOME_TTL_SECONDS,
    )


def build_heartbeat_payload(
    *,
    outcomes: Iterable[ShadowOutcome],
    generated_utc: str | None = None,
) -> dict[str, Any]:
    rows = list(outcomes)
    label_counts: dict[str, int] = {}
    for o in rows:
        label_counts[o.decision_label] = label_counts.get(o.decision_label, 0) + 1
    missing_by_symbol = {o.symbol: list(o.missing_flags) for o in rows}
    return {
        "schema_version": "v2_paper_shadow_outcome_heartbeat_v1",
        "generated_utc": generated_utc or _utc_iso(),
        "outcome_count": len(rows),
        "label_counts": label_counts,
        "missing_flags_by_symbol": missing_by_symbol,
        "symbols": sorted({o.symbol for o in rows}),
        "allowed_redis_writes": [
            "v2:paper:shadow_outcome:{symbol}",
            SHADOW_OUTCOME_HEARTBEAT_KEY,
        ],
        "counted_as_accepted_position": False,
        "counted_as_fill": False,
        "affects_pnl_ledger": False,
        "opens_paper_fill_gate": False,
        "no_synthetic_price": True,
        "no_legacy_redis_read": True,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def write_heartbeat_to_redis(redis_client: Any, payload: dict[str, Any]) -> bool:
    return _safe_redis_set(
        redis_client,
        SHADOW_OUTCOME_HEARTBEAT_KEY,
        json.dumps(payload, sort_keys=True),
        ex=DEFAULT_HEARTBEAT_TTL_SECONDS,
    )
