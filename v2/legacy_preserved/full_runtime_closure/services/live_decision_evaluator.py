#!/usr/bin/env python3
"""
Live Decision Outcome Evaluator (OBSERVE_ONLY)

Consumes trainer decisions from `wma:decisions`, snapshots live reference prices,
and writes horizon outcomes to `wma:decision_outcomes`.

Important:
- No orders
- No simulated positions
- No paper portfolio/PnL
- Additive telemetry only
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis

# Add project root for direct service execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("live_decision_evaluator")


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(float(v))
    except Exception:
        return default


def _parse_stream_obj(fields: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    data = fields.get("data")
    if isinstance(data, str):
        try:
            obj = json.loads(data)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return dict(fields)


def _safe_json(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, list):
        return [_safe_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_json(v) for k, v in obj.items()}
    return str(obj)


def _action_direction(action: str) -> int:
    a = str(action or "").upper()
    if not a:
        return 0
    if any(x in a for x in ("HOLD", "WAIT", "NONE", "NO_ACTION")):
        return 0
    long_hits = any(x in a for x in ("OPEN_LONG", "INCREASE_LONG", "AND_LONG", "LONG"))
    short_hits = any(x in a for x in ("OPEN_SHORT", "INCREASE_SHORT", "AND_SHORT", "SHORT"))
    if long_hits and not short_hits:
        return 1
    if short_hits and not long_hits:
        return -1
    return 0


class LiveDecisionEvaluator:
    def __init__(self) -> None:
        self.redis = redis.from_url(config.REDIS_URL, decode_responses=True)
        self.source_stream = str(getattr(config, "DECISION_EVAL_SOURCE_STREAM", "wma:decisions"))
        self.outcome_stream = str(getattr(config, "DECISION_EVAL_OUTCOME_STREAM", "wma:decision_outcomes"))
        self.pending_zset = str(getattr(config, "DECISION_EVAL_PENDING_ZSET", "wma:evaluator:pending"))
        self.last_id_key = str(getattr(config, "DECISION_EVAL_LAST_ID_KEY", "wma:evaluator:last_id"))
        self.maxlen = int(getattr(config, "DECISION_EVAL_STREAM_MAXLEN", 50000) or 50000)
        self.poll_seconds = float(getattr(config, "DECISION_EVAL_POLL_SECONDS", 1.0) or 1.0)
        self.batch_size = int(getattr(config, "DECISION_EVAL_BATCH_SIZE", 250) or 250)
        self.horizons = sorted({int(x) for x in (getattr(config, "DECISION_EVAL_HORIZONS_SECONDS", [60, 300, 900, 3600]) or [60, 300, 900, 3600]) if int(x) > 0})

    def _load_last_id(self) -> str:
        try:
            v = self.redis.get(self.last_id_key)
            if v:
                return str(v)
        except Exception:
            pass
        return "$"

    def _save_last_id(self, sid: str) -> None:
        try:
            self.redis.set(self.last_id_key, str(sid))
        except Exception:
            pass

    def _price_from_unified(self, symbol: str, tf: str) -> Tuple[float, str]:
        try:
            h = self.redis.hgetall(f"unified_features:{symbol}:{tf}") or {}
            for k in ("price", "close", "last_price", "mark_price"):
                px = _as_float(h.get(k), 0.0)
                if px > 0:
                    return px, f"unified:{k}"
        except Exception:
            pass
        return 0.0, ""

    def _price_from_orderbook(self, symbol: str) -> Tuple[float, str]:
        try:
            raw = self.redis.get(f"orderbook:top:{symbol}")
            if not raw:
                return 0.0, ""
            ob = json.loads(raw)
            if isinstance(ob, dict):
                mid = _as_float(ob.get("mid"), 0.0)
                if mid > 0:
                    return mid, "orderbook:mid"
                bid = _as_float(ob.get("bid"), 0.0)
                ask = _as_float(ob.get("ask"), 0.0)
                if bid > 0 and ask > 0:
                    return ((bid + ask) / 2.0), "orderbook:bidask"
                if bid > 0:
                    return bid, "orderbook:bid"
                if ask > 0:
                    return ask, "orderbook:ask"
        except Exception:
            pass
        return 0.0, ""

    def _price_from_mark(self, symbol: str) -> Tuple[float, str]:
        try:
            raw = self.redis.get(f"latest:binance:mark_price:{symbol}")
            if not raw:
                return 0.0, ""
            mk = json.loads(raw)
            px = _as_float((mk or {}).get("mark_price"), 0.0)
            if px > 0:
                return px, "mark_price"
        except Exception:
            pass
        return 0.0, ""

    def _get_live_price(self, symbol: str, tf: str) -> Tuple[float, str]:
        px, src = self._price_from_unified(symbol, tf)
        if px > 0:
            return px, src
        px, src = self._price_from_orderbook(symbol)
        if px > 0:
            return px, src
        px, src = self._price_from_mark(symbol)
        if px > 0:
            return px, src
        return 0.0, "none"

    def _decision_skip_reason(self, d: Dict[str, Any]) -> str:
        sr = str(d.get("skip_reason") or d.get("reason") or "").strip()
        if sr:
            return sr
        constraints = d.get("constraints_applied")
        if isinstance(constraints, list) and constraints:
            return str(constraints[0])
        stage = str(d.get("stage") or "").strip()
        if stage and stage != "final":
            return stage
        return ""

    def _schedule_decision(self, sid: str, d: Dict[str, Any]) -> int:
        kind = str(d.get("kind") or "")
        if kind != "trainer_decision":
            return 0

        symbol = str(d.get("symbol") or "").upper()
        tf = str(d.get("timeframe") or d.get("tf") or "").strip()
        if not symbol or symbol == "*" or not tf or tf == "*":
            return 0

        action = str(d.get("final_action") or d.get("action") or d.get("action_name") or "")
        direction = _action_direction(action)
        confidence = _as_float(d.get("confidence_adjusted", d.get("confidence", d.get("model_confidence", 0.0))), 0.0)

        decision_id = str(d.get("decision_id") or f"{sid}:{symbol}:{tf}")
        ts_ms = _as_int(d.get("ts_ms"), 0)
        if ts_ms <= 0:
            try:
                ts_ms = int(str(sid).split("-", 1)[0])
            except Exception:
                ts_ms = int(time.time() * 1000)

        ref_price, ref_source = self._get_live_price(symbol, tf)
        skip_reason = self._decision_skip_reason(d)

        if ref_price <= 0:
            # Emit a transparent no-price outcome so coverage diagnostics stay honest.
            self._emit_outcome({
                "kind": "decision_outcome",
                "decision_id": decision_id,
                "symbol": symbol,
                "timeframe": tf,
                "horizon_s": 0,
                "direction": direction,
                "action": action,
                "confidence": confidence,
                "ret_bps": None,
                "direction_correct": None,
                "entry_price": None,
                "exit_price": None,
                "skip_reason": "NO_PRICE_AT_DECISION",
                "decision_stage": str(d.get("stage") or ""),
                "decision_skip_reason": skip_reason,
                "ts_ms": int(time.time() * 1000),
            })
            return 0

        base_payload = {
            "decision_stream_id": sid,
            "decision_id": decision_id,
            "symbol": symbol,
            "timeframe": tf,
            "action": action,
            "direction": direction,
            "confidence": confidence,
            "entry_ts_ms": ts_ms,
            "entry_price": ref_price,
            "entry_price_source": ref_source,
            "decision_stage": str(d.get("stage") or ""),
            "decision_skip_reason": skip_reason,
            "move_intensity": _as_float(d.get("move_intensity"), 0.0),
            "move_type": str(d.get("move_type") or ""),
            "move_direction": str(d.get("move_direction") or ""),
            "scenario_logit_delta": _as_float(d.get("scenario_logit_delta"), 0.0),
            "scenario_ev": _as_float(d.get("scenario_ev"), 0.0),
            "scenario_liq_prob": _as_float(d.get("scenario_liq_prob"), 0.0),
            "scenario_top_action": str(d.get("scenario_top_action") or ""),
            "base_logit": _as_float(d.get("blended_logit", d.get("base_logit", 0.0)), 0.0),
            "bias_dir": _as_int(d.get("bias_dir", d.get("tf_bias_dir", 0)), 0),
            "timing_dir": _as_int(d.get("timing_dir", d.get("tf_timing_dir", 0)), 0),
            "conflict_score": _as_float(d.get("conflict_score", d.get("tf_conflict_score", 0.0)), 0.0),
            "tf_votes": d.get("tf_votes") if isinstance(d.get("tf_votes"), dict) else {},
            "top_contributors": d.get("move_top_contributors") or d.get("top_contributors") or [],
        }

        now_ms = int(time.time() * 1000)
        scheduled = 0
        for h in self.horizons:
            payload = dict(base_payload)
            payload["horizon_s"] = int(h)
            payload["due_ts_ms"] = now_ms + int(h * 1000)
            payload["outcome_id"] = f"{decision_id}:{h}"
            try:
                self.redis.zadd(self.pending_zset, {json.dumps(_safe_json(payload), separators=(",", ":")): float(payload["due_ts_ms"])})
                scheduled += 1
            except Exception as e:
                logger.debug(f"pending schedule failed: {e}")
        return scheduled

    def _conflict_bucket(self, score: float) -> str:
        if score < 0.2:
            return "[0.0,0.2)"
        if score < 0.4:
            return "[0.2,0.4)"
        if score < 0.6:
            return "[0.4,0.6)"
        if score < 0.8:
            return "[0.6,0.8)"
        return "[0.8,1.0]"

    def _emit_outcome(self, rec: Dict[str, Any]) -> None:
        obj = _safe_json(rec)
        self.redis.xadd(
            self.outcome_stream,
            {"data": json.dumps(obj, separators=(",", ":"))},
            maxlen=self.maxlen,
            approximate=True,
        )

    def _update_aggregates(self, out: Dict[str, Any]) -> None:
        horizon = int(out.get("horizon_s") or 0)
        if horizon <= 0:
            return
        hkey = f"{horizon}s"
        tf = str(out.get("timeframe") or "?")
        sym = str(out.get("symbol") or "?")
        conflict = _as_float(out.get("conflict_score"), 0.0)
        bucket = self._conflict_bucket(conflict)
        ret_bps = out.get("ret_bps")
        correct = out.get("direction_correct")

        keys = [
            f"wma:eval:accuracy:{hkey}",
            f"wma:eval:by_tf:{tf}:{hkey}",
            f"wma:eval:by_symbol:{sym}:{hkey}",
        ]

        for key in keys:
            self.redis.hincrby(key, "total", 1)
            if isinstance(ret_bps, (int, float)):
                self.redis.hincrbyfloat(key, "sum_ret_bps", float(ret_bps))
            if isinstance(correct, bool):
                self.redis.hincrby(key, "directional_total", 1)
                if correct:
                    self.redis.hincrby(key, "correct", 1)

        ckey = f"wma:eval:conflict_buckets:{hkey}"
        self.redis.hincrby(ckey, f"{bucket}:total", 1)
        if isinstance(correct, bool):
            self.redis.hincrby(ckey, f"{bucket}:directional_total", 1)
            if correct:
                self.redis.hincrby(ckey, f"{bucket}:correct", 1)

    def _process_due(self) -> int:
        now_ms = int(time.time() * 1000)
        try:
            rows = self.redis.zrangebyscore(self.pending_zset, min="-inf", max=now_ms, start=0, num=self.batch_size)
        except Exception:
            rows = []

        processed = 0
        for member in rows or []:
            try:
                self.redis.zrem(self.pending_zset, member)
            except Exception:
                pass

            try:
                p = json.loads(member)
                if not isinstance(p, dict):
                    continue
            except Exception:
                continue

            symbol = str(p.get("symbol") or "").upper()
            tf = str(p.get("timeframe") or "")
            entry_price = _as_float(p.get("entry_price"), 0.0)
            direction = _as_int(p.get("direction"), 0)
            horizon_s = _as_int(p.get("horizon_s"), 0)

            exit_price, exit_source = self._get_live_price(symbol, tf)
            out: Dict[str, Any] = {
                "kind": "decision_outcome",
                "decision_id": str(p.get("decision_id") or ""),
                "outcome_id": str(p.get("outcome_id") or ""),
                "symbol": symbol,
                "timeframe": tf,
                "horizon_s": horizon_s,
                "action": p.get("action"),
                "direction": direction,
                "confidence": _as_float(p.get("confidence"), 0.0),
                "entry_ts_ms": _as_int(p.get("entry_ts_ms"), 0),
                "eval_ts_ms": int(time.time() * 1000),
                "entry_price": entry_price if entry_price > 0 else None,
                "exit_price": exit_price if exit_price > 0 else None,
                "entry_price_source": str(p.get("entry_price_source") or ""),
                "exit_price_source": exit_source,
                "decision_stage": str(p.get("decision_stage") or ""),
                "decision_skip_reason": str(p.get("decision_skip_reason") or ""),
                "move_intensity": _as_float(p.get("move_intensity"), 0.0),
                "move_type": str(p.get("move_type") or ""),
                "move_direction": str(p.get("move_direction") or ""),
                "scenario_logit_delta": _as_float(p.get("scenario_logit_delta"), 0.0),
                "scenario_ev": _as_float(p.get("scenario_ev"), 0.0),
                "scenario_liq_prob": _as_float(p.get("scenario_liq_prob"), 0.0),
                "scenario_top_action": str(p.get("scenario_top_action") or ""),
                "base_logit": _as_float(p.get("base_logit"), 0.0),
                "bias_dir": _as_int(p.get("bias_dir"), 0),
                "timing_dir": _as_int(p.get("timing_dir"), 0),
                "conflict_score": _as_float(p.get("conflict_score"), 0.0),
                "tf_votes": p.get("tf_votes") if isinstance(p.get("tf_votes"), dict) else {},
                "top_contributors": p.get("top_contributors") if isinstance(p.get("top_contributors"), list) else [],
                "skip_reason": "",
            }

            if entry_price <= 0 or exit_price <= 0:
                out["ret_bps"] = None
                out["direction_correct"] = None
                out["skip_reason"] = "NO_PRICE_AT_EVAL"
            else:
                ret_bps = ((exit_price - entry_price) / entry_price) * 10000.0
                out["ret_bps"] = ret_bps
                if direction > 0:
                    out["direction_correct"] = bool(ret_bps > 0)
                elif direction < 0:
                    out["direction_correct"] = bool(ret_bps < 0)
                else:
                    out["direction_correct"] = None

            try:
                self._emit_outcome(out)
                self._update_aggregates(out)
                processed += 1
            except Exception as e:
                logger.debug(f"outcome emit/update failed: {e}")

        return processed

    def run(self) -> None:
        if not bool(getattr(config, "DECISION_EVAL_ENABLED", True)):
            logger.info("Decision evaluator disabled by config")
            return

        logger.info(
            "Decision evaluator started | source=%s outcome=%s horizons=%s",
            self.source_stream,
            self.outcome_stream,
            self.horizons,
        )
        last_id = self._load_last_id()
        stats = Counter()

        while True:
            try:
                resp = self.redis.xread({self.source_stream: last_id}, count=self.batch_size, block=int(max(100, self.poll_seconds * 1000)))
                if resp:
                    for _stream, entries in resp:
                        for sid, fields in entries or []:
                            obj = _parse_stream_obj(fields)
                            scheduled = self._schedule_decision(str(sid), obj)
                            stats["scheduled"] += int(scheduled)
                            last_id = str(sid)
                    self._save_last_id(last_id)

                done = self._process_due()
                stats["processed"] += int(done)

                if (stats["scheduled"] + stats["processed"]) > 0 and (int(time.time()) % 30 == 0):
                    try:
                        pending = int(self.redis.zcard(self.pending_zset) or 0)
                    except Exception:
                        pending = 0
                    logger.info(
                        "[EVAL] scheduled=%s processed=%s pending=%s last_id=%s",
                        stats.get("scheduled", 0),
                        stats.get("processed", 0),
                        pending,
                        last_id,
                    )
                if not resp:
                    time.sleep(self.poll_seconds)
            except KeyboardInterrupt:
                logger.info("Decision evaluator stopped by user")
                return
            except Exception as e:
                logger.warning(f"evaluator loop error: {e}")
                time.sleep(max(1.0, self.poll_seconds))


def main() -> int:
    evaluator = LiveDecisionEvaluator()
    evaluator.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
