#!/usr/bin/env python3
"""
AI Trading System - Telegram Alert Monitor with System Lifecycle Management
===========================================================================
Comprehensive monitoring service that sends Telegram alerts for:
- System startup/shutdown
- Service restarts and failures
- Service hang detection
- Performance issues
- Critical system events
"""

import asyncio
import os
import sys
import time
import json
import redis
import psutil
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from telegram_alerts import TelegramNotifier
from config import get_live_config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SystemMonitor:
    """Comprehensive system monitoring with Telegram alerts"""
    
    def __init__(self):
        self.config = get_live_config()
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        try:
            from config import (
                TELEGRAM_BOT_TOKEN,
                TELEGRAM_CHAT_ID,
                PRIVATE_CHANNEL_ID,
                PORTFOLIO_CHANNEL_ID,
                TRADE_CHANNEL_ID,
                AI_SIGNALS_CHANNEL_ID,
            )
            # Use explicit channel IDs so system alerts and any forwarded messages don't
            # accidentally default AI signals/trade/portfolio to the private channel.
            self.telegram = TelegramNotifier(
                TELEGRAM_BOT_TOKEN,
                TELEGRAM_CHAT_ID,
                PRIVATE_CHANNEL_ID,
                portfolio_channel_id=PORTFOLIO_CHANNEL_ID,
                trade_channel_id=TRADE_CHANNEL_ID,
                ai_signals_channel_id=AI_SIGNALS_CHANNEL_ID,
                redis_client=self.redis_client,
            )
        except Exception as e:
            logger.warning(f"Telegram initialization failed: {e}")
            self.telegram = None
        
        # Service monitoring state
        self.service_states = {}
        self.last_heartbeats = {}
        self.startup_time = datetime.now()
        self.monitoring_active = True

        # Executed signals (authoritative trade execution alerts)
        self.exec_group = "tg_exec"
        self.exec_consumer = f"{os.uname().nodename}-{os.getpid()}"
        self.exec_last_id = "0-0"
        self.trader_last_id = "0-0"
        self.executed_recent = deque(maxlen=2000)
        self.executed_index = {}
        self.ghost_claims = {}
        self.ghost_window_sec = 10

        self._ensure_exec_group()
        
        # System health thresholds
        self.cpu_threshold = 95.0  # Alert if CPU > 95% for extended period
        self.memory_threshold = 90.0  # Alert if memory > 90%
        self.disk_threshold = 85.0  # Alert if disk > 85%
    
    async def safe_telegram_send(self, method_name, *args, **kwargs):
        """Safely send telegram messages with null check"""
        if self.telegram:
            try:
                method = getattr(self.telegram, method_name)
                await method(*args, **kwargs)
            except Exception as e:
                logger.error(f"Telegram {method_name} failed: {e}")
        else:
            logger.warning(f"Telegram not available, skipping {method_name} call")
        
        # Service definitions
        self.monitored_services = {
            'binance': {
                'process_pattern': 'live_binance.py',
                'heartbeat_key': 'heartbeat:BinanceIngestor',
                'max_restart_interval': 300,  # 5 minutes
                'hang_threshold': 600  # 10 minutes without heartbeat
            },
            'binance-liq': {
                'process_pattern': 'live_binance_liquidations.py',
                'heartbeat_key': 'heartbeat:BinanceLiquidationIngestor',
                'max_restart_interval': 300,
                'hang_threshold': 600
            },
            'feature-pipeline': {
                'process_pattern': 'feature_pipeline.py',
                'heartbeat_key': 'heartbeat:FeaturePipeline',
                'max_restart_interval': 180,  # 3 minutes
                'hang_threshold': 300  # 5 minutes without features
            },
            'trainer': {
                # Match both script and module invocation
                'process_pattern': 'rl.hybrid_trainer',
                # Hybrid trainer now emits heartbeats per instance ID (trainer:heartbeat:{id})
                'heartbeat_key': 'trainer:heartbeat:*',
                'max_restart_interval': 600,  # 10 minutes (training takes time)
                'hang_threshold': 1800  # 30 minutes (training can take long)
            },
            'trader': {
                'process_pattern': 'trader.py',
                'heartbeat_key': 'heartbeat:SignalTrader',
                'max_restart_interval': 120,  # 2 minutes
                'hang_threshold': 300  # 5 minutes
            }
        }
        
        logger.info("🔔 System Monitor initialized with Telegram alerts")

    def _ensure_exec_group(self):
        """Ensure executed_signals consumer group exists."""
        try:
            self.redis_client.xgroup_create("executed_signals", self.exec_group, id="$", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e).upper():
                logger.warning(f"executed_signals group init failed: {e}")

    def _extract_payload(self, fields: dict) -> Dict[str, Any]:
        """Extract payload from Redis fields, preferring JSON in 'data'."""
        if not isinstance(fields, dict):
            return {}
        payload = fields
        if 'data' in fields and isinstance(fields['data'], str):
            try:
                payload = json.loads(fields['data'])
            except Exception:
                payload = fields
        return payload if isinstance(payload, dict) else {}

    def _index_executed(self, payload: Dict[str, Any]) -> None:
        """Index recent executed signals for ghost-claim matching."""
        try:
            ts = float(payload.get("timestamp") or 0.0)
        except Exception:
            ts = 0.0
        if not ts:
            try:
                ts = float(payload.get("ts_ms", 0)) / 1000.0
            except Exception:
                ts = time.time()

        order_id = str(payload.get("exchange_order_id") or payload.get("order_id") or "")
        signal_id = str(payload.get("signal_id") or "")
        account_id = str(payload.get("account_id") or payload.get("account") or "")
        symbol = str(payload.get("symbol") or "").upper()
        action = str(payload.get("action") or payload.get("action_name") or "").upper()

        entry = {
            "ts": ts,
            "order_id": order_id,
            "signal_id": signal_id,
            "account_id": account_id,
            "symbol": symbol,
            "action": action,
        }
        self.executed_recent.append(entry)

        if order_id:
            self.executed_index[f"order:{order_id}"] = ts
        if signal_id:
            self.executed_index[f"signal:{signal_id}"] = ts
        if account_id and symbol and action:
            self.executed_index[f"asa:{account_id}:{symbol}:{action}"] = ts

        # cleanup index entries older than 2 minutes
        cutoff = time.time() - 120
        stale_keys = [k for k, v in self.executed_index.items() if v < cutoff]
        for k in stale_keys:
            self.executed_index.pop(k, None)

    def _match_executed(self, claim: Dict[str, Any]) -> bool:
        order_id = str(claim.get("order_id") or "")
        signal_id = str(claim.get("signal_id") or "")
        account_id = str(claim.get("account_id") or "")
        symbol = str(claim.get("symbol") or "")
        action = str(claim.get("action") or "")
        now = time.time()

        if order_id and (now - self.executed_index.get(f"order:{order_id}", 0)) <= self.ghost_window_sec:
            return True
        if signal_id and (now - self.executed_index.get(f"signal:{signal_id}", 0)) <= self.ghost_window_sec:
            return True
        if account_id and symbol and action:
            key = f"asa:{account_id}:{symbol}:{action}"
            if (now - self.executed_index.get(key, 0)) <= self.ghost_window_sec:
                return True
        return False

    def _format_trade_executed(self, payload: Dict[str, Any]) -> str:
        account_id = payload.get("account_id") or payload.get("account") or "unknown"
        symbol = payload.get("symbol", "UNKNOWN")
        action = payload.get("action") or payload.get("action_name") or "UNKNOWN"
        price = payload.get("executed_price")
        qty = payload.get("executed_qty")
        notional = payload.get("notional_usd")
        fee = payload.get("fee_usd")
        liquidity = payload.get("liquidity")
        order_id = payload.get("exchange_order_id") or payload.get("order_id")
        ts_ms = payload.get("ts_ms") or int(time.time() * 1000)
        ts = datetime.fromtimestamp(int(ts_ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")

        return (
            f"📈 <b>TRADE EXECUTED</b> ✅\n\n"
            f"👤 Account: <b>{account_id}</b>\n"
            f"📌 Symbol: <b>{symbol}</b>\n"
            f"⚡ Action: <b>{action}</b>\n"
            f"💵 Price: <b>{price}</b>\n"
            f"📦 Qty: <b>{qty}</b>\n"
            f"💰 Notional: <b>${notional}</b>\n"
            f"🧾 Fee: <b>${fee}</b>\n"
            f"🧭 Liquidity: <b>{liquidity}</b>\n"
            f"🆔 Order ID: <b>{order_id}</b>\n"
            f"⏰ Time: <b>{ts}</b>"
        )

    async def _process_executed_signals(self):
        """Consume executed_signals and emit authoritative TRADE EXECUTED alerts."""
        try:
            streams = {"executed_signals": ">"}
            results = self.redis_client.xreadgroup(
                self.exec_group,
                self.exec_consumer,
                streams,
                count=50,
                block=1000,
            )

            for _stream, messages in results or []:
                for message_id, fields in messages:
                    payload = self._extract_payload(fields)
                    if not payload:
                        self.redis_client.xack("executed_signals", self.exec_group, message_id)
                        continue

                    self._index_executed(payload)

                    # Skip Telegram alerts for FAILURES — only send for successful fills.
                    # The trader already handles direct alerts for filled orders;
                    # sending failure events here produces confusing $0 alerts.
                    _is_success = bool(payload.get("success") or payload.get("executed"))
                    _has_fill = (float(payload.get("executed_qty") or 0) > 0 and float(payload.get("executed_price") or 0) > 0)
                    if not _is_success and not _has_fill:
                        logger.debug(
                            "MONITOR_SKIP_FAILURE_ALERT | symbol=%s | action=%s | error=%s",
                            payload.get("symbol"), payload.get("action"), payload.get("error"),
                        )
                        self.redis_client.xack("executed_signals", self.exec_group, message_id)
                        continue

                    if self.telegram:
                        # Normalize executed_signals payload into unified execution format
                        exec_data = dict(payload)
                        exec_data["action"] = (
                            payload.get("action")
                            or payload.get("action_name")
                            or payload.get("raw_action_name")
                            or "UNKNOWN"
                        )
                        if payload.get("exchange_order_id") and not payload.get("order_id"):
                            exec_data["order_id"] = payload.get("exchange_order_id")
                        if payload.get("executed_qty") is not None and payload.get("quantity") is None:
                            exec_data["quantity"] = payload.get("executed_qty")
                        # Map fill-proof fields so 3-state classifier sees FILLED (not ORDER_PLACED)
                        if payload.get("executed_qty") is not None and exec_data.get("executedQty") is None:
                            exec_data["executedQty"] = payload.get("executed_qty")
                        if payload.get("executed_price") is not None and exec_data.get("avgPrice") is None:
                            exec_data["avgPrice"] = payload.get("executed_price")

                        action_u = str(exec_data.get("action") or "").upper()
                        px = payload.get("executed_price")
                        if px is not None:
                            if any(tok in action_u for tok in ("CLOSE", "DECREASE", "PARTIAL", "EXIT", "TAKE_PROFIT", "STOP_LOSS", "STEALTH_")):
                                exec_data["exit_price"] = px
                                # Carry entry_price for PnL context (where position was opened)
                                ep = payload.get("entry_price")
                                if ep is not None and exec_data.get("entry_price") is None:
                                    try:
                                        exec_data["entry_price"] = float(ep)
                                    except (TypeError, ValueError):
                                        pass
                            else:
                                exec_data["entry_price"] = px

                        # Override pnl/pnl_pct with realized values when the exec_data
                        # currently has 0.0 (default) but a proper realized figure is available.
                        # Use None-or-zero check so we don't lose a legitimately-zero PnL
                        # that was already computed by the caller, but DO override a stale 0.
                        _rpnl = payload.get("realized_pnl_usd")
                        if _rpnl is not None:
                            _cur_pnl = exec_data.get("pnl")
                            if _cur_pnl is None or _cur_pnl == 0:
                                exec_data["pnl"] = _rpnl
                        _rpct = payload.get("realized_pnl_pct")
                        if _rpct is not None:
                            _cur_pct = exec_data.get("pnl_pct")
                            if _cur_pct is None or _cur_pct == 0:
                                exec_data["pnl_pct"] = _rpct

                        # Preserve provenance/category if available
                        if payload.get("source_module") and not exec_data.get("source"):
                            exec_data["source"] = payload.get("source_module")
                        if payload.get("category") and not exec_data.get("action_category"):
                            exec_data["action_category"] = payload.get("category")
                        # Pass-through leverage so Telegram formatter uses actual value
                        if payload.get("leverage") is not None and exec_data.get("leverage") is None:
                            exec_data["leverage"] = payload.get("leverage")

                        await self.telegram.send_trade_execution(exec_data)
                    self.redis_client.xack("executed_signals", self.exec_group, message_id)

        except Exception as e:
            logger.debug(f"executed_signals read error: {e}")

    async def _process_trader_claims(self):
        """Detect non-authoritative execution claims and emit ghost warnings."""
        try:
            trader_signals = self.redis_client.xread(
                {'wma:trader:signals_received': self.trader_last_id},
                count=50,
                block=1000
            )

            for _stream, messages in trader_signals or []:
                for message_id, fields in messages:
                    payload = self._extract_payload(fields)
                    action = str(payload.get("action") or payload.get("action_name") or "").upper()
                    status = str(payload.get("status") or payload.get("order_status") or "").upper()
                    executed_flag = bool(payload.get("executed") or payload.get("filled") or payload.get("success"))

                    if executed_flag or status in ("FILLED", "PARTIALLY_FILLED"):
                        claim = {
                            "account_id": payload.get("account_id") or payload.get("account") or "unknown",
                            "symbol": str(payload.get("symbol") or "").upper(),
                            "action": action,
                            "order_id": payload.get("exchange_order_id") or payload.get("order_id") or payload.get("orderId"),
                            "signal_id": payload.get("signal_id") or payload.get("id"),
                            "raw": payload,
                            "ts": time.time(),
                        }
                        key = f"{claim['account_id']}:{claim['symbol']}:{claim['action']}:{claim.get('order_id') or claim.get('signal_id') or message_id}"
                        self.ghost_claims[key] = claim

                    self.trader_last_id = message_id

        except Exception as e:
            logger.debug(f"trader signals read error: {e}")

        # Emit ghost warnings for expired claims
        now = time.time()
        expired = [k for k, v in self.ghost_claims.items() if now - v.get("ts", now) > self.ghost_window_sec]
        for k in expired:
            claim = self.ghost_claims.pop(k, None)
            if not claim:
                continue
            if self._match_executed(claim):
                continue
            if self.telegram:
                msg = (
                    "⚠️ <b>GHOST EXECUTION WARNING</b>\n\n"
                    f"👤 Account: <b>{claim.get('account_id')}</b>\n"
                    f"📌 Symbol: <b>{claim.get('symbol')}</b>\n"
                    f"⚡ Action: <b>{claim.get('action')}</b>\n"
                    f"🆔 Order ID: <b>{claim.get('order_id')}</b>\n"
                    f"🔎 Reason: <b>no matching executed_signals entry within {self.ghost_window_sec}s</b>"
                )
                await self.telegram.send_system_alert(msg, "WARNING")
    
    async def send_system_startup_alert(self):
        """Send system startup notification"""
        try:
            message = f"""
🚀 <b>AI TRADING SYSTEM STARTED</b>

⏰ Startup Time: {self.startup_time.strftime('%Y-%m-%d %H:%M:%S')}
🖥️  Hostname: {os.uname().nodename}
🐧 OS: {os.uname().sysname} {os.uname().release}
💻 CPU Cores: {psutil.cpu_count()}
🧠 Total Memory: {psutil.virtual_memory().total // (1024**3)}GB

🔄 Starting service monitoring...
📊 All services will be monitored for:
  • Process health and restarts
  • Performance issues
  • Hang detection
  • Critical errors

🎯 <b>TRADING SYSTEM ONLINE</b>
"""
            
            await self.safe_telegram_send('send_message', message.strip())
            logger.info("📡 System startup alert sent")
        except Exception as e:
            logger.error(f"Failed to send startup alert: {e}")
    
    async def send_system_shutdown_alert(self):
        """Send system shutdown notification"""
        try:
            uptime = datetime.now() - self.startup_time
            uptime_str = str(uptime).split('.')[0]  # Remove microseconds
            
            message = f"""
🛑 <b>AI TRADING SYSTEM SHUTDOWN</b>

⏰ Shutdown Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
⏱️  System Uptime: {uptime_str}
🔄 Shutdown Type: Graceful

📊 Final Status Summary:
"""
            
            # Add service status summary
            for service_name in self.monitored_services:
                status = "🟢 Running" if self._is_service_running(service_name) else "🔴 Stopped"
                message += f"  • {service_name}: {status}\n"
            
            message += "\n🎯 <b>SYSTEM OFFLINE</b>"
            
            await self.telegram.send_message(message.strip())
            logger.info("📡 System shutdown alert sent")
        except Exception as e:
            logger.error(f"Failed to send shutdown alert: {e}")
    
    def _is_service_running(self, service_name: str) -> bool:
        """Check if a service is currently running"""
        try:
            pattern = self.monitored_services[service_name]['process_pattern']
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if pattern in cmdline:
                    return True
            return False
        except Exception:
            return False
    
    def _get_service_pid(self, service_name: str) -> Optional[int]:
        """Get PID of a running service"""
        try:
            pattern = self.monitored_services[service_name]['process_pattern']
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if pattern in cmdline:
                    return proc.info['pid']
            return None
        except Exception:
            return None
    
    async def check_service_health(self):
        """Monitor service health and detect issues"""
        try:
            for service_name, config in self.monitored_services.items():
                current_time = time.time()
                
                # Check if service is running
                is_running = self._is_service_running(service_name)
                pid = self._get_service_pid(service_name) if is_running else None
                
                # Track state changes
                previous_state = self.service_states.get(service_name, {})
                previous_running = previous_state.get('running', False)
                previous_pid = previous_state.get('pid', None)
                
                # Detect service restart (PID changed)
                if is_running and previous_running and pid != previous_pid and previous_pid is not None:
                    await self._send_service_restart_alert(service_name, pid, previous_pid)
                
                # Detect service start
                elif is_running and not previous_running:
                    await self._send_service_start_alert(service_name, pid)
                
                # Detect service stop
                elif not is_running and previous_running:
                    await self._send_service_stop_alert(service_name, previous_pid)
                
                # Check for hangs using heartbeat
                if is_running:
                    await self._check_service_hang(service_name, config)
                
                # Update service state
                self.service_states[service_name] = {
                    'running': is_running,
                    'pid': pid,
                    'last_check': current_time,
                    'start_time': current_time if (is_running and not previous_running) else previous_state.get('start_time', current_time)
                }
                
        except Exception as e:
            logger.error(f"Error in service health check: {e}")
    
    async def _send_service_restart_alert(self, service_name: str, new_pid: int, old_pid: int):
        """Send alert when service restarts"""
        try:
            uptime = datetime.now() - datetime.fromtimestamp(self.service_states[service_name].get('start_time', time.time()))
            uptime_str = str(uptime).split('.')[0]
            
            message = f"""
🔄 <b>SERVICE RESTARTED</b>

🔧 Service: <b>{service_name.upper()}</b>
🆔 Old PID: {old_pid}
🆔 New PID: {new_pid}
⏱️  Previous Uptime: {uptime_str}
⏰ Restart Time: {datetime.now().strftime('%H:%M:%S')}

💡 Service automatically restarted by the system
"""
            
            await self.telegram.send_system_alert(message.strip(), "WARNING")
            logger.info(f"📡 Service restart alert sent for {service_name}")
        except Exception as e:
            logger.error(f"Failed to send restart alert for {service_name}: {e}")
    
    async def _send_service_start_alert(self, service_name: str, pid: int):
        """Send alert when service starts"""
        try:
            message = f"""
✅ <b>SERVICE STARTED</b>

🔧 Service: <b>{service_name.upper()}</b>
🆔 PID: {pid}
⏰ Start Time: {datetime.now().strftime('%H:%M:%S')}

🚀 Service is now online and operational
"""
            
            await self.telegram.send_system_alert(message.strip(), "SUCCESS")
            logger.info(f"📡 Service start alert sent for {service_name}")
        except Exception as e:
            logger.error(f"Failed to send start alert for {service_name}: {e}")
    
    async def _send_service_stop_alert(self, service_name: str, pid: int):
        """Send alert when service stops"""
        try:
            uptime = datetime.now() - datetime.fromtimestamp(self.service_states[service_name].get('start_time', time.time()))
            uptime_str = str(uptime).split('.')[0]
            
            message = f"""
🛑 <b>SERVICE STOPPED</b>

🔧 Service: <b>{service_name.upper()}</b>
🆔 PID: {pid}
⏱️  Uptime: {uptime_str}
⏰ Stop Time: {datetime.now().strftime('%H:%M:%S')}

⚠️ Service has gone offline
"""
            
            await self.telegram.send_system_alert(message.strip(), "ERROR")
            logger.info(f"📡 Service stop alert sent for {service_name}")
        except Exception as e:
            logger.error(f"Failed to send stop alert for {service_name}: {e}")
    
    async def _check_service_hang(self, service_name: str, config: Dict):
        """Check if service appears to be hanging"""
        try:
            heartbeat_key = config.get('heartbeat_key')
            hang_threshold = config.get('hang_threshold', 600)
            
            if not heartbeat_key:
                return
            
            # Get last heartbeat (supports wildcard keys)
            try:
                heartbeat_value = None
                if '*' in heartbeat_key:
                    # Grab the newest heartbeat among matching keys
                    latest_ts = 0
                    for key in self.redis_client.scan_iter(heartbeat_key):
                        try:
                            hb = self.redis_client.get(key)
                            if hb and hb.isdigit():
                                ts = int(hb)
                                if ts > latest_ts:
                                    latest_ts = ts
                        except Exception:
                            continue
                    if latest_ts:
                        heartbeat_value = latest_ts
                else:
                    heartbeat_value = self.redis_client.get(heartbeat_key)
                
                if heartbeat_value:
                    heartbeat_time = int(heartbeat_value) / 1000  # Convert from milliseconds
                    time_since_heartbeat = time.time() - heartbeat_time
                    
                    # Check if we've already alerted for this hang
                    last_hang_alert = self.service_states.get(service_name, {}).get('last_hang_alert', 0)
                    
                    if time_since_heartbeat > hang_threshold and (time.time() - last_hang_alert) > 1800:  # 30 min cooldown
                        await self._send_service_hang_alert(service_name, time_since_heartbeat)
                        self.service_states[service_name]['last_hang_alert'] = time.time()
                        
            except Exception as e:
                logger.debug(f"Error checking heartbeat for {service_name}: {e}")
                
        except Exception as e:
            logger.error(f"Error in hang detection for {service_name}: {e}")
    
    async def _send_service_hang_alert(self, service_name: str, time_since_heartbeat: float):
        """Send alert when service appears to be hanging"""
        try:
            hang_duration = str(timedelta(seconds=int(time_since_heartbeat))).split('.')[0]
            
            message = f"""
⚠️ <b>SERVICE HANG DETECTED</b>

🔧 Service: <b>{service_name.upper()}</b>
⏰ Last Heartbeat: {hang_duration} ago
🆔 PID: {self._get_service_pid(service_name)}
⏰ Detection Time: {datetime.now().strftime('%H:%M:%S')}

🚨 Service may be unresponsive or stuck
💡 Consider manual restart if issue persists
"""
            
            await self.telegram.send_system_alert(message.strip(), "CRITICAL")
            logger.warning(f"📡 Service hang alert sent for {service_name}")
        except Exception as e:
            logger.error(f"Failed to send hang alert for {service_name}: {e}")
    
    async def check_system_health(self):
        """Monitor overall system health"""
        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Check CPU
            if cpu_percent > self.cpu_threshold:
                await self._send_performance_alert("High CPU Usage", f"CPU usage at {cpu_percent:.1f}%", "WARNING")
            
            # Check Memory
            if memory.percent > self.memory_threshold:
                await self._send_performance_alert("High Memory Usage", f"Memory usage at {memory.percent:.1f}%", "WARNING")
            
            # Check Disk
            if disk.percent > self.disk_threshold:
                await self._send_performance_alert("High Disk Usage", f"Disk usage at {disk.percent:.1f}%", "WARNING")
                
        except Exception as e:
            logger.error(f"Error in system health check: {e}")
    
    async def _send_performance_alert(self, alert_type: str, message: str, severity: str):
        """Send performance-related alerts with throttling"""
        try:
            # Use the existing throttling mechanism in telegram_alerts
            full_message = f"""
📊 <b>SYSTEM PERFORMANCE ALERT</b>

⚠️ Issue: <b>{alert_type}</b>
📈 Details: {message}
⏰ Time: {datetime.now().strftime('%H:%M:%S')}

💡 Monitor system resources and consider optimization
"""
            
            await self.telegram.send_system_alert(full_message.strip(), severity)
        except Exception as e:
            logger.error(f"Failed to send performance alert: {e}")
    
    async def monitor_loop(self):
        """Main monitoring loop"""
        logger.info("🔍 Starting system monitoring loop...")
        
        # Send startup alert
        await self.send_system_startup_alert()
        
        try:
            while self.monitoring_active:
                # Authoritative trade execution alerts
                await self._process_executed_signals()
                await self._process_trader_claims()

                # Check service health every 30 seconds
                if int(time.time()) % 30 == 0:
                    await self.check_service_health()

                # Check system health every 2 minutes
                if int(time.time()) % 120 == 0:
                    await self.check_system_health()

                await asyncio.sleep(2)
                
        except KeyboardInterrupt:
            logger.info("🛑 Monitoring stopped by user")
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await self.safe_telegram_send('send_system_alert', f"System monitor encountered error: {str(e)}", "ERROR")
        finally:
            await self.send_system_shutdown_alert()
    
    def stop_monitoring(self):
        """Stop the monitoring loop"""
        self.monitoring_active = False

async def main():
    """Main function"""
    print("🔔 AI Trading System - Telegram Alert Monitor")
    print("=" * 50)
    
    monitor = SystemMonitor()
    
    try:
        await monitor.monitor_loop()
    except KeyboardInterrupt:
        print("\n🛑 Monitor stopped by user")
        monitor.stop_monitoring()
    except Exception as e:
        print(f"❌ Monitor error: {e}")
        await monitor.telegram.send_system_alert(f"System monitor crashed: {str(e)}", "CRITICAL")

if __name__ == "__main__":
    asyncio.run(main())