"""Binance WebSocket helper utilities for the trading system."""

from __future__ import annotations

import logging
import os
import threading
import time
import asyncio
import math
from typing import Any, Dict, List, Optional

try:
	from binance import ThreadedWebsocketManager
	from binance.client import Client
except ImportError:  # pragma: no cover - library is required at runtime
	ThreadedWebsocketManager = None  # type: ignore
	Client = None  # type: ignore

from utils.websocket_limits import WebSocketLimiter, WebSocketLimitConfig


def _resolve_symbols(symbols: List[str]) -> List[str]:
	env_syms = os.getenv("BINANCE_WS_SYMBOLS")
	if env_syms:
		parts = [s.strip().upper() for s in env_syms.split(",") if s.strip()]
		return parts if parts else symbols
	return symbols


class BinanceWebSocketHelper:
	"""Manage Binance futures mark price and account update websockets."""

	MARK_PRICE_UPDATE = "markPriceUpdate"
	ACCOUNT_UPDATE = "ACCOUNT_UPDATE"

	_MAX_WS_STREAMS = int(os.getenv("BINANCE_MAX_STREAMS", "1024"))
	_MAX_WS_CONNECTIONS = int(os.getenv("BINANCE_MAX_CONNECTIONS", "300"))
	_WS_CONNECTION_WINDOW_SECONDS = int(os.getenv("BINANCE_WS_CONNECTION_WINDOW_SECONDS", "300"))

	_WS_LIMITER = WebSocketLimiter(
		WebSocketLimitConfig(
			max_streams=_MAX_WS_STREAMS,
			max_connections=_MAX_WS_CONNECTIONS,
			window_seconds=_WS_CONNECTION_WINDOW_SECONDS,
		),
		logger=logging.getLogger(__name__),
	)

	def __init__(self, client: Client, symbols: List[str]):
		if ThreadedWebsocketManager is None:
			raise RuntimeError("python-binance ThreadedWebsocketManager not available")

		self._logger = logging.getLogger(__name__)
		self._client = client
		self._symbols = _resolve_symbols(symbols or [])

		self._twm: Optional[ThreadedWebsocketManager] = None
		self._listen_key: Optional[str] = None
		self._keepalive_thread: Optional[threading.Thread] = None
		self._reconnect_thread: Optional[threading.Thread] = None
		self._stop_event = threading.Event()

		self._mark_prices: Dict[str, float] = {}
		self._mark_lock = threading.Lock()

		self._positions: List[Dict[str, Any]] = []
		self._positions_lock = threading.Lock()
		self._positions_timestamp = 0.0
		
		# Error tracking for reconnection
		self._consecutive_errors = 0
		self._last_error_time = 0.0
		self._error_log_interval = 30.0  # Only log errors every 30 seconds
		self._reconnect_cooldown = 60.0  # Wait 60 seconds between reconnects
		self._last_reconnect_attempt = 0.0
		self._is_reconnecting = False

		self._start_streams()
		self._start_reconnect_monitor()

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------
	def get_mark_price(self, symbol: str) -> Optional[float]:
		with self._mark_lock:
			return self._mark_prices.get(symbol)

	def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
		with self._positions_lock:
			if symbol is None:
				return [dict(pos) for pos in self._positions]
			return [dict(pos) for pos in self._positions if pos.get("symbol") == symbol]

	def get_positions_timestamp(self) -> float:
		return self._positions_timestamp

	def update_mark_price_from_rest(self, symbol: str, price: float) -> None:
		with self._mark_lock:
			self._mark_prices[symbol] = price

	def update_positions_from_rest(self, positions: List[Dict[str, Any]]) -> None:
		with self._positions_lock:
			self._positions = [dict(pos) for pos in positions]
			self._positions_timestamp = time.time()

	def _seed_mark_prices_rest(self) -> None:
		"""Preload mark prices via REST to avoid empty values during websocket startup."""
		if not self._symbols:
			return
		connect_timeout = float(os.getenv("BINANCE_REST_SEED_CONNECT_TIMEOUT", "2.0"))
		read_timeout = float(os.getenv("BINANCE_REST_SEED_READ_TIMEOUT", "5.0"))
		max_retries = int(os.getenv("BINANCE_REST_SEED_RETRIES", "2"))
		backoff_sec = float(os.getenv("BINANCE_REST_SEED_BACKOFF_SEC", "0.4"))
		requests_params = {"timeout": (connect_timeout, read_timeout)}

		for sym in self._symbols:
			price = None
			for attempt in range(max_retries + 1):
				try:
					resp = self._client.futures_mark_price(symbol=sym, requests_params=requests_params)
					price = float(resp.get("markPrice")) if resp else None
					if price:
						self.update_mark_price_from_rest(sym, price)
						break
				except Exception as exc:
					if attempt >= max_retries:
						self._logger.warning(
							"REST seed mark price failed for %s after %s attempts: %s",
							sym,
							attempt + 1,
							exc,
						)
					else:
						time.sleep(backoff_sec * (attempt + 1))
			if not price:
				self._logger.debug("REST seed mark price missing for %s", sym)

	def _seed_positions_rest(self) -> None:
		"""Preload positions via REST so downstream has a baseline until user-data stream updates."""
		if os.getenv("BINANCE_WS_DISABLE_USER_DATA", "0").lower() in ("1", "true", "yes"):
			return
		try:
			account = self._client.futures_account()
			positions_payload = account.get("positions", []) if account else []
			parsed = []
			for raw in positions_payload:
				symbol = raw.get("symbol") or raw.get("s")
				if not symbol:
					continue
				parsed.append({
					"symbol": symbol,
					"positionSide": raw.get("positionSide", raw.get("ps", "BOTH")),
					"positionAmt": self._safe_float(raw.get("positionAmt", raw.get("pa"))),
					"entryPrice": self._safe_float(raw.get("entryPrice", raw.get("ep"))),
					"markPrice": self._safe_float(raw.get("markPrice", raw.get("mp"))),
					"unRealizedProfit": self._safe_float(raw.get("unRealizedProfit", raw.get("up"))),
					"leverage": self._safe_int(raw.get("leverage", raw.get("l"))),
					"marginType": raw.get("marginType", raw.get("mt", "CROSSED")),
					"isolatedMargin": self._safe_float(raw.get("isolatedMargin", raw.get("iw"))),
					"percentage": 0.0,
				})
			if parsed:
				self.update_positions_from_rest(parsed)
		except Exception:
			self._logger.debug("REST seed positions failed", exc_info=True)

	def _start_mark_price_streams(self) -> None:
		"""Start mark price streams with multiplex fallback and REST seeding for resilience."""
		# Use multiplex when many symbols to reduce connection count and avoid 502 from LB
		stream_count = len(self._symbols)
		use_multiplex = stream_count >= 5 and hasattr(self._twm, "start_futures_multiplex_socket")
		chunk_size_env = int(os.getenv("BINANCE_WS_CHUNK_SIZE", "0") or 0)
		chunk_count_env = int(os.getenv("BINANCE_WS_CHUNKS", "0") or 0)
		chunk_pace = float(os.getenv("BINANCE_WS_CHUNK_PACE_SEC", "1.0"))

		def _chunk(items: List[str]) -> List[List[str]]:
			if chunk_size_env > 0:
				sz = max(1, chunk_size_env)
			elif chunk_count_env > 0:
				sz = max(1, math.ceil(len(items) / chunk_count_env))
			else:
				sz = len(items)
			return [items[i:i + sz] for i in range(0, len(items), sz)]

		if use_multiplex:
			streams = [f"{sym.lower()}@markPrice@1s" for sym in self._symbols]
			stream_chunks = _chunk(streams)
			started = 0
			for idx, chunk in enumerate(stream_chunks, start=1):
				try:
					self._twm.start_futures_multiplex_socket(callback=self._handle_mark_price, streams=chunk)
					started += 1
					# pace chunk handshakes to stay under 300 connections/min bursts
					time.sleep(chunk_pace)
				except Exception as exc:
					self._logger.warning(
						"Multiplex mark price start failed for chunk %s/%s (size=%s): %s",
						idx,
						len(stream_chunks),
						len(chunk),
						exc,
						exc_info=True,
					)
			if started:
				self._backfill_missing_mark_prices()
				return
			# If no chunk succeeded, fall back to per-symbol below

		for symbol in self._symbols:
			# Retry mark-price subscription to ride out transient 5xx from Binance LB, with pacing
			for attempt in range(5):
				try:
					self._twm.start_symbol_mark_price_socket(
						callback=self._handle_mark_price,
						symbol=symbol.lower()
					)
					break
				except Exception as exc:  # pragma: no cover - network/runtime errors
					self._logger.warning(
						"Mark price stream start failed for %s (attempt %s/5): %s",
						symbol,
						attempt + 1,
						exc,
						exc_info=True,
					)
					time.sleep(0.8)
			else:
				# Seed from REST so downstream has a price even if websocket never connects
				try:
					resp = self._client.futures_mark_price(symbol=symbol)
					price = float(resp.get("markPrice")) if resp else None
					if price:
						self.update_mark_price_from_rest(symbol, price)
						self._logger.info("Seeded mark price via REST for %s after websocket retries", symbol)
				except Exception:
					self._logger.debug("Failed to seed mark price via REST for %s", symbol, exc_info=True)

			# Small pacing between symbols to avoid bursty websocket handshakes
			time.sleep(0.15)

		# After startup, fill any missing marks via REST to cover stubborn 502 cases
		self._backfill_missing_mark_prices()
		self._probe_missing_symbols()
		self._final_seed_missing_mark_prices()

	def _backfill_missing_mark_prices(self, delay: float = 2.0) -> None:
		"""Best-effort REST fetch for symbols that never produced a mark price."""
		try:
			time.sleep(delay)
			with self._mark_lock:
				missing = [s for s in self._symbols if s not in self._mark_prices]
			for sym in missing:
				try:
					resp = self._client.futures_mark_price(symbol=sym)
					price = float(resp.get("markPrice")) if resp else None
					if price:
						self.update_mark_price_from_rest(sym, price)
						self._logger.info("Backfilled mark price via REST for %s after websocket startup", sym)
				except Exception:
					self._logger.debug("Backfill REST mark price failed for %s", sym, exc_info=True)
		except Exception:
			self._logger.debug("Backfill mark price routine failed", exc_info=True)

	def _probe_missing_symbols(self) -> None:
		"""Optional targeted probe for stubborn symbols (e.g., BTCUSDT) with limited retries and REST fallback."""
		probe_syms_env = os.getenv("BINANCE_WS_PROBE_SYMBOLS", "BTCUSDT")
		probe_syms = [s.strip().upper() for s in probe_syms_env.split(",") if s.strip()]
		if not probe_syms:
			return
		with self._mark_lock:
			missing = [s for s in probe_syms if s not in self._mark_prices]
		if not missing:
			return
		retry_attempts = int(os.getenv("BINANCE_WS_PROBE_RETRIES", "2"))
		retry_delay = float(os.getenv("BINANCE_WS_PROBE_DELAY_SEC", "2.0"))
		for sym in missing:
			for attempt in range(retry_attempts):
				try:
					self._twm.start_symbol_mark_price_socket(callback=self._handle_mark_price, symbol=sym.lower())
					self._logger.warning("[WS-PROBE] Started probe socket for %s (attempt %s/%s)", sym, attempt + 1, retry_attempts)
					time.sleep(retry_delay)
					if self.get_mark_price(sym) is not None:
						break
				except Exception as exc:
					self._logger.warning("[WS-PROBE] Probe failed for %s (attempt %s/%s): %s", sym, attempt + 1, retry_attempts, exc, exc_info=True)
			# REST fallback if still missing
			if self.get_mark_price(sym) is None:
				try:
					resp = self._client.futures_mark_price(symbol=sym)
					price = float(resp.get("markPrice")) if resp else None
					if price:
						self.update_mark_price_from_rest(sym, price)
						self._logger.info("[WS-PROBE] Seeded %s via REST fallback after probe", sym)
				except Exception:
					self._logger.warning("[WS-PROBE] REST fallback failed for %s", sym, exc_info=True)
			if self.get_mark_price(sym) is None:
				self._logger.warning("[WS-PROBE] Still missing %s after probe and REST fallback", sym)

	def _final_seed_missing_mark_prices(self, attempts: int = 2, delay: float = 2.0) -> None:
		"""Last-chance REST seeding loop for any symbol still missing a mark price."""
		try:
			for i in range(max(1, attempts)):
				with self._mark_lock:
					missing = [s for s in self._symbols if s not in self._mark_prices]
				if not missing:
					return
				for sym in missing:
					try:
						resp = self._client.futures_mark_price(symbol=sym)
						price = float(resp.get("markPrice")) if resp else None
						if price:
							self.update_mark_price_from_rest(sym, price)
							self._logger.info("[WS-SEED] Final REST seed succeeded for %s (attempt %s/%s)", sym, i + 1, attempts)
						else:
							self._logger.warning("[WS-SEED] REST returned no price for %s (attempt %s/%s)", sym, i + 1, attempts)
					except Exception as exc:
						self._logger.warning("[WS-SEED] REST seed failed for %s (attempt %s/%s): %s", sym, i + 1, attempts, exc, exc_info=True)
				if i < attempts - 1:
					time.sleep(delay)
		except Exception:
			self._logger.debug("[WS-SEED] Final seed routine failed", exc_info=True)

	def stop(self) -> None:
		self._stop_event.set()
		if self._keepalive_thread and self._keepalive_thread.is_alive():
			self._keepalive_thread.join(timeout=1)
		if self._twm:
			try:
				self._twm.stop()
			except Exception:  # pragma: no cover - defensive cleanup
				self._logger.debug("Failed to stop ThreadedWebsocketManager", exc_info=True)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------
	def _start_streams(self) -> None:
		self._WS_LIMITER.validate_stream_count(len(self._symbols), context="mark_price")

		# Ensure a fresh event loop to avoid "loop already running" errors in some hosts
		try:
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)
		except Exception:
			pass

		try:
			self._WS_LIMITER.acquire_sync()
			self._twm = ThreadedWebsocketManager(
				api_key=self._client.API_KEY,
				api_secret=self._client.API_SECRET
			)
			self._twm.start()
		except Exception as exc:
			raise RuntimeError(f"Failed to start Binance websocket manager: {exc}") from exc

		# Seed mark prices and positions via REST in a background thread so startup never blocks
		def _seed_rest_async() -> None:
			try:
				self._seed_mark_prices_rest()
				self._seed_positions_rest()
			except Exception:
				self._logger.debug("[WS-SEED] Seed thread failed", exc_info=True)

		threading.Thread(target=_seed_rest_async, daemon=True).start()

		self._start_mark_price_streams()

		# Start futures user data stream for position updates when available (can be disabled via env)
		if os.getenv("BINANCE_WS_DISABLE_USER_DATA", "0").lower() not in ("1", "true", "yes"):
			try:
				self._listen_key = self._client.futures_stream_get_listen_key()
				self._twm.start_futures_user_socket(callback=self._handle_user_data)
				self._keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
				self._keepalive_thread.start()
			except Exception:
				self._logger.debug("Failed to start futures user data stream", exc_info=True)

	def _keepalive_loop(self) -> None:
		while not self._stop_event.is_set() and self._listen_key:
			try:
				time.sleep(30 * 60)  # 30 minutes per Binance documentation
				self._client.futures_stream_keepalive(self._listen_key)
			except Exception:
				self._logger.debug("Failed to keep listen key alive", exc_info=True)

	def _start_reconnect_monitor(self) -> None:
		"""Start a background thread that monitors WebSocket health and reconnects if needed."""
		def monitor_loop():
			while not self._stop_event.is_set():
				try:
					time.sleep(30)  # Check every 30 seconds
					
					# Check if mark prices are stale (no update in 60 seconds)
					now = time.time()
					price_stale = False
					with self._mark_lock:
						# If we have symbols but no prices, or if we detect connection issues
						if self._symbols and not self._mark_prices:
							price_stale = True
					
					# Check consecutive error count
					if self._consecutive_errors > 100 and not self._is_reconnecting:
						# Too many errors, attempt reconnection
						if now - self._last_reconnect_attempt > self._reconnect_cooldown:
							self._logger.warning(
								"[WS-MONITOR] Detected %d consecutive errors, attempting reconnect",
								self._consecutive_errors
							)
							self._attempt_reconnect()
					
				except Exception as e:
					self._logger.debug("[WS-MONITOR] Monitor loop error: %s", e)
		
		self._reconnect_thread = threading.Thread(target=monitor_loop, daemon=True)
		self._reconnect_thread.start()

	def _attempt_reconnect(self) -> None:
		"""Attempt to reconnect WebSocket streams."""
		if self._is_reconnecting:
			return
		
		self._is_reconnecting = True
		self._last_reconnect_attempt = time.time()
		
		try:
			self._logger.info("[WS-RECONNECT] Stopping old WebSocket manager...")
			
			# Stop old TWM
			if self._twm:
				try:
					self._twm.stop()
				except Exception:
					pass
				self._twm = None
			
			# Reset error counter
			self._consecutive_errors = 0
			
			# Wait a bit before reconnecting
			time.sleep(5)
			
			if self._stop_event.is_set():
				return
			
			self._logger.info("[WS-RECONNECT] Starting new WebSocket manager...")
			
			# Create new event loop
			try:
				loop = asyncio.new_event_loop()
				asyncio.set_event_loop(loop)
			except Exception:
				pass
			
			# Start new TWM
			self._WS_LIMITER.acquire_sync()
			self._twm = ThreadedWebsocketManager(
				api_key=self._client.API_KEY,
				api_secret=self._client.API_SECRET
			)
			self._twm.start()
			
			# Seed and restart streams
			self._seed_mark_prices_rest()
			self._seed_positions_rest()
			self._start_mark_price_streams()
			
			# Restart user data stream
			if os.getenv("BINANCE_WS_DISABLE_USER_DATA", "0").lower() not in ("1", "true", "yes"):
				try:
					self._listen_key = self._client.futures_stream_get_listen_key()
					self._twm.start_futures_user_socket(callback=self._handle_user_data)
				except Exception:
					self._logger.debug("[WS-RECONNECT] Failed to restart user data stream", exc_info=True)
			
			self._logger.info("[WS-RECONNECT] WebSocket reconnection successful!")
			
		except Exception as e:
			self._logger.error("[WS-RECONNECT] Reconnection failed: %s", e)
		finally:
			self._is_reconnecting = False

	# ------------------------------------------------------------------
	# Websocket callbacks
	# ------------------------------------------------------------------
	def _handle_mark_price(self, message: Dict[str, Any]) -> None:
		data = message.get("data", message)

		event_type = data.get("e")
		if event_type == "error":
			# Track consecutive errors and rate-limit logging
			self._consecutive_errors += 1
			now = time.time()
			if now - self._last_error_time > self._error_log_interval:
				self._logger.warning(
					"[WS-ERROR] Mark price stream error (consecutive=%d): %s",
					self._consecutive_errors, str(data)[:200]
				)
				self._last_error_time = now
			return

		# Reset error counter on successful message
		self._consecutive_errors = 0

		symbol = data.get("s") or data.get("symbol")
		if not symbol:
			return

		price_str = data.get("p") or data.get("markPrice") or data.get("P")
		try:
			price = float(price_str)
		except (TypeError, ValueError):
			return

		with self._mark_lock:
			self._mark_prices[symbol] = price

		with self._positions_lock:
			for position in self._positions:
				if position.get("symbol") == symbol:
					position["markPrice"] = price

	def _handle_user_data(self, message: Dict[str, Any]) -> None:
		data = message.get("data", message)
		event_type = data.get("e")
		
		# Handle error events
		if event_type == "error":
			self._consecutive_errors += 1
			now = time.time()
			if now - self._last_error_time > self._error_log_interval:
				self._logger.warning(
					"[WS-ERROR] User data stream error (consecutive=%d): %s",
					self._consecutive_errors, str(data)[:200]
				)
				self._last_error_time = now
			return

		if event_type != self.ACCOUNT_UPDATE:
			return
		
		# Reset error counter on successful message
		self._consecutive_errors = 0

		account_data = data.get("a", {})
		positions_payload = account_data.get("P", [])

		# CRITICAL FIX: Binance ACCOUNT_UPDATE sends ONLY changed positions, not all positions.
		# We must MERGE the delta into existing positions, not replace entirely.
		if not positions_payload:
			return

		with self._positions_lock:
			# Build lookup for existing positions: key = (symbol, positionSide)
			existing_map: Dict[tuple, Dict[str, Any]] = {}
			for pos in self._positions:
				key = (pos.get("symbol"), pos.get("positionSide", "BOTH"))
				existing_map[key] = pos

			# Merge incoming deltas
			for raw in positions_payload:
				symbol = raw.get("s")
				if not symbol:
					continue

				position_side = raw.get("ps", "BOTH")
				position_amt = self._safe_float(raw.get("pa"))
				key = (symbol, position_side)

				if abs(position_amt) > 0:
					# Position still open - update or add
					existing_map[key] = {
						"symbol": symbol,
						"positionSide": position_side,
						"positionAmt": position_amt,
						"entryPrice": self._safe_float(raw.get("ep")),
						"markPrice": self._safe_float(raw.get("mp")) or self._safe_float(raw.get("ep")),
						"unRealizedProfit": self._safe_float(raw.get("up")),
						"leverage": self._safe_int(raw.get("l")),
						"marginType": raw.get("mt", "CROSSED"),
						"isolatedMargin": self._safe_float(raw.get("iw")),
						"percentage": 0.0,
					}
				else:
					# Position closed - remove from map
					existing_map.pop(key, None)

			# Rebuild list from merged map
			self._positions = list(existing_map.values())
			self._positions_timestamp = time.time()

	# ------------------------------------------------------------------
	# Static helpers
	# ------------------------------------------------------------------
	@staticmethod
	def _safe_float(value: Any) -> float:
		try:
			return float(value)
		except (TypeError, ValueError):
			return 0.0

	@staticmethod
	def _safe_int(value: Any) -> int:
		try:
			return int(float(value))
		except (TypeError, ValueError):
			return 0


__all__ = ["BinanceWebSocketHelper"]
