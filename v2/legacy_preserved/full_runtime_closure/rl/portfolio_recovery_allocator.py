"""
Portfolio Recovery Allocation (PRA) — URC Stage‑2 (Scaffolding)
==============================================================
This module is intentionally conservative:

- It does NOT replace per‑symbol hedging.
- By default it is **recommendation-only**: it publishes suggestions to Redis for operator visibility.
- Execution (opening new risk on other symbols to earn back drawdowns) is controlled by a separate
  flag and is intentionally left OFF by default.

Why this exists:
- When margin is tight and hedges are capped, per‑symbol hedging can prevent realized losses but
  cannot always "repair" an underwater book quickly.
- PRA is an optional, bounded allocator that looks for *higher‑quality* opportunities across the
  trading universe and suggests where a small recovery budget could be deployed.

Data sources (no CoinAnk dependency):
- `portfolio:equity:{account_id}`
- `portfolio:positions:{account_id}`
- `price:realtime:{SYMBOL}` via `AdaptiveEdgeGate.fetch_market_conditions`
- `unified_features:{SYMBOL}:{tf}`, `msnap:coinapi_wsds:{SYMBOL}`, `orderbook:top:{SYMBOL}` (via edge gate)

Outputs:
- Redis stream: `signals:portfolio_recovery:suggestions`
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _to_str(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="ignore")
    return str(v)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        if isinstance(v, (bytes, bytearray)):
            v = v.decode("utf-8", errors="ignore")
        return float(v)
    except Exception:
        return float(default)


def _tf_to_ms(tf: str) -> int:
    """
    Convert timeframe string to milliseconds (best-effort).
    Supports: 'Xm', 'Xh', 'Xd' where X is int.
    """
    try:
        s = str(tf or "").strip().lower()
        if not s:
            return 0
        unit = s[-1]
        n = int(s[:-1])
        if n <= 0:
            return 0
        if unit == "m":
            return n * 60_000
        if unit == "h":
            return n * 3_600_000
        if unit == "d":
            return n * 86_400_000
    except Exception:
        return 0
    return 0


@dataclass
class PRASuggestion:
    account_id: str
    symbol: str
    side: str
    score: float
    suggested_margin_usd: float
    suggested_notional_usd: float
    leverage: float
    reason: str
    context: Dict[str, Any]


class PortfolioRecoveryAllocator:
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._last_publish_ts: float = 0.0
        self._edge_gate = None
        try:
            from trading.adaptive_edge_gate import get_adaptive_edge_gate

            self._edge_gate = get_adaptive_edge_gate(redis_client=self.redis)
        except Exception as e:
            logger.debug(f"[PRA] AdaptiveEdgeGate unavailable: {e}")
            self._edge_gate = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _read_equity(self, account_id: str) -> Dict[str, Any]:
        if not self.redis:
            return {}
        raw = self.redis.get(f"portfolio:equity:{account_id}")
        if not raw:
            return {}
        raw = _to_str(raw)
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        return data if isinstance(data, dict) else {}

    def _stress_sev(self, eq: Dict[str, Any]) -> float:
        """
        Simple severity proxy in [0,1] (no static block):
        - Higher margin utilization -> higher sev
        - Lower available margin -> higher sev
        """
        equity = _to_float(eq.get("equity_usd", 0.0) or 0.0, 0.0)
        used = _to_float(eq.get("used_margin_usd", 0.0) or 0.0, 0.0)
        avail = _to_float(eq.get("available_margin_usd", 0.0) or 0.0, 0.0)
        util = (used / equity) if equity > 0 else 1.0
        util = max(0.0, min(2.0, float(util)))
        util01 = max(0.0, min(1.0, float(util)))

        # Availability danger: if avail is small relative to equity, danger rises.
        avail_pct = (avail / equity) if equity > 0 else 0.0
        avail_danger = 1.0 - max(0.0, min(1.0, float(avail_pct) / 0.10))  # 10% equity buffer -> low danger
        sev = 1.0 - ((1.0 - util01) * (1.0 - avail_danger))
        return max(0.0, min(1.0, float(sev)))

    def _score_symbol(self, cond: Any) -> Tuple[float, str, Dict[str, Any]]:
        """
        Produce a *relative* candidate score (higher = better) based on:
        - expected move (ATR / realized vol)
        - momentum + squeeze
        - costs (spread/slippage) and micro risk (spoof/fast_move)
        """
        try:
            atr = float(getattr(cond, "atr_pct", 0.0) or 0.0)
            rv = float(getattr(cond, "realized_vol_5m", 0.0) or 0.0)
            expected_move = max(float(atr), float(rv) * 2.0)
        except Exception:
            expected_move = 0.0

        try:
            squeeze = float(getattr(cond, "squeeze_potential", 0.0) or 0.0)
        except Exception:
            squeeze = 0.0
        try:
            mom = float(getattr(cond, "momentum_score", 0.0) or 0.0)
        except Exception:
            mom = 0.0
        mom_abs = max(0.0, min(1.0, abs(float(mom))))

        try:
            spread_bps = float(getattr(cond, "spread_bps", 0.0) or 0.0)
        except Exception:
            spread_bps = 0.0
        try:
            slippage_bps = float(getattr(cond, "estimated_slippage_bps", 0.0) or 0.0)
        except Exception:
            slippage_bps = 0.0

        try:
            spoof = float(getattr(cond, "spoof_score", 0.0) or 0.0)
        except Exception:
            spoof = 0.0
        try:
            fast_move = float(getattr(cond, "fast_move_score", 0.0) or 0.0)
        except Exception:
            fast_move = 0.0
        micro_bad = max(0.0, min(1.0, max(float(spoof), float(fast_move))))

        # Direction heuristic: follow momentum sign by default.
        side = "LONG" if float(mom) >= 0 else "SHORT"

        # Score: edge proxy / (cost + micro risk)
        edge = float(expected_move) * (0.6 + 0.4 * mom_abs) * (1.0 + 0.7 * float(squeeze))
        cost = (float(spread_bps) + float(slippage_bps)) / 100.0  # bps -> %
        denom = 0.02 + cost + (0.20 * float(micro_bad))  # keep denom >0
        score = float(edge) / float(denom) if denom > 0 else 0.0

        ctx = {
            "expected_move_pct": float(expected_move),
            "squeeze": float(squeeze),
            "momentum": float(mom),
            "spread_bps": float(spread_bps),
            "slippage_bps": float(slippage_bps),
            "micro_bad": float(micro_bad),
        }
        reason = f"edge≈{edge:.4f}% cost≈{cost:.3f}% micro_bad={micro_bad:.2f}"
        return float(score), str(side), ctx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_suggestions(
        self,
        *,
        account_id: str,
        universe: Iterable[str],
        max_suggestions: int = 3,
    ) -> List[PRASuggestion]:
        if not self.redis or not self._edge_gate:
            return []

        eq = self._read_equity(account_id)
        equity = _to_float(eq.get("equity_usd", 0.0) or 0.0, 0.0)
        avail = _to_float(eq.get("available_margin_usd", 0.0) or 0.0, 0.0)
        sev = self._stress_sev(eq)

        # Dynamic, bounded budget (recommendation-only): more stress => smaller budget.
        # Keep it conservative to avoid worsening margin pressure.
        max_pct_equity = _to_float(os.getenv("PRA_MAX_MARGIN_PCT_EQUITY", "1.0"), 1.0) / 100.0
        max_pct_avail = _to_float(os.getenv("PRA_MAX_MARGIN_PCT_AVAILABLE", "15.0"), 15.0) / 100.0
        stress_scale = max(0.10, 1.0 - float(sev))  # sev high => scale down
        budget_usd = min(float(equity) * float(max_pct_equity) * float(stress_scale), float(avail) * float(max_pct_avail))
        if budget_usd <= 0.0:
            return []

        # Keep leverage low for PRA suggestions (risk-managed; URC Stage‑2 is optional).
        try:
            lev = float(os.getenv("PRA_SUGGEST_LEVERAGE", "3.0"))
        except Exception:
            lev = 3.0
        lev = max(1.0, min(10.0, float(lev)))

        # Rank symbols by adaptive score
        scored: List[Tuple[float, str, str, Dict[str, Any]]] = []
        for sym in universe:
            sym_u = str(sym or "").upper().strip()
            if not sym_u:
                continue
            try:
                cond = self._edge_gate.fetch_market_conditions(sym_u, "5m")
            except Exception:
                continue

            # Freshness guard (avoid acting on stale data)
            try:
                freshness_ms = float(getattr(cond, "data_freshness_ms", 0.0) or 0.0)
            except Exception:
                freshness_ms = 0.0
            # IMPORTANT: `fetch_market_conditions(..., "5m")` uses candle-close features.
            # A 5m TF can be legitimately ~5m old; 60s is too strict and makes PRA "dead".
            # Default: allow up to ~3 candles of staleness, unless env override is set.
            env_max_age = os.getenv("PRA_MAX_DATA_STALENESS_MS")
            if env_max_age is not None:
                max_age_ms = float(_to_float(env_max_age, 60000.0))
            else:
                tf_ms = float(_tf_to_ms("5m") or 0)
                max_age_ms = float(max(60_000.0, 3.0 * tf_ms)) if tf_ms > 0 else 600_000.0
            if freshness_ms and freshness_ms > max_age_ms:
                continue

            score, side, ctx = self._score_symbol(cond)
            ctx["data_freshness_ms"] = float(freshness_ms)
            ctx["pra_max_data_staleness_ms"] = float(max_age_ms)
            if score <= 0:
                continue
            scored.append((float(score), sym_u, side, ctx))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: max(1, int(max_suggestions or 3))]
        if not top:
            return []

        # Split budget across suggestions (equal split for safety).
        per_usd = float(budget_usd) / float(len(top))
        suggestions: List[PRASuggestion] = []
        for score, sym, side, ctx in top:
            margin_usd = float(per_usd)
            notional_usd = float(margin_usd) * float(lev)
            suggestions.append(
                PRASuggestion(
                    account_id=str(account_id),
                    symbol=str(sym),
                    side=str(side),
                    score=float(score),
                    suggested_margin_usd=float(margin_usd),
                    suggested_notional_usd=float(notional_usd),
                    leverage=float(lev),
                    reason=f"PRA suggestion (sev={sev:.2f}) | {ctx.get('expected_move_pct', 0):.3f}% move | {ctx.get('spread_bps', 0):.1f}bps spread",
                    context=ctx,
                )
            )
        return suggestions

    def maybe_publish_suggestions(
        self,
        *,
        accounts: Iterable[str],
        universe: Iterable[str],
        stream: str = "signals:portfolio_recovery:suggestions",
    ) -> int:
        """
        Publish PRA suggestions periodically.
        Returns number of suggestions published.
        """
        if not self.redis:
            return 0

        enabled = os.getenv("PRA_ENABLED", "true").lower() in ("1", "true", "yes")
        if not enabled:
            return 0

        try:
            interval = float(os.getenv("PRA_PUBLISH_INTERVAL_SEC", "120") or 120.0)
        except Exception:
            interval = 120.0
        now = time.time()
        if (now - float(self._last_publish_ts)) < float(max(5.0, interval)):
            return 0
        self._last_publish_ts = now

        try:
            max_sugs = int(os.getenv("PRA_MAX_SUGGESTIONS_PER_ACCOUNT", "3") or 3)
        except Exception:
            max_sugs = 3

        published = 0
        for acct in accounts:
            acct = str(acct or "").strip().lower()
            if not acct:
                continue
            sugs = self.build_suggestions(account_id=acct, universe=universe, max_suggestions=max_sugs)
            for s in sugs:
                payload = {
                    "ts_ms": int(time.time() * 1000),
                    "type": "PRA_SUGGESTION",
                    **asdict(s),
                }
                try:
                    self.redis.xadd(stream, {"data": json.dumps(payload, separators=(",", ":"))}, maxlen=2000, approximate=True)
                    published += 1
                except Exception:
                    continue

        if published:
            logger.info(f"[PRA] Published {published} suggestions to {stream}")
        return int(published)

    # ------------------------------------------------------------------
    # Optional execution path (Stage-2): PRA_EXECUTE
    # ------------------------------------------------------------------
    def _read_prediction(self, symbol: str, tf: str) -> Tuple[str, float]:
        """
        Read cached trainer prediction from Redis:
        - key: prediction:{symbol}:{tf} (hash)
        - fields: action, confidence
        Returns (direction, confidence) where direction in {LONG, SHORT, FLAT}.
        """
        if not self.redis:
            return "FLAT", 0.0
        try:
            raw = self.redis.hgetall(f"prediction:{symbol}:{tf}") or {}
            if not raw:
                return "FLAT", 0.0

            def _get(k: str):
                v = raw.get(k) or raw.get(k.encode())
                if isinstance(v, (bytes, bytearray)):
                    return v.decode("utf-8", errors="ignore")
                return v

            action = str(_get("action") or "").upper()
            try:
                conf = float(_get("confidence") or 0.0)
            except Exception:
                conf = 0.0

            # Prefer numeric direction from blended_logit when present:
            # - It's the raw directional bias even if the final action is HOLD / PARTIAL_CLOSE.
            # - This better matches the "diversify by confidence strength" requirement.
            try:
                bl = _get("blended_logit")
                bl_f = float(bl) if bl is not None else 0.0
            except Exception:
                bl_f = 0.0
            if bl_f > 0:
                return "LONG", float(conf)
            if bl_f < 0:
                return "SHORT", float(conf)

            # Fallback: parse action text (ignore CLOSE-only semantics; treat as FLAT).
            if "OPEN_LONG" in action or action in {"LONG", "BUY"}:
                return "LONG", float(conf)
            if "OPEN_SHORT" in action or action in {"SHORT", "SELL"}:
                return "SHORT", float(conf)
            if "CLOSE_LONG_AND_OPEN_SHORT" in action or "FLIP_SHORT" in action:
                return "SHORT", float(conf)
            if "CLOSE_SHORT_AND_OPEN_LONG" in action or "FLIP_LONG" in action:
                return "LONG", float(conf)

            return "FLAT", float(conf)
        except Exception:
            return "FLAT", 0.0

    def build_execution_signals(
        self,
        *,
        account_id: str,
        universe: Iterable[str],
        max_signals: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        Convert PRA suggestions into executable trainer signals.

        Requirements:
        - Must be model-aligned via `prediction:{symbol}:{tf}` (5m/15m/1h)
        - Must remain small/bounded (uses PRA budget sizing)
        - No static threshold "levels": selects top-N by combined score
        """
        if not self.redis or not self._edge_gate:
            return []

        # Use existing suggestion ranking for sizing + micro/cost filtering
        sugs = self.build_suggestions(account_id=account_id, universe=universe, max_suggestions=max(1, int(max_signals)))
        if not sugs:
            return []

        scored: List[Tuple[float, PRASuggestion, str, float, float]] = []
        for s in sugs:
            sym = str(s.symbol).upper()
            # Confirm direction via model (prefer 15m, but require at least one non-1m tf to agree)
            d15, c15 = self._read_prediction(sym, "15m")
            d5, c5 = self._read_prediction(sym, "5m")
            d1h, c1h = self._read_prediction(sym, "1h")

            # Determine best model direction and alignment
            # (no hard threshold; we use relative score)
            dirs = [d for d in (d15, d5, d1h) if d in ("LONG", "SHORT")]
            if not dirs:
                continue
            # Majority vote; tie-break by higher confidence
            long_votes = sum(1 for d in dirs if d == "LONG")
            short_votes = sum(1 for d in dirs if d == "SHORT")
            if long_votes > short_votes:
                model_dir = "LONG"
            elif short_votes > long_votes:
                model_dir = "SHORT"
            else:
                # tie: choose higher-conf direction (15m > 1h > 5m preference)
                model_dir = d15 if d15 in ("LONG", "SHORT") else (d1h if d1h in ("LONG", "SHORT") else d5)

            # Alignment score in [0,1]
            align = float(max(long_votes, short_votes)) / float(max(1, len(dirs)))
            # Confidence proxy (prefer 15m, else avg)
            if model_dir == d15 and c15 > 0:
                model_conf = float(c15)
            else:
                vals = []
                if d15 == model_dir:
                    vals.append(float(c15))
                if d5 == model_dir:
                    vals.append(float(c5))
                if d1h == model_dir:
                    vals.append(float(c1h))
                model_conf = float(sum(vals) / max(1, len(vals))) if vals else 0.0

            # Require model direction to match PRA direction if PRA direction is directional.
            # If PRA suggested side differs, skip (fail-closed).
            if str(s.side).upper() in ("LONG", "SHORT") and str(s.side).upper() != model_dir:
                continue

            # Combined score: PRA score × model_conf × alignment
            combined = float(s.score) * (0.35 + 0.65 * float(model_conf)) * (0.50 + 0.50 * float(align))
            scored.append((combined, s, model_dir, model_conf, align))

        if not scored:
            return []

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: max(1, int(max_signals or 2))]

        signals: List[Dict[str, Any]] = []
        for combined, s, model_dir, model_conf, align in top:
            sym = str(s.symbol).upper()
            action_name = "OPEN_LONG" if model_dir == "LONG" else "OPEN_SHORT"
            signals.append(
                {
                    "account_id": str(account_id),
                    "symbol": sym,
                    "timeframe": "multi",
                    "action": action_name,
                    "action_name": action_name,
                    "side": model_dir,
                    "confidence": float(max(0.0, min(0.99, model_conf))),
                    "leverage": float(s.leverage),
                    "recommended_leverage": float(s.leverage),
                    "margin_usd": float(s.suggested_margin_usd),
                    "notional_usd": float(s.suggested_notional_usd),
                    "position_size_pct": 0.0,
                    "action_category": "OPEN_RISK",
                    "source": "portfolio_recovery_allocator",
                    "auto_rebalance": True,  # allow trader to free profit-only slot/margin if needed
                    "reason": f"PRA_EXECUTE score={s.score:.2f} combined={combined:.2f} model_conf={model_conf:.2f} align={align:.2f} | {s.reason}",
                    "context": {"pra": s.context or {}},
                }
            )

        return signals



