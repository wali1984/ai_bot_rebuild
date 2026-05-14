#!/usr/bin/env python3

"""
Telegram Alert System
==========================================
Comprehensive telegram notification system for AI trading bot
"""

import aiohttp
import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Enhanced Telegram notification system"""
    
    def __init__(self, bot_token: str, bot_chat_id: str, channel_id: str, portfolio_channel_id: str = None, trade_channel_id: str = None, ai_signals_channel_id: str = None, redis_client = None):
        self.bot_token = bot_token
        self.bot_chat_id = bot_chat_id
        self.channel_id = channel_id
        self.portfolio_channel_id = portfolio_channel_id or channel_id
        self.trade_channel_id = trade_channel_id or channel_id
        self.ai_signals_channel_id = ai_signals_channel_id or channel_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.MAX_MESSAGE_LENGTH = 3500
        self.redis = redis_client

        # ── BLOCKED-trade batching: suppress individual alerts, send summary ──
        self._blocked_buffer: List[Dict[str, Any]] = []
        self._blocked_flush_interval = 1800  # 30 minutes
        self._blocked_last_flush_ts: float = time.time()

        logger.info(f"✅ Telegram notifier initialized - Portfolio: {self.portfolio_channel_id}, Trade: {self.trade_channel_id}, AI Signals: {self.ai_signals_channel_id}")

    # =====================================================================
    # BLOCKED-trade detector (class-level, reused by all send paths)
    # =====================================================================
    @staticmethod
    def _is_blocked_payload(d: Dict[str, Any]) -> bool:
        """Return True if execution_data represents a BLOCKED trade (no fill, no order, not NOOP).
        Used by send_trade_execution(), send_execution_alert(), and _format_trade_execution()
        to prevent individual BLOCKED alerts from ever reaching users."""
        try:
            def _sf(v):
                try:
                    return float(v) if v not in (None, "") else 0.0
                except (ValueError, TypeError):
                    return 0.0
            eq = _sf(d.get('executedQty') or d.get('executed_qty'))
            ap = _sf(d.get('avgPrice') or d.get('avg_price'))
            if eq > 0 and ap > 0:
                return False  # has fill data → FILLED
            # Explicit NOOP/idempotent → not blocked
            if str(d.get('state_hint', '')).upper() == 'NOOP':
                return False
            if str(d.get('order_type', '')).upper() == 'IDEMPOTENT':
                return False
            if str(d.get('execution_path', '')).lower() == 'idempotent_no_position':
                return False
            # Has real exchange order but no fill yet → ORDER_PLACED (not blocked)
            _oi = d.get('order_id') or d.get('orderId') or d.get('exchange_order_id')
            if _oi:
                ep = str(d.get('execution_path', '')).upper()
                if ep and any(t in ep for t in ('MAKER', 'LIMIT', 'MARKET', 'GTX')):
                    return False
            # Everything else is BLOCKED
            return True
        except Exception:
            return False  # fail-safe: don't suppress

    # =====================================================================
    # Telegram Structured Templates (TG_*_V1)
    # =====================================================================

    @staticmethod
    def _tg_na(value: Any, default: str = "NA") -> str:
        if value is None:
            return default
        if isinstance(value, str) and value.strip() == "":
            return default
        return str(value)

    @staticmethod
    def _tg_bool(value: Any, default: str = "false") -> str:
        if value is None:
            return default
        return "true" if bool(value) else "false"

    @staticmethod
    def _tg_bit(value: Any, default: str = "0") -> str:
        if value is None:
            return default
        return "1" if bool(value) else "0"

    @staticmethod
    def _tg_ts_utc() -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

    @staticmethod
    def _format_symbol_display(symbol: Any) -> str:
        raw = str(symbol or "UNKNOWN").upper()
        pretty = raw
        for suffix in ("USDT", "BUSD", "USDC", "USD", "PERP"):
            if pretty.endswith(suffix):
                pretty = pretty[: -len(suffix)]
                break
        pretty = pretty.strip("_")
        if pretty and pretty != raw:
            return f"{raw} ({pretty})"
        return raw

    def core_header(self, payload: Dict[str, Any]) -> str:
        env = self._tg_na(payload.get("env"))
        account = self._tg_na(payload.get("account"))
        ts_utc = self._tg_na(payload.get("ts_utc"), self._tg_ts_utc())
        portfolio_mode = self._tg_na(payload.get("portfolio_mode"))
        engine = self._tg_na(payload.get("engine"))
        intent = self._tg_na(payload.get("intent"))
        regime = self._tg_na(payload.get("regime"), "UNKNOWN")
        symbol = self._tg_na(payload.get("symbol"))
        action = self._tg_na(payload.get("action"))
        side = self._tg_na(payload.get("side"), "NA")
        reduce_only = self._tg_bool(payload.get("reduce_only"))
        is_risk_add = self._tg_bit(payload.get("is_risk_add"))
        is_reduce = self._tg_bit(payload.get("is_reduce"))

        return (
            f"🧠 WMA AI | {env} | {account}\n"
            f"⏱ {ts_utc} | mode={portfolio_mode} | engine={engine} | intent={intent} | regime={regime}\n"
            f"📌 {symbol} | action={action} | side={side} | reduce_only={reduce_only} | risk_add={is_risk_add} | reduce={is_reduce}"
        )

    def _tg_missing_fields(self, kind: str, payload: Dict[str, Any]) -> List[str]:
        core_fields = [
            "env",
            "account",
            "ts_utc",
            "portfolio_mode",
            "engine",
            "intent",
            "regime",
            "symbol",
            "action",
            "side",
            "reduce_only",
            "is_risk_add",
            "is_reduce",
        ]

        required = {
            "SIGNAL_ACCEPT": [
                "pds",
                "confidence",
                "tf_anchor",
                "book_id",
                "margin_usd",
                "leverage",
                "notional_usd",
                "close_fraction",
                "headroom_ok",
                "slots_used",
                "slots_max",
                "cluster_ok",
                "reason_short",
            ],
            "EXEC_ATTEMPT": [
                "maker_policy",
                "max_attempts",
                "attempt",
                "fallback",
                "order_type",
                "qty",
                "price",
                "tif",
                "spread_bps",
                "depth_is_stale",
                "fast_move_score",
            ],
            "EXEC_RESULT": [
                "status",
                "filled_qty",
                "avg_price",
                "fee_usd",
                "realized_pnl_usd",
                "unrealized_pnl_usd",
                "order_id",
                "client_order_id",
            ],
            "REJECT": [
                "reject_reason",
                "reject_code",
                "margin_util",
                "free_margin_ratio",
                "exec_stress",
                "min_liq_distance_pct",
                "reserve_usd",
            ],
            "RISK_HALT": [
                "violation_code",
                "message",
                "margin_util",
                "free_margin_ratio",
                "equity",
                "positions_count",
            ],
            "SYSTEM_HALTED": [
                "violation_code",
                "message",
                "margin_util",
                "free_margin_ratio",
                "equity",
                "positions_count",
            ],
            "RISK_ASSERT_FAIL": [
                "violation_code",
                "message",
                "account_id",
                "reason",
                "trace_id",
            ],
            "SYSTEM_ALERT": [
                "alert_kind",
                "message",
            ],
        }

        missing = []
        for key in core_fields + required.get(kind, []):
            if key not in payload or payload.get(key) in (None, ""):
                missing.append(key)
        return missing

    @staticmethod
    def _tg_kind_from_payload(payload: Dict[str, Any]) -> Optional[str]:
        return payload.get("tg_kind") or payload.get("kind") or payload.get("template")

    def _format_tg_signal_accept(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"🎯 SIGNAL_ACCEPT | pds={self._tg_na(payload.get('pds'))} | conf={self._tg_na(payload.get('confidence'))} | "
            f"tf={self._tg_na(payload.get('tf_anchor'))} | book={self._tg_na(payload.get('book_id'))}\n\n"
            f"💰 Sizing: margin=${self._tg_na(payload.get('margin_usd'))} | lev={self._tg_na(payload.get('leverage'))}x | "
            f"notional=${self._tg_na(payload.get('notional_usd'))} | close_frac={self._tg_na(payload.get('close_fraction'))}\n"
            f"🧾 Gates: headroom_ok={self._tg_na(payload.get('headroom_ok'))} | slots={self._tg_na(payload.get('slots_used'))}/"
            f"{self._tg_na(payload.get('slots_max'))} | cluster_ok={self._tg_na(payload.get('cluster_ok'))}\n\n"
            f"🧠 Reason: {self._tg_na(payload.get('reason_short'))}"
        )

    def _format_tg_exec_attempt(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"⚙️ EXEC_ATTEMPT | policy={self._tg_na(payload.get('maker_policy'))} | max_attempts={self._tg_na(payload.get('max_attempts'))} | "
            f"attempt={self._tg_na(payload.get('attempt'))}/{self._tg_na(payload.get('max_attempts'))} | fallback={self._tg_na(payload.get('fallback'))}\n\n"
            f"🧾 Order: type={self._tg_na(payload.get('order_type'))} | qty={self._tg_na(payload.get('qty'))} | price={self._tg_na(payload.get('price'))} | "
            f"tif={self._tg_na(payload.get('tif'))}\n"
            f"📊 Micro: spread_bps={self._tg_na(payload.get('spread_bps'))} | depth_stale={self._tg_na(payload.get('depth_is_stale'))} | "
            f"fast_move={self._tg_na(payload.get('fast_move_score'))}"
        )

    def _format_tg_exec_result(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"✅ EXEC_RESULT | status={self._tg_na(payload.get('status'))} | filled_qty={self._tg_na(payload.get('filled_qty'))} | "
            f"avg_price={self._tg_na(payload.get('avg_price'))} | fee=${self._tg_na(payload.get('fee_usd'))}\n\n"
            f"📈 PnL: realized=${self._tg_na(payload.get('realized_pnl_usd'))} | unrealized=${self._tg_na(payload.get('unrealized_pnl_usd'))}\n"
            f"🧾 IDs: order_id={self._tg_na(payload.get('order_id'))} | client_id={self._tg_na(payload.get('client_order_id'))}"
        )

    def _format_tg_reject(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"⛔ REJECT | reason={self._tg_na(payload.get('reject_reason'))} | code={self._tg_na(payload.get('reject_code'))}\n\n"
            f"🧾 Limits: margin_util={self._tg_na(payload.get('margin_util'))} | free_margin_ratio={self._tg_na(payload.get('free_margin_ratio'))} | "
            f"exec_stress={self._tg_na(payload.get('exec_stress'))}\n"
            f"🧯 Liq: min_liq_dist_pct={self._tg_na(payload.get('min_liq_distance_pct'))} | reserve_usd=${self._tg_na(payload.get('reserve_usd'))}"
        )

    def _format_tg_risk_halt(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"🚨 RISK_HALT | code={self._tg_na(payload.get('violation_code'))} | msg={self._tg_na(payload.get('message'))}\n\n"
            f"🧾 Limits: margin_util={self._tg_na(payload.get('margin_util'))} | free_margin_ratio={self._tg_na(payload.get('free_margin_ratio'))}\n"
            f"💼 Equity=${self._tg_na(payload.get('equity'))} | positions={self._tg_na(payload.get('positions_count'))} | margin_usd={self._tg_na(payload.get('margin_usd'))}"
        )

    def _format_tg_system_halted(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"🛑 SYSTEM_HALTED | code={self._tg_na(payload.get('violation_code'))} | msg={self._tg_na(payload.get('message'))}\n\n"
            f"🧾 Limits: margin_util={self._tg_na(payload.get('margin_util'))} | free_margin_ratio={self._tg_na(payload.get('free_margin_ratio'))}\n"
            f"💼 Equity=${self._tg_na(payload.get('equity'))} | positions={self._tg_na(payload.get('positions_count'))} | margin_usd={self._tg_na(payload.get('margin_usd'))}"
        )

    def _format_tg_risk_assert_fail(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"⛔ RISK_ASSERT_FAIL | code={self._tg_na(payload.get('violation_code'))} | msg={self._tg_na(payload.get('message'))}\n"
            f"🔎 reason={self._tg_na(payload.get('reason'))} | trace_id={self._tg_na(payload.get('trace_id'))}"
        )

    def _format_tg_system_alert(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"🟡 SYSTEM_ALERT | kind={self._tg_na(payload.get('alert_kind'))}\n"
            f"🧾 message={self._tg_na(payload.get('message'))}"
        )

    def _format_tg_portfolio_snapshot(self, payload: Dict[str, Any]) -> str:
        return (
            f"📊 PORTFOLIO | {self._tg_na(payload.get('env'))} | {self._tg_na(payload.get('account'))} | {self._tg_na(payload.get('ts_utc'), self._tg_ts_utc())}\n"
            f"mode={self._tg_na(payload.get('portfolio_mode'))} | exec_stress={self._tg_na(payload.get('exec_stress'))} | post_cascade={self._tg_na(payload.get('post_cascade'))}\n\n"
            f"💼 Equity=${self._tg_na(payload.get('equity'))} | Wallet=${self._tg_na(payload.get('wallet'))} | Unrlzd=${self._tg_na(payload.get('unrealized'))} | Rlz24h=${self._tg_na(payload.get('realized_24h'))}\n"
            f"🧾 Margin: util={self._tg_na(payload.get('margin_util'))} | free_ratio={self._tg_na(payload.get('free_margin_ratio'))} | reserve=${self._tg_na(payload.get('reserve_usd'))}\n"
            f"🧯 Risk: min_liq_dist_pct={self._tg_na(payload.get('min_liq_distance_pct'))} | active_syms={self._tg_na(payload.get('active_symbols'))} | open_orders={self._tg_na(payload.get('open_orders'))}\n\n"
            f"🧠 Engines: core_slots={self._tg_na(payload.get('core_slots_used'))}/{self._tg_na(payload.get('core_slots_max'))} | "
            f"strike_slots={self._tg_na(payload.get('strike_slots_used'))}/{self._tg_na(payload.get('strike_slots_max'))} | "
            f"recovery_slots={self._tg_na(payload.get('recovery_slots_used'))}/{self._tg_na(payload.get('recovery_slots_max'))}\n"
            f"🧪 Health: depth_stale_syms={self._tg_na(payload.get('depth_stale_symbols'))} | feed_staleness_max_ms={self._tg_na(payload.get('feed_staleness_max_ms'))}"
        )

    def _format_tg_profit_recycle(self, payload: Dict[str, Any]) -> str:
        return (
            f"{self.core_header(payload)}\n"
            f"♻️ PROFIT_RECYCLE | realized=${self._tg_na(payload.get('realized_usd'))} | recycle=${self._tg_na(payload.get('recycle_usd'))} | pct={self._tg_na(payload.get('recycle_pct'))}\n\n"
            f"🎯 Target: {self._tg_na(payload.get('target_symbol'))} | target_action={self._tg_na(payload.get('target_action'))} | "
            f"freed_margin=${self._tg_na(payload.get('freed_margin_usd'))}\n"
            f"📈 EquityΔ: walletΔ=${self._tg_na(payload.get('wallet_delta'))} | unrlzdΔ=${self._tg_na(payload.get('unrealized_delta'))} | "
            f"equityΔ=${self._tg_na(payload.get('equity_delta'))}"
        )

    async def send_tg(self, kind: str, payload: Dict[str, Any]) -> bool:
        """Unified structured Telegram formatter/sender for TG_*_V1 templates."""
        kind_upper = str(kind or "").upper()

        if kind_upper in {"SIGNAL_ACCEPT", "EXEC_ATTEMPT", "EXEC_RESULT", "REJECT", "RISK_HALT", "SYSTEM_HALTED", "RISK_ASSERT_FAIL", "SYSTEM_ALERT"}:
            missing = self._tg_missing_fields(kind_upper, payload)
            if missing:
                logger.warning(f"TG_FORMAT_MISSING_FIELD | kind={kind_upper} | missing={','.join(missing)}")

        if kind_upper == "SIGNAL_ACCEPT":
            message = self._format_tg_signal_accept(payload)
            ok = await self._send_message(self.ai_signals_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "EXEC_ATTEMPT":
            message = self._format_tg_exec_attempt(payload)
            ok = await self._send_message(self.trade_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "EXEC_RESULT":
            message = self._format_tg_exec_result(payload)
            ok = await self._send_message(self.trade_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "REJECT":
            message = self._format_tg_reject(payload)
            ok = await self._send_message(self.trade_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "RISK_HALT":
            message = self._format_tg_risk_halt(payload)
            ok = await self._send_message(self.trade_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "SYSTEM_HALTED":
            message = self._format_tg_system_halted(payload)
            ok = await self._send_message(self.portfolio_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "RISK_ASSERT_FAIL":
            message = self._format_tg_risk_assert_fail(payload)
            ok = await self._send_message(self.portfolio_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "SYSTEM_ALERT":
            alert_kind = str(payload.get("alert_kind") or "").upper()
            intent = str(payload.get("intent") or "").upper()
            action = str(payload.get("action") or "").upper()
            message_txt = str(payload.get("message") or "").upper()
            if alert_kind.startswith("CANARY") or intent == "CANARY" or action == "CANARY" or message_txt == "CANARY_ONLY":
                try:
                    logger.info(
                        "TG_SUPPRESS_CANARY | kind=SYSTEM_ALERT | alert_kind=%s | intent=%s | action=%s | message=%s",
                        alert_kind,
                        intent,
                        action,
                        message_txt,
                    )
                except Exception:
                    pass
                return False
            message = self._format_tg_system_alert(payload)
            ok = await self._send_message(self.portfolio_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "PORTFOLIO":
            message = self._format_tg_portfolio_snapshot(payload)
            ok = await self._send_message(self.portfolio_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok
        if kind_upper == "PROFIT_RECYCLE":
            message = self._format_tg_profit_recycle(payload)
            ok = await self._send_message(self.trade_channel_id, message)
            self._audit_tg_send(kind_upper, ok, payload)
            return ok

        logger.error(f"TG_FORMAT_UNKNOWN_KIND | kind={kind_upper}")
        return False

    def _audit_tg_send(self, kind: str, ok: bool, payload: Dict[str, Any]) -> None:
        try:
            logger.info(f"TG_SENT | kind={kind} | ok={1 if ok else 0}")
        except Exception:
            pass
        if not self.redis:
            return
        try:
            entry = {
                "kind": str(kind or ""),
                "ok": 1 if ok else 0,
                "ts_ms": int(time.time() * 1000),
                "account": payload.get("account"),
                "symbol": payload.get("symbol"),
            }
            try:
                from config import STREAM_MAXLEN_ALERTS
                maxlen = int(STREAM_MAXLEN_ALERTS)
            except Exception:
                maxlen = 20000
            self.redis.xadd(
                "wma:alerts",
                {"data": json.dumps(entry, separators=(",", ":"))},
                maxlen=maxlen,
                approximate=True,
            )
        except Exception:
            pass
    
    def _get_trainer_metrics(self) -> Dict[str, Any]:
        """Fetch real-time trainer performance metrics from Redis"""
        try:
            if not self.redis:
                return {}
            
            # Get continuous metrics
            metrics = self.redis.hgetall("rl:metrics:continuous")
            if not metrics:
                return {}
            
            # Decode and parse metrics
            decoded_metrics = {}
            for key, value in metrics.items():
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                value_str = value.decode('utf-8') if isinstance(value, bytes) else value
                
                # Try to convert to appropriate type
                try:
                    if key_str in ['timestamp']:
                        decoded_metrics[key_str] = float(value_str)
                    elif '.' in value_str:
                        decoded_metrics[key_str] = float(value_str)
                    else:
                        decoded_metrics[key_str] = int(value_str)
                except:
                    decoded_metrics[key_str] = value_str
            
            return decoded_metrics
            
        except Exception as e:
            logger.debug(f"Could not fetch trainer metrics: {e}")
            return {}
    
    def _chunk_message(self, message: str, max_len: int) -> list:
        """Split a long message into Telegram-safe chunks without cutting lines."""
        if not message:
            return [""]
        if len(message) <= max_len:
            return [message]

        lines = message.split("\n")
        chunks = []
        cur_lines = []
        cur_len = 0

        for line in lines:
            # +1 for newline re-join
            add_len = len(line) + (1 if cur_lines else 0)
            if cur_lines and (cur_len + add_len) > max_len:
                chunks.append("\n".join(cur_lines))
                cur_lines = [line]
                cur_len = len(line)
                continue

            cur_lines.append(line)
            cur_len += add_len

        if cur_lines:
            chunks.append("\n".join(cur_lines))

        # Add small continuation markers when multiple parts
        if len(chunks) > 1:
            out = []
            total = len(chunks)
            for i, ch in enumerate(chunks, start=1):
                if i == 1:
                    out.append(ch)
                else:
                    prefix = f"(cont {i}/{total})\n"
                    # Ensure prefix doesn't push over limit
                    if len(prefix) + len(ch) > max_len:
                        out.append(prefix + ch[: max_len - len(prefix)])
                    else:
                        out.append(prefix + ch)
            return out

        return chunks
    
    async def _send_message(self, chat_id: str, message: str, parse_mode: str = "HTML") -> bool:
        """Send message to Telegram"""
        chunks = self._chunk_message(message, self.MAX_MESSAGE_LENGTH)
        if not chunks:
            chunks = [""]

        url = f"{self.base_url}/sendMessage"
        all_ok = True

        try:
            async with aiohttp.ClientSession() as session:
                for idx, part in enumerate(chunks, start=1):
                    msg_len = len(part) if part else 0
                    preview = part[:100] if part else "(EMPTY)"
                    logger.debug(f"📤 Sending message to {chat_id}: part={idx}/{len(chunks)} len={msg_len}, preview={preview}...")

                    payload = {
                        'chat_id': chat_id,
                        'text': part,
                        'parse_mode': parse_mode,
                        'disable_web_page_preview': True
                    }

                    async with session.post(url, json=payload, timeout=10) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"❌ Telegram API error {response.status}: {error_text}")
                            logger.error(f"📝 Failed message preview: {part[:200] if part else '(empty)'}")
                            all_ok = False

                    # small pacing to avoid bursts on multi-part sends
                    if len(chunks) > 1:
                        await asyncio.sleep(0.25)

            if all_ok:
                logger.info(f"✅ Message sent successfully to {chat_id}")
            return all_ok

        except Exception as e:
            error_str = str(e).lower()
            if "dns" in error_str or "name or service not known" in error_str:
                logger.error(f"❌ DNS Resolution Error: Cannot resolve api.telegram.org")
                logger.error("🌐 Check internet connection and DNS settings")
            elif "general failure" in error_str or "dns server returned" in error_str:
                logger.error(f"❌ DNS Server Error: DNS lookup failed for api.telegram.org")
                logger.error("🌐 Try different DNS servers (8.8.8.8, 1.1.1.1)")
            elif "ssl" in error_str or "certificate" in error_str:
                logger.error(f"❌ SSL/TLS Error: Certificate validation failed")
                logger.error("🔒 Check system time and certificate store")
            else:
                logger.error(f"❌ Error sending message: {e}")
            return False

    @staticmethod
    def _guess_content_type(path: str) -> str:
        ext = os.path.splitext(path or "")[1].lower()
        if ext in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if ext == ".png":
            return "image/png"
        return "application/octet-stream"

    async def _send_photo(
        self,
        chat_id: str,
        photo_path: str,
        caption: Optional[str] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a local image as a Telegram photo with optional caption.

        Falls back to text-only send if the file is missing/unreadable.
        """
        try:
            p = (photo_path or "").strip()
            if not p or not os.path.exists(p):
                logger.debug(f"[TELEGRAM_PHOTO_SKIP] missing photo_path={photo_path}")
                if caption:
                    return await self._send_message(chat_id, caption, parse_mode=parse_mode)
                return False

            url = f"{self.base_url}/sendPhoto"
            async with aiohttp.ClientSession() as session:
                with open(p, "rb") as f:
                    form = aiohttp.FormData()
                    form.add_field("chat_id", str(chat_id))
                    if caption is not None:
                        form.add_field("caption", caption)
                        form.add_field("parse_mode", parse_mode)
                        form.add_field("disable_web_page_preview", "true")
                    form.add_field(
                        "photo",
                        f,
                        filename=os.path.basename(p),
                        content_type=self._guess_content_type(p),
                    )
                    async with session.post(url, data=form, timeout=15) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"❌ Telegram sendPhoto error {response.status}: {error_text}")
                            return False

            logger.info(f"✅ [TELEGRAM_PHOTO_OK] Sent photo to {chat_id}")
            return True
        except Exception as e:
            logger.error(f"❌ [TELEGRAM_PHOTO_ERR] {e}")
            if caption:
                return await self._send_message(chat_id, caption, parse_mode=parse_mode)
            return False

    async def _send_media_group(
        self,
        chat_id: str,
        photo_paths: List[str],
        parse_mode: str = "HTML",
    ) -> bool:
        """Send up to 10 local photos as a Telegram media group (album)."""
        try:
            paths = [p for p in (photo_paths or []) if p and os.path.exists(p)]
            if not paths:
                logger.debug("[TELEGRAM_MEDIAGROUP_SKIP] no valid photo paths")
                return False
            paths = paths[:10]

            url = f"{self.base_url}/sendMediaGroup"
            media = []
            for i, p in enumerate(paths):
                media.append({"type": "photo", "media": f"attach://file{i}"})

            # Read bytes eagerly so file handles don't close before request is sent.
            file_blobs: List[bytes] = []
            file_meta: List[Dict[str, str]] = []
            for p in paths:
                try:
                    with open(p, "rb") as f:
                        file_blobs.append(f.read())
                    file_meta.append(
                        {
                            "filename": os.path.basename(p),
                            "content_type": self._guess_content_type(p),
                        }
                    )
                except Exception as e:
                    logger.debug(f"[TELEGRAM_MEDIAGROUP_READ_FAIL] {p}: {e}")
                    file_blobs.append(b"")
                    file_meta.append({"filename": os.path.basename(p), "content_type": "application/octet-stream"})

            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(chat_id))
                form.add_field("media", json.dumps(media))
                for i, blob in enumerate(file_blobs):
                    if not blob:
                        continue
                    meta = file_meta[i] if i < len(file_meta) else {"filename": f"file{i}", "content_type": "application/octet-stream"}
                    form.add_field(
                        f"file{i}",
                        blob,
                        filename=meta.get("filename") or f"file{i}",
                        content_type=meta.get("content_type") or "application/octet-stream",
                    )

                async with session.post(url, data=form, timeout=20) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"❌ Telegram sendMediaGroup error {response.status}: {error_text}")
                        return False

            logger.info(f"✅ [TELEGRAM_MEDIAGROUP_OK] Sent {len(paths)} photos to {chat_id}")
            return True
        except Exception as e:
            logger.error(f"❌ [TELEGRAM_MEDIAGROUP_ERR] {e}")
            return False
    
    def _format_regime_analysis(self, market_regime_info: Dict[str, Any], tf_hint: Optional[str] = None) -> str:
        """Format comprehensive regime analysis for Telegram signals"""
        try:
            if not market_regime_info:
                return "📊 Regime: Normal Market Conditions"
            
            # Extract regime data
            overall_regime = market_regime_info.get('overall_regime', 'normal')
            regime_analysis = market_regime_info.get('regime_analysis', {})
            timeframe_regimes = market_regime_info.get('timeframe_regimes', {})
            volatility = market_regime_info.get('volatility', 0.5)
            stress_level = market_regime_info.get('stress_level', 0.3)
            structural_regime = market_regime_info.get('effective_structural') or market_regime_info.get('structural_regime')
            macro_regime = market_regime_info.get('macro_regime')
            structural_metrics = market_regime_info.get('structural_metrics') or {}
            time_in_state_days = market_regime_info.get('structural_time_in_state_days')
            risk_mode = market_regime_info.get('risk_mode')
            reg_dir = market_regime_info.get('regime_direction')
            reg_struct = market_regime_info.get('regime_structure')
            reg_stress = market_regime_info.get('regime_stress')
            reg_scores = market_regime_info.get('regime_scores') or {}
            reg_label = market_regime_info.get('regime_label')
            reg_health = market_regime_info.get('regime_health')
            
            # Format overall regime with emoji
            regime_emojis = {
                'crisis': '🚨', 'flash_crash': '⚡', 'bear_market': '🐻',
                'trending_bearish': '📉', 'volatile_sideways': '🌊', 
                'normal': '📊', 'trending_bullish': '📈', 
                'bull_market': '🐂', 'accumulation': '🔄'
            }
            
            regime_emoji = regime_emojis.get(overall_regime, '📊')
            
            # Consistency assertion: structural regime must dominate "Normal"
            if structural_regime and str(structural_regime).upper() != "NORMAL":
                if str(overall_regime).lower() == "normal":
                    overall_regime = "INCONSISTENT"
                    try:
                        if self.redis:
                            entry = {
                                "kind": "REGIME_TG_INCONSISTENT",
                                "ok": 0,
                                "ts_ms": int(time.time() * 1000),
                                "detail": f"structural={structural_regime}",
                            }
                            from config import STREAM_MAXLEN_ALERTS
                            self.redis.xadd(
                                "wma:alerts",
                                {"data": json.dumps(entry, separators=(",", ":"))},
                                maxlen=int(STREAM_MAXLEN_ALERTS),
                                approximate=True,
                            )
                    except Exception:
                        pass

            # Build regime message (truth table)
            regime_msg = f"{regime_emoji} <b>Market Regime</b>\n"
            if reg_label:
                regime_msg += f"Label: <b>{str(reg_label).upper()}</b>"
                if reg_health and str(reg_health).upper() != "OK":
                    regime_msg += f" (health={str(reg_health).upper()})"
                regime_msg += "\n"
            if reg_dir or reg_struct or reg_stress:
                regime_msg += f"Direction: <b>{str(reg_dir or 'NEUTRAL').upper()}</b>\n"
                regime_msg += f"Structure: <b>{str(reg_struct or 'RANGE').upper()}</b>\n"
                regime_msg += f"Stress: <b>{str(reg_stress or 'LOW').upper()}</b>\n"
            else:
                regime_msg += f"Fast: <b>{str(overall_regime).replace('_', ' ').title()}</b>\n"
            if structural_regime:
                dd5 = structural_metrics.get("dd_5d")
                dd10 = structural_metrics.get("dd_10d")
                dd5_s = f"{dd5*100:.1f}%" if isinstance(dd5, (int, float)) else "NA"
                dd10_s = f"{dd10*100:.1f}%" if isinstance(dd10, (int, float)) else "NA"
                tis = f"{float(time_in_state_days):.1f}d" if isinstance(time_in_state_days, (int, float)) else "NA"
                regime_msg += f"Structural: <b>{str(structural_regime).replace('_', ' ')}</b> (DD5d={dd5_s}, DD10d={dd10_s}, t={tis})\n"
            if macro_regime:
                regime_msg += f"Macro(BTC): <b>{str(macro_regime).replace('_', ' ')}</b>\n"
            if risk_mode:
                regime_msg += f"Risk Mode: <b>{str(risk_mode).replace('_', ' ')}</b>\n"

            # Regime derivation highlights (if provided)
            try:
                if reg_scores:
                    dp = reg_scores.get("direction_value")
                    adx = reg_scores.get("adx")
                    liq = reg_scores.get("liq_intensity")
                    vr = reg_scores.get("vol_ratio")
                    ts = reg_scores.get("trend_score")
                    vs = reg_scores.get("vol_score")
                    ds = reg_scores.get("dd_score")
                    ls = reg_scores.get("liq_score")
                    lds = reg_scores.get("liqdn_score")
                    regime_msg += f"Derived: ΔP={dp:.4f} | ADX={adx:.1f} | Liq={liq:.2f} | VR={vr:.2f}\n"
                    if ts is not None and vs is not None and ds is not None and ls is not None and lds is not None:
                        regime_msg += f"Scores: T={ts:.2f} V={vs:.2f} DD={ds:.2f} LQ={ls:.2f} LQD={lds:.2f}\n"
            except Exception:
                pass
            
            # Multi-timeframe breakdown
            if timeframe_regimes:
                regime_msg += f"\n⏰ <b>Timeframe Regimes:</b>\n"
                tf_order = ['1m', '5m', '15m', '1h', '4h', '1d']
                for tf in tf_order:
                    if tf in timeframe_regimes:
                        tf_regime = timeframe_regimes[tf]
                        tf_emoji = regime_emojis.get(tf_regime, '📊')
                        regime_msg += f"  {tf}: {tf_emoji} {tf_regime.replace('_', ' ')[:12]}\n"
                if tf_hint:
                    regime_msg += f"  (tf={tf_hint})\n"
            else:
                tf_val = tf_hint or "UNKNOWN"
                regime_msg += f"\n⏰ <b>Timeframe Regimes:</b> tf={tf_val}\n"
            
            # Market conditions
            regime_msg += f"\n📈 <b>Market Conditions:</b>\n"
            regime_msg += f"  Volatility: {volatility:.1%} {'🔥' if volatility > 0.02 else '📊'}\n"
            regime_msg += f"  Stress Level: {stress_level:.1%} {'⚠️' if stress_level > 0.7 else '✅'}\n"
            
            # Trading bias
            if 'bullish' in str(overall_regime).lower():
                regime_msg += f"  Bias: <b>BULLISH</b> 🐂\n"
            elif 'bearish' in str(overall_regime).lower():
                regime_msg += f"  Bias: <b>BEARISH</b> 🐻\n"
            elif 'crisis' in str(overall_regime).lower() or 'inconsistent' in str(overall_regime).lower():
                regime_msg += f"  Bias: <b>RISK OFF</b> 🚨\n"
            else:
                regime_msg += f"  Bias: <b>NEUTRAL</b> ⚖️\n"
            
            return regime_msg
            
        except Exception as e:
            logger.error(f"Error formatting regime analysis: {e}")
            return "📊 Regime: Analysis unavailable"
    
    def _format_trade_signal(self, signal_data: Dict[str, Any]) -> str:
        """Format comprehensive trade signal"""
        try:
            # Live-only system
            mode = "LIVE"
            mode_emoji = "🔴"
            
            symbol = self._format_symbol_display(signal_data.get('symbol', 'UNKNOWN'))
            action = signal_data.get('action', 'UNKNOWN').upper()
            confidence = signal_data.get('confidence', 0)
            try:
                confidence = float(confidence or 0.0)
            except Exception:
                confidence = 0.0
            # Allow callers to pass 0-1 or 0-100
            if 0.0 <= confidence <= 1.0:
                confidence *= 100.0

            price = signal_data.get('price')
            if price in (None, 0, 0.0):
                price = signal_data.get('current_price', 0)
            try:
                price = float(price or 0.0)
            except Exception:
                price = 0.0
            meta = signal_data.get('metadata') if isinstance(signal_data.get('metadata'), dict) else {}
            timeframe = (
                signal_data.get('timeframe')
                or meta.get('timeframe')
                or meta.get('tf')
                or meta.get('interval')
                or '1m'
            )

            def _is_close_like(act: str) -> bool:
                au = str(act or '').upper()
                return any(tok in au for tok in [
                    'CLOSE', 'STOP_LOSS', 'TAKE_PROFIT', 'PARTIAL_CLOSE', 'REDUCE', 'DECREASE'
                ])

            def _dir_label(d: str) -> str:
                du = str(d or '').upper()
                if du == 'LONG':
                    return 'LONG (UP)'
                if du == 'SHORT':
                    return 'SHORT (DOWN)'
                if du in {'UP', 'DOWN'}:
                    return du
                return du or ''
            
            # Action emoji mapping for 7-action hedge space + legacy actions
            action_emojis = {
                'OPEN_LONG': '📈🟢',
                'OPEN_SHORT': '📉🔴',
                'INCREASE_LONG': '📈⬆️',
                'INCREASE_SHORT': '📉⬇️',
                'DECREASE_LONG': '📈⏬',
                'DECREASE_SHORT': '📉⏫',
                'CLOSE_ALL': '🚪❌',
                'CLOSE_LONG': '📈🚪',
                'CLOSE_SHORT': '📉🚪',
                'TAKE_PROFIT_LONG': '📈💰',
                'TAKE_PROFIT_SHORT': '📉💰',
                'STOP_LOSS_LONG': '📈🛑',
                'STOP_LOSS_SHORT': '📉🛑',
                'PARTIAL_CLOSE_LONG': '📈⚖️',
                'PARTIAL_CLOSE_SHORT': '📉⚖️',
                'PARTIAL_CLOSE': '⚖️',
                'CLOSE_LONG_AND_OPEN_SHORT': '🔄📉',
                'CLOSE_SHORT_AND_OPEN_LONG': '🔄📈',
                'ADD_LONG': '📈➕',
                'ADD_SHORT': '📉➕',
                'LONG': '📈🟢',
                'SHORT': '📉🔴',
                'HOLD': '⏸️',
                'HOLD_LONG': '📈⏸️',
                'HOLD_SHORT': '📉⏸️',
            }
            action_emoji = action_emojis.get(action, '📊')
            
            # Enhanced header with mode indicator
            header = f"🤖 <b>AI TRADE SIGNAL ({mode_emoji} {mode})</b>\n"
            header += f"━━━━━━━━━━━━━━━━━━━━\n\n"
            header += f"📊 <b>{symbol}</b> | {timeframe}\n"
            header += f"{action_emoji} Action: <b>{action}</b>\n"
            header += f"💰 Price: ${price:.4f}\n"
            header += f"🎯 Confidence: {confidence:.1f}%\n\n"

            # Account + price target context (optional, informational)
            try:
                acct = signal_data.get('account_id')
                if acct:
                    header += f"👤 Account: <b>{str(acct).upper()}</b>\n"
            except Exception:
                pass

            try:
                pt = signal_data.get('price_target')
                pt_dir = (signal_data.get('price_target_direction') or '').upper()
                pt_basis = signal_data.get('price_target_basis')
                pt_pct = signal_data.get('price_target_pct')

                if pt is not None and pt_dir:
                    try:
                        pt = float(pt)
                    except Exception:
                        pt = None
                    try:
                        pt_pct_f = float(pt_pct) if pt_pct is not None else None
                    except Exception:
                        pt_pct_f = None

                    if pt is not None:
                        pct_txt = ""
                        if pt_pct_f is not None:
                            pct_val = (pt_pct_f * 100.0) if 0.0 <= pt_pct_f <= 1.0 else pt_pct_f
                            pct_txt = f" ({pct_val:.2f}%)"
                        basis_txt = f" [{pt_basis}]" if pt_basis else ""
                        # IMPORTANT: price_target_* is a MODEL FORECAST direction/level.
                        # For CLOSE_* actions, show it explicitly as a forecast to avoid confusion.
                        label = "Forecast" if _is_close_like(action) else "Target"
                        header += f"🎯 {label}: <b>{_dir_label(pt_dir)}</b> → ${pt:.4f}{pct_txt}{basis_txt}\n"
            except Exception:
                pass

            # Consensus timeframes (informational; derived from multi-TF trend snapshot)
            try:
                ctf = signal_data.get('consensus_tfs')
                if isinstance(ctf, (list, tuple)) and ctf:
                    ctf_txt = ", ".join([str(x) for x in ctf][:8])
                    header += f"🧩 Consensus TFs: <b>{ctf_txt}</b>\n"
            except Exception:
                pass
            
            # Add comprehensive regime analysis if available
            market_regime_info = signal_data.get('market_regime_info', {})
            if market_regime_info:
                header += f"\n{self._format_regime_analysis(market_regime_info, tf_hint=str(timeframe))}\n"
            else:
                # Fallback to basic market regime if available
                market_regime = signal_data.get('market_regime', {})
                if market_regime and isinstance(market_regime, dict):
                    regime_name = market_regime.get('regime', 'UNKNOWN').upper()
                    regime_vol = market_regime.get('volatility', 0)
                    regime_mom = market_regime.get('momentum', 0)
                    regime_stress = market_regime.get('stress_level', 0)
                    
                    # Regime emoji mapping
                    regime_emoji = {
                        'TRENDING': '📈',
                        'VOLATILE': '⚡',
                        'CRISIS': '🚨',
                        'RANGING': '📊',
                        'NORMAL': '✅',
                        'UNKNOWN': '❓'
                    }.get(regime_name, '📊')
                    
                    header += f"\n🌐 <b>MARKET REGIME</b>\n"
                    header += f"{regime_emoji} Regime: <b>{regime_name}</b>\n"
                    header += f"📉 Volatility: {regime_vol:.2%}\n"
                    header += f"💨 Momentum: {regime_mom:+.2%}\n"
                    header += f"⚠️ Stress: {regime_stress:.1%}\n"
                    
                    if market_regime.get('is_extreme_volatility'):
                        header += f"🚨 <b>EXTREME VOLATILITY DETECTED</b>\n"
                    elif market_regime.get('is_high_volatility'):
                        header += f"⚡ <b>HIGH VOLATILITY</b>\n"
                        
                    funding_rate = market_regime.get('funding_rate', 0)
                    if funding_rate != 0:
                        funding_emoji = "💰" if funding_rate > 0 else "💸"
                        header += f"{funding_emoji} Funding: {funding_rate:.4f}%\n"

            # Structural gating reason (if any)
            try:
                blocked_by = signal_data.get("blocked_by") or signal_data.get("blocked_reason")
                risk_mode = signal_data.get("risk_mode")
                struct_regime = signal_data.get("structural_regime")
                if blocked_by:
                    header += f"🛑 Blocked: <b>{str(blocked_by)}</b>\n"
                if risk_mode or struct_regime:
                    header += f"🧱 Risk Mode: <b>{str(risk_mode or 'UNKNOWN')}</b> | Structural={str(struct_regime or 'NA')}\n"
            except Exception:
                pass
            
            header += f"{'='*30}\n\n"
            
            # Get reasoning (type-safe: could be string or dict)
            reasoning = signal_data.get('reasoning', {})
            
            if not reasoning or not isinstance(reasoning, dict):
                # Provide a useful fallback context block (many trainer signals do not attach rich reasoning).
                if reasoning and isinstance(reasoning, str):
                    return header + f"💡 <b>NOTES</b>\n{reasoning[:400]}"

                # Minimal-but-useful context
                action_type = str(signal_data.get('action_type') or '').lower()
                action_cat = str(signal_data.get('action_category') or '').upper()
                src = str(signal_data.get('source') or '').strip()
                why = str(signal_data.get('reason') or '').strip()
                profit_intent = signal_data.get('profit_intent', None)
                reversal = signal_data.get('reversal_confirmed', None)
                rm_active = signal_data.get('ride_move_active', None)
                rm_reason = str(signal_data.get('ride_move_reason') or '').strip()

                close_pct = signal_data.get('close_pct', None)
                close_fraction = signal_data.get('close_fraction', None)
                close_txt = None
                try:
                    if close_fraction is not None:
                        close_txt = f"{float(close_fraction)*100.0:.1f}%"
                    elif close_pct is not None:
                        close_txt = f"{float(close_pct):.1f}%"
                except Exception:
                    close_txt = None

                # Live position snapshot if provided
                pos = signal_data.get('position') if isinstance(signal_data.get('position'), dict) else None
                pos_line = None
                if pos:
                    try:
                        pside = pos.get('side') or pos.get('positionSide') or pos.get('pside')
                        psz = pos.get('size') or pos.get('positionAmt') or pos.get('qty')
                        plev = pos.get('leverage') or pos.get('lev')
                        ppnl = pos.get('pnl_pct') or pos.get('roe') or pos.get('unrealizedPnlPct')
                        pieces = []
                        if pside:
                            pieces.append(str(pside))
                        if psz is not None:
                            pieces.append(f"size={psz}")
                        if plev is not None:
                            pieces.append(f"lev={plev}x")
                        if ppnl is not None:
                            try:
                                pieces.append(f"pnl={float(ppnl):.2f}%")
                            except Exception:
                                pieces.append(f"pnl={ppnl}")
                        if pieces:
                            pos_line = "📌 Position: " + " | ".join(pieces)
                    except Exception:
                        pos_line = None

                lines = []
                if src:
                    lines.append(f"🧩 <b>Source</b>: {src}")
                action_u = str(action or '').upper()
                if action_cat == "PROFIT" or action_u.startswith("SET_") or action_u in {"SET_TAKE_PROFIT", "SET_STOP_LOSS", "UPDATE_TP", "UPDATE_SL"}:
                    action_type = "manage"
                elif _is_close_like(action_u):
                    action_type = "close"
                elif action_u.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")):
                    action_type = "hedge"
                elif "OPEN" in action_u or "INCREASE" in action_u:
                    action_type = "open"

                if action_type:
                    lines.append(f"🧭 <b>Action Type</b>: {action_type}")
                if action_cat:
                    lines.append(f"🏷️ <b>Category</b>: {action_cat}")
                if close_txt and _is_close_like(action):
                    lines.append(f"📉 <b>Close Size</b>: {close_txt}")
                if profit_intent is True:
                    lines.append("💰 <b>Intent</b>: profit-taking")
                if reversal is True:
                    lines.append("🚨 <b>Intent</b>: reversal/defensive")
                if rm_active is True:
                    detail = f" ({rm_reason})" if rm_reason else ""
                    lines.append(f"🏃 <b>Ride-Move</b>: active{detail}")
                if why:
                    lines.append(f"📝 <b>Reason</b>: {why[:240]}")
                if pos_line:
                    lines.append(pos_line)

                if not lines:
                    return header + "ℹ️ No reasoning payload; context unavailable"

                return header + "💡 <b>CONTEXT</b>\n" + "\n".join(lines)
            
            sections = []
            
            # Market Structure
            ms = reasoning.get('market_structure', {})
            if ms and isinstance(ms, dict):
                sections.append(
                    f"🏗️ <b>MARKET STRUCTURE</b>\n"
                    f"• Trend: {ms.get('trend', 'Unknown')}\n"
                    f"• Support: ${float(ms.get('support_level', 0) or 0):.6f}\n"
                    f"• Resistance: ${float(ms.get('resistance_level', 0) or 0):.6f}\n"
                    f"• Volume: {ms.get('volume_profile', 'Unknown')}"
                )
            
            # Technical Analysis
            ta = reasoning.get('technical_analysis', {})
            if ta and isinstance(ta, dict):
                sections.append(
                    f"📈 <b>TECHNICAL INDICATORS</b>\n"
                    f"• RSI: {float(ta.get('rsi', 0) or 0):.2f}\n"
                    f"• MACD: {ta.get('macd_signal', 'Unknown')}\n"
                    f"• Bollinger: {ta.get('bb_position', 'Unknown')}\n"
                    f"• Volume: {ta.get('volume_trend', 'Unknown')}"
                )
            
            # Coinank Data
            coinank = reasoning.get('coinank_data', {})
            if coinank and isinstance(coinank, dict):
                sections.append(
                    f"📊 <b>MARKET SENTIMENT (COINANK)</b>\n"
                    f"• Long/Short: {float(coinank.get('long_short_ratio', 0) or 0):.2f}\n"
                    f"• Open Interest: ${float(coinank.get('open_interest', 0) or 0):,.0f}\n"
                    f"• Funding: {float(coinank.get('funding_rate', 0) or 0):.4f}%\n"
                    f"• Liquidations: ${float(coinank.get('liquidation_volume', 0) or 0):,.0f}"
                )
            
            # Tokenmetrics
            tm = reasoning.get('tokenmetrics_data', {})
            if tm and isinstance(tm, dict):
                sections.append(
                    f"🔍 <b>TOKENMETRICS ANALYSIS</b>\n"
                    f"• Price Score: {float(tm.get('price_score', 0) or 0):.1f}/10\n"
                    f"• Tech Score: {float(tm.get('tech_score', 0) or 0):.1f}/10\n"
                    f"• Grade: {tm.get('trader_grade', 'Unknown')}\n"
                    f"• Risk: {tm.get('risk_level', 'Unknown')}"
                )
            
            # Risk Assessment
            risk_factors = []
            if confidence < 80:
                risk_factors.append(f"Moderate confidence ({confidence:.1f}%)")
            
            rf = reasoning.get('risk_factors', [])
            if rf and isinstance(rf, list):
                risk_factors.extend(rf)
            
            if risk_factors:
                sections.append(
                    f"🎯 <b>RISK ASSESSMENT</b>\n" + 
                    "\n".join([f"• {factor}" for factor in risk_factors])
                )
            
            # AI Reasoning
            decision_logic = reasoning.get('decision_logic', '')
            if decision_logic and isinstance(decision_logic, str):
                sections.append(
                    f"💡 <b>AI REASONING</b>\n{decision_logic}"
                )
            
            # Execution Plan
            ep = reasoning.get('execution_plan', {})
            if ep and isinstance(ep, dict):
                sections.append(
                    f"⚡ <b>EXECUTION PLAN</b>\n"
                    f"• Entry: ${ep.get('entry_zone', 'Unknown')}\n"
                    f"• Stop: ${ep.get('stop_loss', 'Unknown')}\n"
                    f"• Target: ${ep.get('take_profit', 'Unknown')}\n"
                    f"• Size: {ep.get('position_size', 'Unknown')}"
                )
            
            # Combine sections
            formatted_message = header + "\n\n".join(sections)
            
            # Footer
            footer = f"\n\n{'='*30}\n"
            footer += f"🎯 Confidence: <b>{confidence:.1f}%</b>\n"
            footer += f"{action_emoji} Action: <b>{action}</b>\n"
            footer += f"📱 AI Trading Bot"
            
            return formatted_message + footer
            
        except Exception as e:
            logger.error(f"Error formatting signal: {e}")
            action_emoji = '📊'  # Default emoji in case of error
            return f"🤖 <b>AI TRADE SIGNAL</b>\n{symbol} | {action_emoji} {action} | {confidence:.1f}%"
    
    def _format_trade_execution(self, execution_data: Dict[str, Any]) -> str:
        """Format trade execution notification - COMPACT VERSION"""
        try:
            # Type safety
            if not isinstance(execution_data, dict):
                logger.error(f"execution_data is not a dict, got {type(execution_data)}")
                return f"💱 <b>TRADE EXECUTED</b>\n⚠️ Invalid data\n⏰ {datetime.now().strftime('%H:%M:%S')}"

            # Guardrail B: if producer passes a nested 'order' dict, merge its
            # fields shallowly into the root so fill-proof fields are always
            # available at the top level regardless of producer style.
            _nested_order = execution_data.get('order')
            if isinstance(_nested_order, dict):
                for k, v in _nested_order.items():
                    if k not in execution_data or execution_data[k] in (None, '', 0, 0.0):
                        execution_data[k] = v

            # Extract core data
            symbol = self._format_symbol_display(execution_data.get('symbol', 'UNKNOWN'))
            action = str(execution_data.get('action', '')).upper()
            quantity = float(execution_data.get('quantity', 0) or 0)
            confidence = float(execution_data.get('confidence', 0) or 0)
            # Allow callers to pass 0-1 or 0-100
            if 0.0 <= confidence <= 1.0:
                confidence *= 100.0
            leverage = int(execution_data.get('leverage', 10) or 10)
            position_size_pct = float(execution_data.get('position_size_pct', 0) or 0)

            # ── 3-STATE EXECUTION CLASSIFIER ──────────────────────────
            # FILLED   = exchange acknowledged AND has fill data
            # PLACED   = exchange acknowledged (orderId) but no fill yet
            # BLOCKED  = no exchange interaction at all
            # NOTE: Binance returns avgPrice/executedQty as STRINGS — safe-coerce.
            def _safe_float(v):
                try:
                    return float(v) if v not in (None, "") else 0.0
                except (ValueError, TypeError):
                    return 0.0
            _exec_qty = _safe_float(execution_data.get('executedQty') or execution_data.get('executed_qty'))
            _avg_price = _safe_float(execution_data.get('avgPrice') or execution_data.get('avg_price'))
            _order_id = execution_data.get('order_id') or execution_data.get('orderId')
            if _exec_qty > 0 and _avg_price > 0:
                _exec_state = "FILLED"          # confirmed fill
            elif _order_id:
                _exec_state = "ORDER_PLACED"    # ack'd but not yet filled (maker-first)
            else:
                _exec_state = "BLOCKED"         # no exchange interaction

            # 4th state: NOOP for idempotent closes (no position to close)
            # state_hint='NOOP' is an authoritative override from the producer
            if (
                str(execution_data.get('state_hint', '')).upper() == 'NOOP'
                or (
                    _exec_state == "BLOCKED" and (
                        str(execution_data.get('order_type', '')).upper() == 'IDEMPOTENT'
                        or str(execution_data.get('execution_path', '')).lower() == 'idempotent_no_position'
                    )
                )
            ):
                _exec_state = "NOOP"

            # ── SAFETY NET: Never format individual BLOCKED alerts ────
            # All BLOCKED trades should go through the 30-min summary buffer.
            # This is the last line of defense if a caller bypasses the buffer.
            if _exec_state == "BLOCKED":
                logger.debug(
                    "FMT_BLOCKED_SUPPRESSED | symbol=%s | action=%s",
                    execution_data.get("symbol"), action,
                )
                return None  # Callers must handle None → skip send

            # Suppress "NOOP / ALREADY FLAT" alerts when there's no meaningful
            # execution payload (zero qty, zero price, zero notional/margin).
            # These are operationally noisy and provide no actionable info.
            if _exec_state == "NOOP":
                try:
                    _q0 = float(execution_data.get("quantity", 0) or 0.0)
                except Exception:
                    _q0 = 0.0
                try:
                    _ep0 = float(execution_data.get("entry_price", 0) or 0.0)
                except Exception:
                    _ep0 = 0.0
                try:
                    _xp0 = float(execution_data.get("exit_price", 0) or 0.0)
                except Exception:
                    _xp0 = 0.0
                try:
                    _mg0 = float(execution_data.get("margin_usd", 0) or 0.0)
                except Exception:
                    _mg0 = 0.0
                try:
                    _no0 = float(execution_data.get("notional_usd", 0) or 0.0)
                except Exception:
                    _no0 = 0.0
                if (
                    _q0 <= 0.0
                    and _exec_qty <= 0.0
                    and _avg_price <= 0.0
                    and _ep0 <= 0.0
                    and _xp0 <= 0.0
                    and _mg0 <= 0.0
                    and _no0 <= 0.0
                ):
                    logger.info(
                        "TG_NOOP_SUPPRESS_EMPTY | symbol=%s | action=%s",
                        execution_data.get("symbol"),
                        action,
                    )
                    return None

            # Price data
            entry_price = float(execution_data.get('entry_price', 0) or 0)
            exit_price = float(execution_data.get('exit_price', 0) or 0)
            price = exit_price if exit_price > 0 else entry_price

            # Optional signal context
            try:
                current_price = float(execution_data.get('current_price', 0) or 0)
            except Exception:
                current_price = 0.0
            if current_price <= 0 and price > 0:
                current_price = price

            price_target = execution_data.get('price_target')
            price_target_pct = execution_data.get('price_target_pct')
            price_target_direction = str(execution_data.get('price_target_direction', '') or '').upper() or None
            price_target_basis = execution_data.get('price_target_basis')
            try:
                price_target = float(price_target) if price_target not in (None, "") else None
            except Exception:
                price_target = None
            try:
                price_target_pct = float(price_target_pct) if price_target_pct not in (None, "") else None
            except Exception:
                price_target_pct = None
            
            # Portfolio data
            portfolio_balance = float(execution_data.get('balance', 0) or 0)
            equity = float(execution_data.get('equity', 0) or 0)
            # If equity not provided, try to get it from account-specific fields
            if equity <= 0:
                equity = float(execution_data.get('account_equity', 0) or 0)
            if equity <= 0:
                equity = portfolio_balance
            margin_used_pct = float(execution_data.get('margin_used_pct', 0) or 0)
            
            # Trade value and margin calculation
            try:
                notional_value = float(execution_data.get('notional_usd')) if execution_data.get('notional_usd') is not None else None
            except Exception:
                notional_value = None
            if notional_value is None:
                notional_value = quantity * price if price > 0 else 0
            try:
                margin_usd = float(execution_data.get('margin_usd')) if execution_data.get('margin_usd') is not None else None
            except Exception:
                margin_usd = None
            if margin_usd is None:
                margin_usd = notional_value / leverage if leverage > 0 else 0
            
            # Account identification - map account IDs to display names
            account_id = str(execution_data.get('account_id', '') or '').strip().lower()
            if account_id in ('primary', 'wajid', '') or not account_id:
                account_name = "WAJID"
            elif account_id == 'asjad':
                account_name = "ASJAD"
            else:
                account_name = account_id.upper()
            
            # Action classification
            is_entry = 'OPEN' in action or 'INCREASE' in action
            is_exit = any(x in action for x in ['CLOSE', 'DECREASE', 'TAKE_PROFIT', 'STOP_LOSS', 'TRAIL', 'EXIT'])
            
            # Action emoji
            action_emojis = {
                'OPEN_LONG': '🟢', 'OPEN_SHORT': '🔴',
                'INCREASE_LONG': '🟢⬆️', 'INCREASE_SHORT': '🔴⬇️',
                'OPEN_HEDGE_LONG': '🛡️🟢', 'OPEN_HEDGE_SHORT': '🛡️🔴',
                'ADD_HEDGE_LONG': '🛡️🟢⬆️', 'ADD_HEDGE_SHORT': '🛡️🔴⬇️',
                'SCALE_HEDGE': '🛡️⬆️', 'UNWIND_HEDGE': '🛡️📤', 'REBALANCE_HEDGE': '🛡️⚖️',
                'CLOSE_LONG': '📤', 'CLOSE_SHORT': '📤',
                'CLOSE_ALL': '🚪', 'DECREASE_LONG': '📉', 'DECREASE_SHORT': '📉',
                'TAKE_PROFIT_LONG': '💰', 'TAKE_PROFIT_SHORT': '💰',
                'STOP_LOSS_LONG': '🛑', 'STOP_LOSS_SHORT': '🛑',
            }
            action_emoji = action_emojis.get(action, '💱')
            
            # Hedge leg indicator
            is_hedge = (
                bool(execution_data.get('is_hedge', False))
                or bool(execution_data.get('hedge_leg', False))
                or (str(execution_data.get('leg_role') or '').upper() == 'HEDGE')
                or ("HEDGE" in str(action or '').upper())
                or (str(execution_data.get("action_category") or "").strip().upper() == "HEDGE")
            )
            hedge_tag = " | 🛡️ HEDGE" if is_hedge else ""
            
            # Execution details
            order_type = str(execution_data.get('order_type', 'LIMIT')).upper()
            order_id = str(execution_data.get('order_id', ''))
            exec_type = "MAKER" if order_type in ['LIMIT', 'GTX', 'POST_ONLY'] else "TAKER"
            
            # Volatility from market regime
            market_regime = execution_data.get('market_regime_info', {}) or {}
            volatility = float(market_regime.get('volatility', 0) or 0) if isinstance(market_regime, dict) else 0
            vol_label = "HIGH" if volatility > 0.02 else "MODERATE" if volatility > 0.01 else "LOW"
            
            # Format numbers — precision-aware for tiny-price symbols
            def fmt_price(p):
                if p >= 1000: return f"${p:,.2f}"
                elif p >= 1: return f"${p:.4f}"
                elif p >= 0.01: return f"${p:.6f}"
                elif p >= 0.0001: return f"${p:.8f}"
                elif p > 0: return f"${p:.10f}"
                else: return "$0"
            
            def fmt_usd(v):
                if v >= 1000: return f"${v:,.0f}"
                else: return f"${v:.2f}"
            
            # Build compact message — 4-state title
            lines = []
            if _exec_state == "FILLED":
                lines.append(f"💱 <b>TRADE EXECUTED</b> (🔴 LIVE)")
            elif _exec_state == "ORDER_PLACED":
                lines.append(f"📋 <b>ORDER PLACED</b> (🔴 LIVE)")
            elif _exec_state == "NOOP":
                lines.append(f"✅ <b>NOOP / ALREADY FLAT</b> (🔴 LIVE)")
            else:
                lines.append(f"🚫 <b>TRADE BLOCKED</b> (🔴 LIVE)")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"👤 {account_name} | {action_emoji} {action}")
            lines.append(f"📊 {symbol}{hedge_tag}")
            lines.append("")
            
            # ------------------------------------------------------------------
            # Provenance / Attribution (why did this trade happen?)
            # ------------------------------------------------------------------
            src = str(execution_data.get("source") or execution_data.get("producer") or "").strip()
            model = str(execution_data.get("model") or "").strip()
            cat = str(execution_data.get("action_category") or "").strip()
            meta = execution_data.get("metadata") if isinstance(execution_data.get("metadata"), dict) else {}
            tf = str(
                execution_data.get("timeframe")
                or execution_data.get("tf")
                or meta.get("timeframe")
                or meta.get("tf")
                or meta.get("interval")
                or ""
            ).strip()
            sid = str(
                execution_data.get("signal_id")
                or meta.get("signal_id")
                or meta.get("id")
                or meta.get("_proposal_id")
                or ""
            ).strip()
            ppo_c = execution_data.get("ppo_confidence")
            masa_c = execution_data.get("masa_confidence")

            # Operator policy context (if available)
            op_meta = execution_data.get("operator_policy") if isinstance(execution_data.get("operator_policy"), dict) else {}
            if not op_meta and isinstance(meta, dict):
                op_meta = meta.get("operator_policy") if isinstance(meta.get("operator_policy"), dict) else {}

            if src or model or cat or tf or sid:
                who_bits = []
                if src:
                    who_bits.append(f"src={src}")
                if model:
                    who_bits.append(f"model={model}")
                if cat:
                    who_bits.append(f"cat={cat}")
                if tf:
                    who_bits.append(f"tf={tf}")
                if sid:
                    who_bits.append(f"id={sid[:8]}")
                lines.append("🧠 <b>Trigger</b>: " + " | ".join(who_bits))
                # Optional PPO/MASA breakdown
                try:
                    if ppo_c is not None or masa_c is not None:
                        ppo_f = float(ppo_c) if ppo_c is not None else None
                        masa_f = float(masa_c) if masa_c is not None else None
                        parts = []
                        if ppo_f is not None:
                            parts.append(f"PPO={ppo_f:.3f}")
                        if masa_f is not None:
                            parts.append(f"MASA={masa_f:.3f}")
                        if parts:
                            lines.append("🧪 <b>Model</b>: " + " | ".join(parts))
                except Exception:
                    pass
                lines.append("")

            # ------------------------------------------------------------------
            # Policy Context (stress / liq / shock-state from orchestrator)
            # ------------------------------------------------------------------
            if isinstance(op_meta, dict) and op_meta:
                try:
                    liq_bps = op_meta.get("liq_bps")
                    liq_band = str(op_meta.get("liq_band") or "").upper()
                    stress = op_meta.get("stress")
                    vel15 = op_meta.get("vel_15_bps")
                    vel60 = op_meta.get("vel_60_bps")
                    signed15 = op_meta.get("signed_15_bps")
                    signed60 = op_meta.get("signed_60_bps")
                    fms = op_meta.get("fast_move_score")
                    cov = op_meta.get("coverage_ratio")
                    cov_band = op_meta.get("coverage_band") if isinstance(op_meta.get("coverage_band"), dict) else {}
                    htf_aligned_known = bool(op_meta.get("htf_aligned_known"))
                    htf_aligned = bool(op_meta.get("htf_aligned")) if htf_aligned_known else None

                    shock = op_meta.get("shock_state") if isinstance(op_meta.get("shock_state"), dict) else {}
                    shock_name = str(shock.get("state") or "NORMAL").upper()
                    reversal_to = str(shock.get("reversal_to") or "").upper()

                    p_stress = op_meta.get("portfolio_stress") if isinstance(op_meta.get("portfolio_stress"), dict) else {}
                    p_active = bool(p_stress.get("active"))
                    p_stressed = p_stress.get("symbols_stressed")
                    p_total = p_stress.get("symbols_total")

                    policy_bits = []
                    if liq_bps is not None:
                        try:
                            policy_bits.append(f"liq={float(liq_bps):.1f}bps/{liq_band or 'NA'}")
                        except Exception:
                            pass
                    if stress is not None:
                        policy_bits.append(f"stress={'ON' if bool(stress) else 'OFF'}")
                    if shock_name:
                        shock_txt = shock_name
                        if reversal_to:
                            shock_txt += f"→{reversal_to}"
                        policy_bits.append(f"shock={shock_txt}")
                    if htf_aligned is not None:
                        policy_bits.append(f"htf={'ALIGNED' if htf_aligned else 'UNALIGNED'}")
                    if cov is not None:
                        try:
                            cov_txt = f"cov={float(cov):.2f}"
                            cmin = cov_band.get("min")
                            cmax = cov_band.get("max")
                            if cmin is not None and cmax is not None:
                                cov_txt += f"[{float(cmin):.2f}-{float(cmax):.2f}]"
                            policy_bits.append(cov_txt)
                        except Exception:
                            pass
                    if p_stressed is not None and p_total is not None:
                        policy_bits.append(f"pf_stress={'ON' if p_active else 'OFF'}({p_stressed}/{p_total})")
                    if policy_bits:
                        lines.append("🛡️ <b>Policy</b>: " + " | ".join(policy_bits))

                    micro_bits = []
                    if vel15 is not None:
                        micro_bits.append(f"v15={float(vel15):.1f}bps")
                    if vel60 is not None:
                        micro_bits.append(f"v60={float(vel60):.1f}bps")
                    if signed15 is not None:
                        micro_bits.append(f"s15={float(signed15):+.1f}bps")
                    if signed60 is not None:
                        micro_bits.append(f"s60={float(signed60):+.1f}bps")
                    if fms is not None:
                        micro_bits.append(f"fms={float(fms):.2f}")
                    if micro_bits:
                        lines.append("🧪 <b>Micro</b>: " + " | ".join(micro_bits))
                except Exception:
                    pass

            if lines and lines[-1] != "":
                lines.append("")
            
            if is_entry:
                lines.append("💰 <b>Entry:</b>")
                lines.append(f"  • Price: {fmt_price(price)}")
                if current_price > 0:
                    lines.append(f"  • Signal price: {fmt_price(current_price)}")
                lines.append(f"  • Qty: {quantity:.4f} (margin: {fmt_usd(margin_usd)})")
                lines.append(f"  • Leverage: {leverage}× → notional {fmt_usd(notional_value)}")
                if position_size_pct > 0:
                    lines.append(f"  • Size: {position_size_pct:.1f}% of portfolio")
                if price_target is not None and price_target_direction:
                    pct_txt = ""
                    if price_target_pct is not None:
                        pct_val = (price_target_pct * 100.0) if 0.0 <= price_target_pct <= 1.0 else price_target_pct
                        pct_txt = f" ({pct_val:.2f}%)"
                    basis_txt = f" [{price_target_basis}]" if price_target_basis else ""
                    lines.append(f"  • Predicted: {price_target_direction} → {fmt_price(price_target)}{pct_txt}{basis_txt}")
            elif is_exit:
                # Support both field names: realized_pnl/pnl and pnl_percent/pnl_pct
                # Use explicit None-checks instead of truthy `or` to handle 0.0 correctly
                _rpnl = execution_data.get('realized_pnl')
                _pnl = execution_data.get('pnl')
                pnl = float(_rpnl if _rpnl is not None else (_pnl if _pnl is not None else 0))
                _rpct = execution_data.get('pnl_percent')
                _ppct = execution_data.get('pnl_pct')
                pnl_pct = float(_rpct if _rpct is not None else (_ppct if _ppct is not None else 0))
                exit_reason = execution_data.get('exit_reason', '') or execution_data.get('reason', '')
                
                lines.append("💰 <b>Exit:</b>")
                lines.append(f"  • Price: {fmt_price(price)}")
                # For exits: show entry price (where position was opened) for context.
                # "Signal price" = current_price typically falls back to exit_price
                # for close trades, making it identical to Price — not useful.
                if entry_price > 0 and abs(entry_price - price) > 0.001:
                    lines.append(f"  • Entry price: {fmt_price(entry_price)}")
                elif current_price > 0 and abs(current_price - price) > 1e-6:
                    lines.append(f"  • Signal price: {fmt_price(current_price)}")
                lines.append(f"  • Qty: {quantity:.4f} (margin: {fmt_usd(margin_usd)})")
                pnl_emoji = "✅" if pnl >= 0 else "❌"
                lines.append(f"  • PnL: {pnl_emoji} {fmt_usd(pnl)} ({pnl_pct:+.2f}%)")
                if exit_reason:
                    lines.append(f"  • Reason: {exit_reason}")
                # Recovery / trim explanation (numbers)
                try:
                    if bool(execution_data.get("recovery_rebalance")) or str(execution_data.get("source") or "").lower() == "corrective_recovery":
                        b_sym = execution_data.get("recovery_blocked_symbol")
                        b_act = execution_data.get("recovery_blocked_action")
                        b_reason = execution_data.get("recovery_block_reason")
                        need_usd = execution_data.get("recovery_needed_margin_usd")
                        cand_margin = execution_data.get("recovery_candidate_margin_usd")
                        est_pnl_usd = execution_data.get("recovery_est_unrealized_pnl_usd")
                        est_pnl_pct = execution_data.get("recovery_est_pnl_pct")
                        bits = []
                        if b_sym or b_act or b_reason:
                            bits.append(f"blocked={str(b_sym or '')}:{str(b_act or '')} ({str(b_reason or '')})")
                        if need_usd not in (None, "", 0, 0.0):
                            bits.append(f"need≈{fmt_usd(float(need_usd))}")
                        if cand_margin not in (None, "", 0, 0.0):
                            bits.append(f"cand_margin≈{fmt_usd(float(cand_margin))}")
                        if est_pnl_usd not in (None, "", 0, 0.0) or est_pnl_pct not in (None, "", 0, 0.0):
                            try:
                                bits.append(f"est_pnl≈{fmt_usd(float(est_pnl_usd or 0.0))} ({float(est_pnl_pct or 0.0):+.2f}%)")
                            except Exception:
                                pass
                        if bits:
                            lines.append("🧯 <b>Recovery</b>: " + " | ".join(bits))
                except Exception:
                    pass
                try:
                    if str(execution_data.get("source") or "").lower() == "profit_funded_trim":
                        c_use = execution_data.get("trim_credit_used_usd")
                        exp_loss = execution_data.get("trim_expected_loss_usd")
                        p_sym = execution_data.get("trim_profit_symbol")
                        bits = []
                        if p_sym:
                            bits.append(f"from={str(p_sym)}")
                        if c_use not in (None, "", 0, 0.0):
                            bits.append(f"credit={fmt_usd(float(c_use))}")
                        if exp_loss not in (None, "", 0, 0.0):
                            bits.append(f"expected_loss≈{fmt_usd(float(exp_loss))}")
                        if bits:
                            lines.append("💳 <b>Profit-funded</b>: " + " | ".join(bits))
                except Exception:
                    pass
                if price_target is not None and price_target_direction:
                    pct_txt = ""
                    if price_target_pct is not None:
                        pct_val = (price_target_pct * 100.0) if 0.0 <= price_target_pct <= 1.0 else price_target_pct
                        pct_txt = f" ({pct_val:.2f}%)"
                    basis_txt = f" [{price_target_basis}]" if price_target_basis else ""
                    lines.append(f"  • Predicted: {price_target_direction} → {fmt_price(price_target)}{pct_txt}{basis_txt}")
            else:
                lines.append(f"💰 Price: {fmt_price(price)} | Qty: {quantity:.4f}")
            
            lines.append("")
            
            # Execution info
            # Execution info — use normalized _order_id from 3-state classifier
            _oid_display = str(_order_id or '') if _order_id else ''
            if _oid_display:
                lines.append(f"⚡ Exec: {exec_type} | {_exec_state} | #{_oid_display[-12:]}")
            else:
                lines.append(f"⚡ Exec: {exec_type} | {_exec_state}")

            if notional_value and float(notional_value) > 0:
                fee_txt = ""
                try:
                    fee_val = execution_data.get('fee_usd')
                    if fee_val not in (None, ""):
                        fee_txt = f" | fee={fmt_usd(float(fee_val))}"
                except Exception:
                    fee_txt = ""
                lines.append(f"🧾 Notional: {fmt_usd(float(notional_value))}{fee_txt}")
            
            # Portfolio summary
            if equity > 0:
                margin_str = f" | {margin_used_pct:.1f}% margin" if margin_used_pct > 0 else ""
                lines.append(f"💼 Portfolio: {fmt_usd(equity)} equity{margin_str}")
            
            # Confidence and volatility
            if confidence > 0:
                lines.append(f"📈 Conf: {confidence:.1f}% | Vol: {vol_label}")
            
            lines.append(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            
            return "\n".join(lines)
            
        except Exception as e:
            import traceback
            logger.error(f"Error formatting execution: {e}\n{traceback.format_exc()}")
            # Minimal fallback — NEVER crash the notifier
            try:
                symbol = str(execution_data.get('symbol', 'UNKNOWN') if isinstance(execution_data, dict) else 'UNKNOWN')
                action = str(execution_data.get('action', 'UNKNOWN') if isinstance(execution_data, dict) else 'UNKNOWN')
                conf = float(execution_data.get('confidence', 0) if isinstance(execution_data, dict) else 0)
            except:
                symbol, action, conf = 'UNKNOWN', 'UNKNOWN', 0
            # Truncated raw dict for debugging (safe)
            raw_snip = ""
            try:
                if isinstance(execution_data, dict):
                    raw_snip = f"\n🔍 <code>{str(execution_data)[:300]}</code>"
            except:
                raw_snip = ""
            return (
                f"⚠️ <b>TRADE EVENT (FORMAT ERROR)</b>\n"
                f"📊 {symbol} | {action}\n"
                f"📈 Conf: {conf:.1f}%\n"
                f"⏰ {datetime.now().strftime('%H:%M:%S')}"
                f"{raw_snip}"
            )
    
    async def send_signal_alert(self, signal_data: Dict[str, Any]) -> bool:
        """Send trade signal alert to channel"""
        try:
            if signal_data:
                kind = self._tg_kind_from_payload(signal_data)
                if kind:
                    return await self.send_tg(kind, signal_data)
            message = self._format_trade_signal(signal_data)
            success = await self._send_message(self.channel_id, message)
            
            if success:
                logger.info(f"✅ Signal alert sent: {signal_data.get('symbol')} {signal_data.get('action')}")
                
            return success
            
        except Exception as e:
            logger.error(f"Error sending signal alert: {e}")
            return False
    
    async def send_execution_alert(self, execution_data: Dict[str, Any]) -> bool:
        """Send trade execution alert"""
        try:
            # Buffer BLOCKED trades into 30-min summary (same as send_trade_execution)
            if self._is_blocked_payload(execution_data):
                self._blocked_buffer.append(dict(execution_data))
                logger.debug(
                    "TG_EXEC_ALERT_BLOCKED_BUFFERED | symbol=%s | action=%s",
                    execution_data.get("symbol"),
                    execution_data.get("action") or execution_data.get("action_name"),
                )
                await self.flush_blocked_summary()
                return True

            message = self._format_trade_execution(execution_data)
            # Safety net: _format_trade_execution returns None for BLOCKED
            if message is None:
                return True
            
            # Send to both destinations
            tasks = [
                self._send_message(self.bot_chat_id, message),
                self._send_message(self.channel_id, message)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for result in results if result is True)
            
            if success_count > 0:
                logger.info(f"✅ Execution alert sent to {success_count}/2 destinations")
                return True
            else:
                logger.error("❌ Failed to send execution alert")
                return False
                
        except Exception as e:
            logger.error(f"Error sending execution alert: {e}")
            return False
    
    async def send_system_alert(self, message: str, alert_type: str = "INFO") -> bool:
        """Send system alert to both bot chat and channel"""
        try:
            emoji_map = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "SUCCESS": "✅", "CRITICAL": "🚨"}
            emoji = emoji_map.get(alert_type.upper(), "📱")
            
            formatted_message = f"{emoji} <b>SYSTEM ALERT</b>\n\n{message}\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Send to bot chat first
            bot_success = await self._send_message(self.bot_chat_id, formatted_message)
            
            # Also send to channel for system-wide alerts
            channel_success = True
            if self.channel_id and self.channel_id != self.bot_chat_id:
                channel_message = f"{emoji} <b>SYSTEM STATUS</b>\n\n{message}\n\n📱 AI Trading Bot | ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                channel_success = await self._send_message(self.channel_id, channel_message)
            
            return bot_success and channel_success
            
        except Exception as e:
            logger.error(f"Error sending system alert: {e}")
            return False
    
    async def send_announcement(self, title: str, content: str) -> bool:
        """Send announcement to channel"""
        try:
            announcement = f"📢 <b>{title}</b>\n{'='*40}\n\n{content}\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📱 AI Trading Bot"
            return await self._send_message(self.channel_id, announcement)
            
        except Exception as e:
            logger.error(f"Error sending announcement: {e}")
            return False
    
    async def send_portfolio_alert(self, message: str, parse_mode: str = "HTML", media_paths: Optional[List[str]] = None) -> bool:
        """Send portfolio summary alerts to dedicated portfolio channel"""
        try:
            # Intentionally send text-only: Telegram photo/media shows as a header image.
            # Keep formatting unchanged by using sendMessage only.
            return await self._send_message(self.portfolio_channel_id, message, parse_mode)
        except Exception as e:
            logger.error(f"Error sending portfolio alert: {e}")
            return False
    
    async def send_trade_alert(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send trade execution alerts to dedicated trade channel"""
        try:
            return await self._send_message(self.trade_channel_id, message, parse_mode)
        except Exception as e:
            logger.error(f"Error sending trade alert: {e}")
            return False
    
    async def send_ai_signal_alert(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send AI signal alerts to dedicated AI signals channel"""
        try:
            return await self._send_message(self.ai_signals_channel_id, message, parse_mode)
        except Exception as e:
            logger.error(f"Error sending AI signal alert: {e}")
            return False
    
    async def send_channel_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send to main channel (for backwards compatibility)"""
        try:
            return await self._send_message(self.channel_id, message, parse_mode)
        except Exception as e:
            logger.error(f"Error sending channel message: {e}")
            return False

    async def send_message(self, message: str, parse_mode: str = "HTML", forward_to_private: bool = False) -> bool:
        """
        Public send_message method for backward compatibility
        
        Args:
            message: Message text to send
            parse_mode: Telegram parse mode (HTML, Markdown, etc.)
            forward_to_private: If True, send to both bot chat and channel
        
        Returns:
            bool: True if message was sent successfully
        """
        try:
            if forward_to_private:
                # Send to both bot chat and channel
                tasks = [
                    self._send_message(self.bot_chat_id, message, parse_mode),
                    self._send_message(self.channel_id, message, parse_mode)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                success_count = sum(1 for result in results if result is True)
                return success_count > 0
            else:
                # Send to channel only
                return await self._send_message(self.channel_id, message, parse_mode)
                
        except Exception as e:
            logger.error(f"Error in send_message: {e}")
            return False

    def send_message_sync(self, message: str, parse_mode: str = "HTML", forward_to_private: bool = False) -> bool:
        """
        Synchronous-safe wrapper for send_message().
        
        Many parts of the trading system are synchronous (threads, websocket callbacks).
        Calling the async send_message() directly from sync code produces:
            RuntimeWarning: coroutine 'TelegramNotifier.send_message' was never awaited
        
        This helper:
        - schedules the coroutine if we're already inside a running event loop
        - otherwise runs it via asyncio.run()
        """
        try:
            coro = self.send_message(message, parse_mode=parse_mode, forward_to_private=forward_to_private)
        except Exception as e:
            logger.debug(f"[TELEGRAM] send_message_sync build coroutine failed: {e}")
            return False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        # If an event loop is already running in this thread, fire-and-forget.
        if loop and loop.is_running():
            try:
                loop.create_task(coro)
                return True
            except Exception as e:
                logger.debug(f"[TELEGRAM] send_message_sync create_task failed: {e}")
                return False

        # Otherwise, run the coroutine to completion.
        try:
            return bool(asyncio.run(coro))
        except Exception as e:
            logger.debug(f"[TELEGRAM] send_message_sync asyncio.run failed: {e}")
            return False
    
    async def send_portfolio_summary(self, portfolio_data: Dict[str, Any] = None, **kwargs) -> bool:
        """Send portfolio summary to portfolio channel (wrapper for compatibility)"""
        try:
            # Support both dictionary and keyword argument formats
            if portfolio_data is None and kwargs:
                portfolio_data = kwargs

            if portfolio_data:
                kind = self._tg_kind_from_payload(portfolio_data)
                if kind:
                    return await self.send_tg(kind, portfolio_data)
                # Get account name and mode
                account_name = portfolio_data.get('account_name', 'UNKNOWN').upper()
                mode_emoji = "🔴"
                mode_text = "LIVE TRADING"
                
                # Format comprehensive portfolio message with account name
                message = f"💼 {mode_emoji} <b>BINANCE {mode_text} PORTFOLIO SUMMARY</b>\n"
                message += f"👤 <b>ACCOUNT: {account_name}</b>\n"
                message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                message += f"{'═'*35}\n\n"

                total_value = portfolio_data.get('total_value', portfolio_data.get('total_balance', 0))
                available = portfolio_data.get('available', portfolio_data.get('available_balance', 0))
                total_pnl = portfolio_data.get('total_pnl', portfolio_data.get('unrealized_pnl', 0))
                total_pnl_pct = portfolio_data.get('total_pnl_pct', portfolio_data.get('pnl_percentage', 0))
                
                pnl_emoji = "💚" if total_pnl > 0 else "🔴" if total_pnl < 0 else "⚪"
                return_emoji = "🟢" if total_pnl_pct >= 0 else "🔴"
                
                message += f"💰 Total Balance: <b>${total_value:,.2f}</b>\n"
                message += f"💵 Available: <b>${available:,.2f}</b>\n"
                message += f"📈 Unrealized PnL: <b>${total_pnl:+,.2f}</b>\n"
                message += f"{return_emoji} Return: <b>{total_pnl_pct:+.2f}%</b>\n"
                
                # Market conditions for symbols with positions
                market_conditions = portfolio_data.get('market_conditions', {})
                positions = portfolio_data.get('positions', [])
                
                if market_conditions or positions:
                    message += f"\n🌐 <b>Market Conditions:</b>\n"
                    
                    # Show market conditions for each symbol with position
                    symbols_shown = set()
                    for pos in positions:
                        symbol = pos.get('symbol', 'UNKNOWN')
                        if symbol in symbols_shown:
                            continue
                        symbols_shown.add(symbol)
                        
                        # Get market condition for this symbol
                        condition = market_conditions.get(symbol, {})
                        regime = condition.get('regime', 'NORMAL').upper()
                        volatility = condition.get('volatility', 0.5) * 100
                        
                        regime_emoji = "✅" if regime == 'NORMAL' else "⚠️" if 'VOLATILE' in regime else "🚨" if 'CRISIS' in regime else "📊"
                        message += f"{regime_emoji} {symbol}: {regime} (Vol: {volatility:.1f}%)\n"
                
                # Position count
                position_count = len(positions) if positions else 0
                message += f"\n📍 <b>Active Positions:</b> {position_count}\n"
                
                # Detailed positions if requested
                if portfolio_data.get('show_positions', False) and positions:
                    message += f"\n📊 <b>Position Details:</b>\n"
                    for pos in positions:
                        symbol = pos.get('symbol', 'UNKNOWN')
                        side = pos.get('side', 'UNKNOWN')
                        size = pos.get('size', 0)
                        entry_price = pos.get('entry', pos.get('entry_price', 0))
                        current_price = pos.get('current', pos.get('current_price', 0))
                        pnl = pos.get('pnl', pos.get('unrealized_pnl', 0))
                        
                        if current_price and entry_price and entry_price > 0:
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100 if side == 'LONG' else ((entry_price - current_price) / entry_price) * 100
                        else:
                            pnl_pct = 0
                        
                        pos_emoji = "🟢" if side == "LONG" else "🔴"
                        pnl_emoji_pos = "💚" if pnl > 0 else "❤️" if pnl < 0 else "💛"
                        
                        message += f"{pos_emoji} {symbol} {side}: {pnl_emoji_pos} ${pnl:+.2f} ({pnl_pct:+.1f}%)\n"
            else:
                # Simple test message
                message = f"💼 <b>Portfolio Channel Test</b>\n\nPortfolio summary functionality is working!\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            return await self.send_portfolio_alert(message)
        except Exception as e:
            logger.error(f"Error sending portfolio summary: {e}")
            return False
    
    async def send_trade_execution(self, execution_data: Dict[str, Any] = None, signal: Dict[str, Any] = None, execution: Dict[str, Any] = None, **kwargs) -> bool:
        """Send trade execution to trade channel (wrapper for compatibility)"""
        try:
            dedupe_key = None

            # Support both dictionary and keyword argument formats
            if execution_data is None and (signal or kwargs):
                # Merge signal and execution data
                execution_data = {}
                if signal:
                    execution_data.update(signal)
                if execution:
                    execution_data.update(execution)
                if kwargs:
                    execution_data.update(kwargs)
            
            if execution_data:
                # ── BLOCKED-trade batching (FIRST CHECK — before dedup/tg_kind) ──
                # Buffer BLOCKED trades and send a 30-min summary instead of
                # individual alerts.  This must be the very first gate so no
                # downstream path (send_tg, _format_trade_execution) can leak
                # a BLOCKED message.
                if self._is_blocked_payload(execution_data):
                    self._blocked_buffer.append(dict(execution_data))
                    logger.debug(
                        "TG_BLOCKED_BUFFERED | symbol=%s | action=%s | buffer_size=%d",
                        execution_data.get("symbol"),
                        execution_data.get("action") or execution_data.get("action_name"),
                        len(self._blocked_buffer),
                    )
                    await self.flush_blocked_summary()
                    return True

                kind = self._tg_kind_from_payload(execution_data)
                if kind:
                    return await self.send_tg(kind, execution_data)

                # Duplicate suppression across producer paths (trader + monitor)
                dedupe_key = None
                dedupe_ttl_sec = 90  # State-scoped: allows PLACED→FILLED transition
                try:
                    acct = str(execution_data.get("account_id") or execution_data.get("account") or "").strip().lower()
                    sym = str(execution_data.get("symbol") or "").strip().upper()
                    act = str(execution_data.get("action") or execution_data.get("action_name") or "").strip().upper()
                    oid = str(execution_data.get("order_id") or execution_data.get("orderId") or execution_data.get("exchange_order_id") or "").strip()
                    sid = str(execution_data.get("signal_id") or "").strip()
                    # Quick exec-state tag so ORDER_PLACED→FILLED are NOT suppressed
                    def _qs(d):
                        try:
                            def _sf(v):
                                try: return float(v) if v not in (None, "") else 0.0
                                except: return 0.0
                            eq = _sf(d.get('executedQty') or d.get('executed_qty'))
                            ap = _sf(d.get('avgPrice') or d.get('avg_price'))
                            _oi = d.get('order_id') or d.get('orderId')
                            if eq > 0 and ap > 0: return "F"   # FILLED
                            if _oi: return "P"                  # PLACED
                            if str(d.get('order_type', '')).upper() == 'IDEMPOTENT': return "N"  # NOOP
                            return "B"                          # BLOCKED
                        except: return "U"                      # UNKNOWN
                    st = _qs(execution_data)
                    if oid:
                        dedupe_key = f"tg:exec:v3:order:{acct}:{oid}:{st}"
                    elif sid:
                        dedupe_key = f"tg:exec:v3:signal:{acct}:{sid}:{st}"
                    elif acct and sym and act:
                        dedupe_key = f"tg:exec:v3:asa:{acct}:{sym}:{act}:{st}"
                except Exception:
                    dedupe_key = None

                dedupe_reserved = False
                if dedupe_key and self.redis is not None:
                    try:
                        dedupe_reserved = bool(self.redis.set(dedupe_key, "1", ex=dedupe_ttl_sec, nx=True))
                        if not dedupe_reserved:
                            logger.info(
                                "TG_EXEC_DEDUP_SKIP | key=%s | account=%s | symbol=%s | action=%s",
                                dedupe_key,
                                execution_data.get("account_id") or execution_data.get("account"),
                                execution_data.get("symbol"),
                                execution_data.get("action") or execution_data.get("action_name"),
                            )
                            return True
                    except Exception:
                        dedupe_reserved = False

                # (Old inline _is_blocked removed — now handled by
                #  _is_blocked_payload() at the top of this function.)

                message = self._format_trade_execution(execution_data)
                # Safety net: formatter can suppress noisy events (e.g. BLOCKED/empty-NOOP)
                if message is None:
                    logger.debug(
                        "TG_EXEC_FMT_SKIP | symbol=%s | action=%s",
                        execution_data.get("symbol"),
                        execution_data.get("action") or execution_data.get("action_name"),
                    )
                    return True
            else:
                # Simple test message
                message = f"💱 <b>Trade Channel Test</b>\n\nTrade execution functionality is working!\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            icon_path = None
            try:
                icon_path = (execution_data or {}).get("icon_path") or kwargs.get("icon_path")
            except Exception:
                icon_path = None

            # Intentionally send text-only: Telegram photo shows as a header image.
            # Keep formatting unchanged by using sendMessage only.
            sent_ok = await self.send_trade_alert(message)

            # If send failed, release dedupe lock so retry path can alert.
            try:
                if execution_data and (not sent_ok) and dedupe_key and self.redis is not None:
                    self.redis.delete(dedupe_key)
            except Exception:
                pass

            return sent_ok
        except Exception as e:
            logger.error(f"Error sending trade execution: {e}")
            return False
    
    # ── BLOCKED-trade summary flusher ──────────────────────────────
    async def flush_blocked_summary(self, force: bool = False) -> bool:
        """Send a batched summary of blocked trades and clear the buffer.
        Called automatically from send_trade_execution every _blocked_flush_interval
        seconds, or externally via force=True."""
        now = time.time()
        elapsed = now - self._blocked_last_flush_ts
        if not force and elapsed < self._blocked_flush_interval:
            return False  # not time yet
        if not self._blocked_buffer:
            self._blocked_last_flush_ts = now
            return False  # nothing to send

        buf = list(self._blocked_buffer)
        self._blocked_buffer.clear()
        self._blocked_last_flush_ts = now

        # Aggregate by account → symbol → action
        from collections import defaultdict
        agg: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        reasons: Dict[str, set] = defaultdict(set)
        for item in buf:
            acct = str(item.get('account_id') or item.get('account') or 'UNKNOWN').strip().upper()
            if acct in ('PRIMARY', 'WAJID', ''): acct = 'WAJID'
            sym = str(item.get('symbol') or 'UNK').strip().upper()
            act = str(item.get('action') or item.get('action_name') or '').strip().upper()
            key = f"{acct}|{sym}"
            agg[key][act] += 1
            # Collect block reasons if available
            r = str(item.get('reason') or item.get('block_reason') or item.get('skip_reason') or '').strip()
            if r:
                reasons[key].add(r[:60])

        total = len(buf)
        mins = int(elapsed / 60)
        lines = [
            f"🚫 <b>BLOCKED TRADES SUMMARY</b> (last {mins}min)",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Total blocked: <b>{total}</b>",
            "",
        ]
        # Group by account
        acct_groups: Dict[str, list] = defaultdict(list)
        for key, actions in sorted(agg.items()):
            acct, sym = key.split('|', 1)
            action_parts = [f"{act}×{cnt}" for act, cnt in sorted(actions.items())]
            reason_str = ""
            if reasons.get(key):
                reason_str = f" ({', '.join(sorted(reasons[key])[:3])})"
            acct_groups[acct].append(f"  • {sym}: {', '.join(action_parts)}{reason_str}")

        for acct, syms in sorted(acct_groups.items()):
            lines.append(f"👤 <b>{acct}</b>:")
            # Cap display at 15 lines per account
            for s in syms[:15]:
                lines.append(s)
            if len(syms) > 15:
                lines.append(f"  ... +{len(syms)-15} more symbols")
            lines.append("")

        lines.append(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        message = "\n".join(lines)
        try:
            return await self.send_trade_alert(message)
        except Exception as e:
            logger.error(f"flush_blocked_summary send failed: {e}")
            return False

    async def send_ai_signal(self, signal_data: Dict[str, Any] = None, signal: Dict[str, Any] = None, **kwargs) -> bool:
        """Send AI signal to AI signals channel (wrapper for compatibility)"""
        try:
            # Support both dictionary and keyword argument formats
            if signal_data is None and (signal or kwargs):
                signal_data = signal or kwargs
            
            if signal_data:
                kind = self._tg_kind_from_payload(signal_data)
                if kind:
                    return await self.send_tg(kind, signal_data)
                # Check if pre-formatted message is provided
                if 'message' in signal_data:
                    message = signal_data['message']
                else:
                    # Format the message using the old format
                    message = self._format_trade_signal(signal_data)
            else:
                # Simple test message
                message = f"🤖 <b>AI Signals Channel Test</b>\n\nAI signal functionality is working!\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            return await self.send_ai_signal_alert(message)
        except Exception as e:
            logger.error(f"Error sending AI signal: {e}")
            return False

# Utility function for backward compatibility
async def send_telegram_alert(bot_token: str, chat_id: str, message: str) -> bool:
    """Simple utility function"""
    notifier = TelegramNotifier(bot_token, chat_id, chat_id)
    return await notifier.send_system_alert(message)

if __name__ == "__main__":
    print("✅ Telegram alerts module ready")
