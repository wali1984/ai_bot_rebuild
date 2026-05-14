import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from risk.kill_switch import KILL_SWITCH_KEY, get_kill_switch, kill_switch_blocks, set_kill_switch
from risk.phase_controller import get_phase_limits, get_ramp_phase
from risk.assertions import assert_risk, RiskResult


@dataclass
class Violation:
    code: str
    msg: str
    fields: Dict[str, Any]


class HaltManager:
    def __init__(
        self,
        redis_client,
        telegram=None,
        account_id: str = "primary",
        kill_key: str = KILL_SWITCH_KEY,
    ):
        self.redis = redis_client
        self.telegram = telegram
        self.account_id = str(account_id or "primary").strip().lower()
        self.kill_key = kill_key

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _tg_dedupe(self, key: str, ttl_sec: int = 300) -> bool:
        if not self.redis:
            return False
        dedupe_key = f"wma:tg_dedupe:{key}"
        try:
            if self.redis.setnx(dedupe_key, "1"):
                self.redis.expire(dedupe_key, int(ttl_sec))
                return False
        except Exception:
            return False
        return True

    def _fail_storm_triggered(self, window_sec: int = 120, threshold: int = 10) -> bool:
        if not self.redis:
            return False
        key = f"wma:exec_fail:{self.account_id}"
        now_ms = self._now_ms()
        min_ms = now_ms - (window_sec * 1000)
        try:
            self.redis.zadd(key, {str(now_ms): now_ms})
            self.redis.zremrangebyscore(key, 0, min_ms)
            count = int(self.redis.zcard(key) or 0)
            self.redis.expire(key, window_sec * 2)
            return count >= threshold
        except Exception:
            return False

    def _mu_breach_sustained(self, mu_after: float, max_mu: float, breach_delta: float = 0.03, sustain_sec: int = 15) -> bool:
        if not self.redis:
            return False
        if max_mu <= 0:
            return False
        if mu_after <= (max_mu + breach_delta):
            try:
                self.redis.delete(f"wma:mu_breach_start:{self.account_id}")
            except Exception:
                pass
            return False
        key = f"wma:mu_breach_start:{self.account_id}"
        now_ms = self._now_ms()
        try:
            raw = self.redis.get(key)
            if not raw:
                self.redis.set(key, str(now_ms))
                return False
            start_ms = int(raw)
            if now_ms - start_ms >= (sustain_sec * 1000):
                return True
        except Exception:
            return False
        return False

    def check_fail_storm(self) -> bool:
        return self._fail_storm_triggered()

    def check_mu_breach(self, mu_after: float, max_mu: float) -> bool:
        return self._mu_breach_sustained(mu_after, max_mu)

    def is_halted(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        active, data = get_kill_switch(self.redis, account=self.account_id)
        if not active:
            return False, None
        return True, data

    def _phase_from_redis(self) -> str:
        phase = get_ramp_phase(self.redis)
        if not phase:
            phase = os.getenv("RAMP_PHASE")
        phase = str(phase or "").strip().lower()
        if not phase:
            phase = "2500"
        return phase

    def _phase_limits(self, phase: str) -> Dict[str, Any]:
        return get_phase_limits(phase)

    def _symbol_bucket(self, symbol: str) -> str:
        sym = str(symbol or "").upper().strip()
        if sym in {"BTCUSDT", "ETHUSDT"}:
            return "major"
        try:
            from config import SYMBOL_LEVERAGE_CONFIG
        except Exception:
            SYMBOL_LEVERAGE_CONFIG = {}
        try:
            lev_cfg = SYMBOL_LEVERAGE_CONFIG.get(sym) or {}
            max_lev = float(lev_cfg.get("max_leverage") or 0.0)
        except Exception:
            max_lev = 0.0
        if max_lev and max_lev <= 15:
            return "meme"
        return "alt"

    def _equity_snapshot(self) -> Dict[str, Any]:
        if not self.redis:
            return {}
        key = f"portfolio:equity:{self.account_id}"
        try:
            raw = self.redis.get(key)
        except Exception:
            raw = None
        if not raw:
            return {}
        try:
            raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _positions_snapshot(self) -> Dict[str, Any]:
        if not self.redis:
            return {}
        key = f"portfolio:positions:{self.account_id}"
        try:
            raw_map = self.redis.hgetall(key) or {}
        except Exception:
            raw_map = {}
        out = {
            "symbols": set(),
            "symbol_margin": {},
            "bucket_margin": {"major": 0.0, "alt": 0.0, "meme": 0.0},
        }
        for k, v in raw_map.items():
            try:
                ks = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
            except Exception:
                ks = str(k)
            if ":" not in ks:
                continue
            sym, _side = ks.rsplit(":", 1)
            sym_u = str(sym or "").upper().strip()
            try:
                vs = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
            except Exception:
                vs = v
            try:
                pos = json.loads(vs) if isinstance(vs, str) and vs.strip().startswith("{") else {}
            except Exception:
                pos = {}
            if not isinstance(pos, dict):
                continue
            try:
                sz = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or pos.get("qty", 0) or 0))
            except Exception:
                sz = 0.0
            if sz <= 0:
                continue
            out["symbols"].add(sym_u)
            try:
                m = float(pos.get("margin_used") or pos.get("initialMargin") or 0.0)
            except Exception:
                m = 0.0
            out["symbol_margin"].setdefault(sym_u, 0.0)
            out["symbol_margin"][sym_u] += abs(m)
        for sym_u, m in out["symbol_margin"].items():
            bucket = self._symbol_bucket(sym_u)
            out["bucket_margin"][bucket] = float(out["bucket_margin"].get(bucket, 0.0)) + float(m)
        out["open_count"] = len(out["symbols"])
        return out

    def _post_cascade_active(self) -> bool:
        if not self.redis:
            return False
        key = f"wma:post_cascade:{self.account_id}"
        try:
            return bool(self.redis.get(key))
        except Exception:
            return False

    def _track_daily_dd(self, equity: float) -> Tuple[float, Optional[float]]:
        if not self.redis or equity <= 0:
            return 0.0, None
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"wma:equity_day:{self.account_id}"
        try:
            raw = self.redis.get(key)
        except Exception:
            raw = None
        day_equity = None
        stored_day = None
        if raw:
            try:
                raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict):
                    stored_day = str(data.get("day") or "")
                    day_equity = float(data.get("equity") or 0.0)
            except Exception:
                day_equity = None
        if stored_day != today or not day_equity:
            payload = {"day": today, "equity": float(equity), "ts_ms": self._now_ms()}
            try:
                self.redis.set(key, json.dumps(payload, separators=(",", ":")))
            except Exception:
                pass
            day_equity = float(equity)
        dd = (equity - day_equity) / day_equity if day_equity else 0.0
        return dd, day_equity

    def _track_intraday_dd(self, equity: float, window_sec: int = 900) -> Tuple[float, Optional[float]]:
        if not self.redis or equity <= 0:
            return 0.0, None
        key = f"wma:equity_peak_15m:{self.account_id}"
        now_ms = self._now_ms()
        peak = equity
        peak_ts = now_ms
        try:
            raw = self.redis.get(key)
        except Exception:
            raw = None
        if raw:
            try:
                raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict):
                    peak = float(data.get("equity") or equity)
                    peak_ts = int(data.get("ts_ms") or now_ms)
            except Exception:
                peak = equity
                peak_ts = now_ms
        if (now_ms - peak_ts) > (window_sec * 1000):
            peak = equity
            peak_ts = now_ms
        if equity > peak:
            peak = equity
            peak_ts = now_ms
        try:
            self.redis.set(key, json.dumps({"equity": float(peak), "ts_ms": int(peak_ts)}, separators=(",", ":")))
        except Exception:
            pass
        dd = (equity - peak) / peak if peak else 0.0
        return dd, peak

    def _extract_timeframe(self, signal: Dict[str, Any]) -> Optional[str]:
        tf = signal.get("timeframe") or signal.get("tf") or signal.get("interval")
        if not tf and isinstance(signal.get("metadata"), dict):
            meta = signal.get("metadata") or {}
            tf = meta.get("timeframe") or meta.get("tf") or meta.get("interval")
        tf = str(tf or "").strip()
        if tf and tf != "?":
            return tf
        return None

    def _extract_liq_distance_pct(self, signal: Dict[str, Any]) -> Optional[float]:
        # Prefer pos_liq_distance_pct (leverage-derived, preferred for safety)
        try:
            if "pos_liq_distance_pct" in signal:
                return float(signal.get("pos_liq_distance_pct"))
        except Exception:
            pass
        for key in ("liq_distance_pct", "liquidation_distance_pct", "min_liq_distance_pct"):
            try:
                if key in signal:
                    return float(signal.get(key))
            except Exception:
                pass
        meta = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
        try:
            liq_meta = meta.get("liquidation_proximity") if isinstance(meta, dict) else {}
            if isinstance(liq_meta, dict) and liq_meta.get("distance_pct") is not None:
                return float(liq_meta.get("distance_pct"))
        except Exception:
            pass
        return None

    def check_invariants(
        self,
        signal: Dict[str, Any],
        pm: Dict[str, Any],
        action: str,
        is_risk_add: bool,
        is_reduce: bool,
        margin_usd: float,
    ) -> Optional[Violation]:
        if not is_risk_add:
            return None

        phase_code = self._phase_from_redis()
        phase_limits = get_phase_limits(phase_code)
        equity_data = self._equity_snapshot()
        positions = self._positions_snapshot()
        portfolio = {
            "equity": float(
                equity_data.get("equity_usd")
                or equity_data.get("margin_balance_usd")
                or equity_data.get("wallet_balance_usd")
                or equity_data.get("wallet_balance")
                or 0.0
            ),
            "margin_util": float(pm.get("margin_util", 0.0) or 0.0),
            "free_margin_ratio": float(pm.get("free_margin_ratio", 0.0) or 0.0),
            "open_positions": int(positions.get("open_count") or 0),
            "open_symbols": positions.get("symbols", set()),
            "per_symbol_margin_usd": positions.get("symbol_margin", {}),
            "bucket_margin": positions.get("bucket_margin", {}),
            "post_cascade_active": self._post_cascade_active(),
            "portfolio_mode": pm.get("mode"),
        }
        res = assert_risk("TRADER", phase_limits, portfolio, signal)
        if res.ok:
            return None
        return Violation(res.code, "RISK_ASSERT_FAIL", res.meta)

        symbol = str(signal.get("symbol") or "").upper().strip()
        if not symbol:
            return Violation("SCHEMA_MISSING_SYMBOL", "missing symbol", {"field": "symbol"})

        tf = self._extract_timeframe(signal)
        if not tf:
            return Violation("SCHEMA_MISSING_TF", "missing timeframe", {"field": "timeframe"})
        signal.setdefault("timeframe", tf)

        phase = self._phase_from_redis()
        limits = self._phase_limits(phase)

        pm_margin_util = float(pm.get("margin_util", 0.0) or 0.0)
        pm_free_ratio = float(pm.get("free_margin_ratio", 0.0) or 0.0)

        if self._post_cascade_active():
            return Violation("POST_CASCADE_ACTIVE", "post_cascade_active", {"account": self.account_id})

        if pm_margin_util > float(limits.get("max_mu") or 0.0):
            return Violation(
                "MARGIN_UTIL_BREACH",
                "margin_util exceeds phase ceiling",
                {
                    "margin_util": pm_margin_util,
                    "mu_max": float(limits.get("max_mu") or 0.0),
                    "phase": phase,
                },
            )

        if pm_free_ratio < float(limits.get("min_free_margin_ratio") or 0.0):
            return Violation(
                "FREE_MARGIN_LOW",
                "free_margin_ratio below phase minimum",
                {
                    "free_margin_ratio": pm_free_ratio,
                    "min_free_margin_ratio": float(limits.get("min_free_margin_ratio") or 0.0),
                    "phase": phase,
                },
            )

        equity_data = self._equity_snapshot()
        try:
            equity = float(
                equity_data.get("equity_usd")
                or equity_data.get("margin_balance_usd")
                or equity_data.get("wallet_balance_usd")
                or equity_data.get("wallet_balance")
                or 0.0
            )
        except Exception:
            equity = 0.0
        if equity <= 0:
            return Violation("EQUITY_MISSING", "equity missing or zero", {"account": self.account_id})

        dd, day_equity = self._track_daily_dd(equity)
        if dd <= float(limits.get("daily_dd_halt") or 0.0):
            return Violation(
                "DAILY_DD_HALT",
                "daily drawdown limit breached",
                {
                    "dd": dd,
                    "threshold": float(limits.get("daily_dd_halt") or 0.0),
                    "day_equity": day_equity,
                },
            )

        dd15, peak_equity = self._track_intraday_dd(equity)
        if dd15 <= float(limits.get("intraday_dd_halt") or 0.0):
            return Violation(
                "INTRADAY_DD_HALT",
                "intraday drawdown limit breached",
                {
                    "dd_15m": dd15,
                    "threshold": float(limits.get("intraday_dd_halt") or 0.0),
                    "peak_equity": peak_equity,
                },
            )

        pos = self._positions_snapshot()
        if not pos:
            return Violation("POSITIONS_SNAPSHOT_MISSING", "positions snapshot missing", {})

        open_count = int(pos.get("open_count") or 0)
        is_new_symbol = symbol not in pos.get("symbols", set())
        if is_new_symbol and open_count >= int(limits.get("max_positions") or 0):
            return Violation(
                "MAX_OPEN_POSITIONS",
                "max open positions reached",
                {
                    "open_positions": open_count,
                    "max_open_positions": int(limits.get("max_positions") or 0),
                },
            )

        if is_new_symbol:
            hour_bucket = datetime.utcnow().strftime("%Y%m%d%H")
            key = f"wma:ramp:new_positions:{self.account_id}:{hour_bucket}"
            try:
                cur = int(self.redis.get(key) or 0)
            except Exception:
                cur = 0
            if cur >= int(limits.get("max_new_positions_per_hour") or 0):
                return Violation(
                    "MAX_NEW_POSITIONS_PER_HOUR",
                    "max new positions per hour reached",
                    {
                        "count": cur,
                        "max": int(limits.get("max_new_positions_per_hour") or 0),
                    },
                )

        per_symbol_margin = float(pos.get("symbol_margin", {}).get(symbol, 0.0)) + float(margin_usd or 0.0)
        per_symbol_cap = float(limits.get("per_pos_margin_pct") or 0.0) * equity
        if per_symbol_margin > per_symbol_cap:
            return Violation(
                "PER_SYMBOL_MARGIN_CAP",
                "per-symbol margin exceeds cap",
                {
                    "symbol_margin": per_symbol_margin,
                    "cap": per_symbol_cap,
                    "phase": phase,
                },
            )

        bucket = self._symbol_bucket(symbol)
        bucket_caps = limits.get("bucket_caps", {})
        bucket_cap = float(bucket_caps.get(bucket, 0.0)) * equity
        bucket_margin = float(pos.get("bucket_margin", {}).get(bucket, 0.0)) + float(margin_usd or 0.0)
        if bucket_cap > 0 and bucket_margin > bucket_cap:
            return Violation(
                "BUCKET_MARGIN_CAP",
                "bucket margin exceeds cap",
                {
                    "bucket": bucket,
                    "bucket_margin": bucket_margin,
                    "bucket_cap": bucket_cap,
                },
            )

        min_liq = float(
            limits.get("min_liq_major")
            if bucket == "major"
            else limits.get("min_liq_meme")
            if bucket == "meme"
            else limits.get("min_liq_alt")
        )
        liq_distance = self._extract_liq_distance_pct(signal)
        if liq_distance is None:
            return Violation(
                "LIQ_BUFFER_MISSING",
                "liquidation buffer missing",
                {"min_liq_buffer_pct": min_liq},
            )
        if liq_distance < min_liq:
            return Violation(
                "LIQ_BUFFER_BREACH",
                "liquidation buffer below minimum",
                {
                    "liq_distance_pct": liq_distance,
                    "min_liq_buffer_pct": min_liq,
                },
            )

        if is_new_symbol:
            try:
                self.redis.incr(key)
                self.redis.expire(key, 3600)
            except Exception:
                pass

        return None

    def halt(
        self,
        violation: Violation,
        signal: Dict[str, Any],
        pm: Dict[str, Any],
        action: str,
        is_risk_add: bool,
        is_reduce: bool,
        margin_usd: float,
    ) -> Dict[str, Any]:
        scope = "GLOBAL"
        if str(violation.code or "").upper() == "HALT-01":
            scope = "ACCOUNT"
        payload = {
            "active": 1,
            "reason": violation.code,
            "msg": violation.msg,
            "fields": violation.fields,
            "ts_ms": self._now_ms(),
        }

        # Cold-standby mode: when asjad is explicitly disabled, don't escalate to kill-switch.
        try:
            import config as _cfg

            asjad_enabled = bool(getattr(_cfg, "ACCOUNT_ASJAD_ENABLED", False))
            if str(self.account_id).lower() == "asjad" and not asjad_enabled:
                payload["active"] = 0
                payload["reason"] = f"{violation.code}:ACCOUNT_DISABLED_ASJAD"
                payload["msg"] = "account disabled standby; halt converted to diagnostic"
                print(
                    "HALT_SKIP_DISABLED_ACCOUNT | account=asjad | code=%s | details=%s"
                    % (str(violation.code), str(violation.fields))
                )
                return payload
        except Exception:
            pass

        set_kill_switch(
            self.redis,
            scope=scope,
            code=str(violation.code),
            details=payload,
            account=self.account_id,
            symbol=str(signal.get("symbol") or "") or None,
        )

        if not self._tg_dedupe(f"SYSTEM_HALTED:{violation.code}:{self.account_id}"):
            self._notify_telegram(violation, signal, pm, action, is_risk_add, is_reduce, margin_usd)
        return payload

    def _notify_telegram(
        self,
        violation: Violation,
        signal: Dict[str, Any],
        pm: Dict[str, Any],
        action: str,
        is_risk_add: bool,
        is_reduce: bool,
        margin_usd: float,
    ) -> None:
        if not self.telegram:
            return

        payload = {
            "tg_kind": "SYSTEM_HALTED",
            "env": os.getenv("ENV", "LIVE"),
            "account": self.account_id,
            "ts_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
            "portfolio_mode": pm.get("mode"),
            "engine": "trader",
            "intent": signal.get("intent") or "RISK_GUARD",
            "regime": signal.get("regime") or signal.get("market_regime") or "UNKNOWN",
            "symbol": signal.get("symbol"),
            "action": action,
            "side": signal.get("side") or "NA",
            "reduce_only": bool(signal.get("reduce_only")),
            "is_risk_add": int(bool(is_risk_add)),
            "is_reduce": int(bool(is_reduce)),
            "violation_code": violation.code,
            "message": violation.msg,
            "margin_util": pm.get("margin_util"),
            "free_margin_ratio": pm.get("free_margin_ratio"),
            "equity": self._equity_snapshot().get("equity_usd"),
            "positions_count": self._positions_snapshot().get("open_count"),
            "margin_usd": margin_usd,
        }

        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(self.telegram.send_tg("RISK_HALT", payload))
        except RuntimeError:
            try:
                import asyncio

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.telegram.send_tg("SYSTEM_HALTED", payload))
                loop.close()
            except Exception:
                pass
